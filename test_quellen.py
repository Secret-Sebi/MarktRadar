"""Ersatzquellen, Suche und Watchlist. Keine echten Netzabrufe."""

import tempfile
import time
import unittest
from datetime import datetime, timedelta, timezone

_UTC = timezone.utc  # noqa: UP017
from pathlib import Path

from analyse import aktion_bei_datenstatus
from beobachter import haenge_an, lade_liste
from euro import _MAX_ALTER, nach_euro
from fundamental import aus_yahoo, text
from kurse import Bar, Kursdaten, _datenstatus, abweichung_prozent
from quellen import mit_fallback, plausibel
from quellen_coingecko import kurs_aus_gecko
from quellen_stooq import stooq_aus_csv, stooq_kuerzel
from suche import suche_aus_coingecko, suche_aus_yahoo


def _pence(waehrung="GBp", kurszeit=None, start=None, ende=None):
    erste = start or datetime.fromtimestamp(86400, _UTC)
    zweite = ende or datetime.fromtimestamp(172800, _UTC)

    def bar(moment):
        zeit = int(moment.timestamp()) if not isinstance(moment, int) else moment
        return Bar(zeit, 10000.0, 11000.0, 9000.0, 10000.0, 10000.0, 1.0)

    return Kursdaten(
        "HSBA.L",
        "HSBC",
        waehrung,
        10000.0,
        0.0,
        False,
        (10000.0, 10000.0),
        11000.0,
        9000.0,
        (bar(erste), bar(zweite)),
        kurszeit=kurszeit,
    )


def _reihe(start, ende, hoch=100.0, tief=100.0, kurszeit=None, zeitzone="UTC"):
    def bar(moment):
        return Bar(int(moment.timestamp()), 100.0, hoch, tief, 100.0, 100.0, 1.0)

    return Kursdaten(
        "AAPL",
        "Apple",
        "USD",
        100.0,
        0.0,
        False,
        (100.0, 100.0),
        110.0,
        70.0,
        (bar(start), bar(ende)),
        kurszeit=kurszeit,
        zeitzone=zeitzone,
    )


def _kurs(preis=10.0, status="ok"):
    return Kursdaten(
        "TEST",
        "Test",
        "EUR",
        preis,
        1.0,
        False,
        (9.0, preis),
        12.0,
        quelle="Test",
        datenstatus=status,
    )


class StooqTests(unittest.TestCase):
    def test_kuerzel(self):
        self.assertEqual(stooq_kuerzel("AAPL"), "aapl.us")
        self.assertEqual(stooq_kuerzel("SAP.DE"), "sap.de")
        self.assertEqual(stooq_kuerzel("^GSPC"), "^spx")
        self.assertIsNone(stooq_kuerzel("BTC-USD"))
        self.assertIsNone(stooq_kuerzel("^UNBEKANNT"))

    def test_csv_wird_schlusskurs(self):
        heute = datetime.now(timezone.utc).date()  # noqa: UP017
        erster = (heute - timedelta(days=2)).isoformat()
        zweiter = (heute - timedelta(days=1)).isoformat()
        text = f"Date,Open,High,Low,Close,Volume\n{erster},10,11,9,10.5,1000\n{zweiter},10.5,12,10,11,1100\n"
        daten = stooq_aus_csv("AAPL", text)
        self.assertEqual(daten.preis, 11.0)
        self.assertEqual(daten.quelle, "Stooq")
        self.assertEqual(daten.kursart, "schluss")
        self.assertEqual(daten.waehrung, "USD")
        self.assertEqual(daten.datenstatus, "unvollstaendig")
        self.assertEqual(len(daten.balken), 2)

    def test_html_ist_keine_kursdatei(self):
        self.assertIsNone(stooq_aus_csv("AAPL", "<html>Limit</html>"))


