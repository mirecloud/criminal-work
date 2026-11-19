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
| Taux de rejet du LLM | 1 bilan sur 30 (3,3 %), semaines rejouées jusqu'au 23 novembre 2026 |
| Données | Fichier du portail du 18 novembre 2026, consolidé jusqu'à la semaine du 26 octobre |

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
  jobs/bilan_hebdo.py      Tâche du lundi : demande le bilan et dit s'il passe les contrôles.
  jobs/taux_rejet.py       Mesure du taux de rejet du LLM sur des semaines rejouées.
  jobs/prompt_eng/         Gabarits utilisés pendant la mise au point du prompt.
  deploy/docker/           Dockerfiles de l'API et de l'interface, dépendances figées.
  deploy/k8s/              Manifestes Kubernetes (namespace ml510 sur le k3d du homelab).
livrables/                 Présentation PowerPoint.
tests/                     Tests pytest (contrôle du bilan, API avec un LLM simulé).
.github/workflows/ci.yml   CI : tests et image de l'interface à chaque push.
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
LLM_API_KEY=<clé, ou « aucune » si le vLLM n'en exige pas>
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

## Tests

```bash
uv run pytest
```

Les tests du contrôle du bilan tournent partout. Ceux de l'API chargent le vrai modèle et simulent le LLM : ils ont besoin des artefacts des notebooks et sont sautés en CI, où ces artefacts n'existent pas.

Pour mesurer le taux de rejet du LLM sur les 30 dernières semaines rejouées (résultats dans `artifacts/taux_rejet/`) :

```bash
uv run python apps/crime_bulletin/jobs/taux_rejet.py --semaines 30
```

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
| `GET /health/live`, `GET /health/ready` | Santé du service ; *ready* vérifie que le modèle est chargé et liste les variables du LLM manquantes. |
| `GET /semaines` | Semaines disponibles. |
| `GET /prevision` | Prévision, normale et écart par PDQ pour une semaine. |
| `GET /historique` | Courbe réel / prévu d'un PDQ. |
| `POST /bilan` | Bilan rédigé par le LLM, puis vérifié. |
| `POST /question` | Question libre sur les chiffres de la semaine. |

## Déploiement sur le homelab (k3d)

Deux images : l'API embarque le code, les consignes du LLM et les artefacts des notebooks 00 et 04 (un tag = une paire code + données). L'interface n'embarque que Streamlit et n'appelle que l'API. Le `.env` n'entre jamais dans une image (voir `.dockerignore`).

Construisez les images depuis la racine, après avoir exécuté les notebooks, puis poussez-les sur Docker Hub (`docker login -u mirecloud` une fois avant) :

```bash
docker build -f apps/crime_bulletin/deploy/docker/Dockerfile.api -t mirecloud/crime-api:1.3.0 .
docker build -f apps/crime_bulletin/deploy/docker/Dockerfile.ui -t mirecloud/crime-ui:1.0.0 .
docker push mirecloud/crime-api:1.3.0
docker push mirecloud/crime-ui:1.0.0
```

Pointez `kubectl` sur le cluster k3d, sans changer votre contexte par défaut :

```bash
export KUBECONFIG=$(k3d kubeconfig write ml520)
```

Créez le namespace, le certificat de l'autorité mirecloud et, seulement si besoin, la clé du LLM (le ConfigMap met « aucune » par défaut) et l'identifiant Docker Hub (dépôt privé). Ces objets ne sont pas dans le dépôt :

```bash
kubectl apply -f apps/crime_bulletin/deploy/k8s/00-namespace.yaml
kubectl -n ml510 create configmap crime-llm-ca --from-file=ca.crt=<chemin>/mirecloud-ca.crt
kubectl -n ml510 create secret generic crime-llm --from-literal=LLM_API_KEY='<clé>'
kubectl -n ml510 create secret docker-registry dockerhub --docker-username=mirecloud --docker-password='<token>'
```

Appliquez le reste et ouvrez l'interface :

```bash
kubectl apply -f apps/crime_bulletin/deploy/k8s/
kubectl -n ml510 rollout status deploy/crime-api
kubectl -n ml510 port-forward svc/crime-ui 8501:80
```

| Fichier | Contenu |
|---|---|
| `10-config.yaml` | Modèle, URL et clé factice du LLM (non secrets). |
| `20-api.yaml` | API, 2 réplicas. Le pod ne reçoit du trafic qu'une fois le modèle chargé (`/health/ready`). |
| `30-ui.yaml` | Interface, 1 réplica (la session Streamlit vit dans le pod). |
| `40-ingress.yaml` | Entrée Traefik `crimes.localhost` vers l'interface ; l'API reste interne. |
| `50-cronjob-bilan.yaml` | Chaque lundi 07:00 UTC, bilan de la dernière semaine. Le statut (accepté ou rejeté) est dans le log ; un Job en échec signale une panne. Un an d'historique est gardé. |
| `60-networkpolicy.yaml` | Seuls les pods du namespace `ml510` peuvent appeler l'API. |

Tous les pods tournent sans privilèges : utilisateur non root, profil seccomp par défaut, aucune capacité Linux, système de fichiers en lecture seule (sauf `/tmp`).

Pour une nouvelle version du modèle : relancer les notebooks, construire un nouveau tag, le changer dans `20-api.yaml` et `50-cronjob-bilan.yaml`, puis `kubectl apply`.

## Méthode

- **Contrat de prévision.** On ne prédit qu'à partir de semaines consolidées, donc 4 semaines à l'avance.
- **Évaluation.** Origine glissante : le modèle est réentraîné chaque 1er janvier. La règle de choix a été fixée avant la comparaison : meilleure MAE sur 2019–2023, parmi les candidats sans biais de plus de 2 actes sur aucun PDQ. La période 2024–2026 avait déjà été consultée ; elle sert de diagnostic, pas de test indépendant.
- **Candidats.** Les candidats sont `moy_12`, `mix_4_12`, `ridge_residu`, `ridge_hybride`, `ridge_local` et `boosting_hist`. Le boosting a la plus faible MAE, mais il est exclu : il biaise le PDQ 26 de 2,7 actes. Le modèle par PDQ (`ridge_local`) perd nettement sur 2019–2023 ; son avantage sur 2024–2026 n'est pas significatif. Il reste donc un challenger.
- **LLM.** L'application construit un JSON (prévisions, normales, hausses, marge), et le LLM le traite comme des données. Il écrit à température 0, sans mode « réflexion ». La marge donnée est le quantile à 90 % de l'erreur (« dans 9 cas sur 10, l'erreur reste sous 10 actes »), pas l'erreur moyenne. Le texte est rejeté s'il contient un chiffre absent du JSON, un chiffre attribué au mauvais PDQ, un nombre d'actes écrit en lettres, un PDQ inconnu, une hausse omise, une mention obligatoire manquante, ou plus de 4 phrases.

## Limites

- Le modèle n'est pas un outil d'alerte. Seulement 48 alertes de hausse sur 2024–2026, dont un tiers fausses.
- Les chiffres reflètent les déclarations : orienter les patrouilles d'après ces chiffres peut augmenter les déclarations là où on patrouille déjà.
- Le taux de rejet (3,3 %) est mesuré sur 30 semaines seulement ; le CronJob l'enrichit chaque lundi. Les contrôles ne vérifient pas le sens des phrases : un texte qui se contredit sans erreur de chiffre passe.
- Le rafraîchissement des données reste manuel : télécharger le CSV, relancer les notebooks, construire un nouveau tag.
- Aucune donnée personnelle n'est utilisée : seulement des comptes par PDQ et par semaine.
