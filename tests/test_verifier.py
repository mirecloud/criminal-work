"""Le contrôle du bilan : chaque règle a un texte qui passe et un texte qui doit être rejeté."""
import bulletin as B
import pytest

D = {
    "semaine_predite": "2026-11-23",
    "derniere_semaine_connue": "2026-10-26",
    "erreur_max_9_fois_sur_10_actes_par_pdq": 10.0,
    "hausses": [{"pdq": "7", "prevision": 30.1, "normale": 26.0, "ecart": 4.1},
                {"pdq": "12", "prevision": 18.4, "normale": 16.9, "ecart": 1.5}],
    "baisses": [{"pdq": "20", "prevision": 40.2, "normale": 44.0, "ecart": -3.8}],
    "total_prevu": 558.0,
    "total_normale": 608.0,
    "modele": "ridge_residu-test",
}
PDQ = ["7", "12", "20", "21", "38"]
MARGE = "Dans 9 cas sur 10, l'erreur reste sous 10,0 actes par PDQ."
BON = ("Pour la semaine du 23 novembre, le modèle prévoit les plus fortes hausses au PDQ 7 (30,1 actes contre une "
       "normale de 26,0) et au PDQ 12 (18,4 contre 16,9). La plus forte baisse est attendue au PDQ 20. "
       f"{MARGE} {B.MENTION}")


def test_texte_conforme_accepte():
    assert B.verifier(BON, D, PDQ) == []


def test_liste_de_pdq_sans_chiffres_acceptee():
    texte = BON.replace("au PDQ 20.", "aux PDQ 20 et 12.")
    assert B.verifier(texte, D, PDQ) == []


def test_chiffre_invente():
    assert "chiffre_invente" in B.verifier(BON.replace("30,1", "33,3"), D, PDQ)


def test_chiffres_inverses_entre_deux_pdq():
    # Chaque chiffre existe dans le JSON, mais pas pour ce PDQ : l'ancien contrôle laissait passer ce texte.
    texte = BON.replace("(30,1 actes contre une normale de 26,0)", "(18,4 actes contre une normale de 16,9)") \
               .replace("(18,4 contre 16,9)", "(30,1 contre 26,0)")
    assert B.verifier(texte, D, PDQ) == ["chiffre_mal_attribue"]


def test_chiffre_en_lettres():
    texte = BON.replace("La plus forte baisse", "Le total baisse de cinquante actes. La plus forte baisse")
    assert "chiffre_en_lettres" in B.verifier(texte, D, PDQ)


def test_pdq_inconnu_et_hausse_absente():
    texte = BON.replace("PDQ 12", "PDQ 99")
    assert {"pdq_inconnu", "hausses_absentes"} <= set(B.verifier(texte, D, PDQ))


def test_mention_absente():
    assert "mention_absente" in B.verifier(BON.replace(B.MENTION, ""), D, PDQ)


@pytest.mark.parametrize("ajout, attendu", [("", []), ("Le total prévu est de 558,0 actes. ", ["trop_long"])])
def test_quatre_phrases_au_plus(ajout, attendu):
    texte = BON.replace(MARGE, ajout + MARGE)
    assert B.verifier(texte, D, PDQ) == attendu


def test_marge_a_90_pourcent_dans_les_donnees():
    import pandas as pd
    tableau = pd.DataFrame({"PDQ": ["7", "20"], "prevision": [30.1, 40.2], "normale": [26.0, 44.0], "ecart": [4.1, -3.8]})
    d = B.donnees(pd.Timestamp("2026-11-23"), tableau, 10.0, "v", pd.Timestamp("2026-10-26"))
    assert d["erreur_max_9_fois_sur_10_actes_par_pdq"] == 10.0
    assert [r["pdq"] for r in d["hausses"]] == ["7"] and [r["pdq"] for r in d["baisses"]] == ["20"]
