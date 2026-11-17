"""Der Chat wiederholt nur gespeicherte Angaben."""

import json
import unittest
import urllib.request

from fenster import _Bild, mach_server
from gespraech import antwort

_SAP = {
    "symbol": "SAP.DE",
    "name": "SAP",
    "preis": "200 €",
    "wert": 200.0,
    "tag": "+1 %",
    "tag_wert": 1.0,
    "titel": "Beobachten",
    "aktion": "beobachten",
    "gelernt": False,
    "text": "Zu dieser Aktie habe ich noch nichts gelernt.",
    "extra": "Quelle: Yahoo",
}
_BMW = {
    "symbol": "BMW.DE",
    "name": "BMW",
    "preis": "80 €",
    "wert": 80.0,
    "tag": "-2 %",
    "tag_wert": -2.0,
    "titel": "Verkauf prüfen",
    "aktion": "verkauf_pruefen",
    "gelernt": True,
    "text": "Aus gespeicherten Fällen.",
    "extra": "",
}


class GespraechTests(unittest.TestCase):
    def test_nennt_den_gespeicherten_preis(self):
        text = antwort("Was weißt du über SAP?", {"karten": (_SAP, _BMW)})
        self.assertIn("200 €", text)
        self.assertIn("Trade Republic", text)

    def test_kaufhinweis_ist_kein_auftrag(self):
        text = antwort("Soll ich SAP kaufen?", {"karten": (_SAP, _BMW)})
        self.assertIn("kein Auftrag", text)

    def test_erfindet_keinen_preis(self):
        text = antwort("Tesla kostet genau 999 Euro", {"karten": (_SAP,)})
        self.assertNotIn("999", text)
        self.assertIn("nicht geladen", text)

    def test_tagesbewegung_ist_nicht_der_kurs(self):
        solana = {
            "symbol": "SOL-USD",
            "name": "Solana EUR",
            "preis": "65,81 EUR",
            "wert": 65.81,
            "tag": "-2,1 %",
            "tag_wert": -2.1,
            "titel": "Kein klarer Vorteil",
            "aktion": "beobachten",
        }
        text = antwort("ist die solana aktie nicht 1,40 euro oder so", {"karten": (solana,)})
        self.assertIn("65,81 EUR", text)
        self.assertIn("nicht", text)
        self.assertIn("gefallen", text)
        self.assertIn("Krypto", text)

    def test_beste_ist_der_erste_name(self):
        text = antwort("zeig die besten", {"karten": (_SAP, _BMW)})
        self.assertTrue(text.startswith("Ganz vorn sehe ich gerade SAP"))

    def test_verkauf_nur_wenn_gesetzt(self):
        self.assertIn("BMW", antwort("soll ich verkaufen", {"karten": (_SAP, _BMW)}))
        self.assertIn("nicht", antwort("verkaufen", {"karten": (_SAP,)}).lower())

    def test_leere_liste(self):
        self.assertIn("noch nicht da", antwort("SAP", {"karten": ()}))

    def test_server_antwortet(self):
        server = mach_server(_Bild({"karten": (_SAP,)}))
        self.addCleanup(server.shutdown)
        self.addCleanup(server.server_close)
        adresse = f"http://127.0.0.1:{server.server_address[1]}/frage"
        roh = json.dumps({"text": "SAP"}).encode("utf-8")
        anfrage = urllib.request.Request(adresse, data=roh, headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(anfrage, timeout=2) as gelesen:
            antwort_json = json.load(gelesen)
        self.assertIn("200 €", antwort_json["antwort"])
