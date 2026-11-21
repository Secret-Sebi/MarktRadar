"""Speichert Meldungen und die danach gemessene Kursbewegung.

Die Kategorie sagt nur, worum es geht. Ob das den Kurs gedrückt hat,
steht erst fest, wenn spätere echte Kurse vorliegen.
"""

from __future__ import annotations

import json
import re
import sqlite3
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote
from urllib.request import urlopen

from analyse import BERLIN, de_prozent, de_zahl
from ki import _EINFLUSS
from quellen import hole_text

_RUECKBLICK = "16w"
_NEWS_ART = "news-16w"
_NEWS_ZAHL = 10
_GDELT_ZAHL = 75

_THEMEN = (
    ("uebernahme", ("übernahme", "uebernahme", "takeover", "merger")),
    ("zinsen", ("zins", "leitzins", "ezb", " fed", "fed ", "inflation", "rate hike", "interest rate")),
    ("geopolitik", ("sanktion", "zoll", "tariff", "krieg", "geopolit")),
    ("quartal", ("quartal", "earnings", "gewinnwarnung")),
    ("rohstoff", ("ölpreis", "oelpreis", " oil", "opec")),
    ("krypto", ("bitcoin", "ethereum", "krypto", "crypto")),
)
_MINDEST = 8


@dataclass(frozen=True)
class Meldung:
    titel: str
    quelle: str
    zeit: int
    url: str
    kategorie: str


@dataclass(frozen=True)
class Befund:
    kategorie: str
    anzahl: int
    median: float | None
    umfang: str
    eigene: int = 0
    eigene_median: float | None = None


def kategorie(titel: str) -> str:
    text = f" {titel.lower()} "
    for name, woerter in _THEMEN:
        if any(wort in text for wort in woerter):
            return name
    return "unklar"


def aus_yahoo(roh: dict) -> tuple[Meldung, ...]:
    meldungen = []
    for eintrag in (roh.get("news") if isinstance(roh, dict) else None) or []:
        titel = str(eintrag.get("title") or "").strip()
        url = str(eintrag.get("link") or "").strip()
        zeit = eintrag.get("providerPublishTime")
        if not titel or not url or isinstance(zeit, bool) or not isinstance(zeit, (int, float)):
            continue
        meldungen.append(Meldung(titel, str(eintrag.get("publisher") or "Yahoo Finance"), int(zeit), url, kategorie(titel)))
    return tuple(meldungen)


def aus_gdelt(roh: dict) -> tuple[Meldung, ...]:
    meldungen = []
    for eintrag in (roh.get("articles") if isinstance(roh, dict) else None) or []:
        titel = str(eintrag.get("title") or "").strip()
        url = str(eintrag.get("url") or "").strip()
        zeit = _gdelt_zeit(str(eintrag.get("seendate") or ""))
        if not titel or not url or zeit is None:
            continue
        meldungen.append(Meldung(titel, str(eintrag.get("domain") or "GDELT"), zeit, url, kategorie(titel)))
    return tuple(meldungen)


def gegen_index(wert: float | None, index_wert: float | None) -> float | None:
    if wert is None or index_wert is None:
        return None
    return wert - index_wert


def index_ging_mit(wirkung: float | None, relativ: float | None) -> str:
    if wirkung is None or relativ is None:
        return ""
    index = float(wirkung) - float(relativ)
    if abs(float(wirkung)) < 1 or abs(index) < 1 or float(wirkung) * index <= 0:
        return ""
    if abs(float(relativ)) > abs(float(wirkung)) * 0.5:
        return ""
    return "Der Index ging in derselben Zeit mit. Das ist kein einzelnes Firmenereignis."


def ohne_langen_abruf(pfad: Path, symbole: tuple[str, ...]) -> tuple[str, ...]:
    if not symbole:
        return ()
    if not pfad.exists():
        return tuple(symbole)
    with sqlite3.connect(pfad) as verbindung:
        _tabelle(verbindung)
        zeilen = verbindung.execute("SELECT symbol FROM abruf WHERE art = ?", (_NEWS_ART,)).fetchall()
    bekannt = {str(zeile[0]) for zeile in zeilen}
    return tuple(symbol for symbol in symbole if symbol not in bekannt)


