# Bilan hebdomadaire des PDQ — projet intégrateur ML510

Ce projet prévoit, chaque semaine, le nombre d'actes criminels déclarés dans chacun des 29 postes de quartier (PDQ) actifs de Montréal. Un modèle de langage (LLM) rédige ensuite un court bilan à partir de ces prévisions, et l'application vérifie ce texte avant de l'afficher.

Les données sont les [actes criminels](https://donnees.montreal.ca/dataset/actes-criminels) du portail de données ouvertes de Montréal (2015 → 2026). Ce sont des actes **déclarés**, pas des crimes commis.

## Résultat en bref

| | |
|---|---|
| Unité de prévision | 1 PDQ × 1 semaine (lundi → dimanche) |
| Horizon | 4 semaines, car les 14 derniers jours du fichier sont sous-déclarés |
| Modèle retenu | `ridge_residu` : la normale `moy_12` corrigée par une Ridge sur les écarts récents |
| Erreur (MAE), choix 2019–2023 | 4,78 actes par PDQ, contre 5,04 pour la normale seule |
| Erreur (MAE), diagnostic 2024–2026 | 4,68 actes, contre 4,94 |
| Gain sur la normale | 0,26 acte, IC 95 % [0,12 ; 0,39] (bootstrap par blocs de 8 semaines) |
| LLM | Qwen3-14B (AWQ) servi par vLLM, adapté par le prompt seulement |

Le modèle estime bien le **niveau** de chaque PDQ. Il n'est pas encore fiable pour **alerter** sur une hausse : à cette échelle, une hausse de 5 actes relève surtout du bruit hebdomadaire.

## Structure

```
configs/crimes.toml        Tous les réglages (dates, horizon, règle de choix). On les modifie ici, jamais dans les notebooks.
Data/                      Placer actes-criminels.csv ici (non versionné).
notebooks/
  00_start_here.ipynb      Construction du panel PDQ × semaine.
  01_regression_lineaire   Premières références et régression linéaire.
  02_arbres                Arbres et boosting, sans historique.
  03_historique            Contrat v2 : variables retardées (lag_4, lag_5, lag_52, moy_4, moy_12).
  04_comparaison           Origine glissante, 6 candidats, choix du modèle servi.
artifacts/                 Résultats produits par les notebooks (non versionné).
apps/crime_bulletin/
  shared/                  Logique : prediction.py (modèle), bulletin.py (LLM + contrôles), questions.py.
  api/app.py               API FastAPI.
  ui/                      Interface Streamlit (app.py, carte.py, contours des PDQ).
  prompts/                 Consignes données au LLM.
  jobs/prompt_eng/         Gabarits utilisés pendant la mise au point du prompt.
  deploy/k8s/              Réservé au déploiement (pas encore fait).
livrables/                 Présentation PowerPoint.
```

## Installation

Il faut Python ≥ 3.12 et [uv](https://docs.astral.sh/uv/).

```bash
uv sync
```

Téléchargez `actes-criminels.csv` depuis le portail et placez-le dans `Data/`.

Créez un fichier `.env` à la racine. Il n'est jamais versionné.

```
AI_MODEL=<nom du modèle servi par vLLM>
LLM_BASE_URL=<URL de l'API compatible OpenAI>
LLM_API_KEY=<clé>
LLM_CA_FILE=<certificat CA, optionnel>
```

## Reproduire les résultats

Exécutez les notebooks dans l'ordre. Chacun lit les artefacts du précédent.

```bash
for nb in 00_start_here 01_regression_lineaire 02_arbres 03_historique 04_comparaison; do
  uv run jupyter nbconvert --to notebook --execute --inplace notebooks/$nb.ipynb
done
```

Le notebook 04 écrit `artifacts/04_comparaison/modele.joblib` et sa fiche `meta.json`. L'API refuse de démarrer si les deux ne correspondent pas.

## Lancer l'application

Dans un premier terminal, lancez l'API :

```bash
uv run uvicorn app:app --app-dir apps/crime_bulletin/api --port 8000
```

Dans un second terminal, lancez l'interface, depuis la racine pour qu'elle prenne le thème de `.streamlit/` :

```bash
uv run streamlit run apps/crime_bulletin/ui/app.py
```

L'interface appelle l'API à l'adresse `CRIME_API_URL` (par défaut `http://127.0.0.1:8000`).

### Routes de l'API

| Route | Rôle |
|---|---|
| `GET /health/live`, `GET /health/ready` | Santé du service ; *ready* vérifie que le modèle est chargé. |
| `GET /semaines` | Semaines disponibles. |
| `GET /prevision` | Prévision, normale et écart par PDQ pour une semaine. |
| `GET /historique` | Courbe réel / prévu d'un PDQ. |
| `POST /bilan` | Bilan rédigé par le LLM, puis vérifié. |
| `POST /question` | Question libre sur les chiffres de la semaine. |

## Méthode

- **Contrat de prévision.** On ne prédit qu'à partir de semaines consolidées, donc 4 semaines à l'avance.
- **Évaluation.** Origine glissante : le modèle est réentraîné chaque 1er janvier. La règle de choix a été fixée avant la comparaison : meilleure MAE sur 2019–2023, parmi les candidats sans biais de plus de 2 actes sur aucun PDQ. La période 2024–2026 avait déjà été consultée ; elle sert de diagnostic, pas de test indépendant.
- **Candidats.** Les candidats sont `moy_12`, `mix_4_12`, `ridge_residu`, `ridge_hybride`, `ridge_local` et `boosting_hist`. Le boosting a la plus faible MAE, mais il est exclu : il biaise le PDQ 26 de 2,7 actes. Le modèle par PDQ (`ridge_local`) perd nettement sur 2019–2023 ; son avantage sur 2024–2026 n'est pas significatif. Il reste donc un challenger.
- **LLM.** L'application construit un JSON (prévisions, normales, hausses, marge), et le LLM le traite comme des données. Il écrit à température 0, sans mode « réflexion ». Le texte est rejeté s'il contient un chiffre absent du JSON, un PDQ inconnu, une hausse omise, une mention obligatoire manquante, ou s'il est trop long.

## Limites

- Le modèle n'est pas un outil d'alerte. Seulement 48 alertes de hausse sur 2024–2026, dont un tiers fausses.
- Les chiffres reflètent les déclarations : orienter les patrouilles d'après ces chiffres peut augmenter les déclarations là où on patrouille déjà.
- La qualité des bilans du LLM n'a pas encore été mesurée, en particulier le taux de rejet par les contrôles.
- Le déploiement (conteneurs, k3d, tâche planifiée chaque lundi) est planifié mais pas encore réalisé.
- Aucune donnée personnelle n'est utilisée : seulement des comptes par PDQ et par semaine.
