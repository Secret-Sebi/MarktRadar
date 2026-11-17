import tempfile
import unittest
from pathlib import Path

from database import signal_speichern
from kurse import balken_bauen
from technik import (
    adx,
    atr,
    berechne,
    ema_letzter,
    macd,
    muster,
    relativ,
    trend_kreuzt,
    vergleichsindex,
    volatilitaet,
    vorzeichenwechsel,
    zonen,
)


class IndikatorTests(unittest.TestCase):
    def test_vergleichsindex_folgt_dem_markt(self):
        self.assertEqual(vergleichsindex("SAP.DE"), "^GDAXI")
        self.assertEqual(vergleichsindex("MC.PA"), "^FCHI")
        self.assertEqual(vergleichsindex("ETH-USD"), "BTC-USD")
        self.assertEqual(vergleichsindex("BTC-USD"), "")
        self.assertEqual(vergleichsindex("AAPL"), "^GSPC")
        self.assertEqual(vergleichsindex("NESN.SW"), "^SSMI")
        self.assertEqual(vergleichsindex("UNBEKANNT.ZZ"), "")

    def test_ema_letzter_folgt_der_formel(self):
        self.assertEqual(ema_letzter((1, 2, 3, 4, 5, 6), 3), 5.0)
        self.assertEqual(ema_letzter((4, 4, 4, 4), 3), 4.0)
        self.assertIsNone(ema_letzter((1, 2), 3))

    def test_macd_steigt_mit_dem_kurs(self):
        linie, signal, hist = macd(tuple(range(1, 80)))
        self.assertGreater(linie, 0)
        self.assertAlmostEqual(hist, linie - signal)

    def test_atr_erster_durchschnitt(self):
        wert = atr((10, 12, 11, 13), (8, 9, 9, 10), (9, 11, 10, 12), 3)
        self.assertAlmostEqual(wert, (3 + 2 + 3) / 3)

    def test_adx_trend_liegt_ueber_seitwaerts(self):
        flach_schluss = (10.0,) * 80
        trend_schluss = tuple(float(i) for i in range(1, 81))
        flach = adx(tuple(s + 1 for s in flach_schluss), tuple(s - 1 for s in flach_schluss), flach_schluss)
        trend = adx(tuple(s + 0.5 for s in trend_schluss), tuple(s - 0.5 for s in trend_schluss), trend_schluss)
        self.assertGreater(trend, flach)

    def test_volatilitaet_bei_ruhigem_kurs_ist_null(self):
        self.assertEqual(volatilitaet((10.0,) * 30), 0.0)

    def test_zonen_finden_schwung_hoch_und_tief(self):
        tiefs = (8, 8, 8, 1, 8, 8, 8, 8, 8, 8)
        hochs = (6, 6, 6, 2, 6, 6, 6, 12, 6, 6)
        stuetze, widerstand = zonen(hochs, tiefs, 7, 2)
        self.assertEqual(stuetze, 1)
        self.assertEqual(widerstand, 12)

    def test_relativ_gegen_unveraeenderten_index(self):
        self.assertAlmostEqual(relativ((100.0,) * 60 + (150.0,), (100.0,) * 61), 50.0)
        self.assertIsNone(relativ((100.0,) * 10, (100.0,) * 10))

    def test_muster_nennt_ruecksetzer_und_schwache(self):
        namen = muster(
            preis=120,
            sma50=110,
            sma200=100,
            rsi=42,
            rendite_1=-1,
            rendite_5=-3,
            rendite_20=-4,
            index_20=5,
            volumen=100,
            volumen_schnitt=100,
            bricht_widerstand_aus=False,
            kreuzt_trend=False,
        )
        self.assertIn("Rücksetzer im Aufwärtstrend", namen)
        self.assertIn("Schwach trotz steigendem Markt", namen)

    def test_vorzeichenwechsel_und_trendkreuz(self):
        self.assertTrue(vorzeichenwechsel(-1, 1))
        self.assertFalse(vorzeichenwechsel(1, 2))
        reihe = (100.0,) * 160 + (80.0,) * 40
        self.assertTrue(any(trend_kreuzt(reihe + (150.0,) * extra, 5) for extra in range(1, 80)))


class BalkenTests(unittest.TestCase):
    def test_live_kurs_ersetzt_nur_denselben_tag(self):
        balken = balken_bauen(
            (1_700_000_000, 1_700_086_400),
            (100, 110),
            (101, 112),
            (99, 108),
            (100, 110),
            (10, 11),
            (100, 110),
            111,
            1_700_086_400 + 1000,
            "UTC",
        )
        self.assertEqual(tuple(bar.schluss for bar in balken), (100, 111))

    def test_neuer_tag_haengt_an_und_behaelt_den_vortag(self):
        balken = balken_bauen(
            (1_700_000_000, 1_700_086_400),
            (100, 110),
            (101, 112),
            (99, 108),
            (100, 110),
            (10, 11),
            (90, 99),
            120,
            1_700_086_400 + 86_400,
            "UTC",
        )
        self.assertEqual(tuple(bar.schluss for bar in balken), (100, 110, 120))
        self.assertAlmostEqual(balken[-1].bereinigt, 120 * (99 / 110))

    def test_kurze_reihe_ist_unvollstaendig(self):
        from kurse import Bar

        balken = tuple(
            Bar(1_700_000_000 + i * 86_400, 10, 11, 9, 10, 10, 100) for i in range(30)
        )
        technik = berechne(balken, 10, None, True)
        self.assertFalse(technik.vollstaendig)
        self.assertIn("200 Handelstage", technik.fehlend)


class SpeicherTests(unittest.TestCase):
    def test_dieselbe_kategorie_am_selben_tag_nur_einmal(self):
        with tempfile.TemporaryDirectory() as ordner:
            pfad = Path(ordner) / "markt.sqlite"
            self.assertTrue(signal_speichern(pfad, "SAP.DE", "2026-11-14T14:00+01:00", "beobachten", 200, 40, "Grund", "{}"))
            self.assertFalse(signal_speichern(pfad, "SAP.DE", "2026-11-14T18:00+01:00", "beobachten", 201, 40, "Grund", "{}"))
            self.assertTrue(signal_speichern(pfad, "SAP.DE", "2026-11-14T19:00+01:00", "vorsicht", 190, 10, "Grund", "{}"))


if __name__ == "__main__":
    unittest.main()
