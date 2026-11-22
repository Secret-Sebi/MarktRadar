"""Prognosen bleiben leer, bis ein kalibriertes Modell sie trägt."""

import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from prognose import EMPFEHLUNG, TEXT, bewerten, empfehlung, liste, qualitaet, vormerken


class PrognoseTests(unittest.TestCase):
    def test_vormerken_schreibt_keine_wahrscheinlichkeit_und_aendert_nichts(self):
        with tempfile.TemporaryDirectory() as ordner:
            pfad = Path(ordner) / "markt.sqlite"
            self.assertEqual(vormerken(pfad, "AAPL", "2026-11-01T00:00:00+00:00", "2026-11-01T00:00:00+00:00", {"rsi": None}, ("Kurszeit fehlt nicht.",)), 6)
            self.assertEqual(vormerken(pfad, "AAPL", "2026-11-01T00:00:00+00:00", "2026-11-01T00:00:00+00:00", {"rsi": 1}, ("anders",)), 0)
            zeilen = liste(pfad)
            self.assertTrue(all(zeile["p_hoch"] is None and zeile["empfehlung"] == EMPFEHLUNG for zeile in zeilen))
            self.assertIn("Kurszeit", zeilen[0]["gruende"])
            self.assertEqual(empfehlung(True, 1, 0.9), (EMPFEHLUNG, TEXT))

    def test_ausgang_aendert_die_prognose_nicht_und_kleine_stichprobe_bleibt_leer(self):
        with tempfile.TemporaryDirectory() as ordner:
            pfad = Path(ordner) / "markt.sqlite"
            vormerken(pfad, "AAPL", "2026-11-01T00:00:00+00:00", None, {}, ())
            start = int(datetime(2026, 11, 1, tzinfo=timezone.utc).timestamp())  # noqa: UP017
            kurse = {"AAPL": [(start, 100.0)] + [(start + tag * 86400, 110.0) for tag in range(1, 40)]}
            self.assertGreater(bewerten(pfad, kurse, datetime(2026, 12, 20, tzinfo=timezone.utc)), 0)  # noqa: UP017
            self.assertTrue(all(zeile["p_hoch"] is None for zeile in liste(pfad)))
            bild = qualitaet(pfad)
            self.assertEqual(bild["status"], "Nicht ausreichend Daten")
            self.assertIsNone(bild["erfolg"])
            self.assertLess(bild["anzahl"], 60)


if __name__ == "__main__":
    unittest.main()
