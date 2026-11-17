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
    faktor = wechselkurs(code)
    if not isinstance(faktor, (int, float)) or isinstance(faktor, bool) or faktor <= 0:
        return daten
    hinweis = (
        f"Nur der heutige Wechselkurs {code} nach Euro. "
        "Die Prozente bleiben die der Originalwährung. Die alten Stände sind keine historischen Eurokurse. "
        "Das ist nicht der Trade-Republic-Preis."
    )
    return _skaliere(daten, float(faktor) / teiler, hinweis)


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
