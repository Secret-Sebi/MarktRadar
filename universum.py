"""Liquide Märkte zum Messen: DAX, MDAX, S&P 500 und Nasdaq 100."""

from __future__ import annotations

import json
import re
import time
from pathlib import Path
from urllib.request import Request, urlopen

from kurse import gueltiges_symbol

_SP = "https://raw.githubusercontent.com/datasets/s-and-p-500-companies/master/data/constituents.csv"
_DAX = "https://de.wikipedia.org/w/api.php?action=parse&page=DAX&prop=wikitext&format=json"
_MDAX = "https://en.wikipedia.org/w/api.php?action=parse&page=MDAX&prop=text&format=json"
_NDX = (
    "https://en.wikipedia.org/w/api.php?action=parse&page=List_of_NASDAQ-100_companies&prop=text&format=json"
)
_ALTER = 7 * 86400
_KURZ = 6 * 3600
_KOPF = "# liquide"
_RUNDEN = 40
_NAME = "Gemessen werden DAX, MDAX, S&P 500 und Nasdaq 100, plus die watchlist."


def parse_csv(text: str) -> tuple[str, ...]:
    zeilen = [zeile for zeile in text.splitlines() if zeile.strip()]
    if not zeilen:
        return ()
    kopf = [teil.strip() for teil in zeilen[0].split(",")]
    index = kopf.index("Symbol") if "Symbol" in kopf else 0
    return _gueltig(teil.split(",")[index].strip().upper() for teil in zeilen[1:] if len(teil.split(",")) > index)


def parse_wiki_de(text: str) -> tuple[str, ...]:
    roh = _wiki_text(text)
    symbole = []
    for treffer in re.findall(r"\|\s*([A-Z0-9]{2,6})\s*\|\|", roh):
        if any(zeichen.isalpha() for zeichen in treffer):
            symbole.append(f"{treffer}.DE")
    return _gueltig(symbole)


def parse_mdax(text: str) -> tuple[str, ...]:
    roh = _wiki_text(text)
    symbole = []
    for treffer in re.findall(r"<td>\s*([A-Z0-9]{2,6})\s*</td>\s*</tr>", roh):
        if any(zeichen.isalpha() for zeichen in treffer):
            symbole.append(f"{treffer}.DE")
    gueltig = _gueltig(symbole)
    if len(gueltig) < 40:
        return ()
    return gueltig


def parse_wiki_us(text: str) -> tuple[str, ...]:
    roh = _wiki_text(text)
    symbole = _gueltig(re.findall(r"<td>([A-Z]{1,5})</td>\s*<td><a", roh))
    if len(symbole) < 90:
        return ()
    return symbole


def naechste(symbole: tuple[str, ...], cursor: int, groesse: int = _RUNDEN) -> tuple[tuple[str, ...], int]:
    if not symbole:
        return (), 0
    start = cursor % len(symbole)
    teil = tuple(symbole[(start + index) % len(symbole)] for index in range(min(groesse, len(symbole))))
    return teil, (start + len(teil)) % len(symbole)


def lade_universum(
    watchlist: tuple[str, ...],
    cache: Path,
    oeffnen=urlopen,
    jetzt: int | None = None,
) -> tuple[tuple[str, ...], str]:
    moment = int(time.time()) if jetzt is None else int(jetzt)
    gespeichert, fehlt = _lies(cache)
    alter = moment - int(cache.stat().st_mtime) if cache.exists() else _ALTER
    haltbar = _KURZ if fehlt else _ALTER
    frisch = bool(gespeichert) and alter < haltbar
    hinweis = _NAME
    symbole = gespeichert
    if frisch and fehlt:
        hinweis = f"{_NAME} Nicht geladen: {', '.join(fehlt)}."
    if not frisch:
        geladen, fehler, zahlen = _quellen(oeffnen)
        if geladen:
            symbole = geladen
            _schreib(cache, symbole, fehler, zahlen)
        elif gespeichert:
            hinweis = f"{_NAME} Die Liste wurde nicht neu geladen, der gespeicherte Stand bleibt."
        else:
            hinweis = "Die liquiden Listen sind gerade nicht erreichbar. Gemessen wird die watchlist."
        if fehler and geladen:
            hinweis = f"{_NAME} Nicht geladen: {', '.join(fehler)}."
    if not symbole and not watchlist:
        hinweis = "Es gibt noch keine Kürzel zum Messen."
    return tuple(dict.fromkeys(tuple(watchlist) + tuple(symbole))), hinweis