def soll_holen(letzter: int | None, jetzt: int, pause: int = 1800) -> bool:
    if letzter is None:
        return True
    return jetzt - letzter >= pause


def wirkung(balken, zeitpunkt: int, abstand: int) -> float | None:
    if abstand < 1:
        return None
    reihe = tuple(sorted((bar for bar in balken if bar.zeit is not None and bar.schluss > 0), key=lambda bar: bar.zeit))
    start = next((index for index, bar in enumerate(reihe) if bar.zeit >= zeitpunkt), None)
    if start is None or start + abstand >= len(reihe) or reihe[start].schluss == 0:
        return None
    return (reihe[start + abstand].schluss / reihe[start].schluss - 1.0) * 100.0


def speichern(pfad: Path, symbol: str, meldungen: tuple[Meldung, ...]) -> int:
    neu = 0
    pfad.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(pfad) as verbindung:
        _tabelle(verbindung)
        for meldung in meldungen:
            cursor = verbindung.execute(
                """
                INSERT OR IGNORE INTO nachrichten (url, symbol, zeit, titel, quelle, kategorie)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (meldung.url, symbol, meldung.zeit, meldung.titel, meldung.quelle, meldung.kategorie),
            )
            neu += cursor.rowcount
    return neu


def nachtragen(pfad: Path, symbol: str, balken, index_balken=None) -> int:
    with sqlite3.connect(pfad) as verbindung:
        _tabelle(verbindung)
        zeilen = verbindung.execute(
            """
            SELECT id, zeit, wirkung_1, wirkung_3, wirkung_5, wirkung_20
            FROM nachrichten
            WHERE symbol = ? AND (wirkung_1 IS NULL OR wirkung_3 IS NULL OR wirkung_5 IS NULL OR wirkung_20 IS NULL)
            """,
            (symbol,),
        ).fetchall()
        geaendert = 0
        for nummer, zeit, w1, w3, w5, w20 in zeilen:
            vorhanden = {1: w1, 3: w3, 5: w5, 20: w20}
            neu = {}
            for abstand, alt in vorhanden.items():
                if alt is not None:
                    continue
                wert = wirkung(balken, int(zeit), abstand)
                if wert is not None:
                    neu[abstand] = wert
            if not neu:
                continue
            teile = [f"wirkung_{abstand} = ?" for abstand in (1, 3, 5, 20) if abstand in neu]
            werte = [neu[abstand] for abstand in (1, 3, 5, 20) if abstand in neu]
            if 5 in neu:
                index_5 = wirkung(index_balken, int(zeit), 5) if index_balken else None
                teile.append("rel_5 = ?")
                werte.append(gegen_index(neu[5], index_5))
            werte.append(nummer)
            verbindung.execute(f"UPDATE nachrichten SET {', '.join(teile)} WHERE id = ?", werte)
            geaendert += 1
    return geaendert


def statistik(pfad: Path, symbol: str) -> Befund:
    with sqlite3.connect(pfad) as verbindung:
        _tabelle(verbindung)
        anzahl_eigen, median_eigen = _faelle(verbindung, symbol)
        thema = verbindung.execute(
            """
            SELECT kategorie FROM nachrichten
            WHERE symbol = ? AND kategorie != 'unklar'
            ORDER BY zeit DESC LIMIT 1
            """,
            (symbol,),
        ).fetchone()
        if thema is None:
            return Befund("unklar", 0, None, "keine Meldung", anzahl_eigen, median_eigen)
        name = str(thema[0])
        eigen = _mediane(verbindung, name, symbol)
        if eigen[0] >= 5:
            return Befund(name, eigen[0], eigen[1], "dieses Kürzel", anzahl_eigen, median_eigen)
        gesamt = _mediane(verbindung, name, None)
        return Befund(name, gesamt[0], gesamt[1], "mehrere Kürzel", anzahl_eigen, median_eigen)


def aktualisiere(pfad: Path, symbol: str, name: str, balken, oeffnen=urlopen, index_balken=None) -> Befund:
    kurse_merken(pfad, symbol, balken)
    _holen(pfad, symbol, name, oeffnen)
    if pfad.exists():
        nachtragen(pfad, symbol, balken, index_balken)
    return statistik(pfad, symbol) if pfad.exists() else Befund("unklar", 0, None, "keine Meldung")


def aktion_aus_lernen(aktion: str, anzahl: int, median: float | None) -> str:
    if anzahl < _MINDEST or median is None or median > -1:
        return aktion
    if aktion in ("einstieg_pruefen", "sparplan"):
        return "abwarten"
    return aktion


def aktion_aus_verkauf(aktion: str, eigene: int, median: float | None, daten_ok: bool) -> str:
    if not daten_ok or eigene < _MINDEST or median is None or median > -1:
        return aktion
    if aktion in ("fehler", "unvollstaendig"):
        return aktion
    return "verkauf_pruefen"


def fortschritt(pfad: Path) -> dict:
    if not pfad.exists():
        return _lernstand(0, 0, 0, 0, 0, 0)
    with sqlite3.connect(pfad) as verbindung:
        _tabelle(verbindung)
        abgeschlossen = _anzahl(verbindung, True)
        offen = _anzahl(verbindung, False)
        namen = _anzahl(verbindung, True, True)
        schwelle = len(_namen_ab(verbindung, _MINDEST, False))
        testbar = len(_namen_ab(verbindung, 61, True))
        modell = _modell_faelle(verbindung)
    return _lernstand(abgeschlossen, offen, namen, schwelle, testbar, modell)


def einfluss(
    pfad: Path,
    tage: int = 7,
    jetzt: int | None = None,
    grenze: int = 3,
    namen: dict[str, str] | None = None,
) -> dict:
    moment = int(time.time()) if jetzt is None else int(jetzt)
    leer = {"meldungen": [], "offen": [], "hinweis": "In diesem Zeitraum liegt keine zugeordnete Meldung."}
    if not pfad.exists() or tage < 1:
        return leer
    anfang = moment - tage * 86400
    with sqlite3.connect(pfad) as verbindung:
        _tabelle(verbindung)
        zeilen = verbindung.execute(
            """
            SELECT url, symbol, zeit, titel, quelle, wirkung_5, rel_5
            FROM nachrichten
            WHERE zeit >= ?
            ORDER BY zeit DESC
            """,
            (anfang,),
        ).fetchall()
    zuordnung = namen or {}
    zeilen = tuple(
        zeile
        for zeile in zeilen
        if _passt(
            Meldung(str(zeile[3]), str(zeile[4]), int(zeile[2]), str(zeile[0]), "unklar"),
            str(zeile[1]),
            zuordnung.get(str(zeile[1]), ""),
        )
    )
    if not zeilen:
        return leer
    gruppen = _gruppen(zeilen)
    gemessen = tuple(gruppe for gruppe in gruppen if gruppe["staerke"] is not None)
    gemessen = tuple(sorted(gemessen, key=lambda gruppe: (-gruppe["staerke"], -gruppe["zeit"])))[:grenze]
    ohne = tuple(gruppe for gruppe in gruppen if gruppe["staerke"] is None)[:grenze]
    hinweis = (
        "Sortiert nach der größten späteren Kursbewegung. Das ist ein Zusammenhang, keine Ursache. "
        "Betroffen ist nur, wer in der Überschrift vorkam."
        if gemessen
        else "Noch keine Meldung in diesem Zeitraum hat 5 spätere Handelstage. Deshalb nenne ich keinen Einfluss."
    )
    return {
        "meldungen": tuple(_sicht(gruppe, True) for gruppe in gemessen),
        "offen": tuple(_sicht(gruppe, False) for gruppe in ohne),
        "hinweis": hinweis,
    }


def folge_satz(pfad: Path, symbol: str) -> str:
    if not pfad.exists():
        return "Zu diesem Namen ist noch kein Folgetag ausgewertet."
    with sqlite3.connect(pfad) as verbindung:
        _tabelle(verbindung)
        zeilen = verbindung.execute(
            "SELECT zeit, wirkung_1 FROM nachrichten WHERE symbol = ? AND wirkung_1 IS NOT NULL",
            (symbol,),
        ).fetchall()
    tage: dict[int, float] = {}
    for zeit, wert in zeilen:
        tage[int(zeit) // 86400] = float(wert)
    if len(tage) < 8:
        return f"Ausgewertete Folgetage zu diesem Namen: {len(tage)}. Für eine Zahl brauche ich mindestens 8."
    median = sorted(tage.values())
    mitte = len(median) // 2
    wert = median[mitte] if len(median) % 2 else (median[mitte - 1] + median[mitte]) / 2.0
    return (
        f"Nach {len(tage)} ausgewerteten Tagen lag der nächste Handelstag im Median bei {de_zahl(wert, 1)} %."
    )


def satz(befund: Befund) -> str:
    if befund.umfang == "keine Meldung":
        return "Zu diesem Kürzel liegen noch keine auswertbaren Nachrichten vor."
    if befund.anzahl == 0 or befund.median is None:
        return f"Zum Thema {befund.kategorie} gibt es noch keine spätere Kursbewegung."
    text = (
        f"Thema {befund.kategorie}, {befund.umfang}: {befund.anzahl} Meldungen, "
        f"Median nach 5 Handelstagen {de_zahl(befund.median, 1)} %. "
        "Das ist ein Zusammenhang, keine Ursache."
    )
    if befund.anzahl < 20:
        text += " Kleine Stichprobe."
    return text + (
        " Die Zuordnung prüft nur, ob Kürzel oder Name in der Überschrift stehen."
        " Eine Branchenwirkung wird nicht geschätzt."
    )


def nachrichten_adressen(symbol: str, name: str) -> tuple[str, str]:
    yahoo = (
        "https://query2.finance.yahoo.com/v1/finance/search?quotesCount=0&newsCount="
        + str(_NEWS_ZAHL)
        + "&q="
        + quote(symbol)
    )
    gdelt = (
        "https://api.gdeltproject.org/api/v2/doc/doc?mode=artlist&format=json&maxrecords="
        + str(_GDELT_ZAHL)
        + "&timespan="
        + _RUECKBLICK
        + "&query="
        + quote(name or symbol)
    )
    return yahoo, gdelt


def kurse_merken(pfad: Path, symbol: str, balken) -> int:
    rein = str(symbol or "").strip().upper()
    if not rein:
        return 0
    zeilen = []
    for balken_eintrag in balken or ():
        zeit = getattr(balken_eintrag, "zeit", None)
        schluss = getattr(balken_eintrag, "schluss", None)
        if isinstance(zeit, bool) or not isinstance(zeit, int) or not schluss or float(schluss) <= 0:
            continue
        zeilen.append((rein, int(zeit), float(schluss)))
    if not zeilen:
        return 0
    pfad.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(pfad) as verbindung:
        _tabelle(verbindung)
        verbindung.executemany(
            "INSERT OR REPLACE INTO kurse (symbol, zeit, schluss) VALUES (?, ?, ?)",
            zeilen,
        )
    return len(zeilen)


def _holen(pfad: Path, symbol: str, name: str, oeffnen, jetzt: int | None = None) -> None:
    moment = int(time.time()) if jetzt is None else jetzt
    if pfad.exists() and not soll_holen(_letzter_abruf(pfad, symbol), moment):
        return
    gesammelt: list[Meldung] = []
    yahoo, gdelt = nachrichten_adressen(symbol, name)
    for adresse, leser in ((yahoo, aus_yahoo), (gdelt, aus_gdelt)):
        try:
            meldungen = leser(json.loads(hole_text(adresse, oeffnen, "application/json")))
        except (ConnectionError, LookupError, TimeoutError, json.JSONDecodeError, ValueError):
            continue
        gesammelt.extend(meldung for meldung in meldungen if _passt(meldung, symbol, name))
    if gesammelt:
        speichern(pfad, symbol, tuple(gesammelt))
    _abruf_merken(pfad, symbol, moment)


def _passt(meldung: Meldung, symbol: str, name: str) -> bool:
    text = meldung.titel.lower()
    if _ist_marktbericht(text):
        return False
    kuerzel = symbol.upper().split(".")[0].split("-")[0].lower()
    if _wort(text, kuerzel):
        return True
    token = _namenswort(name)
    return bool(token) and _wort(text, token)


def _ist_marktbericht(text: str) -> bool:
    return any(
        muster in text
        for muster in (
            "stock market today",
            "markets today",
            "what to watch",
            "wall street",
            "dow, s&p",
            "countdown to",
            "stocks fall",
            "stocks rise",
            "stocks slip",
            "stocks drop",
            "stocks gain",
            "dollar dips",
        )
    )


def _namenswort(name: str) -> str:
    for wort in str(name or "").replace(",", " ").split():
        rein = wort.strip(".").lower()
        if len(rein) >= 4 and rein not in ("group", "stock", "euro", "ucits", "corp", "holdings"):
            return rein
    return ""


def _wort(text: str, wort: str) -> bool:
    if len(wort) < 3:
        return False
    return re.search(rf"\b{re.escape(wort)}\b", text) is not None


def _faelle(verbindung: sqlite3.Connection, symbol: str) -> tuple[int, float | None]:
    werte = verbindung.execute(
        "SELECT wirkung_5 FROM nachrichten WHERE symbol = ? AND wirkung_5 IS NOT NULL",
        (symbol,),
    ).fetchall()
    zahlen = tuple(float(zeile[0]) for zeile in werte)
    return len(zahlen), _median(zahlen)


def _mediane(verbindung: sqlite3.Connection, kategorie_name: str, symbol: str | None) -> tuple[int, float | None]:
    if symbol is None:
        werte = verbindung.execute(
            "SELECT wirkung_5 FROM nachrichten WHERE kategorie = ? AND wirkung_5 IS NOT NULL",
            (kategorie_name,),
        ).fetchall()
    else:
        werte = verbindung.execute(
            "SELECT wirkung_5 FROM nachrichten WHERE kategorie = ? AND symbol = ? AND wirkung_5 IS NOT NULL",
            (kategorie_name, symbol),
        ).fetchall()
    zahlen = tuple(float(zeile[0]) for zeile in werte)
    return len(zahlen), _median(zahlen)


def _median(werte: tuple[float, ...]) -> float | None:
    if not werte:
        return None
    folge = tuple(sorted(werte))
    mitte = len(folge) // 2
    if len(folge) % 2:
        return folge[mitte]
    return (folge[mitte - 1] + folge[mitte]) / 2


def _gdelt_zeit(wert: str) -> int | None:
    if len(wert) < 16 or wert[8] != "T":
        return None
    try:
        moment = datetime(
            int(wert[0:4]),
            int(wert[4:6]),
            int(wert[6:8]),
            int(wert[9:11]),
            int(wert[11:13]),
            int(wert[13:15]),
            tzinfo=timezone.utc,  # noqa: UP017
        )
    except ValueError:
        return None
    return int(moment.timestamp())


def _tabelle(verbindung: sqlite3.Connection) -> None:
    verbindung.execute(
        """
        CREATE TABLE IF NOT EXISTS nachrichten (
            id INTEGER PRIMARY KEY,
            url TEXT NOT NULL,
            symbol TEXT NOT NULL,
            zeit INTEGER NOT NULL,
            titel TEXT NOT NULL,
            quelle TEXT NOT NULL,
            kategorie TEXT NOT NULL,
            wirkung_1 REAL,
            wirkung_3 REAL,
            wirkung_5 REAL,
            wirkung_20 REAL,
            rel_5 REAL,
            UNIQUE (url, symbol)
        )
        """
    )
    verbindung.execute(
        """
        CREATE TABLE IF NOT EXISTS kurse (
            symbol TEXT NOT NULL,
            zeit INTEGER NOT NULL,
            schluss REAL NOT NULL,
            PRIMARY KEY (symbol, zeit)
        )
        """
    )
    spalten = {str(zeile[1]) for zeile in verbindung.execute("PRAGMA table_info(nachrichten)")}
    if "rel_5" not in spalten:
        verbindung.execute("ALTER TABLE nachrichten ADD COLUMN rel_5 REAL")
    _url_fuer_mehrere_namen(verbindung)
    verbindung.execute(
        """
        CREATE TABLE IF NOT EXISTS abruf (
            symbol TEXT NOT NULL,
            art TEXT NOT NULL,
            zeit INTEGER NOT NULL,
            PRIMARY KEY (symbol, art)
        )
        """
    )


def _url_fuer_mehrere_namen(verbindung: sqlite3.Connection) -> None:
    gefunden = verbindung.execute("SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'nachrichten'").fetchone()
    text = "" if gefunden is None or gefunden[0] is None else str(gefunden[0]).replace(" ", "")
    if "UNIQUE(url,symbol)" in text:
        return
    if "urlTEXTNOTNULLUNIQUE" not in text and "urlTEXTUNIQUE" not in text:
        return
    alt = [str(zeile[1]) for zeile in verbindung.execute("PRAGMA table_info(nachrichten)")]
    definitionen = []
    for _cid, name, typ, pflicht, standard, schluessel in verbindung.execute("PRAGMA table_info(nachrichten)"):
        if schluessel:
            definitionen.append(f"{name} INTEGER PRIMARY KEY")
            continue
        stueck = f"{name} {typ or 'TEXT'}"
        if pflicht:
            stueck += " NOT NULL"
        if standard is not None:
            stueck += f" DEFAULT {standard}"
        definitionen.append(stueck)
    definitionen.append("UNIQUE (url, symbol)")
    verbindung.execute("ALTER TABLE nachrichten RENAME TO nachrichten_alt")
    verbindung.execute(f"CREATE TABLE nachrichten ({', '.join(definitionen)})")
    spalten = ", ".join(alt)
    verbindung.execute(f"INSERT INTO nachrichten ({spalten}) SELECT {spalten} FROM nachrichten_alt")
    verbindung.execute("DROP TABLE nachrichten_alt")


def _kurz(modell: int) -> str:
    if modell <= 0:
        return "Ausgewertete Handelstage: 0. Unter 60 ändert das keinen Vorschlag."
    if modell < _EINFLUSS:
        return (
            f"Ausgewertete Handelstage: {modell}. "
            "Unter 60 bleibt das eine kleine Stichprobe und ändert keinen Vorschlag."
        )
    return f"Ausgewertete Handelstage: {modell}. Das bleibt eine Stichprobe und ändert keinen Vorschlag."


def _lernstand(abgeschlossen: int, offen: int, namen: int, schwelle: int, testbar: int, modell: int) -> dict:
    kurz = _kurz(modell)
    if abgeschlossen == 0 and offen == 0:
        text = (
            "Sobald nach einer Meldung der nächste Handelstag da ist, "
            "lerne ich, ob der Kurs höher schloss. Der Mac muss dafür an sein."
        )
    else:
        text = (
            f"Abgeschlossen sind {abgeschlossen} Fälle bei {namen} Namen, {offen} Meldungen warten noch auf 5 spätere Handelstage. "
            f"{schwelle} Namen haben mindestens {_MINDEST} eigene Fälle, {testbar} Namen haben mehr als 60. "
            "Ein kurzes Fenster kommt aus den geladenen Kursen. "
            "Unklare Überschriften liefern nur die Kursbewegung, und bei geschlossenem Mac kommt nichts dazu."
        )
    return {
        "abgeschlossen": abgeschlossen,
        "offen": offen,
        "namen": namen,
        "schwelle": schwelle,
        "testbar": testbar,
        "modell": modell,
        "kurz": kurz,
        "text": f"{kurz} {text}",
    }


def _anzahl(verbindung: sqlite3.Connection, abgeschlossen: bool, namen: bool = False) -> int:
    if namen:
        zeile = verbindung.execute(
            "SELECT COUNT(DISTINCT symbol) FROM nachrichten WHERE wirkung_5 IS NOT NULL"
        ).fetchone()
    elif abgeschlossen:
        zeile = verbindung.execute("SELECT COUNT(*) FROM nachrichten WHERE wirkung_5 IS NOT NULL").fetchone()
    else:
        zeile = verbindung.execute("SELECT COUNT(*) FROM nachrichten WHERE wirkung_5 IS NULL").fetchone()
    return int(zeile[0] or 0)


def _namen_ab(verbindung: sqlite3.Connection, mindest: int, nur_klar: bool) -> tuple:
    if nur_klar:
        return verbindung.execute(
            """
            SELECT symbol FROM nachrichten
            WHERE wirkung_5 IS NOT NULL AND kategorie != 'unklar'
            GROUP BY symbol
            HAVING COUNT(*) >= ?
            """,
            (mindest,),
        ).fetchall()
    return verbindung.execute(
        """
        SELECT symbol FROM nachrichten
        WHERE wirkung_5 IS NOT NULL
        GROUP BY symbol
        HAVING COUNT(*) >= ?
        """,
        (mindest,),
    ).fetchall()


def _modell_faelle(verbindung: sqlite3.Connection) -> int:
    try:
        zeile = verbindung.execute("SELECT beispiele FROM ki_modell WHERE id = 1").fetchone()
    except sqlite3.OperationalError:
        return 0
    return 0 if zeile is None else int(zeile[0])


def _gruppen(zeilen) -> tuple:
    gruppen: dict[str, dict] = {}
    for url, symbol, zeit, titel, quelle, wirkung_5, rel_5 in zeilen:
        gruppe = gruppen.get(url)
        if gruppe is None:
            gruppe = {"url": url, "titel": titel, "quelle": quelle, "zeit": int(zeit), "symbole": [], "staerke": None}
            gruppen[url] = gruppe
        staerke = None if wirkung_5 is None else abs(float(rel_5 if rel_5 is not None else wirkung_5))
        if staerke is not None and (gruppe["staerke"] is None or staerke > gruppe["staerke"]):
            gruppe["staerke"] = staerke
            gruppe["zeit"] = int(zeit)
        gruppe["symbole"].append(
            {"symbol": symbol, "wirkung": None if wirkung_5 is None else float(wirkung_5), "relativ": None if rel_5 is None else float(rel_5)}
        )
    return tuple(gruppen.values())


def _sicht(gruppe: dict, gemessen: bool) -> dict:
    return {
        "titel": gruppe["titel"],
        "quelle": gruppe["quelle"],
        "zeit": datetime.fromtimestamp(gruppe["zeit"], BERLIN).strftime("%d.%m. %H:%M"),
        "symbole": tuple(
            {
                "symbol": eintrag["symbol"],
                "bewegung": "Wirkung fehlt" if eintrag["wirkung"] is None else de_prozent(eintrag["wirkung"]),
                "zahl": eintrag["wirkung"],
                "relativ": "" if eintrag["relativ"] is None else f"{de_prozent(eintrag['relativ'])} zum Index",
                "markt": index_ging_mit(eintrag["wirkung"], eintrag["relativ"]),
            }
            for eintrag in gruppe["symbole"]
        ),
        "gemessen": gemessen,
    }


def _letzter_abruf(pfad: Path, symbol: str) -> int | None:
    with sqlite3.connect(pfad) as verbindung:
        _tabelle(verbindung)
        zeile = verbindung.execute(
            "SELECT zeit FROM abruf WHERE symbol = ? AND art = ?",
            (symbol, _NEWS_ART),
        ).fetchone()
    return None if zeile is None else int(zeile[0])


def _abruf_merken(pfad: Path, symbol: str, zeit: int) -> None:
    pfad.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(pfad) as verbindung:
        _tabelle(verbindung)
        verbindung.execute(
            """
            INSERT INTO abruf (symbol, art, zeit) VALUES (?, ?, ?)
            ON CONFLICT(symbol, art) DO UPDATE SET zeit = excluded.zeit
            """,
            (symbol, _NEWS_ART, zeit),
        )
