"""Alpaca nur als Paper-Handel. Live-Orders sind technisch gesperrt.

Der Handel bleibt aus, bis er ausdrücklich eingeschaltet wird. Es wird kein
Konto zurückgesetzt. Gehandelt wird höchstens mit 10.000 EUR Gegenwert.
"""

from __future__ import annotations

import json
import os
import sqlite3
import threading
from datetime import datetime, timezone
from decimal import ROUND_DOWN, Decimal
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from analyse import BERLIN
from analyse import fenster as handelsfenster

PAPER = "https://paper-api.alpaca.markets"
ALPACA = "Alpaca"
_KURS_ZEIT: datetime | None = None
STRATEGIE = "muster-3"
KONTEN = (
    {"name": "KI", "art": "ki", "regel": "Lokale Simulation. Entscheidet selbst und lernt erst nach einem geschlossenen Fall."},
    {"name": "Versuch", "art": "versuch", "sprung": 0, "regel": "Die ersten drei Namen von deiner Liste, auch ohne geprüfte Regel."},
    {"name": "Zweite", "art": "versuch", "sprung": 3, "regel": "Die nächsten drei Namen, auch ohne geprüfte Regel."},
    {"name": "Dritte", "art": "versuch", "sprung": 6, "regel": "Wieder die nächsten drei Namen."},
    {"name": "Vierte", "art": "versuch", "sprung": 9, "regel": "Wieder die nächsten drei Namen."},
    {"name": "Fünfte", "art": "versuch", "sprung": 12, "regel": "Wieder die nächsten drei Namen."},
    {"name": "Fenster", "art": "fenster", "sprung": 0, "regel": "Nur wenn das kurze Fenster heute offen ist."},
    {"name": "Fenster 2", "art": "fenster", "sprung": 3, "regel": "Das Fenster ist offen, aber nicht die ersten drei."},
    {"name": "Vorsicht", "art": "vorsicht", "regel": "Nur ab 30 unabhängigen Fällen mit Vorsprung."},
    {"name": "Belastbar", "art": "belastbar", "regel": "Nur ab 60 unabhängigen Fällen."},
    {"name": "Aktie", "art": "aktie", "sprung": 3, "regel": "Nur Aktien, und nicht dieselben ersten Namen wie Versuch."},
    {"name": "ETF", "art": "etf", "regel": "Nur ETFs, auch ohne geprüfte Regel."},
    {"name": "Krypto", "art": "krypto", "regel": "Nur Krypto, auch ohne geprüfte Regel."},
    {"name": "Eng", "art": "versuch", "sprung": 15, "stop_mal": 1, "stop_deckel": "0.04", "regel": "Engerer Stop, andere Namen."},
    {"name": "Weit", "art": "versuch", "sprung": 18, "stop_mal": 3, "stop_deckel": "0.12", "regel": "Weiterer Stop, andere Namen."},
)
START_EUR = Decimal(10000)
_SPERRE = threading.Lock()
_ERLAUBT = ("/v2/account", "/v2/positions", "/v2/orders", "/v2/assets/", "/v2/clock")


class PapierFehler(RuntimeError):
    pass


def grenzen() -> dict[str, Decimal | int]:
    return {
        "risiko": Decimal("0.01"),
        "position": Decimal("0.10"),
        "offen": 10,
        "tagesverlust": Decimal("0.02"),
        "drawdown": Decimal("0.08"),
        "reserve": Decimal("0.10"),
    }


def basis_pruefen() -> str:
    gesetzt = os.environ.get("APCA_API_BASE_URL", PAPER).strip().rstrip("/")
    if gesetzt != PAPER:
        raise PapierFehler("Nur der Paper-Endpunkt ist erlaubt. Ein Live-Endpunkt wird abgewiesen.")
    return PAPER


def schluessel() -> tuple[str, str] | None:
    _env_lesen()
    basis_pruefen()
    key = os.environ.get("APCA_API_KEY_ID", "").strip()
    geheim = os.environ.get("APCA_API_SECRET_KEY", "").strip()
    if not key or not geheim:
        return None
    return key, geheim


def zustand_lesen(pfad: Path) -> dict:
    datei = pfad.parent / "papier_zustand.json"
    if not datei.exists():
        return {"automatisch": False, "notfall": False}
    try:
        roh = json.loads(datei.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"automatisch": False, "notfall": True}
    return {"automatisch": bool(roh.get("automatisch")), "notfall": bool(roh.get("notfall"))}


def zustand_schreiben(pfad: Path, automatisch: bool, notfall: bool) -> dict:
    if automatisch and notfall:
        automatisch = False
    daten = {"automatisch": automatisch, "notfall": notfall}
    datei = pfad.parent / "papier_zustand.json"
    datei.parent.mkdir(parents=True, exist_ok=True)
    datei.write_text(json.dumps(daten), encoding="utf-8")
    return daten


def schalten(pfad: Path, automatisch: bool, bestaetigung: str, notfall: bool = False) -> dict:
    if notfall:
        return zustand_schreiben(pfad, False, True)
    if automatisch and bestaetigung != "PAPIER":
        raise PapierFehler("Paper-Handel wird nur mit der Bestätigung PAPIER eingeschaltet.")
    return zustand_schreiben(pfad, automatisch, False)


def entscheiden(zeile, position_offen: bool, stunde_ok: bool, stop: Decimal | None = None) -> dict:
    muster = _muster(zeile)
    qualitaet = str(muster.get("qualitaet") or "")
    preis = _zahl(_feld(zeile, "preis"))
    status = str(_feld(zeile, "datenstatus") or "")
    technik = _feld(zeile, "technik")
    atr = _zahl(getattr(technik, "atr", None))
    grund = _datenlage(zeile, technik)
    if position_offen:
        if preis is not None and stop is not None and preis <= stop:
            return _entscheidung(zeile, "SELL", qualitaet, grund + " Stop-Loss ist erreicht.")
        return _entscheidung(zeile, "HOLD", qualitaet, grund + " Position bleibt. Kein Stop.")
    if status != "ok" or preis is None or preis <= 0:
        return _entscheidung(zeile, "SKIP", qualitaet, grund + " Kursdaten fehlen oder sind nicht frisch.")
    if not stunde_ok:
        return _entscheidung(zeile, "SKIP", qualitaet, grund + " Außerhalb der Handelszeit für diese Art.")
    if qualitaet not in ("vorsichtig", "belastbarer") or not isinstance(muster.get("rang"), (int, float)):
        return _entscheidung(zeile, "SKIP", qualitaet, grund + " Keine ausreichende, unabhängige Datenbasis. Kein Kauf.")
    if atr is None or atr <= 0:
        return _entscheidung(zeile, "SKIP", qualitaet, grund + " ATR fehlt. Ohne Stop-Loss kein Kauf.")
    return _entscheidung(zeile, "BUY", qualitaet, grund + " Gemessenes Fenster mit Stop aus dem ATR. Kein Auftrag an sich.")


def menge_fuer(sleeve: Decimal, preis: Decimal, stop: Decimal, cash: Decimal, krypto: bool) -> Decimal | None:
    regel = grenzen()
    abstand = preis - stop
    if abstand <= 0 or preis <= 0:
        return None
    risiko = sleeve * regel["risiko"]
    roh = risiko / abstand
    deckel = (sleeve * regel["position"]) / preis
    frei = cash - sleeve * regel["reserve"]
    if frei <= 0:
        return None
    stueck = min(roh, deckel, frei / preis)
    if krypto:
        stueck = stueck.quantize(Decimal("0.000001"), rounding=ROUND_DOWN)
        return stueck if stueck > 0 else None
    ganz = stueck.to_integral_value(rounding=ROUND_DOWN)
    return ganz if ganz >= 1 else None


def kauf_gesperrt(sleeve: Decimal, spitze: Decimal, tagesstart: Decimal | None, offen: int) -> str:
    regel = grenzen()
    if offen >= int(regel["offen"]):
        return "Zu viele offene Positionen."
    if spitze > 0 and (spitze - sleeve) / spitze >= regel["drawdown"]:
        return "Drawdown-Grenze erreicht. Keine neuen Käufe."
    if tagesstart is not None and tagesstart > 0 and (tagesstart - sleeve) / tagesstart >= regel["tagesverlust"]:
        return "Tagesverlustgrenze erreicht. Keine neuen Käufe."
    return ""


def auswertung(trades: tuple[dict, ...]) -> dict:
    if not trades:
        return {
            "trades": 0,
            "treffer": "noch kein abgeschlossener Trade",
            "gewinn": "—",
            "verlust": "—",
            "faktor": "—",
            "hinweis": "Paper-Ergebnisse ändern die Handelsregel nicht.",
        }
    gewinne = [Decimal(trade["ergebnis"]) for trade in trades if Decimal(trade["ergebnis"]) > 0]
    verluste = [Decimal(trade["ergebnis"]) for trade in trades if Decimal(trade["ergebnis"]) < 0]
    summe_verlust = sum(verluste, Decimal(0))
    faktor = "—" if not summe_verlust else str((sum(gewinne, Decimal(0)) / abs(summe_verlust)).quantize(Decimal("0.01")))
    treffer = (Decimal(len(gewinne)) / Decimal(len(trades)) * 100).quantize(Decimal("0.1"))
    return {
        "trades": len(trades),
        "treffer": f"{treffer} %",
        "gewinn": _schnitt(gewinne),
        "verlust": _schnitt(verluste),
        "faktor": faktor,
        "hinweis": "Paper-Ergebnisse ändern die Handelsregel nicht.",
    }


def strategie_uebernehmen(trades: int) -> tuple[bool, str]:
    del trades
    return False, "Eine neue Regel wird nicht automatisch übernommen. Dafür fehlt eine getrennte Prüfung außerhalb dieses Laufs."


def _haendler_uebersicht(pfad: Path) -> dict:
    from haendler import uebersicht

    return uebersicht(pfad)


def ansicht(pfad: Path) -> dict:
    lage = zustand_lesen(pfad)
    konto = _letzte_kontozeile(pfad)
    lernen = auswertung(_trades(pfad))
    hinweis = "Paper-Handel ist aus. Es wird nichts gesendet."
    if lage["notfall"]:
        hinweis = "Stopp ist an. Neue Versuche sind blockiert. Ein erreichter Stop darf noch schließen."
    elif lage["automatisch"] and schluessel() is None:
        hinweis = "Alpaca ist nicht verbunden. Versuche laufen lokal zum letzten Kurs, höchstens drei neue Namen pro Lauf."
    elif lage["automatisch"]:
        hinweis = "Paper-Handel ist an. Nur Simulation, höchstens 10.000 EUR."
    return {
        "modus": "Simulation. Kein echtes Geld.",
        "automatisch": lage["automatisch"],
        "notfall": lage["notfall"],
        "hinweis": hinweis,
        "anleitung": (
            "Alpaca legt ein Paper-Konto mit 100.000 USD an. Diesen Betrag kann die API danach nicht ändern. "
            "Ein neues Paper-Konto entsteht nur im Alpaca-Dashboard. MarktRadar setzt kein Konto zurück "
            "und handelt höchstens mit 10.000 EUR Gegenwert. Schlüssel nur in der .env: "
            "APCA_API_KEY_ID und APCA_API_SECRET_KEY. Endpunkt bleibt der Paper-Server."
        ),
        "konto": konto,
        "konten": _konten_sortiert(pfad),
        "beste": beste_konten(_konten_sortiert(pfad)),
        "alpaca": _alpaca_karte(pfad),
        "haendler": _haendler_uebersicht(pfad),
        "sicherheit": _sicherheit(pfad, lage),
        "positionen": _positionen(pfad),
        "orders": _orders(pfad),
        "aktivitaet": _aktivitaet(pfad),
        "lernen": lernen,
        "strategie": STRATEGIE,
    }


