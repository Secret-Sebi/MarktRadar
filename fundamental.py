"""Unternehmenszahlen nur aus einer echten Yahoo-Antwort. Fehlende Felder bleiben leer."""

from __future__ import annotations

import json
import time
from urllib.parse import quote

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


_CACHE: dict[str, tuple[float, str]] = {}
_PAUSE = 6 * 3600


def hole(symbol: str, oeffnen, jetzt: float | None = None) -> str:
    moment = time.time() if jetzt is None else jetzt
    gespeichert = _CACHE.get(symbol)
    if gespeichert is not None and moment - gespeichert[0] < _PAUSE:
        return gespeichert[1]
    adresse = (
        "https://query1.finance.yahoo.com/v10/finance/quoteSummary/"
        + quote(symbol, safe="")
        + "?modules=assetProfile,financialData,summaryDetail"
    )
    try:
        roh = json.loads(hole_text(adresse, oeffnen, "application/json"))
    except (ConnectionError, LookupError, TimeoutError, json.JSONDecodeError, ValueError):
        _CACHE[symbol] = (moment, "fehlt")
        return "fehlt"
    branche, werte = aus_yahoo(roh if isinstance(roh, dict) else {})
    ergebnis = text(branche, werte)
    _CACHE[symbol] = (moment, ergebnis)
    return ergebnis


def _zahl(wert):
    if isinstance(wert, dict):
        wert = wert.get("raw")
    if isinstance(wert, bool) or not isinstance(wert, (int, float)):
        return None
    return float(wert)
