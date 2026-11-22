"""Getrennte virtuelle KI-Trader. Jeder hat eigene Gewichte und ein eigenes Buch.

Alpaca bleibt ein gemeinsames Paper-Konto. Diese Trader senden dort keine Orders,
damit sie sich keine Positionen schließen. Eine fehlende Datenreihe ist kein Kauf.
"""

from __future__ import annotations

import json
import math
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal

from analyse import rsi, sma
from technik import macd as macd_rechnung
from technik import volatilitaet as volatilitaet_rechnung

_ANTEIL = Decimal("0.00125")
_MINDEST = 20
_SHARPE = 30
_ZUVERLAESSIG = 12
_START = Decimal(10000)
_KENNZAHL = "Nicht ausreichend Daten"


@dataclass(frozen=True)
class Haendler:
    name: str
    gruppe: str
    horizont: str
    markt: str
    einsatz: bool
    regel: str


HAENDLER: tuple[Haendler, ...] = (
    Haendler("Momentum", "Technik", "mittel", "alle", True, "Kauf nur, wenn der Schluss nach 20 und nach 5 Tagen höher liegt."),
    Haendler("RSI", "Technik", "kurz", "alle", True, "Kauf nur bei RSI zwischen 30 und 45. Ab 70 ist es ein Verkauf, wenn eine Position offen ist."),
    Haendler("MACD", "Technik", "kurz", "alle", True, "Kauf nur, wenn die MACD-Linie über der Signallinie liegt. Sonst kein Wert."),
    Haendler("Ausbruch", "Technik", "mittel", "alle", True, "Kauf nur über dem höchsten Schluss der vorigen 20 Tage."),
    Haendler("Trend", "Technik", "mittel", "alle", True, "Kauf nur, wenn der Schluss über dem 20- und dem 50-Tage-Schnitt liegt."),
    Haendler("Gleitend", "Technik", "mittel", "alle", True, "Kauf nur, wenn der 20-Tage-Schnitt den 50-Tage-Schnitt nach oben kreuzt."),
    Haendler("Volumen", "Technik", "kurz", "alle", False, "Volumen liegt nicht vor. Deshalb kein Kauf."),
    Haendler("Volatilität", "Technik", "kurz", "alle", True, "Kauf nur bei gemessener Tagesstreuung unter 3 Prozent."),
    Haendler("Rücksetzer", "Technik", "mittel", "alle", True, "Kauf nur über dem 200-Tage-Schnitt und am 20-Tage-Schnitt, RSI 30 bis 55."),
    Haendler("Kerze", "Technik", "kurz", "alle", False, "Nur Schlusskurse, keine Kerzen. Deshalb kein Kauf."),
    Haendler("Substanz", "Fundament", "lang", "aktie", False, "KGV ist keine Kaufnote."),
    Haendler("Wachstum", "Fundament", "lang", "aktie", False, "Umsatzwachstum ist keine Kaufnote."),
    Haendler("Qualität", "Fundament", "lang", "aktie", False, "Marge und Eigenkapitalrendite sind keine Kaufnote."),
    Haendler("Dividende", "Fundament", "lang", "aktie", False, "Eine Dividendenrendite ist keine Kaufnote."),
    Haendler("Fundament", "Fundament", "lang", "aktie", False, "Mehrere Kennzahlen bleiben ein Hinweis, keine Kaufnote."),
    Haendler("Nachrichten", "Nachrichten", "kurz", "alle", False, "Eine Meldung ist kein Kaufgrund."),
    Haendler("Stimmung", "Nachrichten", "kurz", "alle", False, "Der Ton einer Überschrift ist kein Kaufgrund."),
    Haendler("Quartal", "Nachrichten", "mittel", "aktie", False, "Eine Quartalsmeldung ist kein Auftrag."),
    Haendler("Makro", "Nachrichten", "mittel", "alle", False, "Eine Makromeldung ist kein Kaufgrund."),
    Haendler("Termin", "Nachrichten", "kurz", "alle", False, "Es ist kein Terminkalender gespeichert."),
    Haendler("Krypto", "Markt", "kurz", "krypto", True, "Nur Krypto, und nur mit positivem 20-Tage-Momentum."),
    Haendler("ETF", "Markt", "lang", "etf", True, "Nur ETFs, und nur beim Rücksetzer über dem langen Schnitt."),
    Haendler("Large", "Markt", "lang", "aktie", False, "Die Marktkapitalisierung fehlt. Die Indexliste ist kein Größenmaß."),
    Haendler("Small", "Markt", "lang", "aktie", False, "Die Marktkapitalisierung fehlt. Keine Small-Cap-Auswahl."),
    Haendler("Defensiv", "Markt", "mittel", "alle", True, "Nur ein ruhiger Aufwärtstrend, engerer Stop, unter 1,5 Prozent Streuung."),
    Haendler("Ensemble", "Experiment", "mittel", "alle", True, "Kauf nur, wenn Momentum, Trend, Gleitend und RSI in mindestens drei Fällen kaufen."),
    Haendler("Adaptiv", "Experiment", "kurz", "alle", False, "RSI-Schwelle bleibt fest, bis 30 eigene Fälle die letzte Zehntel verbessern."),
    Haendler("Conträr", "Experiment", "kurz", "alle", True, "Kauf nur bei RSI unter 35 und Schluss über dem 200-Tage-Schnitt."),
    Haendler("Statistik", "Experiment", "mittel", "alle", True, "Kauf nur ab 30 unabhängigen Fällen mit gemessenem Vorsprung."),
    Haendler("Experiment", "Experiment", "kurz", "alle", True, "Isolierter Versuch: RSI 30 bis 40 und Schluss unter dem 20-Tage-Schnitt."),
)


_PROFIL = {
    "Momentum": {"daten": "Mindestens 21 Schlusskurse.", "merkmale": "Rendite über 20 und über 5 Tage.", "fehlt": ""},
    "RSI": {"daten": "Mindestens 15 Schlusskurse.", "merkmale": "RSI geteilt durch 100.", "fehlt": ""},
    "MACD": {"daten": "Mindestens 35 Schlusskurse oder ein schon berechnetes MACD.", "merkmale": "MACD-Linie und Signallinie.", "fehlt": ""},
    "Ausbruch": {"daten": "Mindestens 21 Schlusskurse.", "merkmale": "Abstand zum höchsten der vorigen 20 Schlüsse.", "fehlt": ""},
    "Trend": {"daten": "Mindestens 50 Schlusskurse.", "merkmale": "Abstand zum 50-Tage-Schnitt und ob der kurze Schnitt darüber liegt.", "fehlt": ""},
    "Gleitend": {"daten": "Mindestens 51 Schlusskurse.", "merkmale": "Kreuzung des 20- über den 50-Tage-Schnitt.", "fehlt": ""},
    "Volumen": {"daten": "Handelsvolumen je Tag.", "merkmale": "Kein Merkmal, weil das Volumen fehlt.", "fehlt": "Volumen ist nicht gespeichert."},
    "Volatilität": {"daten": "Schlusskurse für die Tagesstreuung.", "merkmale": "Gemessene Streuung.", "fehlt": ""},
    "Rücksetzer": {"daten": "Mindestens 200 Schlusskurse.", "merkmale": "Lage zu den Schnitten und RSI.", "fehlt": ""},
    "Kerze": {"daten": "Eröffnung, Hoch, Tief und Schluss.", "merkmale": "Kein Merkmal, weil nur Schlüsse vorliegen.", "fehlt": "Kerzen fehlen."},
    "Substanz": {"daten": "Eine Kaufnote aus dem KGV.", "merkmale": "Kein Merkmal.", "fehlt": "KGV ergibt keine Kaufnote."},
    "Wachstum": {"daten": "Eine Kaufnote aus dem Umsatzwachstum.", "merkmale": "Kein Merkmal.", "fehlt": "Umsatzwachstum ergibt keine Kaufnote."},
    "Qualität": {"daten": "Eine Kaufnote aus Marge und Rendite.", "merkmale": "Kein Merkmal.", "fehlt": "Qualität ergibt keine Kaufnote."},
    "Dividende": {"daten": "Eine Kaufnote aus der Dividende.", "merkmale": "Kein Merkmal.", "fehlt": "Dividende ergibt keine Kaufnote."},
    "Fundament": {"daten": "Mehrere Fundamentalnoten mit Kauf.", "merkmale": "Kein Merkmal.", "fehlt": "Der Mix ergibt keine Kaufnote."},
    "Nachrichten": {"daten": "Eine Meldung zum Entscheidungszeitpunkt.", "merkmale": "Kein Merkmal. Eine Meldung ist kein Kauf.", "fehlt": "Nachrichten begründen keinen Kauf."},
    "Stimmung": {"daten": "Der Ton einer Überschrift.", "merkmale": "Kein Merkmal.", "fehlt": "Stimmung begründet keinen Kauf."},
    "Quartal": {"daten": "Eine Quartalsmeldung.", "merkmale": "Kein Merkmal.", "fehlt": "Quartalsmeldungen begründen keinen Kauf."},
    "Makro": {"daten": "Eine Makromeldung.", "merkmale": "Kein Merkmal.", "fehlt": "Makromeldungen begründen keinen Kauf."},
    "Termin": {"daten": "Ein gespeicherter Terminkalender.", "merkmale": "Kein Merkmal.", "fehlt": "Es gibt keinen Terminkalender."},
    "Krypto": {"daten": "Schlusskurse eines *-USD-Namens.", "merkmale": "Dieselben Momentum-Merkmale.", "fehlt": ""},
    "ETF": {"daten": "Schlusskurse eines ETF.", "merkmale": "Dieselben Rücksetzer-Merkmale.", "fehlt": ""},
    "Large": {"daten": "Marktkapitalisierung.", "merkmale": "Kein Merkmal.", "fehlt": "Die Marktkapitalisierung fehlt."},
    "Small": {"daten": "Marktkapitalisierung.", "merkmale": "Kein Merkmal.", "fehlt": "Die Marktkapitalisierung fehlt."},
    "Defensiv": {"daten": "Trend und Streuung.", "merkmale": "Trendmerkmale nur bei niedriger Streuung.", "fehlt": ""},
    "Ensemble": {"daten": "Momentum, Trend, Gleitend und RSI gleichzeitig.", "merkmale": "Anteil der vier Regeln, die kaufen.", "fehlt": ""},
    "Adaptiv": {"daten": "Mindestens 30 eigene abgeschlossene Fälle.", "merkmale": "RSI, die Schwelle ändert der Lauf nicht.", "fehlt": "Die Schwelle bleibt fest, bis eine eigene Prüfung sie trägt."},
    "Conträr": {"daten": "RSI und 200 Schlusskurse.", "merkmale": "RSI und Lage zum langen Schnitt.", "fehlt": ""},
    "Statistik": {"daten": "Gemessenes Muster mit Qualität und Rang.", "merkmale": "Qualität und Rang des Musters.", "fehlt": ""},
    "Experiment": {"daten": "RSI und 20 Schlusskurse, isoliert.", "merkmale": "RSI und Lage zum kurzen Schnitt.", "fehlt": ""},
}


def von(name: str) -> Haendler | None:
    for haendler in HAENDLER:
        if haendler.name == name:
            return haendler
    return None


def entscheide(name: str, zeile, schluesse: tuple[float, ...] | None = None) -> tuple[str, str, tuple[float, ...] | None]:
    haendler = von(name)
    if haendler is None:
        return "SKIP", "Unbekannter Trader. Kein Kauf.", None
    reihe = _reihe(zeile) if schluesse is None else schluesse
    klasse = _klasse(zeile)
    if haendler.markt != "alle" and klasse != haendler.markt:
        return "SKIP", f"{haendler.name} handelt nur {haendler.markt}.", None
    funktion = _REGELN[name]
    return funktion(zeile, reihe)


def bewerten(pfad, name: str, zeile, schluesse: tuple[float, ...] | None = None) -> tuple[str, str, tuple[float, ...] | None, dict]:
    """Die Regel bleibt die Bedingung. Die eigenen Gewichte bewerten nur einen Kauf."""
    entscheidung, grund, merkmale = entscheide(name, zeile, schluesse)
    stand = {
        "signal": entscheidung,
        "version": _version(pfad, name),
        "wahrscheinlichkeit": None,
        "zuverlaessig": False,
    }
    if not merkmale or entscheidung == "SKIP":
        return entscheidung, grund, merkmale, stand
    modell = _modell_lesen(pfad, name)
    if modell is None or len(modell[0]) != len(merkmale):
        if entscheidung == "BUY":
            grund = grund + " Noch keine passenden Gewichte. Nicht zuverlässig."
        return entscheidung, grund, merkmale, stand
    from ki import Modell, wahrscheinlichkeit

    chance = wahrscheinlichkeit(Modell(modell[0], modell[1], modell[2]), merkmale)
    stand["wahrscheinlichkeit"] = round(chance, 4)
    stand["version"] = modell[3]
    if modell[2] < _ZUVERLAESSIG:
        grund = f"{grund} Modell mit {modell[2]} Fällen, nicht zuverlässig."
        return entscheidung, grund, merkmale, stand
    stand["zuverlaessig"] = True
    if entscheidung == "BUY" and chance < 0.5:
        grund = f"Die Regel würde kaufen. Das eigene Modell liegt bei {chance:.0%} und lässt es."
        return "HOLD", grund, merkmale, stand
    grund = f"{grund} Eigenes Modell {chance:.0%}, Version {modell[3]}."
    return entscheidung, grund, merkmale, stand


