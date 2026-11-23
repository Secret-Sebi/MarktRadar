"""Unternehmenszahlen nur aus einer echten Yahoo-Antwort. Fehlende Felder bleiben leer."""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from http.cookiejar import CookieJar
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import HTTPCookieProcessor, Request, build_opener, urlopen

from quellen import hole_text

_FELDER = (
    ("summaryDetail", "trailingPE", "KGV", False),
    ("summaryDetail", "forwardPE", "erwartetes KGV", False),
    ("financialData", "revenueGrowth", "Umsatzwachstum", True),
    ("financialData", "earningsGrowth", "Gewinnwachstum", True),
    ("financialData", "profitMargins", "Gewinnmarge", True),
    ("financialData", "debtToEquity", "Verschuldung", False),
    ("financialData", "freeCashflow", "Free Cashflow", False),
    ("summaryDetail", "dividendYield", "Dividendenrendite", True),
    ("financialData", "returnOnEquity", "Eigenkapitalrendite", True),
)


def aus_yahoo(roh: dict) -> tuple[str, dict[str, float]]:
    ergebnis = roh.get("quoteSummary") if isinstance(roh, dict) else None
    zeilen = ergebnis.get("result") if isinstance(ergebnis, dict) else None
    block = zeilen[0] if isinstance(zeilen, list) and zeilen and isinstance(zeilen[0], dict) else {}
    profil = block.get("assetProfile") if isinstance(block.get("assetProfile"), dict) else {}
    branche = str(profil.get("sector") or "").strip()
    werte = {}
    for modul, schluessel, name, prozent in _FELDER:
        quelle = block.get(modul) if isinstance(block.get(modul), dict) else {}
        zahl = _zahl(quelle.get(schluessel))
        if zahl is None:
            continue
        werte[name] = zahl * 100.0 if prozent else zahl
    return branche, werte


def text(branche: str, werte: dict[str, float]) -> str:
    if not branche and not werte:
        return "fehlt"
    teile = []
    if branche:
        teile.append(f"Branche laut Yahoo: {branche}")
    for name, zahl in werte.items():
        if name in ("KGV", "erwartetes KGV", "Verschuldung"):
            teile.append(f"{name} {zahl:.1f}")
        elif name == "Free Cashflow":
            teile.append(f"{name} {zahl:.0f}")
        else:
            teile.append(f"{name} {zahl:.1f} %")
    teile.append(_bewertung(branche, werte))
    teile.append("Wettbewerber fehlen, solange Yahoo sie nicht liefert.")
    return ". ".join(teile)


def _bewertung(branche: str, werte: dict[str, float]) -> str:
    if any(wort in branche.lower() for wort in ("bank", "insurance", "real estate", "financial")):
        return "Sonderbranche. Dafür fehlen passende Kennzahlen, deshalb gibt es keine positive Bewertung."
    if len(werte) < 5:
        return "Keine fundamentale Gesamtnote. Zu wenige Kennzahlen, und Fehlendes zählt nicht als neutral."
    if werte.get("KGV", 1) < 0 or werte.get("Gewinnmarge", 0) < 0 or werte.get("Free Cashflow", 0) < 0:
        return "Verlust, negative Marge oder negativer Free Cashflow. Das ist kein günstiger Einstieg."
    return "Die vorhandenen Zahlen ergeben keine Kaufnote und keinen Branchenvergleich."


_CACHE: dict[str, tuple[float, Lage]] = {}
_PAUSE = 6 * 3600
_SITZ: dict[str, object] = {"bis": 0.0, "opener": None, "krume": ""}


@dataclass(frozen=True)
class Lage:
    text: str
    stand: str
    quelle: str
    grund: str


def hole(symbol: str, oeffnen, jetzt: float | None = None) -> str:
    return hole_lage(symbol, oeffnen, jetzt).text


