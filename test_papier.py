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
    beste_konten,
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
                self.assertEqual(posts, [])
                _modell_setzen(pfad)
                with patch("ki.messe", return_value=(8, 12)):
                    nach_runde(pfad, (_zeile(),), _server(posts), lambda _code: Decimal("0.9"), moment)
                    nach_runde(pfad, (_zeile(),), _server(posts), lambda _code: Decimal("0.9"), moment)
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


class _Welt:
    def __init__(self):
        self.posts = []
        self.positionen = []
        self.orders = []
        self.antwort = {"id": "1", "status": "accepted", "filled_qty": "0"}
        self.stop_antwort = {"id": "stop", "status": "accepted", "filled_qty": "0"}
        self.equity = "20000"
        self.cash = "15000"


def _oeffnen_welt(welt: _Welt):
    def oeffnen(anfrage, timeout=12):
        del timeout
        adresse = anfrage.full_url
        if "api.alpaca.markets" in adresse and "paper-api" not in adresse:
            raise AssertionError(adresse)
        if adresse.endswith("/v2/account"):
            return _Antwort(json.dumps({"currency": "USD", "equity": welt.equity, "cash": welt.cash}).encode())
        if adresse.endswith("/v2/clock"):
            return _Antwort(b'{"is_open": true}')
        if adresse.endswith("/v2/positions"):
            return _Antwort(json.dumps(welt.positionen).encode())
        if "/v2/orders?status" in adresse:
            return _Antwort(json.dumps(welt.orders).encode())
        if "/v2/assets/" in adresse:
            return _Antwort(b'{"tradable": true, "status": "active"}')
        if "by_client_order_id" in adresse:
            raise HTTPError(adresse, 404, "fehlt", Message(), None)
        if anfrage.method == "DELETE":
            welt.posts.append({"method": "DELETE", "pfad": adresse})
            return _Antwort(b"{}")
        if anfrage.method == "POST":
            body = json.loads(anfrage.data.decode("utf-8"))
            welt.posts.append(body)
            vorlage = welt.stop_antwort if body.get("type") in ("stop", "stop_limit") else welt.antwort
            antwort = dict(vorlage)
            antwort.setdefault("symbol", body.get("symbol"))
            antwort.setdefault("side", body.get("side"))
            antwort.setdefault("qty", body.get("qty"))
            antwort.setdefault("type", body.get("type"))
            antwort.setdefault("client_order_id", body.get("client_order_id"))
            if body.get("stop_price"):
                antwort.setdefault("stop_price", body.get("stop_price"))
            return _Antwort(json.dumps(antwort).encode())
        raise AssertionError(adresse)

    return oeffnen


def _modell_setzen(pfad: Path, symbol: str = "AAPL") -> None:
    from ki import leeres_modell, merkmale, schritt, setze_modell
    from kurse import Bar

    balken = tuple(Bar(i * 86400, None, None, None, 100 + i, 100 + i, None) for i in range(1, 40))
    eingabe = merkmale(balken, None, "unklar")
    if eingabe is None:
        raise AssertionError("Merkmale fehlen")
    modell = leeres_modell()
    for _ in range(12):
        modell = schritt(modell, eingabe, 1)
    setze_modell(pfad, modell)
    with sqlite3.connect(pfad) as verbindung:
        verbindung.execute("CREATE TABLE IF NOT EXISTS kurse (symbol TEXT, zeit INTEGER, schluss REAL)")
        verbindung.execute("DELETE FROM kurse WHERE symbol = ?", (symbol,))
        for i in range(1, 40):
            verbindung.execute("INSERT INTO kurse (symbol, zeit, schluss) VALUES (?, ?, ?)", (symbol, i * 86400, 100 + i))


def _umgebung():
    return {"APCA_API_KEY_ID": "paper", "APCA_API_SECRET_KEY": "geheim", "APCA_API_BASE_URL": "https://paper-api.alpaca.markets"}


def _entscheidungen(pfad: Path):
    with sqlite3.connect(pfad) as verbindung:
        return verbindung.execute("SELECT entscheidung, grund FROM paper_entscheidungen ORDER BY id").fetchall()


