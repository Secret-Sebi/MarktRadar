"""Ereignisse aus der Überschrift. Das ist keine validierte Prognose und keine Ursache."""

from __future__ import annotations

_REGELN = (
    ("sicherheit", ("hack", "breach", "cyberangriff", "datenleck", "ransomware")),
    ("insider", ("insiderkauf", "insiderverkauf", "insider buying", "insider selling")),
    ("gericht", ("lawsuit", "klage", "gericht", "verdict", "ermittlung")),
    ("regulierung", ("regulierung", "antitrust", "verbot", "gesetz", "ban ")),
    ("personal", ("ceo", "vorstand", "tritt zurück", "steps down", "resign", "ernennt", "interim")),
    ("quartal", ("earnings", "quartal", "umsatz", "gewinn", "revenue", "zahlen")),
    ("prognose", ("prognose", "guidance", "outlook", "ausblick")),
    ("uebernahme", ("übernahme", "uebernahme", "takeover", "merger", "fusion")),
    ("partnerschaft", ("partnerschaft", "partnership", "kooperation", "partners with")),
    ("chip", ("chip", "halbleiter", "semiconductor", "gpu")),
    ("ki", ("künstliche intelligenz", "kuenstliche intelligenz", "artificial intelligence", " ai ")),
    ("produkt", ("neues produkt", "launches", "stellt vor", "unveils")),
    ("analyst", ("upgrade", "downgrade", "kursziel", "price target", "analyst")),
    ("investition", ("investition", "expansion", "baut ein werk", "invests")),
    ("finanzierung", ("insolvenz", "bankruptcy", "verschuldung", "debt ")),
    ("makro", ("leitzins", "ezb", " fed", "fed ", "inflation", "zins")),
    ("geopolitik", ("sanktion", "zoll", "tariff", "krieg")),
    ("krypto", ("bitcoin", "ethereum", "krypto", "crypto", "blockchain")),
    ("branche", ("branche", "sektor", "industry")),
)
_POSITIV = ("beat", "raises", "hebt", "rekord", "partnership", "partnerschaft", "stark", "strong demand")
_NEGATIV = ("worried", "klage", "lawsuit", "verfehlt", "misses", "senkt", "slump", "losing streak", "schrumpft", "shrinks", "schwächer", "schwaecher")
_GERUECHT = ("could", "might", " may ", "rumor", "gerücht", "geruecht", "speculation", "reportedly", "angeblich", "odds", "prediction market")
_BEKANNT = ("reuters", "bloomberg", "dpa", "handelsblatt", "sec.gov")
_INDIREKT = {"nvidia": ("AMD", "AVGO"), "nvda": ("AMD", "AVGO")}
_STOP = {"the", "a", "an", "of", "und", "der", "die", "das", "to", "for", "with", "on", "in"}


def analysiere(
    titel: str,
    quelle: str = "",
    symbol: str = "",
    name: str = "",
    veroeffentlicht: int | None = None,
    erfasst: int | None = None,
    schon: bool = False,
) -> dict:
    text = f" {str(titel or '').lower()} "
    treffer = _treffer(text)
    ereignis = treffer[0][0] if treffer else "sonstiges"
    weitere = [name_regel for name_regel, _anzahl in treffer[1:3]]
    bestaetigt = _bestaetigt(text, quelle)
    stimmung, staerke = _stimmung(text)
    bezug = _bezug(text, symbol, name)
    relevanz = 70 if bezug else 25
    if ereignis == "sonstiges":
        relevanz = min(relevanz, 40)
    verspaetet = (
        isinstance(veroeffentlicht, int)
        and isinstance(erfasst, int)
        and erfasst - veroeffentlicht > 6 * 3600
    )
    unsicherheit = "hoch" if bestaetigt != "bestaetigt" or verspaetet or schon else "mittel"
    if bestaetigt == "bestaetigt" and not verspaetet and not schon and any(name_quelle in quelle.lower() for name_quelle in _BEKANNT):
        unsicherheit = "niedrig"
    return {
        "ereignis": ereignis,
        "weitere": weitere,
        "bestaetigt": bestaetigt,
        "stimmung": stimmung,
        "staerke": staerke,
        "relevanz": relevanz,
        "neu": not schon,
        "dauer": _dauer(ereignis),
        "unsicherheit": unsicherheit,
        "verspaetet": verspaetet,
        "wettbewerber": _indirekt(text) if ereignis in ("chip", "ki", "produkt", "personal") else (),
        "satz": _satz(ereignis, stimmung, staerke, bestaetigt, schon, verspaetet),
        "validiert": False,
    }


def schluessel(symbol: str, ereignis: str, titel: str) -> str:
    woerter = [wort for wort in _woerter(titel) if wort not in _STOP][:6]
    return f"{symbol.upper()}:{ereignis}:{' '.join(woerter)}"


