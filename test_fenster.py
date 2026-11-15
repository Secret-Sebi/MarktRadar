import json
import unittest
import urllib.request
from datetime import datetime
from unittest.mock import patch

from analyse import BERLIN, Urteil
from beobachter import Zeile, sammle
from fenster import mach_server
from kurse import Kursdaten, _wechselkurs
from seite import seite_html, stand_bauen


class FensterTests(unittest.TestCase):
    def test_seite_ist_dunkel_und_nennt_die_einschaetzung(self):
        html = seite_html()
        self.assertIn("#3dff9a", html)
        self.assertIn("function graph", html)
        self.assertIn("EINSCHÄTZUNG", html)
        self.assertNotIn("const klein = graph", html)
        self.assertIn("Suchen", html)
        self.assertIn("stand.status || \"Die Kurse kommen.\"", html)
        self.assertNotIn("tkinter", html)

    def test_stand_zeigt_namen_kurs_und_wochenende(self):
        urteil = Urteil(
            "beobachten",
            42,
            "Kein klarer Vorteil",
            "Der Kurs liegt ohne klaren Rücksetzer.",
            "In Trade Republic selbst prüfen.",
        )
        zeile = Zeile("SAP.DE", "SAP SE", "EUR", 213.45, 0.4, urteil, None)
        stand = stand_bauen((zeile,), datetime(2026, 11, 14, 15, 0, tzinfo=BERLIN), 900)
        self.assertIn("SAP", stand["briefing"])
        self.assertEqual(stand["pille"], "Wochenende")
        self.assertEqual(stand["karten"][0]["name"], "SAP")
        self.assertEqual(stand["karten"][0]["preis"], "213,45 EUR")
        self.assertEqual(stand["karten"][0]["richtung"], "hoch")
        self.assertIn("Trade Republic", stand["karten"][0]["extra"])
        self.assertEqual(stand["karten"][0]["stufe"], "offen")
        self.assertFalse(stand["karten"][0]["gelernt"])
        self.assertIn("noch nichts gelernt", stand["karten"][0]["text"])
        self.assertEqual(stand["karten"][0]["bereich"], "Deutschland")

    def test_kursreihe_behaelt_anfang_und_ende(self):
        from beobachter import _kursreihe

        reihe = _kursreihe(range(100), 5)
        self.assertEqual(reihe[0], 0)
        self.assertEqual(reihe[-1], 99)
        self.assertEqual(len(reihe), 5)
        zeile = Zeile(
            "SAP.DE",
            "SAP SE",
            "EUR",
            10,
            1,
            Urteil("sparplan", 70, "Eher Sparplan", "Rücksetzer.", "Prüfen."),
            None,
            reihe=reihe,
        )
        stand = stand_bauen((zeile,), datetime(2026, 11, 14, 15, 0, tzinfo=BERLIN), 900)
        self.assertNotIn("reihe", stand["karten"][0])
        self.assertFalse(stand["karten"][0]["gelernt"])

    def test_bereiche_trennen_krypto_usa_und_etf(self):
        from seite import bereich

        urteil = Urteil("beobachten", 40, "Kein klarer Vorteil", "Grund.", "Prüfen.")
        self.assertEqual(bereich(Zeile("BTC-USD", "Bitcoin", "USD", 1, 1, urteil, None)), "Krypto")
        self.assertEqual(bereich(Zeile("NVDA", "NVIDIA", "USD", 1, 1, urteil, None)), "USA")
        etf = Zeile("VWCE.DE", "VWCE", "EUR", 1, 1, urteil, _Etf())
        self.assertEqual(bereich(etf), "ETFs")

    def test_liste_nimmt_mehr_als_25_werte(self):
        import tempfile
        from pathlib import Path

        from beobachter import lade_liste

        with tempfile.TemporaryDirectory() as ordner:
            pfad = Path(ordner) / "watchlist.txt"
            pfad.write_text("\n".join(f"A{index}.DE" for index in range(30)), encoding="utf-8")
            self.assertEqual(len(lade_liste(pfad)), 30)

    def test_server_liefert_seite_und_stand(self):
        stand = stand_bauen((), datetime(2026, 11, 14, 15, 0, tzinfo=BERLIN), 900)
        server = mach_server(_Bild(stand))
        self.addCleanup(server.shutdown)
        self.addCleanup(server.server_close)
        basis = f"http://127.0.0.1:{server.server_address[1]}"
        with urllib.request.urlopen(basis, timeout=2) as antwort:
            seite = antwort.read().decode("utf-8")
        with urllib.request.urlopen(basis + "/stand", timeout=2) as antwort:
            gelesen = json.load(antwort)
        self.assertIn("MarktRadar", seite)
        self.assertEqual(gelesen["pille"], "Wochenende")

    def test_jede_zeile_kommt_sofort_ins_fenster(self):
        kurs = Kursdaten("SAP.DE", "SAP", "EUR", 10.0, 0.0, False, tuple(float(wert) for wert in range(1, 31)), 30.0)
        gesehen = []
        with patch("beobachter.hole_kurs", return_value=kurs), patch("beobachter.aktualisiere", side_effect=OSError), patch(
            "beobachter.trainiere", side_effect=OSError
        ), patch("beobachter.time.sleep"):
            sammle(("SAP.DE", "ALV.DE"), bei_zeile=gesehen.append)
        self.assertEqual([len(eintrag) for eintrag in gesehen], [1, 2])

    def test_wechselkurs_wird_nur_einmal_geholt(self):
        kurs = Kursdaten("USDEUR=X", "Euro", "EUR", 0.9, None, False, (0.9,), 0.9)
        speicher = {}
        with patch("kurse.yahoo_kurs", return_value=kurs) as yahoo:
            self.assertEqual(_wechselkurs("USD", None, speicher), 0.9)
            self.assertEqual(_wechselkurs("USD", None, speicher), 0.9)
        self.assertEqual(yahoo.call_count, 1)


class _Etf:
    ist_etf = True


class _Bild:
    def __init__(self, stand):
        self._stand = stand

    def lesen(self):
        return self._stand
