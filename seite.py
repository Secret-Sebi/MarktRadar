"""Dunkle Seite für das eigene Fenster. Die Texte kommen aus derselben Rechnung."""

from datetime import datetime
from pathlib import Path

from analyse import BERLIN, fenster as handelsfenster, handels_hinweis
from ansicht import briefing, einzelheiten, kurzname, potenzial
from beobachter import _kurs_prozent, _preis, _sortiert, _warte_text

_SEITE = Path(__file__).resolve().parent / "fenster_app" / "seite.html"
_PILLE = {
    "wochenende": "Wochenende",
    "xetra": "Xetra offen",
    "bestpreis": "Handel offen",
    "zu": "Handel zu",
}


def seite_html() -> str:
    return _SEITE.read_text(encoding="utf-8")


def lade_stand() -> dict:
    return {
        "briefing": "Ich hole die Kurse.",
        "status": "Die Liste steht in der watchlist.txt.",
        "markt": "",
        "pille": "…",
        "uhr": "",
        "arbeitet": True,
        "karten": [],
    }


def fehler_stand(text: str) -> dict:
    stand = lade_stand()
    return {
        **stand,
        "briefing": "Die Kurse sind gerade nicht erreichbar. Ich versuche es wieder.",
        "status": text[:180],
        "arbeitet": False,
    }


def stand_bauen(zeilen, moment: datetime, naechste: int, arbeitet: bool = False) -> dict:
    berlin = moment.astimezone(BERLIN)
    tage = ("Mo", "Di", "Mi", "Do", "Fr", "Sa", "So")
    return {
        "briefing": briefing(zeilen),
        "status": f"Zuletzt {berlin:%H:%M} · wieder in {_warte_text(naechste)}",
        "markt": handels_hinweis(moment),
        "pille": _PILLE.get(handelsfenster(moment), "Markt"),
        "uhr": f"{tage[berlin.weekday()]} {berlin:%d.%m.  %H:%M}",
        "arbeitet": arbeitet,
        "karten": tuple(_karte(zeile) for zeile in _sortiert(zeilen)),
    }


def bereich(zeile) -> str:
    symbol = str(getattr(zeile, "symbol", ""))
    if symbol.endswith("-USD"):
        return "Krypto"
    zahlen = getattr(zeile, "kennzahlen", None)
    if zahlen is not None and getattr(zahlen, "ist_etf", False):
        return "ETFs"
    if symbol.endswith(".DE"):
        return "Deutschland"
    if "." in symbol:
        return "Europa"
    return "USA"


def _karte(zeile) -> dict:
    richtung, tag = _richtung(zeile)
    return {
        "symbol": zeile.symbol,
        "name": kurzname(zeile),
        "preis": _preis(zeile),
        "tag": tag,
        "richtung": richtung,
        "titel": zeile.urteil.titel,
        "aktion": zeile.urteil.aktion,
        "grund": zeile.urteil.grund,
        "extra": einzelheiten(zeile),
        "reihe": tuple(round(float(wert), 4) for wert in getattr(zeile, "reihe", ()) or ()),
        "bereich": bereich(zeile),
        **potenzial(zeile),
    }


def _richtung(zeile):
    if zeile.tag_pct is None:
        return "ohne", "—"
    if zeile.tag_pct > 0:
        return "hoch", _kurs_prozent(zeile.tag_pct)
    if zeile.tag_pct < 0:
        return "runter", _kurs_prozent(zeile.tag_pct)
    return "gleich", _kurs_prozent(zeile.tag_pct)
