"""Speichert Meldungen und die danach gemessene Kursbewegung.

Die Kategorie sagt nur, worum es geht. Ob das den Kurs gedrückt hat,
steht erst fest, wenn spätere echte Kurse vorliegen.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote
from urllib.request import urlopen

from analyse import de_zahl
from quellen import hole_text

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


def nachtragen(pfad: Path, symbol: str, balken) -> int:
    with sqlite3.connect(pfad) as verbindung:
        _tabelle(verbindung)
        zeilen = verbindung.execute(
            "SELECT id, zeit FROM nachrichten WHERE symbol = ? AND wirkung_5 IS NULL",
            (symbol,),
        ).fetchall()
        geaendert = 0
        for nummer, zeit in zeilen:
            werte = {abstand: wirkung(balken, int(zeit), abstand) for abstand in (1, 3, 5, 20)}
            if werte[5] is None:
                continue
            verbindung.execute(
                """
                UPDATE nachrichten
                SET wirkung_1 = ?, wirkung_3 = ?, wirkung_5 = ?, wirkung_20 = ?
                WHERE id = ?
                """,
                (werte[1], werte[3], werte[5], werte[20], nummer),
            )
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


def aktualisiere(pfad: Path, symbol: str, name: str, balken, oeffnen=urlopen) -> Befund:
    _holen(pfad, symbol, name, oeffnen)
    if pfad.exists():
        nachtragen(pfad, symbol, balken)
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
    return text


def _holen(pfad: Path, symbol: str, name: str, oeffnen) -> None:
    gesammelt: list[Meldung] = []
    yahoo = "https://query2.finance.yahoo.com/v1/finance/search?quotesCount=0&newsCount=6&q=" + quote(symbol)
    gdelt = (
        "https://api.gdeltproject.org/api/v2/doc/doc?mode=artlist&format=json&maxrecords=8&timespan=7d&query="
        + quote(name or symbol)
    )
    for adresse, leser, nur_passende in ((yahoo, aus_yahoo, False), (gdelt, aus_gdelt, True)):
        try:
            meldungen = leser(json.loads(hole_text(adresse, oeffnen, "application/json")))
        except (ConnectionError, LookupError, TimeoutError, json.JSONDecodeError, ValueError):
            continue
        if nur_passende:
            meldungen = tuple(meldung for meldung in meldungen if _passt(meldung, symbol, name))
        gesammelt.extend(meldungen)
    if gesammelt:
        speichern(pfad, symbol, tuple(gesammelt))


def _passt(meldung: Meldung, symbol: str, name: str) -> bool:
    text = meldung.titel.lower()
    if symbol.lower() in text:
        return True
    token = name.split()[0].lower() if name else ""
    return len(token) > 2 and token in text


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
            url TEXT NOT NULL UNIQUE,
            symbol TEXT NOT NULL,
            zeit INTEGER NOT NULL,
            titel TEXT NOT NULL,
            quelle TEXT NOT NULL,
            kategorie TEXT NOT NULL,
            wirkung_1 REAL,
            wirkung_3 REAL,
            wirkung_5 REAL,
            wirkung_20 REAL
        )
        """
    )