def hole_lage(symbol: str, oeffnen, jetzt: float | None = None) -> Lage:
    moment = time.time() if jetzt is None else jetzt
    gespeichert = _CACHE.get(symbol)
    if gespeichert is not None and moment - gespeichert[0] < _PAUSE and gespeichert[1].stand != "fehler":
        return gespeichert[1]
    if symbol.upper().endswith("-USD"):
        lage = Lage("Krypto hat keine Unternehmenskennzahlen.", "nicht_anwendbar", "keine", "Krypto")
        _CACHE[symbol] = (moment, lage)
        return lage
    if symbol.startswith("^"):
        lage = Lage("Ein Index hat keine Unternehmenskennzahlen.", "nicht_anwendbar", "keine", "Index")
        _CACHE[symbol] = (moment, lage)
        return lage
    adresse = (
        "https://query1.finance.yahoo.com/v10/finance/quoteSummary/"
        + quote(symbol, safe="")
        + "?modules=assetProfile,financialData,summaryDetail"
    )
    try:
        roh = json.loads(_lesen(adresse, oeffnen))
    except (ConnectionError, LookupError, TimeoutError, json.JSONDecodeError, ValueError):
        return Lage("fehlt", "fehler", "Yahoo Finance", "Die Fundamentalquelle hat nicht geantwortet.")
    if not isinstance(roh, dict):
        return Lage("fehlt", "fehler", "Yahoo Finance", "Die Fundamentalquelle lieferte kein Objekt.")
    branche, werte = aus_yahoo(roh)
    if not branche and not werte:
        lage = Lage("fehlt", "nicht_verfuegbar", "Yahoo Finance", "Yahoo lieferte keine Kennzahlen.")
    else:
        lage = Lage(text(branche, werte), "ok", "Yahoo Finance", "")
    _CACHE[symbol] = (moment, lage)
    return lage


def _lesen(adresse: str, oeffnen) -> str:
    if oeffnen is not urlopen:
        return hole_text(adresse, oeffnen, "application/json")
    opener, krume = _sitz()
    ziel = adresse + "&crumb=" + quote(krume, safe="")
    try:
        with opener.open(Request(ziel, headers=_kopf()), timeout=12) as antwort:
            return antwort.read().decode("utf-8", errors="replace")
    except HTTPError as fehler:
        raise LookupError("Fundamentalquelle antwortet nicht") from fehler
    except (URLError, TimeoutError) as fehler:
        raise ConnectionError("Fundamentalquelle nicht erreichbar") from fehler


def _sitz():
    moment = time.time()
    opener = _SITZ.get("opener")
    krume = str(_SITZ.get("krume") or "")
    if opener is not None and krume and moment < float(_SITZ.get("bis") or 0):
        return opener, krume
    jar = CookieJar()
    neu = build_opener(HTTPCookieProcessor(jar))
    try:
        neu.open(Request("https://fc.yahoo.com", headers=_kopf()), timeout=12).read()
    except HTTPError:
        pass
    except (URLError, TimeoutError) as fehler:
        raise ConnectionError("Fundamentalquelle nicht erreichbar") from fehler
    try:
        with neu.open(Request("https://query1.finance.yahoo.com/v1/test/getcrumb", headers=_kopf()), timeout=12) as antwort:
            krume = antwort.read().decode("utf-8", errors="replace").strip()
    except HTTPError as fehler:
        raise LookupError("Yahoo-Krume fehlt") from fehler
    except (URLError, TimeoutError) as fehler:
        raise ConnectionError("Fundamentalquelle nicht erreichbar") from fehler
    if not krume or any(zeichen in krume for zeichen in (" ", "<", "{")):
        raise LookupError("Yahoo-Krume fehlt")
    _SITZ["opener"] = neu
    _SITZ["krume"] = krume
    _SITZ["bis"] = moment + 1800
    return neu, krume


def _kopf() -> dict[str, str]:
    return {"User-Agent": "Mozilla/5.0", "Accept": "application/json,text/plain,*/*"}


def _zahl(wert):
    if isinstance(wert, dict):
        wert = wert.get("raw")
    if isinstance(wert, bool) or not isinstance(wert, (int, float)):
        return None
    return float(wert)