class GeckoTests(unittest.TestCase):
    def test_chart_und_preis(self):
        jetzt = int(time.time())
        preis = {"bitcoin": {"eur": 100.0, "eur_24h_change": 2.5, "last_updated_at": jetzt}}
        chart = {"prices": [[(jetzt - 86400) * 1000, 90.0], [jetzt * 1000, 100.0]]}
        daten = kurs_aus_gecko("BTC-USD", "Bitcoin", preis, chart)
        self.assertEqual(daten.preis, 100.0)
        self.assertEqual(daten.quelle, "CoinGecko")
        self.assertEqual(daten.waehrung, "EUR")
        self.assertAlmostEqual(daten.tag_pct, 2.5)
        self.assertEqual(daten.datenstatus, "unvollstaendig")

    def test_dollarpreis_wird_nicht_als_euro_beschriftet(self):
        preis = {"bitcoin": {"usd": 100.0, "usd_24h_change": 2.5, "last_updated_at": int(time.time())}}
        self.assertIsNone(kurs_aus_gecko("BTC-USD", "Bitcoin", preis, {"prices": []}))


class QualitaetTests(unittest.TestCase):
    def test_fehlender_zeitpunkt_ist_nicht_aktuell(self):
        jetzt = 1_700_000_000
        self.assertEqual(_datenstatus(None, jetzt), "unvollstaendig")
        self.assertEqual(_datenstatus(True, jetzt), "unvollstaendig")
        self.assertEqual(_datenstatus(jetzt + 3600, jetzt), "unvollstaendig")
        self.assertEqual(_datenstatus(jetzt - 3 * 24 * 3600, jetzt), "ok")
        self.assertEqual(_datenstatus(jetzt - 3 * 24 * 3600, jetzt, krypto=True), "veraltet")
        self.assertEqual(_datenstatus(jetzt - 11 * 24 * 3600, jetzt), "veraltet")

    def test_abweichung_braucht_zwei_echte_preise(self):
        self.assertAlmostEqual(abweichung_prozent(100, 101), 1.0)
        self.assertIsNone(abweichung_prozent(0, 10))
        self.assertIsNone(abweichung_prozent(True, 10))

    def test_fundamental_laesst_fehlende_felder_weg(self):
        roh = {
            "quoteSummary": {
                "result": [
                    {
                        "assetProfile": {"sector": "Technology"},
                        "summaryDetail": {"trailingPE": {"raw": 28.5}},
                        "financialData": {},
                    }
                ]
            }
        }
        branche, werte = aus_yahoo(roh)
        self.assertEqual(branche, "Technology")
        self.assertEqual(werte, {"KGV": 28.5})
        self.assertIn("Branche laut Yahoo: Technology", text(branche, werte))
        self.assertNotIn("Gewinnmarge", text(branche, werte))
        self.assertIn("Keine fundamentale Gesamtnote", text(branche, werte))
        self.assertIn("kein günstiger Einstieg", text("Technology", {"KGV": 12.0, "Gewinnmarge": -3.0, "Free Cashflow": 10.0, "Umsatzwachstum": 5.0, "Eigenkapitalrendite": 8.0}))
        self.assertIn("keine positive Bewertung", text("Financial Services", {"KGV": 8.0}))
        self.assertEqual(text("", {}), "fehlt")