def nach_runde(pfad: Path, zeilen, oeffnen=urlopen, wechselkurs=None, jetzt: datetime | None = None, liste=None) -> dict:
    if not _SPERRE.acquire(blocking=False):
        return ansicht(pfad)
    try:
        try:
            return _runde(pfad, zeilen, oeffnen, wechselkurs, jetzt or datetime.now(BERLIN), liste)
        except PapierFehler as fehler:
            _notfall_nach_fehler(pfad, str(fehler))
            return ansicht(pfad)
    finally:
        _SPERRE.release()


def _runde(pfad, zeilen, oeffnen, wechselkurs, jetzt: datetime, liste=None) -> dict:
    lage = zustand_lesen(pfad)
    _tabellen(pfad)
    if not lage["automatisch"] and not lage["notfall"]:
        return ansicht(pfad)
    if schluessel() is None or lage["notfall"]:
        return _lokal(pfad, zeilen, wechselkurs, oeffnen, jetzt, liste, nur_verkauf=lage["notfall"])
    try:
        basis_pruefen()
        konto = _anfrage(oeffnen, "GET", "/v2/account")
        uhr = _anfrage(oeffnen, "GET", "/v2/clock")
        positionen = _anfrage(oeffnen, "GET", "/v2/positions")
    except PapierFehler as fehler:
        _notfall_nach_fehler(pfad, str(fehler))
        return ansicht(pfad)
    if str(konto.get("currency") or "USD") != "USD":
        _entscheidung_speichern(pfad, {"symbol": "", "entscheidung": "SKIP", "grund": "Konto ist nicht in USD.", "strategie": STRATEGIE})
        return ansicht(pfad)
    kurs = _eurokurs(wechselkurs, oeffnen, jetzt)
    if kurs is None:
        _entscheidung_speichern(pfad, {"symbol": "", "entscheidung": "SKIP", "grund": "EUR/USD fehlt. Kein Handel.", "strategie": STRATEGIE})
        return ansicht(pfad)
    equity = _geld(konto.get("equity"))
    cash = _geld(konto.get("cash"))
    sleeve = min(equity, (START_EUR / kurs).quantize(Decimal("0.01")))
    frisch = _orders_abgleichen(pfad, oeffnen)
    order_unklar = frisch is None
    klar = _sync_alpaca(pfad, positionen, frisch or set())
    stop_sperre = _schutz_alle(pfad, oeffnen)
    markt = _marktwert(pfad, ALPACA)
    quelle = "Yahoo USDEUR=X" if wechselkurs is None else "Vorgabe"
    _snapshot(pfad, equity, cash, markt, sleeve, jetzt)
    _konto_merken(pfad, konto, sleeve, kurs, jetzt, quelle)
    spitze, tagesstart = _grenzen_aus_db(pfad, equity)
    offen = _positionen(pfad, ALPACA)
    sperre = "" if klar else "Positionen sind nicht synchron. Keine neuen Käufe."
    if not sperre:
        sperre = kauf_gesperrt(equity, spitze, tagesstart, len(offen))
    if not _kurs_frisch(jetzt):
        sperre = sperre or "EUR/USD ist nicht frisch. Keine neuen Käufe."
    if stop_sperre:
        sperre = sperre or stop_sperre
    if order_unklar:
        sperre = sperre or "Orderstatus ist unklar. Keine neuen Käufe."
    vergeben = {_norm(str(zeile["symbol"])) for zeile in offen}
    for zeile in zeilen or ():
        symbol = str(_feld(zeile, "symbol") or "")
        if not symbol:
            continue
        klasse = _klasse(zeile)
        alpaca_symbol = _alpaca_symbol(symbol, klasse)
        position = _gleiche_position(offen, symbol, alpaca_symbol)
        if position is None and (_norm(symbol) in vergeben or _norm(alpaca_symbol) in vergeben):
            position = {"symbol": alpaca_symbol, "schutz": "", "stop": "—", "menge": "0"}
        name, grund = _alpaca_entscheidung(pfad, zeile, position, klasse, uhr, jetzt, sperre)
        _entscheidung_speichern(pfad, {"symbol": symbol, "klasse": klasse, "entscheidung": name, "grund": grund, "strategie": STRATEGIE, "konto": ALPACA})
        if name == "BUY":
            _fall_merken(pfad, ALPACA, alpaca_symbol, _merkmale_text(pfad, zeile), "BUY")
            cash -= _kaufen(pfad, oeffnen, zeile, klasse, sleeve, cash, kurs, jetzt)
            vergeben.add(_norm(alpaca_symbol))
        elif name == "SELL":
            _verkaufen(pfad, oeffnen, zeile, klasse, jetzt)
    _schutz_alle(pfad, oeffnen)
    from haendler import runde as haendler_runde

    haendler_runde(pfad, zeilen, {str(_feld(zeile, "symbol") or "") for zeile in zeilen or ()}, kurs, jetzt, False)
    return ansicht(pfad)


def _alpaca_entscheidung(pfad, zeile, position: dict | None, klasse: str, uhr: dict, jetzt: datetime, sperre: str) -> tuple[str, str]:
    stunde = klasse == "krypto" or (bool(uhr.get("is_open")) and handelsfenster(jetzt) in ("xetra", "bestpreis"))
    if position is not None:
        stop = _zahl(position.get("stop"))
        preis = _zahl(_feld(zeile, "preis"))
        if "Broker-Stop" not in str(position.get("schutz") or "") and stop is not None and preis is not None and preis <= stop:
            return "SELL", "Lokale Prüfung, keine aktive Broker-Stop-Order. Der Stop ist erreicht."
        kauf, grund = _ki_kauf(pfad, zeile)
        pruefung = _validierung(pfad, zeile)
        if kauf or not pruefung[0]:
            return "HOLD", "Position bleibt. " + grund
        return "SELL", "Das Modell entscheidet den Verkauf. " + pruefung[1]
    if not stunde:
        return "SKIP", "Außerhalb der Handelszeit. Kein neuer Kauf."
    hinweis = _daten_hinweis(zeile)
    if hinweis:
        return "SKIP", hinweis
    kauf, grund = _ki_kauf(pfad, zeile)
    if not kauf:
        return "SKIP", grund
    pruefung = _validierung(pfad, zeile)
    if not pruefung[0]:
        return "SKIP", pruefung[1]
    if sperre:
        return "SKIP", sperre
    return "BUY", grund + " " + pruefung[1]


def _daten_hinweis(zeile) -> str:
    preis = _zahl(_feld(zeile, "preis"))
    status = str(_feld(zeile, "datenstatus") or "")
    if status != "ok" or preis is None or preis <= 0:
        return "Kursdaten fehlen oder sind nicht frisch."
    atr = _zahl(getattr(_feld(zeile, "technik"), "atr", None))
    if atr is None or atr <= 0:
        return "ATR fehlt. Ohne Stop-Loss kein Kauf."
    return ""


def _lokal(pfad, zeilen, wechselkurs, oeffnen, jetzt: datetime, liste, nur_verkauf: bool) -> dict:
    namen = set(liste) if liste is not None else set(_watchlist())
    try:
        kurs = _eurokurs(wechselkurs, oeffnen, jetzt)
    except (URLError, TimeoutError, OSError):
        kurs = None
    for konto in KONTEN:
        _konto_lauf(pfad, konto["name"], zeilen, namen, kurs, jetzt, nur_verkauf)
    from haendler import runde as haendler_runde

    haendler_runde(pfad, zeilen, namen, kurs, jetzt, nur_verkauf)
    return ansicht(pfad)


def _konto_lauf(pfad, konto: str, zeilen, namen: set[str], kurs, jetzt: datetime, nur_verkauf: bool) -> None:
    sleeve, cash, _equity = _lokales_guthaben(pfad, konto)
    eigene = {str(zeile["symbol"]) for zeile in _positionen(pfad, konto)}
    spitze, tagesstart = _spitze_konto(pfad, konto, cash + _marktwert(pfad, konto))
    sperre = kauf_gesperrt(cash + _marktwert(pfad, konto), spitze, tagesstart, len(eigene))
    stops = {str(zeile["symbol"]): _zahl(zeile.get("stop")) for zeile in _positionen(pfad, konto)}
    spec = _konto_von(konto)
    sprung = int(spec.get("sprung") or 0)
    platz = 0
    gesehen = False
    for zeile in zeilen or ():
        symbol = str(_feld(zeile, "symbol") or "")
        if not symbol or (symbol not in namen and symbol not in eigene):
            continue
        gesehen = True
        preis = _preis_eur(zeile, kurs)
        if preis is None:
            _merken_einmal(pfad, konto, symbol, "SKIP", "Währung oder EUR/USD fehlt. Nicht gekauft.")
            continue
        if symbol in eigene:
            stop = stops.get(symbol)
            if stop is not None and preis <= stop:
                menge = _zahl(next(eintrag["menge"] for eintrag in _positionen(pfad, konto) if eintrag["symbol"] == symbol))
                _lokal_verkaufen(pfad, konto, symbol, preis, jetzt)
                eigene.discard(symbol)
                if menge is not None:
                    cash += preis * menge
                _merken_einmal(pfad, konto, symbol, "SELL", "Stop ist erreicht. Lokal zum letzten Kurs geschlossen.")
            else:
                _jetzt_merken(pfad, konto, symbol, preis)
                _merken_einmal(pfad, konto, symbol, "HOLD", "Position bleibt offen. Stop ist nicht erreicht. Das ist eine lokale Prüfung, keine Broker-Order.")
            continue
        entscheidung = entscheiden(zeile, False, True, None)
        if "ATR fehlt" in entscheidung["grund"] or "Kursdaten fehlen" in entscheidung["grund"]:
            _merken_einmal(pfad, konto, symbol, "SKIP", entscheidung["grund"])
            continue
        if konto == "KI":
            erlaubt, grund = _ki_kauf(pfad, zeile)
        else:
            erlaubt, grund = _darf_kaufen(konto, entscheidung, zeile)
        if not erlaubt:
            _merken_einmal(pfad, konto, symbol, "SKIP", grund)
            continue
        if nur_verkauf or sperre:
            text = "Stopp ist an. Kein neuer Kauf." if nur_verkauf else sperre
            _merken_einmal(pfad, konto, symbol, "SKIP", text)
            continue
        if platz < sprung or platz >= sprung + 3:
            platz += 1
            if platz > sprung + 3:
                _merken_einmal(pfad, konto, symbol, "SKIP", "In diesem Lauf sind schon drei neue Käufe offen.")
            continue
        platz += 1
        kosten = _lokal_kaufen(
            pfad,
            konto,
            zeile,
            preis,
            kurs,
            sleeve,
            cash,
            jetzt,
            int(spec.get("stop_mal") or 2),
            Decimal(str(spec.get("stop_deckel") or "0.08")),
        )
        if kosten <= 0:
            _merken_einmal(pfad, konto, symbol, "SKIP", "Die Menge passt nicht in Risiko, Cash oder Stückzahl.")
            continue
        cash -= kosten
        eigene.add(symbol)
        _merken_einmal(pfad, konto, symbol, "VERSUCH", grund)
    if not gesehen:
        _merken_einmal(pfad, konto, "", "SKIP", "In diesem Lauf ist keiner von deiner Liste mit einem frischen Kurs dabei.")
    _lokal_konto(pfad, konto, sleeve, cash, _marktwert(pfad, konto), kurs, jetzt)


