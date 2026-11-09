"""Le LLM rédige le bilan à partir des seuls chiffres du modèle ; une vérification rejette ce qui n'en vient pas."""
import json
import os
import re
from pathlib import Path

import httpx
from dotenv import load_dotenv
from openai import OpenAI

MENTION = "Il s'agit d'actes déclarés ; prévision indicative, à valider par l'analyste."
ERREURS = {
    "chiffre_invente": "Le texte contient un chiffre absent des données du modèle.",
    "pdq_inconnu": "Le texte cite un PDQ qui n'est pas dans la prévision.",
    "hausses_absentes": "Le texte ne nomme pas les PDQ en plus forte hausse.",
    "mention_absente": "La mention « actes déclarés ; prévision indicative » manque.",
    "trop_long": "Le texte dépasse 5 phrases.",
}


def donnees(cible, tableau, marge, version, derniere_connue):
    """Le seul contenu que le LLM reçoit : un JSON construit par l'application."""
    ligne = lambda r: {"pdq": r.PDQ, "prevision": r.prevision, "normale": r.normale, "ecart": r.ecart}
    return {
        "semaine_predite": cible.date().isoformat(),
        "derniere_semaine_connue": derniere_connue.date().isoformat(),
        "marge_erreur_typique_actes_par_pdq": marge,
        "hausses": [ligne(r) for r in tableau[tableau["ecart"] > 0].head(3).itertuples()],
        "baisses": [ligne(r) for r in tableau[tableau["ecart"] < 0].tail(3).iloc[::-1].itertuples()],
        "total_prevu": round(float(tableau["prevision"].sum()), 1),
        "total_normale": round(float(tableau["normale"].sum()), 1),
        "modele": version,
    }


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


def _nombres_autorises(d):
    valeurs = {d["marge_erreur_typique_actes_par_pdq"], d["total_prevu"], d["total_normale"]}
    for r in d["hausses"] + d["baisses"]:
        valeurs |= {float(r["pdq"]), r["prevision"], r["normale"], r["ecart"], abs(r["ecart"])}
    for cle in ["semaine_predite", "derniere_semaine_connue"]:
        valeurs |= {float(x) for x in d[cle].split("-")}
    return valeurs


def verifier(texte, d, pdq_connus):
    """Liste des codes d'erreur (vide = texte accepté)."""
    erreurs = []
    sans_dates = re.sub(r"\d{4}-\d{2}-\d{2}", " ", texte)
    autorises = _nombres_autorises(d)
    for n in re.findall(r"\d+(?:,\d+|\.\d+)?", sans_dates):
        x = float(n.replace(",", "."))
        if not any(abs(x - a) < 0.051 or x == round(a) for a in autorises):
            erreurs.append("chiffre_invente")
            break
    cites = {int(n) for groupe in re.findall(r"PDQ\s*(\d+(?:\s*(?:,|et|ou)\s*\d+)*)", texte)
             for n in re.findall(r"\d+", groupe)}
    if cites - {int(p) for p in pdq_connus}:
        erreurs.append("pdq_inconnu")
    if not {int(r["pdq"]) for r in d["hausses"]} <= cites:
        erreurs.append("hausses_absentes")
    if "actes déclarés" not in texte or "à valider par l'analyste" not in texte.replace("’", "'"):
        erreurs.append("mention_absente")
    if len([p for p in re.split(r"[.!?»](?:\s|$)", texte) if p.strip()]) > 5:
        erreurs.append("trop_long")
    return erreurs
