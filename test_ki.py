"""Das Modell ändert seine Gewichte nur an abgeschlossenen Fällen."""

import json
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


def _uhr(pfad: Path) -> None:
    """Die Testuhr ist die Meldungszeit. Der automatische Speicherstempel liegt sonst in der Gegenwart."""
    with sqlite3.connect(pfad) as verbindung:
        verbindung.execute("UPDATE nachrichten SET erfasst = zeit")


def _kursreihe(start: float, schritte: int):
    from kurse import mit_ende

    return tuple(
        mit_ende(Bar(index * 100, None, None, None, start + index, start + index, None), index * 100)
        for index in range(1, schritte + 1)
    )


class ModellTests(unittest.TestCase):
    def test_unbelegte_reihe_bewegt_die_gewichte_nicht(self):
        with tempfile.TemporaryDirectory() as ordner:
            pfad = Path(ordner) / "markt.sqlite"
            balken = tuple(Bar(index * 100, None, None, None, 10 + index, 10 + index, None) for index in range(1, 41))
            speichern(pfad, "SAP.DE", aus_yahoo({"news": [{"title": "EZB hebt die Zinsen", "link": "https://beispiel.test/ohne-ende", "publisher": "Reuters", "providerPublishTime": 2500}]}))
            _uhr(pfad)
            nachtragen(pfad, "SAP.DE", balken)
            modell = trainiere(pfad, "SAP.DE", balken, pruefen=False)
            self.assertEqual(modell.beispiele, 0)
            with sqlite3.connect(pfad) as verbindung:
                zeile = verbindung.execute("SELECT status, zeitlich FROM ki_beispiel WHERE horizont = 1").fetchone()
            self.assertEqual(zeile[0], "ausgeschlossen")
            self.assertEqual(zeile[1], "unbewiesen")

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
            _uhr(pfad)
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
            _uhr(pfad)
            nachtragen(pfad, "SAP.DE", balken)
            dritter = trainiere(pfad, "SAP.DE", balken, pruefen=False)
            self.assertGreater(dritter.beispiele, erster.beispiele)
            vierter = trainiere(pfad, "SAP.DE", balken, pruefen=False)
            self.assertEqual(vierter.beispiele, dritter.beispiele)
            self.assertEqual(lies_modell(pfad).beispiele, 0)
            with sqlite3.connect(pfad) as verbindung:
                status = [zeile[0] for zeile in verbindung.execute(
                    "SELECT status FROM ki_beispiel WHERE horizont = 1 ORDER BY nachricht_id"
                )]
            self.assertTrue(status)
            self.assertTrue(all(wert == "trainiert" for wert in status))

    def test_ueberlappende_meldung_wird_nicht_doppelt_trainiert(self):
        with tempfile.TemporaryDirectory() as ordner:
            pfad = Path(ordner) / "markt.sqlite"
            balken = _kursreihe(10, 40)
            speichern(
                pfad,
                "SAP.DE",
                aus_yahoo(
                    {
                        "news": [
                            {"title": "Quartalszahlen enttäuschen", "link": "https://beispiel.test/a", "publisher": "Reuters", "providerPublishTime": 2401},
                            {"title": "Übernahme wird gemeldet", "link": "https://beispiel.test/b", "publisher": "Reuters", "providerPublishTime": 2450},
                        ]
                }
            ),
            )
            _uhr(pfad)
            nachtragen(pfad, "SAP.DE", balken)
            trainiere(pfad, "SAP.DE", balken, pruefen=False)
            with sqlite3.connect(pfad) as verbindung:
                zeilen = verbindung.execute(
                    "SELECT status, grund FROM ki_beispiel WHERE horizont = 1 ORDER BY nachricht_id"
                ).fetchall()
            self.assertEqual(zeilen[0][0], "trainiert")
            self.assertEqual(zeilen[1][0], "ausgeschlossen")
            self.assertIn("überlappt", zeilen[1][1])

    def test_alte_tagessperre_wird_nur_ohne_ueberlappung_nachgeholt(self):
        with tempfile.TemporaryDirectory() as ordner:
            pfad = Path(ordner) / "markt.sqlite"
            balken = _kursreihe(10, 40)
            speichern(pfad, "SAP.DE", aus_yahoo({"news": [{"title": "EZB hebt die Zinsen", "link": "https://beispiel.test/alt", "publisher": "Reuters", "providerPublishTime": 2500}]}))
            _uhr(pfad)
            nachtragen(pfad, "SAP.DE", balken)
            trainiere(pfad, "SAP.DE", balken, pruefen=False)
            speichern(pfad, "SAP.DE", aus_yahoo({"news": [{"title": "Firma meldet Übernahme", "link": "https://beispiel.test/spaet", "publisher": "Reuters", "providerPublishTime": 3600}]}))
            _uhr(pfad)
            nachtragen(pfad, "SAP.DE", balken)
            with sqlite3.connect(pfad) as verbindung:
                nummer = verbindung.execute("SELECT id FROM nachrichten WHERE zeit = 3600").fetchone()[0]
                verbindung.execute(
                    """
                    INSERT INTO ki_beispiel (nachricht_id, horizont, status, grund, ziel, merkmale, zeit, erfasst)
                    VALUES (?, 1, 'ausgeschlossen', 'Gleicher Kalendertag, erstes Beispiel zählt', NULL, NULL, 3600, 1)
                    """,
                    (nummer,),
                )
            vorher = trainiere(pfad, "SAP.DE", balken, pruefen=False).beispiele
            nochmal = trainiere(pfad, "SAP.DE", balken, pruefen=False).beispiele
            self.assertEqual(nochmal, vorher)
            with sqlite3.connect(pfad) as verbindung:
                status = verbindung.execute(
                    "SELECT status FROM ki_beispiel WHERE nachricht_id = ? AND horizont = 1",
                    (nummer,),
                ).fetchone()[0]
            self.assertEqual(status, "trainiert")

    def test_gemessene_pruefung_bleibt_bei_zu_wenigen_zielzeiten(self):
        from ki import _tabellen, _validiere_wenn_faellig

        with tempfile.TemporaryDirectory() as ordner:
            pfad = Path(ordner) / "markt.sqlite"
            with sqlite3.connect(pfad) as verbindung:
                _tabellen(verbindung)
                verbindung.execute(
                    "INSERT INTO ki_horizont (horizont, gewichte, bias, beispiele, validiert, pruefung) VALUES (1, '[]', 0, 1, 0, ?)",
                    ('{"bestanden": false, "grund": "Validierung schlägt die Basisrate nicht", "brier": 0.268, "basis_brier": 0.245, "n": 109}',),
                )
                verbindung.execute(
                    """
                    INSERT INTO ki_beispiel (nachricht_id, horizont, status, grund, ziel, merkmale, zeit, ziel_von, ziel_bis)
                    VALUES (1, 1, 'trainiert', 'x', 1, '[0,0,0,0,0,0,0.4,1]', 10, 10, 20)
                    """
                )
            _validiere_wenn_faellig(pfad)
            with sqlite3.connect(pfad) as verbindung:
                text = verbindung.execute("SELECT pruefung, validiert FROM ki_horizont WHERE horizont = 1").fetchone()
            bericht = json.loads(text[0])
            self.assertEqual(text[1], 0)
            self.assertFalse(bericht["bestanden"])
            self.assertEqual(bericht["brier"], 0.268)
            self.assertEqual(bericht["basis_brier"], 0.245)

    def test_gespeicherte_kurse_fuellen_die_zielzeit_ohne_zweites_training(self):
        from lernen import kurse_merken

        with tempfile.TemporaryDirectory() as ordner:
            pfad = Path(ordner) / "markt.sqlite"
            balken = _kursreihe(10, 40)
            speichern(pfad, "SAP.DE", aus_yahoo({"news": [{"title": "EZB hebt die Zinsen", "link": "https://beispiel.test/reihe", "publisher": "Reuters", "providerPublishTime": 2500}]}))
            _uhr(pfad)
            nachtragen(pfad, "SAP.DE", balken)
            kurse_merken(pfad, "SAP.DE", balken)
            erster = trainiere(pfad, "SAP.DE", balken, pruefen=False)
            with sqlite3.connect(pfad) as verbindung:
                verbindung.execute("UPDATE ki_beispiel SET ziel_von = NULL, ziel_bis = NULL")
            zweiter = trainiere(pfad, "SAP.DE", _kursreihe(10, 5), pruefen=False)
            self.assertEqual(zweiter.beispiele, erster.beispiele)
            with sqlite3.connect(pfad) as verbindung:
                fenster = verbindung.execute(
                    "SELECT ziel_von, ziel_bis FROM ki_beispiel WHERE status = 'trainiert' AND horizont = 1"
                ).fetchone()
            self.assertIsNotNone(fenster[0])
            self.assertGreater(fenster[1], fenster[0])

    def test_fehlende_zielzeit_wird_nachgetragen_ohne_zweites_training(self):
        with tempfile.TemporaryDirectory() as ordner:
            pfad = Path(ordner) / "markt.sqlite"
            balken = _kursreihe(10, 40)
            speichern(pfad, "SAP.DE", aus_yahoo({"news": [{"title": "EZB hebt die Zinsen", "link": "https://beispiel.test/zielzeit", "publisher": "Reuters", "providerPublishTime": 2500}]}))
            _uhr(pfad)
            nachtragen(pfad, "SAP.DE", balken)
            erster = trainiere(pfad, "SAP.DE", balken, pruefen=False)
            with sqlite3.connect(pfad) as verbindung:
                vorher = verbindung.execute("SELECT COUNT(*) FROM ki_beispiel").fetchone()[0]
                verbindung.execute("UPDATE ki_beispiel SET ziel_von = NULL, ziel_bis = NULL WHERE status = 'trainiert'")
            zweiter = trainiere(pfad, "SAP.DE", balken, pruefen=False)
            self.assertEqual(zweiter.beispiele, erster.beispiele)
            with sqlite3.connect(pfad) as verbindung:
                self.assertEqual(verbindung.execute("SELECT COUNT(*) FROM ki_beispiel").fetchone()[0], vorher)
                zeiten = verbindung.execute(
                    "SELECT ziel_von, ziel_bis FROM ki_beispiel WHERE status = 'trainiert'"
                ).fetchall()
            self.assertTrue(zeiten)
            self.assertTrue(all(von is not None and bis is not None and bis > von for von, bis in zeiten))

    def test_vollstaendige_zielzeit_und_fehlende_rekonstruktion_bleiben_unveraendert(self):
        with tempfile.TemporaryDirectory() as ordner:
            pfad = Path(ordner) / "markt.sqlite"
            balken = _kursreihe(10, 40)
            speichern(pfad, "SAP.DE", aus_yahoo({"news": [{"title": "EZB hebt die Zinsen", "link": "https://beispiel.test/zielzeit-fest", "publisher": "Reuters", "providerPublishTime": 2500}]}))
            _uhr(pfad)
            nachtragen(pfad, "SAP.DE", balken)
            trainiere(pfad, "SAP.DE", balken, pruefen=False)
            with sqlite3.connect(pfad) as verbindung:
                verbindung.execute("UPDATE ki_beispiel SET ziel_von = 11, ziel_bis = 22")
                anzahl = verbindung.execute("SELECT COUNT(*) FROM ki_beispiel").fetchone()[0]
            trainiere(pfad, "SAP.DE", balken, pruefen=False)
            with sqlite3.connect(pfad) as verbindung:
                self.assertEqual(
                    verbindung.execute("SELECT COUNT(*), MIN(ziel_von), MAX(ziel_bis) FROM ki_beispiel").fetchone(),
                    (anzahl, 11, 22),
                )
                verbindung.execute("UPDATE ki_beispiel SET ziel_von = NULL, ziel_bis = NULL WHERE status = 'trainiert'")
            trainiere(pfad, "SAP.DE", _kursreihe(10, 5), pruefen=False)
            with sqlite3.connect(pfad) as verbindung:
                leer = verbindung.execute(
                    "SELECT COUNT(*) FROM ki_beispiel WHERE status = 'trainiert' AND ziel_von IS NULL AND ziel_bis IS NULL"
                ).fetchone()[0]
                self.assertEqual(verbindung.execute("SELECT COUNT(*) FROM ki_beispiel").fetchone()[0], anzahl)
            self.assertGreater(leer, 0)

    def test_modell_entscheidet_selbst_und_lernt_den_ausgang_einmal(self):
        balken = _kursreihe(10, 30)
        leer = leeres_modell()
        self.assertFalse(eigene_entscheidung(leer, balken, "zinsen")[0])
        self.assertIn("noch nicht", eigene_entscheidung(leer, balken, "zinsen")[1])
        moment = balken[-1].zeit
        eingabe = merkmale(balken, moment, "zinsen")
        modell = leer
        for _ in range(12):
            modell = schritt(modell, eingabe, 1.0)
        kauf, satz = eigene_entscheidung(modell, balken, "zinsen", moment)
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
