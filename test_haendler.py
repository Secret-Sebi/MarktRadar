"""Jeder KI-Trader hat ein eigenes Buch und eigene Gewichte."""

import os
import sqlite3
import tempfile
import unittest
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

from analyse import BERLIN
from haendler import (
    _PROFIL,
    HAENDLER,
    anpassen,
    bewerten,
    entscheide,
    pruefe,
    uebersicht,
    zurueck,
)
from papier import nach_runde, schalten


class _Technik:
    def __init__(self, atr=2):
        self.atr = atr
        self.macd = None
        self.macd_signal = None


class _Zahlen:
    ist_etf = False


def _zeile(reihe, symbol="AAPL"):
    zeile = type("Zeile", (), {})()
    zeile.symbol = symbol
    zeile.preis = reihe[-1] if reihe else 100
    zeile.waehrung = "EUR"
    zeile.datenstatus = "ok"
    zeile.technik = _Technik()
    zeile.kennzahlen = _Zahlen()
    zeile.reihe = reihe
    zeile.muster = {}
    zeile.fundamental = "fehlt"
    zeile.news_art = ""
    zeile.news_ton = ""
    return zeile


def _umgebung_leer():
    return {"APCA_API_KEY_ID": "", "APCA_API_SECRET_KEY": "", "APCA_API_BASE_URL": "https://paper-api.alpaca.markets"}


