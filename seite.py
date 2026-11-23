"""Dunkle Seite für das eigene Fenster. Die Texte kommen aus derselben Rechnung."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from analyse import BERLIN, de_zahl, handels_hinweis
from analyse import fenster as handelsfenster
from ansicht import briefing, einzelheiten, kurzname, lage, potenzial
from beobachter import _kurs_prozent, _preis, _sortiert, _warte_text
from muster import VERSION as MUSTER_VERSION

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
        "bild": [],
        "lernen": {
            "abgeschlossen": 0,
            "offen": 0,
            "namen": 0,
            "schwelle": 0,
            "testbar": 0,
            "modell": 0,
            "text": "Noch nichts gelernt.",
        },
        "nachrichten": {"tag": {"meldungen": [], "offen": [], "hinweis": ""}, "woche": {"meldungen": [], "offen": [], "hinweis": ""}},
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
    from auswertung import _markt

    symbol = str(getattr(zeile, "symbol", ""))
    zahlen = getattr(zeile, "kennzahlen", None)
    if zahlen is not None and getattr(zahlen, "ist_etf", False):
        return "ETFs"
    return _markt(symbol, "")


def _karte(zeile) -> dict:
    richtung, tag = _richtung(zeile)
    return {
        "symbol": zeile.symbol,
        "name": kurzname(zeile),
        "preis": _preis(zeile),
        "herkunft": _kurzherkunft(zeile),
        "fenster": "" if getattr(zeile, "datenstatus", "") != "ok" else getattr(zeile, "fenster", "") or "",
        "pruefung": getattr(zeile, "pruefung", "") or "",
        "folge": getattr(zeile, "folge", "") or "",
        "ungewoehnlich": getattr(zeile, "ungewoehnlich", "") or "",
        "markt": getattr(zeile, "markt", "") or "",
        "aufwaerts": _aufwaerts(zeile),
        "fenster_faelle": _fenster_faelle(zeile),
        "muster": _muster_text(zeile),
        "muster_version": MUSTER_VERSION if getattr(zeile, "muster", None) else None,
        "vorschlag": _vorschlag_text(zeile),
        "horizonte": list((getattr(zeile, "muster", None) or {}).get("horizonte") or []),
        "qualitaet": str((getattr(zeile, "muster", None) or {}).get("qualitaet") or ""),
        "datenstatus": getattr(zeile, "datenstatus", "") or "",
        "wert": zeile.preis,
        "tag": tag,
        "tag_wert": zeile.tag_pct,
        "richtung": richtung,
        "titel": zeile.urteil.titel,
        "aktion": zeile.urteil.aktion,
        "grund": zeile.urteil.grund,
        "extra": _herkunft(
            zeile,
            "\n".join(
                teil
                for teil in (
                    lage(zeile),
                    einzelheiten(zeile),
                    getattr(zeile, "pruefung", ""),
                    getattr(zeile, "folge", ""),
                    getattr(zeile, "markt", ""),
                )
                if teil
            ),
        ),
        "bereich": bereich(zeile),
        "schritte": getattr(zeile, "schritte", "") or "",
        "kurszeit": _stempel(getattr(zeile, "kurszeit", None)),
        **potenzial(zeile),
    }


def _kurzherkunft(zeile) -> str:
    quelle = getattr(zeile, "quelle", "") or "Quelle fehlt"
    return f"{quelle} · {_kurszeit(getattr(zeile, 'kurszeit', None))}"


def _herkunft(zeile, text: str) -> str:
    quelle = getattr(zeile, "quelle", "")
    if not quelle:
        return text
    zeile_text = " · ".join(
        (
            f"Quelle: {quelle}",
            getattr(zeile, "kursart", "") or "Kurs",
            getattr(zeile, "datenstatus", "") or "ok",
            f"Kurszeit: {_kurszeit(getattr(zeile, 'kurszeit', None))}",
            f"Währung: {getattr(zeile, 'waehrung', '') or 'fehlt'}",
            f"Handelsplatz: {getattr(zeile, 'handelsplatz', '') or 'fehlt'}",
            _abweich(getattr(zeile, "abweichung", None)),
        )
    )
    hinweis = getattr(zeile, "hinweis", "")
    if hinweis:
        zeile_text = f"{zeile_text}\n{hinweis}"
    gelernt = getattr(zeile, "lernen", "")
    if gelernt:
        zeile_text = f"{gelernt}\n{zeile_text}"
    return (text + "\n" + zeile_text).strip() if text else zeile_text


def _aufwaerts(zeile):
    wert = getattr(zeile, "aufwaerts", None)
    if isinstance(wert, bool) or not isinstance(wert, (int, float)):
        return None
    return float(wert)


def _fenster_faelle(zeile) -> int:
    wert = getattr(zeile, "fenster_faelle", 0)
    if isinstance(wert, bool) or not isinstance(wert, int):
        return 0
    return wert


def _muster_text(zeile) -> str | None:
    bild = getattr(zeile, "muster", None)
    if not isinstance(bild, dict):
        return None
    from muster import als_json

    return als_json(bild)


def _vorschlag_text(zeile) -> str:
    bild = getattr(zeile, "muster", None)
    if isinstance(bild, dict) and bild.get("satz"):
        return str(bild["satz"])
    return ""


def _stempel(wert):
    if isinstance(wert, bool) or not isinstance(wert, int):
        return None
    return wert


def _kurszeit(wert) -> str:
    if not isinstance(wert, int):
        return "fehlt"
    return datetime.fromtimestamp(wert, BERLIN).strftime("%d.%m.%Y %H:%M")


def _abweich(wert) -> str:
    if wert is None:
        return "Abgleich fehlt"
    return f"Abweichung {de_zahl(wert, 1)} %"


def _richtung(zeile):
    if zeile.tag_pct is None:
        return "ohne", "—"
    if zeile.tag_pct > 0:
        return "hoch", _kurs_prozent(zeile.tag_pct)
    if zeile.tag_pct < 0:
        return "runter", _kurs_prozent(zeile.tag_pct)
    return "gleich", _kurs_prozent(zeile.tag_pct)
