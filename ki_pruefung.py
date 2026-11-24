"""Chronologische Prüfung je Horizont. Der Test trainiert die Gewichte nicht."""

from __future__ import annotations

import math

from ki import Modell, leeres_modell, schritt, wahrscheinlichkeit

_TRAIN = 36
_VAL = 36
_TEST = 36
_CLIP = 1e-6


def pruefe_faelle(faelle: tuple, gehalten_bis: int | None = None, *, testen: bool = False) -> dict:
    """Der Test wird erst bewertet, wenn die Validierung bestanden ist.

    Jeder Fall braucht Zielbeginn und Zielende. Ein Ziel, das in den nächsten
    Abschnitt reicht, trainiert diesen Abschnitt nicht. Ein schon bewerteter
    Test bleibt aus dem Training.
    """
    nutzbar = tuple(fall for fall in faelle if _fenster(fall) is not None)
    ohne = len(faelle) - len(nutzbar)
    if not nutzbar:
        return _abschluss(False, 0, "Zielzeitpunkt fehlt", None, None, None, None, ohne)
    geordnet = tuple(sorted(nutzbar, key=lambda fall: (_anfang(fall), fall[0])))
    if gehalten_bis is not None:
        return _wiederholung(geordnet, int(gehalten_bis), ohne, testen)
    if len(geordnet) < _TRAIN + _VAL + _TEST:
        return _abschluss(False, len(geordnet), "Nicht ausreichend trainiert", None, None, None, None, ohne)
    test = geordnet[-_TEST:]
    val = geordnet[-(_TEST + _VAL):-_TEST]
    train = geordnet[:-(_TEST + _VAL)]
    if not _danach(train, val) or not _danach(val, test):
        return _abschluss(False, len(geordnet), "Testfälle liegen nicht nach der Prüfung", None, None, None, None, ohne)
    train = _purge(train, val)
    val = _purge(val, test)
    if len(train) < _TRAIN or len(val) < _VAL:
        return _abschluss(False, len(geordnet), "Zielzeitraum reicht in die nächste Prüfung", None, None, None, None, ohne)
    basis = _rate(train)
    val_modell = _fit(train)
    grenze = _anfang(test[0])
    if not _besser(val_modell, val, basis):
        return _mit_vergleich(_abschluss(False, len(geordnet), "Validierung schlägt die Basisrate nicht", _messung(val_modell, val, basis), None, _ende(train[-1]), grenze, ohne), train, val, test, False)
    fenster = train + val
    for start in range(_TRAIN, len(fenster) - _VAL + 1, _VAL):
        block = fenster[start:start + _VAL]
        if len(block) < _VAL or not _danach(fenster[:start], block):
            continue
        vorher = _purge(fenster[:start], block)
        if len(vorher) < _TRAIN:
            return _mit_vergleich(_abschluss(False, len(geordnet), "Zielzeitraum reicht in die nächste Prüfung", _messung(val_modell, val, basis), None, _ende(train[-1]), grenze, ohne), train, val, test, False)
        if not _besser(_fit(vorher), block, _rate(vorher)):
            return _mit_vergleich(_abschluss(False, len(geordnet), "Walk-forward schlägt die Basisrate nicht", _messung(val_modell, val, basis), None, _ende(train[-1]), grenze, ohne), train, val, test, False)
    kandidat = _fit(fenster)
    test_basis = _rate(fenster)
    test_messung = _messung(kandidat, test, test_basis)
    if not _besser(kandidat, test, test_basis):
        return _mit_vergleich(_abschluss(False, len(geordnet), "Test schlägt die Basisrate nicht", _messung(val_modell, val, basis), test_messung, _ende(train[-1]), _anfang(test[0]), ohne), train, val, test, True)
    if not _kalibriert(kandidat, test):
        return _mit_vergleich(_abschluss(False, len(geordnet), "Kalibrierung nicht ausreichend", _messung(val_modell, val, basis), test_messung, _ende(train[-1]), _anfang(test[0]), ohne), train, val, test, True)
    bericht = _abschluss(True, len(geordnet), "Horizont geprüft. Der Test hat die Gewichte nicht trainiert.", _messung(val_modell, val, basis), test_messung, _ende(train[-1]), _anfang(test[0]), ohne)
    bericht["gewichte"] = kandidat.gewichte
    bericht["bias"] = kandidat.bias
    return _mit_vergleich(bericht, train, val, test, True)