class HaendlerTests(unittest.TestCase):
    def test_dreissig_trader_fuenfzehn_im_wettbewerb(self):
        self.assertEqual(len(HAENDLER), 30)
        self.assertEqual(sum(1 for haendler in HAENDLER if haendler.einsatz), 15)
        self.assertEqual(len({haendler.name for haendler in HAENDLER}), 30)

    def test_fehlende_daten_kaufen_nicht(self):
        self.assertEqual(entscheide("Momentum", _zeile(()))[0], "SKIP")
        self.assertIn("Volumen", entscheide("Volumen", _zeile((100,)))[1])
        self.assertIn("Kerzen", entscheide("Kerze", _zeile(tuple(range(1, 40))))[1])
        meldung = _zeile(tuple(range(1, 40)))
        meldung.news_art = "unternehmen"
        entscheidung, grund, _merkmale = entscheide("Nachrichten", meldung)
        self.assertEqual(entscheidung, "SKIP")
        self.assertIn("kein Kaufgrund", grund)
        self.assertIn("Marktkapitalisierung", entscheide("Small", _zeile(tuple(range(1, 40))))[1])

    def test_getrennte_buecher_und_kein_fremder_verkauf(self):
        reihe = tuple(100 + i for i in range(40))
        moment = datetime(2026, 11, 18, 15, 0, tzinfo=BERLIN)
        with tempfile.TemporaryDirectory() as ordner:
            pfad = Path(ordner) / "markt.sqlite"
            with patch.dict(os.environ, _umgebung_leer()):
                schalten(pfad, True, "PAPIER")
                nach_runde(pfad, (_zeile(reihe),), lambda _anfrage, timeout=12: None, lambda _code: Decimal("0.9"), moment, liste=("AAPL",))
                nach_runde(pfad, (_zeile(reihe),), lambda _anfrage, timeout=12: None, lambda _code: Decimal("0.9"), moment, liste=("AAPL",))
            from papier import _positionen

            self.assertEqual(_positionen(pfad, "Momentum")[0]["symbol"], "AAPL")
            self.assertEqual(_positionen(pfad, "RSI"), [])
            self.assertEqual(len(_positionen(pfad, "Momentum")), 1)
            from papier import _buch_kaufen

            _buch_kaufen(pfad, "Momentum", "SAP.DE", "1", "100", "90")
            nachricht = _zeile(tuple(100 + i * 5 for i in range(40)), "SAP.DE")
            with patch.dict(os.environ, _umgebung_leer()):
                nach_runde(pfad, (nachricht,), lambda _anfrage, timeout=12: None, lambda _code: Decimal("0.9"), moment, liste=("SAP.DE",))
            self.assertIn("SAP.DE", [zeile["symbol"] for zeile in _positionen(pfad, "Momentum")])
            self.assertNotIn("SAP.DE", [zeile["symbol"] for zeile in _positionen(pfad, "RSI")])

    def test_gewichte_bleiben_getrennt_und_rollback(self):
        from haendler import _lerne, _tabellen
        from ki import lies_modell

        with tempfile.TemporaryDirectory() as ordner:
            pfad = Path(ordner) / "markt.sqlite"
            _tabellen(pfad)
            _lerne(pfad, "Momentum", (1.0, 0.0), 1.0, 0)
            _lerne(pfad, "RSI", (1.0, 0.0), 0.0, 0)
            with sqlite3.connect(pfad) as verbindung:
                momentum = verbindung.execute("SELECT gewichte FROM ki_haendler_modell WHERE haendler = 'Momentum'").fetchone()[0]
                rsi = verbindung.execute("SELECT gewichte FROM ki_haendler_modell WHERE haendler = 'RSI'").fetchone()[0]
            self.assertNotEqual(momentum, rsi)
            self.assertEqual(lies_modell(pfad).beispiele, 0)
            self.assertTrue(zurueck(pfad, "Momentum", 1))
            with sqlite3.connect(pfad) as verbindung:
                wieder = verbindung.execute("SELECT gewichte, beispiele FROM ki_haendler_modell WHERE haendler = 'Momentum'").fetchone()
            self.assertIn("[0.0, 0.0]", wieder[0])
            self.assertEqual(wieder[1], 0)

    def test_gebuehr_drawdown_und_keine_fruehe_krone(self):
        from haendler import _drawdown, _fall_offen, _fall_zu, _tabellen, von

        with tempfile.TemporaryDirectory() as ordner:
            pfad = Path(ordner) / "markt.sqlite"
            _tabellen(pfad)
            haendler = von("Momentum")
            _fall_offen(pfad, haendler, "AAPL", (0.1, 0.1), Decimal(100))
            _fall_zu(pfad, "Momentum", "AAPL", {"einstieg": "100", "menge": "1"}, Decimal(110))
            with sqlite3.connect(pfad) as verbindung:
                ergebnis = verbindung.execute("SELECT ergebnis FROM ki_haendler_fall").fetchone()[0]
            self.assertEqual(Decimal(ergebnis), Decimal("9.74"))
            with sqlite3.connect(pfad) as verbindung:
                kosten = verbindung.execute("SELECT brutto, gebuehr_einstieg, gebuehr_ausstieg, spread FROM ki_haendler_fall").fetchone()
            self.assertEqual(Decimal(kosten[0]), Decimal("10.00"))
            self.assertEqual(Decimal(kosten[1]), Decimal("0.12"))
            self.assertEqual(Decimal(kosten[2]), Decimal("0.14"))
            self.assertEqual(kosten[3], "nicht gemessen")
            from papier import _tabellen as papier_tabellen

            papier_tabellen(pfad)
            with sqlite3.connect(pfad) as verbindung:
                verbindung.execute(
                    "INSERT INTO paper_konto (broker, waehrung, equity, cash, sleeve, kurs, quelle, zeit, konto) VALUES ('Lokal', 'EUR', '100', '100', '100', '', '', '2026-11-22T10:00:00+00:00', 'Momentum')"
                )
                verbindung.execute(
                    "INSERT INTO paper_konto (broker, waehrung, equity, cash, sleeve, kurs, quelle, zeit, konto) VALUES ('Lokal', 'EUR', '90', '90', '100', '', '', '2026-11-22T11:00:00+00:00', 'Momentum')"
                )
            self.assertAlmostEqual(_drawdown(pfad, "Momentum"), 0.1)
            self.assertEqual(uebersicht(pfad)["beste"], "noch keine ausreichende Stichprobe")
            self.assertIn("20", uebersicht(pfad)["meta"])

    def test_adaptiv_aendert_die_schwelle_nicht_vor_dreissig_faellen(self):
        with tempfile.TemporaryDirectory() as ordner:
            pfad = Path(ordner) / "markt.sqlite"
            self.assertIn("bleibt", anpassen(pfad))

    def test_gewichte_aendern_nur_die_eigene_entscheidung(self):
        import json

        from haendler import _lerne, _tabellen

        reihe = tuple(100 + i for i in range(40))
        zeile = _zeile(reihe)
        with tempfile.TemporaryDirectory() as ordner:
            pfad = Path(ordner) / "markt.sqlite"
            _tabellen(pfad)
            entscheidung, grund, _merkmale, stand = bewerten(pfad, "Momentum", zeile)
            self.assertEqual(entscheidung, "BUY")
            self.assertFalse(stand["zuverlaessig"])
            self.assertIn("Nicht zuverlässig", grund)
            with sqlite3.connect(pfad) as verbindung:
                verbindung.execute(
                    "INSERT INTO ki_haendler_modell (haendler, gewichte, bias, beispiele, version, zeit) VALUES ('Momentum', ?, -5, 12, 2, 't')",
                    (json.dumps([-5.0, -5.0]),),
                )
            self.assertEqual(bewerten(pfad, "Momentum", zeile)[0], "HOLD")
            with sqlite3.connect(pfad) as verbindung:
                verbindung.execute(
                    "UPDATE ki_haendler_modell SET gewichte = ?, bias = 5 WHERE haendler = 'Momentum'",
                    (json.dumps([5.0, 5.0]),),
                )
            self.assertEqual(bewerten(pfad, "Momentum", zeile)[0], "BUY")
            _lerne(pfad, "RSI", (1.0,), 0.0, 0)
            with sqlite3.connect(pfad) as verbindung:
                momentum = verbindung.execute("SELECT beispiele FROM ki_haendler_modell WHERE haendler = 'Momentum'").fetchone()[0]
                rsi = verbindung.execute("SELECT beispiele FROM ki_haendler_modell WHERE haendler = 'RSI'").fetchone()[0]
            self.assertEqual(momentum, 12)
            self.assertEqual(rsi, 1)

    def test_fehlgeschlagener_verkauf_wird_kein_lernfall(self):
        from haendler import _fall_offen, _schliessen, _tabellen, von

        with tempfile.TemporaryDirectory() as ordner:
            pfad = Path(ordner) / "markt.sqlite"
            _tabellen(pfad)
            _fall_offen(pfad, von("Momentum"), "AAPL", (0.1, 0.2), Decimal(100))
            with patch("papier._lokal_verkaufen", return_value=False), patch("papier._positionen", return_value=[{"symbol": "AAPL", "menge": "1", "einstieg": "100"}]):
                ok, geld = _schliessen(pfad, "Momentum", "AAPL", Decimal(110), datetime(2026, 11, 18, 15, tzinfo=BERLIN), "Verkauf")
            self.assertFalse(ok)
            self.assertEqual(geld, Decimal(0))
            with sqlite3.connect(pfad) as verbindung:
                ausstieg = verbindung.execute("SELECT ausstieg, gelernt FROM ki_haendler_fall").fetchone()
            self.assertIsNone(ausstieg[0])
            self.assertEqual(ausstieg[1], 0)

    def test_pruefung_nutzt_nur_spaetere_faelle_und_das_aktive_modell_bleibt(self):
        from haendler import _tabellen

        with tempfile.TemporaryDirectory() as ordner:
            pfad = Path(ordner) / "markt.sqlite"
            _tabellen(pfad)
            with sqlite3.connect(pfad) as verbindung:
                for nummer in range(24):
                    verbindung.execute(
                        """
                        INSERT INTO ki_haendler_fall
                        (haendler, symbol, horizont, merkmale, einstieg, ausstieg, ergebnis, kosten, benchmark, quelle, gelernt, zeit)
                        VALUES ('Momentum', 'AAPL', 'mittel', '[0.1, 0.1]', '100', '101', ?, 'Annahme', 'nicht gemessen', 'simulation', 0, ?)
                        """,
                        ("1.00" if nummer % 2 == 0 else "-1.00", f"2026-01-{(nummer % 28) + 1:02d}T00:00:00+00:00"),
                    )
            bericht = pruefe(pfad, "Momentum")
            self.assertGreater(bericht["test_ab"], bericht["train_bis"])
            self.assertFalse(bericht["besser"])
            with sqlite3.connect(pfad) as verbindung:
                modell = verbindung.execute("SELECT COUNT(*) FROM ki_haendler_modell").fetchone()[0]
            self.assertEqual(modell, 0)

    def test_zentrale_zeigt_echte_null_und_keine_phase(self):
        with tempfile.TemporaryDirectory() as ordner:
            pfad = Path(ordner) / "markt.sqlite"
            bild = uebersicht(pfad)
            self.assertEqual(len(_PROFIL), 30)
            self.assertEqual(bild["aktiv"], 15)
            self.assertEqual(bild["belastbar"], 0)
            self.assertTrue(all(zeile["quelle"] == "simulation" and zeile["ergebnis"] == "0.00" for zeile in bild["rangliste"]))
            self.assertEqual(bild["meta_bericht"]["phasen"]["phase"], "nicht gemessen")
            self.assertIn("Nicht ausreichend", bild["rangliste"][0]["sharpe"])

    def test_live_endpunkt_bleibt_gesperrt(self):
        from papier import PapierFehler, basis_pruefen

        with patch.dict(os.environ, {"APCA_API_BASE_URL": "https://api.alpaca.markets"}), self.assertRaises(PapierFehler):
            basis_pruefen()
