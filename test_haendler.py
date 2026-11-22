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
            self.assertEqual(bericht["status"], "Nicht ausreichend Daten")
            self.assertFalse(bericht["besser"])
            self.assertNotIn("test_ab", bericht)
            with sqlite3.connect(pfad) as verbindung:
                modell = verbindung.execute("SELECT COUNT(*) FROM ki_haendler_modell").fetchone()[0]
            self.assertEqual(modell, 0)
            with sqlite3.connect(pfad) as verbindung:
                for nummer in range(12):
                    verbindung.execute(
                        """
                        INSERT INTO ki_haendler_fall
                        (haendler, symbol, horizont, merkmale, einstieg, ausstieg, ergebnis, kosten, benchmark, quelle, gelernt, zeit)
                        VALUES ('Momentum', 'AAPL', 'mittel', '[0.2, 0.2]', '100', '101', '1.00', 'Annahme', 'nicht gemessen', 'simulation', 0, ?)
                        """,
                        (f"2026-03-{(nummer % 28) + 1:02d}T00:00:00+00:00",),
                    )
            spaeter = pruefe(pfad, "Momentum")
            self.assertLess(spaeter["train_bis"], spaeter["pruef_ab"])
            self.assertLess(spaeter["pruef_ab"], spaeter["test_ab"])
            self.assertFalse(spaeter["besser"])
            self.assertIn("Benchmark nicht gemessen", spaeter["grund"])

    def test_zentrale_zeigt_echte_null_und_keine_phase(self):
        with tempfile.TemporaryDirectory() as ordner:
            pfad = Path(ordner) / "markt.sqlite"
            bild = uebersicht(pfad)
            self.assertEqual(len(_PROFIL), 30)
            self.assertEqual(bild["aktiv"], 15)
            self.assertEqual(bild["belastbar"], 0)
            self.assertTrue(all(zeile["quelle"] == "simulation" and zeile["ergebnis"] == "Keine Daten" for zeile in bild["rangliste"]))
            self.assertEqual(bild["meta_bericht"]["phasen"]["phase"], "nicht gemessen")
            self.assertIn("Nicht ausreichend", bild["rangliste"][0]["sharpe"])
            self.assertEqual(bild["zentrale"]["erfolg"], "Keine Daten")
            self.assertEqual(bild["zentrale"]["kapital"], "Keine Daten")
            self.assertEqual(bild["zentrale"]["faktor"], "Keine Daten")

    def test_live_endpunkt_bleibt_gesperrt(self):
        from papier import PapierFehler, basis_pruefen

        with patch.dict(os.environ, {"APCA_API_BASE_URL": "https://api.alpaca.markets"}), self.assertRaises(PapierFehler):
            basis_pruefen()

    def test_gesamt_equity_ist_die_summe_und_nicht_der_erste_trader(self):
        from papier import _tabellen as papier_tabellen

        with tempfile.TemporaryDirectory() as ordner:
            pfad = Path(ordner) / "markt.sqlite"
            papier_tabellen(pfad)
            with sqlite3.connect(pfad) as verbindung:
                verbindung.execute(
                    "INSERT INTO paper_konto (broker, waehrung, equity, cash, sleeve, kurs, quelle, zeit, konto) VALUES ('Lokal', 'EUR', '10000', '10000', '10000', '', '', '2026-11-22T10:00:00+00:00', 'Momentum')"
                )
                verbindung.execute(
                    "INSERT INTO paper_konto (broker, waehrung, equity, cash, sleeve, kurs, quelle, zeit, konto) VALUES ('Lokal', 'EUR', '10000', '10000', '10000', '', '', '2026-11-22T10:00:00+00:00', 'RSI')"
                )
                verbindung.execute(
                    "INSERT INTO paper_konto (broker, waehrung, equity, cash, sleeve, kurs, quelle, zeit, konto) VALUES ('Lokal', 'EUR', '9000', '9000', '10000', '', '', '2026-11-22T11:00:00+00:00', 'Momentum')"
                )
                verbindung.execute(
                    "INSERT INTO paper_konto (broker, waehrung, equity, cash, sleeve, kurs, quelle, zeit, konto) VALUES ('Lokal', 'EUR', '11000', '11000', '10000', '', '', '2026-11-22T11:00:00+00:00', 'RSI')"
                )
            zentrale = uebersicht(pfad)["zentrale"]
            self.assertEqual(zentrale["gesamt"][0]["equity"], 20000.0)
            self.assertEqual(zentrale["gesamt"][0]["buecher"], 2)
            self.assertEqual(zentrale["gesamt"][-1]["equity"], 20000.0)
            self.assertEqual(zentrale["equity"], "20000.00")
            self.assertEqual(zentrale["kapital"], "20000.00")
            self.assertEqual(zentrale["rendite"], "0.0 %")
            self.assertEqual(zentrale["drawdown"], "0.0%")
            self.assertIn("innerhalb von 10 Tagen", zentrale["aktualitaet"]["kontostand_hinweis"])

    def test_drawdown_behaelt_die_fruehe_senke_und_die_grenze_ist_strenger(self):
        import math

        from haendler import _untere_grenze
        from papier import _tabellen as papier_tabellen

        with tempfile.TemporaryDirectory() as ordner:
            pfad = Path(ordner) / "markt.sqlite"
            papier_tabellen(pfad)
            with sqlite3.connect(pfad) as verbindung:
                verbindung.execute(
                    "INSERT INTO paper_konto (broker, waehrung, equity, cash, sleeve, kurs, quelle, zeit, konto) VALUES ('Lokal', 'EUR', '10000', '10000', '10000', '', '', '2026-11-20T00:00:00+00:00', 'Momentum')"
                )
                verbindung.execute(
                    "INSERT INTO paper_konto (broker, waehrung, equity, cash, sleeve, kurs, quelle, zeit, konto) VALUES ('Lokal', 'EUR', '4000', '4000', '10000', '', '', '2026-11-20T00:01:00+00:00', 'Momentum')"
                )
                for nummer in range(500):
                    verbindung.execute(
                        "INSERT INTO paper_konto (broker, waehrung, equity, cash, sleeve, kurs, quelle, zeit, konto) VALUES ('Lokal', 'EUR', '10000', '10000', '10000', '', '', ?, 'Momentum')",
                        (f"2026-11-20T01:{nummer // 60:02d}:{nummer % 60:02d}+00:00",),
                    )
            zentrale = uebersicht(pfad)["zentrale"]
            self.assertEqual(len(zentrale["gesamt"]), 500)
            self.assertEqual(zentrale["drawdown"], "60.0%")
        werte = [1.0] * 11 + [4.0]
        mittel = sum(werte) / len(werte)
        streuung = math.sqrt(sum((wert - mittel) ** 2 for wert in werte) / len(werte))
        alt = mittel - 1.96 * streuung / math.sqrt(len(werte))
        self.assertLess(_untere_grenze(werte), alt)
        self.assertAlmostEqual(_untere_grenze([2.0] * 12), 2.0)

    def test_fehlender_kurs_ist_keine_null_und_alter_stand_ist_veraltet(self):
        from papier import _tabellen as papier_tabellen

        with tempfile.TemporaryDirectory() as ordner:
            pfad = Path(ordner) / "markt.sqlite"
            papier_tabellen(pfad)
            with sqlite3.connect(pfad) as verbindung:
                verbindung.execute(
                    "INSERT INTO paper_konto (broker, waehrung, equity, cash, sleeve, kurs, quelle, zeit, konto) VALUES ('Lokal', 'EUR', '10000', '9900', '10000', '', '', '2020-01-01T00:00:00+00:00', 'Momentum')"
                )
                verbindung.execute(
                    "INSERT INTO paper_konto (broker, waehrung, equity, cash, sleeve, kurs, quelle, zeit, konto) VALUES ('Lokal', 'EUR', '7000', '6900', '10000', '', '', '2020-01-02T00:00:00+00:00', 'Momentum')"
                )
                verbindung.execute(
                    "INSERT INTO paper_buch (konto, symbol, menge, einstieg, zeit, strategie) VALUES ('Momentum', 'AAPL', '1', '100', '2020-01-01T00:00:00+00:00', 'Momentum')"
                )
            zentrale = uebersicht(pfad)["zentrale"]
            momentum = next(zeile for zeile in uebersicht(pfad)["rangliste"] if zeile["name"] == "Momentum")
            self.assertIsNone(momentum["unrealisiert_zahl"])
            self.assertEqual(zentrale["unrealisiert"], "Keine Daten")
            self.assertIn("veraltet", zentrale["aktualitaet"]["kontostand_hinweis"])
            self.assertEqual(zentrale["drawdown"], "Nicht ausreichend Daten")
            self.assertEqual(zentrale["aktualitaet"]["letzter_kurs"], "Keine Daten")

    def test_success_rate_zaehlt_nur_gueltige_abgeschlossene_nettoergebnisse(self):
        from haendler import _tabellen, kennzahlen_aus

        self.assertEqual(kennzahlen_aus([])["erfolg_text"], "Keine Daten")
        self.assertIsNone(kennzahlen_aus([])["realisiert"])
        self.assertEqual(kennzahlen_aus([Decimal("0.00")])["erfolg_text"], "0.0 % aus 1 Trades")
        self.assertEqual(kennzahlen_aus([Decimal("0.00")])["ergebnis_text"], "0.00")
        self.assertEqual(kennzahlen_aus([Decimal(2), Decimal(-1)])["erfolg"], 0.5)
        with tempfile.TemporaryDirectory() as ordner:
            pfad = Path(ordner) / "markt.sqlite"
            _tabellen(pfad)
            with sqlite3.connect(pfad) as verbindung:
                verbindung.execute(
                    """
                    INSERT INTO ki_haendler_fall
                    (haendler, symbol, horizont, merkmale, einstieg, ausstieg, ergebnis, kosten, benchmark, quelle, gelernt, zeit)
                    VALUES ('Momentum', 'AAPL', 'mittel', '[0.1]', '100', '110', NULL, 'Annahme', 'nicht gemessen', 'simulation', 0, '2026-01-01T00:00:00+00:00')
                    """
                )
                verbindung.execute(
                    """
                    INSERT INTO ki_haendler_fall
                    (haendler, symbol, horizont, merkmale, einstieg, ausstieg, ergebnis, kosten, benchmark, quelle, gelernt, zeit)
                    VALUES ('Momentum', 'MSFT', 'mittel', '[0.1]', '100', '90', '-1.00', 'Annahme', 'nicht gemessen', 'simulation', 0, '2026-01-02T00:00:00+00:00')
                    """
                )
                verbindung.execute(
                    """
                    INSERT INTO ki_haendler_fall
                    (haendler, symbol, horizont, merkmale, einstieg, ausstieg, ergebnis, kosten, benchmark, quelle, gelernt, zeit)
                    VALUES ('RSI', 'AAPL', 'kurz', '[0.1]', '100', '120', '2.00', 'Annahme', 'nicht gemessen', 'simulation', 0, '2026-01-03T00:00:00+00:00')
                    """
                )
            bild = uebersicht(pfad)
            momentum = next(zeile for zeile in bild["rangliste"] if zeile["name"] == "Momentum")
            self.assertEqual(momentum["trades"], 1)
            self.assertEqual(momentum["erfolg_text"] if "erfolg_text" in momentum else momentum["erfolg"], "0.0 % aus 1 Trades")
            self.assertEqual(bild["zentrale"]["erfolg"], "50.0 % aus 2 abgeschlossenen Trades")
            self.assertEqual(bild["zentrale"]["realisiert"], "1.00")
            self.assertGreaterEqual(len(bild["zentrale"]["realisiert_punkte"]), 2)

    def test_pruefung_waehlt_auf_der_validierung_und_gibt_nur_mit_benchmark_frei(self):
        from haendler import _tabellen
        from papier import strategie_uebernehmen

        with tempfile.TemporaryDirectory() as ordner:
            pfad = Path(ordner) / "markt.sqlite"
            _tabellen(pfad)
            with sqlite3.connect(pfad) as verbindung:
                nummer = 0
                for _paar in range(12):
                    for werte, netto in ((" [1, 0]", "10.00"), ("[0, 1]", "-1.00")):
                        nummer += 1
                        verbindung.execute(
                            """
                            INSERT INTO ki_haendler_fall
                            (haendler, symbol, horizont, merkmale, einstieg, ausstieg, ergebnis, kosten, benchmark, quelle, gelernt, zeit)
                            VALUES ('Momentum', 'AAPL', 'mittel', ?, '100', '101', ?, 'Annahme', 'nicht gemessen', 'simulation', 0, ?)
                            """,
                            (werte.strip(), netto, f"2026-01-{(nummer % 28) + 1:02d}T00:00:00+00:00"),
                        )
                for _paar in range(12):
                    for werte, netto in (("[1, 0]", "-5.00"), ("[0, 1]", "10.00")):
                        nummer += 1
                        verbindung.execute(
                            """
                            INSERT INTO ki_haendler_fall
                            (haendler, symbol, horizont, merkmale, einstieg, ausstieg, ergebnis, kosten, benchmark, quelle, gelernt, zeit)
                            VALUES ('Momentum', 'AAPL', 'mittel', ?, '100', '101', ?, 'Annahme', 'nicht gemessen', 'simulation', 0, ?)
                            """,
                            (werte, netto, f"2026-02-{(nummer % 28) + 1:02d}T00:00:00+00:00"),
                        )
                for _paar in range(12):
                    for werte, netto in (("[1, 0]", "100.00"), ("[0, 1]", "-1.00")):
                        nummer += 1
                        verbindung.execute(
                            """
                            INSERT INTO ki_haendler_fall
                            (haendler, symbol, horizont, merkmale, einstieg, ausstieg, ergebnis, kosten, benchmark, quelle, gelernt, zeit)
                            VALUES ('Momentum', 'AAPL', 'mittel', ?, '100', '101', ?, 'Annahme', 'nicht gemessen', 'simulation', 0, ?)
                            """,
                            (werte, netto, f"2026-03-{(nummer % 28) + 1:02d}T00:00:00+00:00"),
                        )
            bericht = pruefe(pfad, "Momentum")
            self.assertEqual(bericht["wahl"], "regel")
            self.assertFalse(bericht["besser"])
            self.assertEqual(bericht["status"], "Benchmark nicht gemessen")
            with sqlite3.connect(pfad) as verbindung:
                self.assertEqual(verbindung.execute("SELECT COUNT(*) FROM ki_haendler_modell").fetchone()[0], 0)
            self.assertFalse(strategie_uebernehmen(99)[0])

    def test_gemessener_index_kann_das_modell_freigeben_ohne_es_zu_uebernehmen(self):
        from haendler import _tabellen

        with tempfile.TemporaryDirectory() as ordner:
            pfad = Path(ordner) / "markt.sqlite"
            _tabellen(pfad)
            with sqlite3.connect(pfad) as verbindung:
                verbindung.execute("CREATE TABLE IF NOT EXISTS kurse (symbol TEXT, zeit INTEGER, schluss REAL)")
                verbindung.execute("INSERT INTO kurse (symbol, zeit, schluss) VALUES ('^GDAXI', ?, 100)", (int(datetime(2026, 1, 1, tzinfo=BERLIN).timestamp()),))
                verbindung.execute("INSERT INTO kurse (symbol, zeit, schluss) VALUES ('^GDAXI', ?, 90)", (int(datetime(2026, 6, 1, tzinfo=BERLIN).timestamp()),))
                for _block, monat in ((0, 1), (1, 3), (2, 5)):
                    for paar in range(12):
                        for _gewinner, werte, netto in ((True, "[1, 0]", "10.00"), (False, "[0, 1]", "-1.00")):
                            tag = paar + 1
                            verbindung.execute(
                                """
                                INSERT INTO ki_haendler_fall
                                (haendler, symbol, horizont, merkmale, einstieg, ausstieg, ergebnis, menge, kosten, benchmark, quelle, gelernt, zeit, ausstieg_zeit)
                                VALUES ('Momentum', 'AAPL', 'mittel', ?, '100', '110', ?, '1', 'Annahme', 'nicht gemessen', 'simulation', 0, ?, ?)
                                """,
                                (
                                    werte,
                                    netto,
                                    f"2026-0{monat}-{tag:02d}T00:00:00+00:00",
                                    f"2026-0{monat}-{tag:02d}T12:00:00+00:00",
                                ),
                            )
            bericht = pruefe(pfad, "Momentum")
            self.assertEqual(bericht["wahl"], "modell")
            self.assertTrue(bericht["besser"])
            self.assertEqual(bericht["status"], "Geprüft")
            self.assertGreater(float(bericht["grund"].split("Untere Grenze ")[1].split(".")[0]), 0)
            self.assertLess(bericht["train_bis"], bericht["pruef_ab"])
            self.assertLess(bericht["pruef_ab"], bericht["test_ab"])
            with sqlite3.connect(pfad) as verbindung:
                self.assertEqual(verbindung.execute("SELECT COUNT(*) FROM ki_haendler_modell").fetchone()[0], 0)

    def test_neues_buch_und_anderes_startkapital_sind_kein_gewinn(self):
        from haendler import kapital_buchen
        from papier import _tabellen as papier_tabellen

        with tempfile.TemporaryDirectory() as ordner:
            pfad = Path(ordner) / "markt.sqlite"
            papier_tabellen(pfad)
            self.assertTrue(kapital_buchen(pfad, "Momentum", Decimal(10000), "eroeffnung", "2026-11-20T10:00:00+00:00"))
            self.assertFalse(kapital_buchen(pfad, "Momentum", Decimal(99999), "eroeffnung", "2026-11-20T11:00:00+00:00"))
            with sqlite3.connect(pfad) as verbindung:
                verbindung.execute(
                    "INSERT INTO paper_konto (broker, waehrung, equity, cash, sleeve, kurs, quelle, zeit, konto) VALUES ('Lokal', 'EUR', '10000', '10000', '10000', '', '', '2026-11-20T10:00:00+00:00', 'Momentum')"
                )
                verbindung.execute(
                    "INSERT INTO paper_konto (broker, waehrung, equity, cash, sleeve, kurs, quelle, zeit, konto) VALUES ('Lokal', 'EUR', '11000', '11000', '10000', '', '', '2026-11-20T11:00:00+00:00', 'Momentum')"
                )
                verbindung.execute(
                    "INSERT INTO paper_konto (broker, waehrung, equity, cash, sleeve, kurs, quelle, zeit, konto) VALUES ('Lokal', 'EUR', '11000', '11000', '10000', '', '', '2026-11-20T11:00:00+00:00', 'Momentum')"
                )
                verbindung.execute(
                    "INSERT INTO paper_konto (broker, waehrung, equity, cash, sleeve, kurs, quelle, zeit, konto) VALUES ('Lokal', 'EUR', '8000', '8000', '10000', '', '', '2026-11-20T11:00:00+00:00', 'Momentum')"
                )
            self.assertTrue(kapital_buchen(pfad, "RSI", Decimal(2000), "eroeffnung", "2026-11-20T12:00:00+00:00"))
            with sqlite3.connect(pfad) as verbindung:
                verbindung.execute(
                    "INSERT INTO paper_konto (broker, waehrung, equity, cash, sleeve, kurs, quelle, zeit, konto) VALUES ('Lokal', 'EUR', '2000', '2000', '2000', '', '', '2026-11-20T12:00:00+00:00', 'RSI')"
                )
            zentrale = uebersicht(pfad)["zentrale"]
            self.assertEqual(zentrale["equity"], "10000.00")
            self.assertEqual(zentrale["kapital"], "12000.00")
            self.assertEqual(zentrale["gesamt"][1]["equity"], 8000.0)
            self.assertEqual(zentrale["gesamt"][-1]["equity"], 10000.0)
            self.assertEqual(zentrale["gesamt"][-1]["wert"], 8000.0)
            self.assertEqual(zentrale["rendite"], "-16.7 %")
            self.assertTrue(kapital_buchen(pfad, "Momentum", Decimal(5000), "einzahlung", "2026-11-21T10:00:00+00:00"))
            with sqlite3.connect(pfad) as verbindung:
                verbindung.execute(
                    "INSERT INTO paper_konto (broker, waehrung, equity, cash, sleeve, kurs, quelle, zeit, konto) VALUES ('Lokal', 'EUR', '13000', '13000', '15000', '', '', '2026-11-21T10:00:00+00:00', 'Momentum')"
                )
            nachher = uebersicht(pfad)["zentrale"]
            self.assertEqual(nachher["gesamt"][-1]["wert"], 8000.0)
            self.assertEqual(nachher["gesamt"][-1]["equity"], 15000.0)
            self.assertTrue(kapital_buchen(pfad, "RSI", Decimal(2000), "zuruecksetzen", "2026-11-21T11:00:00+00:00"))
            with sqlite3.connect(pfad) as verbindung:
                alt = verbindung.execute("SELECT equity FROM paper_konto WHERE konto = 'Momentum' ORDER BY id LIMIT 1").fetchone()[0]
                verbindung.execute(
                    "INSERT INTO paper_konto (broker, waehrung, equity, cash, sleeve, kurs, quelle, zeit, konto) VALUES ('Lokal', 'EUR', '2000', '2000', '2000', '', '', '2026-11-21T11:00:00+00:00', 'RSI')"
                )
            self.assertEqual(alt, "10000")
            frisch = uebersicht(pfad)["zentrale"]
            self.assertEqual(frisch["gesamt"][1]["wert"], 8000.0)

    def test_fehlende_positionsdaten_bleiben_unvollstaendig(self):
        from papier import _tabellen as papier_tabellen

        with tempfile.TemporaryDirectory() as ordner:
            pfad = Path(ordner) / "markt.sqlite"
            papier_tabellen(pfad)
            frisch = int(datetime(2026, 11, 22, 10, tzinfo=BERLIN).timestamp())
            alt = int(datetime(2020, 1, 1, tzinfo=BERLIN).timestamp())
            with sqlite3.connect(pfad) as verbindung:
                verbindung.execute("CREATE TABLE IF NOT EXISTS kurse (symbol TEXT, zeit INTEGER, schluss REAL)")
                verbindung.execute("INSERT INTO kurse (symbol, zeit, schluss) VALUES ('AAPL', ?, 120)", (frisch,))
                verbindung.execute("INSERT INTO kurse (symbol, zeit, schluss) VALUES ('MSFT', ?, 90)", (alt,))
                verbindung.execute("INSERT INTO kurse (symbol, zeit, schluss) VALUES ('MSFT', ?, -1)", (frisch,))
                verbindung.execute(
                    "INSERT INTO paper_buch (konto, symbol, menge, einstieg, zeit, strategie, jetzt) VALUES ('Momentum', 'AAPL', '1', '100', '2026-11-22T10:00:00+00:00', 'Momentum', '120')"
                )
                verbindung.execute(
                    "INSERT INTO paper_buch (konto, symbol, menge, einstieg, zeit, strategie, jetzt) VALUES ('Momentum', 'MSFT', '1', '100', '2026-11-22T10:00:00+00:00', 'Momentum', '90')"
                )
                verbindung.execute(
                    "INSERT INTO paper_buch (konto, symbol, menge, einstieg, zeit, strategie) VALUES ('RSI', 'SAP.DE', '', '', '2026-11-22T10:00:00+00:00', 'RSI')"
                )
            bild = uebersicht(pfad)
            momentum = next(zeile for zeile in bild["rangliste"] if zeile["name"] == "Momentum")
            rsi = next(zeile for zeile in bild["rangliste"] if zeile["name"] == "RSI")
            self.assertIsNone(momentum["unrealisiert_zahl"])
            self.assertEqual(momentum["detail"]["offen"][0]["status"], "Kurs aktuell")
            self.assertEqual(momentum["detail"]["offen"][1]["status"], "Kurs veraltet")
            self.assertNotEqual(momentum["detail"]["offen"][0]["kurszeit"], momentum["detail"]["offen"][1]["kurszeit"])
            self.assertEqual(rsi["detail"]["offen"][0]["status"], "Menge fehlt")
            self.assertIn("je symbol", bild["zentrale"]["aktualitaet"]["kurs_hinweis"].lower())
            self.assertIn("Unvollständig", bild["zentrale"]["aktualitaet"]["kurs_hinweis"])

    def test_pruefung_folgt_der_zeit_und_nicht_der_id(self):
        from datetime import timedelta

        from haendler import _tabellen

        with tempfile.TemporaryDirectory() as ordner:
            pfad = Path(ordner) / "markt.sqlite"
            _tabellen(pfad)
            with sqlite3.connect(pfad) as verbindung:
                for nummer in range(36):
                    zeit = datetime(2026, 5, 1, tzinfo=BERLIN) + timedelta(days=35 - nummer)
                    verbindung.execute(
                        """
                        INSERT INTO ki_haendler_fall
                        (haendler, symbol, horizont, merkmale, einstieg, ausstieg, ergebnis, kosten, benchmark, quelle, gelernt, zeit, ausstieg_zeit)
                        VALUES ('Momentum', 'AAPL', 'mittel', '[0.1, 0.1]', '100', '101', '1.00', 'Annahme', 'nicht gemessen', 'simulation', 0, ?, ?)
                        """,
                        (zeit.isoformat(), (zeit + timedelta(hours=12)).isoformat()),
                    )
            bericht = pruefe(pfad, "Momentum")
            self.assertEqual(bericht["status"], "Benchmark nicht gemessen")
            self.assertGreater(bericht["train_bis"], bericht["pruef_ab"])
            self.assertGreater(bericht["pruef_ab"], bericht["test_ab"])
            self.assertFalse(bericht["besser"])

    def test_negativer_vorsprung_wird_nicht_freigegeben(self):
        from haendler import _haltung, _tabellen

        with tempfile.TemporaryDirectory() as ordner:
            pfad = Path(ordner) / "markt.sqlite"
            _tabellen(pfad)
            with sqlite3.connect(pfad) as verbindung:
                verbindung.execute("CREATE TABLE IF NOT EXISTS kurse (symbol TEXT, zeit INTEGER, schluss REAL)")
                for tag in range(1, 13):
                    eintritt = datetime(2026, 5, tag, tzinfo=BERLIN)
                    verbindung.execute(
                        "INSERT INTO kurse (symbol, zeit, schluss) VALUES ('^GDAXI', ?, 100)",
                        (int(eintritt.timestamp()),),
                    )
                    verbindung.execute(
                        "INSERT INTO kurse (symbol, zeit, schluss) VALUES ('^GDAXI', ?, 10)",
                        (int(eintritt.timestamp()) + 6 * 3600,),
                    )
                for monat, netto_gut, netto_schlecht in ((1, "10.00", "-1.00"), (3, "-0.30", "-1.00"), (5, "-0.30", "-1.00")):
                    for tag in range(1, 13):
                        for werte, netto in (("[1, 0]", netto_gut), ("[0, 1]", netto_schlecht)):
                            verbindung.execute(
                                """
                                INSERT INTO ki_haendler_fall
                                (haendler, symbol, horizont, merkmale, einstieg, ausstieg, ergebnis, menge, kosten, benchmark, quelle, gelernt, zeit, ausstieg_zeit)
                                VALUES ('Momentum', 'AAPL', 'mittel', ?, '100', '99', ?, '1', 'Annahme', 'nicht gemessen', 'simulation', 0, ?, ?)
                                """,
                                (werte, netto, f"2026-0{monat}-{tag:02d}T00:00:00+00:00", f"2026-0{monat}-{tag:02d}T12:00:00+00:00"),
                            )
                verbindung.execute(
                    """
                    INSERT INTO ki_haendler_fall
                    (haendler, symbol, horizont, merkmale, einstieg, ausstieg, ergebnis, kosten, benchmark, quelle, gelernt, zeit, ausstieg_zeit)
                    VALUES ('RSI', 'AAPL', 'kurz', '[0.1]', '100', '101', '1.00', 'Annahme', 'nicht gemessen', 'simulation', 0, '2026-05-01T00:00:00', '2026-05-01T12:00:00+00:00')
                    """
                )
            bericht = pruefe(pfad, "Momentum")
            self.assertEqual(bericht["wahl"], "modell")
            self.assertFalse(bericht["besser"])
            self.assertEqual(bericht["status"], "Nicht freigegeben")
            self.assertEqual(_haltung(pfad, "RSI"), "12.0 Stunden aus 1 Trades")

    def test_suche_und_sortierung_im_dashboard(self):
        import subprocess

        quelle = Path("fenster_app/seite.html").read_text()
        funktion = quelle[quelle.index("function kiListe"):quelle.index("function detailBlick")]
        script = (
            "const quelle = " + repr(quelle) + ";\n"
            "let kiSuche = '';\nlet kiFilter = 'alle';\nlet kiSort = 'name';\nlet kiRichtung = 'auf';\n"
            + funktion
            + """
            kiSuche = "rsi";
            kiSort = "rendite_zahl";
            kiRichtung = "ab";
            const stand = {rangliste: [
              {name:"RSI", einsatz:true, horizont:"kurz", gruppe:"Technik", belastbar:false, rendite_zahl: 1.5},
              {name:"Momentum", einsatz:true, horizont:"mittel", gruppe:"Technik", belastbar:false, rendite_zahl: 20},
              {name:"RSI Trend", einsatz:false, horizont:"lang", gruppe:"Technik", belastbar:false, rendite_zahl: null}
            ]};
            const gesucht = kiListe(stand, true).map(function (zeile) { return zeile.name; });
            if (gesucht.join(",") !== "RSI,RSI Trend") throw new Error("suche " + gesucht.join(","));
            kiSuche = "";
            const sortiert = kiListe(stand, true).map(function (zeile) { return zeile.name; });
            if (sortiert.join(",") !== "Momentum,RSI,RSI Trend") throw new Error("sort " + sortiert.join(","));
            kiFilter = "pausiert";
            const pausiert = kiListe(stand, false).map(function (zeile) { return zeile.name; });
            if (pausiert.join(",") !== "RSI Trend") throw new Error("filter " + pausiert.join(","));
            if (quelle.indexOf("Der Zeitraum filtert nur die Diagramme") < 0) throw new Error("zeit");
            if (quelle.indexOf("kiSuche = suche.value") < 0) throw new Error("eingabe");
            """
        )
        ergebnis = subprocess.run(["node", "-e", script], capture_output=True, text=True, check=False)
        self.assertEqual(ergebnis.returncode, 0, ergebnis.stderr)
