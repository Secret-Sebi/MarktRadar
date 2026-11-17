"""Nachrichtenwirkungen nur aus Kursen, die nach der Meldung liegen."""

import sqlite3
import tempfile
import unittest
from pathlib import Path

from database import signal_speichern
from kurse import Bar
from lernen import (
    Meldung,
    aktion_aus_lernen,
    aktion_aus_verkauf,
    aus_gdelt,
    aus_yahoo,
    einfluss,
    fortschritt,
    gegen_index,
    kategorie,
    nachtragen,
    satz,
    soll_holen,
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

    def test_index_und_abrufpause(self):
        self.assertIsNone(gegen_index(None, 1.0))
        self.assertAlmostEqual(gegen_index(2.0, 0.5), 1.5)
        self.assertTrue(soll_holen(None, 1000))
        self.assertFalse(soll_holen(1000, 2000, 1800))
        self.assertTrue(soll_holen(1000, 3000, 1800))

    def test_fortschritt_und_einfluss_ohne_erfundene_wirkung(self):
        with tempfile.TemporaryDirectory() as ordner:
            pfad = Path(ordner) / "markt.sqlite"
            speichern(
                pfad,
                "SAP.DE",
                (
                    Meldung("SAP Zahlen", "Yahoo", 1_000, "https://a", "quartal"),
                    Meldung("SAP offen", "Yahoo", 1_100, "https://c", "quartal"),
                ),
            )
            speichern(pfad, "SIE.DE", (Meldung("Siemens Zahlen", "Yahoo", 1_200, "https://b", "quartal"),))
            self.assertEqual(fortschritt(pfad)["offen"], 3)
            self.assertIn("warten noch", fortschritt(pfad)["text"])
            with sqlite3.connect(pfad) as verbindung:
                verbindung.execute("UPDATE nachrichten SET wirkung_5 = -1.0, rel_5 = -0.5 WHERE url = ?", ("https://a",))
                verbindung.execute("UPDATE nachrichten SET wirkung_5 = -6.0, rel_5 = -5.0 WHERE url = ?", ("https://b",))
            bild = einfluss(pfad, 7, 1_000 + 3600)
            self.assertEqual(bild["meldungen"][0]["symbole"][0]["symbol"], "SIE.DE")
            self.assertEqual([eintrag["titel"] for eintrag in bild["meldungen"]], ["Siemens Zahlen", "SAP Zahlen"])
            self.assertEqual(bild["offen"][0]["titel"], "SAP offen")
            self.assertNotIn("SAP offen", [eintrag["titel"] for eintrag in bild["meldungen"]])
            self.assertIn("Zusammenhang", bild["hinweis"])
            ausserhalb = einfluss(pfad, 1, 1_000 + 3 * 86400)
            self.assertFalse(ausserhalb["meldungen"])
            self.assertIn("keine zugeordnete", ausserhalb["hinweis"])
            self.assertEqual(fortschritt(pfad)["abgeschlossen"], 2)

    def test_dieselbe_url_gilt_fuer_zwei_namen(self):
        with tempfile.TemporaryDirectory() as ordner:
            pfad = Path(ordner) / "markt.sqlite"
            with sqlite3.connect(pfad) as verbindung:
                verbindung.execute(
                    """
                    CREATE TABLE nachrichten (
                        id INTEGER PRIMARY KEY,
                        url TEXT NOT NULL UNIQUE,
                        symbol TEXT NOT NULL,
                        zeit INTEGER NOT NULL,
                        titel TEXT NOT NULL,
                        quelle TEXT NOT NULL,
                        kategorie TEXT NOT NULL
                    )
                    """
                )
            meldung = Meldung("Zinsen steigen", "Yahoo", 1_000, "https://gleich", "zinsen")
            self.assertEqual(speichern(pfad, "SAP.DE", (meldung,)), 1)
            self.assertEqual(speichern(pfad, "ALV.DE", (meldung,)), 1)
            with sqlite3.connect(pfad) as verbindung:
                namen = {zeile[0] for zeile in verbindung.execute("SELECT symbol FROM nachrichten")}
            self.assertEqual(namen, {"SAP.DE", "ALV.DE"})


def statistik_leer():
    from lernen import Befund

    return Befund("zinsen", 3, -1.0, "dieses Kürzel")


if __name__ == "__main__":
    unittest.main()
