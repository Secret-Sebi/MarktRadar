"""Kursdaten von Yahoo Finance. Das ist nicht der Preis in Trade Republic."""

from __future__ import annotations

import json
import re
import threading
import time
from collections.abc import Sequence
from dataclasses import dataclass, replace
from datetime import datetime
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

_SYMBOL = re.compile(r"^[A-Z0-9^=.-]{1,15}$")
_YAHOO = (
    "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
    "?interval=1d&range=2y&includeAdjustedClose=true&events=div%7Csplit"
)


@dataclass(frozen=True)
class Bar:
    zeit: int | None
    oeffnen: float | None
    hoch: float | None
    tief: float | None
    schluss: float
    bereinigt: float
    volumen: float | None


@dataclass(frozen=True)
class Kursdaten:
    symbol: str
    name: str
    waehrung: str
    preis: float
    tag_pct: float | None
    ist_etf: bool
    schluesse: tuple[float, ...]
    hoch_52w: float | None
    tief_52w: float | None = None
    balken: tuple[Bar, ...] = ()
    hat_bereinigt: bool = False
    quelle: str = "Yahoo Finance"
    kurszeit: int | None = None
    datenstatus: str = "ok"
    kursart: str = "verzoegert"
    handelsplatz: str = ""
    hinweis: str = ""
    abweichung: float | None = None
    zeitzone: str = "UTC"


def gueltiges_symbol(symbol: str) -> bool:
    return _SYMBOL.fullmatch(symbol) is not None


def hole_kurs(symbol: str, oeffnen=urlopen, fx: dict | None = None) -> Kursdaten:
    from euro import nach_euro
    from quellen import mit_fallback

    speicher = fx if fx is not None else {}
    daten = mit_fallback(symbol, oeffnen, yahoo_kurs)
    abweichung = _abweichung(symbol, daten, oeffnen)
    daten = nach_euro(daten, lambda code: _wechselkurs(code, oeffnen, speicher))
    return replace(daten, abweichung=abweichung)


_SPERRE = threading.Lock()
_ZWEIT: dict[str, tuple[float, float | None]] = {}
_ZWEIT_PAUSE = 3600


def abweichung_prozent(erster: float, zweiter: float) -> float | None:
    if isinstance(erster, bool) or isinstance(zweiter, bool):
        return None
    if not isinstance(erster, (int, float)) or not isinstance(zweiter, (int, float)):
        return None
    if erster <= 0 or zweiter <= 0:
        return None
    return (zweiter / erster - 1.0) * 100.0


def _wechselkurs(waehrung: str, oeffnen, speicher: dict | None = None):
    gemerkt = speicher if speicher is not None else {}
    with _SPERRE:
        if waehrung in gemerkt:
            return gemerkt[waehrung]
    try:
        kurs = yahoo_kurs(f"{waehrung}EUR=X", oeffnen)
    except (ConnectionError, LookupError, ValueError, json.JSONDecodeError):
        with _SPERRE:
            gemerkt[waehrung] = None
        return None
    reihe = tuple(
        (bar.zeit, bar.bereinigt if bar.bereinigt and bar.bereinigt > 0 else bar.schluss)
        for bar in kurs.balken
        if (bar.bereinigt and bar.bereinigt > 0) or bar.schluss > 0
    )
    wert = reihe if len(reihe) >= 2 else (kurs.preis if kurs.preis > 0 else None)
    with _SPERRE:
        gemerkt[waehrung] = wert
    return wert


def _abweichung(symbol: str, daten: Kursdaten, oeffnen, jetzt: float | None = None) -> float | None:
    moment = time.time() if jetzt is None else jetzt
    with _SPERRE:
        gespeichert = _ZWEIT.get(symbol)
        if gespeichert is not None and moment - gespeichert[0] < _ZWEIT_PAUSE:
            return gespeichert[1]
    try:
        if symbol.endswith("-USD"):
            from quellen_coingecko import gecko_kurs

            andere = gecko_kurs(symbol, oeffnen)
        else:
            from quellen_stooq import stooq_kurs

            andere = stooq_kurs(symbol, oeffnen)
    except (ConnectionError, LookupError, TimeoutError, ValueError, json.JSONDecodeError):
        andere = None
    wert = None
    if andere is not None and andere.waehrung == daten.waehrung:
        wert = abweichung_prozent(daten.preis, andere.preis)
    with _SPERRE:
        _ZWEIT[symbol] = (moment, wert)
    return wert


