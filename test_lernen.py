"""Nachrichtenwirkungen nur aus Kursen, die nach der Meldung liegen."""

import tempfile
import unittest
from pathlib import Path

from database import signal_speichern
from kurse import Bar
from lernen import (
    aktion_aus_lernen,
    aktion_aus_verkauf,
    aus_gdelt,
    aus_yahoo,
    kategorie,
    nachtragen,
    satz,
    speichern,
    statistik,
    wirkung,
)


def _balken():
    return tuple(Bar(tag * 100, None, None, None, preis, preis, None) for tag, preis in enumerate((10, 11, 12, 9, 8), start=1))


class WirkungTests(unittest.TestCase):
    def test_kategorie_ohne_bewertung(self):
        self.assertEqual(kategorie("Fed hält den Leitzins"), "zinsen")
        self.assertEqual(kategorie("SAP hebt die Prognose"), "unklar")

    def test_yahoo_und_gdelt(self):
        yahoo = aus_yahoo({"news": [{"title": "EZB hebt die Zinsen", "link": "https://beispiel.test/a", "publisher": "Reuters", "providerPublishTime": 250}]})
        gdelt = aus_gdelt({"articles": [{"title": "Neue Sanktionen", "url": "https://beispiel.test/b", "domain": "example.com", "seendate": "20240615T120000Z"}]})
        self.assertEqual(yahoo[0].kategorie, "zinsen")
        self.assertEqual(gdelt[0].kategorie, "geopolitik")
        self.assertGreater(gdelt[0].zeit, 0)

    def test_keine_kurse_vor_der_meldung(self):
        self.assertIsNone(wirkung(_balken(), 600, 1))
        self.assertAlmostEqual(wirkung(_balken(), 150, 1), (12 / 11 - 1) * 100)

    def test_zweite_meldung_aendert_den_median(self):
        with tempfile.TemporaryDirectory() as ordner:
            pfad = Path(ordner) / "markt.sqlite"
            signal_speichern(pfad, "SAP.DE", "2026-11-14T10:00+01:00", "beobachten", 10, 40, "alt", "")
            kurs = tuple(Bar((index + 1) * 100, None, None, None, preis, preis, None) for index, preis in enumerate((10, 20, 20, 20, 20, 20, 30, 10, 10, 10)))
            speichern(pfad, "SAP.DE", aus_yahoo({"news": [{"title": "Fed erhöht die Zinsen", "link": "https://beispiel.test/1", "publisher": "Reuters", "providerPublishTime": 150}]}))
            nachtragen(pfad, "SAP.DE", kurs)
            erster = statistik(pfad, "SAP.DE")
            speichern(pfad, "SAP.DE", aus_yahoo({"news": [{"title": "Fed erhöht die Zinsen erneut", "link": "https://beispiel.test/2", "publisher": "Reuters", "providerPublishTime": 50}]}))
            nachtragen(pfad, "SAP.DE", kurs)
            zweiter = statistik(pfad, "SAP.DE")
            self.assertEqual(speichern(pfad, "SAP.DE", aus_yahoo({"news": [{"title": "Fed erhöht die Zinsen", "link": "https://beispiel.test/1", "publisher": "Reuters", "providerPublishTime": 150}]})), 0)
            self.assertEqual(erster.anzahl, 1)
            self.assertEqual(zweiter.anzahl, 2)
            self.assertNotEqual(erster.median, zweiter.median)

    def test_lernen_erzeugt_kein_kaufsignal(self):
        self.assertEqual(aktion_aus_lernen("beobachten", 12, 4.0), "beobachten")
        self.assertEqual(aktion_aus_lernen("einstieg_pruefen", 3, -5.0), "einstieg_pruefen")
        self.assertEqual(aktion_aus_lernen("einstieg_pruefen", 8, -2.0), "abwarten")
        self.assertIn("Kleine Stichprobe", satz(statistik_leer()))

    def test_verkauf_nur_nach_eigenen_faellen(self):
        self.assertEqual(aktion_aus_verkauf("vorsicht", 0, None, True), "vorsicht")
        self.assertEqual(aktion_aus_verkauf("vorsicht", 3, -4.0, True), "vorsicht")
        self.assertEqual(aktion_aus_verkauf("beobachten", 8, -1.0, False), "beobachten")
        self.assertEqual(aktion_aus_verkauf("beobachten", 8, 1.0, True), "beobachten")
        self.assertEqual(aktion_aus_verkauf("beobachten", 8, -2.0, True), "verkauf_pruefen")
        self.assertEqual(aktion_aus_verkauf("unvollstaendig", 8, -2.0, True), "unvollstaendig")


def statistik_leer():
    from lernen import Befund

    return Befund("zinsen", 3, -1.0, "dieses Kürzel")


if __name__ == "__main__":
    unittest.main()
