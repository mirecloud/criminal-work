"""Interface de l'analyste (Mirecloud) : elle ne parle qu'à l'API, jamais directement au modèle ni au LLM."""
import html
import os
from pathlib import Path

import altair as alt
import httpx
import pandas as pd
import streamlit as st

API = os.getenv("CRIME_API_URL", "http://127.0.0.1:8000")
ASSETS = Path(__file__).resolve().parent / "assets"
api = httpx.Client(base_url=API, timeout=90)

st.set_page_config(page_title="Mirecloud · Bilan des PDQ", page_icon=str(ASSETS / "mirecloud-icone.svg"), layout="wide")
st.logo(str(ASSETS / "mirecloud-clair.svg"), icon_image=str(ASSETS / "mirecloud-icone.svg"), size="large")

st.markdown("""
<style>
  .block-container {padding-top: 2rem; max-width: 1280px;}
  .hero {background: radial-gradient(circle at 85% 20%, rgba(56,189,248,.35), transparent 45%),
                     linear-gradient(120deg, #0b1020 0%, #1e1b4b 55%, #4338ca 100%);
         color: #fff; border: 1px solid #2e3561; border-radius: 18px; padding: 28px 32px; margin-bottom: 22px;
         box-shadow: 0 0 0 1px rgba(129,140,248,.08), 0 18px 40px rgba(0,0,0,.45);}
  .hero h1 {color: #fff; font-size: 2rem; margin: 0 0 4px 0; padding: 0;}
  .hero p {color: #a5b4fc; margin: 0;}
  .pill {display: inline-block; padding: 3px 12px; border-radius: 999px; font-size: .78rem; font-weight: 600;
         margin-bottom: 10px; letter-spacing: .02em;}
  .pill.prevision {background: rgba(56,189,248,.15); color: #7dd3fc; border: 1px solid rgba(56,189,248,.45);}
  .pill.rejeu {background: rgba(251,191,36,.12); color: #fcd34d; border: 1px solid rgba(251,191,36,.45);}
  .kpis {display: grid; grid-template-columns: repeat(4, 1fr); gap: 16px; margin-bottom: 8px;}
  .kpi {background: linear-gradient(180deg, #141a2e 0%, #10152a 100%); border: 1px solid #232b45;
        border-radius: 14px; padding: 16px 18px; box-shadow: 0 8px 24px rgba(0,0,0,.35);}
  .kpi .label {color: #8b93b0; font-size: .78rem; text-transform: uppercase; letter-spacing: .06em;}
  .kpi .value {font-size: 1.75rem; font-weight: 700; color: #f1f5f9; margin-top: 4px;}
  .kpi .sub {font-size: .85rem; color: #8b93b0;}
  .up {color: #f87171 !important;} .down {color: #2dd4bf !important;}
  .bilan {background: #141a2e; border: 1px solid #232b45; border-left: 4px solid #818cf8; border-radius: 14px;
          padding: 20px 24px; font-size: 1.05rem; line-height: 1.7; color: #e2e8f0;
          box-shadow: 0 8px 24px rgba(0,0,0,.35);}
  .statut {display: inline-flex; align-items: center; gap: 8px; padding: 6px 14px; border-radius: 999px;
           font-weight: 600; font-size: .9rem; margin-bottom: 12px;}
  .statut.ok {background: rgba(34,197,94,.12); color: #4ade80; border: 1px solid rgba(34,197,94,.4);}
  .statut.ko {background: rgba(239,68,68,.12); color: #f87171; border: 1px solid rgba(239,68,68,.4);}
  .pied {color: #5b6382; font-size: .8rem; text-align: center; margin-top: 36px;}
  @media (max-width: 900px) {.kpis {grid-template-columns: repeat(2, 1fr);}}
</style>
""", unsafe_allow_html=True)


@st.cache_data(ttl=300)
def lire(route, **params):
    r = api.get(route, params=params)
    r.raise_for_status()
    return r.json()


