"""Prévision de la semaine : le modèle du notebook 04 (normale + correction), avec exactement le même calcul d'historique."""
import hashlib
import json
import os
from pathlib import Path

import joblib
import pandas as pd

ROOT = Path(os.getenv("CRIME_ROOT", Path(__file__).resolve().parents[3]))
ART = ROOT / "artifacts"


class Prevision:
    """Charge une fois le modèle et sa fiche ; refuse un modèle qui ne correspond pas à ce qui a été évalué."""

    def __init__(self, dossier=ART / "04_comparaison"):
        self.meta = json.loads((dossier / "meta.json").read_text(encoding="utf-8"))
        fichier = dossier / "modele.joblib"
        self.empreinte = hashlib.sha256(fichier.read_bytes()).hexdigest()[:16]
        self.modele = joblib.load(fichier)
        if list(self.modele.feature_names_in_) != self.meta["colonnes"]:
            raise ValueError("Le modèle et sa fiche ne correspondent pas : relance le notebook 04.")
        if self.meta["cible"] != "y - moy_12":
            raise ValueError("Ce module attend un modèle qui corrige la normale (notebook 04).")
        self.horizon = self.meta["lag_min_semaines"]
        self.marge = self.meta["marge_erreur"]
        self.fin_entrainement = pd.Timestamp(self.meta["entraine_jusqu_au"])
        self.version = f"{self.meta['modele_retenu']}-{self.empreinte}"
        self.panel = pd.read_parquet(ART / "00_start_here" / "panel.parquet")[["SEMAINE", "PDQ", "y"]]

    def historique(self, panel):
        """Mot pour mot la construction du notebook 04 (lags, moyennes consolidées, écarts à la normale)."""
        p = panel.sort_values(["PDQ", "SEMAINE"]).reset_index(drop=True)
        par_pdq = p.groupby("PDQ")["y"]
        for k in self.meta["lags"]:
            p[f"lag_{k}"] = par_pdq.shift(k)
        for w in self.meta["fenetres"]:
            p[f"moy_{w}"] = par_pdq.transform(lambda s: s.shift(self.horizon).rolling(w).mean())
        p["mois"] = p["SEMAINE"].dt.month
        p["ecart_moy_4"] = p["moy_4"] - p["moy_12"]
        p["ecart_lag_4"] = p[f"lag_{self.horizon}"] - p["moy_12"]
        p["ecart_lag_52"] = p["lag_52"] - p["moy_12"]
        return p

    def semaines_disponibles(self):
        """Les dimanches qu'on peut rejouer : chaque semaine consolidée, après la première année."""
        semaines = sorted(self.panel["SEMAINE"].unique())
        return [pd.Timestamp(s) for s in semaines[52 + max(self.meta["fenetres"]):]]

    def prevoir(self, derniere_connue=None):
        """Prévision de la semaine cible = dernière semaine consolidée + horizon."""
        derniere_connue = pd.Timestamp(derniere_connue) if derniere_connue is not None else self.panel["SEMAINE"].max()
        connu = self.panel[self.panel["SEMAINE"] <= derniere_connue]
        if connu.empty:
            raise ValueError("Aucune semaine consolidée avant cette date.")
        pdq = connu["PDQ"].unique()
        a_venir = [pd.DataFrame({"SEMAINE": derniere_connue + pd.Timedelta(weeks=i), "PDQ": pdq, "y": float("nan")})
                   for i in range(1, self.horizon + 1)]
        p = self.historique(pd.concat([connu, *a_venir]))
        cible = derniere_connue + pd.Timedelta(weeks=self.horizon)
        x = p[p["SEMAINE"] == cible].copy()
        if x[self.meta["colonnes"]].isna().any().any():
            raise ValueError("Historique incomplet pour cette semaine (moins d'un an de données).")
        x["prevision"] = (x["moy_12"] + self.modele.predict(x[self.meta["colonnes"]])).clip(lower=0).round(1)
        x["normale"] = x["moy_12"].round(1)
        x["ecart"] = (x["prevision"] - x["normale"]).round(1)
        reel = self.panel.set_index(["SEMAINE", "PDQ"])["y"]
        x["reel"] = [reel.get((cible, q)) for q in x["PDQ"]]
        tableau = x[["PDQ", "prevision", "normale", "ecart", "reel"]].sort_values("ecart", ascending=False)
        return cible, tableau.reset_index(drop=True)