def _ki_kauf(pfad, zeile) -> tuple[bool, str]:
    from ki import eigene_entscheidung, lies_modell

    try:
        return eigene_entscheidung(lies_modell(pfad), _balken(pfad, str(_feld(zeile, "symbol") or "")), _thema(pfad, zeile))
    except sqlite3.Error:
        return False, "Das Modell ist gerade nicht lesbar."


def _ki_lernen(pfad, symbol: str, preis: Decimal) -> None:
    from ki import lerne_ausgang

    position = next((eintrag for eintrag in _positionen(pfad, "KI") if eintrag["symbol"] == symbol), None)
    if position is None:
        return
    einstieg = _zahl(position["einstieg"])
    if einstieg is None or einstieg <= 0 or preis == einstieg:
        return
    zeit = _zeit_unix(str(position["zeit"]))
    if zeit is None or _schon_gelernt(pfad, symbol, str(position["zeit"])):
        return
    modell = lerne_ausgang(pfad, _balken(pfad, symbol), _thema(pfad, position), zeit, 1.0 if preis > einstieg else 0.0)
    if modell is None:
        return
    _gelernt_merken(pfad, symbol, str(position["zeit"]))


def _balken(pfad, symbol: str):
    from kurse import Bar

    if not pfad.exists() or not symbol:
        return ()
    with sqlite3.connect(pfad) as verbindung:
        tabellen = {name for (name,) in verbindung.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
        if "kurse" not in tabellen:
            return ()
        zeilen = verbindung.execute(
            "SELECT zeit, schluss FROM kurse WHERE symbol = ? ORDER BY zeit",
            (symbol,),
        ).fetchall()
    return tuple(Bar(int(zeit), None, None, None, float(schluss), float(schluss), None) for zeit, schluss in zeilen)


def _thema(pfad, zeile) -> str:
    from ki import bekanntes_thema

    symbol = str(_feld(zeile, "symbol") or "")
    if not pfad.exists() or not symbol:
        return "unklar"
    with sqlite3.connect(pfad) as verbindung:
        tabellen = {name for (name,) in verbindung.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
        if "nachrichten" not in tabellen:
            return "unklar"
        zeile_db = verbindung.execute(
            "SELECT kategorie FROM nachrichten WHERE symbol = ? ORDER BY zeit DESC LIMIT 1",
            (symbol,),
        ).fetchone()
    thema = "" if zeile_db is None else str(zeile_db[0] or "")
    return bekanntes_thema(thema)


def _berlin_tag(text: str):
    try:
        return datetime.fromisoformat(text).astimezone(BERLIN).date()
    except ValueError:
        return None


def _zeit_unix(text: str) -> int | None:
    try:
        return int(datetime.fromisoformat(text).timestamp())
    except ValueError:
        return None


def _schon_gelernt(pfad, symbol: str, zeit: str) -> bool:
    _tabellen(pfad)
    with sqlite3.connect(pfad) as verbindung:
        return verbindung.execute(
            "SELECT 1 FROM paper_ki WHERE symbol = ? AND zeit = ?",
            (symbol, zeit),
        ).fetchone() is not None


def _gelernt_merken(pfad, symbol: str, zeit: str) -> None:
    with sqlite3.connect(pfad) as verbindung:
        verbindung.execute("INSERT OR IGNORE INTO paper_ki (symbol, zeit) VALUES (?, ?)", (symbol, zeit))


def _konto_von(name: str) -> dict:
    for konto in KONTEN:
        if konto["name"] == name:
            return konto
    return {"name": name, "art": "versuch", "sprung": 0, "regel": ""}


def beste_konten(konten: list[dict], anzahl: int = 3) -> list[dict]:
    geordnet = sorted(
        konten,
        key=lambda konto: (-float(konto.get("plus") or 0), -len(konto.get("positionen") or []), str(konto.get("name") or "")),
    )
    return geordnet[:anzahl]


def _darf_kaufen(konto: str, entscheidung: dict, zeile) -> tuple[bool, str]:
    art = str(_konto_von(konto).get("art") or "versuch")
    klasse = _klasse(zeile)
    if art == "vorsicht":
        if entscheidung["entscheidung"] == "BUY":
            return True, "Geprüfte Datenbasis. Kauf nur auf diesem Konto."
        return False, "Nicht gekauft. " + entscheidung["grund"]
    if art == "fenster":
        if _muster(zeile).get("aktiv") is True:
            return True, "Fenster ist heute offen. Kauf nur auf diesem Konto."
        return False, "Nicht gekauft. Das Fenster ist heute nicht offen."
    if art == "belastbar":
        muster = _muster(zeile)
        if muster.get("qualitaet") == "belastbarer" and isinstance(muster.get("rang"), (int, float)):
            return True, "60 unabhängige Fälle. Kauf nur auf diesem Konto."
        return False, "Nicht gekauft. Noch keine 60 unabhängigen Fälle."
    if art == "etf":
        if klasse != "etf":
            return False, "Nicht gekauft. Das ist kein ETF."
        return True, "ETF-Versuch zum letzten Kurs. Keine geprüfte Regel."
    if art == "krypto":
        if klasse != "krypto":
            return False, "Nicht gekauft. Das ist kein Krypto-Name."
        return True, "Krypto-Versuch zum letzten Kurs. Keine geprüfte Regel."
    if art == "aktie":
        if klasse != "aktie":
            return False, "Nicht gekauft. Das ist keine Aktie."
        return True, "Aktien-Versuch, andere Namen. Keine geprüfte Regel."
    return True, "Versuch zum letzten Kurs. Keine geprüfte Regel. Stop aus dem ATR."


def _watchlist() -> tuple[str, ...]:
    from beobachter import LISTE, lade_liste

    return lade_liste(LISTE)


def _preis_eur(zeile, kurs: Decimal | None) -> Decimal | None:
    preis = _geld(_feld(zeile, "preis"))
    if preis <= 0:
        return None
    waehrung = str(_feld(zeile, "waehrung") or "EUR").upper()
    if waehrung in ("EUR", ""):
        return preis
    if waehrung == "USD" and kurs is not None:
        return (preis * kurs).quantize(Decimal("0.01"))
    return None


def _lokales_guthaben(pfad: Path, konto: str) -> tuple[Decimal, Decimal, Decimal]:
    _tabellen(pfad)
    with sqlite3.connect(pfad) as verbindung:
        zeile = verbindung.execute(
            """
            SELECT sleeve, cash, equity FROM paper_konto
            WHERE broker = 'Lokal' AND konto = ?
            ORDER BY id DESC LIMIT 1
            """,
            (konto,),
        ).fetchone()
    if zeile is None:
        return START_EUR, START_EUR, START_EUR
    return _geld(zeile[0]), _geld(zeile[1]), _geld(zeile[2])


def _lokal_kaufen(pfad, konto: str, zeile, preis: Decimal, kurs, sleeve: Decimal, cash: Decimal, jetzt: datetime, stop_mal: int = 2, stop_deckel: Decimal | None = None) -> Decimal:
    atr = _geld(getattr(_feld(zeile, "technik"), "atr", None))
    waehrung = str(_feld(zeile, "waehrung") or "EUR").upper()
    if waehrung == "USD" and kurs is not None:
        atr = (atr * kurs).quantize(Decimal("0.01"))
    deckel = Decimal("0.08") if stop_deckel is None else stop_deckel
    abstand = min(atr * stop_mal, preis * deckel) if atr > 0 else Decimal(0)
    stop = (preis - abstand).quantize(Decimal("0.01"))
    if stop <= 0 or stop >= preis:
        return Decimal(0)
    klasse = _klasse(zeile)
    stueck = menge_fuer(sleeve, preis, stop, cash, klasse == "krypto")
    if stueck is None:
        return Decimal(0)
    symbol = str(_feld(zeile, "symbol"))
    kennung = _kennung(symbol, konto + "versuch", jetzt)
    if _bekannt(pfad, kennung):
        return Decimal(0)
    auftrag = {
        "symbol": symbol,
        "qty": str(stueck),
        "side": "buy",
        "type": "limit",
        "limit_price": str(preis.quantize(Decimal("0.01"))),
        "client_order_id": kennung,
    }
    _order_merken(pfad, auftrag, klasse, "lokale Simulation", stop, kurs, jetzt, "")
    _ereignis(pfad, kennung, "lokale Simulation", str(stueck), "lokal")
    _buch_kaufen(pfad, konto, symbol, str(stueck), str(preis), str(stop))
    _jetzt_merken(pfad, konto, symbol, preis)
    if konto == "KI":
        _fall_merken(pfad, konto, symbol, _merkmale_text(pfad, zeile), "BUY")
        _fall_einstieg(pfad, konto, symbol, str(preis))
    return stueck * preis


def _lokal_verkaufen(pfad, konto: str, symbol: str, preis: Decimal, jetzt: datetime) -> bool:
    position = next((eintrag for eintrag in _positionen(pfad, konto) if eintrag["symbol"] == symbol), None)
    if position is None:
        return False
    kennung = _kennung(symbol, konto + "verkauf", jetzt)
    if _bekannt(pfad, kennung):
        return False
    auftrag = {
        "symbol": symbol,
        "qty": position["menge"],
        "side": "sell",
        "type": "limit",
        "limit_price": str(preis.quantize(Decimal("0.01"))),
        "client_order_id": kennung,
    }
    _order_merken(pfad, auftrag, "lokal", "lokale Simulation", None, None, jetzt, "")
    _ereignis(pfad, kennung, "lokale Simulation", position["menge"], "lokal")
    _buch_verkaufen(pfad, konto, symbol, position["menge"], str(preis))
    return True


def _lokal_konto(pfad, konto: str, sleeve: Decimal, cash: Decimal, markt: Decimal, kurs, jetzt: datetime) -> None:
    equity = cash + markt
    with sqlite3.connect(pfad) as verbindung:
        verbindung.execute(
            """
            INSERT INTO paper_konto (broker, waehrung, equity, cash, sleeve, kurs, quelle, zeit, konto)
            VALUES ('Lokal', 'EUR', ?, ?, ?, ?, 'letzter Kurs', ?, ?)
            """,
            (
                str(equity.quantize(Decimal("0.01"))),
                str(cash.quantize(Decimal("0.01"))),
                str(sleeve),
                "" if kurs is None else str(kurs),
                jetzt.isoformat(),
                konto,
            ),
        )


def _marktwert(pfad: Path, konto: str | None = None) -> Decimal:
    summe = Decimal(0)
    for zeile in _positionen(pfad, konto):
        jetzt = _zahl(zeile.get("jetzt")) or _zahl(zeile.get("einstieg")) or Decimal(0)
        menge = _zahl(zeile.get("menge")) or Decimal(0)
        summe += jetzt * menge
    return summe


def _jetzt_merken(pfad: Path, konto: str, symbol: str, preis: Decimal) -> None:
    with sqlite3.connect(pfad) as verbindung:
        verbindung.execute(
            "UPDATE paper_buch SET jetzt = ? WHERE konto = ? AND symbol = ?",
            (str(preis), konto, symbol),
        )


def _merken_einmal(pfad: Path, konto: str, symbol: str, entscheidung: str, grund: str) -> None:
    _tabellen(pfad)
    heute = datetime.now(BERLIN).date()
    with sqlite3.connect(pfad) as verbindung:
        letzte = verbindung.execute(
            """
            SELECT entscheidung, grund, zeit FROM paper_entscheidungen
            WHERE symbol = ? AND konto = ? ORDER BY id DESC LIMIT 1
            """,
            (symbol, konto),
        ).fetchone()
    if letzte and letzte[0] == entscheidung and letzte[1] == grund and _berlin_tag(str(letzte[2])) == heute:
        return
    _entscheidung_speichern(
        pfad,
        {"symbol": symbol, "klasse": "lokal", "entscheidung": entscheidung, "grund": grund, "strategie": STRATEGIE, "konto": konto},
    )


def _aktivitaet(pfad: Path, konto: str | None = None, nur: str | None = None) -> list[dict]:
    if not pfad.exists():
        return []
    _tabellen(pfad)
    frage = "SELECT symbol, entscheidung, grund, zeit, konto FROM paper_entscheidungen"
    werte: tuple = ()
    filter_sql = []
    if konto is not None:
        filter_sql.append("konto = ?")
        werte = werte + (konto,)
    if nur is not None:
        filter_sql.append("entscheidung = ?")
        werte = werte + (nur,)
    if filter_sql:
        frage += " WHERE " + " AND ".join(filter_sql)
    frage += " ORDER BY id DESC LIMIT 8"
    with sqlite3.connect(pfad) as verbindung:
        zeilen = verbindung.execute(frage, werte).fetchall()
    return [
        {"symbol": zeile[0] or "Liste", "entscheidung": zeile[1], "grund": zeile[2], "zeit": zeile[3], "konto": zeile[4] or ""}
        for zeile in zeilen
    ]


def _kaufen(pfad, oeffnen, zeile, klasse, sleeve, cash, kurs, jetzt) -> Decimal:
    preis = _geld(_feld(zeile, "preis"))
    atr = _geld(getattr(_feld(zeile, "technik"), "atr", None))
    abstand = min(atr * 2, preis * Decimal("0.08"))
    stop = (preis - abstand).quantize(Decimal("0.01"))
    if stop <= 0 or stop >= preis:
        return Decimal(0)
    stueck = menge_fuer(sleeve, preis, stop, cash, klasse == "krypto")
    if stueck is None:
        return Decimal(0)
    alpaca_symbol = _alpaca_symbol(str(_feld(zeile, "symbol")), klasse)
    if _gehalten(_positionen(pfad, ALPACA), str(_feld(zeile, "symbol")), alpaca_symbol):
        return Decimal(0)
    if not _handelbar(oeffnen, alpaca_symbol):
        _entscheidung_speichern(pfad, {"symbol": alpaca_symbol, "entscheidung": "SKIP", "grund": "Bei Alpaca nicht als handelbar bestätigt.", "strategie": STRATEGIE, "konto": ALPACA})
        return Decimal(0)
    kennung = _kennung(alpaca_symbol, "buy", jetzt)
    if _bekannt(pfad, kennung) or _order_bei_alpaca(oeffnen, kennung) is not None:
        return Decimal(0)
    auftrag = {
        "symbol": alpaca_symbol,
        "qty": str(stueck),
        "side": "buy",
        "type": "limit",
        "time_in_force": "gtc" if klasse == "krypto" else "day",
        "limit_price": str(preis.quantize(Decimal("0.01"))),
        "client_order_id": kennung,
    }
    antwort = _order_ausfuehren(pfad, oeffnen, auftrag, klasse, stop, kurs, jetzt)
    if _status_name(str(antwort.get("status") or "")) in ("abgelehnt", "fehlgeschlagen", "storniert", ""):
        return Decimal(0)
    return stueck * preis


def _verkaufen(pfad, oeffnen, zeile, klasse, jetzt) -> None:
    symbol = _alpaca_symbol(str(_feld(zeile, "symbol")), klasse)
    position = _gleiche_position(_positionen(pfad, ALPACA), str(_feld(zeile, "symbol")), symbol)
    preis = _geld(_feld(zeile, "preis"))
    if position is None or preis <= 0:
        return
    kennung = _kennung(symbol, "sell", jetzt)
    if _bekannt(pfad, kennung) or _order_bei_alpaca(oeffnen, kennung) is not None:
        return
    auftrag = {
        "symbol": symbol,
        "qty": position["menge"],
        "side": "sell",
        "type": "limit",
        "time_in_force": "gtc" if klasse == "krypto" else "day",
        "limit_price": str(preis.quantize(Decimal("0.01"))),
        "client_order_id": kennung,
    }
    _order_ausfuehren(pfad, oeffnen, auftrag, klasse, None, None, jetzt)


def _order_ausfuehren(pfad, oeffnen, auftrag, klasse, stop, kurs, jetzt) -> dict:
    _order_merken(pfad, auftrag, klasse, "vorbereitet", stop, kurs, jetzt, "")
    try:
        antwort = _anfrage(oeffnen, "POST", "/v2/orders", auftrag)
    except PapierFehler as fehler:
        _ereignis(pfad, auftrag["client_order_id"], "fehlgeschlagen", "", str(fehler)[:240])
        return {}
    if not isinstance(antwort, dict):
        _ereignis(pfad, auftrag["client_order_id"], "fehlgeschlagen", "", "")
        return {}
    status = _status_name(str(antwort.get("status") or ""))
    _ereignis(pfad, auftrag["client_order_id"], status, str(antwort.get("filled_qty") or ""), str(antwort.get("id") or ""))
    if status in ("ausgefuehrt", "teilweise"):
        _trade_aus_fill(pfad, antwort, stop)
    return antwort


def _anfrage(oeffnen, methode: str, pfad: str, koerper: dict | None = None) -> dict | list:
    if methode not in ("GET", "POST", "DELETE") or not any(pfad.startswith(teil) for teil in _ERLAUBT):
        raise PapierFehler("Diese Alpaca-Aktion ist gesperrt.")
    if methode == "DELETE" and not pfad.startswith("/v2/orders/"):
        raise PapierFehler("Diese Alpaca-Aktion ist gesperrt.")
    if any(wort in pfad for wort in ("reset", "transfer", "wire", "ach")):
        raise PapierFehler("Kontoänderungen und Auszahlungen sind gesperrt.")
    zugang = schluessel()
    if zugang is None:
        raise PapierFehler("Paper-Schlüssel fehlen.")
    daten = None if koerper is None else json.dumps(koerper).encode("utf-8")
    anfrage = Request(basis_pruefen() + pfad, data=daten, method=methode)
    anfrage.add_header("APCA-API-KEY-ID", zugang[0])
    anfrage.add_header("APCA-API-SECRET-KEY", zugang[1])
    anfrage.add_header("Accept", "application/json")
    if daten is not None:
        anfrage.add_header("Content-Type", "application/json")
    try:
        with oeffnen(anfrage, timeout=12) as antwort:
            roh = antwort.read().decode("utf-8", errors="replace")
    except HTTPError as fehler:
        if fehler.code == 404:
            return {}
        raise PapierFehler(f"Paper-Anfrage fehlgeschlagen ({fehler.code}).") from None
    except (URLError, TimeoutError, OSError) as fehler:
        raise PapierFehler("Paper-Verbindung fehlgeschlagen.") from fehler
    if not roh:
        return {}
    gelesen = json.loads(roh)
    if isinstance(gelesen, (dict, list)):
        return gelesen
    raise PapierFehler("Antwort der Paper-API ist unbrauchbar.")


def _handelbar(oeffnen, symbol: str) -> bool:
    try:
        asset = _anfrage(oeffnen, "GET", "/v2/assets/" + symbol.replace("/", ""))
    except PapierFehler:
        return False
    return bool(asset.get("tradable")) and str(asset.get("status") or "") == "active"


def _order_bei_alpaca(oeffnen, kennung: str) -> dict | None:
    try:
        gefunden = _anfrage(oeffnen, "GET", "/v2/orders:by_client_order_id?client_order_id=" + kennung)
    except PapierFehler:
        return None
    if not gefunden:
        return None
    return gefunden if isinstance(gefunden, dict) else None


def _orders_abgleichen(pfad: Path, oeffnen) -> set[str] | None:
    orders: list = []
    frisch: set[str] = set()
    try:
        gelesen = _anfrage(oeffnen, "GET", "/v2/orders?status=all&limit=500")
    except PapierFehler:
        return None
    if isinstance(gelesen, list):
        orders.extend(eintrag for eintrag in gelesen if isinstance(eintrag, dict))
    gesehen = {str(order.get("client_order_id") or "") for order in orders}
    for kennung in _offene_kennungen(pfad):
        if kennung in gesehen:
            continue
        einzeln = _order_bei_alpaca(oeffnen, kennung)
        if isinstance(einzeln, dict) and einzeln.get("client_order_id"):
            orders.append(einzeln)
    for order in orders:
        kennung = str(order.get("client_order_id") or "")
        if not kennung.startswith("mr"):
            continue
        status = _status_name(str(order.get("status") or ""))
        menge = str(order.get("filled_qty") or "")
        bezug = str(order.get("id") or "")
        if status in ("ausgefuehrt", "teilweise") and _fill_schon(pfad, bezug, menge):
            _ereignis(pfad, kennung, status, menge, bezug)
            continue
        _order_nachtragen(pfad, order, status)
        _ereignis(pfad, kennung, status, menge, bezug)
        if status in ("ausgefuehrt", "teilweise"):
            _trade_aus_fill(pfad, order, None)
            if str(order.get("side") or "") == "buy":
                frisch.add(_norm(str(order.get("symbol") or "")))
    return frisch


def _tabellen(pfad: Path) -> None:
    pfad.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(pfad) as verbindung:
        verbindung.execute(
            """
            CREATE TABLE IF NOT EXISTS paper_konto (
                id INTEGER PRIMARY KEY,
                broker TEXT NOT NULL,
                waehrung TEXT NOT NULL,
                equity TEXT NOT NULL,
                cash TEXT NOT NULL,
                sleeve TEXT NOT NULL,
                kurs TEXT NOT NULL,
                quelle TEXT NOT NULL,
                zeit TEXT NOT NULL
            )
            """
        )
        verbindung.execute(
            """
            CREATE TABLE IF NOT EXISTS paper_orders (
                id INTEGER PRIMARY KEY,
                client_order_id TEXT NOT NULL UNIQUE,
                symbol TEXT NOT NULL,
                klasse TEXT NOT NULL,
                seite TEXT NOT NULL,
                menge TEXT NOT NULL,
                typ TEXT NOT NULL,
                status TEXT NOT NULL,
                preis TEXT NOT NULL,
                stop TEXT,
                kurs TEXT,
                zeit TEXT NOT NULL
            )
            """
        )
        verbindung.execute(
            """
            CREATE TABLE IF NOT EXISTS paper_ereignis (
                id INTEGER PRIMARY KEY,
                client_order_id TEXT NOT NULL,
                status TEXT NOT NULL,
                menge TEXT NOT NULL,
                bezug TEXT NOT NULL,
                zeit TEXT NOT NULL
            )
            """
        )
        verbindung.execute(
            """
            CREATE TABLE IF NOT EXISTS paper_positionen (
                symbol TEXT PRIMARY KEY,
                menge TEXT NOT NULL,
                einstieg TEXT NOT NULL,
                stop TEXT,
                zeit TEXT NOT NULL,
                strategie TEXT NOT NULL
            )
            """
        )
        spalten = {str(zeile[1]) for zeile in verbindung.execute("PRAGMA table_info(paper_positionen)")}
        if "jetzt" not in spalten:
            verbindung.execute("ALTER TABLE paper_positionen ADD COLUMN jetzt TEXT")
        verbindung.execute(
            """
            CREATE TABLE IF NOT EXISTS paper_ki (
                symbol TEXT NOT NULL,
                zeit TEXT NOT NULL,
                PRIMARY KEY (symbol, zeit)
            )
            """
        )
        verbindung.execute(
            """
            CREATE TABLE IF NOT EXISTS paper_buch (
                konto TEXT NOT NULL,
                symbol TEXT NOT NULL,
                menge TEXT NOT NULL,
                einstieg TEXT NOT NULL,
                stop TEXT,
                zeit TEXT NOT NULL,
                strategie TEXT NOT NULL,
                jetzt TEXT,
                schutz TEXT,
                PRIMARY KEY (konto, symbol)
            )
            """
        )
        _spalte_dazu(verbindung, "paper_buch", "schutz")
        verbindung.execute(
            """
            INSERT OR IGNORE INTO paper_buch (konto, symbol, menge, einstieg, stop, zeit, strategie, jetzt)
            SELECT 'Versuch', symbol, menge, einstieg, stop, zeit, strategie, jetzt FROM paper_positionen
            """
        )
        verbindung.execute(
            """
            CREATE TABLE IF NOT EXISTS paper_trades (
                id INTEGER PRIMARY KEY,
                symbol TEXT NOT NULL,
                menge TEXT NOT NULL,
                ergebnis TEXT NOT NULL,
                strategie TEXT NOT NULL,
                zeit TEXT NOT NULL
            )
            """
        )
        verbindung.execute(
            """
            CREATE TABLE IF NOT EXISTS paper_entscheidungen (
                id INTEGER PRIMARY KEY,
                symbol TEXT NOT NULL,
                klasse TEXT NOT NULL,
                entscheidung TEXT NOT NULL,
                qualitaet TEXT NOT NULL,
                grund TEXT NOT NULL,
                strategie TEXT NOT NULL,
                zeit TEXT NOT NULL
            )
            """
        )
        verbindung.execute(
            """
            CREATE TABLE IF NOT EXISTS paper_snapshots (
                id INTEGER PRIMARY KEY,
                sleeve TEXT NOT NULL,
                zeit TEXT NOT NULL
            )
            """
        )
        for name in ("equity", "cash", "markt", "spitze", "drawdown", "tagesstart"):
            _spalte_dazu(verbindung, "paper_snapshots", name)
        verbindung.execute(
            """
            CREATE TABLE IF NOT EXISTS paper_faelle (
                id INTEGER PRIMARY KEY,
                konto TEXT NOT NULL,
                symbol TEXT NOT NULL,
                entscheidung TEXT NOT NULL,
                merkmale TEXT NOT NULL,
                einstieg TEXT,
                ausstieg TEXT,
                dauer TEXT,
                ergebnis TEXT,
                kosten TEXT,
                benchmark TEXT,
                strategie TEXT NOT NULL,
                gelernt INTEGER NOT NULL DEFAULT 0,
                zeit TEXT NOT NULL
            )
            """
        )
        for tabelle in ("paper_konto", "paper_entscheidungen", "paper_trades", "paper_orders"):
            _spalte_dazu(verbindung, tabelle, "konto")
        verbindung.execute("UPDATE paper_konto SET konto = 'Versuch' WHERE broker = 'Lokal' AND (konto IS NULL OR konto = '')")
        verbindung.execute("UPDATE paper_entscheidungen SET konto = 'Versuch' WHERE konto IS NULL OR konto = ''")


def _entscheidung(zeile, name: str, qualitaet: str, grund: str) -> dict:
    return {
        "symbol": str(_feld(zeile, "symbol") or ""),
        "klasse": _klasse(zeile),
        "entscheidung": name,
        "qualitaet": qualitaet,
        "grund": grund,
        "strategie": STRATEGIE,
        "preis": str(_feld(zeile, "preis") or ""),
    }


def _datenlage(zeile, technik) -> str:
    teile = [f"Strategie {STRATEGIE}."]
    teile.append("MACD fehlt." if getattr(technik, "macd", None) is None else "MACD ist vorhanden und wird nicht als Kaufgrund verwendet.")
    teile.append("Volumen ist in der vorhandenen Technik nicht enthalten.")
    fundamental = str(_feld(zeile, "fundamental") or "fehlt")
    teile.append("Fundamentaldaten fehlen." if fundamental in ("", "fehlt") else "Fundamentaldaten sind ein Hinweis, kein Kaufgrund.")
    teile.append("Nachrichten sind kein Kaufgrund und keine Ursache.")
    return " ".join(teile)


def _klasse(zeile) -> str:
    symbol = str(_feld(zeile, "symbol") or "").upper()
    if symbol.endswith("-USD"):
        return "krypto"
    zahlen = _feld(zeile, "kennzahlen")
    if getattr(zahlen, "ist_etf", False) or str(_feld(zeile, "bereich") or "") == "ETFs":
        return "etf"
    return "aktie"


def _alpaca_symbol(symbol: str, klasse: str) -> str:
    if klasse == "krypto" and symbol.upper().endswith("-USD"):
        return symbol.upper().replace("-USD", "/USD")
    return symbol.upper()


def _kennung(symbol: str, seite: str, jetzt: datetime) -> str:
    rein = "".join(zeichen for zeichen in f"mr{STRATEGIE}{symbol}{seite}{jetzt:%Y%m%d}" if zeichen.isalnum())
    return rein[:48]


def _feld(zeile, name: str):
    if isinstance(zeile, dict):
        return zeile.get(name)
    return getattr(zeile, name, None)


def _muster(zeile) -> dict:
    muster = _feld(zeile, "muster")
    return muster if isinstance(muster, dict) else {}


def _zahl(wert) -> Decimal | None:
    if isinstance(wert, bool) or wert is None or wert == "":
        return None
    try:
        zahl = Decimal(str(wert))
    except (ArithmeticError, ValueError):
        return None
    if not zahl.is_finite():
        return None
    return zahl


def _geld(wert) -> Decimal:
    zahl = _zahl(wert)
    if zahl is None:
        return Decimal(0)
    return zahl.quantize(Decimal("0.0001"))


def _kurs_frisch(jetzt: datetime) -> bool:
    if _KURS_ZEIT is None:
        return False
    alter = jetzt - _KURS_ZEIT
    return alter.total_seconds() <= 3 * 24 * 3600 and alter.total_seconds() >= -15 * 60


def _eurokurs(wechselkurs, oeffnen, jetzt: datetime) -> Decimal | None:
    global _KURS_ZEIT
    if wechselkurs is None:
        from kurse import yahoo_kurs

        try:
            kurs = yahoo_kurs("USDEUR=X", oeffnen)
        except (ConnectionError, LookupError, ValueError, json.JSONDecodeError):
            _KURS_ZEIT = None
            return None
        _KURS_ZEIT = datetime.fromtimestamp(kurs.kurszeit, BERLIN) if kurs.kurszeit else None
        zahl = _zahl(kurs.preis)
    else:
        wert = wechselkurs("USD")
        if isinstance(wert, tuple):
            _KURS_ZEIT = wert[1] if isinstance(wert[1], datetime) else None
            zahl = _zahl(wert[0])
        else:
            _KURS_ZEIT = jetzt
            zahl = _zahl(wert)
    if zahl is None or zahl <= 0:
        _KURS_ZEIT = None
        return None
    return zahl


def _norm(symbol: str) -> str:
    return "".join(zeichen for zeichen in symbol.upper() if zeichen.isalnum())


def _gehalten(offen, symbol: str, alpaca_symbol: str) -> bool:
    return _gleiche_position(offen, symbol, alpaca_symbol) is not None


def _gleiche_position(offen, symbol: str, alpaca_symbol: str):
    ziele = {_norm(symbol), _norm(alpaca_symbol)}
    for zeile in offen:
        if _norm(str(zeile.get("symbol") or "")) in ziele:
            return zeile
    return None


def _validierung(pfad, zeile) -> tuple[bool, str]:
    from ki import messe

    symbol = str(_feld(zeile, "symbol") or "")
    try:
        ergebnis = messe(pfad, symbol, _balken(pfad, symbol))
    except sqlite3.Error:
        return False, "Getrennte Prüfung ist nicht lesbar. Kein Kauf."
    if ergebnis is None:
        return False, "Getrennte Prüfung fehlt. Kein Kauf."
    treffer, gesamt = ergebnis
    if gesamt <= 0 or treffer * 2 < gesamt:
        return False, f"Getrennte Prüfung {treffer} von {gesamt}. Kein Kauf."
    return True, f"Getrennte Prüfung {treffer} von {gesamt}."


def _sync_alpaca(pfad, positionen, behalten: set[str]) -> bool:
    if not isinstance(positionen, list):
        return False
    gesehen: set[str] = set()
    for eintrag in positionen:
        if not isinstance(eintrag, dict):
            continue
        symbol = str(eintrag.get("symbol") or "")
        menge = _zahl(eintrag.get("qty"))
        einstieg = _zahl(eintrag.get("avg_entry_price"))
        jetzt = _zahl(eintrag.get("current_price")) or einstieg
        if not symbol or menge is None or einstieg is None or jetzt is None:
            continue
        gesehen.add(_norm(symbol))
        _buch_setzen(pfad, ALPACA, symbol, str(menge), str(einstieg), str(jetzt), "")
    for zeile in list(_positionen(pfad, ALPACA)):
        if _norm(zeile["symbol"]) in gesehen or _norm(zeile["symbol"]) in behalten:
            continue
        _buch_verkaufen(pfad, ALPACA, zeile["symbol"], zeile["menge"], str(zeile["jetzt"]))
    return True


def _buch_setzen(pfad, konto: str, symbol: str, menge: str, einstieg: str, jetzt: str, stop: str) -> None:
    _tabellen(pfad)
    with sqlite3.connect(pfad) as verbindung:
        zeilen = verbindung.execute("SELECT symbol, stop FROM paper_buch WHERE konto = ?", (konto,)).fetchall()
        treffer = next((zeile for zeile in zeilen if _norm(zeile[0]) == _norm(symbol)), None)
        if treffer is not None:
            behalten = treffer[1] if stop in ("", None) else stop
            verbindung.execute(
                """
                UPDATE paper_buch
                SET symbol = ?, menge = ?, einstieg = ?, jetzt = ?, stop = ?
                WHERE konto = ? AND symbol = ?
                """,
                (symbol, menge, einstieg, jetzt, behalten, konto, treffer[0]),
            )
            return
        verbindung.execute(
            """
            INSERT INTO paper_buch (konto, symbol, menge, einstieg, stop, zeit, strategie, jetzt, schutz)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (konto, symbol, menge, einstieg, stop, datetime.now(timezone.utc).isoformat(), STRATEGIE, jetzt, "Stop fehlt"),  # noqa: UP017
        )


def _status_name(status: str) -> str:
    name = status.lower()
    zuordnung = {
        "new": "angenommen",
        "accepted": "angenommen",
        "pending_new": "angenommen",
        "accepted_for_bidding": "angenommen",
        "partially_filled": "teilweise",
        "filled": "ausgefuehrt",
        "canceled": "storniert",
        "cancelled": "storniert",
        "expired": "storniert",
        "done_for_day": "storniert",
        "rejected": "abgelehnt",
        "vorbereitet": "vorbereitet",
        "eingereicht": "eingereicht",
        "angenommen": "angenommen",
        "teilweise": "teilweise",
        "ausgefuehrt": "ausgefuehrt",
        "abgelehnt": "abgelehnt",
        "storniert": "storniert",
        "fehlgeschlagen": "fehlgeschlagen",
    }
    return zuordnung.get(name, "fehlgeschlagen")


def _offene_kennungen(pfad: Path) -> list[str]:
    if not pfad.exists():
        return []
    _tabellen(pfad)
    fertig = ("ausgefuehrt", "abgelehnt", "storniert", "fehlgeschlagen", "filled", "lokale Simulation")
    with sqlite3.connect(pfad) as verbindung:
        zeilen = verbindung.execute("SELECT client_order_id, status FROM paper_orders").fetchall()
    return [str(kennung) for kennung, status in zeilen if str(status) not in fertig and str(kennung).startswith("mr")]


def _fill_schon(pfad: Path, bezug: str, menge: str) -> bool:
    if not bezug:
        return False
    ziel = _zahl(menge) or Decimal(0)
    with sqlite3.connect(pfad) as verbindung:
        zeilen = verbindung.execute("SELECT menge FROM paper_ereignis WHERE bezug = ?", (bezug,)).fetchall()
    return any((_zahl(zeile[0]) or Decimal(0)) >= ziel > 0 for zeile in zeilen)


def _order_nachtragen(pfad, order: dict, status: str) -> None:
    kennung = str(order.get("client_order_id") or "")
    if not kennung or _bekannt(pfad, kennung):
        return
    auftrag = {
        "client_order_id": kennung,
        "symbol": str(order.get("symbol") or ""),
        "side": str(order.get("side") or ""),
        "qty": str(order.get("qty") or order.get("filled_qty") or ""),
        "type": str(order.get("type") or "limit"),
        "limit_price": str(order.get("limit_price") or order.get("filled_avg_price") or ""),
        "stop_price": str(order.get("stop_price") or ""),
    }
    _order_merken(pfad, auftrag, "aktie", status, _zahl(order.get("stop_price")), None, datetime.now(BERLIN), "")


def _stop_aus_kauf(pfad, symbol: str) -> Decimal | None:
    if not pfad.exists():
        return None
    with sqlite3.connect(pfad) as verbindung:
        zeilen = verbindung.execute(
            "SELECT symbol, stop FROM paper_orders WHERE seite = 'buy' AND stop IS NOT NULL ORDER BY id DESC"
        ).fetchall()
    for name, stop in zeilen:
        if _norm(str(name)) == _norm(symbol):
            return _zahl(stop)
    return None


def _schutz_alle(pfad, oeffnen) -> str:
    try:
        offen = _anfrage(oeffnen, "GET", "/v2/orders?status=open&limit=500")
    except PapierFehler:
        return "Stop unklar. Keine neuen Käufe."
    if not isinstance(offen, list):
        return "Stop unklar. Keine neuen Käufe."
    for zeile in _positionen(pfad, ALPACA):
        if not _schutz_eine(pfad, oeffnen, zeile, offen):
            return "Stop unklar. Keine neuen Käufe."
    return ""


def _schutz_eine(pfad, oeffnen, zeile: dict, offen: list) -> bool:
    symbol = str(zeile["symbol"])
    menge = str(zeile["menge"])
    stop = _zahl(zeile.get("stop")) or _stop_aus_kauf(pfad, symbol)
    if stop is None or stop <= 0:
        _schutz_text(pfad, symbol, "Stop fehlt. Keine Broker-Order.")
        return True
    _stop_am_buch(pfad, symbol, stop)
    if _stop_passt(offen, symbol, menge, stop) or _lokaler_stop_passt(pfad, symbol, menge, stop):
        _schutz_text(pfad, symbol, "Broker-Stop")
        return True
    if _stop_abgelehnt(pfad, symbol, menge):
        _schutz_text(pfad, symbol, "kein Broker-Stop. Die lokale Prüfung ist kein Ersatz.")
        return True
    for order in offen:
        if _norm(str(order.get("symbol") or "")) != _norm(symbol):
            continue
        if str(order.get("side") or "") != "sell" or str(order.get("type") or "") not in ("stop", "stop_limit"):
            continue
        if not _stop_stornieren(pfad, oeffnen, order):
            _schutz_text(pfad, symbol, "Stop unklar. Kein zweiter Stop.")
            return False
    klasse = "krypto" if "/" in symbol or symbol.upper().endswith("USD") else "aktie"
    kennung = _neue_stop_kennung(pfad, symbol)
    auftrag = {
        "symbol": symbol,
        "qty": menge,
        "side": "sell",
        "type": "stop_limit" if klasse == "krypto" else "stop",
        "time_in_force": "gtc",
        "stop_price": str(stop),
        "client_order_id": kennung,
    }
    if klasse == "krypto":
        auftrag["limit_price"] = str((stop * Decimal("0.99")).quantize(Decimal("0.01")))
    antwort = _order_ausfuehren(pfad, oeffnen, auftrag, klasse, stop, None, datetime.now(BERLIN))
    status = _status_name(str(antwort.get("status") or "fehlgeschlagen"))
    if status in ("abgelehnt", "fehlgeschlagen", "storniert"):
        _schutz_text(pfad, symbol, "kein Broker-Stop. Die lokale Prüfung ist kein Ersatz.")
    else:
        _schutz_text(pfad, symbol, "Broker-Stop")
    return True


def _stop_passt(offen: list, symbol: str, menge: str, stop: Decimal) -> bool:
    for order in offen:
        if _norm(str(order.get("symbol") or "")) != _norm(symbol):
            continue
        if str(order.get("side") or "") != "sell" or str(order.get("type") or "") not in ("stop", "stop_limit"):
            continue
        if str(order.get("qty") or "") == menge and _zahl(order.get("stop_price")) == stop:
            return True
    return False


def _lokaler_stop_passt(pfad, symbol: str, menge: str, stop: Decimal) -> bool:
    with sqlite3.connect(pfad) as verbindung:
        zeilen = verbindung.execute(
            "SELECT symbol, menge, stop, status, typ FROM paper_orders WHERE seite = 'sell'"
        ).fetchall()
    for name, order_menge, order_stop, status, typ in zeilen:
        if _norm(str(name)) != _norm(symbol) or str(typ) not in ("stop", "stop_limit"):
            continue
        if str(status) in ("abgelehnt", "fehlgeschlagen", "storniert", "ausgefuehrt"):
            continue
        if str(order_menge) == menge and _zahl(order_stop) == stop:
            return True
    return False


def _stop_abgelehnt(pfad, symbol: str, menge: str) -> bool:
    with sqlite3.connect(pfad) as verbindung:
        zeilen = verbindung.execute(
            "SELECT symbol, menge, status, typ FROM paper_orders WHERE seite = 'sell'"
        ).fetchall()
    return any(
        _norm(str(name)) == _norm(symbol) and str(order_menge) == menge and str(typ) in ("stop", "stop_limit") and str(status) in ("abgelehnt", "fehlgeschlagen")
        for name, order_menge, status, typ in zeilen
    )


def _stop_stornieren(pfad, oeffnen, order: dict) -> bool:
    bezug = str(order.get("id") or "")
    kennung = str(order.get("client_order_id") or "")
    if not bezug:
        return True
    try:
        _anfrage(oeffnen, "DELETE", "/v2/orders/" + bezug)
    except PapierFehler:
        return False
    if kennung:
        _ereignis(pfad, kennung, "storniert", "", bezug)
    return True


def _neue_stop_kennung(pfad, symbol: str) -> str:
    basis = "".join(zeichen for zeichen in f"mrstop{symbol}" if zeichen.isalnum())[:40]
    nummer = 0
    while _bekannt(pfad, basis if nummer == 0 else f"{basis}{nummer}"):
        nummer += 1
    return basis if nummer == 0 else f"{basis}{nummer}"


def _schutz_text(pfad, symbol: str, text: str) -> None:
    with sqlite3.connect(pfad) as verbindung:
        verbindung.execute("UPDATE paper_buch SET schutz = ? WHERE konto = ? AND symbol = ?", (text, ALPACA, symbol))
        if verbindung.total_changes:
            return
        zeilen = verbindung.execute("SELECT symbol FROM paper_buch WHERE konto = ?", (ALPACA,)).fetchall()
        for (name,) in zeilen:
            if _norm(name) == _norm(symbol):
                verbindung.execute("UPDATE paper_buch SET schutz = ? WHERE konto = ? AND symbol = ?", (text, ALPACA, name))


def _stop_am_buch(pfad, symbol: str, stop: Decimal) -> None:
    with sqlite3.connect(pfad) as verbindung:
        verbindung.execute(
            "UPDATE paper_buch SET stop = ? WHERE konto = ? AND symbol = ? AND (stop IS NULL OR stop = '' OR stop = '—')",
            (str(stop), ALPACA, symbol),
        )


def _merkmale_text(pfad, zeile) -> str:
    from ki import merkmale

    eingabe = merkmale(_balken(pfad, str(_feld(zeile, "symbol") or "")), None, _thema(pfad, zeile))
    if eingabe is None:
        return ""
    return json.dumps(list(eingabe))


def _fall_merken(pfad, konto: str, symbol: str, merkmale_text: str, entscheidung: str) -> None:
    _tabellen(pfad)
    with sqlite3.connect(pfad) as verbindung:
        offen = verbindung.execute(
            "SELECT id FROM paper_faelle WHERE konto = ? AND symbol = ? AND ausstieg IS NULL",
            (konto, symbol),
        ).fetchone()
        if offen is not None or not merkmale_text:
            return
        verbindung.execute(
            """
            INSERT INTO paper_faelle
            (konto, symbol, entscheidung, merkmale, kosten, benchmark, strategie, gelernt, zeit)
            VALUES (?, ?, ?, ?, 'nicht gemeldet', 'nicht gemessen', ?, 0, ?)
            """,
            (konto, symbol, entscheidung, merkmale_text, STRATEGIE, datetime.now(timezone.utc).isoformat()),  # noqa: UP017
        )


def _fall_einstieg(pfad, konto: str, symbol: str, preis: str) -> None:
    if not pfad.exists():
        return
    _tabellen(pfad)
    with sqlite3.connect(pfad) as verbindung:
        verbindung.execute(
            """
            UPDATE paper_faelle SET einstieg = ?
            WHERE konto = ? AND symbol = ? AND ausstieg IS NULL AND einstieg IS NULL
            """,
            (preis, konto, symbol),
        )


def _fall_schliessen(pfad, konto: str, symbol: str, einstieg: str, ausstieg: str, start: str) -> None:
    if konto not in ("KI", ALPACA):
        return
    _tabellen(pfad)
    with sqlite3.connect(pfad) as verbindung:
        zeile = verbindung.execute(
            """
            SELECT id, merkmale, gelernt, zeit FROM paper_faelle
            WHERE konto = ? AND symbol = ? AND ausstieg IS NULL AND einstieg IS NOT NULL
            ORDER BY id DESC LIMIT 1
            """,
            (konto, symbol),
        ).fetchone()
        if zeile is None:
            return
        nummer, merkmale_text, gelernt, zeit = zeile
        ergebnis = (Decimal(ausstieg) - Decimal(einstieg)).quantize(Decimal("0.01"))
        dauer = ""
        anfang = _zeit_unix(start) or _zeit_unix(str(zeit))
        if anfang is not None:
            dauer = str(max(0, int(datetime.now(timezone.utc).timestamp()) - anfang))  # noqa: UP017
        verbindung.execute(
            "UPDATE paper_faelle SET ausstieg = ?, ergebnis = ?, dauer = ? WHERE id = ?",
            (ausstieg, str(ergebnis), dauer, nummer),
        )
    if gelernt:
        return
    try:
        eingabe = tuple(json.loads(merkmale_text))
    except (TypeError, json.JSONDecodeError):
        return
    if not eingabe:
        return
    from ki import lerne_merkmale

    if lerne_merkmale(pfad, tuple(float(wert) for wert in eingabe), 1.0 if ergebnis > 0 else 0.0) is None:
        return
    with sqlite3.connect(pfad) as verbindung:
        verbindung.execute("UPDATE paper_faelle SET gelernt = 1 WHERE id = ?", (nummer,))


def _env_lesen() -> None:
    datei = Path(".env")
    if not datei.exists():
        return
    for zeile in datei.read_text(encoding="utf-8").splitlines():
        if not zeile or zeile.strip().startswith("#") or "=" not in zeile:
            continue
        name, wert = zeile.split("=", 1)
        name = name.strip()
        if name in ("APCA_API_KEY_ID", "APCA_API_SECRET_KEY", "APCA_API_BASE_URL") and name not in os.environ:
            os.environ[name] = wert.strip().strip('"')


def _notfall_nach_fehler(pfad: Path, text: str) -> None:
    zustand_schreiben(pfad, False, True)
    _entscheidung_speichern(pfad, {"symbol": "", "entscheidung": "SKIP", "grund": text[:240], "strategie": STRATEGIE})


def _spalte_dazu(verbindung, tabelle: str, name: str) -> None:
    spalten = {str(zeile[1]) for zeile in verbindung.execute(f"PRAGMA table_info({tabelle})")}
    if name not in spalten:
        verbindung.execute(f"ALTER TABLE {tabelle} ADD COLUMN {name} TEXT")


def _entscheidung_speichern(pfad: Path, entscheidung: dict) -> None:
    _tabellen(pfad)
    with sqlite3.connect(pfad) as verbindung:
        verbindung.execute(
            """
            INSERT INTO paper_entscheidungen (symbol, klasse, entscheidung, qualitaet, grund, strategie, zeit, konto)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                str(entscheidung.get("symbol") or ""),
                str(entscheidung.get("klasse") or ""),
                str(entscheidung.get("entscheidung") or "SKIP"),
                str(entscheidung.get("qualitaet") or ""),
                str(entscheidung.get("grund") or ""),
                str(entscheidung.get("strategie") or STRATEGIE),
                datetime.now(timezone.utc).isoformat(),  # noqa: UP017
                str(entscheidung.get("konto") or "Alpaca"),
            ),
        )


def _order_merken(pfad, auftrag, klasse, status, stop, kurs, jetzt, alpaca_id) -> None:
    del jetzt, alpaca_id
    _tabellen(pfad)
    with sqlite3.connect(pfad) as verbindung:
        verbindung.execute(
            """
            INSERT OR IGNORE INTO paper_orders
            (client_order_id, symbol, klasse, seite, menge, typ, status, preis, stop, kurs, zeit)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                auftrag["client_order_id"],
                auftrag["symbol"],
                klasse,
                auftrag["side"],
                auftrag["qty"],
                auftrag["type"],
                status,
                str(auftrag.get("limit_price") or auftrag.get("stop_price") or ""),
                None if stop is None else str(stop),
                None if kurs is None else str(kurs),
                datetime.now(timezone.utc).isoformat()  # noqa: UP017,
            ),
        )


def _ereignis(pfad: Path, kennung: str, status: str, menge: str, bezug: str) -> None:
    _tabellen(pfad)
    with sqlite3.connect(pfad) as verbindung:
        verbindung.execute(
            "INSERT INTO paper_ereignis (client_order_id, status, menge, bezug, zeit) VALUES (?, ?, ?, ?, ?)",
            (kennung, status, menge, bezug, datetime.now(timezone.utc).isoformat()),  # noqa: UP017
        )
        verbindung.execute("UPDATE paper_orders SET status = ? WHERE client_order_id = ?", (status, kennung))


def _bekannt(pfad: Path, kennung: str) -> bool:
    _tabellen(pfad)
    with sqlite3.connect(pfad) as verbindung:
        zeile = verbindung.execute("SELECT status FROM paper_orders WHERE client_order_id = ?", (kennung,)).fetchone()
    return zeile is not None


def _konto_merken(pfad, konto, sleeve, kurs, jetzt, quelle: str = "Yahoo USDEUR=X") -> None:
    with sqlite3.connect(pfad) as verbindung:
        verbindung.execute(
            """
            INSERT INTO paper_konto (broker, waehrung, equity, cash, sleeve, kurs, quelle, zeit)
            VALUES ('Alpaca Paper', 'USD', ?, ?, ?, ?, ?, ?)
            """,
            (str(_geld(konto.get("equity"))), str(_geld(konto.get("cash"))), str(sleeve), str(kurs), quelle, jetzt.isoformat()),
        )


def _snapshot(pfad, equity: Decimal, cash: Decimal, markt: Decimal, sleeve: Decimal, jetzt: datetime) -> None:
    _tabellen(pfad)
    with sqlite3.connect(pfad) as verbindung:
        zeilen = verbindung.execute("SELECT equity, sleeve, zeit FROM paper_snapshots ORDER BY id").fetchall()
        werte = []
        for equity_text, sleeve_text, zeit in zeilen:
            basis = equity_text if equity_text not in (None, "") else sleeve_text
            zahl = _zahl(basis)
            if zahl is not None:
                werte.append((zahl, str(zeit)))
        spitze = max([wert for wert, _zeit in werte] + [equity])
        heute = [wert for wert, zeit in werte if zeit.startswith(jetzt.date().isoformat())]
        start = heute[0] if heute else equity
        drawdown = Decimal(0) if spitze <= 0 else ((spitze - equity) / spitze).quantize(Decimal("0.0001"))
        verbindung.execute(
            """
            INSERT INTO paper_snapshots (sleeve, zeit, equity, cash, markt, spitze, drawdown, tagesstart)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                str(sleeve),
                jetzt.date().isoformat() + "T" + jetzt.strftime("%H:%M"),
                str(equity),
                str(cash),
                str(markt),
                str(spitze),
                str(drawdown),
                str(start),
            ),
        )


