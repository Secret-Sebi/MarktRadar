"""Nachrichten werden verstanden, nicht als Kaufsignal behandelt."""

import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from haendler import entscheide
from lernen import analysen_nachholen, speichern, zuordnungen_nachholen
from nachrichten_analyse import analysiere, schluessel, zuordnung

_NVDA = (
    "Nvidia earnings live: Nvidia to report Q3 results after the bell "
    "with Colette Kress to host first call as interim CEO"
)


class _Technik:
    atr = 2


def _zeile(reihe, symbol="AAPL"):
    zeile = type("Zeile", (), {})()
    zeile.symbol = symbol
    zeile.preis = reihe[-1] if reihe else 100
    zeile.datenstatus = "ok"
    zeile.technik = _Technik()
    zeile.kennzahlen = type("Zahlen", (), {"ist_etf": False})()
    zeile.news_art = ""
    zeile.news_ton = ""
    zeile.news_bild = None
    zeile.muster = {"qualitaet": "vorsichtig", "rang": 1}
    zeile.reihe = reihe
    return zeile


class NachrichtenAnalyseTests(unittest.TestCase):
    def test_positive_partnerschaft_ist_kein_kauf(self):
        bild = analysiere("NVIDIA announces partnership with a supplier", "Reuters", "NVDA", "NVIDIA", 100, 120)
        self.assertEqual(bild["ereignis"], "partnerschaft")
        self.assertEqual(bild["stimmung"], "positiv")
        self.assertGreater(bild["staerke"], 0)
        self.assertFalse(bild["validiert"])
        self.assertIn("kein Auftrag", bild["satz"])

    def test_negative_klage_bleibt_negativ(self):
        bild = analysiere("Apple faces lawsuit over the product", "Reuters", "AAPL", "Apple", 100, 120)
        self.assertEqual(bild["ereignis"], "gericht")
        self.assertEqual(bild["stimmung"], "negativ")
        self.assertLess(bild["staerke"], 0)

    def test_neutrale_meldung_wird_nicht_positiv(self):
        bild = analysiere("SAP schedules a meeting", "Reuters", "SAP.DE", "SAP", 100, 120)
        self.assertEqual(bild["stimmung"], "neutral")
        self.assertEqual(bild["staerke"], 0)

    def test_unternehmen_und_wettbewerber(self):
        bild = analysiere("NVIDIA unveils a new chip", "Reuters", "NVDA", "NVIDIA", 100, 130)
        self.assertEqual(bild["ereignis"], "chip")
        self.assertGreaterEqual(bild["relevanz"], 70)
        self.assertIn("AMD", bild["wettbewerber"])

    def test_gleiche_entscheidung_wird_nicht_doppelt_gezaehlt(self):
        titel = "NVIDIA announces partnership with suppliers"
        erster = schluessel("NVDA", "partnerschaft", titel)
        zweiter = schluessel("NVDA", "partnerschaft", "NVIDIA announces partnership with suppliers today")
        self.assertNotEqual(erster, zweiter)
        bild = analysiere(titel, "Reuters", "NVDA", "NVIDIA", 100, 120, True)
        self.assertFalse(bild["neu"])
        self.assertIn("nicht noch einmal", bild["satz"])

    def test_verspaetete_meldung_gilt_nicht_als_damals_bekannt(self):
        bild = analysiere("NVIDIA announces partnership", "Reuters", "NVDA", "NVIDIA", 1_000, 1_000 + 7 * 3600)
        self.assertTrue(bild["verspaetet"])
        self.assertIn("verspätet", bild["satz"])

    def test_kursreaktion_und_benchmark(self):
        self.assertEqual(zuordnung(None, 1.0), "Kursreaktion noch nicht messbar")
        self.assertIn("Vergleichsindex fehlt", zuordnung(-3.3, None))
        self.assertIn("Gesamtmarkt", zuordnung(1.2, 1.0))
        self.assertIn("Möglicher Einfluss", zuordnung(4.0, 0.5))
        self.assertIn("Mehrere", zuordnung(4.0, 0.5, 2))
        self.assertIn("vor der Veröffentlichung", zuordnung(1.0, 0.0, 0, 3.0))

    def test_analyse_bleibt_unverändert_und_ohne_spaeteren_kurs(self):
        with tempfile.TemporaryDirectory() as ordner:
            pfad = Path(ordner) / "markt.sqlite"
            from lernen import Meldung

            meldung = Meldung("NVIDIA announces partnership", "Reuters", 100, "https://beispiel.test/nvda", "unklar")
            self.assertEqual(speichern(pfad, "NVDA", (meldung,), "NVIDIA"), 1)
            self.assertEqual(speichern(pfad, "NVDA", (meldung,), "NVIDIA"), 0)
            with sqlite3.connect(pfad) as verbindung:
                roh, erfasst = verbindung.execute("SELECT analyse, erfasst FROM nachrichten").fetchone()
            bild = json.loads(roh)
            self.assertNotIn("wirkung_1", bild)
            self.assertGreater(erfasst, 100)
            self.assertTrue(bild["verspaetet"])

    def test_trader_bleiben_eigenstaendig(self):
        reihe = tuple(100 + index for index in range(30))
        zeile = _zeile(reihe)
        zeile.news_bild = analysiere("Apple faces lawsuit", "Reuters", "AAPL", "Apple", 100, 110)
        entscheidung, grund, _merkmale = entscheide("Momentum", zeile)
        self.assertEqual(entscheidung, "BUY")
        self.assertIn("Kursbewegung", grund)
        zeile.news_art = "unternehmen"
        self.assertEqual(entscheide("Nachrichten", zeile)[0], "SKIP")
        self.assertIn("kein Kaufgrund", entscheide("Nachrichten", zeile)[1])
        zeile.news_bild = {
            "ereignis": "gericht",
            "stimmung": "negativ",
            "staerke": -40,
            "bestaetigt": "bestaetigt",
            "verspaetet": False,
        }
        self.assertEqual(entscheide("Defensiv", zeile)[0], "HOLD")

    def test_nvidia_gespeicherte_ueberschrift_behauptet_keine_ursache(self):
        bild = analysiere(_NVDA, "Yahoo Finance", "NVDA", "NVIDIA", 1795350000, 1795350100)
        self.assertIn(bild["ereignis"], ("personal", "quartal"))
        self.assertNotEqual(bild["bestaetigt"], "bestaetigt")
        self.assertIn("Vergleichsindex fehlt", zuordnung(-3.2988942533417775, None))
        self.assertFalse(bild["validiert"])

    def test_leere_analyse_wird_nachtraeglich_gespeichert(self):
        with tempfile.TemporaryDirectory() as ordner:
            pfad = Path(ordner) / "markt.sqlite"
            with sqlite3.connect(pfad) as verbindung:
                from lernen import _tabelle

                _tabelle(verbindung)
                spalten = {str(zeile[1]) for zeile in verbindung.execute("PRAGMA table_info(nachrichten)")}
                if "ki_genutzt" not in spalten:
                    verbindung.execute("ALTER TABLE nachrichten ADD COLUMN ki_genutzt INTEGER")
                verbindung.execute(
                    """
                    INSERT INTO nachrichten
                    (url, symbol, zeit, titel, quelle, kategorie, wirkung_1, ki_genutzt)
                    VALUES ('https://example.test/nvda', 'NVDA', 1795350000, ?, 'Yahoo Finance', 'unternehmen', -3.3, 0)
                    """,
                    (_NVDA,),
                )
            self.assertEqual(analysen_nachholen(pfad), 1)
            self.assertEqual(zuordnungen_nachholen(pfad), 1)
            with sqlite3.connect(pfad) as verbindung:
                analyse, zuordnung_text, wirkung, genutzt = verbindung.execute(
                    "SELECT analyse, zuordnung, wirkung_1, ki_genutzt FROM nachrichten"
                ).fetchone()
            bild = json.loads(analyse)
            self.assertTrue(bild["nachtraeglich"])
            self.assertIn("Vergleichsindex fehlt", zuordnung_text)
            self.assertAlmostEqual(wirkung, -3.3)
            self.assertEqual(genutzt, 0)
            self.assertEqual(analysen_nachholen(pfad), 0)


if __name__ == "__main__":
    unittest.main()
