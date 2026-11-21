"""Historische Fensterfälle. Nur Daten bis zum jeweiligen Tag, keine überlappenden Ausgänge.

Ein positiver späterer Kurs ist kein Beweis, dass das Fenster ihn verursacht hat.
"""

from __future__ import annotations

import math
from collections.abc import Sequence

from analyse import de_prozent, kennzahlen_aus_schluessen, setup_aus_kennzahlen

HORIZONTE = (1, 3, 5, 20, 60)
VORSICHTIG = 30
BELASTBAR = 60
KOSTEN = 0.25
VERSION = 3


def als_json(bild: dict) -> str:
    import json

    kopie = dict(bild)
    kopie["horizonte"] = [dict(horizont) for horizont in bild.get("horizonte") or ()]
    return json.dumps(kopie, ensure_ascii=False)


def signale(schluesse: Sequence[float], ist_etf: bool) -> tuple[int, ...]:
    werte = _werte(schluesse)
    treffer = []
    for index in range(199, len(werte)):
        if setup_aus_kennzahlen(kennzahlen_aus_schluessen(werte[: index + 1], ist_etf, None)):
            treffer.append(index)
    return tuple(treffer)


def unabhaengige(werte: Sequence[float], punkte: Sequence[int], horizont: int, indexwerte: Sequence[float] | None = None) -> tuple[tuple[float, float | None], ...]:
    faelle = []
    zuletzt = -10**9
    for index in punkte:
        if index - zuletzt < horizont:
            continue
        paar = _rendite(werte, indexwerte, index, horizont)
        if paar is None:
            continue
        faelle.append(paar)
        zuletzt = index
    return tuple(faelle)


def pruefen(zahlen, schluesse: Sequence[float], index_schluesse: Sequence[float] | None = None, bereinigt: bool = True) -> dict:
    werte = _werte(schluesse)
    ist_etf = bool(zahlen is not None and zahlen.ist_etf)
    indexwerte = None if index_schluesse is None else _indexwerte(index_schluesse, len(werte))
    punkte = signale(werte, ist_etf)
    horizonte = tuple(_horizont(werte, punkte, tage, indexwerte) for tage in HORIZONTE)
    entscheidung = _entscheidung(horizonte, bool(bereinigt))
    bild = {
        "aktiv": setup_aus_kennzahlen(zahlen),
        "art": "etf" if ist_etf else "aktie",
        "bereinigt": bool(bereinigt),
        "kosten": KOSTEN,
        "zeitraum": len(werte),
        "buyhold": _kauf_halten(werte),
        "index_buyhold": None if indexwerte is None else _kauf_halten(indexwerte),
        "horizonte": horizonte,
        "qualitaet": entscheidung["qualitaet"],
        "rang": entscheidung["rang"],
        "faelle": entscheidung["faelle"],
        "tage": entscheidung["tage"],
    }
    bild["satz"] = _satz(bild)
    if not bild["aktiv"]:
        bild["rang"] = None
        bild["satz"] = "Das Fenster ist im aktuellen Kurs nicht offen. " + bild["satz"]
    return bild


def _werte(schluesse: Sequence[float]) -> tuple[float, ...]:
    return tuple(float(wert) for wert in schluesse if wert)


def _indexwerte(schluesse: Sequence[float], laenge: int) -> tuple[float | None, ...]:
    werte = tuple(None if wert is None or isinstance(wert, bool) or not wert else float(wert) for wert in schluesse)
    if len(werte) < laenge:
        werte = werte + (None,) * (laenge - len(werte))
    return werte[:laenge]


def _rendite(werte, indexwerte, start: int, horizont: int) -> tuple[float, float | None] | None:
    ziel = start + horizont
    if ziel >= len(werte) or not werte[start]:
        return None
    kurs = (werte[ziel] / werte[start] - 1.0) * 100.0
    index = None
    if indexwerte is not None and ziel < len(indexwerte) and indexwerte[start] and indexwerte[ziel]:
        index = (indexwerte[ziel] / indexwerte[start] - 1.0) * 100.0
    return kurs, index


