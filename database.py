"""Dauerhafte Signale. Dieselbe Kategorie am selben Tag wird nicht erneut geschrieben."""

import sqlite3
from pathlib import Path


def signal_speichern(
    pfad: Path,
    symbol: str,
    zeit: str,
    kategorie: str,
    preis: float,
    score: int,
    grund: str,
    indikatoren: str,
) -> bool:
    tag = zeit[:10]
    pfad.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(pfad) as verbindung:
        _tabelle(verbindung)
        vorhanden = verbindung.execute(
            "SELECT kategorie, substr(zeit, 1, 10) FROM signale WHERE symbol = ? ORDER BY id DESC LIMIT 1",
            (symbol,),
        ).fetchone()
        if vorhanden is not None and vorhanden[0] == kategorie and vorhanden[1] == tag:
            return False
        verbindung.execute(
            """
            INSERT INTO signale (zeit, symbol, preis, kategorie, score, grund, indikatoren)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (zeit, symbol, preis, kategorie, score, grund, indikatoren),
        )
    return True


def _tabelle(verbindung: sqlite3.Connection) -> None:
    verbindung.execute(
        """
        CREATE TABLE IF NOT EXISTS signale (
            id INTEGER PRIMARY KEY,
            zeit TEXT NOT NULL,
            symbol TEXT NOT NULL,
            preis REAL,
            kategorie TEXT NOT NULL,
            score INTEGER,
            grund TEXT,
            indikatoren TEXT
        )
        """
    )