def _grenzen_aus_db(pfad: Path, equity: Decimal) -> tuple[Decimal, Decimal | None]:
    _tabellen(pfad)
    with sqlite3.connect(pfad) as verbindung:
        zeilen = verbindung.execute("SELECT equity, sleeve, zeit FROM paper_snapshots ORDER BY id").fetchall()
    werte = []
    for equity_text, sleeve_text, zeit in zeilen:
        basis = equity_text if equity_text not in (None, "") else sleeve_text
        zahl = _zahl(basis)
        if zahl is not None:
            werte.append((zahl, str(zeit)))
    if not werte:
        werte = [(equity, "")]
    heute = [wert for wert, zeit in werte if zeit.startswith(datetime.now(BERLIN).date().isoformat())]
    return max(wert for wert, _zeit in werte), (heute[0] if heute else None)


def _positionen(pfad: Path, konto: str | None = None) -> list[dict]:
    if not pfad.exists():
        return []
    _tabellen(pfad)
    frage = "SELECT konto, symbol, menge, einstieg, stop, zeit, jetzt, schutz FROM paper_buch"
    werte: tuple = ()
    if konto is not None:
        frage += " WHERE konto = ?"
        werte = (konto,)
    with sqlite3.connect(pfad) as verbindung:
        zeilen = verbindung.execute(frage, werte).fetchall()
    return [
        {
            "konto": zeile[0],
            "symbol": zeile[1],
            "menge": zeile[2],
            "einstieg": zeile[3],
            "stop": zeile[4] or "—",
            "zeit": zeile[5],
            "jetzt": zeile[6] or zeile[3],
            "schutz": zeile[7] or ("nur lokale Prüfung" if zeile[0] != ALPACA else "Stop fehlt"),
        }
        for zeile in zeilen
    ]