def _horizont(werte, punkte, tage: int, indexwerte) -> dict:
    faelle = unabhaengige(werte, punkte, tage, indexwerte)
    kurse = tuple(fall[0] for fall in faelle)
    indizes = tuple(fall[1] for fall in faelle if fall[1] is not None)
    positiv = sum(1 for wert in kurse if wert > 0)
    negativ = sum(1 for wert in kurse if wert < 0)
    return {
        "tage": tage,
        "anzahl": len(kurse),
        "median": None if not kurse else _median(kurse),
        "treffer": None if not kurse else positiv / len(kurse),
        "positiv": positiv,
        "negativ": negativ,
        "schlechtester": None if not kurse else min(kurse),
        "bester": None if not kurse else max(kurse),
        "streuung": _streuung(kurse),
        "index_median": None if len(indizes) * 2 < max(len(kurse), 1) else _median(indizes),
    }


def _entscheidung(horizonte: Sequence[dict], bereinigt: bool) -> dict:
    groesster = max(horizonte, key=lambda horizont: horizont["anzahl"], default=None)
    leer = {
        "qualitaet": "zu_klein",
        "rang": None,
        "faelle": 0 if groesster is None else int(groesster["anzahl"]),
        "tage": 0 if groesster is None else int(groesster["tage"]),
    }
    if not bereinigt:
        leer["qualitaet"] = "unbereinigt"
        return leer
    geeignet = tuple(horizont for horizont in horizonte if horizont["anzahl"] >= VORSICHTIG and horizont["index_median"] is not None)
    if not geeignet:
        groesster = max(horizonte, key=lambda horizont: horizont["anzahl"], default=None)
        if groesster and groesster["anzahl"] >= VORSICHTIG and groesster["index_median"] is None:
            return {"qualitaet": "index_fehlt", "rang": None, "faelle": groesster["anzahl"], "tage": groesster["tage"]}
        if groesster:
            return {"qualitaet": "zu_klein", "rang": None, "faelle": groesster["anzahl"], "tage": groesster["tage"]}
        return leer
    gewaehlt = max(geeignet, key=lambda horizont: horizont["tage"])
    ueberschuss = float(gewaehlt["median"]) - KOSTEN - float(gewaehlt["index_median"])
    if ueberschuss <= 0:
        return {"qualitaet": "kein_vorsprung", "rang": None, "faelle": gewaehlt["anzahl"], "tage": gewaehlt["tage"]}
    streuung = gewaehlt["streuung"] if gewaehlt["streuung"] else 0.5
    gewicht = min(int(gewaehlt["anzahl"]), BELASTBAR) / float(BELASTBAR)
    treffer = 0.5 + max(0.0, float(gewaehlt["treffer"] or 0.0) - 0.5)
    qualitaet = "belastbarer" if gewaehlt["anzahl"] >= BELASTBAR else "vorsichtig"
    return {
        "qualitaet": qualitaet,
        "rang": (ueberschuss / max(float(streuung), 0.5)) * gewicht * treffer,
        "faelle": int(gewaehlt["anzahl"]),
        "tage": int(gewaehlt["tage"]),
    }


