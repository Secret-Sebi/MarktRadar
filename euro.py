"""Rechnet einen echten Kurs in Euro um. Ohne Wechselkurs bleibt die Ursprungswährung."""

from __future__ import annotations

from dataclasses import replace

from kurse import Bar, Kursdaten

_PENCE = {"GBp": "GBP", "GBX": "GBP"}


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
    kurse = tuple(
        (int(zeit), float(rate))
        for zeit, rate in reihe
        if isinstance(zeit, int) and not isinstance(zeit, bool) and isinstance(rate, (int, float)) and not isinstance(rate, bool) and rate > 0
    )
    kurse = tuple(sorted(kurse))
    if len(kurse) < 2 or not daten.balken:
        return None
    paare = []
    for bar in daten.balken:
        rate = _rate_bis(kurse, bar.zeit)
        if rate is None:
            continue
        paare.append((bar, rate / teiler))
    if len(paare) < 2 or len(paare) * 2 < len(daten.balken):
        return None
    balken = tuple(
        Bar(bar.zeit, _mal(bar.oeffnen, faktor), _mal(bar.hoch, faktor), _mal(bar.tief, faktor), bar.schluss * faktor, bar.bereinigt * faktor, bar.volumen)
        for bar, faktor in paare
    )
    letzter = paare[-1][1]
    fehlend = len(daten.balken) - len(paare)
    hinweis = "Euro mit dem Wechselkurs des jeweiligen Handelstags. Das ist nicht der Trade-Republic-Preis."
    if fehlend:
        hinweis += f" {fehlend} ältere Schlüsse ohne Wechselkurs wurden weggelassen."
    schluesse = tuple(bar.bereinigt for bar in balken)
    tag = daten.tag_pct
    if len(schluesse) >= 2 and schluesse[-2] > 0:
        tag = (schluesse[-1] / schluesse[-2] - 1.0) * 100.0
    return replace(
        daten,
        waehrung="EUR",
        preis=daten.preis * letzter,
        tag_pct=tag,
        schluesse=schluesse,
        hoch_52w=_mal(daten.hoch_52w, letzter),
        tief_52w=_mal(daten.tief_52w, letzter),
        balken=balken,
        hinweis=f"{daten.hinweis} {hinweis}".strip(),
    )


def _rate_bis(kurse: tuple[tuple[int, float], ...], zeit: int) -> float | None:
    tag = int(zeit) // 86400
    gewaehlt = None
    for fx_zeit, rate in kurse:
        if fx_zeit // 86400 <= tag:
            gewaehlt = rate
            continue
        break
    return gewaehlt


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