def _buch_kaufen(pfad: Path, konto: str, symbol: str, menge: str, preis: str, stop: str) -> None:
    with sqlite3.connect(pfad) as verbindung:
        vorhanden = verbindung.execute(
            "SELECT symbol FROM paper_buch WHERE konto = ? AND symbol = ?",
            (konto, symbol),
        ).fetchone()
        if vorhanden:
            return
        verbindung.execute(
            """
            INSERT INTO paper_buch (konto, symbol, menge, einstieg, stop, zeit, strategie, jetzt)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (konto, symbol, menge, preis, stop, datetime.now(timezone.utc).isoformat(), STRATEGIE, preis),  # noqa: UP017
        )


def _buch_verkaufen(pfad: Path, konto: str, symbol: str, menge: str, preis: str) -> None:
    with sqlite3.connect(pfad) as verbindung:
        alt = verbindung.execute(
            "SELECT menge, einstieg, zeit FROM paper_buch WHERE konto = ? AND symbol = ?",
            (konto, symbol),
        ).fetchone()
        if alt is None:
            return
        ergebnis = (Decimal(preis) - Decimal(alt[1])) * Decimal(menge)
        verbindung.execute(
            """
            INSERT INTO paper_trades (symbol, menge, ergebnis, strategie, zeit, konto)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (symbol, menge, str(ergebnis.quantize(Decimal("0.01"))), STRATEGIE, datetime.now(timezone.utc).isoformat(), konto),  # noqa: UP017
        )
        verbindung.execute("DELETE FROM paper_buch WHERE konto = ? AND symbol = ?", (konto, symbol))
    _fall_schliessen(pfad, konto, symbol, str(alt[1]), preis, str(alt[2]))


