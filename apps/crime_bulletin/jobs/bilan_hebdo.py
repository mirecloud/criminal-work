"""Tâche du lundi : demander le bilan de la dernière semaine consolidée et dire s'il passe les contrôles.

Une ligne JSON par exécution, lisible dans `kubectl logs`. Code de sortie :
0 = bilan accepté, 1 = bilan rejeté par les contrôles, 2 = API ou LLM indisponible.
Compter les codes 1 sur plusieurs semaines donne le taux de rejet du LLM.
"""
import json
import os
import sys

import httpx

API = os.getenv("CRIME_API_URL", "http://crime-api")

try:
    # timeout large : le client LLM de l'API réessaie, un bilan peut prendre ~3 min
    with httpx.Client(base_url=API, timeout=240) as http:
        semaines = http.get("/semaines").raise_for_status().json()
        reponse = http.post("/bilan", json={"derniere_connue": semaines[-1]}).raise_for_status().json()
except httpx.HTTPError as erreur:
    print(json.dumps({"statut": "indisponible", "erreur": str(erreur)}, ensure_ascii=False), flush=True)
    sys.exit(2)

print(json.dumps({"statut": "accepte" if reponse["accepte"] else "rejete",
                  "semaine_predite": reponse["semaine_predite"], "erreurs": reponse["erreurs"],
                  "modele": reponse["modele"], "llm": reponse["llm"], "secondes": reponse["secondes"]},
                 ensure_ascii=False), flush=True)
sys.exit(0 if reponse["accepte"] else 1)