def runde(pfad, zeilen, namen: set[str], kurs, jetzt: datetime, nur_verkauf: bool) -> None:
    from papier import (
        _daten_hinweis,
        _lokal_kaufen,
        _lokal_konto,
        _lokales_guthaben,
        _marktwert,
        _positionen,
        _preis_eur,
        _spitze_konto,
        kauf_gesperrt,
    )

    _tabellen(pfad)
    for haendler in HAENDLER:
        if not haendler.einsatz:
            continue
        name = haendler.name
        from papier import _jetzt_merken

        _sleeve, cash, _equity = _lokales_guthaben(pfad, name)
        if not _hat_kontozeile(pfad, name):
            kapital_buchen(pfad, name, _START, "eroeffnung", jetzt.isoformat())
        bestand = _positionen(pfad, name)
        eigene = {str(zeile["symbol"]) for zeile in bestand}
        sperre = kauf_gesperrt(cash + _marktwert(pfad, name), *_spitze_konto(pfad, name, cash + _marktwert(pfad, name)), len(eigene))
        stops = {str(zeile["symbol"]): _zahl(zeile.get("stop")) for zeile in bestand}
        kauefe = 0
        for zeile in zeilen or ():
            symbol = str(_feld(zeile, "symbol") or "")
            if not symbol or (symbol not in namen and symbol not in eigene):
                continue
            preis = _preis_eur(zeile, kurs)
            if preis is None:
                _notiz(pfad, name, symbol, "SKIP", "Währung oder EUR/USD fehlt. Nicht gekauft.", {"signal": "SKIP"})
                continue
            if symbol in eigene:
                stop = stops.get(symbol)
                if stop is not None and preis <= stop:
                    ok, gutschrift = _schliessen(pfad, name, symbol, preis, jetzt, "Stop ist erreicht. Lokale Prüfung, keine Broker-Order.")
                    if ok:
                        cash += gutschrift
                        eigene.discard(symbol)
                    continue
                entscheidung, grund, _merkmale, stand = bewerten(pfad, name, zeile)
                if entscheidung == "SELL":
                    ok, gutschrift = _schliessen(pfad, name, symbol, preis, jetzt, grund)
                    if ok:
                        cash += gutschrift
                        eigene.discard(symbol)
                else:
                    _jetzt_merken(pfad, name, symbol, preis)
                    _notiz(pfad, name, symbol, "HOLD", grund, stand)
                continue
            if nur_verkauf or sperre or kauefe >= 3:
                continue
            hinweis = _daten_hinweis(zeile)
            if hinweis:
                _notiz(pfad, name, symbol, "SKIP", hinweis, {"signal": "SKIP"})
                continue
            entscheidung, grund, merkmale, stand = bewerten(pfad, name, zeile)
            if entscheidung != "BUY":
                _notiz(pfad, name, symbol, entscheidung if entscheidung in ("HOLD", "SKIP") else "SKIP", grund, stand)
                continue
            stop_mal = 1 if name == "Defensiv" else 2
            deckel = Decimal("0.04") if name == "Defensiv" else Decimal("0.08")
            kosten = _lokal_kaufen(pfad, name, zeile, preis, kurs, _START, cash, jetzt, stop_mal, deckel)
            if kosten <= 0:
                _notiz(pfad, name, symbol, "SKIP", "Die Menge passt nicht in Risiko, Cash oder Stückzahl.", stand)
                continue
            cash -= kosten + (kosten * _ANTEIL).quantize(Decimal("0.01"))
            kauefe += 1
            eigene.add(symbol)
            _fall_offen(pfad, haendler, symbol, merkmale, preis, kosten)
            _notiz(pfad, name, symbol, "BUY", grund, stand)
        _lokal_konto(pfad, name, _START, cash, _marktwert(pfad, name), kurs, jetzt)


def uebersicht(pfad) -> dict:
    _tabellen(pfad)
    _kapital_nachziehen(pfad)
    zeilen = []
    for haendler in HAENDLER:
        zeilen.append(_zeile(pfad, haendler))
    zeilen.sort(key=lambda zeile: (0 if zeile["belastbar"] else 1, -zeile["score"], zeile["name"]))
    for nummer, zeile in enumerate((zeile for zeile in zeilen if zeile["belastbar"]), start=1):
        zeile["platz"] = nummer
    bewertbar = [zeile for zeile in zeilen if zeile["belastbar"]]
    beste = max(bewertbar, key=lambda zeile: zeile["score"])["name"] if bewertbar else "noch keine ausreichende Stichprobe"
    schwach = min(bewertbar, key=lambda zeile: zeile["score"])["name"] if bewertbar else "noch keine ausreichende Stichprobe"
    lernzeit = _letzte_lernzeit(pfad)
    return {
        "anzahl": len(HAENDLER),
        "aktiv": sum(1 for haendler in HAENDLER if haendler.einsatz),
        "pause": sum(1 for haendler in HAENDLER if not haendler.einsatz),
        "beste": beste,
        "schwaechste": schwach,
        "lernen": lernzeit or "noch kein abgeschlossener Lernfall",
        "hinweis": "Simulation, getrennt vom Alpaca-Buch und vom öffentlichen Modell. Unter 20 abgeschlossenen Fällen gibt es keinen Sieger.",
        "ohne_daten": sum(1 for haendler in HAENDLER if not haendler.einsatz),
        "belastbar": len(bewertbar),
        "meta": _meta(zeilen),
        "meta_bericht": _meta_bericht(pfad, zeilen),
        "rangliste": zeilen,
        "zentrale": _zentrale(pfad, zeilen),
    }


def zurueck(pfad, name: str, version: int) -> bool:
    _tabellen(pfad)
    with sqlite3.connect(pfad) as verbindung:
        zeile = verbindung.execute(
            "SELECT gewichte, bias, beispiele FROM ki_haendler_version WHERE haendler = ? AND version = ?",
            (name, version),
        ).fetchone()
        if zeile is None:
            return False
        verbindung.execute(
            """
            INSERT INTO ki_haendler_modell (haendler, gewichte, bias, beispiele, version, zeit)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(haendler) DO UPDATE SET
                gewichte = excluded.gewichte, bias = excluded.bias,
                beispiele = excluded.beispiele, version = excluded.version, zeit = excluded.zeit
            """,
            (name, zeile[0], zeile[1], zeile[2], version, _jetzt()),
        )
        _version_schreiben(verbindung, name, version, zeile[0], zeile[1], zeile[2], f"zurück auf Version {version}")
    return True


def anpassen(pfad, name: str = "Adaptiv") -> str:
    """Ändert eine Schwelle nur, wenn die letzten Fälle die früheren schlagen."""
    _tabellen(pfad)
    with sqlite3.connect(pfad) as verbindung:
        faelle = verbindung.execute(
            "SELECT ergebnis FROM ki_haendler_fall WHERE haendler = ? AND ausstieg IS NOT NULL AND quelle = 'simulation' ORDER BY id",
            (name,),
        ).fetchall()
    if len(faelle) < 30:
        return "Zu wenige abgeschlossene Fälle. Schwelle bleibt."
    erste = [float(zeile[0]) > 0 for zeile in faelle[:20]]
    letzte = [float(zeile[0]) > 0 for zeile in faelle[-10:]]
    if sum(letzte) / len(letzte) <= sum(erste) / len(erste):
        return "Die letzten Fälle sind nicht besser. Schwelle bleibt."
    with sqlite3.connect(pfad) as verbindung:
        alt = verbindung.execute(
            "SELECT wert FROM ki_haendler_parameter WHERE haendler = ? AND schluessel = 'rsi'",
            (name,),
        ).fetchone()
        wert = 45.0 if alt is None else float(alt[0])
        neu = max(30.0, wert - 1.0)
        verbindung.execute(
            """
            INSERT INTO ki_haendler_parameter (haendler, schluessel, wert) VALUES (?, 'rsi', ?)
            ON CONFLICT(haendler, schluessel) DO UPDATE SET wert = excluded.wert
            """,
            (name, neu),
        )
    return f"RSI-Schwelle von {wert:.0f} auf {neu:.0f}. Nur wegen der späteren Fälle."


def _momentum(_zeile, reihe: tuple[float, ...]):
    if len(reihe) < 21 or reihe[-21] <= 0 or reihe[-6] <= 0:
        return "SKIP", "Zu wenige Schlüsse für das Momentum. Kein Kauf.", None
    lang = reihe[-1] / reihe[-21] - 1
    funf = reihe[-1] / reihe[-6] - 1
    merkmale = (lang, funf)
    if lang > 0.02 and funf > 0:
        return "BUY", "Der Schluss liegt nach 20 Tagen und nach 5 Tagen höher.", merkmale
    if lang < 0:
        return "SELL", "Die Bewegung über 20 Tage ist negativ.", merkmale
    return "HOLD", "Das Momentum ist nicht klar.", merkmale


def _rsi_bei(reihe: tuple[float, ...], unten: float, oben: float, verkauf: float):
    wert = rsi(reihe, 14) if len(reihe) >= 15 else None
    if wert is None:
        return "SKIP", "RSI fehlt. Kein Kauf.", None
    merkmale = (wert / 100.0,)
    if unten <= wert <= oben:
        return "BUY", f"RSI {wert:.0f} liegt im gesetzten Bereich.", merkmale
    if wert >= verkauf:
        return "SELL", f"RSI {wert:.0f} ist hoch.", merkmale
    return "HOLD", f"RSI {wert:.0f} löst nichts aus.", merkmale


def _rsi(_zeile, reihe):
    return _rsi_bei(reihe, 30, 45, 70)


def _macd(_zeile, reihe):
    wert = macd_rechnung(reihe) if len(reihe) >= 35 else None
    if wert is None:
        linie = getattr(_feld(_zeile, "technik"), "macd", None)
        signal = getattr(_feld(_zeile, "technik"), "macd_signal", None)
        if linie is None or signal is None:
            return "SKIP", "MACD fehlt. Kein Kauf.", None
        wert = (float(linie), float(signal), float(linie) - float(signal))
    linie, signal, hist = wert
    merkmale = (linie, signal)
    if hist > 0 and linie > signal:
        return "BUY", "Die MACD-Linie liegt über der Signallinie.", merkmale
    if hist < 0:
        return "SELL", "Die MACD-Linie liegt unter der Signallinie.", merkmale
    return "HOLD", "Der MACD zeigt keinen Wechsel.", merkmale


def _ausbruch(_zeile, reihe):
    if len(reihe) < 21:
        return "SKIP", "Zu wenige Schlüsse für den Ausbruch. Kein Kauf.", None
    grenze = max(reihe[-21:-1])
    merkmale = (reihe[-1] / grenze - 1 if grenze else 0.0,)
    if grenze > 0 and reihe[-1] > grenze:
        return "BUY", "Der Schluss liegt über dem höchsten Schluss der vorigen 20 Tage.", merkmale
    return "HOLD", "Kein Ausbruch über die vorigen Schlüsse.", merkmale


def _trend(_zeile, reihe):
    kurz = sma(reihe, 20)
    lang = sma(reihe, 50)
    if kurz is None or lang is None or lang == 0:
        return "SKIP", "Der gleitende Schnitt fehlt. Kein Kauf.", None
    merkmale = (reihe[-1] / lang - 1, 1.0 if kurz > lang else 0.0)
    if reihe[-1] > kurz > lang:
        return "BUY", "Der Schluss liegt über dem 20- und dem 50-Tage-Schnitt.", merkmale
    if reihe[-1] < lang:
        return "SELL", "Der Schluss liegt unter dem 50-Tage-Schnitt.", merkmale
    return "HOLD", "Kein klarer Trend.", merkmale


def _gleitend(_zeile, reihe):
    if len(reihe) < 51:
        return "SKIP", "Zu wenige Schlüsse für die Kreuzung. Kein Kauf.", None
    jetzt_kurz = sma(reihe, 20)
    jetzt_lang = sma(reihe, 50)
    vorher_kurz = sma(reihe[:-1], 20)
    vorher_lang = sma(reihe[:-1], 50)
    if None in (jetzt_kurz, jetzt_lang, vorher_kurz, vorher_lang):
        return "SKIP", "Der gleitende Schnitt fehlt. Kein Kauf.", None
    merkmale = (jetzt_kurz - jetzt_lang,)
    if vorher_kurz <= vorher_lang and jetzt_kurz > jetzt_lang:
        return "BUY", "Der 20-Tage-Schnitt kreuzt den 50-Tage-Schnitt nach oben.", merkmale
    if jetzt_kurz < jetzt_lang:
        return "SELL", "Der kurze Schnitt liegt unter dem langen.", merkmale
    return "HOLD", "Keine neue Kreuzung.", merkmale


