"""API HTTP : la prévision (modèle ML) et le bilan (LLM + contrôle). La logique reste dans shared/."""
import os
import sys
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query, Request
from pydantic import BaseModel

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "shared"))
import bulletin as B  # noqa: E402
import prediction as P  # noqa: E402

PROMPTS = Path(os.getenv("CRIME_PROMPTS", Path(__file__).resolve().parents[1] / "prompts"))


class Ligne(BaseModel):
    pdq: str
    prevision: float
    normale: float
    ecart: float
    reel: int | None


class PrevisionReponse(BaseModel):
    semaine_predite: str
    derniere_semaine_connue: str
    marge: float
    modele: str
    lignes: list[Ligne]


class BilanDemande(BaseModel):
    derniere_connue: str | None = None


class BilanReponse(BaseModel):
    semaine_predite: str
    texte: str
    accepte: bool
    erreurs: list[str]
    messages: list[str]
    modele: str
    llm: str
    secondes: float


@asynccontextmanager
async def lifespan(app):
    try:
        app.state.prevision = P.Prevision()
    except (FileNotFoundError, ValueError) as erreur:
        print(f"Modèle indisponible : {erreur}", flush=True)
        app.state.prevision = None
    yield


app = FastAPI(title="Bilan hebdomadaire des PDQ", version="0.1.0", lifespan=lifespan,
              description="Prévision par PDQ (modèle du notebook 03) et bilan rédigé par le LLM, contrôlé automatiquement.")


@app.middleware("http")
async def journal(request: Request, call_next):
    """Une ligne de journal par requête, avec un identifiant (comme X-Request-ID chez le prof)."""
    rid = request.headers.get("x-request-id", uuid.uuid4().hex[:12])
    debut = time.perf_counter()
    reponse = await call_next(request)
    reponse.headers["x-request-id"] = rid
    print(f'{{"rid": "{rid}", "route": "{request.url.path}", "status": {reponse.status_code}, '
          f'"ms": {1000 * (time.perf_counter() - debut):.0f}}}', flush=True)
    return reponse


def modele():
    if app.state.prevision is None:
        raise HTTPException(503, "Modèle indisponible : vérifie artifacts/03_historique.")
    return app.state.prevision


@app.get("/health/live")
def live():
    return {"status": "ok"}


@app.get("/health/ready")
def ready():
    m = modele()
    return {"status": "ready", "modele": m.version, "derniere_semaine": m.panel["SEMAINE"].max().date().isoformat(),
            "prompts": (PROMPTS / "instructions.txt").is_file()}


@app.get("/semaines")
def semaines():
    """Les dimanches qu'on peut rejouer (dernière semaine consolidée connue)."""
    return [s.date().isoformat() for s in modele().semaines_disponibles()]


def _prevoir(m, derniere_connue):
    try:
        return m.prevoir(derniere_connue)
    except ValueError as erreur:
        raise HTTPException(422, str(erreur)) from None


@app.get("/prevision", response_model=PrevisionReponse)
def prevision(derniere_connue: str | None = Query(None, description="AAAA-MM-JJ ; vide = la plus récente")):
    m = modele()
    cible, tableau = _prevoir(m, derniere_connue)
    dl = cible - P.pd.Timedelta(weeks=m.horizon)
    lignes = [Ligne(pdq=r.PDQ, prevision=r.prevision, normale=r.normale, ecart=r.ecart,
                    reel=None if r.reel is None else int(r.reel)) for r in tableau.itertuples()]
    return PrevisionReponse(semaine_predite=cible.date().isoformat(), derniere_semaine_connue=dl.date().isoformat(),
                            marge=m.marge, modele=m.version, lignes=lignes)


@app.post("/bilan", response_model=BilanReponse)
def bilan(demande: BilanDemande):
    m = modele()
    try:
        instructions = (PROMPTS / "instructions.txt").read_text(encoding="utf-8")
    except FileNotFoundError:
        raise HTTPException(503, "Instructions du LLM absentes : active un prompt (prompts/instructions.txt).") from None
    cible, tableau = _prevoir(m, demande.derniere_connue)
    d = B.donnees(cible, tableau, m.marge, m.version, cible - P.pd.Timedelta(weeks=m.horizon))
    debut = time.perf_counter()
    try:
        texte = B.rediger(d, instructions)
    except Exception as erreur:  # serveur LLM injoignable, délai dépassé, etc.
        print(f"LLM indisponible : {type(erreur).__name__}", flush=True)
        raise HTTPException(503, "Le serveur LLM ne répond pas ; la prévision reste disponible.") from None
    erreurs = B.verifier(texte, d, tableau["PDQ"])
    return BilanReponse(semaine_predite=d["semaine_predite"], texte=texte, accepte=not erreurs, erreurs=erreurs,
                        messages=[B.ERREURS[e] for e in erreurs], modele=m.version, llm=os.environ["AI_MODEL"],
                        secondes=round(time.perf_counter() - debut, 1))