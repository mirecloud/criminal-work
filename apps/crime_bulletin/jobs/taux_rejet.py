"""Mesure du taux de rejet du LLM : un bilan par semaine rejouée, vérifié par les mêmes contrôles que l'API.

Usage (depuis la racine du projet, LLM configuré dans .env) :
    uv run python apps/crime_bulletin/jobs/taux_rejet.py --semaines 20
Écrit artifacts/taux_rejet/bilans.csv (un bilan par ligne) et resume.json.
"""
import argparse
import json
import sys
import time
from collections import Counter
from pathlib import Path

RACINE = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(RACINE / "apps" / "crime_bulletin" / "shared"))
import bulletin as B  # noqa: E402
import prediction as P  # noqa: E402

parser = argparse.ArgumentParser()
parser.add_argument("--semaines", type=int, default=20, help="nombre de semaines rejouées, les plus récentes")
args = parser.parse_args()

manquantes = B.variables_manquantes()
if manquantes:
    sys.exit(f"LLM non configuré : {', '.join(manquantes)}")

m = P.Prevision()
instructions = (RACINE / "apps" / "crime_bulletin" / "prompts" / "instructions.txt").read_text(encoding="utf-8")
llm = B.client()
lignes = []
for semaine in m.semaines_disponibles()[-args.semaines:]:
    cible, tableau = m.prevoir(semaine)
    d = B.donnees(cible, tableau, m.marge_90, m.version, semaine)
    debut = time.perf_counter()
    try:
        texte = B.rediger(d, instructions, llm=llm)
    except Exception as erreur:  # une panne n'est pas un rejet : on la compte à part
        lignes.append({"semaine_predite": d["semaine_predite"], "statut": "indisponible", "erreurs": type(erreur).__name__,
                       "secondes": round(time.perf_counter() - debut, 1), "texte": ""})
        continue
    erreurs = B.verifier(texte, d, tableau["PDQ"])
    lignes.append({"semaine_predite": d["semaine_predite"], "statut": "rejete" if erreurs else "accepte",
                   "erreurs": " ".join(erreurs), "secondes": round(time.perf_counter() - debut, 1), "texte": texte})
    print(lignes[-1]["semaine_predite"], lignes[-1]["statut"], lignes[-1]["erreurs"], flush=True)

repondus = [l for l in lignes if l["statut"] != "indisponible"]
resume = {
    "modele": m.version,
    "semaines": len(lignes),
    "repondus": len(repondus),
    "rejetes": sum(l["statut"] == "rejete" for l in repondus),
    "taux_rejet": round(sum(l["statut"] == "rejete" for l in repondus) / len(repondus), 3) if repondus else None,
    "erreurs": dict(Counter(e for l in repondus for e in l["erreurs"].split())),
    "secondes_mediane": sorted(l["secondes"] for l in repondus)[len(repondus) // 2] if repondus else None,
}
sortie = RACINE / "artifacts" / "taux_rejet"
sortie.mkdir(parents=True, exist_ok=True)
P.pd.DataFrame(lignes).to_csv(sortie / "bilans.csv", index=False)
(sortie / "resume.json").write_text(json.dumps(resume, ensure_ascii=False, indent=2), encoding="utf-8")
print(json.dumps(resume, ensure_ascii=False))
