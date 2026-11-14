"""Carte des PDQ : la prévision de la semaine posée sur les territoires officiels (aucun fond de carte externe)."""
import json
from pathlib import Path

import altair as alt

LIMITES = Path(__file__).resolve().parent / "assets" / "limites-pdq.geojson"
HAUSSE, BAISSE, SOUS_SEUIL = "Hausse notable", "Baisse notable", "Sous le seuil"
TEINTES = {HAUSSE: "#f87171", BAISSE: "#2dd4bf", SOUS_SEUIL: "#64748b"}
ECART, NIVEAU = "Écart à la normale", "Niveau prévu"
FOND, ENCRE = "#0b1020", "#e2e8f0"


def lecture(ecart, seuil):
    """La même règle que le graphique des écarts : sous le seuil, on ne parle ni de hausse ni de baisse."""
    return SOUS_SEUIL if abs(ecart) < seuil else HAUSSE if ecart > 0 else BAISSE


def limites():
    return json.loads(LIMITES.read_text(encoding="utf-8"))


def carte(tableau, seuil, mode=ECART, geo=None, hauteur=620):
    """Renvoie (graphique, PDQ sans territoire). `tableau` : colonnes pdq, prevision, normale, ecart."""
    geo = geo or limites()
    lignes = {r.pdq: r for r in tableau.itertuples()}
    territoires = []
    for f in geo["features"]:
        r = lignes.get(f["properties"]["pdq"])
        if r is None:
            continue
        territoires.append({**f, "properties": {**f["properties"], "prevision": r.prevision, "normale": r.normale,
                                                "ecart": r.ecart, "lecture": lecture(r.ecart, seuil)}})
    sans_territoire = sorted(set(lignes) - {f["properties"]["pdq"] for f in territoires}, key=int)

    if mode == NIVEAU:
        couleur = alt.Color("properties.prevision:Q", title="Actes prévus",
                            scale=alt.Scale(range=["#1e1b4b", "#4338ca", "#a5b4fc"], domainMin=0),
                            legend=alt.Legend(orient="top-left", direction="horizontal", gradientLength=180))
    else:
        couleur = alt.Color("properties.lecture:N", scale=alt.Scale(domain=list(TEINTES), range=list(TEINTES.values())),
                            legend=alt.Legend(title=None, orient="top-left"))
    # Les limites sont déjà projetées (MTM zone 8, mètres) : on les dessine telles quelles, le nord en haut.
    projection = dict(type="identity", reflectY=True)
    donnees = alt.Data(values=territoires)
    formes = alt.Chart(donnees).mark_geoshape(stroke=FOND, strokeWidth=2).encode(
        color=couleur,
        tooltip=[alt.Tooltip("properties.pdq:N", title="PDQ"), alt.Tooltip("properties.prevision:Q", title="Prévu"),
                 alt.Tooltip("properties.normale:Q", title="Normale"),
                 alt.Tooltip("properties.ecart:Q", title="Écart", format="+.1f"),
                 alt.Tooltip("properties.lecture:N", title="Lecture")])
    position = dict(longitude="properties.cx:Q", latitude="properties.cy:Q", text="properties.pdq:N")
    # Un halo sombre sous chaque numéro : lisible sur un territoire clair comme sur un territoire foncé.
    halo = alt.Chart(donnees).mark_text(fontSize=11, fontWeight="bold", color=FOND, stroke=FOND, strokeWidth=3,
                                        strokeOpacity=0.6).encode(**position)
    numeros = alt.Chart(donnees).mark_text(fontSize=11, fontWeight="bold", color=ENCRE).encode(**position)
    return (formes + halo + numeros).project(**projection).properties(height=hauteur), sans_territoire
