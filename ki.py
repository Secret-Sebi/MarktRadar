"""Kleines Modell, das seine Gewichte aus abgeschlossenen Fällen nachzieht.

Eingaben sind nur Kurse, die vor der Meldung lagen. Die Antwort ist,
ob der nächste Handelstag höher schloss. Liegt der noch nicht vor,
nimmt es die Bewegung nach fünf Tagen.
"""

from __future__ import annotations

import json
import math
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from analyse import rsi, sma

_THEMEN = ("zinsen", "geopolitik", "quartal", "rohstoff", "krypto", "uebernahme")
_MINDEST = 12
_EINFLUSS = 60
_RATE = 0.2


@dataclass(frozen=True)
class Modell:
    gewichte: tuple[float, ...]
    bias: float
    beispiele: int


def leeres_modell() -> Modell:
    return Modell((0.0,) * (len(_THEMEN) + 2), 0.0, 0)


def merkmale(balken, zeitpunkt: int | None, thema: str) -> tuple[float, ...] | None:
    schluesse = tuple(
        bar.schluss
        for bar in sorted(balken, key=lambda bar: bar.zeit or 0)
        if bar.zeit is not None and (zeitpunkt is None or bar.zeit < zeitpunkt) and bar.schluss > 0
    )
    if len(schluesse) < 20:
        return None
    rsi_wert = rsi(schluesse, 14)
    linie = sma(schluesse, 20)
    if rsi_wert is None or linie is None or linie == 0:
        return None
    thema_werte = tuple(1.0 if name == thema else 0.0 for name in _THEMEN)
    return thema_werte + (max(0.0, min(1.0, rsi_wert / 100.0)), 1.0 if schluesse[-1] > linie else 0.0)


def schritt(modell: Modell, eingabe: tuple[float, ...], ziel: float) -> Modell:
    chance = wahrscheinlichkeit(modell, eingabe)
    fehler = chance - ziel
    gewichte = tuple(
        max(-5.0, min(5.0, gewicht - _RATE * fehler * wert))
        for gewicht, wert in zip(modell.gewichte, eingabe)
    )
    bias = max(-5.0, min(5.0, modell.bias - _RATE * fehler))
    return Modell(gewichte, bias, modell.beispiele + 1)


def wahrscheinlichkeit(modell: Modell, eingabe: tuple[float, ...]) -> float:
    summe = modell.bias + sum(gewicht * wert for gewicht, wert in zip(modell.gewichte, eingabe))
    if summe > 20:
        return 1.0
    if summe < -20:
        return 0.0
    return 1.0 / (1.0 + math.exp(-summe))


