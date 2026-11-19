"""Le contrôle des réponses aux questions : poli avec l'analyste, strict sur le sujet et les chiffres."""
import questions as Q

D = {"semaine_predite": "2026-11-23", "derniere_semaine_connue": "2026-10-26", "modele": "ridge_residu-b7c5",
     "pdq": [{"pdq": "1", "prevision": 5.4, "normale": 6.8, "ecart": -1.4, "lecture": "sous le seuil"}]}
PDQ = ["1", "7"]
CONSIGNE = "Réponds en 2 phrases au plus."


def controle(texte, question="salut"):
    return Q.verifier(texte, D, question, CONSIGNE, PDQ)


def test_salutation_polie_acceptee():
    texte = ("Bonjour ! Je peux répondre à vos questions sur la prévision de la semaine affichée : PDQ, normale, "
             "écarts et marge d'erreur.")
    assert controle(texte) == []


def test_reponse_sur_la_semaine_acceptee():
    # Faux rejet observé en production : « semaine » ne faisait pas partie du sujet.
    assert controle("Pour la semaine du 23 novembre 2026.", "pour quelle semaine") == []


def test_refus_standard_accepte():
    assert controle(Q.REFUS, "écris un poème") == []


def test_hors_sujet_rejete():
    assert controle("Voici un poème sur la neige qui tombe sur la ville.", "écris un poème") == ["hors_sujet"]


def test_chiffre_invente_rejete():
    assert "chiffre_invente" in controle("Le PDQ 1 a une prévision de 12,3 actes.", "et le PDQ 1")


def test_lecture_fausse_rejetee():
    # Observé avec Qwen : chiffres justes, conclusion fausse (−1,4 est sous le seuil de 3 actes).
    texte = "Le PDQ 1 a une prévision de 5,4 actes, une normale de 6,8 actes et un écart de -1,4 actes, soit une baisse notable."
    assert controle(texte, "et le pdq 1") == ["lecture_fausse"]


def test_lecture_juste_acceptee():
    texte = "Le PDQ 1 a une prévision de 5,4 actes et une normale de 6,8 actes : l'écart est sous le seuil."
    assert controle(texte, "et le pdq 1") == []
