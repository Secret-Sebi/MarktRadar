"""Sechs Einflussbereiche. Ein fehlender Bereich bleibt fehlend und wird nicht geschätzt."""

from __future__ import annotations


def faktoren(schritte: dict | None, nachricht: dict | None = None) -> tuple[dict, ...]:
    schritte = schritte if isinstance(schritte, dict) else {}
    nachricht = nachricht if isinstance(nachricht, dict) else {}
    return (
        _nachrichten(schritte, nachricht),
        _fundamental(schritte),
        _fehlt("Makro", "Keine Zins-, Inflations- oder Arbeitsmarktreihe gespeichert."),
        _fehlt("Kapitalströme", "Volumen, Short Interest, Optionen und ETF-Flüsse sind nicht gespeichert."),
        _technik(schritte),
        _fehlt("Branche", "Keine Branchenreihe gespeichert. DAX und S&P sind Marktindizes, kein Sektor."),
    )


def luecken() -> dict[str, str]:
    return {
        "makro": "Keine Zins-, Inflations- oder Arbeitsmarktreihe gespeichert.",
        "kapital": "Volumen, Short Interest, Optionen und ETF-Flüsse sind nicht gespeichert.",
        "branche": "Keine Branchenreihe gespeichert.",
        "prognose": "Kein Horizont ist validiert. Angezeigte Stärken sind keine Wahrscheinlichkeiten.",
    }


def _nachrichten(schritte: dict, nachricht: dict) -> dict:
    stand = _stand(schritte, "nachrichten")
    if nachricht.get("ereignis"):
        return _zeile(
            "Nachrichten",
            "nicht_validiert",
            f"Ereignis {nachricht.get('ereignis')}, Stimmung {nachricht.get('stimmung') or 'unklar'}. "
            f"{nachricht.get('zuordnung') or 'Kursreaktion noch nicht messbar.'} Keine Ursache.",
        )
    if stand == "fehler":
        return _zeile("Nachrichten", "fehler", "Die Nachrichtenquelle hat nicht geantwortet.")
    if stand in ("ok", "nicht_verfuegbar"):
        return _zeile("Nachrichten", "unvollstaendig", "Ein Abruf liegt vor, aber keine gespeicherte Ereignisanalyse.")
    return _zeile("Nachrichten", "fehlt", "Keine Nachricht analysiert.")


def _fundamental(schritte: dict) -> dict:
    stand = _stand(schritte, "fundamental")
    if stand == "ok":
        return _zeile("Fundamental", "vorhanden", "Kennzahlen liegen vor. Daraus wird keine Kaufnote.")
    if stand == "nicht_verfuegbar":
        return _zeile("Fundamental", "nicht_verfuegbar", "Die Quelle antwortete ohne Kennzahlen.")
    if stand == "nicht_anwendbar":
        return _zeile("Fundamental", "nicht_anwendbar", "Für diesen Namen gibt es keine Unternehmenskennzahlen.")
    if stand == "fehler":
        return _zeile("Fundamental", "fehler", "Die Fundamentalquelle hat nicht geantwortet.")
    return _zeile("Fundamental", "fehlt", "Fundamentaldaten fehlen.")


def _technik(schritte: dict) -> dict:
    historie = _stand(schritte, "historie")
    technik = _stand(schritte, "technik")
    if historie == "ok" and technik == "ok":
        return _zeile("Technik", "vorhanden", "Kursmuster liegen vor. Das ist keine Prognose.")
    if historie == "nicht_ausreichend":
        return _zeile("Technik", "unvollstaendig", "Zu wenige historische Schlüsse.")
    if technik == "fehler" or historie == "fehler":
        return _zeile("Technik", "fehler", "Die technische Rechnung ist fehlgeschlagen.")
    return _zeile("Technik", "fehlt", "Technik ist nicht gemessen.")


def _fehlt(name: str, satz: str) -> dict:
    return _zeile(name, "fehlt", satz)


def _stand(schritte: dict, name: str) -> str:
    eintrag = schritte.get(name)
    if isinstance(eintrag, dict):
        return str(eintrag.get("stand") or "")
    return str(eintrag or "")


def _zeile(name: str, stand: str, satz: str) -> dict:
    return {"name": name, "stand": stand, "satz": satz, "validiert": False}