class EuroTests(unittest.TestCase):
    def test_usd_wird_mit_wechselkurs_zu_euro(self):
        daten = Kursdaten(
            "AAPL",
            "Apple",
            "USD",
            100.0,
            1.5,
            False,
            (80.0, 100.0),
            110.0,
            70.0,
            (Bar(1, 90.0, 110.0, 80.0, 100.0, 100.0, 5.0),),
            hinweis="Yahoo.",
        )
        euro = nach_euro(daten, lambda code: 0.9 if code == "USD" else None)
        self.assertEqual(euro.waehrung, "USD")
        self.assertAlmostEqual(euro.preis, 100.0)
        self.assertAlmostEqual(euro.schluesse[-1], 100.0)
        self.assertAlmostEqual(euro.hoch_52w, 110.0)
        self.assertAlmostEqual(euro.balken[0].schluss, 100.0)
        self.assertIn("Ursprungswährung bleibt", euro.hinweis)
        self.assertAlmostEqual(euro.schluesse[-1] / euro.schluesse[0], 100.0 / 80.0)

    def test_historischer_wechselkurs_aendert_die_eurorendite(self):
        daten = Kursdaten(
            "AAPL",
            "Apple",
            "USD",
            100.0,
            0.0,
            False,
            (100.0, 100.0),
            100.0,
            100.0,
            (Bar(86400, 100.0, 100.0, 100.0, 100.0, 100.0, 1.0), Bar(172800, 100.0, 100.0, 100.0, 100.0, 100.0, 1.0)),
        )
        euro = nach_euro(daten, lambda code: ((86400, 0.8), (172800, 1.0)) if code == "USD" else ())
        self.assertEqual(euro.waehrung, "EUR")
        self.assertAlmostEqual(euro.balken[0].schluss, 80.0)
        self.assertAlmostEqual(euro.balken[1].schluss, 100.0)
        self.assertAlmostEqual(euro.tag_pct, 25.0)
        self.assertIn("jeweiligen Handelstags", euro.hinweis)

    def test_unvollstaendige_wechselkursreihe_bleibt_dollar(self):
        daten = Kursdaten(
            "AAPL",
            "Apple",
            "USD",
            100.0,
            None,
            False,
            (100.0, 100.0),
            100.0,
            (Bar(1, 100.0, 100.0, 100.0, 100.0, 100.0, 1.0), Bar(86400 * 10, 100.0, 100.0, 100.0, 100.0, 100.0, 1.0)),
        )
        euro = nach_euro(daten, lambda code: ((86400 * 10, 0.9), (86400 * 11, 0.9)))
        self.assertEqual(euro.waehrung, "USD")
        self.assertEqual(euro.preis, 100.0)

    def test_zu_alter_wechselkurs_wird_nicht_verwendet(self):
        start = datetime(2024, 1, 2, 21, tzinfo=_UTC)
        spaeter = start + timedelta(seconds=_MAX_ALTER + 86400 + 1)
        daten = _reihe(start, spaeter)
        euro = nach_euro(daten, lambda code: ((int(start.timestamp()), 0.8), (int(start.timestamp()) + 86400, 0.8)))
        self.assertEqual(euro.waehrung, "USD")
        self.assertNotIn("jeweiligen Handelstags", euro.hinweis)

    def test_mehrere_fehlende_tage_bleiben_dollar(self):
        start = datetime(2024, 1, 2, 21, tzinfo=_UTC)
        ende = start + timedelta(days=8)
        daten = _reihe(start, ende)
        euro = nach_euro(daten, lambda code: ((int(start.timestamp()), 0.9), (int(start.timestamp()) + 3600, 0.9)))
        self.assertEqual(euro.waehrung, "USD")
        self.assertEqual(euro.preis, 100.0)

    def test_wochenende_nutzt_den_freitagskurs(self):
        freitag = datetime(2024, 1, 5, 21, tzinfo=_UTC)
        montag = datetime(2024, 1, 8, 21, tzinfo=_UTC)
        daten = _reihe(freitag, montag, kurszeit=int(montag.timestamp()))
        euro = nach_euro(daten, lambda code: ((int(freitag.timestamp()), 0.8), (int(freitag.timestamp()) - 86400, 0.7)))
        self.assertEqual(euro.waehrung, "EUR")
        self.assertAlmostEqual(euro.balken[-1].schluss, 80.0)
        self.assertAlmostEqual(euro.preis, 80.0)

    def test_ein_feiertag_bleibt_innerhalb_von_vier_tagen(self):
        freitag = datetime(2024, 1, 5, 21, tzinfo=_UTC)
        dienstag = datetime(2024, 1, 9, 21, tzinfo=_UTC)
        daten = _reihe(freitag, dienstag, kurszeit=int(dienstag.timestamp()))
        euro = nach_euro(daten, lambda code: ((int(freitag.timestamp()), 0.5), (int(freitag.timestamp()) - 86400, 0.4)))
        self.assertEqual(euro.waehrung, "EUR")
        self.assertAlmostEqual(euro.preis, 50.0)

    def test_spaeterer_wechselkurs_am_gleichen_utc_tag_gilt_nicht(self):
        balken = datetime(2024, 1, 8, 1, tzinfo=_UTC)
        davor = datetime(2024, 1, 7, 22, tzinfo=_UTC)
        danach = datetime(2024, 1, 8, 5, tzinfo=_UTC)
        daten = _reihe(balken, balken + timedelta(days=1), kurszeit=int(balken.timestamp()), zeitzone="America/New_York")
        euro = nach_euro(
            daten,
            lambda code: ((int(davor.timestamp()), 0.5), (int(danach.timestamp()), 2.0), (int((balken + timedelta(days=1)).timestamp()), 0.5)),
        )
        self.assertEqual(euro.waehrung, "EUR")
        self.assertAlmostEqual(euro.balken[0].schluss, 50.0)

    def test_aktueller_kurs_ohne_tageskurs_bleibt_dollar(self):
        montag = datetime(2024, 1, 8, 21, tzinfo=_UTC)
        dienstag = datetime(2024, 1, 9, 15, tzinfo=_UTC)
        daten = _reihe(montag - timedelta(days=1), montag, kurszeit=int(dienstag.timestamp()))
        euro = nach_euro(
            daten,
            lambda code: ((int((montag - timedelta(days=1)).timestamp()), 0.8), (int(montag.timestamp()), 0.8)),
        )
        self.assertEqual(euro.waehrung, "USD")
        self.assertEqual(euro.preis, 100.0)
        self.assertIn("Kurszeitpunkt", euro.hinweis)

    def test_52_wochen_kommen_aus_der_umgerechneten_reihe(self):
        start = datetime(2023, 1, 2, 21, tzinfo=_UTC)
        ende = start + timedelta(days=400)
        daten = _reihe(start, ende, hoch=110.0, tief=70.0, kurszeit=int(ende.timestamp()))
        euro = nach_euro(daten, lambda code: ((int(start.timestamp()), 0.5), (int(ende.timestamp()), 2.0)))
        self.assertEqual(euro.waehrung, "EUR")
        self.assertAlmostEqual(euro.hoch_52w, 220.0)
        self.assertAlmostEqual(euro.tief_52w, 140.0)
        kurz = _reihe(start, start + timedelta(days=2), hoch=110.0, tief=70.0, kurszeit=int((start + timedelta(days=2)).timestamp()))
        ohne = nach_euro(kurz, lambda code: ((int(start.timestamp()), 2.0), (int((start + timedelta(days=2)).timestamp()), 2.0)))
        self.assertIsNone(ohne.hoch_52w)
        self.assertIsNone(ohne.tief_52w)
        self.assertIn("nicht verfügbar", ohne.hinweis)

    def test_ohne_wechselkurs_bleibt_dollar(self):
        daten = Kursdaten("AAPL", "Apple", "USD", 100.0, None, False, (100.0,), 100.0)
        euro = nach_euro(daten, lambda code: None)
        self.assertEqual(euro.waehrung, "USD")
        self.assertEqual(euro.preis, 100.0)

    def test_leere_waehrung_bleibt(self):
        daten = Kursdaten("X", "X", "", 5.0, None, False, (5.0,), 5.0)

        def verboten(code):
            raise AssertionError(code)

        self.assertEqual(nach_euro(daten, verboten).waehrung, "")
        def verboten(code):
            raise AssertionError(code)

        self.assertEqual(nach_euro(_kurs(), verboten).waehrung, "EUR")

    def test_pence_mit_historischer_reihe_werden_einmal_geteilt(self):
        euro = nach_euro(_pence(), lambda code: ((86400, 0.8), (172800, 1.0)))
        self.assertEqual(euro.waehrung, "EUR")
        self.assertAlmostEqual(euro.balken[0].schluss, 80.0)
        self.assertAlmostEqual(euro.balken[1].schluss, 100.0)
        self.assertAlmostEqual(euro.preis, 100.0)
        self.assertAlmostEqual(euro.tag_pct, 25.0)
        self.assertNotAlmostEqual(euro.preis, 1.0)

    def test_pence_mit_einem_tageskurs_bleiben_pfund(self):
        euro = nach_euro(_pence(), lambda code: 1.2)
        self.assertEqual(euro.waehrung, "GBP")
        self.assertAlmostEqual(euro.preis, 100.0)
        self.assertAlmostEqual(euro.balken[0].schluss, 100.0)
        self.assertIn("nicht Euro", euro.hinweis)

    def test_pence_ohne_wechselkurs_bleiben_pfund(self):
        for waehrung in ("GBp", "GBX"):
            euro = nach_euro(_pence(waehrung), lambda code: None)
            self.assertEqual(euro.waehrung, "GBP")
            self.assertAlmostEqual(euro.preis, 100.0)
            self.assertIn("nicht Euro", euro.hinweis)

    def test_unvollstaendige_pence_reihe_bleibt_pfund(self):
        daten = _pence()
        euro = nach_euro(daten, lambda code: ())
        self.assertEqual(euro.waehrung, "GBP")
        self.assertAlmostEqual(euro.preis, 100.0)
        einer = nach_euro(daten, lambda code: ((86400, 1.2),))
        self.assertEqual(einer.waehrung, "GBP")
        self.assertAlmostEqual(einer.preis, 100.0)
        falsch = nach_euro(daten, lambda code: ((True, 1.2), ("spaeter", 1.2)))
        self.assertEqual(falsch.waehrung, "GBP")
        self.assertAlmostEqual(falsch.balken[0].schluss, 100.0)

    def test_pence_ohne_passenden_tageskurs_bleiben_pfund(self):
        montag = datetime(2024, 1, 8, 21, tzinfo=_UTC)
        dienstag = datetime(2024, 1, 9, 15, tzinfo=_UTC)
        daten = _pence(kurszeit=int(dienstag.timestamp()), start=montag - timedelta(days=1), ende=montag)
        euro = nach_euro(
            daten,
            lambda code: ((int((montag - timedelta(days=1)).timestamp()), 0.8), (int(montag.timestamp()), 0.9)),
        )
        self.assertEqual(euro.waehrung, "GBP")
        self.assertAlmostEqual(euro.preis, 100.0)
        self.assertAlmostEqual(euro.balken[-1].schluss, 100.0)
        self.assertIn("Kurszeitpunkt", euro.hinweis)

    def test_hinweistext_stuft_pfund_nicht_als_pence_ein(self):
        from dataclasses import replace

        daten = replace(
            _reihe(datetime(2024, 1, 2, tzinfo=_UTC), datetime(2024, 1, 3, tzinfo=_UTC)),
            waehrung="GBP",
            hinweis="Pence wurden in Pfund umgerechnet.",
        )
        euro = nach_euro(daten, lambda code: 1.2)
        self.assertEqual(euro.waehrung, "GBP")
        self.assertIn("Ursprungswährung", euro.hinweis)

    def test_zukuenftiger_pence_kurs_wird_nicht_verwendet(self):
        euro = nach_euro(_pence(), lambda code: ((86400, 0.5), (172800 + 3600, 9.0), (172800, 1.0)))
        self.assertEqual(euro.waehrung, "EUR")
        self.assertAlmostEqual(euro.balken[0].schluss, 50.0)
        self.assertAlmostEqual(euro.balken[1].schluss, 100.0)
        self.assertNotAlmostEqual(euro.balken[1].schluss, 900.0)


