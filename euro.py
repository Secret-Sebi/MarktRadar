"""Rechnet einen echten Kurs in Euro um. Ohne Wechselkurs bleibt die Ursprungswährung.

Ein Wechselkurs gilt höchstens vier Kalendertage. Das deckt ein Wochenende und einen
Feiertag. Ein vollständiger Börsenkalender liegt nicht vor. Zwei fehlende Werktage
gelten nicht mehr als Feiertag. Ein späterer Wechselkurs wird für einen früheren
Balken nicht verwendet.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from kurse import Bar, Kursdaten

_PENCE = {"GBp": "GBP", "GBX": "GBP"}
_MAX_ALTER = 4 * 86400
_JAHR = 365 * 86400


def nach_euro(daten: Kursdaten, wechselkurs) -> Kursdaten:
    code, teiler = _basis(daten.waehrung)
    if not daten.waehrung or (code == "EUR" and teiler == 1):
        return daten
    if code == "EUR":
        return _skaliere(daten, 1 / teiler, "Pence wurden in Euro umgerechnet.")
    geliefert = wechselkurs(code)
    if isinstance(geliefert, (tuple, list)):
        historisch = _mit_reihe(daten, geliefert, teiler)
        if historisch is not None:
            return historisch
        return daten
    if not isinstance(geliefert, (int, float)) or isinstance(geliefert, bool) or geliefert <= 0:
        return daten
    hinweis = (
        f"Nur der heutige Wechselkurs {code} nach Euro. "
        "Die Prozente bleiben die der Originalwährung. Die alten Stände sind keine historischen Eurokurse. "
        "Das ist nicht der Trade-Republic-Preis."
    )
    return _skaliere(daten, float(geliefert) / teiler, hinweis)


def _mit_reihe(daten: Kursdaten, reihe, teiler: float) -> Kursdaten | None:
    kurse = _kurse(reihe)
    if len(kurse) < 2 or not daten.balken:
        return None
    paare = []
    for bar in daten.balken:
        if not isinstance(bar.zeit, int) or isinstance(bar.zeit, bool):
            continue
        gefunden = _rate_bis(kurse, bar.zeit)
        if gefunden is None:
            continue
        paare.append((bar, gefunden[1] / teiler))
    if len(paare) < 2 or len(paare) * 2 < len(daten.balken):
        return None
    referenz = daten.kurszeit if isinstance(daten.kurszeit, int) and not isinstance(daten.kurszeit, bool) else paare[-1][0].zeit
    live = _rate_bis(kurse, referenz)
    if live is None or not _live_ok(live[0], referenz, daten.zeitzone):
        return _ohne_euro(daten, "Aktueller Kurs ohne Wechselkurs zum Kurszeitpunkt. Nicht als Euro ausgewiesen.")
    balken = tuple(_bar_um(bar, faktor) for bar, faktor in paare)
    hoch, tief = _grenzen(balken)
    fehlend = len(daten.balken) - len(paare)
    hinweis = "Euro mit dem Wechselkurs des jeweiligen Handelstags. Das ist nicht der Trade-Republic-Preis."
    if fehlend:
        hinweis += f" {fehlend} Schlüsse ohne Wechselkurs innerhalb von 4 Tagen wurden weggelassen."
    if hoch is None or tief is None:
        hinweis += " 52-Wochen-Hoch und -Tief nicht verfügbar."
    schluesse = tuple(bar.bereinigt for bar in balken)
    tag = daten.tag_pct
    if len(schluesse) >= 2 and schluesse[-2] > 0:
        tag = (schluesse[-1] / schluesse[-2] - 1.0) * 100.0
    return replace(
        daten,
        waehrung="EUR",
        preis=daten.preis * (live[1] / teiler),
        tag_pct=tag,
        schluesse=schluesse,
        hoch_52w=hoch,
        tief_52w=tief,
        balken=balken,
        hinweis=f"{daten.hinweis} {hinweis}".strip(),
    )


def _kurse(reihe) -> tuple[tuple[int, float], ...]:
    kurse = tuple(
        (int(zeit), float(rate))
        for zeit, rate in reihe
        if isinstance(zeit, int) and not isinstance(zeit, bool) and isinstance(rate, (int, float)) and not isinstance(rate, bool) and rate > 0
    )
    return tuple(sorted(kurse))


def _bar_um(bar: Bar, faktor: float) -> Bar:
    return Bar(
        bar.zeit,
        _mal(bar.oeffnen, faktor),
        _mal(bar.hoch, faktor),
        _mal(bar.tief, faktor),
        bar.schluss * faktor,
        bar.bereinigt * faktor,
        bar.volumen,
    )


def _ohne_euro(daten: Kursdaten, satz: str) -> Kursdaten:
    return replace(daten, hinweis=f"{daten.hinweis} {satz}".strip())


def _rate_bis(kurse: tuple[tuple[int, float], ...], zeit: int) -> tuple[int, float] | None:
    """Letzter Kurs, der nicht nach dem Balken liegt und nicht älter als vier Tage ist."""
    grenze = int(zeit)
    gewaehlt = None
    for fx_zeit, rate in kurse:
        if fx_zeit > grenze:
            break
        if grenze - fx_zeit <= _MAX_ALTER:
            gewaehlt = (fx_zeit, rate)
    return gewaehlt


def _live_ok(fx_zeit: int, quote_zeit: int, zeitzone: str) -> bool:
    """Der aktuelle Kurs braucht denselben Handelstag oder nur Wochenende und höchstens einen Feiertag."""
    if fx_zeit > quote_zeit or quote_zeit - fx_zeit > _MAX_ALTER:
        return False
    fx_tag = _handelstag(fx_zeit, zeitzone)
    quote_tag = _handelstag(quote_zeit, zeitzone)
    if fx_tag == quote_tag:
        return True
    dazwischen = []
    tag = fx_tag + timedelta(days=1)
    while tag < quote_tag:
        dazwischen.append(tag)
        tag += timedelta(days=1)
    if quote_tag.weekday() == 0 and all(ein_tag.weekday() >= 5 for ein_tag in dazwischen):
        return True
    return len([ein_tag for ein_tag in dazwischen if ein_tag.weekday() < 5]) == 1


def _handelstag(zeit: int, zeitzone: str):
    try:
        zone = ZoneInfo(zeitzone or "UTC")
    except (ZoneInfoNotFoundError, ValueError):
        zone = ZoneInfo("UTC")
    return datetime.fromtimestamp(int(zeit), zone).date()


def _grenzen(balken: tuple[Bar, ...]) -> tuple[float | None, float | None]:
    if not balken or not isinstance(balken[0].zeit, int) or not isinstance(balken[-1].zeit, int):
        return None, None
    if balken[-1].zeit - balken[0].zeit < _JAHR:
        return None, None
    start = balken[-1].zeit - _JAHR
    hochs = [bar.hoch for bar in balken if isinstance(bar.zeit, int) and bar.zeit >= start and bar.hoch is not None]
    tiefs = [bar.tief for bar in balken if isinstance(bar.zeit, int) and bar.zeit >= start and bar.tief is not None]
    if not hochs or not tiefs:
        return None, None
    return max(hochs), min(tiefs)


def _basis(waehrung: str) -> tuple[str, float]:
    if waehrung in _PENCE:
        return _PENCE[waehrung], 100.0
    return waehrung, 1.0


def _skaliere(daten: Kursdaten, faktor: float, hinweis: str) -> Kursdaten:
    balken = tuple(
        Bar(
            bar.zeit,
            _mal(bar.oeffnen, faktor),
            _mal(bar.hoch, faktor),
            _mal(bar.tief, faktor),
            bar.schluss * faktor,
            bar.bereinigt * faktor,
            bar.volumen,
        )
        for bar in daten.balken
    )
    return replace(
        daten,
        waehrung="EUR",
        preis=daten.preis * faktor,
        schluesse=tuple(wert * faktor for wert in daten.schluesse),
        hoch_52w=_mal(daten.hoch_52w, faktor),
        tief_52w=_mal(daten.tief_52w, faktor),
        balken=balken,
        hinweis=f"{daten.hinweis} {hinweis}".strip(),
    )


def _mal(wert: float | None, faktor: float) -> float | None:
    if wert is None:
        return None
    return wert * faktor
