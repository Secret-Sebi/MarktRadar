import unittest
from datetime import datetime
from zoneinfo import ZoneInfo

from analyse import (
    Kennzahlen,
    abstand_prozent,
    fenster,
    handels_hinweis,
    kennzahlen_aus_schluessen,
    rsi,
    sma,
    soll_melden,
    urteilen,
)
from beobachter import Zeile, bildschirm, zustand_nach_runde
from kurse import gueltiges_symbol, kurse_aus_antwort

BERLIN = ZoneInfo("Europe/Berlin")


def k(**werte):
    basis = dict(  # noqa: C408
        preis=100.0,
        sma20=100.0,
        sma50=100.0,
        sma200=100.0,
        rsi=50.0,
        hoch_52w=110.0,
        aenderung_5t_pct=0.0,
        aenderung_20t_pct=0.0,
        ist_etf=False,
        anzahl_kurse=220,
    )
    basis.update(werte)
    return Kennzahlen(**basis)


class AnalyseTests(unittest.TestCase):
    def test_sma_nutzt_nur_das_fenster_am_ende(self):
        self.assertEqual(sma((1, 2, 3, 4), 2), 3.5)
        self.assertIsNone(sma((1, 2), 3))

    def test_rsi_bei_reinem_anstieg_und_fall(self):
        self.assertEqual(rsi(tuple(range(1, 40))), 100.0)
        self.assertEqual(rsi(tuple(range(40, 0, -1))), 0.0)
        self.assertEqual(rsi(tuple([20.0] * 30)), 50.0)

    def test_ruecksetzer_im_aufwaertstrend_wird_pruefen(self):
        urteil = urteilen(
            k(
                preis=120,
                sma20=125,
                sma50=110,
                sma200=100,
                rsi=42,
                hoch_52w=130,
                aenderung_5t_pct=-3,
            )
        )
        self.assertEqual(urteil.aktion, "einstieg_pruefen")
        self.assertEqual(urteil.score, 92)
        self.assertIn("Rücksetzer", urteil.grund)
        self.assertIn("Limit-Order", urteil.hinweis_broker)

    def test_hoher_rsi_heisst_nicht_hinterherlaufen(self):
        urteil = urteilen(k(preis=130, sma20=120, sma50=110, sma200=100, rsi=74, hoch_52w=132, aenderung_5t_pct=2))
        self.assertEqual(urteil.aktion, "abwarten")
        self.assertEqual(urteil.score, 24)

    def test_abwaertstrend_ist_kein_einstieg(self):
        urteil = urteilen(k(preis=80, sma20=90, sma50=95, sma200=110, rsi=45, hoch_52w=120, aenderung_5t_pct=-1))
        self.assertEqual(urteil.aktion, "vorsicht")
        self.assertIn("200-Tage-Linie", urteil.grund)

    def test_etf_ohne_klaren_ruecksetzer_bleibt_sparplan(self):
        urteil = urteilen(
            k(preis=150, sma20=148, sma50=140, sma200=120, rsi=55, hoch_52w=155, aenderung_5t_pct=0.4, ist_etf=True)
        )
        self.assertEqual(urteil.aktion, "sparplan")
        self.assertIn("Sparplan", urteil.grund)

    def test_etf_ruecksetzer_nennt_sparplan_und_limit(self):
        urteil = urteilen(
            k(preis=120, sma20=125, sma50=110, sma200=100, rsi=40, hoch_52w=140, aenderung_5t_pct=-4, ist_etf=True)
        )
        self.assertEqual(urteil.aktion, "einstieg_pruefen")
        self.assertIn("Sparplan", urteil.hinweis_broker)

    def test_unklar_bei_wenigen_tagen(self):
        urteil = urteilen(k(anzahl_kurse=10, sma50=None, sma200=None, rsi=None))
        self.assertEqual(urteil.aktion, "unklar")

    def test_mittlerer_wert_bleibt_beobachten(self):
        urteil = urteilen(k(preis=105, sma20=104, sma50=100, sma200=102, rsi=58, hoch_52w=110, aenderung_5t_pct=0.5))
        self.assertEqual(urteil.aktion, "beobachten")
        self.assertEqual(urteil.score, 28)

    def test_kennzahl_aus_reihe(self):
        werte = tuple(float(i) for i in range(1, 221))
        zahlen = kennzahlen_aus_schluessen(werte, False, None)
        self.assertEqual(zahlen.preis, 220.0)
        self.assertIsNotNone(zahlen.sma200)
        self.assertEqual(zahlen.rsi, 100.0)
        self.assertAlmostEqual(abstand_prozent(120, 100), 20.0)

    def test_fenster_berlin(self):
        self.assertEqual(fenster(datetime(2026, 11, 14, 14, 0, tzinfo=BERLIN)), "wochenende")
        self.assertEqual(fenster(datetime(2026, 11, 11, 10, 0, tzinfo=BERLIN)), "xetra")
        self.assertEqual(fenster(datetime(2026, 11, 11, 20, 0, tzinfo=BERLIN)), "bestpreis")
        self.assertEqual(fenster(datetime(2026, 11, 11, 6, 0, tzinfo=BERLIN)), "zu")
        self.assertEqual(fenster(datetime(2026, 11, 11, 17, 30, tzinfo=BERLIN)), "bestpreis")

    def test_erste_sichtung_meldet_nicht(self):
        self.assertFalse(soll_melden(None, "einstieg_pruefen"))
        self.assertFalse(soll_melden("beobachten", "beobachten"))
        self.assertTrue(soll_melden("beobachten", "einstieg_pruefen"))
        self.assertFalse(soll_melden("einstieg_pruefen", "einstieg_pruefen"))


