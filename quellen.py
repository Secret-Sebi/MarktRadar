"""Yahoo zuerst, danach eine echte Ersatzquelle. Niemals ein erfundener Kurs."""

from __future__ import annotations

import json
import math
from urllib.error import HTTPError, URLError
from urllib.request import Request


def mit_fallback(symbol: str, oeffnen, yahoo, stooq=None, gecko=None):
    from kurse import gueltiges_symbol

    if not gueltiges_symbol(symbol):
        raise ValueError("Ungültiges Kürzel")
    if stooq is None:
        from quellen_stooq import stooq_kurs

        stooq = stooq_kurs
    if gecko is None:
        from quellen_coingecko import gecko_kurs

        gecko = gecko_kurs
    letzter = None
    for funktion in _reihenfolge(symbol, yahoo, stooq, gecko):
        try:
            daten = funktion(symbol, oeffnen)
        except (ConnectionError, LookupError, TimeoutError, ValueError, json.JSONDecodeError) as fehler:
            letzter = fehler
            continue
        if not plausibel(daten):
            letzter = LookupError("Kurswert ist nicht plausibel")
            continue
        return daten
    raise LookupError("Keine verlässlichen Kursdaten") from letzter


def plausibel(daten) -> bool:
    preis = getattr(daten, "preis", None)
    if isinstance(preis, bool) or not isinstance(preis, (int, float)):
        return False
    if not math.isfinite(preis) or preis <= 0:
        return False
    for bar in getattr(daten, "balken", ()) or ():
        if bar.schluss <= 0 or not math.isfinite(bar.schluss):
            return False
        if bar.hoch is not None and bar.tief is not None and bar.hoch < bar.tief:
            return False
    return True


def hole_text(adresse: str, oeffnen, akzeptiere: str, kopf: dict | None = None) -> str:
    headers = {"User-Agent": "MarktRadar/1.0", "Accept": akzeptiere}
    if kopf:
        headers.update(kopf)
    anfrage = Request(adresse, headers=headers)
    letzter = None
    for _versuch in range(2):
        try:
            with oeffnen(anfrage, timeout=12) as antwort:
                return antwort.read().decode("utf-8", errors="replace")
        except HTTPError as fehler:
            raise LookupError("Datenquelle antwortet ohne Kurs") from fehler
        except (URLError, TimeoutError) as fehler:
            letzter = fehler
    raise ConnectionError("Datenquelle nicht erreichbar") from letzter


def _reihenfolge(symbol: str, yahoo, stooq, gecko):
    if symbol.endswith("-USD"):
        return (_euro_paar(yahoo), gecko)
    return (yahoo, stooq)


def _euro_paar(yahoo):
    def laden(symbol: str, oeffnen):
        from dataclasses import replace

        daten = yahoo(symbol[:-4] + "-EUR", oeffnen)
        return replace(daten, symbol=symbol)

    return laden
