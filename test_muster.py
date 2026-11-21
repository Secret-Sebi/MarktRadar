"""Unabhängige Fensterfälle. Acht überlappende Tage sind keine Einschätzung."""

import unittest

from analyse import Kennzahlen, setup_aus_kennzahlen
from muster import _entscheidung, pruefen, signale, unabhaengige


def _horizont(anzahl, median, streuung, treffer, index_median, tage=5):
    return {
        "tage": tage,
        "anzahl": anzahl,
        "median": median,
        "treffer": treffer,
        "positiv": int(anzahl * treffer),
        "negativ": anzahl - int(anzahl * treffer),
        "schlechtester": -5.0,
        "bester": 8.0,
        "streuung": streuung,
        "index_median": index_median,
    }


class MusterTests(unittest.TestCase):
    def test_ueberlappende_tage_zaehlen_nicht_doppelt(self):
        werte = tuple(float(100 + index) for index in range(20))
        self.assertEqual(len(unabhaengige(werte, (0, 1, 2, 10), 5, None)), 2)

    def test_wenige_faelle_stehen_nicht_vor_einer_stabileren_reihe(self):
        klein = _entscheidung((_horizont(8, 20.0, 1.0, 0.9, 0.1),), True)
        self.assertIsNone(klein["rang"])
        self.assertEqual(klein["qualitaet"], "zu_klein")
        dreissig = _entscheidung((_horizont(30, 4.0, 8.0, 0.55, 0.2),), True)
        hundert = _entscheidung((_horizont(100, 1.2, 1.5, 0.62, 0.2),), True)
        self.assertIsNotNone(dreissig["rang"])
        self.assertGreater(hundert["rang"], dreissig["rang"])

    def test_ohne_vorsprung_index_oder_bereinigung_kein_rang(self):
        ohne_vorsprung = _entscheidung((_horizont(80, 0.2, 1.0, 0.4, 0.3),), True)
        self.assertEqual(ohne_vorsprung["qualitaet"], "kein_vorsprung")
        self.assertIsNone(ohne_vorsprung["rang"])
        ohne_index = _entscheidung((_horizont(40, 2.0, 1.0, 0.6, None),), True)
        self.assertEqual(ohne_index["qualitaet"], "index_fehlt")
        roh = _entscheidung((_horizont(40, 2.0, 1.0, 0.6, 0.1),), False)
        self.assertEqual(roh["qualitaet"], "unbereinigt")
        self.assertIsNone(roh["rang"])

    def test_aktie_und_etf_sind_getrennt(self):
        aktie = Kennzahlen(95, 100, 110, 90, 50, 110, -1, 0, False, 220)
        etf = Kennzahlen(95, 100, 110, 90, 50, 110, -1, 0, True, 220)
        self.assertTrue(setup_aus_kennzahlen(aktie))
        self.assertFalse(setup_aus_kennzahlen(etf))

    def test_spaetere_kurse_aendern_alte_signale_nicht(self):
        werte = []
        preis = 100.0
        for _index in range(260):
            preis *= 1.001
            werte.append(preis)
        basis = signale(tuple(werte), False)
        erweitert = signale(tuple(werte) + (preis * 2,), False)
        self.assertEqual(basis, tuple(index for index in erweitert if index < len(werte)))

    def test_kurzer_zeitraum_sagt_datenbasis_zu_klein(self):
        zahlen = Kennzahlen(95, 100, 110, 90, 42, 110, -1, 0, False, 220)
        bild = pruefen(zahlen, (100.0,) * 30, None, True)
        self.assertTrue(bild["aktiv"])
        self.assertIsNone(bild["rang"])
        self.assertIn("Datenbasis zu klein", bild["satz"])
        self.assertIn("Annahme", bild["satz"])
        self.assertIn("kein Auftrag", bild["satz"])
        zu = Kennzahlen(80, 90, 85, 100, 40, 110, -1, 0, False, 220)
        geschlossen = pruefen(zu, (100.0,) * 30, None, True)
        self.assertFalse(geschlossen["aktiv"])
        self.assertIsNone(geschlossen["rang"])
        self.assertIn("nicht offen", geschlossen["satz"])
        self.assertIn("Datenbasis zu klein", geschlossen["satz"])
