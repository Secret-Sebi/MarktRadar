"""Gespeicherte Prognosen. Ohne kalibriertes Modell bleiben die Wahrscheinlichkeiten leer."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

HORIZONTE = ((1, "handel"), (3, "handel"), (5, "handel"), (10, "handel"), (20, "handel"), (30, "kalender"))
TEXT = "Noch keine zuverlässige Prognose möglich"
EMPFEHLUNG = "KEINE AUSREICHENDE DATENBASIS"
_MINDEST = 60
_VERSION = "logistisch-ungeprueft"


def vormerken(pfad: Path, symbol: str, as_of: str, kurszeit: str | None, merkmale: dict, gruende: tuple[str, ...]) -> int:
    """Legt je Horizont eine Zeile an. Vorhandene Zeilen werden nicht geändert."""
    pfad.parent.mkdir(parents=True, exist_ok=True)
    neu = 0
    with sqlite3.connect(pfad) as verbindung:
        _tabellen(verbindung)
        for horizont, art in HORIZONTE:
            cursor = verbindung.execute(
                """
                INSERT OR IGNORE INTO prognose
                (symbol, horizont, art, as_of, modell_version, p_hoch, p_seit, p_runter, empfehlung, gruende, merkmale, kurszeit)
                VALUES (?, ?, ?, ?, ?, NULL, NULL, NULL, ?, ?, ?, ?)
                """,
                (
                    symbol,
                    horizont,
                    art,
                    as_of,
                    _VERSION,
                    EMPFEHLUNG,
                    " ".join(gruende) or TEXT,
                    json.dumps(merkmale, ensure_ascii=False),
                    kurszeit,
                ),
            )
            neu += cursor.rowcount
    return neu


def empfehlung(daten_ok: bool, nachrichten: int, chance: float | None) -> tuple[str, str]:
    """Eine Nachricht oder eine Chance über 50 % ist kein Kauf."""
    del daten_ok, nachrichten, chance
    return EMPFEHLUNG, TEXT


def liste(pfad: Path) -> list[dict]:
    if not pfad.exists():
        return []
    with sqlite3.connect(pfad) as verbindung:
        _tabellen(verbindung)
        zeilen = verbindung.execute(
            """
            SELECT id, symbol, horizont, art, as_of, modell_version, p_hoch, p_seit, p_runter,
                   empfehlung, gruende, kurszeit
            FROM prognose ORDER BY as_of, symbol, art, horizont
            """
        ).fetchall()
    return [
        {
            "id": nummer,
            "symbol": symbol,
            "horizont": horizont,
            "art": art,
            "as_of": as_of,
            "modell_version": version,
            "p_hoch": p_hoch,
            "p_seit": p_seit,
            "p_runter": p_runter,
            "empfehlung": entscheidung,
            "gruende": gruende,
            "kurszeit": kurszeit,
            "text": TEXT if p_hoch is None else "",
        }
        for nummer, symbol, horizont, art, as_of, version, p_hoch, p_seit, p_runter, entscheidung, gruende, kurszeit in zeilen
    ]


def bewerten(pfad: Path, kurse: dict[str, list[tuple[int, float]]], jetzt: datetime) -> int:
    """Schreibt den späteren Kurs dazu. Die Prognosezeile bleibt unverändert."""
    if not pfad.exists():
        return 0
    moment = jetzt.astimezone(timezone.utc)  # noqa: UP017
    neu = 0
    with sqlite3.connect(pfad) as verbindung:
        _tabellen(verbindung)
        offen = verbindung.execute(
            """
            SELECT id, symbol, horizont, art, as_of FROM prognose
            WHERE id NOT IN (SELECT prognose_id FROM prognose_ausgang)
            """
        ).fetchall()
        for nummer, symbol, horizont, art, as_of in offen:
            start = _unix(as_of)
            if start is None:
                continue
            bewegung = _bewegung(kurse.get(symbol) or [], start, int(horizont), str(art), moment)
            if bewegung is None:
                continue
            richtung = "seit" if bewegung == 0 else "hoch" if bewegung > 0 else "runter"
            verbindung.execute(
                """
                INSERT INTO prognose_ausgang (prognose_id, bewegung, richtung, bewertet_am)
                VALUES (?, ?, ?, ?)
                """,
                (nummer, bewegung, richtung, moment.isoformat()),
            )
            neu += 1
    return neu


def qualitaet(pfad: Path) -> dict:
    leer = {"status": "Nicht ausreichend Daten", "anzahl": 0, "erfolg": None, "brier": None, "text": TEXT}
    if not pfad.exists():
        return leer
    with sqlite3.connect(pfad) as verbindung:
        _tabellen(verbindung)
        zeilen = verbindung.execute(
            """
            SELECT p.p_hoch, p.p_seit, p.p_runter, a.richtung
            FROM prognose AS p JOIN prognose_ausgang AS a ON a.prognose_id = p.id
            """
        ).fetchall()
    voll = [zeile for zeile in zeilen if None not in zeile[:3]]
    if len(voll) < _MINDEST:
        return {**leer, "anzahl": len(zeilen)}
    treffer = 0
    brier = 0.0
    for p_hoch, p_seit, p_runter, richtung in voll:
        ziel = {"hoch": (1.0, 0.0, 0.0), "seit": (0.0, 1.0, 0.0), "runter": (0.0, 0.0, 1.0)}.get(str(richtung))
        if ziel is None:
            return {**leer, "anzahl": len(voll)}
        prognose = max(("hoch", p_hoch), ("seit", p_seit), ("runter", p_runter), key=lambda paar: paar[1])[0]
        if prognose == richtung:
            treffer += 1
        brier += sum((wert - ziel_wert) ** 2 for wert, ziel_wert in zip((p_hoch, p_seit, p_runter), ziel))
    return {
        "status": "gemessen",
        "anzahl": len(voll),
        "erfolg": treffer / len(voll),
        "brier": brier / len(voll),
        "text": f"Success Rate {treffer / len(voll) * 100:.1f} % aus {len(voll)} ausgewerteten Prognosen. Das ist kein Gewinnversprechen.",
    }


def _bewegung(balken: list[tuple[int, float]], start: int, horizont: int, art: str, jetzt: datetime) -> float | None:
    reihe = sorted((int(zeit), float(preis)) for zeit, preis in balken if preis and preis > 0 and int(zeit) <= int(jetzt.timestamp()))
    vorher = [paar for paar in reihe if paar[0] <= start]
    if not vorher or not vorher[-1][1]:
        return None
    if art == "kalender":
        ziel = start + horizont * 86400
        if jetzt.timestamp() < ziel:
            return None
        spaeter = [paar for paar in reihe if paar[0] >= ziel]
    else:
        danach = [paar for paar in reihe if paar[0] > start]
        if len(danach) < horizont or jetzt.timestamp() < danach[horizont - 1][0]:
            return None
        spaeter = [danach[horizont - 1]]
    if not spaeter:
        return None
    return (spaeter[0][1] / vorher[-1][1] - 1.0) * 100.0


def _unix(wert: str) -> int | None:
    try:
        stempel = datetime.fromisoformat(str(wert))
    except ValueError:
        return None
    if stempel.tzinfo is None:
        stempel = stempel.replace(tzinfo=timezone.utc)  # noqa: UP017
    return int(stempel.timestamp())


def _tabellen(verbindung: sqlite3.Connection) -> None:
    verbindung.execute(
        """
        CREATE TABLE IF NOT EXISTS prognose (
            id INTEGER PRIMARY KEY,
            symbol TEXT NOT NULL,
            horizont INTEGER NOT NULL,
            art TEXT NOT NULL,
            as_of TEXT NOT NULL,
            modell_version TEXT NOT NULL,
            p_hoch REAL,
            p_seit REAL,
            p_runter REAL,
            empfehlung TEXT NOT NULL,
            gruende TEXT NOT NULL,
            merkmale TEXT NOT NULL,
            kurszeit TEXT,
            UNIQUE (symbol, horizont, art, as_of)
        )
        """
    )
    verbindung.execute(
        """
        CREATE TABLE IF NOT EXISTS prognose_ausgang (
            id INTEGER PRIMARY KEY,
            prognose_id INTEGER NOT NULL UNIQUE,
            bewegung REAL NOT NULL,
            richtung TEXT NOT NULL,
            bewertet_am TEXT NOT NULL
        )
        """
    )


def kalender_ziel(start: datetime, tage: int = 30) -> datetime:
    return start.astimezone(timezone.utc) + timedelta(days=tage)  # noqa: UP017
