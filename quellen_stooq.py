"""Tägliche Schlusskurse von Stooq. Kein Echtzeit-Feed und kein API-Schlüssel."""

from __future__ import annotations

from datetime import datetime, timezone
from urllib.parse import quote

from kurse import Bar, Kursdaten, _datenstatus
from quellen import hole_text

_INDEX = {"^GDAXI": "^dax", "^GSPC": "^spx", "^DJI": "^dji", "^IXIC": "^ndq"}
_INDEX_WAEHRUNG = {"^GDAXI": "EUR", "^GSPC": "USD", "^DJI": "USD", "^IXIC": "USD"}
_SUFFIX_WAEHRUNG = {"DE": "EUR", "PA": "EUR", "AS": "EUR", "MI": "EUR", "SW": "CHF", "L": "GBP", "TO": "CAD", "HK": "HKD"}


def stooq_kuerzel(symbol: str) -> str | None:
    if symbol.endswith("-USD") or symbol.startswith("^") and symbol not in _INDEX:
        return None
    if symbol in _INDEX:
        return _INDEX[symbol]
    if "." in symbol:
        return symbol.lower()
    return symbol.lower() + ".us"


def stooq_kurs(symbol: str, oeffnen) -> Kursdaten:
    kuerzel = stooq_kuerzel(symbol)
    if kuerzel is None:
        raise LookupError("Stooq hat für dieses Kürzel kein bekanntes Gegenstück")
    adresse = "https://stooq.com/q/d/l/?s=" + quote(kuerzel, safe="") + "&i=d"
    daten = stooq_aus_csv(symbol, hole_text(adresse, oeffnen, "text/csv"))
    if daten is None:
        raise LookupError("Stooq lieferte keine Kursdatei")
    return daten


def stooq_aus_csv(symbol: str, text: str) -> Kursdaten | None:
    roh = text.lstrip()
    if not roh or roh.startswith("<") or not roh.lower().startswith("date"):
        return None
    balken = []
    for zeile in roh.splitlines()[1:]:
        teile = zeile.split(",")
        if len(teile) < 5:
            continue
        schluss = _zahl(teile[4])
        zeit = _tag(teile[0])
        if schluss is None or schluss <= 0 or zeit is None:
            continue
        balken.append(
            Bar(zeit, _zahl(teile[1]), _zahl(teile[2]), _zahl(teile[3]), schluss, schluss, _zahl(teile[5]) if len(teile) > 5 else None)
        )
    if len(balken) < 2:
        return None
    waehrung = _waehrung(symbol)
    letzter = balken[-1].schluss
    voriger = balken[-2].schluss
    tag = (letzter / voriger - 1.0) * 100.0 if voriger else None
    hinweis = "Schlusskurse von Stooq, kein Echtzeitkurs und nicht splitbereinigt."
    if not waehrung:
        hinweis += " Währung steht in der Datei nicht."
    else:
        hinweis += " Währung ist aus dem Kürzel abgeleitet, nicht aus der Datei."
    hochs = tuple(bar.hoch for bar in balken[-252:] if bar.hoch is not None)
    tiefs = tuple(bar.tief for bar in balken[-252:] if bar.tief is not None)
    return Kursdaten(
        symbol=symbol,
        name=symbol,
        waehrung=waehrung,
        preis=letzter,
        tag_pct=tag,
        ist_etf=False,
        schluesse=tuple(bar.schluss for bar in balken),
        hoch_52w=max(hochs) if hochs else None,
        tief_52w=min(tiefs) if tiefs else None,
        balken=tuple(balken),
        hat_bereinigt=False,
        quelle="Stooq",
        kurszeit=balken[-1].zeit,
        datenstatus="unvollstaendig" if _datenstatus(balken[-1].zeit) == "ok" else "veraltet",
        kursart="schluss",
        handelsplatz="Stooq",
        hinweis=hinweis,
    )


def _waehrung(symbol: str) -> str:
    if symbol in _INDEX_WAEHRUNG:
        return _INDEX_WAEHRUNG[symbol]
    if "." not in symbol:
        return "USD"
    return _SUFFIX_WAEHRUNG.get(symbol.rsplit(".", 1)[-1], "")


def _zahl(wert: str) -> float | None:
    try:
        zahl = float(wert)
    except (TypeError, ValueError):
        return None
    return zahl


def _tag(wert: str) -> int | None:
    try:
        moment = datetime.strptime(wert, "%Y-%m-%d").replace(tzinfo=timezone.utc)  # noqa: UP017
    except ValueError:
        return None
    return int(moment.timestamp())