def _volumen(_zeile, _reihe):
    return "SKIP", "Volumen liegt in den gespeicherten Kursen nicht vor. Kein Kauf.", None


def _volatil(_zeile, reihe):
    wert = volatilitaet_rechnung(reihe)
    if wert is None:
        return "SKIP", "Die Streuung fehlt. Kein Kauf.", None
    merkmale = (wert,)
    if 0 < wert < 0.03:
        return "BUY", "Die gemessene Tagesstreuung liegt unter 3 Prozent.", merkmale
    return "HOLD", "Die Streuung ist für diesen Trader zu hoch oder leer.", merkmale


def _ruecksetzer(_zeile, reihe):
    lang = sma(reihe, 200)
    kurz = sma(reihe, 20)
    wert = rsi(reihe, 14) if len(reihe) >= 15 else None
    if lang is None or kurz is None or wert is None:
        return "SKIP", "Für den Rücksetzer fehlen 200 Tage oder der RSI. Kein Kauf.", None
    merkmale = (reihe[-1] / lang - 1, wert / 100.0)
    if reihe[-1] > lang and reihe[-1] <= kurz and 30 <= wert <= 55:
        return "BUY", "Rücksetzer über dem langen Schnitt.", merkmale
    return "HOLD", "Der Rücksetzer ist nicht da.", merkmale


def _kerze(_zeile, _reihe):
    return "SKIP", "Es sind nur Schlusskurse gespeichert, keine Kerzen. Kein Kauf.", None


def _fundament(zeile, feld: str, satz: str):
    text = str(_feld(zeile, "fundamental") or "")
    if not text or text == "fehlt" or feld not in text:
        return "SKIP", f"{feld} fehlt. Kein Kauf.", None
    return "SKIP", satz, None


def _substanz(zeile, _reihe):
    return _fundament(zeile, "KGV", "Das KGV ist keine Kaufnote. Kein Kauf.")


def _wachstum(zeile, _reihe):
    return _fundament(zeile, "Umsatzwachstum", "Umsatzwachstum ist keine Kaufnote. Kein Kauf.")


def _qualitaet(zeile, _reihe):
    return _fundament(zeile, "Gewinnmarge", "Die Qualitätskennzahlen sind keine Kaufnote. Kein Kauf.")


def _dividende(zeile, _reihe):
    return _fundament(zeile, "Dividendenrendite", "Die Dividendenrendite ist keine Kaufnote. Kein Kauf.")


def _fundament_mix(zeile, _reihe):
    text = str(_feld(zeile, "fundamental") or "")
    if text in ("", "fehlt"):
        return "SKIP", "Fundamentaldaten fehlen. Kein Kauf.", None
    return "SKIP", "Mehrere Kennzahlen bleiben ein Hinweis, keine Kaufnote.", None


def _news(zeile, art: str, satz: str):
    gesehen = str(_feld(zeile, "news_art") or "")
    if not gesehen:
        return "SKIP", "Keine Nachricht zum Entscheidungszeitpunkt. Kein Kauf.", None
    if gesehen != art:
        return "SKIP", f"Die Meldung ist {gesehen}, nicht {art}. Kein Kauf.", None
    return "SKIP", satz, None


def _nachrichten(zeile, _reihe):
    return _news(zeile, "unternehmen", "Eine Unternehmensmeldung ist kein Kaufgrund.")


def _stimmung(zeile, _reihe):
    ton = str(_feld(zeile, "news_ton") or "")
    if not ton:
        return "SKIP", "Der Ton der Meldung fehlt. Kein Kauf.", None
    return "SKIP", "Der Ton einer Überschrift ist kein Kaufgrund.", None


def _quartal(zeile, _reihe):
    return _news(zeile, "quartal", "Eine Quartalsmeldung ist kein Auftrag.")


def _makro(zeile, _reihe):
    return _news(zeile, "makro", "Eine Makromeldung ist kein Kaufgrund.")


def _termin(_zeile, _reihe):
    return "SKIP", "Es ist kein Terminkalender gespeichert. Kein Kauf.", None


def _krypto(zeile, reihe):
    if not str(_feld(zeile, "symbol") or "").upper().endswith("-USD"):
        return "SKIP", "Das ist kein Krypto-Name.", None
    return _momentum(zeile, reihe)


def _etf(zeile, reihe):
    if _klasse(zeile) != "etf":
        return "SKIP", "Das ist kein ETF.", None
    return _ruecksetzer(zeile, reihe)


def _large(_zeile, _reihe):
    return "SKIP", "Die Marktkapitalisierung fehlt. Die Indexliste ist kein Größenmaß.", None


def _small(_zeile, _reihe):
    return "SKIP", "Die Marktkapitalisierung fehlt. Keine Small-Cap-Auswahl.", None


def _defensiv(zeile, reihe):
    name, _grund, merkmale = _trend(zeile, reihe)
    wert = volatilitaet_rechnung(reihe)
    if wert is None:
        return "SKIP", "Die Streuung fehlt. Defensiv kauft nicht.", None
    if name == "BUY" and wert < 0.015:
        return "BUY", "Ruhiger Aufwärtstrend. Engerer Stop.", merkmale
    return "HOLD", "Trend oder Streuung passen nicht zur defensiven Regel.", merkmale


def _ensemble(zeile, reihe):
    stimmen = [_momentum(zeile, reihe), _trend(zeile, reihe), _gleitend(zeile, reihe), _rsi(zeile, reihe)]
    if any(stimme[0] == "SKIP" for stimme in stimmen):
        return "SKIP", "Das Ensemble ist unvollständig, weil eine Grundlage fehlt. Kein Kauf.", None
    kaeufe = sum(1 for stimme in stimmen if stimme[0] == "BUY")
    merkmale = (kaeufe / 4,)
    if kaeufe >= 3:
        return "BUY", f"{kaeufe} von 4 technischen Stimmen sind für einen Kauf.", merkmale
    return "HOLD", f"Nur {kaeufe} von 4 Stimmen. Kein Kauf.", merkmale


def _adaptiv(zeile, reihe):
    return _rsi_bei(reihe, 30, 45, 70)


def _contraer(_zeile, reihe):
    wert = rsi(reihe, 14) if len(reihe) >= 15 else None
    lang = sma(reihe, 200)
    if wert is None or lang is None:
        return "SKIP", "RSI oder der lange Schnitt fehlt. Kein Kauf.", None
    merkmale = (wert / 100.0,)
    if wert < 35 and reihe[-1] > lang:
        return "BUY", "Niedriger RSI über dem langen Schnitt.", merkmale
    if wert > 65:
        return "SELL", "Der RSI ist nicht mehr niedrig.", merkmale
    return "HOLD", "Kein conträrer Fall.", merkmale


def _statistik(zeile, _reihe):
    muster = _feld(zeile, "muster")
    muster = muster if isinstance(muster, dict) else {}
    qualitaet = str(muster.get("qualitaet") or "")
    rang = muster.get("rang")
    if qualitaet in ("vorsichtig", "belastbarer") and isinstance(rang, (int, float)):
        return "BUY", "Mindestens 30 unabhängige Fälle mit gemessenem Vorsprung.", (float(rang),)
    return "SKIP", "Die statistische Basis reicht nicht. Kein Kauf.", None


def _experiment(_zeile, reihe):
    wert = rsi(reihe, 14) if len(reihe) >= 15 else None
    kurz = sma(reihe, 20)
    if wert is None or kurz is None:
        return "SKIP", "RSI oder der kurze Schnitt fehlt. Kein Kauf.", None
    merkmale = (wert / 100.0,)
    if 30 <= wert <= 40 and reihe[-1] < kurz:
        return "BUY", "Isolierter Versuch unter dem kurzen Schnitt. Gilt nur für dieses Buch.", merkmale
    return "HOLD", "Der isolierte Versuch ist nicht ausgelöst.", merkmale


_REGELN = {
    "Momentum": _momentum,
    "RSI": _rsi,
    "MACD": _macd,
    "Ausbruch": _ausbruch,
    "Trend": _trend,
    "Gleitend": _gleitend,
    "Volumen": _volumen,
    "Volatilität": _volatil,
    "Rücksetzer": _ruecksetzer,
    "Kerze": _kerze,
    "Substanz": _substanz,
    "Wachstum": _wachstum,
    "Qualität": _qualitaet,
    "Dividende": _dividende,
    "Fundament": _fundament_mix,
    "Nachrichten": _nachrichten,
    "Stimmung": _stimmung,
    "Quartal": _quartal,
    "Makro": _makro,
    "Termin": _termin,
    "Krypto": _krypto,
    "ETF": _etf,
    "Large": _large,
    "Small": _small,
    "Defensiv": _defensiv,
    "Ensemble": _ensemble,
    "Adaptiv": _adaptiv,
    "Conträr": _contraer,
    "Statistik": _statistik,
    "Experiment": _experiment,
}


def _schliessen(pfad, name: str, symbol: str, preis: Decimal, jetzt: datetime, grund: str) -> tuple[bool, Decimal]:
    from papier import _lokal_verkaufen, _positionen

    position = next((eintrag for eintrag in _positionen(pfad, name) if eintrag["symbol"] == symbol), None)
    if position is None:
        return False, Decimal(0)
    if not _lokal_verkaufen(pfad, name, symbol, preis, jetzt):
        _notiz(pfad, name, symbol, "SKIP", "Verkauf nicht ausgeführt. Kein Lernfall.", {"signal": "SELL"})
        return False, Decimal(0)
    _fall_zu(pfad, name, symbol, position, preis)
    _notiz(pfad, name, symbol, "SELL", grund, {"signal": "SELL"})
    menge = _zahl(position.get("menge")) or Decimal(0)
    _brutto, _ein, aus, _netto = _kosten(_zahl(position.get("einstieg")) or Decimal(0), preis, menge)
    return True, preis * menge - aus