def _quellen(oeffnen) -> tuple[tuple[str, ...], tuple[str, ...], tuple[tuple[str, int], ...]]:
    paare = (
        (_SP, parse_csv, "S&P 500"),
        (_DAX, parse_wiki_de, "DAX"),
        (_MDAX, parse_mdax, "MDAX"),
        (_NDX, parse_wiki_us, "Nasdaq 100"),
    )
    symbole: list[str] = []
    fehler: list[str] = []
    zahlen: list[tuple[str, int]] = []
    for adresse, parser, name in paare:
        try:
            teil = parser(_holen(oeffnen, adresse))
        except (OSError, TimeoutError, ValueError, json.JSONDecodeError):
            fehler.append(name)
            continue
        zahlen.append((name, len(teil)))
        if teil:
            symbole.extend(teil)
        else:
            fehler.append(name)
    return tuple(dict.fromkeys(symbole)), tuple(fehler), tuple(zahlen)


def _holen(oeffnen, adresse: str) -> str:
    if oeffnen is urlopen:
        anfrage = Request(adresse, headers={"User-Agent": "MarktRadar/1.0 (local)"})
        with urlopen(anfrage, timeout=25) as antwort:
            return antwort.read().decode("utf-8", "replace")
    with oeffnen(adresse, timeout=25) as antwort:
        roh = antwort.read()
    return roh.decode("utf-8", "replace") if isinstance(roh, (bytes, bytearray)) else str(roh)


def _wiki_text(text: str) -> str:
    try:
        daten = json.loads(text)
    except json.JSONDecodeError:
        return text
    parse = daten.get("parse") if isinstance(daten, dict) else None
    if not isinstance(parse, dict):
        return text
    wikitext = parse.get("wikitext")
    if isinstance(wikitext, dict) and isinstance(wikitext.get("*"), str):
        return wikitext["*"]
    html = parse.get("text")
    if isinstance(html, dict) and isinstance(html.get("*"), str):
        return html["*"]
    return text


def _gueltig(symbole) -> tuple[str, ...]:
    return tuple(dict.fromkeys(symbol for symbol in symbole if gueltiges_symbol(symbol)))


_MINDEST = {"DAX": 40, "MDAX": 40, "S&P 500": 400, "Nasdaq 100": 90}


def abdeckung(cache: Path) -> dict:
    if not cache.exists():
        return {"symbole": 0, "eindeutig": 0, "fehlt": [], "indizes": {}, "hinweis": "Keine gespeicherte Liste."}
    zeilen = [zeile.strip() for zeile in cache.read_text(encoding="utf-8").splitlines() if zeile.strip()]
    if not zeilen or zeilen[0] != _KOPF:
        return {"symbole": 0, "eindeutig": 0, "fehlt": [], "indizes": {}, "hinweis": "Die gespeicherte Liste hat keinen gültigen Kopf."}
    fehlt = [zeile[8:].strip() for zeile in zeilen if zeile.startswith("# fehlt ")]
    indizes = {}
    for zeile in zeilen:
        if not zeile.startswith("# zahl "):
            continue
        teile = zeile.split()
        if len(teile) < 4 or not teile[-1].isdigit():
            continue
        indizes[" ".join(teile[2:-1])] = int(teile[-1])
    symbole = [zeile.upper() for zeile in zeilen if not zeile.startswith("#")]
    hinweise = []
    if not indizes:
        hinweise.append("Zahl je Index ist nicht gespeichert.")
    for name, mindest in _MINDEST.items():
        if name in fehlt:
            hinweise.append(f"{name} wurde nicht geladen.")
        elif name in indizes and indizes[name] < mindest:
            hinweise.append(f"{name} ist unvollständig: {indizes[name]}.")
    return {
        "symbole": len(symbole),
        "eindeutig": len(set(symbole)),
        "fehlt": fehlt,
        "indizes": indizes,
        "hinweis": " ".join(hinweise),
    }


def _schreib(cache: Path, symbole: tuple[str, ...], fehler: tuple[str, ...], zahlen: tuple[tuple[str, int], ...] = ()) -> None:
    kopf = [_KOPF, *(f"# zahl {name} {zahl}" for name, zahl in zahlen), *(f"# fehlt {name}" for name in fehler)]
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text("\n".join((*kopf, *symbole)) + "\n", encoding="utf-8")


def _lies(cache: Path) -> tuple[tuple[str, ...], tuple[str, ...]]:
    if not cache.exists():
        return (), ()
    zeilen = [zeile.strip() for zeile in cache.read_text(encoding="utf-8").splitlines() if zeile.strip()]
    if not zeilen or zeilen[0] != _KOPF:
        return (), ()
    fehlt = tuple(zeile[8:].strip() for zeile in zeilen if zeile.startswith("# fehlt "))
    symbole = tuple(zeile.upper() for zeile in zeilen if not zeile.startswith("#"))
    if len(symbole) > 2000:
        return (), ()
    return symbole, fehlt
