"""Chronologische Prüfung je Horizont. Der Test trainiert die Gewichte nicht."""

from __future__ import annotations

import math

from ki import Modell, leeres_modell, schritt, wahrscheinlichkeit

_TRAIN = 36
_VAL = 36
_TEST = 36
_CLIP = 1e-6


def pruefe_faelle(faelle: tuple[tuple[int, tuple[float, ...], float], ...], sperre: int = 0) -> dict:
    """Sperre ist der Mindestabstand in Sekunden bis das Ziel bekannt sein kann.

    Drei Kalendertage je Handelstag sind ein Puffer, kein Börsenkalender.
    """
    geordnet = tuple(sorted(faelle, key=lambda fall: fall[0]))
    if len(geordnet) < _TRAIN + _VAL + _TEST:
        return _leer(len(geordnet), "Nicht ausreichend trainiert")
    test = geordnet[-_TEST:]
    val = geordnet[-(_TEST + _VAL):-_TEST]
    train = geordnet[:-(_TEST + _VAL)]
    if test[0][0] <= val[-1][0] or val[0][0] <= train[-1][0]:
        return _leer(len(geordnet), "Testfälle liegen nicht nach der Prüfung")
    if sperre > 0:
        train = tuple(fall for fall in train if fall[0] + sperre <= val[0][0])
        val = tuple(fall for fall in val if fall[0] + sperre <= test[0][0])
        if len(train) < _TRAIN or len(val) < _VAL:
            return _leer(len(geordnet), "Zielzeitraum reicht in die nächste Prüfung")
    basis = _rate(train)
    val_modell = _fit(train)
    if not _besser(val_modell, val, basis):
        return _bericht(False, len(geordnet), "Validierung schlägt die Basisrate nicht", val_modell, test, basis)
    fenster = train + val
    for start in range(_TRAIN, len(fenster) - _VAL + 1, _VAL):
        block = fenster[start:start + _VAL]
        if len(block) < _VAL or block[0][0] <= fenster[start - 1][0]:
            continue
        vorher = tuple(fall for fall in fenster[:start] if sperre <= 0 or fall[0] + sperre <= block[0][0])
        if len(vorher) < _TRAIN:
            return _bericht(False, len(geordnet), "Zielzeitraum reicht in die nächste Prüfung", val_modell, test, basis)
        if not _besser(_fit(vorher), block, _rate(vorher)):
            return _bericht(False, len(geordnet), "Walk-forward schlägt die Basisrate nicht", val_modell, test, basis)
    kandidat = _fit(fenster)
    if not _besser(kandidat, test, _rate(fenster)):
        return _bericht(False, len(geordnet), "Test schlägt die Basisrate nicht", kandidat, test, basis)
    if not _kalibriert(kandidat, test):
        return _bericht(False, len(geordnet), "Kalibrierung nicht ausreichend", kandidat, test, basis)
    bericht = _bericht(True, len(geordnet), "Horizont geprüft. Der Test hat die Gewichte nicht trainiert.", kandidat, test, basis)
    bericht["gewichte"] = kandidat.gewichte
    bericht["bias"] = kandidat.bias
    return bericht


def _leer(anzahl: int, grund: str) -> dict:
    return {"bestanden": False, "grund": grund, "n": anzahl, "brier": None, "logloss": None, "basis_brier": None, "kalibrierung": None}


def _bericht(bestanden: bool, anzahl: int, grund: str, modell: Modell, test, basis: float) -> dict:
    brier, logloss = _scores(modell, test)
    basis_brier, basis_logloss = _scores_konstante(basis, test)
    return {
        "bestanden": bestanden,
        "grund": grund,
        "n": anzahl,
        "brier": brier,
        "logloss": logloss,
        "basis_brier": basis_brier,
        "basis_logloss": basis_logloss,
        "kalibrierung": _luecken(modell, test),
    }


def _fit(faelle) -> Modell:
    """Mehrere Durchgänge nur auf diesem Abschnitt. Der Testabschnitt bleibt außen."""
    modell = leeres_modell()
    for _durchgang in range(8):
        for _zeit, eingabe, ziel in faelle:
            modell = schritt(modell, eingabe, ziel)
    return modell


def _rate(faelle) -> float:
    if not faelle:
        return 0.5
    return sum(ziel for _zeit, _eingabe, ziel in faelle) / len(faelle)


def _besser(modell: Modell, faelle, basis: float) -> bool:
    brier, logloss = _scores(modell, faelle)
    basis_brier, basis_logloss = _scores_konstante(basis, faelle)
    return brier < basis_brier and logloss < basis_logloss


def _scores(modell: Modell, faelle) -> tuple[float, float]:
    paare = tuple((wahrscheinlichkeit(modell, eingabe), ziel) for _zeit, eingabe, ziel in faelle)
    return _mittel_brier(paare), _mittel_logloss(paare)


def _scores_konstante(basis: float, faelle) -> tuple[float, float]:
    paare = tuple((basis, ziel) for _zeit, _eingabe, ziel in faelle)
    return _mittel_brier(paare), _mittel_logloss(paare)


def _mittel_brier(paare: tuple[tuple[float, float], ...]) -> float:
    return sum((max(_CLIP, min(1.0 - _CLIP, p)) - y) ** 2 for p, y in paare) / len(paare)


def _mittel_logloss(paare: tuple[tuple[float, float], ...]) -> float:
    summe = 0.0
    for p_roh, y in paare:
        p = max(_CLIP, min(1.0 - _CLIP, p_roh))
        summe += -(y * math.log(p) + (1.0 - y) * math.log(1.0 - p))
    return summe / len(paare)


def _kalibriert(modell: Modell, test) -> bool:
    luecken = _luecken(modell, test)
    belegt = [luecke for luecke in luecken if luecke["n"] >= 5]
    if len(belegt) < 2:
        return False
    return all(abs(luecke["mittel"] - luecke["treffer"]) <= 0.15 for luecke in belegt)


def _luecken(modell: Modell, test) -> list[dict]:
    eimer: list[list[tuple[float, float]]] = [[] for _ in range(5)]
    for _zeit, eingabe, ziel in test:
        p = wahrscheinlichkeit(modell, eingabe)
        index = min(4, int(p * 5))
        eimer[index].append((p, ziel))
    return [
        {
            "n": len(werte),
            "mittel": None if not werte else sum(p for p, _y in werte) / len(werte),
            "treffer": None if not werte else sum(y for _p, y in werte) / len(werte),
        }
        for werte in eimer
    ]