def _spitze_konto(pfad: Path, konto: str, equity: Decimal) -> tuple[Decimal, Decimal | None]:
    with sqlite3.connect(pfad) as verbindung:
        zeilen = verbindung.execute(
            "SELECT equity, zeit FROM paper_konto WHERE broker = 'Lokal' AND konto = ? ORDER BY id",
            (konto,),
        ).fetchall()
    werte = [Decimal(zeile[0]) for zeile in zeilen] or [equity]
    heute = [Decimal(zeile[0]) for zeile in zeilen if str(zeile[1]).startswith(datetime.now(BERLIN).date().isoformat())]
    return max(werte), (heute[0] if heute else None)


def _konten_ansicht(pfad: Path) -> list[dict]:
    _tabellen(pfad)
    bilder = []
    for konto in KONTEN:
        name = konto["name"]
        _sleeve, cash, _equity = _lokales_guthaben(pfad, name)
        equity = cash + _marktwert(pfad, name)
        differenz = equity - START_EUR
        positionen = []
        for zeile in _positionen(pfad, name):
            einstieg = _zahl(zeile["einstieg"]) or Decimal(0)
            jetzt = _zahl(zeile["jetzt"]) or einstieg
            menge = _zahl(zeile["menge"]) or Decimal(0)
            abstand = (jetzt - einstieg) * menge
            prozent = Decimal(0) if einstieg <= 0 else (jetzt - einstieg) / einstieg * Decimal(100)
            positionen.append(
                {
                    "symbol": zeile["symbol"],
                    "menge": zeile["menge"],
                    "einstieg": _euro(einstieg, False),
                    "jetzt": _euro(jetzt, False),
                    "stop": zeile["stop"],
                    "schutz": zeile["schutz"],
                    "marktwert": _euro(jetzt * menge, False),
                    "differenz": _euro(abstand, True),
                    "prozent": _prozent(prozent),
                    "klasse": _richtung(abstand),
                }
            )
        bilder.append(
            {
                "name": name,
                "herkunft": "Lokale Simulation",
                "regel": konto["regel"],
                "cash": _euro(cash, False),
                "equity": _euro(equity, False),
                "angelegt": _euro(equity - cash, False),
                "differenz": _euro(differenz, True),
                "plus": float(differenz.quantize(Decimal("0.01"))),
                "prozent": _prozent(differenz / START_EUR * Decimal(100)),
                "klasse": _richtung(differenz),
                "satz": (_aktivitaet(pfad, name)[:1] or [{}])[0].get("grund", ""),
                "positionen": positionen,
                "nicht": _aktivitaet(pfad, name, "SKIP")[:4],
                "lernen": auswertung(_trades(pfad, name)),
            }
        )
    return bilder