class FallbackTests(unittest.TestCase):
    def test_krypto_fragt_zuerst_das_euro_paar(self):
        gesehen = []

        def yahoo(symbol, oeffnen):
            gesehen.append(symbol)
            return _kurs(50.0)

        def stopp(symbol, oeffnen):
            raise AssertionError(symbol)

        daten = mit_fallback("BTC-USD", None, yahoo=yahoo, stooq=stopp, gecko=stopp)
        self.assertEqual(gesehen, ["BTC-EUR"])
        self.assertEqual(daten.symbol, "BTC-USD")
        self.assertEqual(daten.preis, 50.0)

    def test_krypto_faellt_auf_gecko_zurueck(self):
        def yahoo(symbol, oeffnen):
            raise LookupError(symbol)

        gesehen = []

        def gecko(symbol, oeffnen):
            gesehen.append(symbol)
            return _kurs(40.0)

        daten = mit_fallback("BTC-USD", None, yahoo=yahoo, stooq=gecko, gecko=gecko)
        self.assertEqual(gesehen, ["BTC-USD"])
        self.assertEqual(daten.preis, 40.0)

    def test_yahoo_gewinnt(self):
        yahoo = _kurs()

        def stoq(symbol, oeffnen):
            raise AssertionError("Stooq darf nicht drankommen")

        daten = mit_fallback("SAP.DE", None, yahoo=lambda s, o: yahoo, stooq=stoq, gecko=stoq)
        self.assertEqual(daten.preis, 10.0)

    def test_stooq_nach_yahoo_fehler(self):
        ersatz = _kurs(12.0, "unvollstaendig")

        def yahoo(symbol, oeffnen):
            raise LookupError("Yahoo leer")

        daten = mit_fallback("SAP.DE", None, yahoo=yahoo, stooq=lambda s, o: ersatz, gecko=yahoo)
        self.assertEqual(daten.preis, 12.0)
        self.assertEqual(daten.quelle, "Test")

    def test_ungueltiges_kuerzel_fragt_keine_quelle(self):
        def verboten(symbol, oeffnen):
            raise AssertionError("Quelle wurde gefragt")

        with self.assertRaises(ValueError):
            mit_fallback("SAP.DE;rm", None, yahoo=verboten, stooq=verboten, gecko=verboten)

    def test_kein_erfundener_kurs(self):
        def leer(symbol, oeffnen):
            raise LookupError("leer")

        with self.assertRaises(LookupError):
            mit_fallback("SAP.DE", None, yahoo=leer, stooq=leer, gecko=leer)

    def test_unplausibler_preis_wird_verworfen(self):
        self.assertFalse(plausibel(_kurs(0)))
        self.assertFalse(plausibel(_kurs(float("nan"))))


