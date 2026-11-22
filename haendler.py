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

_KOSTEN = Decimal("0.0025")
_MINDEST = 20
_SHARPE = 30
_START = Decimal(10000)


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
        bestand = _positionen(pfad, name)
        eigene = {str(zeile["symbol"]) for zeile in bestand}
        sperre = kauf_gesperrt(cash + _marktwert(pfad, name), *_spitze_konto(pfad, name, cash + _marktwert(pfad, name)), len(eigene))
        stops = {str(zeile["symbol"]): _zahl(zeile.get("stop")) for zeile in bestand}
        mengen = {str(zeile["symbol"]): _zahl(zeile.get("menge")) for zeile in bestand}
        kauefe = 0
        for zeile in zeilen or ():
            symbol = str(_feld(zeile, "symbol") or "")
            if not symbol or (symbol not in namen and symbol not in eigene):
                continue
            preis = _preis_eur(zeile, kurs)
            if preis is None:
                _notiz(pfad, name, symbol, "SKIP", "Währung oder EUR/USD fehlt. Nicht gekauft.")
                continue
            if symbol in eigene:
                stop = stops.get(symbol)
                if stop is not None and preis <= stop:
                    _schliessen(pfad, name, symbol, preis, jetzt, "Stop ist erreicht. Lokale Prüfung, keine Broker-Order.")
                    cash += preis * (mengen.get(symbol) or Decimal(0))
                    eigene.discard(symbol)
                    continue
                entscheidung, grund, _merkmale = entscheide(name, zeile)
                if entscheidung == "SELL":
                    _schliessen(pfad, name, symbol, preis, jetzt, grund)
                    cash += preis * (mengen.get(symbol) or Decimal(0))
                    eigene.discard(symbol)
                else:
                    _jetzt_merken(pfad, name, symbol, preis)
                    _notiz(pfad, name, symbol, "HOLD", grund)
                continue
            if nur_verkauf or sperre or kauefe >= 3:
                continue
            hinweis = _daten_hinweis(zeile)
            if hinweis:
                _notiz(pfad, name, symbol, "SKIP", hinweis)
                continue
            entscheidung, grund, merkmale = entscheide(name, zeile)
            if entscheidung != "BUY":
                _notiz(pfad, name, symbol, entscheidung if entscheidung in ("HOLD", "SKIP") else "SKIP", grund)
                continue
            stop_mal = 1 if name == "Defensiv" else 2
            deckel = Decimal("0.04") if name == "Defensiv" else Decimal("0.08")
            kosten = _lokal_kaufen(pfad, name, zeile, preis, kurs, _START, cash, jetzt, stop_mal, deckel)
            if kosten <= 0:
                _notiz(pfad, name, symbol, "SKIP", "Die Menge passt nicht in Risiko, Cash oder Stückzahl.")
                continue
            cash -= kosten
            kauefe += 1
            eigene.add(symbol)
            _fall_offen(pfad, haendler, symbol, merkmale, preis)
            _notiz(pfad, name, symbol, "BUY", grund)
        _lokal_konto(pfad, name, _START, cash, _marktwert(pfad, name), kurs, jetzt)


def uebersicht(pfad) -> dict:
    _tabellen(pfad)
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
        "meta": _meta(zeilen),
        "rangliste": zeilen,
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


def _schliessen(pfad, name: str, symbol: str, preis: Decimal, jetzt: datetime, grund: str) -> None:
    from papier import _lokal_verkaufen, _positionen

    position = next((eintrag for eintrag in _positionen(pfad, name) if eintrag["symbol"] == symbol), None)
    if position is None:
        return
    _lokal_verkaufen(pfad, name, symbol, preis, jetzt)
    _fall_zu(pfad, name, symbol, position, preis)
    _notiz(pfad, name, symbol, "SELL", grund)


def _notiz(pfad, name: str, symbol: str, entscheidung: str, grund: str) -> None:
    _tabellen(pfad)
    with sqlite3.connect(pfad) as verbindung:
        verbindung.execute(
            "INSERT INTO ki_haendler_entscheidung (haendler, symbol, entscheidung, grund, zeit) VALUES (?, ?, ?, ?, ?)",
            (name, symbol, entscheidung, grund, _jetzt()),
        )


