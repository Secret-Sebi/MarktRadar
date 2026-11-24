"""Tageskerze: Bar.zeit ist der Sitzungsbeginn, der Schluss kommt später.

Konvention, solange Bar kein Endfeld hat. Die Tests hängen das explizite
Sitzungsende als Attribut sitzungsende an eine Bar. Der Schluss gilt erst
ab diesem Zeitpunkt als bekannt. verfuegbar_bis(bar) soll genau dieses
Ende liefern und None, wenn es fehlt. None heißt: nicht raten.

Eine fehlende Zeitzone, ein Wochenendbalken ohne Sitzung und ein
aufgefüllter Feiertag bleiben damit für Merkmale unbrauchbar.
Liegt nachrichten.erfasst vor, ist die Entscheidungszeit das spätere
von Veröffentlichung und Eingang. Fehlt der Eingang, ist eine Kerze
ohne explizites Ende nicht sicher.
Eine spätere Kurskorrektur ersetzt die Ursprungszeile nicht. Die neue
Fassung trägt kontaminiert=1, der ursprüngliche Schluss bleibt stehen.
"""

import json
import sqlite3
import tempfile
import unittest
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from ki import merkmale, trainiere
from kurse import Bar
from lernen import aus_yahoo, kurse_merken, nachtragen, speichern, zielzeit

BERLIN = ZoneInfo("Europe/Berlin")
SONDER = 1.0
MONTAG = date(2024, 6, 3)
DIENSTAG = date(2024, 6, 4)
MITTWOCH = date(2024, 6, 5)
FREITAG = date(2024, 6, 7)
SAMSTAG = date(2024, 6, 8)


class _Kerze:
    """Bar plus explizites Sitzungsende. Bar.zeit bleibt der Beginn."""

    def __init__(self, bar, sitzungsende, zeitzone):
        self.sitzungsende = sitzungsende
        self.zeitzone = zeitzone
        self._bar = bar

    def __getattr__(self, name):
        return getattr(self._bar, name)


def _unix(tag, stunde, minute, zone):
    return int(datetime(tag.year, tag.month, tag.day, stunde, minute, tzinfo=zone).timestamp())


def _kerze(zeit, schluss, sitzungsende, zeitzone):
    balken = Bar(zeit, None, None, None, float(schluss), float(schluss), None)
    return _Kerze(balken, sitzungsende, zeitzone)


def _equity(tag, schluss):
    return _kerze(_unix(tag, 9, 0, BERLIN), schluss, _unix(tag, 17, 30, BERLIN), "Europe/Berlin")


def _werktage_ab(start, anzahl, richtung):
    tage = []
    cursor = start
    while len(tage) < anzahl:
        cursor += timedelta(days=richtung)
        if cursor.weekday() < 5:
            tage.append(cursor)
    if richtung < 0:
        tage.reverse()
    return tage


def _reihe_um(stichtag, sonder=None, davor=30, danach=25):
    tage = _werktage_ab(stichtag, davor, -1) + [stichtag] + _werktage_ab(stichtag, danach, 1)
    reihe = []
    for index, tag in enumerate(tage):
        schluss = SONDER if tag == sonder else 100.0 + index
        reihe.append(_equity(tag, schluss))
    return tuple(reihe)


def _index(reihe, tag):
    for index, bar in enumerate(reihe):
        if datetime.fromtimestamp(bar.zeit, BERLIN).date() == tag:
            return index
    raise AssertionError(f"Handelstag fehlt: {tag}")


def _ersetzt(reihe, tag, balken):
    index = _index(reihe, tag)
    return reihe[:index] + (balken,) + reihe[index + 1 :]


def _echte_sitzungen(balken):
    echt = []
    for bar in sorted(balken, key=lambda eintrag: eintrag.zeit or 0):
        ende = getattr(bar, "sitzungsende", None)
        if isinstance(ende, bool) or not isinstance(ende, int):
            continue
        if isinstance(bar.zeit, bool) or not isinstance(bar.zeit, int):
            continue
        echt.append(bar)
    return tuple(echt)


def _bekannt(balken, zeitpunkt):
    return tuple(bar for bar in _echte_sitzungen(balken) if bar.sitzungsende <= zeitpunkt)


