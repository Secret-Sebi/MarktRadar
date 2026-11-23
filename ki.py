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


_HORIZONTE = (1, 3, 5, 20)


def trainiere(pfad: Path, symbol: str, balken, pruefen: bool = True) -> Modell:
    """Trainiert jeden Horizont getrennt. Das alte gemischte Modell bleibt unangetastet."""
    pfad.parent.mkdir(parents=True, exist_ok=True)
    neu = False
    with sqlite3.connect(pfad) as verbindung:
        _tabellen(verbindung)
        zeilen = verbindung.execute(
            """
            SELECT id, zeit, kategorie, wirkung_1, wirkung_3, wirkung_5, wirkung_20
            FROM nachrichten WHERE symbol = ? ORDER BY zeit, id
            """,
            (symbol,),
        ).fetchall()
        modelle = {horizont: _horizont_lesen(verbindung, horizont) for horizont in _HORIZONTE}
        tage = {horizont: _trainierte_tage(verbindung, symbol, horizont) for horizont in _HORIZONTE}
        for nummer, zeit, thema, *wirkungen in zeilen:
            wirkung = dict(zip(_HORIZONTE, wirkungen))
            for horizont in _HORIZONTE:
                if _beispiel_vorhanden(verbindung, int(nummer), horizont):
                    continue
                bewegung = wirkung[horizont]
                if bewegung is None:
                    continue
                tag = int(zeit) // 86400
                if tag in tage[horizont]:
                    _beispiel(verbindung, int(nummer), horizont, int(zeit), "ausgeschlossen", "Gleicher Kalendertag, erstes Beispiel zählt", None, None)
                    continue
                try:
                    eingabe = merkmale(balken, int(zeit), str(thema))
                except (TypeError, ValueError):
                    _beispiel(verbindung, int(nummer), horizont, int(zeit), "fehler", "Merkmale konnten nicht gebaut werden", None, None)
                    continue
                if eingabe is None:
                    _beispiel(verbindung, int(nummer), horizont, int(zeit), "ausgeschlossen", "Zum Meldungszeitpunkt liegen keine 20 Kurse davor", None, None)
                    continue
                ziel = 1.0 if float(bewegung) > 0 else 0.0
                modelle[horizont] = schritt(modelle[horizont], eingabe, ziel)
                tage[horizont].add(tag)
                _beispiel(verbindung, int(nummer), horizont, int(zeit), "trainiert", "Trainiert auf diesem Horizont", ziel, eingabe)
                if horizont == 1:
                    verbindung.execute("UPDATE nachrichten SET ki_genutzt = 1 WHERE id = ?", (nummer,))
                neu = True
        for horizont, modell in modelle.items():
            _horizont_schreiben(verbindung, horizont, modell)
    if neu and pruefen:
        _validiere_wenn_faellig(pfad)
    return _horizont_modell(pfad, 1)


def validiere_jetzt(pfad: Path) -> None:
    _validiere_wenn_faellig(pfad, True)


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


def lerne_merkmale(pfad: Path, eingabe: tuple[float, ...], ziel: float) -> Modell | None:
    if not eingabe:
        return None
    pfad.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(pfad) as verbindung:
        _tabellen(verbindung)
        modell = schritt(_lesen(verbindung), eingabe, ziel)
        _schreiben(verbindung, modell)
    return modell


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


def ki_satz(modell: Modell, chance: float | None, pruefung: tuple[int, int] | None = None, geprueft: bool = False) -> str:
    del chance, pruefung
    freigabe = "Horizont 1 ist geprüft." if geprueft else "Kein Horizont ist freigegeben."
    if modell.beispiele == 0:
        return (
            "Das Modell hat noch keinen Handelstag ausgewertet. "
            "Es lernt, sobald nach einer Meldung der nächste Handelstag da ist. "
            f"{freigabe} Ein kurzes Fenster kommt aus den geladenen Kursen, nicht aus dieser Zahl."
        )
    return (
        f"Das Modell hat {modell.beispiele} Handelstage ausgewertet: ob der nächste Tag höher schloss. "
        f"Unter {_EINFLUSS} Tagen bleibt das eine kleine Stichprobe. "
        f"{freigabe} Ein kurzes Fenster bleibt eine Lesart der Kurse, kein Auftrag."
    )


