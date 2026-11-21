"""Paper-Handel bleibt aus, bis er ausdrücklich an ist. Live-Orders sind gesperrt."""

import json
import os
import sqlite3
import tempfile
import unittest
from datetime import datetime
from decimal import Decimal
from email.message import Message
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError

from analyse import BERLIN
from papier import (
    auswertung,
    basis_pruefen,
    entscheiden,
    kauf_gesperrt,
    menge_fuer,
    nach_runde,
    schalten,
    strategie_uebernehmen,
    zustand_lesen,
)


class _Technik:
    def __init__(self, atr=2, macd=None):
        self.atr = atr
        self.macd = macd


class _Zahlen:
    ist_etf = False


def _symbole(pfad, konto):
    from papier import _positionen

    return [zeile["symbol"] for zeile in _positionen(pfad, konto)]


def _zeile(qualitaet="vorsichtig", rang=0.2, atr=2, status="ok"):
    zeile = type("Zeile", (), {})()
    zeile.symbol = "AAPL"
    zeile.preis = 100
    zeile.datenstatus = status
    zeile.technik = _Technik(atr)
    zeile.kennzahlen = _Zahlen()
    zeile.muster = {"qualitaet": qualitaet, "rang": rang}
    zeile.fundamental = "fehlt"
    return zeile


class _Antwort:
    def __init__(self, roh: bytes):
        self._roh = roh

    def read(self):
        return self._roh

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False


def _server(posts: list):
    def oeffnen(anfrage, timeout=12):
        del timeout
        adresse = anfrage.full_url
        if "api.alpaca.markets" in adresse and "paper-api" not in adresse:
            raise AssertionError(adresse)
        if adresse.endswith("/v2/account"):
            return _Antwort(b'{"currency":"USD","equity":"20000","cash":"15000"}')
        if adresse.endswith("/v2/clock"):
            return _Antwort(b'{"is_open": true}')
        if adresse.endswith("/v2/positions"):
            return _Antwort(b"[]")
        if "/v2/orders?status" in adresse:
            return _Antwort(b"[]")
        if "/v2/assets/" in adresse:
            return _Antwort(b'{"tradable": true, "status": "active"}')
        if "by_client_order_id" in adresse:
            raise HTTPError(adresse, 404, "fehlt", Message(), None)
        if anfrage.method == "POST":
            posts.append(json.loads(anfrage.data.decode("utf-8")))
            return _Antwort(b'{"id":"1","status":"accepted","filled_qty":"0"}')
        raise AssertionError(adresse)

    return oeffnen


