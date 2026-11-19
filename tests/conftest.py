"""Rend importables les modules de l'application (shared/ et api/), comme le fait api/app.py."""
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
APP = RACINE / "apps" / "crime_bulletin"
for dossier in [APP / "shared", APP / "api", APP / "jobs"]:
    sys.path.insert(0, str(dossier))

# Les tests qui chargent le modèle ont besoin des artefacts des notebooks (non versionnés) : en CI, ils sont sautés.
ARTEFACTS = RACINE / "artifacts" / "04_comparaison" / "modele.joblib"
