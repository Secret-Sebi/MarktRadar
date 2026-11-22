"""Die große Liste wird gemessen, ruhige Namen bleiben unsichtbar."""

import os
import tempfile
import time
import unittest
from pathlib import Path

from analyse import ist_wichtig
from auswertung import (
    alle,
    chancen_nachtragen,
    faellig,
    merken,
    mess_runde,
    pause_bei_luecke,
    runde_groesse,
    runde_symbole,
    sende_hinweise,
    sichtbar,
)
from universum import (
    abdeckung,
    lade_universum,
    naechste,
    parse_csv,
    parse_mdax,
    parse_wiki_de,
    parse_wiki_us,
)

_CSV = "Symbol,Security\nAAPL,Apple\nBRK.B,Berkshire\n"
_DAX = '|ADS|| Sportartikel\n|1987|| Jahr\n|[[SAP]]||'


class UniversumTests(unittest.TestCase):
    def test_parse_nimmt_kuerzel_und_laesst_jahre_weg(self):
        self.assertEqual(parse_csv(_CSV), ("AAPL", "BRK.B"))
        self.assertEqual(parse_wiki_de(_DAX), ("ADS.DE",))
        self.assertEqual(parse_wiki_us("<td>AAPL</td><td><a href=\"x\">Apple</a></td>"), ())
        zellen = "".join(
            f"<td>{chr(65 + index // 26)}{chr(65 + index % 26)}X</td><td><a href=\"x\">Name</a></td>"
            for index in range(90)
        )
        self.assertEqual(len(parse_wiki_us(zellen)), 90)
        self.assertEqual(parse_mdax("<td>AIXA</td></tr>"), ())
        mdax = "".join(f"<td>{chr(65 + index // 26)}{chr(65 + index % 26)}M</td></tr>" for index in range(40))
        self.assertEqual(parse_mdax(mdax)[0], "AAM.DE")
        self.assertEqual(len(parse_mdax(mdax)), 40)

    def test_abdeckung_liest_gespeicherte_zahlen_und_erfindet_keine(self):
        with tempfile.TemporaryDirectory() as ordner:
            cache = Path(ordner) / "universum.txt"
            cache.write_text("# liquide\n# zahl DAX 10\n# fehlt Nasdaq 100\nAAPL\nAAPL\n", encoding="utf-8")
            bild = abdeckung(cache)
        self.assertEqual(bild["symbole"], 2)
        self.assertEqual(bild["eindeutig"], 1)
        self.assertEqual(bild["indizes"]["DAX"], 10)
        self.assertIn("unvollständig", bild["hinweis"])
        self.assertIn("Nasdaq 100", bild["hinweis"])

    def test_naechste_laeuft_rund(self):
        teil, cursor = naechste(("A", "B", "C"), 2, 2)
        self.assertEqual(teil, ("C", "A"))
        self.assertEqual(cursor, 1)

    def test_frischer_cache_geht_nicht_ins_netz(self):
        with tempfile.TemporaryDirectory() as ordner:
            cache = Path(ordner) / "universum.txt"
            cache.write_text("# liquide\nAAPL\n", encoding="utf-8")
            symbole, hinweis = lade_universum(("SAP.DE",), cache, oeffnen=self._verboten, jetzt=int(time.time()))
        self.assertEqual(symbole, ("SAP.DE", "AAPL"))
        self.assertIn("DAX", hinweis)

    def test_fehlende_liste_wird_nach_sechs_stunden_neu_geholt(self):
        with tempfile.TemporaryDirectory() as ordner:
            cache = Path(ordner) / "universum.txt"
            cache.write_text("# liquide\n# fehlt MDAX\nAAPL\n", encoding="utf-8")
            moment = int(time.time())
            os.utime(cache, (moment, moment))
            symbole, hinweis = lade_universum(("SAP.DE",), cache, oeffnen=self._verboten, jetzt=moment)
            self.assertEqual(symbole, ("SAP.DE", "AAPL"))
            self.assertIn("MDAX", hinweis)
            os.utime(cache, (moment - 7 * 3600, moment - 7 * 3600))
            symbole, _ = lade_universum(("SAP.DE",), cache, oeffnen=self._quellen, jetzt=moment)
        self.assertIn("ADS.DE", symbole)

    def test_alte_riesenliste_wird_ersetzt(self):
        with tempfile.TemporaryDirectory() as ordner:
            cache = Path(ordner) / "universum.txt"
            cache.write_text("ZZZZ\n" * 2500, encoding="utf-8")
            symbole, hinweis = lade_universum(("SAP.DE",), cache, oeffnen=self._quellen, jetzt=int(time.time()))
        self.assertIn("AAPL", symbole)
        self.assertIn("ADS.DE", symbole)
        self.assertNotIn("ZZZZ", symbole)
        self.assertIn("Nasdaq 100", hinweis)

    def test_ruhiger_name_bleibt_im_hintergrund(self):
        with tempfile.TemporaryDirectory() as ordner:
            pfad = Path(ordner) / "markt.sqlite"
            merken(
                pfad,
                (
                    {"symbol": "BAYN.DE", "name": "Bayer", "preis": "30 EUR", "wert": 30, "tag": "+0,4 %", "tag_wert": 0.4, "richtung": "hoch", "herkunft": "Yahoo", "fenster": "", "datenstatus": "ok", "bereich": "Deutschland", "kurszeit": int(time.time())},
                    {"symbol": "NVDA", "name": "NVIDIA", "preis": "140 EUR", "wert": 140, "tag": "-4 %", "tag_wert": -4, "richtung": "runter", "herkunft": "Yahoo", "fenster": "", "datenstatus": "ok", "bereich": "USA", "kurszeit": int(time.time()), "ungewoehnlich": "Heute selten."},
                    {"symbol": "NORM", "name": "Normal", "preis": "20 EUR", "wert": 20, "tag": "-4 %", "tag_wert": -4, "richtung": "runter", "herkunft": "Yahoo", "fenster": "", "datenstatus": "ok", "bereich": "USA", "kurszeit": int(time.time())},
                    {"symbol": "ALT", "name": "Alt", "preis": "10 EUR", "wert": 10, "tag": "-5 %", "tag_wert": -5, "richtung": "runter", "herkunft": "Yahoo", "fenster": "", "datenstatus": "ok", "bereich": "USA", "kurszeit": int(time.time()) - 40 * 3600},
                ),
            )
            namen = [karte["name"] for karte in sichtbar(pfad)]
            self.assertEqual(faellig(pfad, ("BAYN.DE", "NVDA", "SAP.DE"), int(time.time())), ("SAP.DE",))
        self.assertEqual(namen, ["NVIDIA"])
        self.assertEqual(runde_symbole(("ALT", "NVDA", "SAP.DE"), ("SAP.DE", "BTC-USD")), ("SAP.DE", "ALT", "NVDA"))
        self.assertEqual(
            runde_symbole(("ALT", "NVDA"), ("SAP.DE", "BTC-USD"), sofort=("SAP.DE",)),
            ("SAP.DE", "ALT", "NVDA"),
        )
        self.assertEqual(
            runde_symbole(("ALT",), ("SAP.DE",), sofort=("NVDA", "SAP.DE")),
            ("SAP.DE", "NVDA", "ALT"),
        )
        self.assertEqual(runde_groesse(41), 80)
        self.assertEqual(runde_groesse(10), 40)
        self.assertEqual(pause_bei_luecke(180, 3), 60)
        self.assertEqual(pause_bei_luecke(180, 0), 180)
        self.assertFalse(ist_wichtig("", -4.0, "ok", 0, 40 * 3600))

    def test_fehlende_nachrichten_kommen_trotz_frischem_kurs(self):
        with tempfile.TemporaryDirectory() as ordner:
            pfad = Path(ordner) / "markt.sqlite"
            merken(
                pfad,
                (
                    {
                        "symbol": "AAPL",
                        "name": "Apple",
                        "preis": "100 EUR",
                        "wert": 100,
                        "tag": "0 %",
                        "tag_wert": 0,
                        "richtung": "ohne",
                        "herkunft": "Yahoo",
                        "fenster": "",
                        "ungewoehnlich": "",
                        "datenstatus": "ok",
                        "bereich": "USA",
                        "kurszeit": int(time.time()),
                    },
                ),
            )
            menge = mess_runde(pfad, ("AAPL", "MSFT"), ("AAPL",), int(time.time()))
            self.assertEqual(menge[0], "AAPL")
            self.assertIn("MSFT", menge)

    def test_gespeicherte_kurse_liefern_die_chance_einmal(self):
        from kurse import Bar
        from lernen import kurse_merken

        with tempfile.TemporaryDirectory() as ordner:
            pfad = Path(ordner) / "markt.sqlite"
            merken(
                pfad,
                (
                    {
                        "symbol": "AAA",
                        "name": "Alpha",
                        "preis": "10 EUR",
                        "wert": 10,
                        "tag": "0 %",
                        "tag_wert": 0,
                        "richtung": "ohne",
                        "herkunft": "Yahoo",
                        "fenster": "",
                        "datenstatus": "ok",
                        "bereich": "USA",
                        "kurszeit": int(time.time()),
                    },
                ),
            )
            kurse_merken(pfad, "AAA", tuple(Bar(index, None, None, None, 10, 10, None) for index in range(10)))
            self.assertEqual(chancen_nachtragen(pfad), 1)
            self.assertEqual(chancen_nachtragen(pfad), 0)
            karte = next(eintrag for eintrag in alle(pfad) if eintrag["symbol"] == "AAA")
        self.assertIsNone(karte["aufwaerts"])
        self.assertEqual(karte["fenster_faelle"], 0)

    def test_mitteilung_kommt_einmal(self):
        with tempfile.TemporaryDirectory() as ordner:
            pfad = Path(ordner) / "markt.sqlite"
            karte = {
                "symbol": "NVDA",
                "name": "NVIDIA",
                "preis": "100 EUR",
                "wert": 100,
                "tag": "-4 %",
                "tag_wert": -4,
                "richtung": "runter",
                "herkunft": "Yahoo",
                "fenster": "",
                "ungewoehnlich": "Heute selten.",
                "datenstatus": "ok",
                "bereich": "USA",
                "kurszeit": int(time.time()),
            }
            merken(pfad, (karte,))
            texte = []
            self.assertEqual(sende_hinweise(pfad, (karte,), ("NVDA",), lambda titel, text: texte.append((titel, text))), 1)
            self.assertEqual(sende_hinweise(pfad, (karte,), ("NVDA",), lambda titel, text: texte.append((titel, text))), 0)
            self.assertEqual(sende_hinweise(pfad, (karte,), ("SAP.DE",), lambda titel, text: texte.append((titel, text))), 0)
        self.assertIn("NVIDIA ist ungewöhnlich", texte[0][0])
        self.assertIn("kein Auftrag", texte[0][1])

    def _verboten(self, *args, **kwargs):
        raise AssertionError("Netz")

    def _quellen(self, adresse, timeout=20):
        class Antwort:
            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def read(self):
                if "constituents" in adresse:
                    return b"Symbol,Security\nAAPL,Apple\n"
                if "page=DAX" in adresse:
                    return b"|ADS|| Sportartikel\n"
                if "page=MDAX" in adresse:
                    return b"|ALV|| Versicherung\n"
                return b"<td>AAPL</td><td><a href=\"x\">Apple</a></td>"

        return Antwort()


if __name__ == "__main__":
    unittest.main()
