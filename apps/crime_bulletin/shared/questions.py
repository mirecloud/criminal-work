"""Questions de l'analyste sur la prévision de la semaine : le LLM ne répond qu'à partir du JSON de l'application."""
import json
import os
import re

import bulletin as B

ERREURS = {
    "chiffre_invente": "La réponse contient un chiffre absent des données de la semaine : à vérifier dans le tableau.",
    "pdq_inconnu": "La réponse cite un PDQ qui n'est pas dans la prévision.",
    "trop_long": "La réponse dépasse 6 phrases.",
    "hors_sujet": "La réponse ne porte pas sur la prévision de la semaine.",
}
REFUS = "Ces données ne permettent pas de répondre."
SUJET = re.compile(r"PDQ|normale|prévision|prévu|écart|seuil|modèle|consolidé|erreur|actes", re.IGNORECASE)


def donnees(cible, tableau, derniere_connue, marge, marge_90, seuil, fenetre, version):
    """Tout ce que le LLM peut savoir : les chiffres de chaque PDQ pour la semaine affichée, rien d'autre."""
    reel_connu = bool(tableau["reel"].notna().all())

    def ligne(r):
        lecture = "sous le seuil" if abs(r.ecart) < seuil else "hausse notable" if r.ecart > 0 else "baisse notable"
        d = {"pdq": r.PDQ, "prevision": r.prevision, "normale": r.normale, "ecart": r.ecart, "lecture": lecture}
        if reel_connu:
            d |= {"reel": int(r.reel), "erreur": round(float(r.reel) - r.prevision, 1)}
        return d

    lignes = [ligne(r) for r in tableau.itertuples()]
    # Le LLM classe mal une longue liste : l'application le fait pour lui.
    classement = {"plus_fortes_previsions": sorted(lignes, key=lambda x: -x["prevision"])[:3]}
    if reel_connu:
        classement["plus_grandes_erreurs"] = sorted(lignes, key=lambda x: -abs(x["erreur"]))[:3]
    return {
        "semaine_predite": cible.date().isoformat(),
        "derniere_semaine_connue": derniere_connue.date().isoformat(),
        "reel_connu": reel_connu,
        "nombre_de_pdq": len(lignes),
        "total_prevu": round(float(tableau["prevision"].sum()), 1),
        "total_normale": round(float(tableau["normale"].sum()), 1),
        "nombre_hausses_notables": sum(x["lecture"] == "hausse notable" for x in lignes),
        "nombre_baisses_notables": sum(x["lecture"] == "baisse notable" for x in lignes),
        "seuil_ecart_notable_actes": seuil,
        "erreur_moyenne_actes_par_pdq": marge,
        "erreur_depassee_une_fois_sur_dix": marge_90,
        "semaines_dans_la_normale": fenetre,
        "modele": version,
        **classement,
        "pdq": lignes,
    }


def repondre(question, d, instructions, llm=None, modele=None):
    llm = llm or B.client()
    reponse = llm.chat.completions.create(
        model=modele or os.environ["AI_MODEL"],
        messages=[{"role": "system", "content": instructions},
                  {"role": "user", "content": "Données fournies par l'application (JSON) :\n" + json.dumps(d, ensure_ascii=False)
                                              + "\n\nQuestion de l'analyste :\n" + question}],
        temperature=0, max_tokens=500,
        extra_body={"chat_template_kwargs": {"enable_thinking": False}},
    )
    return reponse.choices[0].message.content.strip()


def _nombres(texte):
    return {float(n.replace(",", ".")) for n in re.findall(r"\d+(?:[.,]\d+)?", texte)}


def verifier(texte, d, question, instructions, pdq_connus):
    """Codes d'erreur (vide = réponse acceptée). Un chiffre est admis s'il vient des données, de la question ou de la méthode."""
    erreurs = []
    # Le nom du modèle contient une empreinte hexadécimale : ses chiffres ne sont pas des données.
    autorises = _nombres(json.dumps({**d, "modele": ""})) | _nombres(question) | _nombres(instructions)
    if any(not any(abs(x - a) < 0.051 for a in autorises) for x in _nombres(texte)):
        erreurs.append("chiffre_invente")
    cites = {int(n) for groupe in re.findall(r"PDQ\s*(\d+(?:\s*(?:,|et|ou)\s*\d+)*)", texte)
             for n in re.findall(r"\d+", groupe)}
    if cites - {int(p) for p in pdq_connus}:
        erreurs.append("pdq_inconnu")
    if REFUS.rstrip(".") not in texte and not SUJET.search(texte):
        erreurs.append("hors_sujet")
    if len([p for p in re.split(r"[.!?»](?:\s|$)", texte) if p.strip()]) > 6:
        erreurs.append("trop_long")
    return erreurs