def freigegeben(pfad: Path, horizont: int = 1) -> bool:
    if not pfad.exists():
        return False
    with sqlite3.connect(pfad) as verbindung:
        _tabellen(verbindung)
        zeile = verbindung.execute(
            "SELECT validiert FROM ki_horizont WHERE horizont = ?",
            (horizont,),
        ).fetchone()
    return bool(zeile and zeile[0])


def modell_fuer_anzeige(pfad: Path, horizont: int = 1) -> Modell | None:
    if not freigegeben(pfad, horizont):
        return None
    with sqlite3.connect(pfad) as verbindung:
        _tabellen(verbindung)
        zeile = verbindung.execute(
            "SELECT einsatz_gewichte, einsatz_bias, beispiele FROM ki_horizont WHERE horizont = ?",
            (horizont,),
        ).fetchone()
    if zeile is None or not zeile[0]:
        return None
    return Modell(tuple(float(wert) for wert in json.loads(zeile[0])), float(zeile[1]), int(zeile[2]))


def nachweis(pfad: Path) -> dict:
    leer = {"trainiert": 0, "ausgeschlossen": 0, "fehler": 0, "freigegeben": []}
    if not pfad.exists():
        return leer
    with sqlite3.connect(pfad) as verbindung:
        _tabellen(verbindung)
        tabellen = {zeile[0] for zeile in verbindung.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
        if "ki_beispiel" not in tabellen:
            return leer
        for status, anzahl in verbindung.execute("SELECT status, COUNT(*) FROM ki_beispiel GROUP BY status"):
            if status in leer:
                leer[status] = int(anzahl)
        leer["freigegeben"] = [
            int(horizont)
            for (horizont,) in verbindung.execute("SELECT horizont FROM ki_horizont WHERE validiert = 1 ORDER BY horizont")
        ]
    return leer


def _validiere_wenn_faellig(pfad: Path, erzwingen: bool = False) -> None:
    import time

    from ki_pruefung import pruefe_faelle

    with sqlite3.connect(pfad) as verbindung:
        _tabellen(verbindung)
        for horizont in _HORIZONTE:
            zeile = verbindung.execute(
                "SELECT pruefung FROM ki_horizont WHERE horizont = ?",
                (horizont,),
            ).fetchone()
            vorher = {}
            if zeile and zeile[0]:
                try:
                    vorher = json.loads(zeile[0])
                except json.JSONDecodeError:
                    vorher = {}
            faelle = tuple(
                (int(zeit), tuple(float(wert) for wert in json.loads(merkmale)), float(ziel))
                for zeit, merkmale, ziel in verbindung.execute(
                    """
                    SELECT zeit, merkmale, ziel FROM ki_beispiel
                    WHERE horizont = ? AND status = 'trainiert' AND merkmale IS NOT NULL AND ziel IS NOT NULL
                    ORDER BY zeit, nachricht_id
                    """,
                    (horizont,),
                )
            )
            if len(faelle) < 108 and not erzwingen:
                bericht = {
                    "bestanden": False,
                    "grund": "Nicht ausreichend trainiert",
                    "n": len(faelle),
                    "brier": None,
                    "logloss": None,
                    "basis_brier": None,
                    "basis_logloss": None,
                    "kalibrierung": None,
                }
            elif not erzwingen and isinstance(vorher.get("zeit"), int) and time.time() - vorher["zeit"] < 900 and vorher.get("n") == len(faelle):
                continue
            else:
                bericht = pruefe_faelle(faelle)
            bericht["zeit"] = int(time.time())
            gewichte = bericht.pop("gewichte", None)
            bias = bericht.pop("bias", None)
            verbindung.execute(
                """
                UPDATE ki_horizont
                SET validiert = ?, pruefung = ?, einsatz_gewichte = ?, einsatz_bias = ?
                WHERE horizont = ?
                """,
                (
                    1 if bericht["bestanden"] else 0,
                    json.dumps(bericht, ensure_ascii=False),
                    None if gewichte is None else json.dumps(gewichte),
                    bias,
                    horizont,
                ),
            )


def _horizont_modell(pfad: Path, horizont: int) -> Modell:
    if not pfad.exists():
        return leeres_modell()
    with sqlite3.connect(pfad) as verbindung:
        _tabellen(verbindung)
        return _horizont_lesen(verbindung, horizont)


def _horizont_lesen(verbindung: sqlite3.Connection, horizont: int) -> Modell:
    zeile = verbindung.execute(
        "SELECT gewichte, bias, beispiele FROM ki_horizont WHERE horizont = ?",
        (horizont,),
    ).fetchone()
    if zeile is None:
        return leeres_modell()
    return Modell(tuple(float(wert) for wert in json.loads(zeile[0])), float(zeile[1]), int(zeile[2]))


def _horizont_schreiben(verbindung: sqlite3.Connection, horizont: int, modell: Modell) -> None:
    verbindung.execute(
        """
        INSERT INTO ki_horizont (horizont, gewichte, bias, beispiele, validiert, pruefung)
        VALUES (?, ?, ?, ?, 0, '')
        ON CONFLICT(horizont) DO UPDATE SET
            gewichte = excluded.gewichte, bias = excluded.bias, beispiele = excluded.beispiele
        """,
        (horizont, json.dumps(modell.gewichte), modell.bias, modell.beispiele),
    )


def _trainierte_tage(verbindung: sqlite3.Connection, symbol: str, horizont: int) -> set[int]:
    zeilen = verbindung.execute(
        """
        SELECT n.zeit FROM ki_beispiel b
        JOIN nachrichten n ON n.id = b.nachricht_id
        WHERE n.symbol = ? AND b.horizont = ? AND b.status = 'trainiert'
        """,
        (symbol, horizont),
    ).fetchall()
    return {int(zeit) // 86400 for (zeit,) in zeilen}


def _beispiel_vorhanden(verbindung: sqlite3.Connection, nummer: int, horizont: int) -> bool:
    zeile = verbindung.execute(
        "SELECT 1 FROM ki_beispiel WHERE nachricht_id = ? AND horizont = ?",
        (nummer, horizont),
    ).fetchone()
    return zeile is not None


def _beispiel(verbindung, nummer: int, horizont: int, zeit: int, status: str, grund: str, ziel, eingabe) -> None:
    verbindung.execute(
        """
        INSERT INTO ki_beispiel (nachricht_id, horizont, status, grund, ziel, merkmale, zeit)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            nummer,
            horizont,
            status,
            grund,
            ziel,
            None if eingabe is None else json.dumps(eingabe),
            zeit,
        ),
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
    verbindung.execute(
        """
        CREATE TABLE IF NOT EXISTS ki_horizont (
            horizont INTEGER PRIMARY KEY,
            gewichte TEXT NOT NULL,
            bias REAL NOT NULL,
            beispiele INTEGER NOT NULL,
            validiert INTEGER NOT NULL DEFAULT 0,
            pruefung TEXT NOT NULL DEFAULT '',
            einsatz_gewichte TEXT,
            einsatz_bias REAL
        )
        """
    )
    verbindung.execute(
        """
        CREATE TABLE IF NOT EXISTS ki_beispiel (
            nachricht_id INTEGER NOT NULL,
            horizont INTEGER NOT NULL,
            status TEXT NOT NULL,
            grund TEXT NOT NULL,
            ziel REAL,
            merkmale TEXT,
            zeit INTEGER NOT NULL,
            PRIMARY KEY (nachricht_id, horizont)
        )
        """
    )
    spalten = {str(zeile[1]) for zeile in verbindung.execute("PRAGMA table_info(nachrichten)")}
    if spalten and "ki_genutzt" not in spalten:
        verbindung.execute("ALTER TABLE nachrichten ADD COLUMN ki_genutzt INTEGER NOT NULL DEFAULT 0")
    horizont_spalten = {str(zeile[1]) for zeile in verbindung.execute("PRAGMA table_info(ki_horizont)")}
    if horizont_spalten and "einsatz_gewichte" not in horizont_spalten:
        verbindung.execute("ALTER TABLE ki_horizont ADD COLUMN einsatz_gewichte TEXT")
        verbindung.execute("ALTER TABLE ki_horizont ADD COLUMN einsatz_bias REAL")


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
