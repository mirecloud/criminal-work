"""Le LLM rédige le bilan à partir des seuls chiffres du modèle ; une vérification rejette ce qui n'en vient pas."""
import json
import os
import re
from pathlib import Path

import httpx
from dotenv import load_dotenv
from openai import OpenAI

MENTION = "Il s'agit d'actes déclarés ; prévision indicative, à valider par l'analyste."
PHRASES_MAX = 4
VARIABLES_LLM = ["AI_MODEL", "LLM_BASE_URL", "LLM_API_KEY"]
ERREURS = {
    "chiffre_invente": "Le texte contient un chiffre absent des données du modèle.",
    "chiffre_mal_attribue": "Le texte attribue à un PDQ un chiffre qui appartient à un autre PDQ.",
    "chiffre_en_lettres": "Le texte écrit un nombre d'actes en lettres : il ne peut pas être vérifié.",
    "pdq_inconnu": "Le texte cite un PDQ qui n'est pas dans la prévision.",
    "hausses_absentes": "Le texte ne nomme pas les PDQ en plus forte hausse.",
    "mention_absente": "La mention « actes déclarés ; prévision indicative » manque.",
    "trop_long": f"Le texte dépasse {PHRASES_MAX} phrases.",
}
# Nombres en lettres suivis d'« acte(s) » : « trois actes » échapperait au contrôle des chiffres.
EN_LETTRES = re.compile(
    r"\b(?:deux|trois|quatre|cinq|six|sept|huit|neuf|dix|onze|douze|treize|quatorze|quinze|seize|vingt|trente|"
    r"quarante|cinquante|soixante|cent)(?:[\s-]+\w+)?\s+actes?\b", re.IGNORECASE)
NOMBRE = r"\d+(?:,\d+|\.\d+)?"


def donnees(cible, tableau, marge_90, version, derniere_connue):
    """Le seul contenu que le LLM reçoit : un JSON construit par l'application."""
    ligne = lambda r: {"pdq": r.PDQ, "prevision": r.prevision, "normale": r.normale, "ecart": r.ecart}
    return {
        "semaine_predite": cible.date().isoformat(),
        "derniere_semaine_connue": derniere_connue.date().isoformat(),
        # Quantile à 90 % de l'erreur absolue (rejeu 2024–2026) : une vraie plage, pas l'erreur moyenne.
        "erreur_max_9_fois_sur_10_actes_par_pdq": marge_90,
        "hausses": [ligne(r) for r in tableau[tableau["ecart"] > 0].head(3).itertuples()],
        "baisses": [ligne(r) for r in tableau[tableau["ecart"] < 0].tail(3).iloc[::-1].itertuples()],
        "total_prevu": round(float(tableau["prevision"].sum()), 1),
        "total_normale": round(float(tableau["normale"].sum()), 1),
        "modele": version,
    }


def variables_manquantes():
    """Les variables d'environnement du LLM qui manquent (liste vide = configuration complète)."""
    load_dotenv(override=False)
    return [v for v in VARIABLES_LLM if not os.getenv(v)]


def client():
    """Client OpenAI pointé sur le vLLM du homelab ; le certificat CA est optionnel (inutile dans le cluster)."""
    load_dotenv(override=False)
    ca = os.getenv("LLM_CA_FILE")
    return OpenAI(base_url=os.environ["LLM_BASE_URL"], api_key=os.environ["LLM_API_KEY"],
                  http_client=httpx.Client(verify=ca if ca else True, timeout=60))


def rediger(d, instructions, llm=None, modele=None):
    llm = llm or client()
    reponse = llm.chat.completions.create(
        model=modele or os.environ["AI_MODEL"],
        messages=[{"role": "system", "content": instructions},
                  {"role": "user", "content": "Données fournies par l'application (JSON) :\n" + json.dumps(d, ensure_ascii=False)}],
        temperature=0, max_tokens=400,
        extra_body={"chat_template_kwargs": {"enable_thinking": False}},
    )
    return reponse.choices[0].message.content.strip()


def _proche(x, valeurs):
    return any(abs(x - a) < 0.051 or x == round(a) for a in valeurs)


def _valeurs_par_pdq(d):
    """Pour chaque PDQ de hausses/baisses : les seuls chiffres qu'on peut écrire à côté de son numéro."""
    return {int(r["pdq"]): {r["prevision"], r["normale"], r["ecart"], abs(r["ecart"])} for r in d["hausses"] + d["baisses"]}


def _valeurs_globales(d):
    """Les chiffres qui ne dépendent d'aucun PDQ : marge, totaux, dates, et « 9 fois sur 10 »."""
    valeurs = {d["erreur_max_9_fois_sur_10_actes_par_pdq"], d["total_prevu"], d["total_normale"], 9.0, 10.0}
    for cle in ["semaine_predite", "derniere_semaine_connue"]:
        valeurs |= {float(x) for x in d[cle].split("-")}
    return valeurs


def _phrases(texte):
    return [p for p in re.split(r"[.!?»](?:\s|$)", texte) if p.strip()]


def _attribution(phrase, par_pdq, globales):
    """Vrai si un chiffre de PDQ est écrit après le numéro d'un AUTRE PDQ dans la même phrase.

    Le PDQ courant est le dernier nommé seul (« au PDQ 7 (30,1 actes… ») ; après une liste
    (« aux PDQ 20 et 15 ») on ne sait pas à qui va le chiffre, et on ne juge pas.
    """
    courant = None
    for m in re.finditer(rf"PDQ\s*(\d+(?:\s*(?:,|et|ou)\s*\d+)*)|({NOMBRE})", phrase):
        if m.group(1):
            numeros = re.findall(r"\d+", m.group(1))
            courant = int(numeros[0]) if len(numeros) == 1 else None
            continue
        x = float(m.group(2).replace(",", "."))
        if courant is None or _proche(x, globales) or _proche(x, par_pdq.get(courant, set())):
            continue
        if any(_proche(x, v) for q, v in par_pdq.items() if q != courant):
            return True
    return False


def verifier(texte, d, pdq_connus):
    """Liste des codes d'erreur (vide = texte accepté)."""
    erreurs = []
    sans_dates = re.sub(r"\d{4}-\d{2}-\d{2}", " ", texte)
    par_pdq, globales = _valeurs_par_pdq(d), _valeurs_globales(d)
    autorises = globales | set(map(float, par_pdq)) | set().union(*par_pdq.values())
    if any(not _proche(float(n.replace(",", ".")), autorises) for n in re.findall(NOMBRE, sans_dates)):
        erreurs.append("chiffre_invente")
    if any(_attribution(p, par_pdq, globales) for p in _phrases(sans_dates)):
        erreurs.append("chiffre_mal_attribue")
    if EN_LETTRES.search(texte):
        erreurs.append("chiffre_en_lettres")
    cites = {int(n) for groupe in re.findall(r"PDQ\s*(\d+(?:\s*(?:,|et|ou)\s*\d+)*)", texte)
             for n in re.findall(r"\d+", groupe)}
    if cites - {int(p) for p in pdq_connus}:
        erreurs.append("pdq_inconnu")
    if not {int(r["pdq"]) for r in d["hausses"]} <= cites:
        erreurs.append("hausses_absentes")
    if "actes déclarés" not in texte or "à valider par l'analyste" not in texte.replace("’", "'"):
        erreurs.append("mention_absente")
    if len(_phrases(texte)) > PHRASES_MAX:
        erreurs.append("trop_long")
    return erreurs