def _ziel_erwartet(balken, zeitpunkt, abstand):
    offen = [bar for bar in _echte_sitzungen(balken) if bar.sitzungsende > zeitpunkt]
    if abstand < 1 or len(offen) <= abstand:
        return None
    return offen[0].zeit, offen[abstand].sitzungsende


def _verfuegbar_bis(bar):
    for name in ("ki", "lernen", "kurse"):
        modul = __import__(name, fromlist=("verfuegbar_bis",))
        funktion = getattr(modul, "verfuegbar_bis", None)
        if funktion is not None:
            return funktion(bar)
    raise AssertionError(
        "verfuegbar_bis fehlt in ki, lernen und kurse; "
        "ohne explizites Sitzungsende darf der Schluss nicht als bekannt gelten"
    )


def _vektoren(wert):
    if wert is None:
        return None
    return [float(teil) for teil in wert]


class KerzenzeitTests(unittest.TestCase):
    def _assert_gleiche_merkmale(self, ist, soll, hinweis):
        self.assertIsNotNone(soll, hinweis)
        self.assertIsNotNone(ist, hinweis)
        self.assertEqual(len(ist), len(soll), hinweis)
        for index, (links, rechts) in enumerate(zip(ist, soll)):
            self.assertAlmostEqual(links, rechts, places=6, msg=f"{hinweis} an Position {index}")

    def _merkmal_ohne_zukuenftigen_schluss(self, reihe, zeitpunkt, hinweis):
        ist = _vektoren(merkmale(reihe, zeitpunkt, "zinsen"))
        soll = _vektoren(merkmale(_bekannt(reihe, zeitpunkt), zeitpunkt, "zinsen"))
        self._assert_gleiche_merkmale(ist, soll, hinweis)

    def _assert_zielzeit(self, reihe, zeitpunkt):
        self.assertEqual(zielzeit(reihe, zeitpunkt, 1), _ziel_erwartet(reihe, zeitpunkt, 1))

    def test_meldung_vor_der_eroeffnung_nutzt_den_tagesschluss_nicht(self):
        reihe = _reihe_um(MONTAG, sonder=MONTAG)
        meldung = _unix(MONTAG, 8, 0, BERLIN)
        with self.subTest("merkmale"):
            self._merkmal_ohne_zukuenftigen_schluss(reihe, meldung, "vor der Eroeffnung")
        with self.subTest("zielzeit"):
            self._assert_zielzeit(reihe, meldung)

    def test_meldung_waehrend_der_sitzung_nutzt_denselben_schluss_nicht(self):
        reihe = _reihe_um(MONTAG, sonder=MONTAG)
        meldung = _unix(MONTAG, 12, 0, BERLIN)
        with self.subTest("merkmale"):
            self._merkmal_ohne_zukuenftigen_schluss(reihe, meldung, "waehrend der Sitzung")
        with self.subTest("zielzeit"):
            self._assert_zielzeit(reihe, meldung)

    def test_meldung_kurz_vor_dem_schluss_nutzt_ihn_nicht(self):
        reihe = _reihe_um(MONTAG, sonder=MONTAG)
        kerze = reihe[_index(reihe, MONTAG)]
        meldung = kerze.sitzungsende - 1
        with self.subTest("merkmale"):
            self._merkmal_ohne_zukuenftigen_schluss(reihe, meldung, "kurz vor dem Schluss")
        with self.subTest("zielzeit"):
            self._assert_zielzeit(reihe, meldung)

    def test_meldung_nach_dem_schluss_darf_ihn_nutzen(self):
        reihe = _reihe_um(MONTAG, sonder=MONTAG)
        kerze = reihe[_index(reihe, MONTAG)]
        meldung = kerze.sitzungsende + 1
        ist = merkmale(reihe, meldung, "zinsen")
        ohne = tuple(bar for bar in reihe if bar.zeit != kerze.zeit)
        self._assert_gleiche_merkmale(
            _vektoren(ist),
            _vektoren(merkmale(_bekannt(reihe, meldung), meldung, "zinsen")),
            "nach dem Schluss",
        )
        self.assertNotEqual(ist, merkmale(ohne, meldung, "zinsen"))

    def test_wochenendmeldung_erfindet_keine_sitzung(self):
        reihe = _reihe_um(FREITAG)
        erfunden = _kerze(_unix(SAMSTAG, 0, 0, BERLIN), SONDER, None, None)
        reihe = reihe + (erfunden,)
        meldung = _unix(SAMSTAG, 15, 0, BERLIN)
        with self.subTest("merkmale"):
            self._merkmal_ohne_zukuenftigen_schluss(reihe, meldung, "Wochenende")
        with self.subTest("zielzeit"):
            fenster = zielzeit(reihe, meldung, 1)
            self.assertEqual(fenster, _ziel_erwartet(reihe, meldung, 1))
            self.assertIsNotNone(fenster)
            for stempel in fenster:
                self.assertLess(datetime.fromtimestamp(stempel, BERLIN).weekday(), 5)

    def test_feiertag_wird_uebersprungen_nicht_aufgefuellt(self):
        reihe = _reihe_um(DIENSTAG)
        luecke = reihe[_index(reihe, MITTWOCH)]
        reihe = _ersetzt(reihe, MITTWOCH, _kerze(luecke.zeit, luecke.schluss, None, None))
        meldung = _unix(DIENSTAG, 18, 0, BERLIN)
        with self.subTest("merkmale"):
            self._merkmal_ohne_zukuenftigen_schluss(reihe, meldung, "Feiertag")
        with self.subTest("zielzeit"):
            fenster = zielzeit(reihe, meldung, 1)
            self.assertEqual(fenster, _ziel_erwartet(reihe, meldung, 1))
            self.assertIsNotNone(fenster)
            for stempel in fenster:
                self.assertNotEqual(datetime.fromtimestamp(stempel, BERLIN).date(), MITTWOCH)

    def test_krypto_kerze_gilt_erst_nach_ihrem_ende(self):
        start = datetime(2024, 1, 1, tzinfo=timezone.utc)  # noqa: UP017
        reihe = []
        for index in range(40):
            beginn = int((start + timedelta(days=index)).timestamp())
            schluss = SONDER if index == 25 else 100.0 + index
            reihe.append(_kerze(beginn, schluss, beginn + 86400, "UTC"))
        reihe = tuple(reihe)
        kerze = reihe[25]
        with self.subTest("zum Beginn"):
            self._merkmal_ohne_zukuenftigen_schluss(reihe, kerze.zeit, "Krypto zum Beginn")
        with self.subTest("kurz nach Beginn"):
            self._merkmal_ohne_zukuenftigen_schluss(reihe, kerze.zeit + 1, "Krypto nach Beginn")
        with self.subTest("kurz vor Ende"):
            self._merkmal_ohne_zukuenftigen_schluss(reihe, kerze.sitzungsende - 1, "Krypto vor Ende")
        with self.subTest("am Ende"):
            ist = merkmale(reihe, kerze.sitzungsende, "zinsen")
            ohne = reihe[:25] + reihe[26:]
            self._assert_gleiche_merkmale(
                _vektoren(ist),
                _vektoren(merkmale(_bekannt(reihe, kerze.sitzungsende), kerze.sitzungsende, "zinsen")),
                "Krypto am Ende",
            )
            self.assertNotEqual(ist, merkmale(ohne, kerze.sitzungsende, "zinsen"))

    def _gelerntes_merkmal(self, reihe, veroeffentlicht, erfasst, url):
        with tempfile.TemporaryDirectory() as ordner:
            pfad = Path(ordner) / "markt.sqlite"
            speichern(
                pfad,
                "SAP.DE",
                aus_yahoo(
                    {
                        "news": [
                            {
                                "title": "EZB hebt die Zinsen",
                                "link": url,
                                "publisher": "Reuters",
                                "providerPublishTime": veroeffentlicht,
                            }
                        ]
                    }
                ),
            )
            with sqlite3.connect(pfad) as verbindung:
                verbindung.execute("UPDATE nachrichten SET erfasst = ? WHERE symbol = ?", (erfasst, "SAP.DE"))
            nachtragen(pfad, "SAP.DE", reihe)
            trainiere(pfad, "SAP.DE", reihe, pruefen=False)
            with sqlite3.connect(pfad) as verbindung:
                zeile = verbindung.execute(
                    "SELECT status, grund, merkmale FROM ki_beispiel WHERE horizont = 1"
                ).fetchone()
                validiert = verbindung.execute("SELECT validiert FROM ki_horizont WHERE horizont = 1").fetchone()
        self.assertIsNotNone(zeile, "kein Trainingsbeispiel")
        self.assertEqual(zeile[0], "trainiert", zeile[1])
        self.assertEqual(validiert[0], 0)
        return json.loads(zeile[2])

    def test_spaeter_eingang_und_fehlender_eingang(self):
        reihe = _reihe_um(MONTAG, sonder=MONTAG)
        kerze = reihe[_index(reihe, MONTAG)]
        with self.subTest("eingang nach dem Schluss"):
            gespeichert = self._gelerntes_merkmal(
                reihe,
                _unix(MONTAG, 8, 0, BERLIN),
                kerze.sitzungsende + 60,
                "https://beispiel.test/kerze-eingang",
            )
            soll = _vektoren(merkmale(reihe, kerze.sitzungsende + 60, "zinsen"))
            self._assert_gleiche_merkmale(gespeichert, soll, "Entscheidungszeit ist der Eingang")
        with self.subTest("fehlender Eingang"):
            unklar = _kerze(kerze.zeit, SONDER, None, None)
            reihe_unklar = _ersetzt(reihe, MONTAG, unklar)
            gespeichert = self._gelerntes_merkmal(
                reihe_unklar,
                _unix(MONTAG, 12, 0, BERLIN),
                None,
                "https://beispiel.test/kerze-ohne-eingang",
            )
            zeitpunkt = _unix(MONTAG, 12, 0, BERLIN)
            soll = _vektoren(merkmale(_bekannt(reihe_unklar, zeitpunkt), zeitpunkt, "zinsen"))
            self._assert_gleiche_merkmale(gespeichert, soll, "fehlender Eingang")

    def test_fehlende_zeitzone_ohne_explizites_ende_bleibt_unbenutzbar(self):
        reihe = _reihe_um(MONTAG, sonder=MONTAG)
        kerze = reihe[_index(reihe, MONTAG)]
        unklar = _kerze(kerze.zeit, SONDER, None, None)
        reihe_unklar = _ersetzt(reihe, MONTAG, unklar)
        spaeter = kerze.zeit + 3 * 86400
        with self.subTest("merkmale"):
            self._merkmal_ohne_zukuenftigen_schluss(reihe_unklar, spaeter, "fehlende Zeitzone")
        with self.subTest("verfuegbar_bis"):
            self.assertIsNone(_verfuegbar_bis(unklar))
            self.assertEqual(_verfuegbar_bis(kerze), kerze.sitzungsende)
        with self.subTest("explizites Ende ohne Zeitzone"):
            klar = _kerze(kerze.zeit, SONDER, kerze.sitzungsende, None)
            reihe_klar = _ersetzt(reihe, MONTAG, klar)
            self._merkmal_ohne_zukuenftigen_schluss(reihe_klar, kerze.sitzungsende + 1, "explizites Ende")

    def test_spaetere_korrektur_gilt_nicht_rueckwirkend(self):
        reihe = _reihe_um(MONTAG)
        ziel = reihe[-1]
        entscheidung = ziel.sitzungsende + 3600
        vorher = merkmale(reihe, entscheidung, "zinsen")
        korrigiert = _kerze(ziel.zeit, SONDER, ziel.sitzungsende, ziel.zeitzone)
        with tempfile.TemporaryDirectory() as ordner:
            pfad = Path(ordner) / "markt.sqlite"
            kurse_merken(pfad, "SAP.DE", reihe)
            kurse_merken(pfad, "SAP.DE", (korrigiert,))
            with sqlite3.connect(pfad) as verbindung:
                schluesse = [
                    zeile[0]
                    for zeile in verbindung.execute(
                        "SELECT schluss FROM kurse WHERE symbol = ? AND zeit = ?",
                        ("SAP.DE", ziel.zeit),
                    )
                ]
                spalten = [zeile[1] for zeile in verbindung.execute("PRAGMA table_info(kurse)")]
                from ki import _reihe_aus_kursen

                gelesen = _reihe_aus_kursen(verbindung, "SAP.DE", ())
        with self.subTest("ursprung"):
            self.assertTrue(any(abs(wert - ziel.schluss) < 1e-9 for wert in schluesse), schluesse)
        with self.subTest("kontaminiert"):
            self.assertIn("kontaminiert", spalten)
        with self.subTest("merkmale"):
            self._assert_gleiche_merkmale(
                _vektoren(merkmale(gelesen, entscheidung, "zinsen")),
                _vektoren(vorher),
                "Korrektur darf die alte Entscheidung nicht aendern",
            )


if __name__ == "__main__":
    unittest.main()