class KritischePapierTests(unittest.TestCase):
    def _lauf(self, pfad, welt, zeilen, kurs=lambda _code: Decimal("0.9"), moment=None):
        moment = moment or datetime(2026, 11, 18, 15, 0, tzinfo=BERLIN)
        with patch.dict(os.environ, _umgebung()), patch("ki.messe", return_value=(8, 12)):
            schalten(pfad, True, "PAPIER")
            return nach_runde(pfad, zeilen, _oeffnen_welt(welt), kurs, moment)

    def test_alpaca_position_wird_synchronisiert_und_geschlossen(self):
        welt = _Welt()
        welt.positionen = [{"symbol": "AAPL", "qty": "3", "avg_entry_price": "100", "current_price": "110"}]
        with tempfile.TemporaryDirectory() as ordner:
            pfad = Path(ordner) / "markt.sqlite"
            self._lauf(pfad, welt, ())
            self.assertEqual(_symbole(pfad, "Alpaca"), ["AAPL"])
            welt.positionen = []
            self._lauf(pfad, welt, ())
            self.assertEqual(_symbole(pfad, "Alpaca"), [])

    def test_offene_alpaca_position_wird_nicht_nochmal_gekauft(self):
        welt = _Welt()
        welt.positionen = [{"symbol": "BTCUSD", "qty": "1", "avg_entry_price": "100", "current_price": "101"}]
        zeile = _zeile()
        zeile.symbol = "BTC-USD"
        with tempfile.TemporaryDirectory() as ordner:
            pfad = Path(ordner) / "markt.sqlite"
            _modell_setzen(pfad, "BTC-USD")
            self._lauf(pfad, welt, (zeile,))
            self.assertEqual([post for post in welt.posts if post.get("side") == "buy"], [])
            self.assertEqual(len(_symbole(pfad, "Alpaca")), 1)

    def test_ki_entscheidet_den_alpaca_kauf_muster_allein_nicht(self):
        welt = _Welt()
        with tempfile.TemporaryDirectory() as ordner:
            pfad = Path(ordner) / "markt.sqlite"
            with patch.dict(os.environ, _umgebung()):
                schalten(pfad, True, "PAPIER")
                nach_runde(pfad, (_zeile(),), _oeffnen_welt(welt), lambda _code: Decimal("0.9"), datetime(2026, 11, 18, 15, 0, tzinfo=BERLIN))
            self.assertEqual(welt.posts, [])
            self.assertIn("SKIP", [zeile[0] for zeile in _entscheidungen(pfad)])
            _modell_setzen(pfad)
            with patch.dict(os.environ, _umgebung()), patch("ki.messe", return_value=(8, 12)):
                nach_runde(pfad, (_zeile(),), _oeffnen_welt(welt), lambda _code: Decimal("0.9"), datetime(2026, 11, 18, 15, 0, tzinfo=BERLIN))
            kauf = _entscheidungen(pfad)[-1]
            self.assertEqual(kauf[0], "BUY")
            self.assertIn("Modell", kauf[1])
            self.assertIn("Getrennte Prüfung", kauf[1])
            self.assertEqual(welt.posts[0]["side"], "buy")

    def test_zu_wenig_daten_oder_schwache_pruefung_kauft_nicht(self):
        welt = _Welt()
        with tempfile.TemporaryDirectory() as ordner:
            pfad = Path(ordner) / "markt.sqlite"
            with patch.dict(os.environ, _umgebung()):
                schalten(pfad, True, "PAPIER")
                nach_runde(pfad, (_zeile(),), _oeffnen_welt(welt), lambda _code: Decimal("0.9"), datetime(2026, 11, 18, 15, 0, tzinfo=BERLIN))
            self.assertIn("noch nicht", _entscheidungen(pfad)[-1][1])
            _modell_setzen(pfad)
            with patch.dict(os.environ, _umgebung()), patch("ki.messe", return_value=None):
                nach_runde(pfad, (_zeile(),), _oeffnen_welt(welt), lambda _code: Decimal("0.9"), datetime(2026, 11, 18, 15, 0, tzinfo=BERLIN))
            self.assertIn("Getrennte Prüfung fehlt", _entscheidungen(pfad)[-1][1])
            with patch.dict(os.environ, _umgebung()), patch("ki.messe", return_value=(2, 12)):
                nach_runde(pfad, (_zeile(),), _oeffnen_welt(welt), lambda _code: Decimal("0.9"), datetime(2026, 11, 18, 15, 0, tzinfo=BERLIN))
            self.assertIn("Kein Kauf", _entscheidungen(pfad)[-1][1])
        self.assertEqual(welt.posts, [])

    def test_drawdown_und_tagesverlust_lesen_den_kontowert(self):
        from papier import _grenzen_aus_db, _snapshot

        moment = datetime.now(BERLIN)
        with tempfile.TemporaryDirectory() as ordner:
            pfad = Path(ordner) / "markt.sqlite"
            _snapshot(pfad, Decimal(100), Decimal(40), Decimal(60), Decimal(20), moment)
            spitze, start = _grenzen_aus_db(pfad, Decimal(90))
            self.assertEqual(spitze, Decimal(100))
            self.assertEqual(start, Decimal(100))
            self.assertIn("Drawdown", kauf_gesperrt(Decimal(90), spitze, None, 0))
            _snapshot(pfad, Decimal(97), Decimal(40), Decimal(57), Decimal(20), moment)
            _spitze, tagesstart = _grenzen_aus_db(pfad, Decimal(97))
            self.assertEqual(tagesstart, Decimal(100))
            self.assertIn("Tagesverlust", kauf_gesperrt(Decimal(97), Decimal(100), tagesstart, 0))

    def test_teilfuellung_und_ablehnung(self):
        welt = _Welt()
        welt.antwort = {"id": "teil", "status": "partially_filled", "filled_qty": "4", "filled_avg_price": "101.5"}
        with tempfile.TemporaryDirectory() as ordner:
            pfad = Path(ordner) / "markt.sqlite"
            _modell_setzen(pfad)
            self._lauf(pfad, welt, (_zeile(),))
            from papier import _positionen

            bestand = _positionen(pfad, "Alpaca")
            self.assertEqual(Decimal(bestand[0]["menge"]), Decimal(4))
            self.assertEqual(Decimal(bestand[0]["einstieg"]), Decimal("101.5"))
            stops = [post for post in welt.posts if post.get("type") == "stop"]
            self.assertEqual(stops[0]["qty"], "4")
            welt.positionen = []
            welt.posts.clear()
            welt.antwort = {"id": "nein", "status": "rejected", "filled_qty": "0"}
            andere = _zeile()
            andere.symbol = "MSFT"
            _modell_setzen(pfad, "MSFT")
            self._lauf(pfad, welt, (andere,))
            self.assertNotIn("MSFT", _symbole(pfad, "Alpaca"))

    def test_neustart_stellt_position_und_stop_wieder_her(self):
        welt = _Welt()
        welt.antwort = {"id": "voll", "status": "filled", "filled_qty": "2", "filled_avg_price": "100"}
        with tempfile.TemporaryDirectory() as ordner:
            pfad = Path(ordner) / "markt.sqlite"
            _modell_setzen(pfad)
            self._lauf(pfad, welt, (_zeile(),))
            from papier import _positionen

            bestand = _positionen(pfad, "Alpaca")[0]
            stop = next(post for post in welt.posts if post.get("type") == "stop")
            with sqlite3.connect(pfad) as verbindung:
                verbindung.execute("DELETE FROM paper_orders WHERE typ IN ('stop', 'stop_limit')")
            welt.positionen = [{"symbol": "AAPL", "qty": bestand["menge"], "avg_entry_price": "100", "current_price": "100"}]
            welt.orders = [
                {
                    "id": "stop-1",
                    "client_order_id": stop["client_order_id"],
                    "symbol": "AAPL",
                    "side": "sell",
                    "type": "stop",
                    "qty": bestand["menge"],
                    "stop_price": stop["stop_price"],
                    "status": "new",
                }
            ]
            welt.antwort = {"id": "1", "status": "accepted", "filled_qty": "0"}
            vorher = len(welt.posts)
            self._lauf(pfad, welt, (_zeile(),))
            self.assertEqual(len(welt.posts), vorher)
            self.assertEqual(_positionen(pfad, "Alpaca")[0]["schutz"], "Broker-Stop")

    def test_wechselkurs_richtung_und_sperre(self):
        welt = _Welt()
        with tempfile.TemporaryDirectory() as ordner:
            pfad = Path(ordner) / "markt.sqlite"
            _modell_setzen(pfad)
            self._lauf(pfad, welt, ())
            with sqlite3.connect(pfad) as verbindung:
                sleeve = Decimal(verbindung.execute("SELECT sleeve FROM paper_konto WHERE broker = 'Alpaca Paper'").fetchone()[0])
            self.assertEqual(sleeve, Decimal("11111.11"))
            welt.posts.clear()
            self._lauf(pfad, welt, (_zeile(),), kurs=lambda _code: None)
            self.assertEqual(welt.posts, [])
            self.assertIn("EUR/USD fehlt", _entscheidungen(pfad)[-1][1])
            welt.posts.clear()
            self._lauf(pfad, welt, (_zeile(),), kurs=lambda _code: (Decimal("0.9"), datetime(2020, 1, 1, tzinfo=BERLIN)))
            self.assertEqual([post for post in welt.posts if post.get("side") == "buy"], [])
            self.assertIn("nicht frisch", _entscheidungen(pfad)[-1][1])

    def test_lokale_konten_bleiben_getrennt(self):
        moment = datetime(2026, 11, 18, 15, 0, tzinfo=BERLIN)
        with tempfile.TemporaryDirectory() as ordner:
            pfad = Path(ordner) / "markt.sqlite"
            umgebung = {"APCA_API_KEY_ID": "", "APCA_API_SECRET_KEY": "", "APCA_API_BASE_URL": "https://paper-api.alpaca.markets"}
            with patch.dict(os.environ, umgebung):
                schalten(pfad, True, "PAPIER")
                nach_runde(pfad, (_zeile("zu_klein", None),), lambda _anfrage, timeout=12: None, lambda _code: Decimal("0.9"), moment, liste=("AAPL",))
                from papier import ansicht

                bild = ansicht(pfad)
            self.assertTrue(all(konto["herkunft"] == "Lokale Simulation" for konto in bild["konten"]))
            self.assertEqual(bild["alpaca"]["name"], "Alpaca nicht verbunden")
            self.assertIn("nichts an Alpaca", bild["alpaca"]["satz"])
            self.assertEqual(_symbole(pfad, "Alpaca"), [])
            with sqlite3.connect(pfad) as verbindung:
                status = verbindung.execute("SELECT status FROM paper_orders").fetchall()
            self.assertTrue(status)
            self.assertTrue(all(zeile[0] == "lokale Simulation" for zeile in status))

    def test_kill_switch_blockiert_neuen_kauf(self):
        welt = _Welt()
        with tempfile.TemporaryDirectory() as ordner:
            pfad = Path(ordner) / "markt.sqlite"
            _modell_setzen(pfad)
            with patch.dict(os.environ, _umgebung()), patch("ki.messe", return_value=(8, 12)):
                schalten(pfad, False, "", True)
                nach_runde(pfad, (_zeile(),), _oeffnen_welt(welt), lambda _code: Decimal("0.9"), datetime(2026, 11, 18, 15, 0, tzinfo=BERLIN), liste=("AAPL",))
        self.assertEqual([post for post in welt.posts if post.get("side") == "buy"], [])

    def test_live_anfrage_wird_nicht_gesendet(self):
        from papier import PapierFehler, _anfrage

        def oeffnen(*_args, **_kwargs):
            raise AssertionError("Live-Anfrage wurde gesendet")

        with patch.dict(os.environ, {"APCA_API_BASE_URL": "https://api.alpaca.markets", "APCA_API_KEY_ID": "live", "APCA_API_SECRET_KEY": "geheim"}), self.assertRaises(PapierFehler):
            _anfrage(oeffnen, "POST", "/v2/orders", {"symbol": "AAPL"})

    def test_doppelte_order_wird_verhindert(self):
        welt = _Welt()
        with tempfile.TemporaryDirectory() as ordner:
            pfad = Path(ordner) / "markt.sqlite"
            _modell_setzen(pfad)
            self._lauf(pfad, welt, (_zeile(),))
            self._lauf(pfad, welt, (_zeile(),))
        self.assertEqual(len([post for post in welt.posts if post.get("side") == "buy"]), 1)

    def test_fremdes_fenster_schaltet_nicht(self):
        from fenster import anfrage_erlaubt

        self.assertTrue(anfrage_erlaubt({"Origin": "http://127.0.0.1:9", "X-MarktRadar": "1"}))
        self.assertFalse(anfrage_erlaubt({"Origin": "https://fremd.test", "X-MarktRadar": "1"}))
        self.assertFalse(anfrage_erlaubt({"Sec-Fetch-Site": "cross-site", "X-MarktRadar": "1", "Origin": "http://127.0.0.1:9"}))
        self.assertFalse(anfrage_erlaubt({"Origin": "http://127.0.0.1:9"}))

    def test_viele_konten_und_die_drei_mit_dem_meisten_plus(self):
        bild = (
            {"name": "Leer", "plus": 0, "positionen": []},
            {"name": "Vorne", "plus": 25, "positionen": [{}]},
            {"name": "Mitte", "plus": 4, "positionen": []},
            {"name": "Hinten", "plus": -2, "positionen": [{}, {}]},
        )
        self.assertEqual([konto["name"] for konto in beste_konten(list(bild))], ["Vorne", "Mitte", "Leer"])
        moment = datetime(2026, 11, 18, 15, 0, tzinfo=BERLIN)
        with tempfile.TemporaryDirectory() as ordner:
            pfad = Path(ordner) / "markt.sqlite"
            umgebung = {"APCA_API_KEY_ID": "", "APCA_API_SECRET_KEY": "", "APCA_API_BASE_URL": "https://paper-api.alpaca.markets"}
            with patch.dict(os.environ, umgebung):
                schalten(pfad, True, "PAPIER")
                nach_runde(pfad, (_zeile("zu_klein", None),), lambda _anfrage, timeout=12: None, lambda _code: Decimal("0.9"), moment, liste=("AAPL",))
                from papier import ansicht

                bild_live = ansicht(pfad)
            self.assertGreaterEqual(len(bild_live["konten"]), 12)
            self.assertEqual(len(bild_live["beste"]), 3)
            self.assertIn("AAPL", _symbole(pfad, "Versuch"))
            self.assertNotIn("AAPL", _symbole(pfad, "Zweite"))
            self.assertNotIn("AAPL", _symbole(pfad, "ETF"))
            self.assertNotIn("AAPL", _symbole(pfad, "Krypto"))
            self.assertTrue(bild_live["beste"][0]["positionen"])

    def test_lernen_wartet_auf_den_geschlossenen_fall(self):
        from ki import lies_modell

        moment = datetime(2026, 11, 18, 15, 0, tzinfo=BERLIN)
        with tempfile.TemporaryDirectory() as ordner:
            pfad = Path(ordner) / "markt.sqlite"
            _modell_setzen(pfad)
            umgebung = {"APCA_API_KEY_ID": "", "APCA_API_SECRET_KEY": "", "APCA_API_BASE_URL": "https://paper-api.alpaca.markets"}
            with patch.dict(os.environ, umgebung):
                schalten(pfad, True, "PAPIER")
                nach_runde(pfad, (_zeile(),), lambda _anfrage, timeout=12: None, lambda _code: Decimal("0.9"), moment, liste=("AAPL",))
                self.assertEqual(lies_modell(pfad).beispiele, 12)
                nach_runde(pfad, (_zeile(),), lambda _anfrage, timeout=12: None, lambda _code: Decimal("0.9"), moment, liste=("AAPL",))
                self.assertEqual(lies_modell(pfad).beispiele, 12)
                verkauf = _zeile()
                verkauf.preis = 90
                nach_runde(pfad, (verkauf,), lambda _anfrage, timeout=12: None, lambda _code: Decimal("0.9"), moment, liste=("AAPL",))
                self.assertEqual(lies_modell(pfad).beispiele, 13)
                with sqlite3.connect(pfad) as verbindung:
                    zeile = verbindung.execute("SELECT ausstieg, gelernt FROM paper_faelle WHERE konto = 'KI'").fetchone()
                self.assertIsNotNone(zeile[0])
                self.assertEqual(zeile[1], 1)
