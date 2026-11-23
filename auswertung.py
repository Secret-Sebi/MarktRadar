"""Gespeicherte Auswertungen. Ruhige Namen bleiben hier, auch wenn sie nicht angezeigt werden."""

from __future__ import annotations

import json
import re
import sqlite3
import time
from collections.abc import Sequence
from datetime import datetime
from pathlib import Path

from analyse import BERLIN, ist_wichtig
from einfluss import faktoren

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
    "aufwaerts",
    "fenster_faelle",
    "muster",
    "muster_version",
    "schritte",
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


_US_KLASSE = re.compile(r"^[A-Z]{1,5}\.[A-Z]$")
_PFLICHT_SCHRITTE = ("kurs", "historie", "technik", "fundamental", "nachrichten", "modell", "muster", "auswertung")
_ERLAUBT = {
    "kurs": {"ok"},
    "historie": {"ok"},
    "technik": {"ok"},
    "fundamental": {"ok", "nicht_verfuegbar", "nicht_anwendbar"},
    "nachrichten": {"ok", "nicht_verfuegbar"},
    "modell": {"ok"},
    "muster": {"ok"},
    "auswertung": {"ok"},
}


def schritte_lesen(roh) -> dict:
    if isinstance(roh, dict):
        return roh
    if not roh:
        return {}
    try:
        daten = json.loads(str(roh))
    except json.JSONDecodeError:
        return {}
    return daten if isinstance(daten, dict) else {}


def _schritt_stand(eintrag) -> str:
    if isinstance(eintrag, dict):
        return str(eintrag.get("stand") or "")
    return str(eintrag or "")


def analyse_code(lage: str, schritte_roh, preis_da: bool, datenstatus: str, ungewoehnlich) -> str:
    """Ein frischer Kurs oder ein leeres Tagesfeld ist keine vollständige Messung."""
    if lage == "veraltet":
        return "veraltet"
    schritte = schritte_lesen(schritte_roh)
    if not schritte:
        if not preis_da or str(datenstatus or "") in ("", "unvollstaendig"):
            return "fehlgeschlagen"
        if ungewoehnlich is None:
            return "wartet"
        return "teilweise"
    if _schritt_stand(schritte.get("kurs")) == "fehler" and not any(
        _schritt_stand(schritte.get(name)) for name in _PFLICHT_SCHRITTE if name != "kurs"
    ):
        return "fehlgeschlagen"
    staende = {name: _schritt_stand(schritte.get(name)) for name in _PFLICHT_SCHRITTE}
    if all(staende[name] in _ERLAUBT[name] for name in _PFLICHT_SCHRITTE):
        return "abgeschlossen"
    return "teilweise"


