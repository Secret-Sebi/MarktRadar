"""Das Modell ändert seine Gewichte nur an abgeschlossenen Fällen."""

import sqlite3
import tempfile
import unittest
from pathlib import Path

from ki import (
    aktion_aus_ki,
    eigene_entscheidung,
    ki_satz,
    leeres_modell,
    lerne_ausgang,
    lies_modell,
    merkmale,
    schritt,
    setze_modell,
    trainiere,
    trefferquote,
    wahrscheinlichkeit,
)
from kurse import Bar
from lernen import aus_yahoo, nachtragen, speichern


def _kursreihe(start: float, schritte: int):
    return tuple(Bar(index * 100, None, None, None, start + index, start + index, None) for index in range(1, schritte + 1))


class ModellTests(unittest.TestCase):
    def test_spaetere_kurse_aendern_die_eingabe_nicht(self):
        vorher = _kursreihe(10, 25)
        nachher = vorher + tuple(Bar(9000, None, None, None, 500, 500, None) for _ in range(5))
        self.assertEqual(merkmale(vorher, 3000, "zinsen"), merkmale(nachher, 3000, "zinsen"))

    def test_gewichte_bewegen_sich(self):
        eingabe = (1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.4, 1.0)
        modell = leeres_modell()
        for _ in range(12):
            modell = schritt(modell, eingabe, 1.0)
        self.assertGreater(modell.gewichte[0], 0.0)
        self.assertEqual(modell.beispiele, 12)
        self.assertGreater(wahrscheinlichkeit(modell, eingabe), 0.5)

    def test_fall_wird_nur_einmal_gelernt(self):
        with tempfile.TemporaryDirectory() as ordner:
            pfad = Path(ordner) / "markt.sqlite"
            balken = _kursreihe(10, 40)
            speichern(pfad, "SAP.DE", aus_yahoo({"news": [{"title": "EZB hebt die Zinsen", "link": "https://beispiel.test/ki", "publisher": "Reuters", "providerPublishTime": 2500}]}))
            nachtragen(pfad, "SAP.DE", balken)
            erster = trainiere(pfad, "SAP.DE", balken)
            zweiter = trainiere(pfad, "SAP.DE", balken)
            self.assertEqual(erster.beispiele, zweiter.beispiele)
            self.assertGreater(erster.beispiele, 0)
            speichern(
                pfad,
                "SAP.DE",
                aus_yahoo(
                    {
                        "news": [
                            {"title": "Nur eine Notiz", "link": "https://beispiel.test/gleicher-tag", "publisher": "Reuters", "providerPublishTime": 2600},
                            {"title": "Noch eine Notiz", "link": "https://beispiel.test/gleicher-tag-2", "publisher": "Reuters", "providerPublishTime": 2700},
                        ]
                    }
                ),
            )
            nachtragen(pfad, "SAP.DE", balken)
            dritter = trainiere(pfad, "SAP.DE", balken)
            self.assertEqual(dritter.beispiele, erster.beispiele)
            self.assertEqual(lies_modell(pfad).beispiele, 0)
            with sqlite3.connect(pfad) as verbindung:
                status = [zeile[0] for zeile in verbindung.execute(
                    "SELECT status FROM ki_beispiel WHERE horizont = 1 ORDER BY nachricht_id"
                )]
            self.assertEqual(status[0], "trainiert")
            self.assertTrue(status[1:])
            self.assertTrue(all(wert == "ausgeschlossen" for wert in status[1:]))

    def test_modell_entscheidet_selbst_und_lernt_den_ausgang_einmal(self):
        balken = _kursreihe(10, 30)
        leer = leeres_modell()
        self.assertFalse(eigene_entscheidung(leer, balken, "zinsen")[0])
        self.assertIn("noch nicht", eigene_entscheidung(leer, balken, "zinsen")[1])
        eingabe = merkmale(balken, None, "zinsen")
        modell = leer
        for _ in range(12):
            modell = schritt(modell, eingabe, 1.0)
        kauf, satz = eigene_entscheidung(modell, balken, "zinsen")
        self.assertTrue(kauf)
        self.assertIn("selbst", satz)
        self.assertEqual(aktion_aus_ki("beobachten", modell, 0.8, True), "beobachten")
        with tempfile.TemporaryDirectory() as ordner:
            pfad = Path(ordner) / "markt.sqlite"
            setze_modell(pfad, modell)
            vorher = lies_modell(pfad).beispiele
            self.assertIsNotNone(lerne_ausgang(pfad, balken, "zinsen", 2900, 0.0))
            self.assertEqual(lies_modell(pfad).beispiele, vorher + 1)
            self.assertIsNone(lerne_ausgang(pfad, balken[:5], "zinsen", 2900, 1.0))
            self.assertEqual(lies_modell(pfad).beispiele, vorher + 1)

    def test_ungepruefte_wahrscheinlichkeit_aendert_nichts(self):
        positiv = leeres_modell()
        eingabe = (1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.4, 1.0)
        for _ in range(20):
            positiv = schritt(positiv, eingabe, 1.0)
        chance = wahrscheinlichkeit(positiv, eingabe)
        self.assertGreater(chance, 0.5)
        self.assertEqual(aktion_aus_ki("beobachten", positiv, chance, True), "beobachten")
        self.assertIn("Handelstage ausgewertet", ki_satz(positiv, chance))

    def test_trefferquote_erzeugt_kein_pruefen(self):
        eingabe = (1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.4, 1.0)
        faelle = tuple((eingabe, 1) for _ in range(24))
        self.assertEqual(trefferquote(faelle), (12, 12))
        self.assertEqual(aktion_aus_ki("beobachten", leeres_modell(), 0.9, True, (12, 12)), "beobachten")
        self.assertEqual(aktion_aus_ki("einstieg_pruefen", leeres_modell(), 0.2, True, (40, 60)), "einstieg_pruefen")
        self.assertEqual(aktion_aus_ki("einstieg_pruefen", leeres_modell(), 0.1, True, (61, 61)), "einstieg_pruefen")
        self.assertIn("noch keinen Handelstag", ki_satz(leeres_modell(), 0.9, (12, 12)))


if __name__ == "__main__":
    unittest.main()
