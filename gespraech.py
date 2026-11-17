"""Antworten nur aus dem geladenen Stand. Kein erfundener Kurs, kein Auftrag."""

from __future__ import annotations

import re

from analyse import de_zahl

_HILFE = (
    "Frag mich einfach, zum Beispiel was Solana kostet oder wer gerade vorn liegt. "
    "Ich sag nur, was wirklich geladen ist, und ich kaufe nichts."
)


def antwort(frage: str, stand: dict) -> str:
    text = " ".join(str(frage or "").split())[:500]
    if not text:
        return _HILFE
    niedrig = text.lower()
    if niedrig in ("hallo", "hi", "hey", "guten tag"):
        return "Hey. Worum geht's? Nenn mir einen Namen von der Liste."
    karten = tuple(stand.get("karten") or ())
    if not karten:
        return "Die Kurse sind noch nicht da. Gleich kann ich dir dazu was sagen."
    treffer = _finde(niedrig, karten)
    if len(treffer) == 1 and not _ist_liste(niedrig):
        return _eine(treffer[0], niedrig)
    if "verkauf" in niedrig:
        return _verkauf(karten)
    if any(wort in niedrig for wort in ("schlecht", "unten", "letzte")):
        return _reihe("Weiter unten sehe ich", karten[-5:])
    if any(wort in niedrig for wort in ("beste", "besten", "vorn", "oben")):
        return _reihe("Ganz vorn sehe ich gerade", karten[:5])
    if treffer:
        return _reihe("Dazu passen", treffer[:5])
    if any(wort in niedrig for wort in ("gelernt", "lernen", "nachricht")):
        return _wissen(stand)
    if any(wort in niedrig for wort in ("hilfe", "was kannst", "was weißt", "was weisst")):
        return _HILFE
    return "Die habe ich gerade nicht geladen. " + _reihe("Auf der Liste sind zum Beispiel", karten[:5])


def _wissen(stand: dict) -> str:
    lernen = stand.get("lernen") or {}
    nachrichten = (stand.get("nachrichten") or {}).get("woche") or {}
    teile = [str(lernen.get("text") or "Noch nichts gelernt.")]
    meldungen = nachrichten.get("meldungen") or ()
    if meldungen:
        namen = ", ".join(str(eintrag.get("titel") or "") for eintrag in meldungen[:3])
        teile.append(f"Die größte gemessene Bewegung diese Woche: {namen}.")
    elif nachrichten.get("hinweis"):
        teile.append(str(nachrichten["hinweis"]))
    return " ".join(teile)


def _finde(niedrig: str, karten) -> tuple:
    treffer = []
    for karte in karten:
        symbol = str(karte.get("symbol") or "")
        name = str(karte.get("name") or "")
        kurz = symbol.lower().split(".")[0].split("-")[0]
        if symbol and symbol.lower() in niedrig:
            treffer.append(karte)
            continue
        if len(kurz) >= 2 and re.search(rf"\b{re.escape(kurz)}\b", niedrig):
            treffer.append(karte)
            continue
        if any(len(wort) > 2 and re.search(rf"\b{re.escape(wort)}\b", niedrig) for wort in name.lower().split()):
            treffer.append(karte)
    return tuple(treffer)


def _ist_liste(niedrig: str) -> bool:
    return any(wort in niedrig for wort in ("beste", "besten", "schlecht", "verkauf", "liste", "alle"))


def _eine(karte: dict, frage: str) -> str:
    name = _rufname(karte)
    preis = karte.get("preis") or "keinen Preis"
    wert = _zahl(karte.get("wert"))
    if wert is None:
        wert = _zahl(preis)
    genannt = _genannt(frage)
    bewegung = _bewegung(wert, _zahl(karte.get("tag_wert")))
    if genannt and wert is not None and any(_nah(zahl, wert) for zahl in genannt):
        satz = f"Ja, ungefähr. {name} liegt bei {preis}."
    elif genannt and bewegung is not None and any(_nah(zahl, abs(bewegung)) for zahl in genannt):
        richtung = "gefallen" if bewegung < 0 else "gestiegen"
        satz = (
            f"Nein, {name} kostet nicht {_euro(genannt[0])}. Ich sehe {preis}. "
            f"Heute ist {name} um etwa {_euro(abs(bewegung))} {richtung}. Vielleicht meinst du das."
        )
    elif genannt and wert is not None:
        satz = f"Nein. {name} liegt bei {preis}, nicht bei {_euro(genannt[0])}."
    else:
        satz = f"{name} liegt gerade bei {preis}."
    if str(karte.get("symbol") or "").endswith("-USD") and "aktie" in frage:
        satz += " Das ist Krypto, keine Aktie."
    if karte.get("tag"):
        satz += f" Heute: {karte['tag']}."
    if any(wort in frage for wort in ("warum", "kaufen", "verkauf", "einstieg", "potenzial")):
        satz += f" Mein Hinweis ist „{karte.get('titel') or 'unklar'}“. Das ist kein Auftrag."
        if karte.get("text"):
            satz += " " + str(karte["text"])
    else:
        satz += " Das ist der geladene Kurs, nicht der Preis in Trade Republic."
    return satz


def _verkauf(karten) -> str:
    liste = tuple(karte for karte in karten if karte.get("aktion") == "verkauf_pruefen")
    if not liste:
        return "Einen Verkaufshinweis habe ich gerade nicht. Der kommt erst nach genug eigenen Fällen und bleibt eine Prüfung, kein Auftrag."
    namen = ", ".join(_rufname(karte) for karte in liste)
    return f"Bei {namen} würde ich nur prüfen, ob ein Verkauf Sinn hat. Das ist kein Auftrag."


def _reihe(anfang: str, karten) -> str:
    namen = ", ".join(f"{_rufname(karte)} mit {karte.get('preis') or 'ohne Preis'}" for karte in karten)
    return f"{anfang} {namen}."


def _rufname(karte: dict) -> str:
    name = str(karte.get("name") or karte.get("symbol") or "Der Name")
    for endung in (" EUR", " USD"):
        if name.endswith(endung):
            return name[: -len(endung)]
    return name


def _genannt(text: str) -> tuple[float, ...]:
    zahlen = []
    for roh in re.findall(r"\d+(?:\.\d{3})*(?:,\d+)?", text):
        zahl = _zahl(roh)
        if zahl is not None:
            zahlen.append(zahl)
    return tuple(zahlen)


def _zahl(wert) -> float | None:
    if isinstance(wert, bool) or wert is None:
        return None
    if isinstance(wert, (int, float)):
        return float(wert)
    roh = str(wert).split()[0].replace(".", "").replace(",", ".")
    try:
        return float(roh)
    except ValueError:
        return None


def _bewegung(wert: float | None, tag: float | None) -> float | None:
    if wert is None or tag is None:
        return None
    return wert * tag / 100.0


def _nah(links: float, rechts: float) -> bool:
    return abs(links - rechts) <= max(0.2, abs(rechts) * 0.12)


def _euro(wert: float) -> str:
    return de_zahl(wert, 2) + " Euro"
