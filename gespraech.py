"""Antworten nur aus dem geladenen Stand. Kein erfundener Kurs, kein Auftrag."""

from __future__ import annotations

import re

from analyse import de_zahl

_HILFE = (
    "Frag mich einfach, zum Beispiel was Solana kostet. "
    "Ich sag nur, was wirklich geladen ist, und ich kaufe nichts. Ein Hallo reicht auch."
)
_BEKANNT = {
    "hallo", "hi", "hey", "moin", "servus", "na", "yo", "guten", "gute", "tag", "morgen", "abend", "nacht",
    "wie", "gehts", "geht", "es", "dir", "euch", "alles", "klar", "soweit", "gut",
    "danke", "dankeschoen", "dankeschön", "super", "cool", "passt", "prima", "nice",
    "tschuess", "tschüss", "tschau", "ciao", "bis", "spaeter", "später", "dann",
    "wer", "bist", "du", "was", "machst", "kannst", "hilfe",
    "und", "auch", "mal", "eben", "so", "mir", "ja", "nein", "bitte", "ok", "okay", "freut", "mich", "oder",
    "ein", "einfach", "da", "ich", "bin",
}
_PARTIKEL = {
    "denn", "doch", "aber", "bei", "zusammen", "schönen", "schoenen", "schoen",
    "wieder", "heute", "heut", "eigentlich", "gerade", "schon", "noch", "wohl", "man", "ihr", "uns",
}


def antwort(frage: str, stand: dict) -> str:
    text = " ".join(str(frage or "").split())[:500]
    if not text:
        return _HILFE
    niedrig = text.lower()
    treffer = _treffer(niedrig, stand)
    gespraech = _smalltalk(niedrig)
    if gespraech and not treffer:
        return gespraech
    if any(wort in niedrig for wort in ("verkauf", "kaufen", "prüfen", "pruefen", "einstieg", "beste", "besten", "soll ich", "was soll")):
        return _rat(niedrig, treffer, stand)
    karten = tuple(stand.get("karten") or ())
    if not karten and not treffer:
        return "Die Kurse sind noch nicht da. Gleich kann ich dir dazu was sagen."
    if len(treffer) == 1:
        satz = _eine(treffer[0], niedrig)
        if _begruesst(niedrig):
            return "Hey. " + satz
        return satz
    if treffer:
        return _reihe("Dazu passen", treffer[:5])
    if any(wort in niedrig for wort in ("gelernt", "lernen", "nachricht")):
        return _wissen(stand)
    if any(wort in niedrig for wort in ("hilfe", "was kannst", "was weißt", "was weisst")):
        return _HILFE
    return "Die habe ich gerade nicht geladen. " + _reihe("Auf der Liste sind zum Beispiel", karten[:5])


def _worte(text: str) -> tuple[str, ...]:
    roh = text.lower().replace("'", "").replace("’", "")
    return tuple(re.findall(r"[a-zäöüß]+", roh))


def _begruesst(text: str) -> bool:
    return bool(set(_worte(text)) & {"hallo", "hi", "hey", "moin", "servus", "yo", "guten", "gute", "schönen", "schoenen"})


def _smalltalk(text: str) -> str | None:
    worte = _worte(text)
    if not worte or any(wort not in _BEKANNT and wort not in _PARTIKEL for wort in worte):
        return None
    if not any(wort in _BEKANNT for wort in worte):
        return None
    menge = set(worte)
    if menge & {"tschuess", "tschüss", "tschau", "ciao", "bis"}:
        return "Bis dann. Die Liste bleibt hier, falls du später noch einen Kurs willst."
    if menge & {"danke", "dankeschoen", "dankeschön"}:
        return "Gern. Sag einfach Bescheid, wenn du noch einen Namen hören willst."
    if menge & {"kannst", "hilfe"} or {"wer", "bist"} <= menge or {"was", "machst"} <= menge:
        return _HILFE
    if menge & {"gehts", "geht"} or {"alles", "klar"} <= menge or {"alles", "gut"} <= menge:
        if _begruesst(text):
            return "Hey, mir geht's gut. Ich schau gerade auf die Kurse. Wonach soll ich gucken?"
        return "Mir geht's gut. Die Liste ist da. Nenn mir einen Namen, dann sag ich dir Preis, Zeitpunkt und Quelle."
    if _begruesst(text) or menge & {"na"}:
        return "Hey. Ich bin da. Frag mich nach einem Namen, dann sag ich dir Preis, Zeitpunkt und Quelle."
    return "Alles klar. Ich bin da, wenn du einen Namen hast."


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


def _treffer(niedrig: str, stand: dict) -> tuple:
    treffer = _finde(niedrig, tuple(stand.get("karten") or ()))
    if treffer:
        return treffer
    suche = stand.get("suche")
    if suche is None:
        return ()
    return _finde(niedrig, tuple(suche()))


def _rat(niedrig: str, treffer, stand: dict) -> str:
    if "beste" in niedrig or "besten" in niedrig:
        wichtige = tuple(
            karte
            for karte in tuple(stand.get("karten") or ())
            if isinstance(karte.get("aufwaerts"), (int, float)) and not isinstance(karte.get("aufwaerts"), bool)
        )
        if not wichtige:
            return "Gerade hat kein Name 8 eigene Fälle mit positivem Median. Ich erfinde keinen."
        geordnet = tuple(sorted(wichtige, key=lambda karte: float(karte["aufwaerts"]), reverse=True))
        namen = ", ".join(_rufname(karte) for karte in geordnet[:5])
        return f"Nach oben, aus dem Median der eigenen Fälle, kein Auftrag: {namen}. {_vorschlag(geordnet[0])}"
    if len(treffer) == 1:
        return _vorschlag(treffer[0])
    if not treffer:
        return "Diesen Namen habe ich noch nicht ausgewertet. Ich erfinde keinen Vorschlag."
    return "Dazu passen mehrere Namen. Nenn einen davon, dann sage ich, was die Kurse hergeben."


def _vorschlag(karte: dict) -> str:
    name = _rufname(karte)
    if karte.get("datenstatus") not in ("", "ok", None):
        return f"Zu {name} sind die Kursdaten nicht verlässlich. Einen Vorschlag erfinde ich nicht."
    basis = _eine(karte, "")
    folge = str(karte.get("folge") or "")
    if karte.get("fenster"):
        text = f"Vorschlag aus den eigenen Kursen, kein Auftrag: {karte['fenster']} {basis}"
    elif karte.get("ungewoehnlich"):
        text = (
            f"Für {name} ist der Tag ungewöhnlich. Das ist kein Auftrag und kein kurzes Fenster. "
            f"{karte['ungewoehnlich']} {basis}"
        )
    elif karte.get("pruefung"):
        text = f"{karte['pruefung']} {basis}"
    else:
        tag = karte.get("tag_wert")
        if isinstance(tag, (int, float)) and not isinstance(tag, bool) and abs(tag) >= 3:
            text = (
                f"Heute bewegt sich {name} stark. Ob das für diesen Namen ungewöhnlich ist, ist noch nicht geprüft. {basis}"
            )
        else:
            text = (
                f"Zu {name} sehe ich kein kurzes Fenster und keinen ungewöhnlichen Tag. {basis} "
                "Gut oder schlecht leite ich daraus nicht ab."
            )
    if folge:
        text = f"{text} {folge}"
    markt = str(karte.get("markt") or "")
    if markt:
        text = f"{text} {markt}"
    return text


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
    if karte.get("herkunft"):
        satz += " " + str(karte["herkunft"]) + "."
    satz += " Das ist der geladene Kurs, nicht der Preis in Trade Republic."
    return satz


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