def yahoo_kurs(symbol: str, oeffnen=urlopen) -> Kursdaten:
    if not gueltiges_symbol(symbol):
        raise ValueError("Ungültiges Kürzel")
    adresse = _YAHOO.format(symbol=quote(symbol, safe=""))
    anfrage = Request(adresse, headers={"User-Agent": "MarktRadar/1.0"})
    try:
        with oeffnen(anfrage, timeout=12) as antwort:
            roh = antwort.read()
    except (HTTPError, URLError, TimeoutError) as fehler:
        raise ConnectionError("Yahoo Finance nicht erreichbar") from fehler
    daten = kurse_aus_antwort(json.loads(roh.decode("utf-8")))
    if daten is None:
        raise LookupError("Keine Kursdaten")
    return daten


def _datenstatus(kurszeit: int | None, jetzt: int | None = None, krypto: bool = False) -> str:
    if isinstance(kurszeit, bool) or not isinstance(kurszeit, int):
        return "unvollstaendig"
    alter = (int(time.time()) if jetzt is None else jetzt) - kurszeit
    if alter < -15 * 60:
        return "unvollstaendig"
    grenze = 2 * 24 * 3600 if krypto else 10 * 24 * 3600
    if alter > grenze:
        return "veraltet"
    return "ok"


def kurse_aus_antwort(payload: dict) -> Kursdaten | None:
    block = _erster_block(payload)
    if block is None:
        return None
    meta = block.get("meta") or {}
    quote = _quote(block)
    if quote is None:
        return None
    bereinigt = _adjclose(block)
    balken = balken_bauen(
        tuple(block.get("timestamp") or ()),
        tuple(quote.get("open") or ()),
        tuple(quote.get("high") or ()),
        tuple(quote.get("low") or ()),
        tuple(quote.get("close") or ()),
        tuple(quote.get("volume") or ()),
        tuple(bereinigt),
        _optional_float(meta.get("regularMarketPrice")),
        _zeitstempel(meta.get("regularMarketTime")),
        str(meta.get("exchangeTimezoneName") or "UTC"),
    )
    if not balken:
        return None
    schluesse = tuple(bar.bereinigt for bar in balken)
    preis = _optional_float(meta.get("regularMarketPrice")) or balken[-1].schluss
    name = meta.get("longName") or meta.get("shortName") or meta.get("symbol") or ""
    kurszeit = _zeitstempel(meta.get("regularMarketTime")) or balken[-1].zeit
    symbol = str(meta.get("symbol") or "")
    return Kursdaten(
        symbol=symbol,
        name=_name(str(name)),
        waehrung=str(meta.get("currency") or ""),
        preis=preis,
        tag_pct=_tag_pct(meta, schluesse),
        ist_etf=meta.get("instrumentType") == "ETF",
        schluesse=schluesse,
        hoch_52w=_optional_float(meta.get("fiftyTwoWeekHigh")),
        tief_52w=_optional_float(meta.get("fiftyTwoWeekLow")),
        balken=balken,
        hat_bereinigt=bool(bereinigt),
        quelle="Yahoo Finance",
        kurszeit=kurszeit,
        datenstatus=_datenstatus(kurszeit, krypto=symbol.upper().endswith("-USD")),
        kursart="verzoegert",
        handelsplatz=str(meta.get("exchangeName") or meta.get("fullExchangeName") or ""),
        hinweis="Verzögerter Yahoo-Finance-Kurs, kein Echtzeit-Feed und nicht der Brokerpreis.",
        zeitzone=str(meta.get("exchangeTimezoneName") or "UTC"),
    )