class SucheTests(unittest.TestCase):
    def test_yahoo_liste(self):
        roh = {"quotes": [{"symbol": "SAP.DE", "shortname": "SAP SE", "quoteType": "EQUITY", "exchDisp": "XETRA"}]}
        treffer = suche_aus_yahoo(roh)
        self.assertEqual(treffer[0].symbol, "SAP.DE")
        self.assertEqual(treffer[0].quelle, "Yahoo Finance")

    def test_doppelter_coin_entfaellt(self):
        roh = {"coins": [
            {"symbol": "btc", "name": "Bitcoin"},
            {"symbol": "btc", "name": "Anderes Bitcoin"},
            {"symbol": "eth", "name": "Ethereum"},
        ]}
        symbole = tuple(treffer.symbol for treffer in suche_aus_coingecko(roh))
        self.assertEqual(symbole, ("ETH-USD",))


class ListeTests(unittest.TestCase):
    def test_anhaengen_behaelt_kommentare(self):
        with tempfile.TemporaryDirectory() as ordner:
            pfad = Path(ordner) / "watchlist.txt"
            pfad.write_text("# bleibt\nSAP.DE\n", encoding="utf-8")
            self.assertEqual(haenge_an(pfad, "AAPL"), "hinzugefuegt")
            self.assertEqual(haenge_an(pfad, "aapl"), "vorhanden")
            self.assertEqual(pfad.read_text(encoding="utf-8"), "# bleibt\nSAP.DE\nAAPL\n")

    def test_mehr_als_48_werte(self):
        with tempfile.TemporaryDirectory() as ordner:
            pfad = Path(ordner) / "watchlist.txt"
            pfad.write_text("\n".join(f"A{index}.DE" for index in range(49)), encoding="utf-8")
            self.assertEqual(len(lade_liste(pfad)), 49)

    def test_kein_einstieg_ohne_verlässliche_daten(self):
        self.assertEqual(aktion_bei_datenstatus("einstieg_pruefen", "veraltet"), "unvollstaendig")
        self.assertEqual(aktion_bei_datenstatus("sparplan", "unvollstaendig"), "unvollstaendig")
        self.assertEqual(aktion_bei_datenstatus("beobachten", "veraltet"), "beobachten")
        self.assertEqual(aktion_bei_datenstatus("einstieg_pruefen", "ok"), "einstieg_pruefen")


if __name__ == "__main__":
    unittest.main()