def trainiere(pfad: Path, symbol: str, balken) -> Modell:
    pfad.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(pfad) as verbindung:
        _tabellen(verbindung)
        modell = _lesen(verbindung)
        zeilen = verbindung.execute(
            """
            SELECT id, zeit, kategorie, wirkung_1, wirkung_5 FROM nachrichten
            WHERE symbol = ? AND ki_genutzt = 0 AND (wirkung_1 IS NOT NULL OR wirkung_5 IS NOT NULL)
            ORDER BY zeit
            """,
            (symbol,),
        ).fetchall()
        schon = verbindung.execute(
            "SELECT zeit FROM nachrichten WHERE symbol = ? AND ki_genutzt = 1",
            (symbol,),
        ).fetchall()
        gesehene_tage = {int(zeit) // 86400 for (zeit,) in schon}
        for nummer, zeit, thema, wirkung_1, wirkung_5 in zeilen:
            tag = int(zeit) // 86400
            if tag in gesehene_tage:
                verbindung.execute("UPDATE nachrichten SET ki_genutzt = 1 WHERE id = ?", (nummer,))
                continue
            bewegung = wirkung_1 if wirkung_1 is not None else wirkung_5
            eingabe = merkmale(balken, int(zeit), str(thema))
            if eingabe is None or bewegung is None:
                continue
            modell = schritt(modell, eingabe, 1.0 if float(bewegung) > 0 else 0.0)
            gesehene_tage.add(tag)
            verbindung.execute("UPDATE nachrichten SET ki_genutzt = 1 WHERE id = ?", (nummer,))
        _schreiben(verbindung, modell)
    return modell


def messe(pfad: Path, symbol: str, balken) -> tuple[int, int] | None:
    if not pfad.exists():
        return None
    with sqlite3.connect(pfad) as verbindung:
        _tabellen(verbindung)
        zeilen = verbindung.execute(
            """
            SELECT zeit, kategorie, wirkung_5 FROM nachrichten
            WHERE symbol = ? AND wirkung_5 IS NOT NULL AND kategorie != 'unklar'
            ORDER BY zeit
            """,
            (symbol,),
        ).fetchall()
    paare = []
    for zeit, thema, wirkung_5 in zeilen:
        eingabe = merkmale(balken, int(zeit), str(thema))
        if eingabe is None:
            continue
        paare.append((eingabe, 1 if float(wirkung_5) > 0 else 0))
    return trefferquote(tuple(paare))


def schaetzung(modell: Modell, balken, thema: str) -> float | None:
    if modell.beispiele < _MINDEST:
        return None
    eingabe = merkmale(balken, None, thema)
    if eingabe is None:
        return None
    return wahrscheinlichkeit(modell, eingabe)


def trefferquote(faelle: tuple[tuple[tuple[float, ...], int], ...]) -> tuple[int, int] | None:
    if len(faelle) < _MINDEST * 2:
        return None
    trainingsende = len(faelle) - _MINDEST
    modell = leeres_modell()
    for eingabe, ziel in faelle[:trainingsende]:
        modell = schritt(modell, eingabe, float(ziel))
    treffer = 0
    for eingabe, ziel in faelle[trainingsende:]:
        prognose = 1 if wahrscheinlichkeit(modell, eingabe) >= 0.5 else 0
        if prognose == ziel:
            treffer += 1
    return treffer, _MINDEST


def bekanntes_thema(name: str) -> str:
    return name if name in _THEMEN else "unklar"


def eigene_entscheidung(modell: Modell, balken, thema: str) -> tuple[bool, str]:
    if modell.beispiele < _MINDEST:
        return False, (
            f"Das Modell hat {modell.beispiele} abgeschlossene Tage. "
            f"Unter {_MINDEST} entscheidet es noch nicht."
        )
    eingabe = merkmale(balken, None, thema)
    if eingabe is None:
        return False, "Dem Modell fehlen die Kurse vor der Entscheidung."
    chance = wahrscheinlichkeit(modell, eingabe)
    if chance >= 0.5:
        return True, f"Das Modell entscheidet selbst für einen Kauf. Es hat {modell.beispiele} abgeschlossene Tage gesehen."
    return False, f"Das Modell entscheidet selbst dagegen. Es hat {modell.beispiele} abgeschlossene Tage gesehen."


def lies_modell(pfad: Path) -> Modell:
    if not pfad.exists():
        return leeres_modell()
    with sqlite3.connect(pfad) as verbindung:
        _tabellen(verbindung)
        return _lesen(verbindung)


def setze_modell(pfad: Path, modell: Modell) -> None:
    pfad.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(pfad) as verbindung:
        _tabellen(verbindung)
        _schreiben(verbindung, modell)


def lerne_ausgang(pfad: Path, balken, thema: str, zeitpunkt: int, ziel: float) -> Modell | None:
    eingabe = merkmale(balken, zeitpunkt, thema)
    if eingabe is None:
        return None
    with sqlite3.connect(pfad) as verbindung:
        _tabellen(verbindung)
        modell = schritt(_lesen(verbindung), eingabe, ziel)
        _schreiben(verbindung, modell)
    return modell


def aktion_aus_ki(
    aktion: str,
    modell: Modell,
    chance: float | None,
    daten_ok: bool,
    pruefung: tuple[int, int] | None = None,
) -> str:
    del modell, chance, daten_ok, pruefung
    return aktion


def ki_satz(modell: Modell, chance: float | None, pruefung: tuple[int, int] | None = None) -> str:
    del chance, pruefung
    if modell.beispiele == 0:
        return (
            "Das Modell hat noch keinen Handelstag ausgewertet. "
            "Es lernt, sobald nach einer Meldung der nächste Handelstag da ist. "
            "Ein kurzes Fenster kommt aus den geladenen Kursen, nicht aus dieser Zahl."
        )
    return (
        f"Das Modell hat {modell.beispiele} Handelstage ausgewertet: ob der nächste Tag höher schloss. "
        f"Unter {_EINFLUSS} Tagen bleibt das eine kleine Stichprobe. "
        "Ein kurzes Fenster bleibt eine Lesart der Kurse, kein Auftrag."
    )


def _tabellen(verbindung: sqlite3.Connection) -> None:
    verbindung.execute(
        """
        CREATE TABLE IF NOT EXISTS ki_modell (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            gewichte TEXT NOT NULL,
            bias REAL NOT NULL,
            beispiele INTEGER NOT NULL
        )
        """
    )
    spalten = {str(zeile[1]) for zeile in verbindung.execute("PRAGMA table_info(nachrichten)")}
    if spalten and "ki_genutzt" not in spalten:
        verbindung.execute("ALTER TABLE nachrichten ADD COLUMN ki_genutzt INTEGER NOT NULL DEFAULT 0")


def _lesen(verbindung: sqlite3.Connection) -> Modell:
    zeile = verbindung.execute("SELECT gewichte, bias, beispiele FROM ki_modell WHERE id = 1").fetchone()
    if zeile is None:
        return leeres_modell()
    return Modell(tuple(float(wert) for wert in json.loads(zeile[0])), float(zeile[1]), int(zeile[2]))


def _schreiben(verbindung: sqlite3.Connection, modell: Modell) -> None:
    verbindung.execute(
        """
        INSERT INTO ki_modell (id, gewichte, bias, beispiele) VALUES (1, ?, ?, ?)
        ON CONFLICT(id) DO UPDATE SET gewichte = excluded.gewichte, bias = excluded.bias, beispiele = excluded.beispiele
        """,
        (json.dumps(modell.gewichte), modell.bias, modell.beispiele),
    )