class PapierTests(unittest.TestCase):
    def test_live_endpunkt_wird_abgewiesen(self):
        with patch.dict(os.environ, {"APCA_API_BASE_URL": "https://api.alpaca.markets"}), self.assertRaises(RuntimeError):
            basis_pruefen()

    def test_ohne_einschalten_geht_keine_order_raus(self):
        posts = []
        with tempfile.TemporaryDirectory() as ordner:
            pfad = Path(ordner) / "markt.sqlite"
            with patch.dict(os.environ, {"APCA_API_KEY_ID": "paper", "APCA_API_SECRET_KEY": "geheim", "APCA_API_BASE_URL": "https://paper-api.alpaca.markets"}):
                nach_runde(pfad, (_zeile(),), _server(posts), lambda _code: Decimal("0.9"), datetime(2026, 11, 18, 15, 0, tzinfo=BERLIN))
        self.assertEqual(posts, [])

    def test_kauf_nur_bei_ausreichender_basis_und_nicht_doppelt(self):
        posts = []
        moment = datetime(2026, 11, 18, 15, 0, tzinfo=BERLIN)
        with tempfile.TemporaryDirectory() as ordner:
            pfad = Path(ordner) / "markt.sqlite"
            umgebung = {"APCA_API_KEY_ID": "paper", "APCA_API_SECRET_KEY": "geheim", "APCA_API_BASE_URL": "https://paper-api.alpaca.markets"}
            with patch.dict(os.environ, umgebung):
                schalten(pfad, True, "PAPIER")
                nach_runde(pfad, (_zeile(),), _server(posts), lambda _code: Decimal("0.9"), moment)
                nach_runde(pfad, (_zeile(),), _server(posts), lambda _code: Decimal("0.9"), moment)
                nach_runde(pfad, (_zeile("zu_klein", None),), _server(posts), lambda _code: Decimal("0.9"), moment)
        self.assertEqual(len(posts), 1)
        self.assertEqual(posts[0]["type"], "limit")
        self.assertEqual(posts[0]["side"], "buy")
        self.assertNotIn("market", posts[0]["type"])

    def test_stop_fehlt_und_kill_switch_blockieren(self):
        posts = []
        moment = datetime(2026, 11, 18, 15, 0, tzinfo=BERLIN)
        with tempfile.TemporaryDirectory() as ordner:
            pfad = Path(ordner) / "markt.sqlite"
            with patch.dict(os.environ, {"APCA_API_KEY_ID": "paper", "APCA_API_SECRET_KEY": "geheim", "APCA_API_BASE_URL": "https://paper-api.alpaca.markets"}):
                schalten(pfad, True, "PAPIER")
                nach_runde(pfad, (_zeile(atr=None),), _server(posts), lambda _code: Decimal("0.9"), moment)
                schalten(pfad, False, "", True)
                nach_runde(pfad, (_zeile(),), _server(posts), lambda _code: Decimal("0.9"), moment)
                self.assertTrue(zustand_lesen(pfad)["notfall"])
        self.assertEqual(posts, [])

    def test_mengen_und_grenzen_nutzen_dezimalwerte(self):
        stueck = menge_fuer(Decimal(10000), Decimal(100), Decimal(95), Decimal(9000), False)
        self.assertEqual(stueck, Decimal(10))
        self.assertIsNone(menge_fuer(Decimal(100), Decimal(100), Decimal(95), Decimal(50), False))
        self.assertIn("Drawdown", kauf_gesperrt(Decimal(90), Decimal(100), None, 0))
        self.assertIn("Tagesverlust", kauf_gesperrt(Decimal(97), Decimal(100), Decimal(100), 0))
        bild = auswertung(({"ergebnis": "10"}, {"ergebnis": "-5"}))
        self.assertEqual(bild["faktor"], "2.00")
        self.assertFalse(strategie_uebernehmen(80)[0])

    def test_alte_tabelle_bleibt_bei_der_migration(self):
        with tempfile.TemporaryDirectory() as ordner:
            pfad = Path(ordner) / "markt.sqlite"
            with sqlite3.connect(pfad) as verbindung:
                verbindung.execute("CREATE TABLE signale (id INTEGER PRIMARY KEY, symbol TEXT)")
                verbindung.execute("INSERT INTO signale (symbol) VALUES ('SAP.DE')")
            entscheiden(_zeile(), False, True)
            from papier import _tabellen

            _tabellen(pfad)
            with sqlite3.connect(pfad) as verbindung:
                self.assertEqual(verbindung.execute("SELECT symbol FROM signale").fetchone()[0], "SAP.DE")
                self.assertIn("paper_orders", {zeile[0] for zeile in verbindung.execute("SELECT name FROM sqlite_master WHERE type = 'table'")})

    def test_ohne_schluessel_probiert_es_lokal_und_nicht_doppelt(self):
        moment = datetime(2026, 11, 18, 15, 0, tzinfo=BERLIN)
        with tempfile.TemporaryDirectory() as ordner:
            pfad = Path(ordner) / "markt.sqlite"
            umgebung = {
                "APCA_API_KEY_ID": "",
                "APCA_API_SECRET_KEY": "",
                "APCA_API_BASE_URL": "https://paper-api.alpaca.markets",
            }
            with patch.dict(os.environ, umgebung):
                schalten(pfad, True, "PAPIER")
                nach_runde(pfad, (_zeile("zu_klein", None),), lambda _anfrage, timeout=12: None, lambda _code: Decimal("0.9"), moment, liste=("AAPL",))
                nach_runde(pfad, (_zeile("zu_klein", None),), lambda _anfrage, timeout=12: None, lambda _code: Decimal("0.9"), moment, liste=("AAPL",))
                from papier import _positionen, ansicht

                self.assertEqual(len(_positionen(pfad)), 1)
                self.assertEqual(ansicht(pfad)["aktivitaet"][0]["entscheidung"], "HOLD")
                schalten(pfad, False, "", True)
                anderer = _zeile("zu_klein", None)
                anderer.symbol = "SAP.DE"
                nach_runde(pfad, (anderer,), lambda _anfrage, timeout=12: None, lambda _code: Decimal("0.9"), moment, liste=("AAPL", "SAP.DE"))
                self.assertEqual([zeile["symbol"] for zeile in _positionen(pfad)], ["AAPL"])

    def test_drei_konten_kaufen_nicht_dasselbe(self):
        moment = datetime(2026, 11, 18, 15, 0, tzinfo=BERLIN)
        fenster = _zeile("zu_klein", None)
        fenster.symbol = "SAP.DE"
        fenster.muster = {"qualitaet": "zu_klein", "rang": None, "aktiv": True}
        vorsicht = _zeile()
        vorsicht.symbol = "MSFT"
        with tempfile.TemporaryDirectory() as ordner:
            pfad = Path(ordner) / "markt.sqlite"
            umgebung = {"APCA_API_KEY_ID": "", "APCA_API_SECRET_KEY": "", "APCA_API_BASE_URL": "https://paper-api.alpaca.markets"}
            with patch.dict(os.environ, umgebung):
                schalten(pfad, True, "PAPIER")
                nach_runde(
                    pfad,
                    (_zeile("zu_klein", None), fenster, vorsicht),
                    lambda _anfrage, timeout=12: None,
                    lambda _code: Decimal("0.9"),
                    moment,
                    liste=("AAPL", "SAP.DE", "MSFT"),
                )
                from papier import ansicht

                konten = {konto["name"]: konto for konto in ansicht(pfad)["konten"]}
                self.assertIn("AAPL", _symbole(pfad, "Versuch"))
                self.assertEqual(_symbole(pfad, "Fenster"), ["SAP.DE"])
                self.assertEqual(_symbole(pfad, "Vorsicht"), ["MSFT"])
                self.assertIn("nicht gekauft", konten["Fenster"]["nicht"][0]["grund"].lower() + konten["Vorsicht"]["regel"].lower())
                self.assertTrue(konten["Versuch"]["differenz"].endswith("€"))

    def test_ohne_daten_kein_kauf(self):
        entscheidung = entscheiden(_zeile(status="veraltet"), False, True)
        self.assertEqual(entscheidung["entscheidung"], "SKIP")
        self.assertIn("nicht", entscheidung["grund"])
