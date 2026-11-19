"""Tâche du lundi : demander le bilan de la dernière semaine consolidée et dire s'il passe les contrôles.

Une ligne JSON par exécution, lisible dans `kubectl logs`, avec "statut" = accepte | rejete | indisponible.
Code de sortie : 0 = le service a répondu (bilan accepté OU rejeté), 1 = panne (API, LLM ou configuration).
Un rejet n'est pas une panne : c'est une mesure. Compter les "rejete" sur plusieurs lundis donne le taux de rejet.
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
    detail = erreur.response.text[:300] if isinstance(erreur, httpx.HTTPStatusError) else str(erreur)
    print(json.dumps({"statut": "indisponible", "erreur": detail}, ensure_ascii=False), flush=True)
    sys.exit(1)

print(json.dumps({"statut": "accepte" if reponse["accepte"] else "rejete",
                  "semaine_predite": reponse["semaine_predite"], "erreurs": reponse["erreurs"],
                  "modele": reponse["modele"], "llm": reponse["llm"], "secondes": reponse["secondes"]},
                 ensure_ascii=False), flush=True)
sys.exit(0)
