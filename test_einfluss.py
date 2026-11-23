"""Fehlende Einflussbereiche bleiben fehlend."""

import unittest

from einfluss import faktoren, luecken


class EinflussTests(unittest.TestCase):
    def test_fehlende_bereiche_werden_nicht_geschätzt(self):
        zeilen = faktoren({}, None)
        self.assertEqual([zeile["stand"] for zeile in zeilen], ["fehlt"] * 6)
        self.assertTrue(all(zeile["validiert"] is False for zeile in zeilen))
        self.assertNotIn("wahrscheinlichkeit", luecken())

    def test_widerspruch_wird_nicht_zu_einer_note(self):
        zeilen = {zeile["name"]: zeile for zeile in faktoren(
            {"fundamental": {"stand": "ok"}, "technik": {"stand": "ok"}, "historie": {"stand": "ok"}, "nachrichten": {"stand": "ok"}},
            {"ereignis": "quartal", "stimmung": "positiv", "zuordnung": "Keine eindeutige Zuordnung möglich."},
        )}
        self.assertEqual(zeilen["Nachrichten"]["stand"], "nicht_validiert")
        self.assertEqual(zeilen["Fundamental"]["stand"], "vorhanden")
        self.assertEqual(zeilen["Makro"]["stand"], "fehlt")
        self.assertIn("Keine Ursache", zeilen["Nachrichten"]["satz"])

    def test_quellenfehler_bleibt_fehler(self):
        zeilen = {zeile["name"]: zeile for zeile in faktoren({"nachrichten": {"stand": "fehler"}, "fundamental": {"stand": "fehler"}}, None)}
        self.assertEqual(zeilen["Nachrichten"]["stand"], "fehler")
        self.assertEqual(zeilen["Fundamental"]["stand"], "fehler")


if __name__ == "__main__":
    unittest.main()