def zuordnung(aktie: float | None, index: float | None, weitere: int = 0, davor: float | None = None) -> str:
    if aktie is None:
        return "Kursreaktion noch nicht messbar"
    if weitere > 0:
        return "Mehrere mögliche Einflussfaktoren"
    if davor is not None and abs(davor) >= 1.0 and abs(davor) > abs(aktie):
        return "Kursbewegung bereits vor der Veröffentlichung erkennbar"
    if index is None:
        return "Keine eindeutige Zuordnung möglich. Der Vergleichsindex fehlt."
    abstand = aktie - index
    if abs(abstand) < 1.0:
        return "Kursbewegung überwiegend durch den Gesamtmarkt erklärbar"
    if abs(abstand) >= 2.0 and abs(aktie) > abs(index):
        return "Möglicher Einfluss. Keine Ursache."
    return "Keine eindeutige Zuordnung möglich"


def lesart(name: str, bild: dict | None) -> str:
    if not bild:
        return ""
    kern = (
        f"Ereignis {bild.get('ereignis')}, Stimmung {bild.get('stimmung')}, "
        f"geschätzte Stärke {bild.get('staerke')}. Keine validierte Wahrscheinlichkeit."
    )
    if name == "Nachrichten":
        return kern + " Eine Meldung ist kein Kaufgrund."
    if name == "Defensiv":
        return kern + " Defensiv bleibt bei bestätigtem negativem Ereignis außen."
    if name == "Momentum":
        return kern + " Momentum folgt der Kursbewegung, nicht der Überschrift."
    if name == "Trend":
        return kern + " Der Trend bleibt die Regel, die Meldung nur ein Hinweis."
    if name == "Fundament":
        return kern + " Eine Überschrift ersetzt keine Kennzahl."
    if name == "Experiment":
        return kern + " Das Experiment übernimmt die Einschätzung nicht als Order."
    return kern + " Die eigene Regel bleibt zuständig."


def defensiv_stoppt(bild: dict | None) -> bool:
    if not bild:
        return False
    try:
        staerke = int(bild.get("staerke"))
    except (TypeError, ValueError):
        return False
    return bild.get("bestaetigt") == "bestaetigt" and staerke <= -40 and not bild.get("verspaetet")


def _treffer(text: str) -> list[tuple[str, int]]:
    gefunden = []
    for name, woerter in _REGELN:
        anzahl = sum(1 for wort in woerter if wort in text)
        if anzahl:
            gefunden.append((name, anzahl))
    gefunden.sort(key=lambda paar: (-paar[1], paar[0]))
    return gefunden


def _bestaetigt(text: str, quelle: str) -> str:
    if any(wort in text for wort in _GERUECHT):
        return "geruecht"
    if any(name in quelle.lower() for name in _BEKANNT) and any(wort in text for wort in ("announces", "meldet", "earnings", "quartal")):
        return "bestaetigt"
    return "unklar"


def _stimmung(text: str) -> tuple[str, int]:
    positiv = any(wort in text for wort in _POSITIV)
    negativ = any(wort in text for wort in _NEGATIV)
    if positiv and negativ:
        return "gemischt", 0
    if positiv:
        return "positiv", 40
    if negativ:
        return "negativ", -40
    return "neutral", 0


def _bezug(text: str, symbol: str, name: str) -> bool:
    kuerzel = symbol.split(".")[0].split("-")[0].lower()
    if len(kuerzel) >= 2 and f" {kuerzel} " in text:
        return True
    token = next((wort.lower() for wort in str(name or "").split() if len(wort) >= 4), "")
    return bool(token) and token in text


def _dauer(ereignis: str) -> str:
    if ereignis in ("personal", "analyst", "insider"):
        return "kurz"
    if ereignis in ("regulierung", "geopolitik", "finanzierung"):
        return "lang"
    return "mittel"


def _indirekt(text: str) -> tuple[str, ...]:
    for name, ziele in _INDIREKT.items():
        if name in text:
            return ziele
    return ()


def _satz(ereignis: str, stimmung: str, staerke: int, bestaetigt: str, schon: bool, verspaetet: bool) -> str:
    teile = [f"Ereignis {ereignis}, Stimmung {stimmung}, geschätzte Stärke {staerke} von -100 bis 100."]
    teile.append(f"Bestätigung: {bestaetigt}.")
    if schon:
        teile.append("Dieselbe Entscheidung ist schon erfasst und zählt nicht noch einmal.")
    if verspaetet:
        teile.append("Die Meldung war bei der Erfassung schon verspätet und gilt nicht als damals bekannt.")
    teile.append("Das ist keine Kursursache und kein Auftrag.")
    return " ".join(teile)


def _woerter(titel: str) -> list[str]:
    roh = []
    wort = []
    for zeichen in str(titel or "").lower():
        if zeichen.isalnum():
            wort.append(zeichen)
        elif wort:
            roh.append("".join(wort))
            wort = []
    if wort:
        roh.append("".join(wort))
    return roh