def _fall_offen(pfad, haendler: Haendler, symbol: str, merkmale, preis: Decimal) -> None:
    if not merkmale:
        return
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
            (haendler, symbol, horizont, merkmale, einstieg, kosten, benchmark, quelle, gelernt, zeit)
            VALUES (?, ?, ?, ?, ?, 'Annahme 0,25 Prozent des Einstiegs', 'nicht gemessen', 'simulation', 0, ?)
            """,
            (haendler.name, symbol, haendler.horizont, json.dumps(list(merkmale)), str(preis), _jetzt()),
        )


def _fall_zu(pfad, name: str, symbol: str, position: dict, preis: Decimal) -> None:
    einstieg = _zahl(position.get("einstieg"))
    menge = _zahl(position.get("menge"))
    if einstieg is None or menge is None:
        return
    brutto = (preis - einstieg) * menge
    gebuehr = (einstieg * menge * _KOSTEN).quantize(Decimal("0.01"))
    netto = (brutto - gebuehr).quantize(Decimal("0.01"))
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
            "UPDATE ki_haendler_fall SET ausstieg = ?, ergebnis = ? WHERE id = ?",
            (str(preis), str(netto), zeile[0]),
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
    treffer = sum(1 for wert in netto if wert > 0)
    gewinne = [wert for wert in netto if wert > 0]
    verluste = [wert for wert in netto if wert < 0]
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
    return {
        "name": haendler.name,
        "gruppe": haendler.gruppe,
        "horizont": haendler.horizont,
        "einsatz": haendler.einsatz,
        "regel": haendler.regel,
        "version": _version(pfad, haendler.name),
        "trades": len(netto),
        "quote": "—" if not netto else f"{treffer}/{len(netto)}",
        "gewinn": "—" if not gewinne else f"{sum(gewinne) / len(gewinne):.2f}",
        "verlust": "—" if not verluste else f"{sum(verluste) / len(verluste):.2f}",
        "ergebnis": f"{sum(netto, Decimal(0)):.2f}" if netto else "0.00",
        "drawdown": "—" if dd is None else f"{dd:.1%}",
        "sharpe": _quote(renditen, False),
        "sortino": _quote(renditen, True),
        "belastbar": belastbar,
        "score": score,
        "platz": platz,
        "quelle": "simulation",
        "letzte": _letzte(pfad, haendler.name),
    }


def _meta(zeilen: list[dict]) -> str:
    belastbar = [zeile for zeile in zeilen if zeile["belastbar"]]
    if not belastbar:
        return "Noch keine Marktphasen und kein Sieger. Dafür fehlen je Trader mindestens 20 abgeschlossene Fälle mit positivem unterem Rand."
    namen = ", ".join(zeile["name"] for zeile in sorted(belastbar, key=lambda zeile: zeile["score"], reverse=True)[:3])
    return f"Nur diese Trader haben eine ausreichende Stichprobe: {namen}. Der höchste Gewinn allein reicht nicht."


def _quote(renditen: list[float], nur_unten: bool) -> str:
    if len(renditen) < _SHARPE:
        return "—"
    mittel = sum(renditen) / len(renditen)
    basis = [min(0.0, wert) for wert in renditen] if nur_unten else [wert - mittel for wert in renditen]
    streuung = math.sqrt(sum(wert ** 2 for wert in basis) / len(basis))
    if streuung == 0:
        return "—"
    wert = mittel / streuung
    return f"{wert:.2f} pro Trade"


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
        if start is None or start <= 0 or ende is None:
            continue
        ergebnis.append((_zahl(netto) or Decimal(0), float(ende / start - 1)))
    return ergebnis


def _drawdown(pfad, name: str) -> float | None:
    if not pfad.exists():
        return None
    with sqlite3.connect(pfad) as verbindung:
        tabellen = {zeile[0] for zeile in verbindung.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
        if "paper_konto" not in tabellen:
            return None
        zeilen = verbindung.execute(
            "SELECT equity FROM paper_konto WHERE broker = 'Lokal' AND konto = ? ORDER BY id",
            (name,),
        ).fetchall()
    werte = [float(zeile[0]) for zeile in zeilen if _zahl(zeile[0]) is not None]
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
    if not pfad.exists():
        return 1
    with sqlite3.connect(pfad) as verbindung:
        zeile = verbindung.execute("SELECT version FROM ki_haendler_modell WHERE haendler = ?", (name,)).fetchone()
    return 1 if zeile is None else int(zeile[0])


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