class ProgrammTests(unittest.TestCase):
    def test_wochenende_text_und_erste_runde_ohne_meldung(self):
        self.assertIn("Wochenende", handels_hinweis(datetime(2026, 11, 14, 14, 0, tzinfo=BERLIN)))
        urteil = urteilen(k(preis=120, sma20=125, sma50=110, sma200=100, rsi=42, hoch_52w=130, aenderung_5t_pct=-3))
        zeile = Zeile("SAP.DE", "SAP SE", "EUR", 120.0, -1.0, urteil, None)
        zustand, meldungen = zustand_nach_runde({"symbole": {}}, (zeile,), "2026-11-14T14:00")
        self.assertEqual(meldungen, ())
        self.assertEqual(zustand["symbole"]["SAP.DE"]["aktion"], "einstieg_pruefen")
        _, spaeter = zustand_nach_runde(
            {"symbole": {"SAP.DE": {"aktion": "beobachten", "seit": "früher"}}},
            (zeile,),
            "2026-11-14T15:00",
        )
        self.assertEqual(spaeter[0].symbol, "SAP.DE")
        text = bildschirm((zeile,), datetime(2026, 11, 14, 14, 0, tzinfo=BERLIN), 900, False)
        self.assertIn("PRÜFEN", text)
        self.assertIn("SAP.DE", text)
        self.assertIn("Keine Anlageberatung", text)


class KursTests(unittest.TestCase):
    def test_symbol(self):
        self.assertTrue(gueltiges_symbol("SAP.DE"))
        self.assertTrue(gueltiges_symbol("^GDAXI"))
        self.assertFalse(gueltiges_symbol("SAP.DE;rm"))
        self.assertFalse(gueltiges_symbol(""))

    def test_yahoo_antwort(self):
        payload = {
            "chart": {
                "result": [
                    {
                        "meta": {
                            "symbol": "SAP.DE",
                            "longName": "SAP SE",
                            "shortName": "SAP SE                        I",
                            "currency": "EUR",
                            "regularMarketPrice": 200.0,
                            "chartPreviousClose": 190.0,
                            "instrumentType": "EQUITY",
                            "fiftyTwoWeekHigh": 220.0,
                        },
                        "indicators": {"quote": [{"close": [None, 180.0, 190.0, 195.0]}]},
                    }
                ],
                "error": None,
            }
        }
        daten = kurse_aus_antwort(payload)
        self.assertEqual(daten.name, "SAP SE")
        self.assertEqual(daten.schluesse[-1], 200.0)
        self.assertAlmostEqual(daten.tag_pct, (200 / 190 - 1) * 100)
        self.assertFalse(daten.ist_etf)

    def test_tag_prozent_nimmt_nicht_den_chartanfang(self):
        payload = {
            "chart": {
                "result": [
                    {
                        "meta": {
                            "symbol": "VWCE.DE",
                            "longName": "Vanguard FTSE All-World",
                            "currency": "EUR",
                            "regularMarketPrice": 169.86,
                            "regularMarketChangePercent": -0.91,
                            "chartPreviousClose": 133.04,
                            "instrumentType": "ETF",
                            "fiftyTwoWeekHigh": 180.0,
                        },
                        "indicators": {"quote": [{"close": [133.0, 171.42, 169.86]}]},
                    }
                ],
                "error": None,
            }
        }
        daten = kurse_aus_antwort(payload)
        self.assertAlmostEqual(daten.tag_pct, -0.91)

    def test_yahoo_fehler(self):
        self.assertIsNone(kurse_aus_antwort({"chart": {"result": None, "error": {"description": "x"}}}))


if __name__ == "__main__":
    unittest.main()