MOIS = ["janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août",
        "septembre", "octobre", "novembre", "décembre"]


def date_fr(iso):
    d = pd.Timestamp(iso)
    return f"{d.day} {MOIS[d.month - 1]} {d.year}"


def kpi(label, valeur, sous="", classe=""):
    return (f'<div class="kpi"><div class="label">{label}</div>'
            f'<div class="value {classe}">{valeur}</div><div class="sub">{sous}</div></div>')


# --- Barre latérale ------------------------------------------------------------------------
with st.sidebar:
    st.markdown("### Bilan hebdomadaire")
    st.caption("Postes de quartier de Montréal · actes criminels déclarés")
    try:
        etat = lire("/health/ready")
    except httpx.HTTPError:
        st.error(f"API injoignable ({API}).")
        st.stop()
    st.success("Service prêt", icon="🟢")
    semaines = lire("/semaines")[::-1]
    choix = st.selectbox("Dimanche (dernière semaine consolidée)", semaines, index=0,
                         help="Le premier choix correspond à ce dimanche ; les autres rejouent un dimanche passé.")
    st.caption("La semaine prédite commence 4 semaines après la dernière semaine consolidée "
               "(14 jours de latence de déclaration + âge de l'extrait).")
    st.divider()
    st.caption(f"Modèle · `{etat['modele']}`")

prev = lire("/prevision", derniere_connue=choix)
tableau = pd.DataFrame(prev["lignes"])
passe = bool(tableau["reel"].notna().all())
total, normale = tableau["prevision"].sum(), tableau["normale"].sum()

# --- En-tête -----------------------------------------------------------------------------
pastille = '<span class="pill rejeu">DIMANCHE REJOUÉ · réel connu</span>' if passe else \
           '<span class="pill prevision">PRÉVISION · réel inconnu</span>'
st.markdown(f"""<div class="hero">{pastille}
  <h1>Semaine du {date_fr(prev['semaine_predite'])}</h1>
  <p>Données consolidées jusqu'à la semaine du {date_fr(prev['derniere_semaine_connue'])} · 29 postes de quartier</p></div>""",
            unsafe_allow_html=True)

ecart_total = total - normale
cartes = [
    kpi("Total prévu", f"{total:.0f}", "actes déclarés, 29 PDQ"),
    kpi("Écart à la normale", f"{ecart_total:+.0f}", "par rapport aux 12 dernières semaines",
        "up" if ecart_total > 0 else "down"),
    kpi("Marge typique", f"± {prev['marge']}", "actes par PDQ (mesurée au test)"),
]
if passe:
    erreur = (tableau["prevision"] - tableau["reel"]).abs().mean()
    cartes.append(kpi("Erreur réelle", f"{erreur:.1f}", "actes par PDQ cette semaine",
                      "up" if erreur > prev["marge"] else "down"))
else:
    cartes.append(kpi("PDQ en hausse", f"{int((tableau['ecart'] > 0).sum())}", "au-dessus de leur normale"))
st.markdown(f'<div class="kpis">{"".join(cartes)}</div>', unsafe_allow_html=True)

onglet_bilan, onglet_graphe, onglet_tableau, onglet_limites = st.tabs(
    ["📝  Bilan rédigé", "📊  Écarts par PDQ", "📋  Tableau", "ℹ️  Méthode et limites"])