def _notiz(pfad, name: str, symbol: str, entscheidung: str, grund: str, stand: dict | None = None) -> None:
    stand = stand or {}
    _tabellen(pfad)
    with sqlite3.connect(pfad) as verbindung:
        verbindung.execute(
            """
            INSERT INTO ki_haendler_entscheidung
            (haendler, symbol, entscheidung, grund, zeit, version, signal, wahrscheinlichkeit, zuverlaessig)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                name,
                symbol,
                entscheidung,
                grund,
                _jetzt(),
                stand.get("version"),
                stand.get("signal") or entscheidung,
                None if stand.get("wahrscheinlichkeit") is None else str(stand["wahrscheinlichkeit"]),
                1 if stand.get("zuverlaessig") else 0,
            ),
        )


def _fall_offen(pfad, haendler: Haendler, symbol: str, merkmale, preis: Decimal, notional: Decimal | None = None) -> None:
    if not merkmale:
        return
    betrag = notional if notional is not None else preis
    ein = (betrag * _ANTEIL).quantize(Decimal("0.01")) if betrag is not None else Decimal(0)
    with sqlite3.connect(pfad) as verbindung:
        offen = verbindung.execute(
            "SELECT id FROM ki_haendler_fall WHERE haendler = ? AND symbol = ? AND ausstieg IS NULL",
            (haendler.name, symbol),
        ).fetchone()
        if offen is not None:
            return
        verbindung.execute(
            """
            INSERT INTO ki_haendler_fall
            (haendler, symbol, horizont, merkmale, einstieg, kosten, benchmark, quelle, gelernt, zeit, gebuehr_einstieg, spread, slippage)
            VALUES (?, ?, ?, ?, ?, ?, 'nicht gemessen', 'simulation', 0, ?, ?, 'nicht gemessen', 'nicht gemessen')
            """,
            (
                haendler.name,
                symbol,
                haendler.horizont,
                json.dumps(list(merkmale)),
                str(preis),
                "Annahme 0,125 Prozent vom Einstieg und 0,125 Prozent vom Ausstieg. Spread und Slippage nicht gemessen.",
                _jetzt(),
                str(ein),
            ),
        )


def _fall_zu(pfad, name: str, symbol: str, position: dict, preis: Decimal) -> None:
    einstieg = _zahl(position.get("einstieg"))
    menge = _zahl(position.get("menge"))
    if einstieg is None or menge is None:
        return
    brutto, ein, aus, netto = _kosten(einstieg, preis, menge)
    with sqlite3.connect(pfad) as verbindung:
        zeile = verbindung.execute(
            """
            SELECT id, merkmale, gelernt FROM ki_haendler_fall
            WHERE haendler = ? AND symbol = ? AND ausstieg IS NULL ORDER BY id DESC LIMIT 1
            """,
            (name, symbol),
        ).fetchone()
        if zeile is None:
            return
        verbindung.execute(
            """
            UPDATE ki_haendler_fall
            SET ausstieg = ?, ergebnis = ?, brutto = ?, gebuehr_einstieg = ?, gebuehr_ausstieg = ?,
                spread = 'nicht gemessen', slippage = 'nicht gemessen', ausstieg_zeit = ?, menge = ?
            WHERE id = ?
            """,
            (str(preis), str(netto), str(brutto), str(ein), str(aus), _jetzt(), str(menge), zeile[0]),
        )
    if zeile[2]:
        return
    try:
        merkmale = tuple(float(wert) for wert in json.loads(zeile[1]))
    except (TypeError, json.JSONDecodeError):
        return
    if not merkmale:
        return
    _lerne(pfad, name, merkmale, 1.0 if netto > 0 else 0.0, zeile[0])


def _lerne(pfad, name: str, merkmale: tuple[float, ...], ziel: float, fall: int) -> None:
    from ki import Modell, schritt

    with sqlite3.connect(pfad) as verbindung:
        aktuell = _modell(verbindung, name, len(merkmale))
        if len(aktuell[0]) != len(merkmale):
            return
        _version_schreiben(verbindung, name, aktuell[3], json.dumps(aktuell[0]), aktuell[1], aktuell[2], "vor dem Lernschritt")
        neu = schritt(Modell(aktuell[0], aktuell[1], aktuell[2]), merkmale, ziel)
        version = aktuell[3] + 1
        verbindung.execute(
            """
            INSERT INTO ki_haendler_modell (haendler, gewichte, bias, beispiele, version, zeit)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(haendler) DO UPDATE SET
                gewichte = excluded.gewichte, bias = excluded.bias,
                beispiele = excluded.beispiele, version = excluded.version, zeit = excluded.zeit
            """,
            (name, json.dumps(neu.gewichte), neu.bias, neu.beispiele, version, _jetzt()),
        )
        _version_schreiben(verbindung, name, version, json.dumps(neu.gewichte), neu.bias, neu.beispiele, "Lernschritt aus abgeschlossenem Fall")
        verbindung.execute("UPDATE ki_haendler_fall SET gelernt = 1 WHERE id = ?", (fall,))


def _kosten(einstieg: Decimal, ausstieg: Decimal, menge: Decimal) -> tuple[Decimal, Decimal, Decimal, Decimal]:
    """Annahme je Seite 0,125 Prozent. Spread und Slippage sind nicht gemessen."""
    brutto = ((ausstieg - einstieg) * menge).quantize(Decimal("0.01"))
    ein = (einstieg * menge * _ANTEIL).quantize(Decimal("0.01"))
    aus = (ausstieg * menge * _ANTEIL).quantize(Decimal("0.01"))
    return brutto, ein, aus, (brutto - ein - aus).quantize(Decimal("0.01"))


def _modell_lesen(pfad, name: str):
    if pfad is None or not pfad.exists():
        return None
    with sqlite3.connect(pfad) as verbindung:
        tabellen = {zeile[0] for zeile in verbindung.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
        if "ki_haendler_modell" not in tabellen:
            return None
        zeile = verbindung.execute(
            "SELECT gewichte, bias, beispiele, version FROM ki_haendler_modell WHERE haendler = ?",
            (name,),
        ).fetchone()
    if zeile is None:
        return None
    return tuple(float(wert) for wert in json.loads(zeile[0])), float(zeile[1]), int(zeile[2]), int(zeile[3])


def _modell(verbindung, name: str, laenge: int) -> tuple[tuple[float, ...], float, int, int]:
    zeile = verbindung.execute(
        "SELECT gewichte, bias, beispiele, version FROM ki_haendler_modell WHERE haendler = ?",
        (name,),
    ).fetchone()
    if zeile is None:
        gewichte = (0.0,) * laenge
        verbindung.execute(
            "INSERT INTO ki_haendler_modell (haendler, gewichte, bias, beispiele, version, zeit) VALUES (?, ?, 0, 0, 1, ?)",
            (name, json.dumps(gewichte), _jetzt()),
        )
        _version_schreiben(verbindung, name, 1, json.dumps(gewichte), 0.0, 0, "Start")
        return gewichte, 0.0, 0, 1
    return tuple(float(wert) for wert in json.loads(zeile[0])), float(zeile[1]), int(zeile[2]), int(zeile[3])


def _version_schreiben(verbindung, name: str, version: int, gewichte: str, bias: float, beispiele: int, grund: str) -> None:
    verbindung.execute(
        """
        INSERT INTO ki_haendler_version (haendler, version, gewichte, bias, beispiele, grund, zeit)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (name, version, gewichte, bias, beispiele, grund, _jetzt()),
    )


def _zeile(pfad, haendler: Haendler) -> dict:
    faelle = _abgeschlossen(pfad, haendler.name)
    netto = [fall[0] for fall in faelle]
    rechnung = kennzahlen_aus(netto)
    renditen = [fall[1] for fall in faelle]
    dd = _drawdown(pfad, haendler.name)
    score = 0.0
    belastbar = False
    platz = None
    if len(netto) >= _MINDEST:
        mittel = sum(renditen) / len(renditen)
        streuung = math.sqrt(sum((wert - mittel) ** 2 for wert in renditen) / len(renditen)) if renditen else 0
        untere = mittel - 1.96 * streuung / math.sqrt(len(renditen))
        belastbar = untere > 0
        score = untere * min(len(netto), 60) / 60
    sharpe, sortino = _quoten_aus_equity(pfad, haendler.name)
    detail = _detail(pfad, haendler.name)
    pruefung = detail.get("pruefung") or {}
    zeile = {
        "name": haendler.name,
        "gruppe": haendler.gruppe,
        "horizont": haendler.horizont,
        "einsatz": haendler.einsatz,
        "status": "Wettbewerb" if haendler.einsatz else "pausiert",
        "markt": haendler.markt,
        "daten": _PROFIL[haendler.name]["daten"],
        "merkmale_text": _PROFIL[haendler.name]["merkmale"],
        "fehlt": _PROFIL[haendler.name]["fehlt"],
        "regel": haendler.regel,
        "version": _version(pfad, haendler.name),
        "trades": rechnung["trades"],
        "quote": rechnung["quote"],
        "gewinn": rechnung["gewinn_text"],
        "verlust": rechnung["verlust_text"],
        "ergebnis": rechnung["ergebnis_text"],
        "ergebnis_zahl": rechnung["realisiert"],
        "rendite": _rendite(pfad, haendler.name),
        "drawdown": _KENNZAHL if dd is None else f"{dd:.1%}",
        "sharpe": sharpe,
        "sortino": sortino,
        "faktor": rechnung["faktor_text"],
        "benchmark": "nicht gemessen",
        "belastbar": belastbar,
        "score": score,
        "platz": platz,
        "quelle": "simulation",
        "letzte": _letzte(pfad, haendler.name),
        "lernstatus": _lernstatus(pfad, haendler.name),
        "detail": detail,
        "treffer_zahl": rechnung["treffer"],
        "verlust_zahl": rechnung["verluste"],
        "erfolg_zahl": rechnung["erfolg"],
        "erfolg": rechnung["erfolg_text"],
        "rendite_zahl": _rendite_zahl(pfad, haendler.name),
        "dd_zahl": dd,
        "faktor_zahl": rechnung["faktor"],
        "realisiert_zahl": rechnung["realisiert"],
        "gewinn_summe": rechnung["gewinn_summe"],
        "verlust_summe": rechnung["verlust_summe"],
        "unrealisiert_zahl": _unrealisiert(detail.get("offen") or []),
        "letzter": _letzter_trade(pfad, haendler.name),
        "haltung": _haltung(pfad, haendler.name),
        "serie": _serie(netto),
        "validierung": pruefung.get("status") or "Nicht ausreichend Daten",
    }
    return zeile


def _rendite_zahl(pfad, name: str) -> float | None:
    werte = _equity_reihe(pfad, name)
    basis = _basis_name(pfad, name)
    if not werte or basis is None or basis <= 0:
        return None
    return (werte[-1] / float(basis) - 1) * 100


def _unrealisiert(offen: list[dict]) -> float | None:
    if not offen:
        return None
    if any(zeile.get("kurs_fehlt") for zeile in offen):
        return None
    summe = Decimal(0)
    for zeile in offen:
        einstieg = _zahl(zeile.get("einstieg"))
        jetzt = _zahl(zeile.get("jetzt"))
        menge = _zahl(zeile.get("menge"))
        if einstieg is None or jetzt is None or menge is None:
            return None
        summe += (jetzt - einstieg) * menge
    return float(summe)


def kennzahlen_aus(netto: list[Decimal]) -> dict:
    """Eine Rechnung für Dashboard, Rangliste und Trader-Detail."""
    if not netto:
        return {
            "trades": 0,
            "treffer": None,
            "verluste": None,
            "erfolg": None,
            "erfolg_text": "Keine Daten",
            "quote": "Keine Daten",
            "realisiert": None,
            "gewinn_text": "Keine Daten",
            "verlust_text": "Keine Daten",
            "gewinn_summe": None,
            "verlust_summe": None,
            "faktor": None,
            "faktor_text": "Keine Daten",
            "ergebnis_text": "Keine Daten",
        }
    treffer = [wert for wert in netto if wert > 0]
    verluste = [wert for wert in netto if wert < 0]
    summe = sum(netto, Decimal(0))
    gewinn_summe = sum(treffer, Decimal(0))
    verlust_summe = sum(verluste, Decimal(0))
    erfolg = len(treffer) / len(netto)
    faktor = None
    if len(netto) >= _MINDEST and verlust_summe < 0:
        faktor = float(gewinn_summe / abs(verlust_summe))
    return {
        "trades": len(netto),
        "treffer": len(treffer),
        "verluste": len(verluste),
        "erfolg": erfolg,
        "erfolg_text": f"{erfolg * 100:.1f} % aus {len(netto)} Trades",
        "quote": f"{len(treffer)}/{len(netto)}",
        "realisiert": float(summe),
        "gewinn_text": "Keine Daten" if not treffer else f"{gewinn_summe / len(treffer):.2f}",
        "verlust_text": "Keine Daten" if not verluste else f"{verlust_summe / len(verluste):.2f}",
        "gewinn_summe": float(gewinn_summe),
        "verlust_summe": float(verlust_summe),
        "faktor": faktor,
        "faktor_text": "Nicht ausreichend Daten" if faktor is None else f"{faktor:.2f}",
        "ergebnis_text": f"{summe:.2f}",
    }


def _letzter_trade(pfad, name: str) -> str:
    if not pfad.exists():
        return "Keine Daten"
    with sqlite3.connect(pfad) as verbindung:
        zeile = verbindung.execute(
            """
            SELECT COALESCE(ausstieg_zeit, zeit) FROM ki_haendler_fall
            WHERE haendler = ? AND ausstieg IS NOT NULL AND quelle = 'simulation' AND ergebnis IS NOT NULL
            ORDER BY id DESC LIMIT 1
            """,
            (name,),
        ).fetchone()
    return "Keine Daten" if zeile is None else str(zeile[0])


def _haltung(pfad, name: str) -> str:
    if not pfad.exists():
        return "Keine Daten"
    with sqlite3.connect(pfad) as verbindung:
        spalten = {str(zeile[1]) for zeile in verbindung.execute("PRAGMA table_info(ki_haendler_fall)")}
        if "ausstieg_zeit" not in spalten:
            return "Keine Daten"
        zeilen = verbindung.execute(
            """
            SELECT zeit, ausstieg_zeit FROM ki_haendler_fall
            WHERE haendler = ? AND ausstieg IS NOT NULL AND quelle = 'simulation'
            AND zeit IS NOT NULL AND ausstieg_zeit IS NOT NULL
            """,
            (name,),
        ).fetchall()
    dauer = []
    for start, ende in zeilen:
        beginn = _zeit_lesen(start)
        schluss = _zeit_lesen(ende)
        if beginn is None or schluss is None:
            continue
        dauer.append((schluss - beginn).total_seconds())
    if not dauer:
        return "Keine Daten"
    stunden = sum(dauer) / len(dauer) / 3600
    return f"{stunden:.1f} Stunden aus {len(dauer)} Trades"


def _serie(netto: list[Decimal]) -> str:
    if not netto:
        return "Keine Daten"
    gewinn = verlust = lauf = 0
    letzte = 0
    for wert in netto:
        richtung = 1 if wert > 0 else -1 if wert < 0 else 0
        if richtung == 0 or richtung != letzte:
            lauf = 1 if richtung else 0
        else:
            lauf += 1
        letzte = richtung
        gewinn = max(gewinn, lauf if richtung == 1 else 0)
        verlust = max(verlust, lauf if richtung == -1 else 0)
    return f"{gewinn} Gewinne, {verlust} Verluste in Folge"


