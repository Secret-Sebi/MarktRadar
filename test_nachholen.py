"""Eine Runde ohne Fenster, solange das Fenster nicht selbst misst."""

import os
import tempfile
import time
import unittest
from io import StringIO
from pathlib import Path

from auswertung import merken
from beobachter import fenster_laeuft, nachholen
from lernen import _abruf_merken


class NachholenTests(unittest.TestCase):
    def test_offenes_fenster_wird_nicht_doppelt_gemessen(self):
        with tempfile.TemporaryDirectory() as ordner:
            pid = Path(ordner) / "fenster.pid"
            pid.write_text(str(os.getpid()), encoding="utf-8")
            ausgabe = StringIO()
            code = nachholen(ausgabe, pid_pfad=pid)
        self.assertEqual(code, 0)
        self.assertIn("Fenster misst schon", ausgabe.getvalue())

    def test_tote_pid_gilt_nicht_als_fenster(self):
        with tempfile.TemporaryDirectory() as ordner:
            pid = Path(ordner) / "fenster.pid"
            pid.write_text("999999", encoding="utf-8")
            self.assertFalse(fenster_laeuft(pid))

    def test_frische_liste_wird_nicht_neu_geladen(self):
        with tempfile.TemporaryDirectory() as ordner:
            wurzel = Path(ordner)
            cache = wurzel / "universum.txt"
            cache.write_text("# liquide\nAAPL\n", encoding="utf-8")
            liste = wurzel / "watchlist.txt"
            liste.write_text("# leer\n", encoding="utf-8")
            datenbank = wurzel / "markt.sqlite"
            merken(
                datenbank,
                (
                    {
                        "symbol": "AAPL",
                        "name": "Apple",
                        "preis": "100 EUR",
                        "wert": 100,
                        "tag": "0 %",
                        "tag_wert": 0,
                        "richtung": "ohne",
                        "herkunft": "Yahoo",
                        "fenster": "",
                        "datenstatus": "ok",
                        "bereich": "USA",
                        "kurszeit": int(time.time()),
                    },
                ),
            )
            _abruf_merken(datenbank, "AAPL", int(time.time()))
            ausgabe = StringIO()
            code = nachholen(ausgabe, pid_pfad=wurzel / "fehlt.pid", liste=liste, cache=cache, datenbank=datenbank)
        self.assertEqual(code, 0)
        self.assertIn("6 Stunden", ausgabe.getvalue())


if __name__ == "__main__":
    unittest.main()