def bestand(pfad: Path, symbole: tuple[str, ...] = (), jetzt: int | None = None, watchlist: tuple[str, ...] = ()) -> dict:
    """Kompakte Liste des Universums. Eine fehlende oder veraltete Zeile gilt nicht als analysiert."""
    moment = int(time.time()) if jetzt is None else int(jetzt)
    gespeichert: dict[str, tuple] = {}
    reihen: dict[str, list[float]] = {}
    if pfad.exists():
        with sqlite3.connect(pfad) as verbindung:
            _tabelle(verbindung)
            for zeile in verbindung.execute(
                """
                SELECT symbol, name, preis, tag, tag_wert, richtung, datenstatus, bereich, kurszeit,
                       aufwaerts, herkunft, muster, ungewoehnlich, aktualisiert, schritte
                FROM auswertung
                """
            ):
                gespeichert[str(zeile[0])] = zeile
            tabellen = {name for (name,) in verbindung.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
            if "kurse" in tabellen:
                try:
                    kurse = verbindung.execute(
                        """
                        SELECT symbol, schluss FROM (
                            SELECT symbol, schluss, ROW_NUMBER() OVER (PARTITION BY symbol ORDER BY zeit DESC) AS n
                            FROM kurse
                            WHERE schluss IS NOT NULL AND schluss > 0
                        ) WHERE n <= 12
                        ORDER BY symbol, n DESC
                        """
                    )
                except sqlite3.OperationalError:
                    kurse = ()
                for symbol, schluss in kurse:
                    try:
                        reihen.setdefault(str(symbol), []).append(float(schluss))
                    except (TypeError, ValueError):
                        continue
    reihenfolge = tuple(dict.fromkeys((*symbole, *gespeichert)))
    liste = {str(symbol).upper() for symbol in watchlist}
    zeilen = []
    letzte = None
    for symbol in reihenfolge:
        zeile = gespeichert.get(symbol)
        eintrag = _bestand_zeile(symbol, zeile, moment, reihen.get(symbol))
        eintrag["liste"] = symbol in liste
        zeilen.append(eintrag)
        stempel = None if zeile is None else zeile[13]
        if isinstance(stempel, int) and not isinstance(stempel, bool) and (letzte is None or stempel > letzte):
            letzte = stempel
    return {"zeilen": zeilen, "universum": len(tuple(dict.fromkeys(symbole))), "letzte": letzte}


def _bestand_zeile(symbol: str, zeile: tuple | None, jetzt: int, reihe: list[float] | None) -> dict:
    from kurse import _datenstatus

    if zeile is None:
        return {
            "symbol": symbol,
            "name": symbol,
            "preis": None,
            "tag": None,
            "tag_wert": None,
            "richtung": "",
            "datenstatus": "unvollstaendig",
            "bereich": _bereich_symbol(symbol),
            "analyse": "nicht_gestartet",
            "schritte": {},
            "kurszeit": None,
            "aufwaerts": None,
            "herkunft": "",
            "lage": "ausstehend",
            "reihe": reihe if reihe and len(reihe) >= 2 else None,
            "faktoren": list(faktoren(None, None)),
        }
    _symbol, name, preis, tag, tag_wert, richtung, datenstatus, bereich, kurszeit, aufwaerts, herkunft, muster, ungewoehnlich, _aktualisiert, schritte = zeile
    qualitaet = str(_bild(muster).get("qualitaet") or "")
    if qualitaet not in ("vorsichtig", "belastbarer"):
        aufwaerts = None
    krypto = str(bereich or "") == "Krypto" or symbol.endswith("-USD")
    frische = _datenstatus(kurszeit if isinstance(kurszeit, int) and not isinstance(kurszeit, bool) else None, jetzt, krypto)
    gespeichert = str(datenstatus or "")
    if gespeichert == "veraltet" or frische == "veraltet":
        lage = "veraltet"
    elif gespeichert not in ("", "ok") or frische != "ok":
        lage = "fehlend"
    else:
        lage = "analysiert"
    preis_da = bool(preis) and str(preis) not in ("—", "-")
    analyse = analyse_code(lage, schritte, preis_da, gespeichert, ungewoehnlich)
    vorsprung = aufwaerts if isinstance(aufwaerts, (int, float)) and not isinstance(aufwaerts, bool) else None
    bewegung = tag_wert if isinstance(tag_wert, (int, float)) and not isinstance(tag_wert, bool) else None
    return {
        "symbol": symbol,
        "name": str(name or symbol),
        "preis": preis,
        "tag": tag,
        "tag_wert": bewegung,
        "richtung": str(richtung or ""),
        "datenstatus": gespeichert or frische,
        "bereich": _markt(symbol, str(bereich or "")),
        "analyse": analyse,
        "schritte": schritte_lesen(schritte),
        "kurszeit": kurszeit if isinstance(kurszeit, int) and not isinstance(kurszeit, bool) else None,
        "aufwaerts": vorsprung,
        "herkunft": str(herkunft or ""),
        "lage": lage,
        "reihe": reihe if reihe and len(reihe) >= 2 else None,
        "faktoren": list(faktoren(schritte_lesen(schritte), None)),
    }


def _markt(symbol: str, bereich: str) -> str:
    if bereich == "ETFs":
        return "ETFs"
    if bereich == "Krypto" or symbol.endswith("-USD"):
        return "Krypto"
    if _US_KLASSE.fullmatch(symbol):
        return "USA"
    return bereich or _bereich_symbol(symbol)


def _bereich_symbol(symbol: str) -> str:
    if symbol.endswith("-USD"):
        return "Krypto"
    if symbol.endswith(".DE"):
        return "Deutschland"
    if _US_KLASSE.fullmatch(symbol):
        return "USA"
    if "." in symbol:
        return "Europa"
    return "USA"


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


def chancen_nachtragen(pfad: Path) -> int:
    if not pfad.exists():
        return 0
    from analyse import kennzahlen_aus_schluessen
    from lernen import _tabelle as kurse_tabelle
    from muster import VERSION, als_json, pruefen
    from technik import vergleichsindex

    with sqlite3.connect(pfad) as verbindung:
        kurse_tabelle(verbindung)
        _tabelle(verbindung)
        verbindung.execute(
            """
            UPDATE auswertung
            SET aufwaerts = NULL, fenster_faelle = 0
            WHERE datenstatus = 'ok' AND (muster_version IS NULL OR muster_version < ?)
            """,
            (VERSION,),
        )
        offen = verbindung.execute(
            """
            SELECT symbol, bereich FROM auswertung
            WHERE datenstatus = 'ok' AND (muster_version IS NULL OR muster_version < ?)
            """,
            (VERSION,),
        ).fetchall()
        updates = []
        for symbol, bereich in offen:
            aktie, bereinigt = _kursreihe(verbindung, str(symbol))
            index_symbol = vergleichsindex(str(symbol))
            index, index_bereinigt = _kursreihe(verbindung, index_symbol) if index_symbol else ((), False)
            schluesse, index_schluesse = _angleichen(aktie, index if index_bereinigt else ())
            ist_etf = str(bereich or "") == "ETFs"
            if len(schluesse) < 50:
                bild = {"satz": "Datenbasis zu klein.", "rang": None, "faelle": 0, "qualitaet": "zu_klein", "horizonte": []}
            else:
                zahlen = kennzahlen_aus_schluessen(schluesse, ist_etf, None)
                bild = pruefen(zahlen, schluesse, index_schluesse, bereinigt)
            updates.append((bild["rang"], int(bild["faelle"]), als_json(bild), VERSION, str(symbol)))
        verbindung.executemany(
            """
            UPDATE auswertung
            SET aufwaerts = ?, fenster_faelle = ?, muster = ?, muster_version = ?
            WHERE symbol = ?
            """,
            updates,
        )
    return len(updates)


def index_an_tagen(pfad: Path, symbol: str, zeiten: Sequence[int]) -> tuple[float | None, ...] | None:
    if not symbol or not pfad.exists():
        return None
    from lernen import _tabelle as kurse_tabelle

    with sqlite3.connect(pfad) as verbindung:
        kurse_tabelle(verbindung)
        _reihe, bereinigt = _kursreihe(verbindung, symbol)
    if not bereinigt or not _reihe:
        return None
    nach_tag = {zeit // 86400: wert for zeit, wert in _reihe}
    return tuple(nach_tag.get(int(zeit) // 86400) if isinstance(zeit, int) and not isinstance(zeit, bool) else None for zeit in zeiten)


def _kursreihe(verbindung: sqlite3.Connection, symbol: str) -> tuple[tuple[tuple[int, float], ...], bool]:
    try:
        zeilen = verbindung.execute(
            "SELECT zeit, schluss, bereinigt FROM kurse WHERE symbol = ? ORDER BY zeit",
            (symbol,),
        ).fetchall()
    except sqlite3.OperationalError:
        return (), False
    if not zeilen:
        return (), False
    vollstaendig = all(zeile[2] not in (None, 0) for zeile in zeilen)
    reihe = tuple((int(zeile[0]), float(zeile[2] if vollstaendig else zeile[1])) for zeile in zeilen if zeile[1])
    return reihe, vollstaendig


def _angleichen(aktie: tuple[tuple[int, float], ...], index: tuple[tuple[int, float], ...]) -> tuple[tuple[float, ...], tuple[float | None, ...] | None]:
    werte = tuple(wert for _zeit, wert in aktie)
    if not index:
        return werte, None
    nach_tag = {zeit // 86400: wert for zeit, wert in index}
    return werte, tuple(nach_tag.get(zeit // 86400) for zeit, _wert in aktie)


def _karte(zeile) -> dict:
    karte = dict(zip((*_FELDER, "aktualisiert"), zeile))
    if karte["pruefung"] is None:
        karte["fenster"] = ""
    karte["fenster"] = karte["fenster"] or ""
    karte["pruefung"] = karte["pruefung"] or ""
    karte["folge"] = karte["folge"] or ""
    karte["ungewoehnlich"] = karte["ungewoehnlich"] or ""
    karte["markt"] = karte["markt"] or ""
    bild = _bild(karte.get("muster"))
    karte["vorschlag"] = str(bild.get("satz") or "")
    karte["horizonte"] = list(bild.get("horizonte") or [])
    karte["qualitaet"] = str(bild.get("qualitaet") or "")
    wert = karte.get("aufwaerts")
    karte["aufwaerts"] = None if isinstance(wert, bool) or not isinstance(wert, (int, float)) else float(wert)
    if karte["qualitaet"] not in ("vorsichtig", "belastbarer"):
        karte["aufwaerts"] = None
    faelle = bild.get("faelle", karte.get("fenster_faelle"))
    karte["fenster_faelle"] = 0 if isinstance(faelle, bool) or not isinstance(faelle, int) else faelle
    karte.pop("muster", None)
    karte["datenstatus"] = karte["datenstatus"] or ""
    stempel = karte.get("aktualisiert")
    if isinstance(stempel, int) and not isinstance(stempel, bool):
        text = datetime.fromtimestamp(stempel, BERLIN).strftime("%d.%m. %H:%M")
        karte["herkunft"] = f"{karte['herkunft']} · gespeichert {text}"
    return karte


def _bild(text) -> dict:
    if not isinstance(text, str) or not text:
        return {}
    try:
        bild = json.loads(text)
    except json.JSONDecodeError:
        return {}
    return bild if isinstance(bild, dict) else {}


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
        ("aufwaerts", "REAL"),
        ("fenster_faelle", "INTEGER"),
        ("muster", "TEXT"),
        ("muster_version", "INTEGER"),
        ("hinweis_stand", "TEXT"),
        ("schritte", "TEXT"),
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