def _zentrale(pfad, zeilen: list[dict]) -> dict:
    trades = sum(zeile["trades"] for zeile in zeilen)
    treffer = sum(zeile["treffer_zahl"] or 0 for zeile in zeilen)
    gewinn_summe = sum(zeile["gewinn_summe"] for zeile in zeilen if zeile["gewinn_summe"] is not None)
    verlust_summe = sum(zeile["verlust_summe"] for zeile in zeilen if zeile["verlust_summe"] is not None)
    realisiert = [zeile["realisiert_zahl"] for zeile in zeilen if zeile["realisiert_zahl"] is not None]
    kurs_fehlt = any(
        any(position.get("kurs_fehlt") for position in (zeile.get("detail") or {}).get("offen") or [])
        for zeile in zeilen
    )
    unrealisiert = None if kurs_fehlt else [
        zeile["unrealisiert_zahl"] for zeile in zeilen if zeile["unrealisiert_zahl"] is not None
    ]
    kurven = []
    for zeile in zeilen:
        punkte = (zeile.get("detail") or {}).get("punkte") or []
        if len(punkte) >= 2:
            kurven.append({"name": zeile["name"], "punkte": punkte})
    verlauf = _gesamt_verlauf(pfad)
    gesamt = verlauf["punkte"]
    buecher = _letzte_buecher(pfad)
    kapital = _kapital_summe(pfad)
    equity = None if not buecher or any(buch["equity"] is None for buch in buecher) else sum(buch["equity"] for buch in buecher)
    cash = None if not buecher or any(buch["cash"] is None for buch in buecher) else sum(buch["cash"] for buch in buecher)
    rendite = None if kapital is None or equity is None or kapital <= 0 else (equity / kapital - 1) * 100
    tief = None if verlauf["veraltet"] or verlauf["unvollstaendig"] else verlauf["drawdown"]
    faktor = None
    if trades >= _MINDEST and verlust_summe < 0:
        faktor = gewinn_summe / abs(verlust_summe)
    return {
        "trades": trades,
        "kapital": "Keine Daten" if kapital is None else f"{kapital:.2f}",
        "equity": "Keine Daten" if equity is None else f"{equity:.2f}",
        "cash": "Keine Daten" if cash is None else f"{cash:.2f}",
        "erfolg": "Keine Daten" if trades == 0 else f"{treffer / trades * 100:.1f} % aus {trades} abgeschlossenen Trades",
        "realisiert": "Keine Daten" if not realisiert else f"{sum(realisiert):.2f}",
        "unrealisiert": "Keine Daten" if not unrealisiert else f"{sum(unrealisiert):.2f}",
        "rendite": "Keine Daten" if rendite is None else f"{rendite:.1f} %",
        "drawdown": "Nicht ausreichend Daten" if verlauf["veraltet"] or verlauf["unvollstaendig"] else ("Keine Daten" if tief is None else f"{tief:.1%}"),
        "faktor": "Keine Daten" if trades == 0 else ("Nicht ausreichend Daten" if faktor is None else f"{faktor:.2f}"),
        "equity_buecher": len(buecher),
        "offen": sum(len((zeile.get("detail") or {}).get("offen") or []) for zeile in zeilen),
        "kurven": kurven,
        "gesamt": gesamt[-500:],
        "realisiert_punkte": _realisiert_punkte(pfad),
        "aktualitaet": _aktualitaet(pfad, buecher, kurs_fehlt),
        "hinweis": (
            "Die gezeichnete Kurve lässt neue Bücher und Einzahlungen weg. Die Equity-Zahl bleibt die Summe der Bücher. "
            "Rendite ist Gesamt-Equity gegen das gespeicherte Kapital, kein Mittel der Einzelprozente. "
            "Drawdown nutzt die kapitalbereinigte Kurve. Ein veralteter Stand ergibt keinen Risiko-Prozentwert. "
            "Spread und Slippage sind nicht gemessen. Sharpe je Equity-Stand, nicht annualisiert. "
            + verlauf["hinweis"]
        ),
        "zeit_hinweis": "Der Zeitraum filtert nur die Diagramme. Kennzahlen gelten für den gesamten gespeicherten Zeitraum.",
    }