def _konten_sortiert(pfad: Path) -> list[dict]:
    return sorted(
        _konten_ansicht(pfad),
        key=lambda konto: (-float(konto.get("plus") or 0), -len(konto.get("positionen") or []), str(konto.get("name") or "")),
    )


def _alpaca_karte(pfad: Path) -> dict:
    verbunden = schluessel() is not None
    zeile = _alpaca_kontozeile(pfad)
    kurs = _zahl(zeile.get("kurs"))
    equity_usd = _zahl(zeile.get("equity")) or Decimal(0)
    cash_usd = _zahl(zeile.get("cash")) or Decimal(0)
    if kurs is None or kurs <= 0:
        equity = cash = Decimal(0)
        differenz = Decimal(0)
        kurs_text = "kein EUR/USD"
    else:
        equity = (equity_usd * kurs).quantize(Decimal("0.01"))
        cash = (cash_usd * kurs).quantize(Decimal("0.01"))
        differenz = equity - START_EUR
        kurs_text = f"EUR/USD {kurs} vom {zeile.get('zeit', '—')}, Quelle {zeile.get('quelle', '—')}"
    snapshot = _letzter_snapshot(pfad)
    positionen = []
    for eintrag in _positionen(pfad, ALPACA):
        einstieg = _zahl(eintrag["einstieg"]) or Decimal(0)
        jetzt = _zahl(eintrag["jetzt"]) or einstieg
        menge = _zahl(eintrag["menge"]) or Decimal(0)
        faktor = kurs if kurs is not None and kurs > 0 else Decimal(1)
        abstand = (jetzt - einstieg) * menge * faktor
        positionen.append(
            {
                "symbol": eintrag["symbol"],
                "menge": eintrag["menge"],
                "einstieg": _euro(einstieg * faktor, False),
                "jetzt": _euro(jetzt * faktor, False),
                "stop": eintrag["stop"],
                "schutz": eintrag["schutz"],
                "marktwert": _euro(jetzt * menge * faktor, False),
                "differenz": _euro(abstand, True),
                "klasse": _richtung(abstand),
            }
        )
    from ki import lies_modell

    modell = lies_modell(pfad) if pfad.exists() else None
    beispiele = 0 if modell is None else modell.beispiele
    satz = kurs_text
    if snapshot:
        satz += f". Drawdown {snapshot['drawdown']}. Tagesanfang {snapshot['tagesstart']} USD."
    letzte = _aktivitaet(pfad, ALPACA)[:1]
    if letzte:
        satz += f" Letzte Entscheidung {letzte[0]['entscheidung']}: {letzte[0]['grund']}"
    satz += f" Modell mit {beispiele} abgeschlossenen Tagen. Strategie {STRATEGIE}."
    if not verbunden:
        satz = "Keine Schlüssel. Es wird nichts an Alpaca gesendet. " + satz
    return {
        "verbunden": verbunden,
        "name": "Alpaca Paper" if verbunden else "Alpaca nicht verbunden",
        "herkunft": "Alpaca Paper" if verbunden else "Alpaca nicht verbunden",
        "regel": "Alpaca Paper. Kein echtes Geld." if verbunden else "Keine Alpaca-Orders.",
        "cash": _euro(cash, False),
        "equity": _euro(equity, False),
        "angelegt": _euro(max(Decimal(0), equity - cash), False),
        "differenz": _euro(differenz, True),
        "klasse": _richtung(differenz),
        "satz": satz,
        "positionen": positionen,
        "nicht": _aktivitaet(pfad, ALPACA, "SKIP")[:4],
        "lernen": auswertung(_trades(pfad, ALPACA)),
        "orders": _orders(pfad),
    }


