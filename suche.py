"""Suche nach echten Yahoo- und CoinGecko-Treffern. Keine erfundenen Kürzel."""

from __future__ import annotations

import json
from dataclasses import dataclass
from urllib.parse import quote
from urllib.request import urlopen

from quellen import hole_text


@dataclass(frozen=True)
class Treffer:
    symbol: str
    name: str
    typ: str
    boerse: str
    quelle: str


def suche(text: str, oeffnen=urlopen) -> tuple[Treffer, ...]:
    begriff = " ".join(text.split())
    if len(begriff) < 2:
        return ()
    treffer: tuple[Treffer, ...] = ()
    for leser in (_yahoo, _gecko):
        try:
            treffer = treffer + leser(begriff, oeffnen)
        except (ConnectionError, LookupError, json.JSONDecodeError, TimeoutError, ValueError):
            continue
    return _ohne_doppelte(treffer)[:8]


def suche_aus_yahoo(roh: dict) -> tuple[Treffer, ...]:
    zitate = roh.get("quotes") if isinstance(roh, dict) else None
    treffer = []
    for eintrag in zitate or []:
        symbol = str(eintrag.get("symbol") or "").strip().upper()
        if not symbol:
            continue
        treffer.append(
            Treffer(
                symbol,
                str(eintrag.get("shortname") or eintrag.get("longname") or symbol),
                str(eintrag.get("quoteType") or eintrag.get("typeDisp") or ""),
                str(eintrag.get("exchDisp") or ""),
                "Yahoo Finance",
            )
        )
    return tuple(treffer)


def suche_aus_coingecko(roh: dict) -> tuple[Treffer, ...]:
    gruppen = {}
    for coin in (roh.get("coins") if isinstance(roh, dict) else None) or []:
        symbol = str(coin.get("symbol") or "").strip().upper()
        if symbol:
            gruppen.setdefault(symbol, []).append(coin)
    treffer = []
    for symbol, coins in gruppen.items():
        if len(coins) != 1:
            continue
        treffer.append(Treffer(symbol + "-USD", str(coins[0].get("name") or symbol), "Krypto", "CoinGecko", "CoinGecko"))
    return tuple(treffer)


def _yahoo(text: str, oeffnen):
    adresse = "https://query2.finance.yahoo.com/v1/finance/search?quotesCount=8&newsCount=0&q=" + quote(text)
    return suche_aus_yahoo(json.loads(hole_text(adresse, oeffnen, "application/json")))


def _gecko(text: str, oeffnen):
    adresse = "https://api.coingecko.com/api/v3/search?query=" + quote(text)
    return suche_aus_coingecko(json.loads(hole_text(adresse, oeffnen, "application/json")))


def _ohne_doppelte(treffer: tuple[Treffer, ...]) -> tuple[Treffer, ...]:
    gesehen = set()
    ergebnis = []
    for eintrag in treffer:
        if eintrag.symbol in gesehen:
            continue
        gesehen.add(eintrag.symbol)
        ergebnis.append(eintrag)
    return tuple(ergebnis)