def _letzte_buecher(pfad) -> list[dict]:
    if not pfad.exists():
        return []
    namen = {haendler.name for haendler in HAENDLER}
    with sqlite3.connect(pfad) as verbindung:
        tabellen = {zeile[0] for zeile in verbindung.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
        if "paper_konto" not in tabellen:
            return []
        zeilen = verbindung.execute(
            """
            SELECT konto, cash, equity, zeit FROM paper_konto
            WHERE broker = 'Lokal' AND id IN (
                SELECT MAX(id) FROM paper_konto WHERE broker = 'Lokal' GROUP BY konto
            )
            """
        ).fetchall()
    buecher = []
    for konto, cash, equity, zeit in zeilen:
        if konto not in namen:
            continue
        buecher.append({"name": konto, "cash": _zahl(cash), "equity": _zahl(equity), "zeit": zeit})
    return buecher


_REBASE = {"zuruecksetzen", "wiederherstellung", "schliessen"}


def kapital_buchen(pfad, name: str, betrag: Decimal, art: str, zeit: str) -> bool:
    """Hängt eine Kapitalbewegung an. Alte Zeilen bleiben unverändert."""
    _tabellen(pfad)
    stempel = _zeit_lesen(zeit)
    if stempel is None or art not in {"eroeffnung", "erster Stand", "einzahlung", "auszahlung", "zuruecksetzen", "wiederherstellung", "schliessen"}:
        return False
    with sqlite3.connect(pfad) as verbindung:
        vorhanden = verbindung.execute(
            "SELECT id, basis FROM ki_haendler_kapital WHERE haendler = ? ORDER BY zeit, id",
            (name,),
        ).fetchall()
        if art in {"eroeffnung", "erster Stand"} and vorhanden:
            return False
        aktuell = Decimal(0) if not vorhanden else (_zahl(vorhanden[-1][1]) or Decimal(0))
        if art == "schliessen":
            neu = Decimal(0)
        elif art in {"eroeffnung", "erster Stand", "zuruecksetzen", "wiederherstellung"}:
            if betrag is None or betrag < 0:
                return False
            neu = betrag
        elif art == "einzahlung":
            neu = aktuell + abs(betrag)
        else:
            neu = aktuell - abs(betrag)
            if neu < 0:
                return False
        verbindung.execute(
            """
            INSERT INTO ki_haendler_kapital (haendler, delta, basis, art, zeit)
            VALUES (?, ?, ?, ?, ?)
            """,
            (name, str((neu - aktuell).quantize(Decimal("0.01"))), str(neu.quantize(Decimal("0.01"))), art, stempel.isoformat()),
        )
    return True


def _hat_kontozeile(pfad, name: str) -> bool:
    if not pfad.exists():
        return False
    with sqlite3.connect(pfad) as verbindung:
        tabellen = {zeile[0] for zeile in verbindung.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
        if "paper_konto" not in tabellen:
            return False
        zeile = verbindung.execute(
            "SELECT 1 FROM paper_konto WHERE broker = 'Lokal' AND konto = ? LIMIT 1",
            (name,),
        ).fetchone()
    return zeile is not None


def _kapital_nachziehen(pfad) -> None:
    """Erster gemessener Stand wird einmal als Kapital gespeichert. Nichts wird überschrieben."""
    if not pfad.exists():
        return
    _tabellen(pfad)
    namen = {haendler.name for haendler in HAENDLER}
    with sqlite3.connect(pfad) as verbindung:
        tabellen = {zeile[0] for zeile in verbindung.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
        if "paper_konto" not in tabellen:
            return
        belegt = {str(zeile[0]) for zeile in verbindung.execute("SELECT DISTINCT haendler FROM ki_haendler_kapital")}
        zeilen = verbindung.execute(
            """
            SELECT konto, equity, zeit, id FROM paper_konto
            WHERE broker = 'Lokal' ORDER BY id
            """
        ).fetchall()
    erste: dict[str, tuple] = {}
    for konto, equity, zeit, nummer in zeilen:
        if konto not in namen or konto in belegt or konto in erste:
            continue
        if _zahl(equity) is None or _zeit_lesen(zeit) is None:
            continue
        erste[str(konto)] = (equity, zeit, nummer)
    for name, (equity, zeit, _nummer) in erste.items():
        kapital_buchen(pfad, name, _zahl(equity) or Decimal(0), "erster Stand", str(zeit))


def _basis_name(pfad, name: str) -> Decimal | None:
    if not pfad.exists():
        return None
    _kapital_nachziehen(pfad)
    with sqlite3.connect(pfad) as verbindung:
        zeile = verbindung.execute(
            "SELECT basis FROM ki_haendler_kapital WHERE haendler = ? ORDER BY zeit, id DESC LIMIT 1",
            (name,),
        ).fetchone()
    if zeile is None:
        return None
    return _zahl(zeile[0])


def _kapital_summe(pfad) -> Decimal | None:
    if not pfad.exists():
        return None
    _kapital_nachziehen(pfad)
    namen = {haendler.name for haendler in HAENDLER}
    with sqlite3.connect(pfad) as verbindung:
        zeilen = verbindung.execute(
            """
            SELECT haendler, basis FROM ki_haendler_kapital
            WHERE id IN (SELECT MAX(id) FROM ki_haendler_kapital GROUP BY haendler)
            """
        ).fetchall()
    summe = Decimal(0)
    gesehen = False
    for name, basis in zeilen:
        zahl = _zahl(basis)
        if name not in namen or zahl is None or zahl <= 0:
            continue
        summe += zahl
        gesehen = True
    return summe if gesehen else None


def _gesamt_verlauf(pfad) -> dict:
    leer = {"punkte": [], "drawdown": None, "veraltet": False, "unvollstaendig": False, "hinweis": ""}
    if not pfad.exists():
        return leer
    _kapital_nachziehen(pfad)
    namen = {haendler.name for haendler in HAENDLER}
    with sqlite3.connect(pfad) as verbindung:
        tabellen = {zeile[0] for zeile in verbindung.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
        if "paper_konto" not in tabellen:
            return leer
        kontozeilen = verbindung.execute(
            "SELECT id, konto, equity, zeit FROM paper_konto WHERE broker = 'Lokal' ORDER BY id"
        ).fetchall()
        kapitalzeilen = verbindung.execute(
            "SELECT id, haendler, basis, art, zeit FROM ki_haendler_kapital ORDER BY id"
        ).fetchall()
    staende: dict[str, list[tuple]] = {}
    for nummer, konto, equity, zeit in kontozeilen:
        stempel = _zeit_lesen(zeit)
        zahl = _zahl(equity)
        if konto not in namen or stempel is None or zahl is None:
            continue
        staende.setdefault(str(konto), []).append((stempel, str(zeit), float(zahl), int(nummer)))
    bewegungen: dict[str, list[tuple]] = {}
    for nummer, name, basis, art, zeit in kapitalzeilen:
        stempel = _zeit_lesen(zeit)
        zahl = _zahl(basis)
        if name not in namen or stempel is None or zahl is None:
            continue
        bewegungen.setdefault(str(name), []).append((stempel, float(zahl), str(art), int(nummer)))
    zeiten = sorted({eintrag[0] for serie in list(staende.values()) + list(bewegungen.values()) for eintrag in serie})
    zeiger_stand = {name: 0 for name in staende}
    zeiger_kapital = {name: 0 for name in bewegungen}
    equity_jetzt: dict[str, float] = {}
    equity_zeit: dict[str, datetime] = {}
    basis_jetzt: dict[str, float] = {}
    punkte = []
    vorher_equity = None
    vorher_basis = None
    wert = None
    spitze = None
    segment = 0.0
    schlimmste = 0.0
    unvollstaendig = False
    for zeit in zeiten:
        rebase = False
        for name, serie in staende.items():
            index = zeiger_stand[name]
            while index < len(serie) and serie[index][0] <= zeit:
                equity_jetzt[name] = serie[index][2]
                equity_zeit[name] = serie[index][0]
                index += 1
            zeiger_stand[name] = index
        for name, serie in bewegungen.items():
            index = zeiger_kapital[name]
            while index < len(serie) and serie[index][0] <= zeit:
                basis_jetzt[name] = serie[index][1]
                if serie[index][0] == zeit and serie[index][2] in _REBASE:
                    rebase = True
                index += 1
            zeiger_kapital[name] = index
        aktiv = [name for name, basis in basis_jetzt.items() if basis > 0]
        if any(name not in equity_jetzt for name in aktiv):
            unvollstaendig = True
            continue
        if not aktiv:
            if wert is not None and spitze is not None and spitze > 0:
                schlimmste = max(schlimmste, segment)
            wert = None
            spitze = None
            segment = 0.0
            vorher_equity = None
            vorher_basis = None
            continue
        equity = round(sum(equity_jetzt[name] for name in aktiv), 2)
        basis = round(sum(basis_jetzt[name] for name in aktiv), 2)
        if basis <= 0:
            continue
        if wert is None or rebase or vorher_equity is None:
            if wert is not None and spitze is not None and spitze > 0:
                schlimmste = max(schlimmste, segment)
            wert = equity
            spitze = equity
            segment = 0.0
        else:
            wert = round(wert + (equity - vorher_equity) - (basis - vorher_basis), 2)
            spitze = max(spitze, wert)
            if spitze > 0:
                segment = max(segment, (spitze - wert) / spitze)
        vorher_equity = equity
        vorher_basis = basis
        punkte.append(
            {
                "equity": equity,
                "kapital": basis,
                "wert": wert,
                "zeit": zeit.isoformat(),
                "buecher": len(aktiv),
                "fortgeschrieben": sum(1 for name in aktiv if equity_zeit.get(name) != zeit),
            }
        )
    if wert is not None and spitze is not None and spitze > 0:
        schlimmste = max(schlimmste, segment)
    drawdown = None if len(punkte) < 2 or (spitze is not None and spitze <= 0 and schlimmste == 0) else schlimmste
    if len(punkte) < 2:
        drawdown = None
    letzte = _zeit_lesen(punkte[-1]["zeit"]) if punkte else None
    veraltet = letzte is not None and (datetime.now(timezone.utc) - letzte).total_seconds() > 10 * 24 * 3600  # noqa: UP017
    hinweis = "Kontostand älter als 10 Tage. Der Drawdown ist deshalb kein aktueller Risikowert." if veraltet else ""
    if unvollstaendig:
        hinweis = "Mindestens ein Buch hat Kapital ohne Equity-Stand. " + hinweis
    return {"punkte": punkte, "drawdown": drawdown, "veraltet": veraltet, "unvollstaendig": unvollstaendig, "hinweis": hinweis}


def _gesamt_punkte(pfad) -> list[dict]:
    return _gesamt_verlauf(pfad)["punkte"]


def _realisiert_punkte(pfad) -> list[dict]:
    if not pfad.exists():
        return []
    namen = {haendler.name for haendler in HAENDLER}
    with sqlite3.connect(pfad) as verbindung:
        tabellen = {zeile[0] for zeile in verbindung.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
        if "ki_haendler_fall" not in tabellen:
            return []
        zeilen = verbindung.execute(
            """
            SELECT haendler, ergebnis, COALESCE(ausstieg_zeit, zeit) FROM ki_haendler_fall
            WHERE ausstieg IS NOT NULL AND quelle = 'simulation' AND ergebnis IS NOT NULL
            ORDER BY id
            """
        ).fetchall()
    paare = []
    for haendler, ergebnis, zeit in zeilen:
        if haendler not in namen:
            continue
        netto = _zahl(ergebnis)
        stempel = _zeit_lesen(zeit)
        if netto is None or stempel is None:
            continue
        paare.append((stempel, str(zeit), netto))
    paare.sort(key=lambda paar: paar[0])
    lauf = Decimal(0)
    return [{"equity": float(lauf := lauf + netto), "zeit": zeit} for _stempel, zeit, netto in paare][-500:]


def _aktualitaet(pfad, buecher: list[dict], kurs_fehlt: bool) -> dict:
    zeiten = [_zeit_lesen(buch.get("zeit")) for buch in buecher]
    zeiten = [zeit for zeit in zeiten if zeit is not None]
    jetzt = datetime.now(timezone.utc)  # noqa: UP017
    if not zeiten:
        stand = "Keine Daten"
        stand_hinweis = "Kein gespeicherter Kontostand."
    else:
        letzte = max(zeiten)
        stand = letzte.isoformat()
        stand_hinweis = "Kontostand veraltet." if (jetzt - letzte).total_seconds() > 10 * 24 * 3600 else "Kontostand innerhalb von 10 Tagen."
    kurs_zeit, kurs_hinweis = _letzter_kurs(pfad, jetzt)
    lage = [position for haendler in HAENDLER for position in _offen_lesen(pfad, haendler.name)]
    if lage:
        teile = [f"{position['symbol']}: {position['status']}, {position['kurszeit'] or 'ohne Zeit'}" for position in lage]
        kurs_hinweis = "Je Symbol einzeln, nicht der neueste Kurs aller Namen. " + " | ".join(teile)
    else:
        kurs_hinweis = "Keine offenen Positionen. Ein einzelner gespeicherter Kurs gilt nicht für jedes Symbol. " + kurs_hinweis
    if kurs_fehlt and lage:
        kurs_hinweis = "Unvollständig, fehlende Werte sind keine 0. " + kurs_hinweis
    return {"kontostand": stand, "kontostand_hinweis": stand_hinweis, "letzter_kurs": kurs_zeit, "kurs_hinweis": kurs_hinweis, "positionen": lage}


def _letzter_kurs(pfad, jetzt: datetime) -> tuple[str, str]:
    if not pfad.exists():
        return "Keine Daten", "Keine Kursreihe."
    with sqlite3.connect(pfad) as verbindung:
        tabellen = {zeile[0] for zeile in verbindung.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
        if "kurse" not in tabellen:
            return "Keine Daten", "Keine Kursreihe."
        zeile = verbindung.execute("SELECT MAX(zeit) FROM kurse WHERE schluss > 0").fetchone()
    if zeile is None or zeile[0] is None:
        return "Keine Daten", "Kein gültiger Kurs gespeichert."
    try:
        stempel = datetime.fromtimestamp(float(zeile[0]), timezone.utc)  # noqa: UP017
    except (OSError, OverflowError, ValueError):
        return "Keine Daten", "Kurszeit ist ungültig."
    hinweis = "Neuester gespeicherter Kurs, nicht der Stand jedes Symbols. " + (
        "Kurs veraltet." if (jetzt - stempel).total_seconds() > 10 * 24 * 3600 else "Zeitpunkt liegt innerhalb von 10 Tagen."
    )
    return stempel.isoformat(), hinweis


def _zeit_lesen(wert) -> datetime | None:
    if not wert:
        return None
    try:
        stempel = datetime.fromisoformat(str(wert))
    except ValueError:
        return None
    if stempel.tzinfo is None:
        stempel = stempel.replace(tzinfo=timezone.utc)  # noqa: UP017
    return stempel.astimezone(timezone.utc)  # noqa: UP017


def _meta(zeilen: list[dict]) -> str:
    belastbar = [zeile for zeile in zeilen if zeile["belastbar"]]
    if not belastbar:
        return "Noch keine Marktphasen und kein Sieger. Dafür fehlen je Trader mindestens 20 abgeschlossene Fälle mit positivem unterem Rand."
    namen = ", ".join(zeile["name"] for zeile in sorted(belastbar, key=lambda zeile: zeile["score"], reverse=True)[:3])
    return f"Nur diese Trader haben eine ausreichende Stichprobe: {namen}. Der höchste Gewinn allein reicht nicht."


def _quoten_aus_equity(pfad, name: str) -> tuple[str, str]:
    """Veränderung aufeinanderfolgender Equity-Stände. Nicht annualisiert."""
    werte = _equity_reihe(pfad, name)
    if len(werte) < _SHARPE + 1:
        return _KENNZAHL, _KENNZAHL
    renditen = [(werte[i] - werte[i - 1]) / werte[i - 1] for i in range(1, len(werte)) if werte[i - 1] > 0]
    if len(renditen) < _SHARPE:
        return _KENNZAHL, _KENNZAHL
    mittel = sum(renditen) / len(renditen)
    abweichung = [wert - mittel for wert in renditen]
    unten = [min(0.0, wert) for wert in renditen]
    streuung = math.sqrt(sum(wert ** 2 for wert in abweichung) / len(abweichung))
    streuung_unten = math.sqrt(sum(wert ** 2 for wert in unten) / len(unten))
    sharpe = _KENNZAHL if streuung == 0 else f"{mittel / streuung:.2f} je Stand"
    sortino = _KENNZAHL if streuung_unten == 0 else f"{mittel / streuung_unten:.2f} je Stand"
    return sharpe, sortino


def _rendite(pfad, name: str) -> str:
    zahl = _rendite_zahl(pfad, name)
    if zahl is None:
        return "Keine Daten" if not _equity_reihe(pfad, name) else _KENNZAHL
    return f"{zahl:.1f} %"


def _equity_reihe(pfad, name: str) -> list[float]:
    if not pfad.exists():
        return []
    with sqlite3.connect(pfad) as verbindung:
        tabellen = {zeile[0] for zeile in verbindung.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
        if "paper_konto" not in tabellen:
            return []
        zeilen = verbindung.execute(
            "SELECT equity FROM paper_konto WHERE broker = 'Lokal' AND konto = ? ORDER BY id",
            (name,),
        ).fetchall()
    return [float(zeile[0]) for zeile in zeilen if _zahl(zeile[0]) is not None]


def _abgeschlossen(pfad, name: str) -> list[tuple[Decimal, float]]:
    if not pfad.exists():
        return []
    with sqlite3.connect(pfad) as verbindung:
        zeilen = verbindung.execute(
            """
            SELECT ergebnis, einstieg, ausstieg FROM ki_haendler_fall
            WHERE haendler = ? AND ausstieg IS NOT NULL AND quelle = 'simulation'
            """,
            (name,),
        ).fetchall()
    ergebnis = []
    for netto, einstieg, ausstieg in zeilen:
        start = _zahl(einstieg)
        ende = _zahl(ausstieg)
        netto_zahl = _zahl(netto)
        if start is None or start <= 0 or ende is None or netto_zahl is None:
            continue
        ergebnis.append((netto_zahl, float(ende / start - 1)))
    return ergebnis


def _drawdown(pfad, name: str) -> float | None:
    return _drawdown_aus(_equity_reihe(pfad, name))


def _drawdown_aus(werte: list[float]) -> float | None:
    if len(werte) < 2:
        return None
    spitze = werte[0]
    tief = 0.0
    for wert in werte:
        spitze = max(spitze, wert)
        if spitze > 0:
            tief = max(tief, (spitze - wert) / spitze)
    return tief


def _letzte(pfad, name: str) -> str:
    if not pfad.exists():
        return "noch keine Entscheidung"
    with sqlite3.connect(pfad) as verbindung:
        zeile = verbindung.execute(
            "SELECT entscheidung, grund FROM ki_haendler_entscheidung WHERE haendler = ? ORDER BY id DESC LIMIT 1",
            (name,),
        ).fetchone()
    if zeile is None:
        return "noch keine Entscheidung"
    return f"{zeile[0]}: {zeile[1]}"


def _version(pfad, name: str) -> int:
    if pfad is None or not pfad.exists():
        return 1
    with sqlite3.connect(pfad) as verbindung:
        tabellen = {zeile[0] for zeile in verbindung.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
        if "ki_haendler_modell" not in tabellen:
            return 1
        zeile = verbindung.execute("SELECT version FROM ki_haendler_modell WHERE haendler = ?", (name,)).fetchone()
    return 1 if zeile is None else int(zeile[0])


def _lernstatus(pfad, name: str) -> str:
    modell = _modell_lesen(pfad, name)
    if modell is None or modell[2] < _ZUVERLAESSIG:
        zahl = 0 if modell is None else modell[2]
        return f"{zahl} Fälle, nicht zuverlässig"
    return f"{modell[2]} Fälle, Version {modell[3]}"


def _detail(pfad, name: str) -> dict:
    konto = _kontostand(pfad, name)
    punkte = _equity_punkte(pfad, name)[-120:]
    return {
        "start": None if (basis := _basis_name(pfad, name)) is None else f"{basis:.2f}",
        "equity": konto["equity"],
        "cash": konto["cash"],
        "hat_buch": konto["hat_buch"],
        "offen": konto["offen"],
        "geschlossen": _geschlossen(pfad, name),
        "verlauf": [punkt["equity"] for punkt in punkte],
        "punkte": punkte,
        "entscheidungen": _entscheidungen(pfad, name),
        "versionen": _versionen(pfad, name),
        "pruefung": _letzte_pruefung(pfad, name),
    }


def _equity_punkte(pfad, name: str) -> list[dict]:
    if not pfad.exists():
        return []
    with sqlite3.connect(pfad) as verbindung:
        tabellen = {zeile[0] for zeile in verbindung.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
        if "paper_konto" not in tabellen:
            return []
        zeilen = verbindung.execute(
            "SELECT equity, zeit FROM paper_konto WHERE broker = 'Lokal' AND konto = ? ORDER BY id",
            (name,),
        ).fetchall()
    return [{"equity": float(zeile[0]), "zeit": zeile[1]} for zeile in zeilen if _zahl(zeile[0]) is not None]


def _kontostand(pfad, name: str) -> dict:
    offen = _offen_lesen(pfad, name)
    if not pfad.exists():
        return {"equity": None, "cash": None, "offen": offen, "hat_buch": False}
    with sqlite3.connect(pfad) as verbindung:
        tabellen = {zeile[0] for zeile in verbindung.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
        if "paper_konto" not in tabellen:
            return {"equity": None, "cash": None, "offen": offen, "hat_buch": False}
        zeile = verbindung.execute(
            "SELECT cash, equity FROM paper_konto WHERE broker = 'Lokal' AND konto = ? ORDER BY id DESC LIMIT 1",
            (name,),
        ).fetchone()
    if zeile is None:
        return {"equity": None, "cash": None, "offen": offen, "hat_buch": False}
    equity = _zahl(zeile[1])
    cash = _zahl(zeile[0])
    return {
        "equity": None if equity is None else f"{equity:.2f}",
        "cash": None if cash is None else f"{cash:.2f}",
        "offen": offen,
        "hat_buch": True,
    }


def _offen_lesen(pfad, name: str) -> list[dict]:
    if not pfad.exists():
        return []
    with sqlite3.connect(pfad) as verbindung:
        tabellen = {zeile[0] for zeile in verbindung.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
        if "paper_buch" not in tabellen:
            return []
        zeilen = verbindung.execute(
            "SELECT symbol, menge, einstieg, jetzt FROM paper_buch WHERE konto = ?",
            (name,),
        ).fetchall()
        kurse = {}
        if "kurse" in tabellen:
            for symbol, *_rest in zeilen:
                kurs = verbindung.execute(
                    "SELECT zeit, schluss FROM kurse WHERE symbol = ? AND schluss > 0 ORDER BY zeit DESC LIMIT 1",
                    (symbol,),
                ).fetchone()
                if kurs is not None:
                    kurse[symbol] = kurs
    uhr = datetime.now(timezone.utc)  # noqa: UP017
    ergebnis = []
    for symbol, menge, einstieg, jetzt in zeilen:
        kurs = kurse.get(symbol)
        kurszeit = None
        if kurs is not None:
            try:
                kurszeit = datetime.fromtimestamp(float(kurs[0]), timezone.utc)  # noqa: UP017
            except (OSError, OverflowError, TypeError, ValueError):
                kurszeit = None
        status = _positions_status(symbol, menge, einstieg, jetzt, kurszeit, uhr)
        ergebnis.append(
            {
                "symbol": symbol,
                "menge": menge,
                "einstieg": einstieg,
                "jetzt": jetzt,
                "kurszeit": None if kurszeit is None else kurszeit.isoformat(),
                "status": status,
                "kurs_fehlt": status != "Kurs aktuell",
            }
        )
    return ergebnis


def _positions_status(symbol: str, menge, einstieg, jetzt, kurszeit: datetime | None, uhr: datetime) -> str:
    menge_zahl = _zahl(menge)
    einstieg_zahl = _zahl(einstieg)
    kurs = _zahl(jetzt)
    if menge_zahl is None:
        return "Menge fehlt"
    if menge_zahl <= 0:
        return "Menge ungültig"
    if einstieg_zahl is None:
        return "Einstieg fehlt"
    if einstieg_zahl <= 0:
        return "Einstieg ungültig"
    if kurs is None:
        return "Kurs fehlt"
    if kurs <= 0:
        return "Kurs ungültig"
    if kurszeit is None:
        return "Kurszeit fehlt"
    grenze = 2 * 24 * 3600 if str(symbol).upper().endswith("-USD") else 10 * 24 * 3600
    if (uhr - kurszeit).total_seconds() > grenze:
        return "Kurs veraltet"
    return "Kurs aktuell"


def _geschlossen(pfad, name: str) -> list[dict]:
    if not pfad.exists():
        return []
    with sqlite3.connect(pfad) as verbindung:
        zeilen = verbindung.execute(
            """
            SELECT symbol, ergebnis, brutto, zeit FROM ki_haendler_fall
            WHERE haendler = ? AND ausstieg IS NOT NULL AND quelle = 'simulation'
            ORDER BY id DESC LIMIT 8
            """,
            (name,),
        ).fetchall()
    return [{"symbol": zeile[0], "ergebnis": zeile[1], "brutto": zeile[2], "zeit": zeile[3]} for zeile in zeilen]


def _entscheidungen(pfad, name: str) -> list[dict]:
    if not pfad.exists():
        return []
    with sqlite3.connect(pfad) as verbindung:
        zeilen = verbindung.execute(
            """
            SELECT zeit, entscheidung, grund, version, signal, wahrscheinlichkeit, zuverlaessig
            FROM ki_haendler_entscheidung WHERE haendler = ? ORDER BY id DESC LIMIT 8
            """,
            (name,),
        ).fetchall()
    return [
        {
            "zeit": zeile[0],
            "entscheidung": zeile[1],
            "grund": zeile[2],
            "version": zeile[3],
            "signal": zeile[4],
            "wahrscheinlichkeit": zeile[5],
            "zuverlaessig": bool(zeile[6]),
        }
        for zeile in zeilen
    ]


def _versionen(pfad, name: str) -> list[dict]:
    if not pfad.exists():
        return []
    with sqlite3.connect(pfad) as verbindung:
        zeilen = verbindung.execute(
            """
            SELECT version, beispiele, grund, zeit FROM ki_haendler_version
            WHERE haendler = ? ORDER BY id DESC LIMIT 5
            """,
            (name,),
        ).fetchall()
    return [{"version": zeile[0], "beispiele": zeile[1], "grund": zeile[2], "zeit": zeile[3]} for zeile in zeilen]


def _letzte_pruefung(pfad, name: str) -> dict:
    if not pfad.exists():
        return {"besser": False, "grund": "Noch keine unabhängige Prüfung.", "status": "Nicht ausreichend Daten"}
    with sqlite3.connect(pfad) as verbindung:
        tabellen = {zeile[0] for zeile in verbindung.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
        if "ki_haendler_pruefung" not in tabellen:
            return {"besser": False, "grund": "Noch keine unabhängige Prüfung.", "status": "Nicht ausreichend Daten"}
        zeile = verbindung.execute(
            """
            SELECT besser, grund, test_n, zeit FROM ki_haendler_pruefung
            WHERE haendler = ? ORDER BY id DESC LIMIT 1
            """,
            (name,),
        ).fetchone()
    if zeile is None:
        return {"besser": False, "grund": "Noch keine unabhängige Prüfung.", "status": "Nicht ausreichend Daten"}
    grund = str(zeile[1])
    if zeile[0]:
        status = "Geprüft"
    elif grund.startswith("Nicht ausreichend") or "Weniger als" in grund or "nicht nach" in grund:
        status = "Nicht ausreichend Daten"
    elif grund.startswith("Nicht freigegeben"):
        status = "Nicht freigegeben"
    elif grund.startswith("Benchmark nicht gemessen") or "Benchmark nicht gemessen" in grund:
        status = "Benchmark nicht gemessen"
    else:
        status = "Nicht ausreichend Daten"
    return {"besser": bool(zeile[0]), "grund": grund, "test": zeile[2], "zeit": zeile[3], "status": status}


def pruefe(pfad, name: str) -> dict:
    """Trainiert nur auf früheren Fällen und prüft spätere. Das aktive Modell bleibt unverändert."""
    _tabellen(pfad)
    with sqlite3.connect(pfad) as verbindung:
        zeilen = verbindung.execute(
            """
            SELECT id, merkmale, ergebnis, zeit, ausstieg_zeit, einstieg, menge FROM ki_haendler_fall
            WHERE haendler = ? AND ausstieg IS NOT NULL AND quelle = 'simulation'
            ORDER BY id
            """,
            (name,),
        ).fetchall()
    faelle = []
    for nummer, merkmale, ergebnis, zeit, ausstieg_zeit, einstieg, menge in zeilen:
        try:
            werte = tuple(float(wert) for wert in json.loads(merkmale))
        except (TypeError, json.JSONDecodeError):
            continue
        netto = _zahl(ergebnis)
        if not werte or netto is None:
            continue
        faelle.append(
            {
                "id": int(nummer),
                "werte": werte,
                "ziel": 1.0 if netto > 0 else 0.0,
                "netto": float(netto),
                "zeit": str(zeit),
                "ausstieg_zeit": ausstieg_zeit,
                "einstieg": _zahl(einstieg),
                "menge": _zahl(menge),
            }
        )
    if any(_fall_zeit(fall) is None for fall in faelle):
        bericht = {"besser": False, "status": "Nicht ausreichend Daten", "grund": "Ohne Ausstiegszeit ist die zeitliche Trennung nicht möglich.", "test_n": len(faelle)}
        _pruefung_speichern(pfad, name, bericht)
        return bericht
    faelle.sort(key=lambda fall: (_fall_zeit(fall), fall["id"]))
    if len(faelle) < 36:
        bericht = {"besser": False, "status": "Nicht ausreichend Daten", "grund": "Weniger als 36 abgeschlossene Fälle für Training, Prüfung und Test.", "test_n": len(faelle)}
        _pruefung_speichern(pfad, name, bericht)
        return bericht
    drittel = len(faelle) // 3
    training = faelle[:drittel]
    validierung = faelle[drittel:drittel * 2]
    test = faelle[drittel * 2:]
    if (
        not validierung
        or _fall_zeit(test[0]) <= _fall_zeit(validierung[-1])
        or _fall_zeit(validierung[0]) <= _fall_zeit(training[-1])
    ):
        bericht = {"besser": False, "status": "Nicht ausreichend Daten", "grund": "Testfälle liegen nicht nach der Prüfung.", "test_n": len(test)}
        _pruefung_speichern(pfad, name, bericht)
        return bericht
    from ki import Modell, schritt, wahrscheinlichkeit

    modell = Modell((0.0,) * len(training[0]["werte"]), 0.0, 0)
    for fall in training:
        if len(fall["werte"]) != len(modell.gewichte):
            continue
        modell = schritt(modell, fall["werte"], fall["ziel"])
    val_genommen = _ausgewaehlt(modell, validierung, wahrscheinlichkeit)
    val_modell = _mittel([fall["netto"] for fall in val_genommen])
    val_regel = _mittel([fall["netto"] for fall in validierung])
    wahl = "modell" if val_modell is not None and val_regel is not None and val_modell > val_regel else "regel"
    genommen = _ausgewaehlt(modell, test, wahrscheinlichkeit)
    modell_netto = _mittel([fall["netto"] for fall in genommen])
    regel_netto = _mittel([fall["netto"] for fall in test])
    basis = _basis_name(pfad, name)
    start = float(basis) if basis is not None and basis > 0 else float(_START)
    genommen_ids = {fall["id"] for fall in genommen}
    modell_pfad = _equity_aus_nettos(start, [fall["netto"] if fall["id"] in genommen_ids else 0.0 for fall in test])
    regel_pfad = _equity_aus_nettos(start, [fall["netto"] for fall in test])
    modell_dd = _drawdown_aus(modell_pfad)
    regel_dd = _drawdown_aus(regel_pfad)
    risiko_ok = modell_dd is not None and regel_dd is not None and modell_dd <= 0.08 and modell_dd <= regel_dd
    modell_ende = modell_pfad[-1]
    regel_ende = regel_pfad[-1]
    benchmark_summe, benchmark_text = _benchmark_summe(pfad, genommen if wahl == "modell" else test)
    unsicherheit = _untere_grenze([fall["netto"] for fall in genommen]) if wahl == "modell" else _untere_grenze([fall["netto"] for fall in test])
    besser = False
    if (
        benchmark_summe is not None
        and wahl == "modell"
        and len(test) >= 12
        and len(genommen) >= 12
        and modell_netto is not None
        and regel_netto is not None
        and unsicherheit is not None
        and unsicherheit > 0
        and unsicherheit > regel_netto
        and modell_ende > start
        and modell_ende > regel_ende
        and benchmark_summe is not None
        and modell_ende > start + benchmark_summe
        and risiko_ok
    ):
        besser = True
        status = "Geprüft"
    elif benchmark_summe is None:
        status = "Benchmark nicht gemessen"
    else:
        status = "Nicht freigegeben"
    grund = (
        f"{status}. Validierung wählt {wahl}. Validierung Modell {_zahl_text(val_modell)}, Regel {_zahl_text(val_regel)}. "
        f"Test Modell {_zahl_text(modell_netto)} auf {len(genommen)} von {len(test)} späteren Fällen, Regel {_zahl_text(regel_netto)}. "
        f"Untere Grenze {_zahl_text(unsicherheit)}. Equity ab {start:.2f}, Modellende {_zahl_text(modell_ende)}, Regelende {_zahl_text(regel_ende)}. "
        f"{benchmark_text} Spread und Slippage sind für beide nicht gemessen. "
        "Sharpe nicht ausreichend Daten. Aktives Modell unverändert."
    )
    bericht = {
        "besser": besser,
        "status": status,
        "wahl": wahl,
        "grund": grund,
        "test_n": len(test),
        "train_bis": training[-1]["id"],
        "pruef_ab": validierung[0]["id"],
        "test_ab": test[0]["id"],
    }
    _pruefung_speichern(pfad, name, bericht)
    return bericht


def _ausgewaehlt(modell, faelle: list[dict], wahrscheinlichkeit) -> list[dict]:
    genommen = []
    for fall in faelle:
        if len(fall["werte"]) != len(modell.gewichte):
            continue
        if wahrscheinlichkeit(modell, fall["werte"]) >= 0.5:
            genommen.append(fall)
    return genommen


def _mittel(werte: list[float]) -> float | None:
    if not werte:
        return None
    return sum(werte) / len(werte)


def _untere_grenze(werte: list[float]) -> float | None:
    if len(werte) < 12:
        return None
    mittel = sum(werte) / len(werte)
    streuung = math.sqrt(sum((wert - mittel) ** 2 for wert in werte) / (len(werte) - 1))
    t = 2.20 if len(werte) < 30 else 2.04 if len(werte) < 120 else 1.96
    return mittel - t * streuung / math.sqrt(len(werte))


def _summenpfad(werte: list[float]) -> list[float]:
    lauf = 0.0
    pfad = []
    for wert in werte:
        lauf += wert
        pfad.append(lauf)
    return pfad


def _zahl_text(wert: float | None) -> str:
    return "—" if wert is None else f"{wert:.2f}"


def _fall_zeit(fall: dict) -> datetime | None:
    return _zeit_lesen(fall.get("ausstieg_zeit")) or _zeit_lesen(fall.get("zeit"))


def _equity_aus_nettos(start: float, nettos: list[float]) -> list[float]:
    """Equity-Kurve ab demselben Start. Übersprungene Fälle lassen das Kapital unverändert."""
    lauf = start
    pfad = [lauf]
    for netto in nettos:
        lauf += netto
        pfad.append(lauf)
    return pfad


def _benchmark_summe(pfad, faelle: list[dict]) -> tuple[float | None, str]:
    """Indexkauf über dieselbe Haltedauer und dieselben Gebühren. Lücken bleiben leer."""
    reihen = _index_reihe(pfad)
    if not reihen:
        return None, "Benchmark nicht gemessen. Keine Indexreihe."
    summe = 0.0
    luecken = 0
    for fall in faelle:
        einstieg = fall.get("einstieg")
        menge = fall.get("menge")
        start = _index_zur_zeit(reihen, fall.get("zeit"))
        ende = _index_zur_zeit(reihen, fall.get("ausstieg_zeit"))
        if einstieg is None or menge is None or einstieg <= 0 or menge <= 0 or start is None or ende is None or start <= 0:
            luecken += 1
            continue
        ausstieg = einstieg * (Decimal(str(ende)) / Decimal(str(start)))
        _brutto, _ein, _aus, netto = _kosten(einstieg, ausstieg, menge)
        summe += float(netto)
    if luecken or not faelle:
        return None, f"Benchmark nicht gemessen. Datenlücke bei {luecken} Fällen."
    return summe, "Benchmark ist der Index über dieselbe Haltedauer."


def _index_reihe(pfad) -> list[tuple[float, float]]:
    if not pfad.exists():
        return []
    with sqlite3.connect(pfad) as verbindung:
        tabellen = {zeile[0] for zeile in verbindung.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
        if "kurse" not in tabellen:
            return []
        for symbol in ("^GDAXI", "^GSPC"):
            zeilen = verbindung.execute(
                "SELECT zeit, schluss FROM kurse WHERE symbol = ? AND schluss > 0 ORDER BY zeit",
                (symbol,),
            ).fetchall()
            reihe = [(float(zeit), float(schluss)) for zeit, schluss in zeilen if zeit is not None and schluss is not None]
            if len(reihe) >= 2:
                return reihe
    return []


def _index_zur_zeit(reihe: list[tuple[float, float]], zeit) -> float | None:
    stempel = _zeit_lesen(zeit)
    if stempel is None:
        return None
    ziel = stempel.timestamp()
    gewaehlt = None
    for punkt, preis in reihe:
        if punkt <= ziel:
            gewaehlt = preis
        else:
            break
    return gewaehlt


def _pruefung_speichern(pfad, name: str, bericht: dict) -> None:
    with sqlite3.connect(pfad) as verbindung:
        verbindung.execute(
            """
            INSERT INTO ki_haendler_pruefung (haendler, besser, grund, test_n, train_bis, test_ab, zeit)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                name,
                1 if bericht["besser"] else 0,
                bericht["grund"],
                bericht.get("test_n", 0),
                bericht.get("train_bis"),
                bericht.get("test_ab"),
                _jetzt(),
            ),
        )


def _meta_bericht(pfad, zeilen: list[dict]) -> dict:
    phasen = _phasen(pfad)
    belastbar = [
        zeile for zeile in zeilen
        if zeile["belastbar"] and (zeile.get("detail") or {}).get("pruefung", {}).get("besser")
    ]
    if belastbar:
        summe = sum(max(zeile["score"], 0.0) for zeile in belastbar) or 1.0
        gewichte = {zeile["name"]: round(max(zeile["score"], 0.0) / summe, 2) for zeile in belastbar}
        hinweis = "Vorschlag aus der Stichprobe. Keine Order und keine Änderung der Risikogrenzen."
    else:
        gewichte = {}
        hinweis = "Keine Gewichtung. Dafür fehlt eine bestandene unabhängige Prüfung. Risikogrenzen bleiben."
    schwaechen = [
        {"name": zeile["name"], "grund": zeile["fehlt"] or "Stichprobe oder unterer Rand reicht nicht."}
        for zeile in zeilen
        if not zeile["belastbar"]
    ]
    bericht = {
        "phasen": phasen,
        "gewichte": gewichte,
        "hinweis": hinweis,
        "schwaechen": schwaechen[:8],
        "unzuverlaessig": [zeile["name"] for zeile in zeilen if not zeile["belastbar"]],
        "quelle": "simulation",
    }
    _meta_speichern(pfad, bericht)
    return bericht


def _phasen(pfad) -> dict:
    if not pfad.exists():
        return {"phase": "nicht gemessen", "grund": "Keine Kursreihe."}
    with sqlite3.connect(pfad) as verbindung:
        tabellen = {zeile[0] for zeile in verbindung.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
        if "kurse" not in tabellen:
            return {"phase": "nicht gemessen", "grund": "Keine Kursreihe."}
        for symbol in ("^GDAXI", "^GSPC"):
            zeilen = verbindung.execute(
                "SELECT schluss FROM kurse WHERE symbol = ? ORDER BY zeit",
                (symbol,),
            ).fetchall()
            schluesse = [float(zeile[0]) for zeile in zeilen if zeile[0] is not None and float(zeile[0]) > 0]
            if len(schluesse) >= 21:
                return _phase_aus(symbol, schluesse)
    return {"phase": "nicht gemessen", "grund": "Indexreihe zu kurz oder nicht gespeichert."}


def _phase_aus(symbol: str, schluesse: list[float]) -> dict:
    rendite = schluesse[-1] / schluesse[-21] - 1
    aenderungen = [schluesse[i] / schluesse[i - 1] - 1 for i in range(1, len(schluesse)) if schluesse[i - 1] > 0]
    streuung = math.sqrt(sum(wert ** 2 for wert in aenderungen[-20:]) / max(1, len(aenderungen[-20:])))
    if rendite <= -0.02:
        phase = "fallend"
    elif streuung >= 0.02:
        phase = "volatil"
    elif rendite >= 0.02:
        phase = "steigend"
    else:
        phase = "seitwaerts"
    return {"phase": phase, "symbol": symbol, "rendite_20": round(rendite, 4), "grund": "Aus gespeicherten Indexschlüssen."}


def _meta_speichern(pfad, bericht: dict) -> None:
    if not pfad.exists():
        return
    text = json.dumps(bericht, ensure_ascii=False)
    with sqlite3.connect(pfad) as verbindung:
        letzte = verbindung.execute("SELECT text FROM ki_haendler_meta ORDER BY id DESC LIMIT 1").fetchone()
        if letzte is not None and letzte[0] == text:
            return
        verbindung.execute("INSERT INTO ki_haendler_meta (text, zeit) VALUES (?, ?)", (text, _jetzt()))


def _letzte_lernzeit(pfad) -> str:
    if not pfad.exists():
        return ""
    with sqlite3.connect(pfad) as verbindung:
        zeile = verbindung.execute(
            "SELECT zeit FROM ki_haendler_version ORDER BY id DESC LIMIT 1"
        ).fetchone()
    return "" if zeile is None else str(zeile[0])


def _tabellen(pfad) -> None:
    pfad.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(pfad) as verbindung:
        verbindung.execute(
            """
            CREATE TABLE IF NOT EXISTS ki_haendler_modell (
                haendler TEXT PRIMARY KEY,
                gewichte TEXT NOT NULL,
                bias REAL NOT NULL,
                beispiele INTEGER NOT NULL,
                version INTEGER NOT NULL,
                zeit TEXT NOT NULL
            )
            """
        )
        verbindung.execute(
            """
            CREATE TABLE IF NOT EXISTS ki_haendler_version (
                id INTEGER PRIMARY KEY,
                haendler TEXT NOT NULL,
                version INTEGER NOT NULL,
                gewichte TEXT NOT NULL,
                bias REAL NOT NULL,
                beispiele INTEGER NOT NULL,
                grund TEXT NOT NULL,
                zeit TEXT NOT NULL
            )
            """
        )
        verbindung.execute(
            """
            CREATE TABLE IF NOT EXISTS ki_haendler_fall (
                id INTEGER PRIMARY KEY,
                haendler TEXT NOT NULL,
                symbol TEXT NOT NULL,
                horizont TEXT NOT NULL,
                merkmale TEXT NOT NULL,
                einstieg TEXT,
                ausstieg TEXT,
                ergebnis TEXT,
                kosten TEXT,
                benchmark TEXT,
                quelle TEXT NOT NULL,
                gelernt INTEGER NOT NULL DEFAULT 0,
                zeit TEXT NOT NULL
            )
            """
        )
        verbindung.execute(
            """
            CREATE TABLE IF NOT EXISTS ki_haendler_parameter (
                haendler TEXT NOT NULL,
                schluessel TEXT NOT NULL,
                wert REAL NOT NULL,
                PRIMARY KEY (haendler, schluessel)
            )
            """
        )
        verbindung.execute("CREATE INDEX IF NOT EXISTS ki_haendler_fall_name ON ki_haendler_fall (haendler, quelle)")
        for name, typ in (
            ("brutto", "TEXT"),
            ("gebuehr_einstieg", "TEXT"),
            ("gebuehr_ausstieg", "TEXT"),
            ("spread", "TEXT"),
            ("slippage", "TEXT"),
            ("ausstieg_zeit", "TEXT"),
            ("menge", "TEXT"),
        ):
            _spalte(verbindung, "ki_haendler_fall", name, typ)
        verbindung.execute(
            """
            CREATE TABLE IF NOT EXISTS ki_haendler_entscheidung (
                id INTEGER PRIMARY KEY,
                haendler TEXT NOT NULL,
                symbol TEXT NOT NULL,
                entscheidung TEXT NOT NULL,
                grund TEXT NOT NULL,
                zeit TEXT NOT NULL
            )
            """
        )
        for name, typ in (
            ("version", "INTEGER"),
            ("signal", "TEXT"),
            ("wahrscheinlichkeit", "TEXT"),
            ("zuverlaessig", "INTEGER"),
        ):
            _spalte(verbindung, "ki_haendler_entscheidung", name, typ)
        verbindung.execute(
            """
            CREATE TABLE IF NOT EXISTS ki_haendler_pruefung (
                id INTEGER PRIMARY KEY,
                haendler TEXT NOT NULL,
                besser INTEGER NOT NULL,
                grund TEXT NOT NULL,
                test_n INTEGER NOT NULL,
                train_bis INTEGER,
                test_ab INTEGER,
                zeit TEXT NOT NULL
            )
            """
        )
        verbindung.execute(
            """
            CREATE TABLE IF NOT EXISTS ki_haendler_meta (
                id INTEGER PRIMARY KEY,
                text TEXT NOT NULL,
                zeit TEXT NOT NULL
            )
            """
        )
        verbindung.execute(
            """
            CREATE TABLE IF NOT EXISTS ki_haendler_kapital (
                id INTEGER PRIMARY KEY,
                haendler TEXT NOT NULL,
                delta TEXT NOT NULL,
                basis TEXT NOT NULL,
                art TEXT NOT NULL,
                zeit TEXT NOT NULL
            )
            """
        )


def _spalte(verbindung, tabelle: str, name: str, typ: str) -> None:
    vorhanden = {str(zeile[1]) for zeile in verbindung.execute(f"PRAGMA table_info({tabelle})")}
    if name not in vorhanden:
        verbindung.execute(f"ALTER TABLE {tabelle} ADD COLUMN {name} {typ}")


def _reihe(zeile) -> tuple[float, ...]:
    werte = _feld(zeile, "reihe") or ()
    return tuple(float(wert) for wert in werte if isinstance(wert, (int, float)) and wert > 0)


def _klasse(zeile) -> str:
    symbol = str(_feld(zeile, "symbol") or "").upper()
    if symbol.endswith("-USD"):
        return "krypto"
    zahlen = _feld(zeile, "kennzahlen")
    if getattr(zahlen, "ist_etf", False):
        return "etf"
    return "aktie"


def _feld(zeile, name: str):
    if isinstance(zeile, dict):
        return zeile.get(name)
    return getattr(zeile, name, None)


def _zahl(wert) -> Decimal | None:
    try:
        zahl = Decimal(str(wert))
    except (ArithmeticError, TypeError, ValueError):
        return None
    if not zahl.is_finite():
        return None
    return zahl


def _jetzt() -> str:
    return datetime.now(timezone.utc).isoformat()  # noqa: UP017
