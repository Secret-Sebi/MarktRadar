"""Modellvergleich. Ein besserer Validierungswert gibt das Modell nicht frei."""

import unittest

from ki_pruefung import pruefe_faelle
from prognose_vergleich import vergleiche
from test_umsetzung import _fall


def _merkmal(index: int, ziel: int, letztes: int):
    return (index, (0.0,) * 7 + (float(letztes),), float(ziel), index * 10, index * 10 + 9)


class VergleichTests(unittest.TestCase):
    def test_konstante_reihe_oeffnet_den_test_nicht(self):
        faelle = tuple(_merkmal(index, 1, 0) for index in range(72))
        bericht = vergleiche(faelle[:36], faelle[36:], (), test_offen=False)
        self.assertFalse(bericht["freigegeben"])
        self.assertIn("random_forest", bericht["nicht_implementiert"])
        self.assertIn("gradient_boosting", bericht["nicht_implementiert"])
        self.assertTrue(bericht["modelle"])
        self.assertTrue(all(modell["test"] is None and not modell["freigegeben"] for modell in bericht["modelle"]))

    def test_momentum_ist_eine_andere_regel_und_bleibt_gesperrt(self):
        train = tuple(_merkmal(index, index % 2, index % 2) for index in range(36))
        val = tuple(_merkmal(index, index % 2, index % 2) for index in range(36, 72))
        bericht = vergleiche(train, val, val, test_offen=False)
        modelle = {modell["id"]: modell for modell in bericht["modelle"]}
        self.assertTrue(modelle["momentum"]["schlaegt_validierung"])
        self.assertFalse(modelle["konstant"]["schlaegt_validierung"])
        self.assertNotEqual(modelle["momentum"]["validierung"]["brier"], modelle["konstant"]["validierung"]["brier"])
        self.assertIsNone(modelle["momentum"]["test"])
        self.assertFalse(modelle["momentum"]["freigegeben"])
        self.assertFalse(bericht["freigegeben"])

    def test_bestandene_pruefung_gibt_nur_die_logistik_frei(self):
        bericht = pruefe_faelle(tuple(_fall(index, index % 2) for index in range(120)))
        self.assertTrue(bericht["bestanden"], bericht["grund"])
        freigaben = {modell["id"]: modell["freigegeben"] for modell in bericht["vergleich"]["modelle"]}
        self.assertTrue(freigaben["logistisch"])
        self.assertFalse(freigaben["momentum"])
        self.assertFalse(freigaben["konstant"])

    def test_fehlende_validierung_vergleicht_ohne_testzahlen(self):
        bericht = pruefe_faelle(tuple(_fall(index, 1) for index in range(120)))
        self.assertFalse(bericht["bestanden"])
        self.assertIsNone(bericht["test"])
        self.assertFalse(bericht["vergleich"]["freigegeben"])
        self.assertTrue(all(modell["test"] is None for modell in bericht["vergleich"]["modelle"]))
