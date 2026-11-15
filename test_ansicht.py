import unittest

from ansicht import briefing, einzelheiten, kurzname, potenzial


class _Urteil:
    def __init__(self, aktion, broker="In Trade Republic selbst prüfen."):
        self.aktion = aktion
        self.hinweis_broker = broker


class _Zeile:
    def __init__(self, symbol, name, aktion):
        self.symbol = symbol
        self.name = name
        self.urteil = _Urteil(aktion)
        self.technik = None


class AnsichtTests(unittest.TestCase):
    def test_briefing_spricht_die_gruppen_aus(self):
        text = briefing(
            (
                _Zeile("ALV.DE", "Allianz SE", "abwarten"),
                _Zeile("BMW.DE", "Bayerische Motoren Werke Aktiengesellschaft", "vorsicht"),
                _Zeile("VWCE.DE", "Vanguard FTSE All-World UCITS ETF", "sparplan"),
            )
        )
        self.assertIn("3 Werte", text)
        self.assertIn("Einen klaren Einstiegsmoment sehe ich gerade nicht.", text)
        self.assertIn("Allianz", text)
        self.assertIn("BMW", text)
        self.assertIn("VWCE", text)
        self.assertNotIn("Aktiengesellschaft", text)

    def test_einstieg_wird_nicht_verneint(self):
        text = briefing((_Zeile("SAP.DE", "SAP SE", "einstieg_pruefen"),))
        self.assertIn("Zum Prüfen liegen SAP vorn.", text)
        self.assertNotIn("sehe ich gerade nicht", text)

    def test_leere_liste(self):
        self.assertIn("leer", briefing(()))

    def test_kurzname_etf_und_einzelheiten(self):
        zeile = _Zeile("SXR8.DE", "iShares Core S&P 500 UCITS ETF", "sparplan")
        self.assertEqual(kurzname(zeile), "SXR8")
        self.assertIn("Trade Republic", einzelheiten(zeile))

    def test_potenzial_fehlt_ohne_kurse_und_ist_hoch_beim_pruefen(self):
        offen = _Zeile("BMW.DE", "BMW", "unvollstaendig")
        offen.faelle = 4
        offen.urteil.score = 0
        self.assertIsNone(potenzial(offen)["score"])
        self.assertIn("fehlen vollständige Kurse", potenzial(offen)["text"])
        hoch = _Zeile("SAP.DE", "SAP", "einstieg_pruefen")
        hoch.faelle = 0
        hoch.urteil.score = 80
        hoch.urteil.grund = "Rücksetzer im Aufwärtstrend."
        ohne = potenzial(hoch)
        self.assertIsNone(ohne["score"])
        self.assertFalse(ohne["gelernt"])
        self.assertIn("noch nichts gelernt", ohne["text"])
        hoch.faelle = 2
        ergebnis = potenzial(hoch)
        self.assertEqual(ergebnis["stufe"], "hoch")
        self.assertEqual(ergebnis["score"], 80)
        self.assertTrue(ergebnis["gelernt"])
        self.assertIn("keine Gewinnzusage", ergebnis["text"])


if __name__ == "__main__":
    unittest.main()
