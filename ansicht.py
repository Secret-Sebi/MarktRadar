"""Texte für das Fenster. Dieselbe Bewertung, in ganzen Sätzen."""

from typing import Sequence

from analyse import de_prozent, de_zahl


_SAETZE = (
    ("einstieg_pruefen", "Zum Prüfen liegen {namen} vorn."),
    ("sparplan", "Für einen Sparplan sehe ich {namen}."),
    ("beobachten", "Ohne klaren Vorteil bleiben {namen}."),
    ("abwarten", "Schon gelaufen, deshalb kein Nachkauf: {namen}."),
    ("vorsicht", "Im Abwärtstrend liegen {namen}."),
    ("unklar", "Noch unklar sind {namen}."),
    ("unvollstaendig", "Zu wenig Daten haben {namen}."),
    ("fehler", "Gerade nicht geladen sind {namen}."),
)


def kurzname(zeile) -> str:
    name = " ".join(str(zeile.name).split())
    if "ETF" in name or "UCITS" in name:
        return str(zeile.symbol).split(".")[0]
    for endung in (" Aktiengesellschaft", " SE", " AG", " Inc.", " Corporation", " USD"):
        if name.endswith(endung):
            name = name[: -len(endung)].rstrip(",")
            break
    if len(name.split()) > 2:
        return str(zeile.symbol).split(".")[0]
    return name or str(zeile.symbol)


def briefing(zeilen: Sequence) -> str:
    if not zeilen:
        return "Die Liste ist leer. Trag Kürzel in die watchlist.txt ein."
    gruppen = {}
    for zeile in zeilen:
        gruppen.setdefault(zeile.urteil.aktion, []).append(kurzname(zeile))
    saetze = [f"Ich habe {_menge(len(zeilen))} angeschaut."]
    if "einstieg_pruefen" not in gruppen:
        saetze.append("Einen klaren Einstiegsmoment sehe ich gerade nicht.")
    for aktion, vorlage in _SAETZE:
        namen = gruppen.get(aktion)
        if namen:
            saetze.append(vorlage.format(namen=_aufzaehlung(namen)))
    return " ".join(saetze)


def potenzial(zeile) -> dict:
    aktion = zeile.urteil.aktion
    score = int(zeile.urteil.score)
    if aktion in ("fehler", "unklar", "unvollstaendig"):
        return {
            "stufe": "offen",
            "score": None,
            "text": "Zum Potenzial sage ich noch nichts. Dafür fehlen vollständige Kurse.",
        }
    stufe, kopf = _potenzial_stufe(aktion, score)
    return {
        "stufe": stufe,
        "score": score,
        "text": f"{kopf}. Score {score} von 100. {zeile.urteil.grund} Das ist keine Gewinnzusage.",
    }


def _potenzial_stufe(aktion: str, score: int):
    if aktion == "einstieg_pruefen":
        return "hoch", "Potenzial hoch"
    if aktion == "sparplan" and score >= 75:
        return "hoch", "Sparplan-Potenzial hoch"
    if aktion == "sparplan" or (aktion == "beobachten" and score >= 45):
        return "mittel", "Potenzial mittel" if aktion == "beobachten" else "Sparplan-Potenzial mittel"
    return "niedrig", "Potenzial niedrig"


def einzelheiten(zeile) -> str:
    zeilen = []
    technik = getattr(zeile, "technik", None)
    if technik is not None and technik.muster:
        zeilen.append("Muster: " + ", ".join(technik.muster))
    if technik is not None:
        zeilen.append(
            " · ".join(
                (
                    "60 Tage " + de_prozent(technik.rendite_60),
                    "Schwankung " + de_prozent(technik.volatilitaet),
                    f"Stütze {_zahl(technik.stuetze)}",
                    f"Widerstand {_zahl(technik.widerstand)}",
                    _vergleich(technik),
                )
            )
        )
        if technik.hinweise:
            zeilen.append("Hinweis: " + ", ".join(technik.hinweise))
    if zeile.urteil.hinweis_broker:
        zeilen.append(zeile.urteil.hinweis_broker)
    return "\n".join(zeile for zeile in zeilen if zeile)


def _menge(anzahl: int) -> str:
    if anzahl == 1:
        return "einen Wert"
    return f"{anzahl} Werte"


def _aufzaehlung(namen: Sequence[str]) -> str:
    if len(namen) == 1:
        return namen[0]
    if len(namen) == 2:
        return f"{namen[0]} und {namen[1]}"
    return ", ".join(namen[:-1]) + " und " + namen[-1]


def _zahl(wert) -> str:
    if wert is None:
        return "—"
    return de_zahl(wert, 2 if abs(wert) >= 100 else 1)


def _vergleich(technik) -> str:
    if technik.relativ is None:
        return "Vergleich fehlt"
    name = technik.index_titel or "Index"
    return f"gegen {name} {de_prozent(technik.relativ).replace(' %', '')} Punkte"