# --- Bilan rédigé par le LLM -----------------------------------------------------------------
with onglet_bilan:
    st.write("Le LLM rédige le bilan **uniquement** à partir des chiffres du modèle ; "
             "un contrôle automatique vérifie chaque chiffre et chaque PDQ cité.")
    if st.button("✨  Rédiger le bilan", type="primary"):
        with st.spinner("Rédaction en cours…"):
            r = api.post("/bilan", json={"derniere_connue": choix})
        if r.status_code != 200:
            st.error(r.json().get("detail", "Erreur du service."))
        else:
            b = r.json()
            statut = ('<div class="statut ok">✅ Contrôle réussi : chiffres et PDQ issus du modèle</div>' if b["accepte"]
                      else '<div class="statut ko">❌ Contrôle échoué : ne pas utiliser ce texte tel quel</div>')
            st.markdown(statut + f'<div class="bilan">{html.escape(b["texte"])}</div>', unsafe_allow_html=True)
            for m in b["messages"]:
                st.warning(m)
            st.caption(f"Rédigé en {b['secondes']} s · LLM `{b['llm']}` · modèle `{b['modele']}`")

# --- Graphique ---------------------------------------------------------------------------------
with onglet_graphe:
    g = tableau.assign(sens=lambda t: t["ecart"].map(lambda e: "Hausse" if e > 0 else "Baisse"))
    barres = alt.Chart(g).mark_bar(cornerRadiusEnd=4).encode(
        x=alt.X("ecart:Q", title="Écart prévu à la normale (actes)"),
        y=alt.Y("pdq:N", sort="-x", title="PDQ"),
        color=alt.Color("sens:N", scale=alt.Scale(domain=["Hausse", "Baisse"], range=["#f87171", "#2dd4bf"]),
                        legend=alt.Legend(title=None, orient="top")),
        tooltip=[alt.Tooltip("pdq:N", title="PDQ"), alt.Tooltip("prevision:Q", title="Prévu"),
                 alt.Tooltip("normale:Q", title="Normale"), alt.Tooltip("ecart:Q", title="Écart")],
    ).properties(height=640)
    st.altair_chart(barres, width="stretch")

# --- Tableau -----------------------------------------------------------------------------------
with onglet_tableau:
    colonnes = {"pdq": "PDQ", "prevision": "Prévu", "normale": "Normale", "ecart": "Écart", "reel": "Réel"}
    affiche = tableau.rename(columns=colonnes)
    if not passe:
        affiche = affiche.drop(columns="Réel")
    st.dataframe(affiche, hide_index=True, width="stretch", height=560,
                 column_config={"Écart": st.column_config.NumberColumn(format="%+.1f"),
                                "Prévu": st.column_config.ProgressColumn(format="%.1f", min_value=0,
                                                                        max_value=float(tableau["prevision"].max()))})

# --- Méthode et limites ----------------------------------------------------------------------
with onglet_limites:
    gauche, droite = st.columns(2)
    gauche.markdown(
        "#### Comment c'est calculé\n"
        "1. **Normale** : moyenne des 12 dernières semaines consolidées du PDQ.\n"
        "2. **Modèle ML** (notebook 04) : un Ridge apprend de combien corriger la normale, à partir de la tendance "
        "récente (4 semaines), de la dernière semaine connue, de la même semaine l'an passé et du mois. "
        "Prévision = normale + correction.\n"
        "3. **LLM** (Qwen3-14B, homelab) : rédige à partir d'un JSON de chiffres, sans accès aux données.\n"
        "4. **Contrôle** : règles fixes (chiffres, PDQ, mention obligatoire, longueur).")
    droite.markdown(
        "#### Limites connues\n"
        "- **Actes déclarés**, pas crimes commis ; les 14 derniers jours sont exclus.\n"
        f"- Erreur typique de ± {prev['marge']} actes par PDQ et par semaine (rejeu rétrospectif 2024–2026) : "
        "un écart plus petit que cette marge n'est pas une vraie hausse.\n"
        "- Le modèle prévoit un **niveau**, il ne détecte pas les pics ponctuels.\n"
        "- Un changement brusque n'entre dans la normale qu'après 4 semaines.\n"
        "- Aucun événement (fête, météo, opération policière) n'est connu du modèle.")

st.markdown('<div class="pied">Mirecloud · Projet intégrateur ML510 · Polytechnique Montréal · '
            'prévision indicative, à valider par l\'analyste</div>', unsafe_allow_html=True)