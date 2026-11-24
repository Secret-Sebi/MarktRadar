"""Vergleicht drei Prognoseregeln auf derselben zeitlichen Trennung.

Der Vergleich trainiert nicht auf dem Test und gibt kein Modell frei.
Random Forest, Gradient Boosting und neuronale Netze sind nicht eingebaut.
"""

from __future__ import annotations

import math

from ki import leeres_modell, schritt, wahrscheinlichkeit

_CLIP = 1e-6
_NICHT = ("random_forest", "gradient_boosting", "neuronales_netz")


def vergleiche(train, val, test, *, test_offen: bool, logistisch_freigegeben: bool = False) -> dict:
    """Misst konstant, Momentum und Logistik. Nur die Logistik kann freigegeben sein."""
    if len(train) < 36 or len(val) < 36:
        return _leer("Weniger als 36 Trainings- oder Validierungsfälle.")
    basis = _rate(train)
    regeln = (
        ("konstant", lambda _eingabe: basis),
        ("momentum", _momentum(train, basis)),
        ("logistisch", _logistisch(train)),
    )
    modelle = []
    for name, regel in regeln:
        validierung = _bewerte(regel, val, basis)
        schlaegt = name != "konstant" and _schlaegt(validierung)
        test_messung = _bewerte(regel, test, basis) if test_offen and schlaegt else None
        modelle.append(
            {
                "id": name,
                "version": "vergleich-1",
                "features": ["themen", "rsi", "ueber_schnitt"],
                "validierung": validierung,
                "test": test_messung,
                "schlaegt_validierung": schlaegt,
                "freigegeben": bool(logistisch_freigegeben) and name == "logistisch",
            }
        )
    return {
        "status": "freigegeben" if logistisch_freigegeben else "nicht_freigegeben",
        "grund": "Vergleich ist keine eigene Freigabe.",
        "modelle": modelle,
        "nicht_implementiert": list(_NICHT),
        "freigegeben": bool(logistisch_freigegeben),
    }


def _leer(grund: str) -> dict:
    return {
        "status": "nicht_freigegeben",
        "grund": grund,
        "modelle": [],
        "nicht_implementiert": list(_NICHT),
        "freigegeben": False,
    }


def _logistisch(train):
    modell = leeres_modell()
    for _durchgang in range(8):
        for fall in train:
            modell = schritt(modell, fall[1], fall[2])
    return lambda eingabe: wahrscheinlichkeit(modell, eingabe)


def _momentum(train, basis: float):
    oben = tuple(fall[2] for fall in train if _letzter(fall) >= 0.5)
    unten = tuple(fall[2] for fall in train if _letzter(fall) < 0.5)
    rate_oben = _mittel(oben, basis)
    rate_unten = _mittel(unten, basis)

    def regel(eingabe):
        return rate_oben if eingabe and float(eingabe[-1]) >= 0.5 else rate_unten

    return regel


def _letzter(fall) -> float:
    eingabe = fall[1]
    if not eingabe:
        return 0.0
    return float(eingabe[-1])


def _bewerte(regel, faelle, basis: float) -> dict:
    paare = tuple((float(regel(fall[1])), float(fall[2])) for fall in faelle)
    basis_paare = tuple((basis, float(fall[2])) for fall in faelle)
    return {
        "n": len(faelle),
        "brier": _brier(paare),
        "logloss": _logloss(paare),
        "basis_brier": _brier(basis_paare),
        "basis_logloss": _logloss(basis_paare),
    }


def _schlaegt(messung: dict) -> bool:
    return messung["brier"] < messung["basis_brier"] and messung["logloss"] < messung["basis_logloss"]


def _brier(paare) -> float:
    return sum((_clip(p) - y) ** 2 for p, y in paare) / len(paare)


def _logloss(paare) -> float:
    return sum(-(y * math.log(_clip(p)) + (1.0 - y) * math.log(1.0 - _clip(p))) for p, y in paare) / len(paare)


def _clip(wert: float) -> float:
    return max(_CLIP, min(1.0 - _CLIP, wert))


def _rate(faelle) -> float:
    return sum(float(fall[2]) for fall in faelle) / len(faelle)


def _mittel(werte: tuple[float, ...], ersatz: float) -> float:
    if not werte:
        return ersatz
    return sum(werte) / len(werte)
