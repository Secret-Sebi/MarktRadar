"""Texte für das Fenster. Dieselbe Bewertung, in ganzen Sätzen."""

from collections.abc import Sequence

from analyse import de_prozent, de_zahl


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
    if len(zeilen) == 1:
        return "Ein Wert geladen."
    return f"{len(zeilen)} Werte geladen."


def potenzial(zeile) -> dict:
    if int(getattr(zeile, "faelle", 0) or 0) <= 0:
        return {
            "stufe": "offen",
            "score": None,
            "gelernt": False,
            "text": "Zu dieser Aktie habe ich noch nichts gelernt. Deshalb nenne ich kein Potenzial.",
        }
    aktion = zeile.urteil.aktion
    score = int(zeile.urteil.score)
    if aktion in ("fehler", "unklar", "unvollstaendig"):
        return {
            "stufe": "offen",
            "score": None,
            "gelernt": True,
            "text": "Zum Potenzial sage ich noch nichts. Dafür fehlen vollständige Kurse.",
        }
    stufe, kopf = _potenzial_stufe(aktion, score)
    return {
        "stufe": stufe,
        "score": score,
        "gelernt": True,
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


def lage(zeile) -> str:
    fundamental = getattr(zeile, "fundamental", "") or "fehlt"
    if int(getattr(zeile, "faelle", 0) or 0) <= 0:
        nachrichten = "noch nichts zu dieser Aktie gelernt"
    else:
        nachrichten = "gespeicherte Fälle, ohne Ursachenbehauptung"
    markt = "fehlt"
    risiko = "fehlt"
    tech = getattr(zeile, "technik", None)
    if tech is not None and getattr(tech, "relativ", None) is not None:
        markt = f"gegen {tech.index_titel or 'Index'} {de_prozent(tech.relativ)}"
    preis = getattr(zeile, "preis", None)
    stuetze = None if tech is None else getattr(tech, "stuetze", None)
    if stuetze and preis:
        risiko = (
            f"bis zur Stütze {de_zahl((preis / stuetze - 1.0) * 100.0, 1)} %. "
            "Das ist kein garantierter Verlust."
        )
    return "\n".join(
        (
            f"Fundamental: {fundamental}",
            f"Nachrichten: {nachrichten}",
            f"Markt: {markt}",
            f"Risiko: {risiko}",
        )
    )


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
    return "\n".join(zeile for zeile in zeilen if zeile)


def _zahl(wert) -> str:
    if wert is None:
        return "—"
    return de_zahl(wert, 2 if abs(wert) >= 100 else 1)


def _vergleich(technik) -> str:
    if technik.relativ is None:
        return "Vergleich fehlt"
    name = technik.index_titel or "Index"
    return f"gegen {name} {de_prozent(technik.relativ).replace(' %', '')} Punkte"