def _alpaca_kontozeile(pfad: Path) -> dict:
    if not pfad.exists():
        return {}
    _tabellen(pfad)
    with sqlite3.connect(pfad) as verbindung:
        zeile = verbindung.execute(
            """
            SELECT equity, cash, sleeve, kurs, quelle, zeit FROM paper_konto
            WHERE broker = 'Alpaca Paper' ORDER BY id DESC LIMIT 1
            """
        ).fetchone()
    if zeile is None:
        return {}
    return {"equity": zeile[0], "cash": zeile[1], "sleeve": zeile[2], "kurs": zeile[3], "quelle": zeile[4], "zeit": zeile[5]}


def _letzter_snapshot(pfad: Path) -> dict | None:
    if not pfad.exists():
        return None
    _tabellen(pfad)
    with sqlite3.connect(pfad) as verbindung:
        zeile = verbindung.execute(
            "SELECT equity, cash, markt, spitze, drawdown, tagesstart FROM paper_snapshots ORDER BY id DESC LIMIT 1"
        ).fetchone()
    if zeile is None or zeile[0] in (None, ""):
        return None
    return {
        "equity": zeile[0],
        "cash": zeile[1],
        "markt": zeile[2],
        "spitze": zeile[3],
        "drawdown": zeile[4] or "0",
        "tagesstart": zeile[5] or zeile[0],
    }


def _sicherheit(pfad: Path, lage: dict) -> dict:
    verbunden = schluessel() is not None
    return {
        "paper": "verbunden" if verbunden else "nicht verbunden",
        "endpunkt": PAPER,
        "automatisch": lage["automatisch"] and verbunden,
        "notfall": lage["notfall"],
        "sync": "Alpaca ist die Quelle der offenen Positionen." if verbunden else "Alpaca ist nicht verbunden.",
        "hinweis": "Automatischer Handel bleibt aus, bis er ausdrücklich eingeschaltet wird.",
    }


def _richtung(wert: Decimal) -> str:
    if wert > Decimal("0.005"):
        return "plus"
    if wert < Decimal("-0.005"):
        return "minus"
    return "null"


def _euro(wert: Decimal, vorzeichen: bool) -> str:
    wert = wert.quantize(Decimal("0.01"))
    if wert == 0:
        vorzeichen = False
    betrag = abs(wert)
    ganz, cent = f"{betrag:.2f}".split(".")
    teile: list[str] = []
    roh = ganz
    while roh:
        teile.append(roh[-3:])
        roh = roh[:-3]
    text = ".".join(reversed(teile)) + "," + cent + " €"
    if wert < 0:
        return "−" + text
    if vorzeichen and wert > 0:
        return "+" + text
    return text


def _prozent(wert: Decimal) -> str:
    zahl = wert.quantize(Decimal("0.1"))
    if zahl == 0:
        return "0,0 %"
    text = f"{abs(zahl):.1f}".replace(".", ",") + " %"
    if zahl < 0:
        return "−" + text
    if zahl > 0:
        return "+" + text
    return "0,0 %"


def _orders(pfad: Path) -> list[dict]:
    if not pfad.exists():
        return []
    _tabellen(pfad)
    with sqlite3.connect(pfad) as verbindung:
        zeilen = verbindung.execute(
            "SELECT symbol, seite, menge, status, preis, zeit FROM paper_orders ORDER BY id DESC LIMIT 8"
        ).fetchall()
    return [
        {"symbol": zeile[0], "seite": zeile[1], "menge": zeile[2], "status": zeile[3], "preis": zeile[4], "zeit": zeile[5]}
        for zeile in zeilen
    ]


def _trades(pfad: Path, konto: str | None = None) -> tuple[dict, ...]:
    if not pfad.exists():
        return ()
    _tabellen(pfad)
    frage = "SELECT ergebnis, strategie, symbol FROM paper_trades"
    werte: tuple = ()
    if konto is not None:
        frage += " WHERE konto = ?"
        werte = (konto,)
    with sqlite3.connect(pfad) as verbindung:
        zeilen = verbindung.execute(frage, werte).fetchall()
    return tuple({"ergebnis": zeile[0], "strategie": zeile[1], "symbol": zeile[2]} for zeile in zeilen)


def _letzte_kontozeile(pfad: Path) -> dict:
    leer = {"start": "10.000 EUR", "equity": "—", "cash": "—", "sleeve": "—", "kurs": "—"}
    if not pfad.exists():
        return leer
    _tabellen(pfad)
    with sqlite3.connect(pfad) as verbindung:
        zeile = verbindung.execute(
            "SELECT equity, cash, sleeve, kurs, zeit FROM paper_konto ORDER BY id DESC LIMIT 1"
        ).fetchone()
    if zeile is None:
        return leer
    return {"start": "10.000 EUR", "equity": zeile[0], "cash": zeile[1], "sleeve": zeile[2], "kurs": zeile[3], "zeit": zeile[4]}


def _trade_aus_fill(pfad: Path, order: dict, stop: Decimal | None = None) -> None:
    symbol = str(order.get("symbol") or "")
    seite = str(order.get("side") or "")
    menge = _zahl(order.get("filled_qty"))
    preis = _zahl(order.get("filled_avg_price"))
    if not symbol or menge is None or menge <= 0 or preis is None or preis <= 0:
        return
    if seite == "buy":
        if stop is None:
            stop = _stop_aus_kauf(pfad, symbol)
        _buch_setzen(pfad, ALPACA, symbol, str(menge), str(preis), str(preis), "" if stop is None else str(stop))
        _fall_einstieg(pfad, ALPACA, symbol, str(preis))
        return
    position = _gleiche_position(_positionen(pfad, ALPACA), symbol, symbol)
    if position is None:
        return
    bestand = _zahl(position["menge"]) or Decimal(0)
    if menge + Decimal("0.0000001") >= bestand:
        _buch_verkaufen(pfad, ALPACA, position["symbol"], position["menge"], str(preis))
        return
    with sqlite3.connect(pfad) as verbindung:
        verbindung.execute(
            "UPDATE paper_buch SET menge = ?, jetzt = ? WHERE konto = ? AND symbol = ?",
            (str(bestand - menge), str(preis), ALPACA, position["symbol"]),
        )


def _schnitt(werte: list[Decimal]) -> str:
    if not werte:
        return "—"
    return str((sum(werte, Decimal(0)) / Decimal(len(werte))).quantize(Decimal("0.01")))
