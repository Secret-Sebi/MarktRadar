"""Kryptokurse über die öffentliche CoinGecko-API. Kein erfundener Preis."""

from __future__ import annotations

import json
import os
from urllib.parse import quote

from kurse import Bar, Kursdaten, _datenstatus
from quellen import hole_text

_FEST = {"BTC-USD": ("bitcoin", "Bitcoin"), "ETH-USD": ("ethereum", "Ethereum"), "SOL-USD": ("solana", "Solana")}
_BASIS = "https://api.coingecko.com/api/v3"


def gecko_kurs(symbol: str, oeffnen) -> Kursdaten:
    coin_id, name = _coin(symbol, oeffnen)
    preis = json.loads(hole_text(_preis_adresse(coin_id), oeffnen, "application/json", _kopf()))
    try:
        chart = json.loads(hole_text(_chart_adresse(coin_id), oeffnen, "application/json", _kopf()))
    except (ConnectionError, LookupError, json.JSONDecodeError):
        chart = {"prices": []}
    daten = kurs_aus_gecko(symbol, name, preis, chart)
    if daten is None:
        raise LookupError("CoinGecko lieferte keinen Preis")
    return daten


def kurs_aus_gecko(symbol: str, name: str, preis: dict, chart: dict) -> Kursdaten | None:
    coin_id = _FEST.get(symbol, (None, None))[0] or _id_aus_preis(preis)
    block = preis.get(coin_id) if isinstance(preis, dict) and coin_id else None
    if not isinstance(block, dict):
        block = next((wert for wert in preis.values() if isinstance(wert, dict) and "eur" in wert), None) if isinstance(preis, dict) else None
    if not isinstance(block, dict) or not isinstance(block.get("eur"), (int, float)) or isinstance(block.get("eur"), bool):
        return None
    letzter = float(block["eur"])
    if letzter <= 0:
        return None
    balken = _balken(chart if isinstance(chart, dict) else {})
    if not balken or balken[-1].schluss != letzter:
        zeit = block.get("last_updated_at")
        kurszeit = int(zeit) if isinstance(zeit, (int, float)) and not isinstance(zeit, bool) else None
        balken = balken + (Bar(kurszeit, letzter, letzter, letzter, letzter, letzter, None),)
    aenderung = block.get("eur_24h_change")
    tag = float(aenderung) if isinstance(aenderung, (int, float)) and not isinstance(aenderung, bool) else None
    kurszeit = balken[-1].zeit
    return Kursdaten(
        symbol=symbol,
        name=name or symbol,
        waehrung="EUR",
        preis=letzter,
        tag_pct=tag,
        ist_etf=False,
        schluesse=tuple(bar.schluss for bar in balken),
        hoch_52w=max(bar.schluss for bar in balken),
        tief_52w=min(bar.schluss for bar in balken),
        balken=tuple(balken),
        hat_bereinigt=False,
        quelle="CoinGecko",
        kurszeit=kurszeit,
        datenstatus="veraltet" if _datenstatus(kurszeit, krypto=True) == "veraltet" else "unvollstaendig",
        kursart="aggregiert",
        handelsplatz="CoinGecko",
        hinweis="Aggregierter CoinGecko-Preis in Euro, kein Börsen-Echtzeitkurs und nicht der Trade-Republic-Preis. Deshalb kein Einstiegssignal.",
    )


def _coin(symbol: str, oeffnen):
    if symbol in _FEST:
        return _FEST[symbol]
    ticker = symbol[:-4] if symbol.endswith("-USD") else ""
    if not ticker:
        raise LookupError("CoinGecko wird nur für USD-Paare genutzt")
    roh = json.loads(hole_text(_BASIS + "/search?query=" + quote(ticker), oeffnen, "application/json", _kopf()))
    coins = [coin for coin in (roh.get("coins") or []) if str(coin.get("symbol", "")).upper() == ticker]
    if len(coins) != 1 or not coins[0].get("id"):
        raise LookupError("CoinGecko-Ticker ist nicht eindeutig")
    return str(coins[0]["id"]), str(coins[0].get("name") or symbol)


def _balken(chart: dict):
    preise = chart.get("prices") or []
    volumen = chart.get("total_volumes") or []
    balken = []
    for index, punkt in enumerate(preise):
        if not isinstance(punkt, (list, tuple)) or len(punkt) < 2:
            continue
        preis = punkt[1]
        if isinstance(preis, bool) or not isinstance(preis, (int, float)) or preis <= 0:
            continue
        zeit = int(punkt[0] / 1000) if isinstance(punkt[0], (int, float)) else None
        menge = None
        punkt_volumen = volumen[index] if index < len(volumen) else None
        if (
            isinstance(punkt_volumen, (list, tuple))
            and len(punkt_volumen) > 1
            and isinstance(punkt_volumen[1], (int, float))
            and not isinstance(punkt_volumen[1], bool)
        ):
            menge = float(punkt_volumen[1])
        balken.append(Bar(zeit, None, None, None, float(preis), float(preis), menge))
    return tuple(balken)


def _preis_adresse(coin_id: str) -> str:
    return (
        _BASIS + "/simple/price?ids=" + quote(coin_id)
        + "&vs_currencies=eur&include_24hr_change=true&include_last_updated_at=true"
    )


def _chart_adresse(coin_id: str) -> str:
    return _BASIS + "/coins/" + quote(coin_id) + "/market_chart?vs_currency=eur&days=365&interval=daily"


def _id_aus_preis(preis: dict) -> str | None:
    if not isinstance(preis, dict) or len(preis) != 1:
        return None
    return next(iter(preis))


def _kopf() -> dict:
    kopf = {"User-Agent": "MarktRadar/1.0", "Accept": "application/json"}
    schluessel = os.environ.get("COINGECKO_API_KEY", "").strip()
    if schluessel:
        kopf["x-cg-demo-api-key"] = schluessel
    return kopf
