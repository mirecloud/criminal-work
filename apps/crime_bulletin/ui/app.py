"""Interface de l'analyste : elle ne parle qu'à l'API (jamais directement au modèle ni au LLM)."""
import os

import httpx
import pandas as pd
import streamlit as st

API = os.getenv("CRIME_API_URL", "http://127.0.0.1:8000")
api = httpx.Client(base_url=API, timeout=90)

st.set_page_config(page_title="Bilan hebdomadaire des PDQ", page_icon="📋", layout="wide")


@st.cache_data(ttl=300)
def lire(route, **params):
    r = api.get(route, params=params)
    r.raise_for_status()
    return r.json()


# --- Barre latérale : état du service et choix du dimanche -------------------------------
with st.sidebar:
    st.title("📋 Bilan hebdomadaire")
    st.caption("Postes de quartier de Montréal · actes criminels déclarés")
    try:
        etat = lire("/health/ready")
    except httpx.HTTPError:
        st.error(f"API injoignable ({API}).")
        st.stop()
    st.success(f"Service prêt · modèle `{etat['modele']}`")
    semaines = lire("/semaines")[::-1]
    choix = st.selectbox("Dernière semaine consolidée", semaines, index=0,
                         help="Le premier choix correspond à ce dimanche. Les autres rejouent un dimanche passé.")
    st.caption("Le modèle prédit la semaine qui commence 4 semaines après la dernière semaine consolidée "
               "(latence de déclaration de 14 jours + âge de l'extrait).")

prev = lire("/prevision", derniere_connue=choix)
tableau = pd.DataFrame(prev["lignes"])
passe = tableau["reel"].notna().all()

st.header(f"Semaine du {prev['semaine_predite']}")
st.caption(f"Données consolidées jusqu'à la semaine du {prev['derniere_semaine_connue']} · "
           f"{'dimanche rejoué : le réel est connu' if passe else 'prévision : le réel est encore inconnu'}")

col1, col2, col3 = st.columns(3)
col1.metric("Total prévu (29 PDQ)", f"{tableau['prevision'].sum():.0f} actes",
            f"{tableau['prevision'].sum() - tableau['normale'].sum():+.0f} vs normale")
col2.metric("Marge d'erreur typique", f"± {prev['marge']} actes par PDQ")
if passe:
    col3.metric("Erreur réelle cette semaine", f"{(tableau['prevision'] - tableau['reel']).abs().mean():.1f} actes par PDQ")
else:
    col3.metric("PDQ au-dessus de leur normale", int((tableau["ecart"] > 0).sum()))

# --- Le bilan rédigé par le LLM ------------------------------------------------------------
st.subheader("Bilan rédigé")
if st.button("Rédiger le bilan", type="primary"):
    with st.spinner("Le LLM rédige à partir des chiffres du modèle…"):
        r = api.post("/bilan", json={"derniere_connue": choix})
    if r.status_code != 200:
        st.error(r.json().get("detail", "Erreur du service."))
    else:
        b = r.json()
        if b["accepte"]:
            st.success("Contrôle réussi : chaque chiffre et chaque PDQ viennent du modèle.", icon="✅")
        else:
            st.error("Contrôle échoué : ce texte ne doit pas être utilisé tel quel.", icon="❌")
            for m in b["messages"]:
                st.write(f"- {m}")
        st.info(b["texte"])
        with st.expander("Détails techniques"):
            st.json({k: b[k] for k in ["modele", "llm", "secondes", "erreurs"]})

# --- Tableau et graphique -----------------------------------------------------------------
st.subheader("Prévision par PDQ (écart à la normale des 12 dernières semaines)")
gauche, droite = st.columns([3, 2])
graphe = tableau.set_index("pdq")[["ecart"]].rename(columns={"ecart": "Écart prévu (actes)"})
gauche.bar_chart(graphe, horizontal=True, sort=False, height=620)
colonnes = {"pdq": "PDQ", "prevision": "Prévu", "normale": "Normale", "ecart": "Écart", "reel": "Réel"}
affiche = tableau.rename(columns=colonnes)
if not passe:
    affiche = affiche.drop(columns="Réel")
droite.dataframe(affiche, hide_index=True, height=620)

with st.expander("Limites connues (notebook 03)"):
    st.markdown(
        "- **Actes déclarés**, pas crimes commis ; les 14 derniers jours sont sous-déclarés et exclus.\n"
        f"- Erreur typique de ± {prev['marge']} actes par PDQ et par semaine, mesurée sur 2024–2026.\n"
        "- **PDQ 21** : le modèle le sous-estime (biais de +9,4 actes au test) depuis la fermeture du PDQ 22 ; "
        "une forte baisse annoncée pour ce PDQ n'est pas fiable.\n"
        "- Aucun événement (fête, météo, opération policière) n'est connu du modèle."
    )