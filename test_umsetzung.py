"""Nachweis für Horizonte, Fundamentalstatus, Index und Positionsgrenze."""

import sqlite3
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from urllib.request import urlopen

from beobachter import index_sichern
from fundamental import _CACHE, hole_lage
from haendler import _benchmark_summe, platz_frei
from ki_pruefung import pruefe_faelle
from kurse import Bar


def _fall(zeit: int, ziel: int):
    return (zeit, (float(ziel),) + (0.0,) * 7, float(ziel))


class UmsetzungTests(unittest.TestCase):
    def test_horizont_ohne_stichprobe_bleibt_zu(self):
        self.assertFalse(pruefe_faelle(tuple(_fall(index, index % 2) for index in range(20)))["bestanden"])

    def test_horizont_mit_trennbaren_faellen_kann_bestehen(self):
        bericht = pruefe_faelle(tuple(_fall(index, index % 2) for index in range(120)))
        self.assertTrue(bericht["bestanden"], bericht["grund"])
        self.assertLess(bericht["brier"], bericht["basis_brier"])
        self.assertLess(bericht["logloss"], bericht["basis_logloss"])

    def test_konstante_reihe_besteht_nicht(self):
        self.assertFalse(pruefe_faelle(tuple(_fall(index, 1) for index in range(120)))["bestanden"])

    def test_leere_fundamentalantwort_ist_nicht_verfuegbar_und_fehler_werden_nicht_gehalten(self):
        _CACHE.clear()
        with patch("fundamental._lesen", return_value='{"quoteSummary":{"result":[{}]}}'):
            self.assertEqual(hole_lage("SAP.DE", urlopen, 10).stand, "nicht_verfuegbar")
        _CACHE.clear()
        with patch("fundamental._lesen", side_effect=ConnectionError("weg")):
            self.assertEqual(hole_lage("SIE.DE", urlopen, 11).stand, "fehler")
        self.assertNotIn("SIE.DE", _CACHE)
        self.assertEqual(hole_lage("BTC-USD", urlopen, 12).stand, "nicht_anwendbar")

    def test_index_wird_gespeichert_und_fremder_index_zaehlt_nicht(self):
        with tempfile.TemporaryDirectory() as ordner:
            pfad = Path(ordner) / "markt.sqlite"
            daten = SimpleNamespace(
                symbol="^GSPC",
                balken=(Bar(1, None, None, None, 10, 10, None), Bar(2, None, None, None, 11, 11, None)),
                hat_bereinigt=False,
            )
            self.assertEqual(index_sichern(pfad, daten), 2)
            self.assertEqual(index_sichern(pfad, ConnectionError("weg")), 0)
            with sqlite3.connect(pfad) as verbindung:
                self.assertEqual(verbindung.execute("SELECT COUNT(*) FROM kurse WHERE symbol = '^GSPC'").fetchone()[0], 2)
                verbindung.execute("DELETE FROM kurse")
                verbindung.execute("INSERT INTO kurse (symbol, zeit, schluss) VALUES ('^GDAXI', 1, 100)")
                verbindung.execute("INSERT INTO kurse (symbol, zeit, schluss) VALUES ('^GDAXI', 2, 90)")
            fall = {"symbol": "AAPL", "einstieg": 100, "menge": 1, "zeit": "1970-01-01T00:00:02+00:00", "ausstieg_zeit": "1970-01-01T00:00:03+00:00"}
            summe, text = _benchmark_summe(pfad, [fall])
            self.assertIsNone(summe)
            self.assertIn("Datenlücke", text)

    def test_elfter_platz_in_derselben_runde_bleibt_zu(self):
        self.assertFalse(platz_frei(10, 0))
        self.assertTrue(platz_frei(9, 0))
        offen = 8
        gekauft = 0
        for _ in range(12):
            if not platz_frei(offen, gekauft):
                continue
            offen += 1
            gekauft += 1
        self.assertEqual((offen, gekauft), (10, 2))