def _satz(bild: dict) -> str:
    horizont = _passender(bild)
    anzahl = 0 if horizont is None else int(horizont["anzahl"])
    tage = 0 if horizont is None else int(horizont["tage"])
    kosten = (
        f"Handelskosten sind nicht gemessen. Abgezogen ist eine Annahme von {de_prozent(KOSTEN)} "
        "für Spread und Slippage, nicht die Courtage."
    )
    halten = _halten_satz(bild)
    unsicherheit = (
        "Die Liste enthält heutige Indexmitglieder, früher entfernte Namen fehlen. "
        "Ein späterer Kurs beweist die Ursache nicht. Das ist kein Auftrag."
    )
    qualitaet = bild["qualitaet"]
    if qualitaet == "unbereinigt":
        kern = "Schlusskurse sind nicht splitbereinigt. Daraus wird kein Vorschlag."
    elif qualitaet == "zu_klein":
        kern = f"Datenbasis zu klein: {anzahl} unabhängige Fälle nach {tage} Handelstagen. Vorsichtig ab 30, belastbarer ab 60."
    elif qualitaet == "index_fehlt":
        kern = f"Indexvergleich fehlt bei {anzahl} Fällen nach {tage} Handelstagen. Kein Vorschlag."
    elif horizont is None:
        kern = "Datenbasis zu klein."
    else:
        name = "Belastbarer" if qualitaet == "belastbarer" else "Vorsichtig" if qualitaet == "vorsichtig" else "Gemessen"
        kern = (
            f"{name}, {bild['art']}, {anzahl} unabhängige Fälle nach {tage} Handelstagen. "
            f"Median {de_prozent(horizont['median'])}, nach der Kostenannahme {de_prozent(float(horizont['median']) - KOSTEN)}. "
            f"Treffer {_anteil(horizont['treffer'])}, {horizont['positiv']} positiv, {horizont['negativ']} negativ, "
            f"schlechtester {de_prozent(horizont['schlechtester'])}, bester {de_prozent(horizont['bester'])}. "
            f"Index-Median {de_prozent(horizont['index_median'])}."
        )
    zeilen = [kern, _alle_horizonte(bild["horizonte"]), f"Zeitraum: {bild['zeitraum']} geladene Handelstage. {halten}", kosten, unsicherheit]
    return " ".join(teil for teil in zeilen if teil)


def _passender(bild: dict) -> dict | None:
    if bild["tage"]:
        for horizont in bild["horizonte"]:
            if horizont["tage"] == bild["tage"]:
                return horizont
    if not bild["horizonte"]:
        return None
    return max(bild["horizonte"], key=lambda horizont: horizont["anzahl"])


def _alle_horizonte(horizonte: Sequence[dict]) -> str:
    teile = []
    for horizont in horizonte:
        if horizont["anzahl"] < VORSICHTIG or horizont["median"] is None:
            teile.append(f"{horizont['tage']}T: {horizont['anzahl']} Fälle, Datenbasis zu klein")
            continue
        teile.append(
            f"{horizont['tage']}T: {horizont['anzahl']} Fälle, Median {de_prozent(horizont['median'])}, "
            f"Treffer {_anteil(horizont['treffer'])}, Index {de_prozent(horizont['index_median'])}"
        )
    return " | ".join(teile)


def _halten_satz(bild: dict) -> str:
    text = f"Kauf und Halten ab dem ersten bewertbaren Tag: {de_prozent(bild['buyhold'])}."
    if bild["index_buyhold"] is not None:
        text += f" Der Index in derselben Spanne: {de_prozent(bild['index_buyhold'])}."
    return text + " Das ist der Vergleich, kein Handelssystem."


def _anteil(wert) -> str:
    if wert is None:
        return "ohne Trefferquote"
    return f"{round(float(wert) * 100)} %"


def _kauf_halten(werte: Sequence[float]) -> float | None:
    if len(werte) <= 200 or not werte[199] or not werte[-1]:
        return None
    return (float(werte[-1]) / float(werte[199]) - 1.0) * 100.0


def _median(werte: Sequence[float]) -> float:
    sortiert = sorted(werte)
    mitte = len(sortiert) // 2
    if len(sortiert) % 2:
        return float(sortiert[mitte])
    return (float(sortiert[mitte - 1]) + float(sortiert[mitte])) / 2.0


def _streuung(werte: Sequence[float]) -> float | None:
    if len(werte) < 2:
        return None
    mittel = sum(werte) / len(werte)
    varianz = sum((wert - mittel) ** 2 for wert in werte) / (len(werte) - 1)
    return math.sqrt(varianz)