def _wiederholung(geordnet, gehalten_bis: int, ohne: int, testen: bool) -> dict:
    vorher = tuple(fall for fall in geordnet if _ende(fall) <= gehalten_bis)
    if len(vorher) < _TRAIN + _VAL:
        return _abschluss(False, len(vorher), "Nicht ausreichend trainiert", None, None, None, gehalten_bis, ohne)
    val = vorher[-_VAL:]
    train = _purge(vorher[:-_VAL], val)
    if len(train) < _TRAIN or not _danach(train, val):
        return _abschluss(False, len(vorher), "Zielzeitraum reicht in die nächste Prüfung", None, None, None, gehalten_bis, ohne)
    basis = _rate(train)
    modell = _fit(train)
    messung = _messung(modell, val, basis)
    if not _besser(modell, val, basis):
        return _mit_vergleich(_abschluss(False, len(vorher), "Validierung schlägt die Basisrate nicht", messung, None, _ende(train[-1]), gehalten_bis, ohne), train, val, (), False)
    test = tuple(fall for fall in geordnet if _anfang(fall) >= gehalten_bis)
    if not testen or len(test) < _TEST or not _danach(val, test):
        return _mit_vergleich(_abschluss(False, len(vorher), "Test bleibt gehalten. Keine erneute Testwertung.", messung, None, _ende(train[-1]), gehalten_bis, ohne), train, val, test, False)
    kandidat = _fit(train + val)
    test_basis = _rate(train + val)
    test_messung = _messung(kandidat, test, test_basis)
    if not _besser(kandidat, test, test_basis):
        return _mit_vergleich(_abschluss(False, len(geordnet), "Test schlägt die Basisrate nicht", messung, test_messung, _ende(train[-1]), gehalten_bis, ohne), train, val, test, True)
    if not _kalibriert(kandidat, test):
        return _mit_vergleich(_abschluss(False, len(geordnet), "Kalibrierung nicht ausreichend", messung, test_messung, _ende(train[-1]), gehalten_bis, ohne), train, val, test, True)
    bericht = _abschluss(True, len(geordnet), "Horizont geprüft. Der Test hat die Gewichte nicht trainiert.", messung, test_messung, _ende(train[-1]), gehalten_bis, ohne)
    bericht["gewichte"] = kandidat.gewichte
    bericht["bias"] = kandidat.bias
    return _mit_vergleich(bericht, train, val, test, True)


def _fenster(fall) -> tuple[int, int] | None:
    if len(fall) < 5 or isinstance(fall[3], bool) or isinstance(fall[4], bool):
        return None
    if not isinstance(fall[3], int) or not isinstance(fall[4], int) or fall[4] <= fall[3]:
        return None
    return fall[3], fall[4]


def _anfang(fall) -> int:
    return int(fall[3])


def _ende(fall) -> int:
    return int(fall[4])


def _danach(links, rechts) -> bool:
    return bool(links and rechts and _anfang(rechts[0]) > _anfang(links[-1]) and _ende(links[-1]) <= _anfang(rechts[0]))


def _purge(links, rechts):
    if not rechts:
        return tuple(links)
    grenze = _anfang(rechts[0])
    return tuple(fall for fall in links if _ende(fall) <= grenze)


def _messung(modell: Modell, faelle, basis: float) -> dict:
    brier, logloss = _scores(modell, faelle)
    basis_brier, basis_logloss = _scores_konstante(basis, faelle)
    return {
        "n": len(faelle),
        "brier": brier,
        "logloss": logloss,
        "basis_brier": basis_brier,
        "basis_logloss": basis_logloss,
        "kalibrierung": _luecken(modell, faelle),
    }


def _abschluss(bestanden: bool, anzahl: int, grund: str, validierung, test, train_bis, test_von, ohne: int) -> dict:
    quelle = test if test is not None else validierung
    return {
        "bestanden": bestanden,
        "grund": grund,
        "n": anzahl,
        "gemessen": "test" if test is not None else "validierung",
        "validierung": validierung,
        "test": test,
        "brier": None if quelle is None else quelle["brier"],
        "logloss": None if quelle is None else quelle["logloss"],
        "basis_brier": None if quelle is None else quelle["basis_brier"],
        "basis_logloss": None if quelle is None else quelle["basis_logloss"],
        "kalibrierung": None if quelle is None else quelle["kalibrierung"],
        "train_bis": train_bis,
        "test_von": test_von,
        "ohne_zielzeit": ohne,
        "vergleich": {
            "status": "nicht_freigegeben",
            "grund": "Noch kein Modellvergleich.",
            "modelle": [],
            "nicht_implementiert": ["random_forest", "gradient_boosting", "neuronales_netz"],
            "freigegeben": False,
        },
    }


def _mit_vergleich(bericht: dict, train, val, test, test_offen: bool) -> dict:
    from prognose_vergleich import vergleiche

    bericht["vergleich"] = vergleiche(train, val, test, test_offen=test_offen, logistisch_freigegeben=bool(bericht["bestanden"]))
    return bericht


def _fit(faelle) -> Modell:
    """Mehrere Durchgänge nur auf diesem Abschnitt. Der Testabschnitt bleibt außen."""
    modell = leeres_modell()
    for _durchgang in range(8):
        for fall in faelle:
            modell = schritt(modell, fall[1], fall[2])
    return modell


def _rate(faelle) -> float:
    if not faelle:
        return 0.5
    return sum(fall[2] for fall in faelle) / len(faelle)


def _besser(modell: Modell, faelle, basis: float) -> bool:
    brier, logloss = _scores(modell, faelle)
    basis_brier, basis_logloss = _scores_konstante(basis, faelle)
    return brier < basis_brier and logloss < basis_logloss


def _scores(modell: Modell, faelle) -> tuple[float, float]:
    paare = tuple((wahrscheinlichkeit(modell, fall[1]), fall[2]) for fall in faelle)
    return _mittel_brier(paare), _mittel_logloss(paare)


def _scores_konstante(basis: float, faelle) -> tuple[float, float]:
    paare = tuple((basis, fall[2]) for fall in faelle)
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
    for fall in test:
        p = wahrscheinlichkeit(modell, fall[1])
        index = min(4, int(p * 5))
        eimer[index].append((p, fall[2]))
    return [
        {
            "n": len(werte),
            "mittel": None if not werte else sum(p for p, _y in werte) / len(werte),
            "treffer": None if not werte else sum(y for _p, y in werte) / len(werte),
        }
        for werte in eimer
    ]
