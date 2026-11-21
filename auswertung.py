"""Gespeicherte Auswertungen. Ruhige Namen bleiben hier, auch wenn sie nicht angezeigt werden."""

from __future__ import annotations

import sqlite3
import time
from datetime import datetime
from pathlib import Path

from analyse import BERLIN, ist_wichtig

_FELDER = (
    "symbol",
    "name",
    "preis",
    "wert",
    "tag",
    "tag_wert",
    "richtung",
    "herkunft",
    "fenster",
    "pruefung",
    "folge",
    "datenstatus",
    "bereich",
    "kurszeit",
    "ungewoehnlich",
    "markt",
)


def merken(pfad: Path, karten) -> None:
    pfad.parent.mkdir(parents=True, exist_ok=True)
    moment = int(time.time())
    with sqlite3.connect(pfad) as verbindung:
        _tabelle(verbindung)
        for karte in karten:
            symbol = str(karte.get("symbol") or "").strip().upper()
            if not symbol:
                continue
            werte = tuple(karte.get(feld) for feld in _FELDER)
            verbindung.execute(
                f"""
                INSERT INTO auswertung ({", ".join(_FELDER)}, aktualisiert)
                VALUES ({", ".join("?" for _ in _FELDER)}, ?)
                ON CONFLICT(symbol) DO UPDATE SET
                {", ".join(f"{feld} = excluded.{feld}" for feld in _FELDER[1:])},
                aktualisiert = excluded.aktualisiert
                """,
                (*werte, moment),
            )


def sichtbar(pfad: Path, jetzt: int | None = None) -> tuple[dict, ...]:
    moment = int(time.time()) if jetzt is None else int(jetzt)
    return tuple(
        karte
        for karte in alle(pfad)
        if ist_wichtig(
            karte["fenster"],
            karte["tag_wert"],
            karte["datenstatus"],
            karte.get("kurszeit"),
            moment,
            karte.get("ungewoehnlich") or "",
        )
    )


def runde_groesse(fehlend: int) -> int:
    return 80 if int(fehlend) > 40 else 40


def pause_bei_luecke(naechste: int, fehlend: int) -> int:
    warte = int(naechste)
    if int(fehlend) > 0:
        return min(warte, 60)
    return warte


def runde_symbole(
    offen: tuple[str, ...],
    zuerst: tuple[str, ...],
    groesse: int = 40,
    sofort: tuple[str, ...] = (),
) -> tuple[str, ...]:
    vorgezogen = set(offen) | set(sofort)
    vorne = [symbol for symbol in zuerst if symbol in vorgezogen]
    gesehen = set(vorne)
    danach = [symbol for symbol in sofort if symbol not in gesehen]
    gesehen.update(danach)
    rest = [symbol for symbol in offen if symbol not in gesehen]
    return tuple((vorne + danach + rest)[:groesse])


def mess_runde(pfad: Path, universum: tuple[str, ...], watchlist: tuple[str, ...], jetzt: int) -> tuple[str, ...]:
    from lernen import ohne_langen_abruf

    fehlend = ohne_langen_abruf(pfad, tuple(universum))
    sofort = tuple(dict.fromkeys(noch_nicht_beurteilt(pfad, tuple(watchlist)) + fehlend))
    return runde_symbole(
        faellig(pfad, tuple(universum), jetzt),
        tuple(watchlist),
        runde_groesse(len(fehlend)),
        sofort,
    )


def noch_nicht_beurteilt(pfad: Path, symbole: tuple[str, ...]) -> tuple[str, ...]:
    if not symbole or not pfad.exists():
        return tuple(symbole)
    with sqlite3.connect(pfad) as verbindung:
        _tabelle(verbindung)
        zeilen = verbindung.execute("SELECT symbol, ungewoehnlich FROM auswertung").fetchall()
    bekannt = {str(symbol): wert for symbol, wert in zeilen}
    return tuple(symbol for symbol in symbole if symbol not in bekannt or bekannt[symbol] is None)


def mit_kurszeit(pfad: Path, jetzt: int, stunden: int = 36) -> int:
    if not pfad.exists():
        return 0
    grenze = int(jetzt) - stunden * 3600
    with sqlite3.connect(pfad) as verbindung:
        _tabelle(verbindung)
        zeile = verbindung.execute(
            "SELECT COUNT(*) FROM auswertung WHERE kurszeit IS NOT NULL AND kurszeit >= ?",
            (grenze,),
        ).fetchone()
    return int(zeile[0] or 0)


def faellig(pfad: Path, symbole: tuple[str, ...], jetzt: int, stunden: int = 6) -> tuple[str, ...]:
    zeiten = _zeiten(pfad)
    grenze = int(jetzt) - stunden * 3600
    alt = [symbol for symbol in symbole if zeiten.get(symbol, 0) < grenze]
    return tuple(sorted(alt, key=lambda symbol: zeiten.get(symbol, 0)))


