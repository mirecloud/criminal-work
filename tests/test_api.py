"""L'API avec le vrai modèle (artefacts des notebooks) et un LLM simulé : aucun appel réseau."""
import pytest
from conftest import ARTEFACTS

pytestmark = pytest.mark.skipif(not ARTEFACTS.exists(), reason="artefacts absents : exécuter les notebooks 00 à 04")


@pytest.fixture(scope="module")
def api():
    from fastapi.testclient import TestClient
    import app as A
    with TestClient(A.app) as client:
        yield client, A


@pytest.fixture
def llm_configure(monkeypatch, api):
    _, A = api
    monkeypatch.setattr(A.B, "load_dotenv", lambda **_: None)
    for variable, valeur in [("AI_MODEL", "test"), ("LLM_BASE_URL", "http://llm.invalid/v1"), ("LLM_API_KEY", "aucune")]:
        monkeypatch.setenv(variable, valeur)


def test_sante(api):
    client, _ = api
    assert client.get("/health/live").json() == {"status": "ok"}
    pret = client.get("/health/ready").json()
    assert pret["status"] == "ready" and pret["prompts"]


def test_prevision_29_pdq_et_horizon_4(api):
    client, A = api
    p = client.get("/prevision").json()
    assert len(p["lignes"]) == 29
    ecart = A.P.pd.Timestamp(p["semaine_predite"]) - A.P.pd.Timestamp(p["derniere_semaine_connue"])
    assert ecart.days == 7 * 4
    assert p["marge_90"] is not None and p["marge_90"] > p["marge"]


def test_bilan_controle_avec_llm_simule(api, llm_configure, monkeypatch):
    client, A = api

    def redaction_fidele(d, instructions):
        assert "9 cas sur 10" in instructions
        h = d["hausses"][0]
        return (f"Le modèle prévoit la plus forte hausse au PDQ {h['pdq']} ({h['prevision']} actes contre une normale "
                f"de {h['normale']}). Dans 9 cas sur 10, l'erreur reste sous "
                f"{d['erreur_max_9_fois_sur_10_actes_par_pdq']} actes par PDQ. {A.B.MENTION}")

    monkeypatch.setattr(A.B, "rediger", redaction_fidele)
    b = client.post("/bilan", json={}).json()
    # Les autres hausses ne sont pas nommées : le contrôle doit le voir, et seulement ça.
    attendu = [] if len([1 for l in client.get("/prevision").json()["lignes"] if l["ecart"] > 0]) <= 1 else ["hausses_absentes"]
    assert b["erreurs"] == attendu


def test_llm_non_configure_message_clair(api, monkeypatch):
    client, A = api
    monkeypatch.setattr(A.B, "load_dotenv", lambda **_: None)
    monkeypatch.delenv("AI_MODEL", raising=False)
    r = client.post("/bilan", json={})
    assert r.status_code == 503 and "AI_MODEL" in r.json()["detail"]
    assert "AI_MODEL" in client.get("/health/ready").json()["llm_manquant"]


def test_llm_injoignable(api, llm_configure, monkeypatch):
    client, A = api

    def panne(d, instructions):
        raise TimeoutError

    monkeypatch.setattr(A.B, "rediger", panne)
    r = client.post("/bilan", json={})
    assert r.status_code == 503 and "ne répond pas" in r.json()["detail"]