def balken_bauen(
    zeiten: Sequence[object],
    oeffnen: Sequence[object],
    hochs: Sequence[object],
    tiefs: Sequence[object],
    schluesse: Sequence[object],
    volumen: Sequence[object],
    bereinigt: Sequence[object],
    live: float | None,
    live_zeit: int | None,
    zeitzone: str,
) -> tuple[Bar, ...]:
    roh = _roh_balken(zeiten, oeffnen, hochs, tiefs, schluesse, volumen, bereinigt)
    if not roh or live is None:
        return roh
    if any(bar.zeit is None for bar in roh) or live_zeit is None:
        return roh[:-1] + (_mit_live(roh[-1], live),)
    live_tag = _tag(live_zeit, zeitzone)
    letzter_tag = _tag(roh[-1].zeit, zeitzone)
    if live_tag is None or letzter_tag is None or live_tag == letzter_tag:
        return roh[:-1] + (_mit_live(roh[-1], live),)
    if live_tag > letzter_tag:
        return roh + (_neuer_tag(roh[-1], live, live_zeit),)
    return roh


def _schluesse(roh: Sequence[object], live) -> tuple[float, ...]:
    werte = tuple(float(wert) for wert in roh if isinstance(wert, (int, float)) and not isinstance(wert, bool))
    live_preis = _optional_float(live)
    if live_preis is None or not werte:
        return werte
    return werte[:-1] + (live_preis,)


def _tag_pct(meta: dict, schluesse: tuple[float, ...]) -> float | None:
    # chartPreviousClose ist der Kurs am Anfang der abgefragten Spanne, nicht der Vortag.
    prozent = meta.get("regularMarketChangePercent")
    if isinstance(prozent, (int, float)) and not isinstance(prozent, bool):
        return float(prozent)
    if len(schluesse) >= 2 and schluesse[-2] != 0:
        return (schluesse[-1] / schluesse[-2] - 1.0) * 100.0
    return None


def _optional_float(wert) -> float | None:
    if isinstance(wert, bool) or not isinstance(wert, (int, float)):
        return None
    return float(wert)


def _name(name: str) -> str:
    return " ".join(name.split())


def _erster_block(payload: dict):
    chart = payload.get("chart") if isinstance(payload, dict) else None
    if not isinstance(chart, dict):
        return None
    ergebnisse = chart.get("result")
    if not ergebnisse:
        return None
    return ergebnisse[0]


def _quote(block: dict):
    quote_block = (block.get("indicators") or {}).get("quote") or []
    if not quote_block:
        return None
    return quote_block[0]


def _adjclose(block: dict):
    adj = (block.get("indicators") or {}).get("adjclose") or []
    if not adj:
        return ()
    return adj[0].get("adjclose") or ()


def _zeitstempel(wert) -> int | None:
    if isinstance(wert, bool) or not isinstance(wert, (int, float)):
        return None
    return int(wert)


def _roh_balken(zeiten, oeffnen, hochs, tiefs, schluesse, volumen, bereinigt) -> tuple[Bar, ...]:
    laenge = max(len(schluesse), len(bereinigt))
    balken = []
    for index in range(laenge):
        schluss = _optional_float(_wert(schluesse, index))
        adj = _optional_float(_wert(bereinigt, index))
        if schluss is None and adj is None:
            continue
        if schluss is None:
            schluss = adj
        if adj is None:
            adj = schluss
        balken.append(
            Bar(
                _zeitstempel(_wert(zeiten, index)),
                _optional_float(_wert(oeffnen, index)),
                _optional_float(_wert(hochs, index)),
                _optional_float(_wert(tiefs, index)),
                schluss,
                adj,
                _optional_float(_wert(volumen, index)),
            )
        )
    return tuple(balken)


def _wert(werte, index):
    if index >= len(werte):
        return None
    return werte[index]


def _mit_live(bar: Bar, live: float) -> Bar:
    faktor = bar.bereinigt / bar.schluss if bar.schluss else 1.0
    hoch = live if bar.hoch is None or live > bar.hoch else bar.hoch
    tief = live if bar.tief is None or live < bar.tief else bar.tief
    return Bar(bar.zeit, bar.oeffnen, hoch, tief, live, live * faktor, bar.volumen)


def _neuer_tag(vorgaenger: Bar, live: float, zeit: int) -> Bar:
    faktor = vorgaenger.bereinigt / vorgaenger.schluss if vorgaenger.schluss else 1.0
    return Bar(zeit, live, live, live, live, live * faktor, None)


def _tag(zeit: int | None, zeitzone: str):
    if zeit is None:
        return None
    try:
        zone = ZoneInfo(zeitzone)
    except (ZoneInfoNotFoundError, ValueError):
        zone = ZoneInfo("UTC")
    return datetime.fromtimestamp(zeit, zone).date()