def alle(pfad: Path) -> tuple[dict, ...]:
    if not pfad.exists():
        return ()
    with sqlite3.connect(pfad) as verbindung:
        _tabelle(verbindung)
        zeilen = verbindung.execute(
            f"SELECT {', '.join(_FELDER)}, aktualisiert FROM auswertung ORDER BY name"
        ).fetchall()
    return tuple(_karte(zeile) for zeile in zeilen)


def anzahl(pfad: Path) -> int:
    if not pfad.exists():
        return 0
    with sqlite3.connect(pfad) as verbindung:
        _tabelle(verbindung)
        zeile = verbindung.execute("SELECT COUNT(*) FROM auswertung").fetchone()
    return int(zeile[0] or 0)


def _karte(zeile) -> dict:
    karte = dict(zip((*_FELDER, "aktualisiert"), zeile))
    if karte["pruefung"] is None:
        karte["fenster"] = ""
    karte["fenster"] = karte["fenster"] or ""
    karte["pruefung"] = karte["pruefung"] or ""
    karte["folge"] = karte["folge"] or ""
    karte["ungewoehnlich"] = karte["ungewoehnlich"] or ""
    karte["markt"] = karte["markt"] or ""
    karte["datenstatus"] = karte["datenstatus"] or ""
    stempel = karte.get("aktualisiert")
    if isinstance(stempel, int) and not isinstance(stempel, bool):
        text = datetime.fromtimestamp(stempel, BERLIN).strftime("%d.%m. %H:%M")
        karte["herkunft"] = f"{karte['herkunft']} · gespeichert {text}"
    return karte


def _zeiten(pfad: Path) -> dict[str, int]:
    if not pfad.exists():
        return {}
    with sqlite3.connect(pfad) as verbindung:
        _tabelle(verbindung)
        zeilen = verbindung.execute("SELECT symbol, aktualisiert FROM auswertung").fetchall()
    return {str(symbol): int(zeit or 0) for symbol, zeit in zeilen}


def _tabelle(verbindung: sqlite3.Connection) -> None:
    verbindung.execute(
        """
        CREATE TABLE IF NOT EXISTS auswertung (
            symbol TEXT PRIMARY KEY,
            name TEXT,
            preis TEXT,
            wert REAL,
            tag TEXT,
            tag_wert REAL,
            richtung TEXT,
            herkunft TEXT,
            fenster TEXT,
            pruefung TEXT,
            folge TEXT,
            datenstatus TEXT,
            bereich TEXT,
            kurszeit INTEGER,
            ungewoehnlich TEXT,
            aktualisiert INTEGER NOT NULL
        )
        """
    )
    vorhanden = {str(zeile[1]) for zeile in verbindung.execute("PRAGMA table_info(auswertung)")}
    for name, art in (
        ("pruefung", "TEXT"),
        ("folge", "TEXT"),
        ("kurszeit", "INTEGER"),
        ("ungewoehnlich", "TEXT"),
        ("markt", "TEXT"),
        ("hinweis_stand", "TEXT"),
    ):
        if name not in vorhanden:
            verbindung.execute(f"ALTER TABLE auswertung ADD COLUMN {name} {art}")


def sende_hinweise(pfad: Path, karten, liste: tuple[str, ...], hinweis, grenze: int = 3) -> int:
    erlaubt = set(liste)
    stand = _hinweis_stand(pfad)
    gesendet = 0
    for karte in karten:
        symbol = str(karte.get("symbol") or "")
        if symbol not in erlaubt:
            continue
        text = str(karte.get("ungewoehnlich") or karte.get("fenster") or "")
        if not text:
            if stand.get(symbol):
                _setze_hinweis_stand(pfad, symbol, "")
            continue
        if stand.get(symbol) == text or gesendet >= grenze:
            continue
        name = str(karte.get("name") or symbol)
        hinweis(f"{name} ist ungewöhnlich", f"{text} Das ist kein Auftrag.")
        _setze_hinweis_stand(pfad, symbol, text)
        gesendet += 1
    return gesendet


def _hinweis_stand(pfad: Path) -> dict[str, str]:
    if not pfad.exists():
        return {}
    with sqlite3.connect(pfad) as verbindung:
        _tabelle(verbindung)
        zeilen = verbindung.execute(
            "SELECT symbol, hinweis_stand FROM auswertung WHERE hinweis_stand IS NOT NULL"
        ).fetchall()
    return {str(symbol): str(text or "") for symbol, text in zeilen}


def _setze_hinweis_stand(pfad: Path, symbol: str, text: str) -> None:
    with sqlite3.connect(pfad) as verbindung:
        _tabelle(verbindung)
        verbindung.execute("UPDATE auswertung SET hinweis_stand = ? WHERE symbol = ?", (text, symbol))
