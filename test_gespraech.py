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
        self.assertIn("kein kurzes Fenster", text)
        self.assertIn("200 €", text)
        self.assertNotIn("999", text)

    def test_vorschlag_nutzt_nur_ein_bekanntes_fenster(self):
        karte = {**_SAP, "fenster": "Kurzes Fenster, die nächsten 1–3 Handelstage.", "datenstatus": "ok"}
        text = antwort("Was soll ich mit SAP machen?", {"karten": (karte,)})
        self.assertIn("Kurzes Fenster", text)
        self.assertIn("kein Auftrag", text)
        ohne = {
            **_SAP,
            "fenster": "",
            "pruefung": "Das reicht nicht für einen Vorschlag.",
            "folge": "Ausgewertete Folgetage zu diesem Namen: 2. Für eine Zahl brauche ich mindestens 8.",
            "datenstatus": "ok",
        }
        text_ohne = antwort("Was soll ich mit SAP machen?", {"karten": (ohne,)})
        self.assertIn("reicht nicht", text_ohne)
        self.assertIn("mindestens 8", text_ohne)
        self.assertNotIn("Vorschlag aus den eigenen Kursen", text_ohne)
        self.assertIn("noch nicht ausgewertet", antwort("Was soll ich mit Tesla machen?", {"karten": (_SAP,)}))
        mit_markt = {**_SAP, "datenstatus": "ok", "markt": "Der DAX ist heute um 1,4 % gefallen. Dieser Name geht mit dem Markt."}
        self.assertIn("geht mit dem Markt", antwort("Was soll ich mit SAP machen?", {"karten": (mit_markt,)}))

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

    def test_beste_ist_keine_empfehlung(self):
        text = antwort("zeig die besten", {"karten": (_SAP, _BMW)})
        self.assertIn("30 unabhängige", text)
        self.assertIn("erfinde keinen", text)
        self.assertNotIn("SAP", text)

    def test_verkauf_ist_keine_empfehlung(self):
        self.assertIn("noch nicht ausgewertet", antwort("soll ich verkaufen", {"karten": (_SAP, _BMW)}))

    def test_hallo_ist_ein_gespraech(self):
        text = antwort("Hallo!", {"karten": (_SAP,)})
        self.assertIn("Hey", text)
        self.assertNotIn("nicht geladen", text)
        wie = antwort("Hallo, wie geht's?", {"karten": (_SAP,)})
        self.assertIn("geht's gut", wie)
        self.assertNotIn("nicht geladen", wie)
        self.assertIn("Gern", antwort("danke", {"karten": (_SAP,)}))
        self.assertIn("Hey", antwort("Hallo", {"karten": ()}))
        self.assertNotIn("noch nicht da", antwort("Moin", {"karten": ()}))

    def test_gruss_mit_fuellwort_bleibt_gespraech(self):
        stand = {"karten": (_SAP,)}
        for satz in ("Wie geht's denn?", "Alles klar bei dir?", "Hallo zusammen", "Schönen guten Tag"):
            self.assertNotIn("nicht geladen", antwort(satz, stand), satz)
        self.assertIn("nicht geladen", antwort("Hallo Tesla", stand))

    def test_hallo_mit_namen_nennt_den_preis(self):
        text = antwort("Hallo, was kostet SAP?", {"karten": (_SAP, _BMW)})
        self.assertIn("Hey", text)
        self.assertIn("200 €", text)

    def test_leere_liste(self):
        self.assertIn("noch nicht da", antwort("SAP", {"karten": ()}))

    def test_prognosefrage_erfindet_keine_wahrscheinlichkeit(self):
        text = antwort("Was passiert wahrscheinlich mit NVIDIA in den nächsten 7 Tagen?", {"karten": (_SAP,)})
        self.assertIn("Noch keine zuverlässige Prognose", text)
        self.assertNotIn("%", text)

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
