#!/usr/bin/env python3
"""Lokales Kursprogramm für diesen Mac.

Start (öffnet das Fenster):
    python3 beobachter.py

Nur Text im Terminal:
    python3 beobachter.py --terminal

Einmal anzeigen und beenden:
    python3 beobachter.py --einmal

Eine Runde ohne Fenster, wenn der Mac wach ist und das Fenster nicht läuft:
    python3 beobachter.py --nachholen

Das Fenster spricht nur 127.0.0.1 auf diesem Mac an. Es gibt kein Konto und keinen Broker.
"""

from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
import time
from collections.abc import Sequence
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import TextIO

from analyse import (
    BERLIN,
    Kennzahlen,
    Urteil,
    abstand_prozent,
    aktion_bei_datenstatus,
    angezeigtes_fenster,
    de_prozent,
    de_zahl,
    fehler_urteil,
    fenster,
    handels_hinweis,
    kennzahlen_aus_schluessen,
    markt_satz,
    soll_melden,
    ungewoehnlicher_tag,
    unvollstaendig_urteil,
    urteilen,
)
from database import signal_speichern
from ki import aktion_aus_ki, ki_satz, messe, schaetzung, trainiere
from kurse import gueltiges_symbol, hole_kurs
from lernen import aktion_aus_lernen, aktion_aus_verkauf, aktualisiere, folge_satz, satz
from technik import berechne, vergleichsindex

ORDNER = Path(__file__).resolve().parent
LISTE = ORDNER / "watchlist.txt"
ZUSTAND = ORDNER / "zustand.json"
DATENBANK = ORDNER / "daten" / "markt.sqlite"
UNIVERSUM = ORDNER / "daten" / "universum.txt"
FENSTER_PID = ORDNER / "daten" / "fenster.pid"
_INDEX_NAME = {
    "^GDAXI": "DAX",
    "^GSPC": "S&P 500",
    "^FCHI": "CAC 40",
    "^AEX": "AEX",
    "^FTSE": "FTSE 100",
    "^SSMI": "SMI",
    "^GSPTSE": "TSX",
    "^HSI": "Hang Seng",
    "^N225": "Nikkei",
    "BTC-USD": "Bitcoin",
}

_STANDARD_LISTE = """\
# Ein Yahoo-Kürzel pro Zeile. Zeilen mit # ignoriert das Programm.
# Krypto
BTC-USD
ETH-USD
SOL-USD
# USA
NVDA
AAPL
MSFT
AMZN
GOOGL
META
TSLA
AMD
AVGO
NFLX
# Deutschland
SAP.DE
SIE.DE
ALV.DE
BMW.DE
IFX.DE
RHM.DE
MBG.DE
DTE.DE
AIR.DE
ADS.DE
VOW3.DE
DBK.DE
BAYN.DE
BAS.DE
# ETFs
VWCE.DE
SXR8.DE
EUNL.DE
EXS1.DE
QDVE.DE
"""

_TAGE = ("Mo", "Di", "Mi", "Do", "Fr", "Sa", "So")


@dataclass(frozen=True)
class Zeile:
    symbol: str
    name: str
    waehrung: str
    preis: float | None
    tag_pct: float | None
    urteil: Urteil
    kennzahlen: Kennzahlen | None
    technik: object | None = None
    reihe: tuple[float, ...] = ()
    quelle: str = ""
    datenstatus: str = ""
    kursart: str = ""
    lernen: str = ""
    hinweis: str = ""
    faelle: int = 0
    kurszeit: int | None = None
    abweichung: float | None = None
    handelsplatz: str = ""
    fundamental: str = "fehlt"
    fenster: str = ""
    pruefung: str = ""
    folge: str = ""
    ungewoehnlich: str = ""
    markt: str = ""


def main(argv: Sequence[str], ausgabe: TextIO = sys.stdout) -> int:
    einmal, sekunden, symbole, terminal, still = lese_argumente(argv)
    try:
        if still:
            return nachholen(ausgabe)
        if not einmal and not terminal:
            from fenster import oeffne_fenster

            return oeffne_fenster(sekunden, symbole)
        return lauf(einmal, sekunden, symbole, ausgabe)
    except KeyboardInterrupt:
        ausgabe.write("\nMarktRadar beendet. Es wurde nichts gekauft.\n")
        return 0


def nachholen(
    ausgabe: TextIO,
    pid_pfad: Path = FENSTER_PID,
    liste: Path = LISTE,
    cache: Path = UNIVERSUM,
    datenbank: Path = DATENBANK,
    uhr=datetime.now,
) -> int:
    if fenster_laeuft(pid_pfad):
        ausgabe.write("Das Fenster misst schon.\n")
        return 0
    from auswertung import merken, mess_runde, sende_hinweise
    from seite import stand_bauen
    from universum import lade_universum

    moment = uhr(BERLIN)
    watchlist = lade_liste(liste)
    universum, hinweis = lade_universum(watchlist, cache, jetzt=int(moment.timestamp()))
    menge = mess_runde(datenbank, universum, watchlist, int(moment.timestamp()))
    if not menge:
        ausgabe.write(f"{hinweis} In den letzten 6 Stunden ist diese Liste gemessen.\n")
        return 0
    ausgabe.write(f"{hinweis} Hole {len(menge)} von {len(universum)}.\n")
    ausgabe.flush()
    gemessen, zeilen, _, _ = beobachte(menge, lade_zustand(ZUSTAND), ausgabe, uhr=uhr)
    if zeilen:
        karten = stand_bauen(zeilen, gemessen, 0)["karten"]
        merken(datenbank, karten)
        sende_hinweise(datenbank, karten, watchlist, macos_hinweis)
    return 0


def fenster_merken(pfad: Path = FENSTER_PID) -> None:
    pfad.parent.mkdir(parents=True, exist_ok=True)
    pfad.write_text(str(os.getpid()), encoding="utf-8")


def fenster_vergessen(pfad: Path = FENSTER_PID) -> None:
    try:
        if pfad.exists() and pfad.read_text(encoding="utf-8").strip() == str(os.getpid()):
            pfad.unlink()
    except OSError:
        return


def fenster_laeuft(pfad: Path = FENSTER_PID) -> bool:
    if not pfad.exists():
        return False
    try:
        pid = int(pfad.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return False
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


def lauf(
    einmal: bool,
    sekunden: int | None,
    symbole_arg: tuple[str, ...],
    ausgabe: TextIO,
    uhr=datetime.now,
    schlaf=time.sleep,
    hinweis=None,
) -> int:
    zustand = lade_zustand(ZUSTAND)
    erste_runde = True
    while True:
        symbole = symbole_arg or lade_liste(LISTE)
        if erste_runde:
            ausgabe.write("Lade Kurse …\n")
            ausgabe.flush()
        moment, zeilen, zustand, naechste = beobachte(symbole, zustand, ausgabe, sekunden, uhr, hinweis)
        text = bildschirm(zeilen, moment, naechste, ausgabe.isatty() and not einmal, not einmal)
        if ausgabe.isatty() and not einmal:
            ausgabe.write("\033[2J\033[H")
        ausgabe.write(text)
        ausgabe.flush()
        if einmal:
            return 0
        erste_runde = False
        schlaf(naechste)


def beobachte(symbole, zustand, ausgabe, sekunden=None, uhr=datetime.now, hinweis=None, bei_zeile=None):
    moment = uhr(BERLIN)
    zeilen = sammle(symbole, bei_zeile=bei_zeile)
    naechste = warte_sekunden(moment, sekunden)
    zustand, meldungen = zustand_nach_runde(zustand, zeilen, moment.isoformat(timespec="minutes"))
    speichere_zustand(ZUSTAND, zustand)
    _signale_sichern(zeilen, moment, ausgabe)
    _melde(meldungen, hinweis if hinweis is not None else macos_hinweis)
    return moment, zeilen, zustand, naechste


def lese_argumente(argv: Sequence[str]) -> tuple[bool, int | None, tuple[str, ...], bool, bool]:
    einmal = False
    terminal = False
    still = False
    sekunden = None
    symbole = []
    args = list(argv[1:])
    index = 0
    while index < len(args):
        arg = args[index]
        if arg == "--einmal":
            einmal = True
        elif arg == "--terminal":
            terminal = True
        elif arg == "--nachholen":
            still = True
        elif arg == "--sekunden":
            index += 1
            if index >= len(args):
                raise SystemExit("Nach --sekunden fehlt die Zahl.")
            try:
                sekunden = int(args[index])
            except ValueError:
                raise SystemExit("--sekunden braucht eine ganze Zahl.") from None
        elif arg.startswith("-"):
            raise SystemExit("Bekannt sind --einmal, --terminal, --nachholen und --sekunden N.")
        else:
            symbole.append(arg.strip().upper())
        index += 1
    return einmal, sekunden, tuple(symbole), terminal, still


def warte_sekunden(moment: datetime, vorgabe: int | None) -> int:
    if vorgabe is not None:
        return max(60, vorgabe)
    if fenster(moment) in ("xetra", "bestpreis"):
        return 180
    return 900


def lade_liste(pfad: Path) -> tuple[str, ...]:
    if not pfad.exists():
        pfad.write_text(_STANDARD_LISTE, encoding="utf-8")
    roh = []
    for zeile in pfad.read_text(encoding="utf-8").splitlines():
        text = zeile.split("#", 1)[0].strip().upper()
        if text:
            roh.append(text)
    return tuple(dict.fromkeys(roh))


def haenge_an(pfad: Path, symbol: str) -> str:
    symbol = symbol.strip().upper()
    if not gueltiges_symbol(symbol):
        raise ValueError("Ungültiges Kürzel")
    if not pfad.exists():
        pfad.write_text(symbol + "\n", encoding="utf-8")
        return "hinzugefuegt"
    text = pfad.read_text(encoding="utf-8")
    if symbol in lade_liste(pfad):
        return "vorhanden"
    prefix = "" if text.endswith("\n") or not text else "\n"
    pfad.write_text(text + prefix + symbol + "\n", encoding="utf-8")
    return "hinzugefuegt"


def lade_zustand(pfad: Path) -> dict:
    if not pfad.exists():
        return {"symbole": {}}
    try:
        daten = json.loads(pfad.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"symbole": {}}
    symbole = daten.get("symbole") if isinstance(daten, dict) else None
    if not isinstance(symbole, dict):
        return {"symbole": {}}
    return {"symbole": dict(symbole)}


def speichere_zustand(pfad: Path, zustand: dict) -> None:
    tmp = pfad.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(zustand, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(pfad)


def zustand_nach_runde(alt: dict, zeilen: Sequence[Zeile], zeit: str):
    bisher = alt.get("symbole") if isinstance(alt.get("symbole"), dict) else {}
    neu = {}
    meldungen = []
    for zeile in zeilen:
        eintrag = bisher.get(zeile.symbol)
        vorher = eintrag.get("aktion") if isinstance(eintrag, dict) else None
        gleiche_aktion = isinstance(eintrag, dict) and eintrag.get("aktion") == zeile.urteil.aktion
        seit = str(eintrag.get("seit") or zeit) if gleiche_aktion else zeit
        neu[zeile.symbol] = {"aktion": zeile.urteil.aktion, "seit": seit}
        if soll_melden(vorher if isinstance(vorher, str) else None, zeile.urteil.aktion):
            meldungen.append(zeile)
    return {"symbole": neu}, tuple(meldungen)


def sammle(symbole: Sequence[str], bei_zeile=None) -> tuple[Zeile, ...]:
    fx: dict = {}
    if not symbole:
        return ()
    indizes = tuple(dict.fromkeys(index for index in (vergleichsindex(symbol) for symbol in symbole) if index))
    zeilen: tuple[Zeile, ...] = ()
    fertige_indizes: dict = {}
    with ThreadPoolExecutor(max_workers=4) as pool:
        laeuft = {pool.submit(_kurs_oder_fehler, symbol, fx): ("index", symbol) for symbol in indizes}
        laeuft.update({pool.submit(_kurs_oder_fehler, symbol, fx): ("wert", symbol) for symbol in symbole})
        for fertig in as_completed(laeuft):
            art, symbol = laeuft[fertig]
            ergebnis = fertig.result()
            if art == "index":
                fertige_indizes[symbol] = None if isinstance(ergebnis, Exception) else ergebnis
                continue
            zeilen = zeilen + (bewerte(symbol, fertige_indizes.get(vergleichsindex(symbol)), fx, ergebnis),)
            if bei_zeile is not None:
                bei_zeile(zeilen)
    return zeilen


def _kurs_oder_fehler(symbol: str, fx: dict):
    try:
        return hole_kurs(symbol, fx=fx)
    except (ConnectionError, LookupError, ValueError, json.JSONDecodeError) as fehler:
        return fehler


def bewerte(symbol: str, markt=None, fx: dict | None = None, daten=None) -> Zeile:
    if isinstance(daten, Exception):
        return _fehler(symbol, str(daten))
    try:
        if daten is None:
            daten = hole_kurs(symbol, fx=fx)
    except (ConnectionError, LookupError, ValueError, json.JSONDecodeError) as fehler:
        return _fehler(symbol, str(fehler))
    zahlen = kennzahlen_aus_schluessen(daten.schluesse, daten.ist_etf, daten.hoch_52w)
    technik = berechne(
        daten.balken,
        daten.preis,
        None if markt is None else markt.balken,
        daten.hat_bereinigt,
        _INDEX_NAME.get(vergleichsindex(symbol), "kein passender Index"),
        daten.hoch_52w,
        daten.tief_52w,
    )
    urteil = urteilen(zahlen) if technik.vollstaendig else unvollstaendig_urteil(technik.fehlend)
    if aktion_bei_datenstatus(urteil.aktion, daten.datenstatus or "ok") != urteil.aktion:
        urteil = unvollstaendig_urteil((daten.hinweis or "Die Kursdaten sind nicht verlässlich genug.",))
    lern_satz = ""
    thema = "unklar"
    befund = None
    try:
        index_balken = None if markt is None else getattr(markt, "balken", None)
        befund = aktualisiere(
            DATENBANK, daten.symbol or symbol, daten.name or symbol, daten.balken, index_balken=index_balken
        )
        lern_satz = satz(befund)
        thema = befund.kategorie
        if aktion_aus_lernen(urteil.aktion, befund.anzahl, befund.median) != urteil.aktion:
            urteil = Urteil(
                "abwarten",
                urteil.score,
                "Nicht hinterherlaufen",
                (
                    f"Nicht prüfen: bei {befund.anzahl} Fällen lag der Median nach 5 Handelstagen "
                    f"bei {de_zahl(befund.median, 1)} %. {urteil.grund}"
                ),
                "Die bisherigen Fälle sprechen gegen einen Einstieg. Die Beobachtung läuft weiter.",
            )
    except (OSError, sqlite3.Error):
        lern_satz = "Die bisherigen Nachrichten konnten nicht gespeichert werden."
    try:
        modell = trainiere(DATENBANK, daten.symbol or symbol, daten.balken)
        chance = schaetzung(modell, daten.balken, thema)
        pruefung = messe(DATENBANK, daten.symbol or symbol, daten.balken)
        lern_satz = f"{lern_satz} {ki_satz(modell, chance, pruefung)}".strip()
        neue_aktion = aktion_aus_ki(
            urteil.aktion, modell, chance, (daten.datenstatus or "ok") == "ok", pruefung
        )
        if neue_aktion == "abwarten" and neue_aktion != urteil.aktion and chance is not None:
            urteil = Urteil(
                "abwarten",
                urteil.score,
                "Nicht hinterherlaufen",
                (
                    f"Nicht prüfen: die aktuelle Modellzahl ist {de_zahl(chance * 100, 0)}. "
                    "Das ist keine kalibrierte Wahrscheinlichkeit. "
                    f"{urteil.grund}"
                ),
                "Das Modell spricht gegen einen Einstieg. Die Beobachtung läuft weiter.",
            )
    except (OSError, sqlite3.Error):
        pass
    if befund is not None and aktion_aus_verkauf(
        urteil.aktion, befund.eigene, befund.eigene_median, (daten.datenstatus or "ok") == "ok"
    ) == "verkauf_pruefen":
        urteil = Urteil(
            "verkauf_pruefen",
            urteil.score,
            "Verkauf prüfen",
            (
                f"Verkauf prüfen, weil {befund.eigene} eigene Fälle im Median "
                f"{de_zahl(befund.eigene_median, 1)} % nach 5 Handelstagen liegen. Das ist kein Auftrag. {urteil.grund}"
            ),
            "Kein Auftrag. In Trade Republic selbst prüfen, ob du verkaufen willst.",
        )
    try:
        from urllib.request import urlopen

        from fundamental import hole as hole_fundamental

        fundamental = hole_fundamental(daten.symbol or symbol, urlopen)
    except (OSError, ValueError):
        fundamental = "fehlt"
    fenster_text, pruefung = ("", "")
    tag_text = ""
    markt_text = ""
    if (daten.datenstatus or "ok") == "ok":
        fenster_text, fenster_grund = angezeigtes_fenster(zahlen, daten.schluesse)
        tag_text, tag_grund = ungewoehnlicher_tag(daten.tag_pct, daten.schluesse)
        pruefung = " ".join(teil for teil in ("" if fenster_text else fenster_grund, "" if tag_text else tag_grund) if teil)
        index_symbol = vergleichsindex(daten.symbol or symbol)
        index_pct = None if markt is None else getattr(markt, "tag_pct", None)
        markt_text = markt_satz(daten.tag_pct, index_pct, _INDEX_NAME.get(index_symbol, ""))
    try:
        folge = folge_satz(DATENBANK, daten.symbol or symbol)
    except (OSError, sqlite3.Error):
        folge = "Zu diesem Namen ist noch kein Folgetag ausgewertet."
    return Zeile(
        symbol=daten.symbol or symbol,
        name=daten.name or symbol,
        waehrung=daten.waehrung,
        preis=daten.preis,
        tag_pct=daten.tag_pct,
        urteil=urteil,
        kennzahlen=zahlen,
        technik=technik,
        reihe=_kursreihe(tuple(balken.schluss for balken in daten.balken)),
        quelle=daten.quelle,
        datenstatus=daten.datenstatus,
        kursart=daten.kursart,
        lernen=lern_satz,
        hinweis=daten.hinweis,
        faelle=0 if befund is None else befund.eigene,
        kurszeit=daten.kurszeit,
        abweichung=daten.abweichung,
        handelsplatz=daten.handelsplatz,
        fundamental=fundamental,
        fenster=fenster_text,
        pruefung=pruefung,
        folge=folge,
        ungewoehnlich=tag_text,
        markt=markt_text,
    )


def bildschirm(zeilen: Sequence[Zeile], moment: datetime, naechste: int, _farbig: bool, weiter: bool = True) -> str:
    berlin = moment.astimezone(BERLIN)
    kopf = (
        f"MARKTRADAR  {_TAGE[berlin.weekday()]} {berlin:%d.%m.%Y %H:%M} Uhr Berlin\n"
        "Nur dieses MacBook. Keine App, kein Konto, es wird nichts gekauft.\n"
        "Keine Anlageberatung. Der angezeigte Kurs kann vom Preis in Trade Republic abweichen.\n"
        "Der große Preis ist der letzte Marktkurs. Die Rechnung gleicht Aktiensplits aus.\n"
        f"{handels_hinweis(moment)}\n"
        "Feiertage prüft das Programm nicht.\n"
    )
    koerper = "\n\n".join(_karte(zeile) for zeile in _sortiert(zeilen)) or "Die Liste ist leer. Trag Kürzel in watchlist.txt ein."
    if weiter:
        fuss = f"\nNächste Runde in {_warte_text(naechste)}. Beenden mit Ctrl+C.\nListe: {LISTE}\nSignale: {DATENBANK}\n"
    else:
        fuss = f"\nEin Durchgang. Liste: {LISTE}\nSignale: {DATENBANK}\n"
    return kopf + "\n" + koerper.strip() + "\n" + fuss


def macos_hinweis(titel: str, text: str) -> bool:
    script = (
        f"display notification {_applescript(text[:180])} "
        f"with title {_applescript(titel[:80])}"
    )
    ergebnis = subprocess.run(["osascript", "-e", script], check=False, capture_output=True, text=True)
    return ergebnis.returncode == 0


def _karte(zeile: Zeile) -> str:
    zeit = "Zeit fehlt"
    if isinstance(zeile.kurszeit, int) and not isinstance(zeile.kurszeit, bool):
        zeit = datetime.fromtimestamp(zeile.kurszeit, BERLIN).strftime("%d.%m.%Y %H:%M")
    zeilen = [
        f"{zeile.symbol}  {zeile.name}",
        f"           {_preis(zeile)}   {_kurs_prozent(zeile.tag_pct)}   {zeile.quelle or 'Quelle fehlt'} · {zeit}",
    ]
    if zeile.kennzahlen is not None:
        zeilen.append("           " + _details(zeile.kennzahlen))
    zeilen.extend(_technikzeilen(zeile.technik))
    return "\n".join(zeilen)


def _details(zahlen: Kennzahlen) -> str:
    rsi = de_zahl(zahlen.rsi, 1) if zahlen.rsi is not None else "—"
    return " · ".join(
        (
            f"RSI {rsi}",
            "200-Tage " + de_prozent(abstand_prozent(zahlen.preis, zahlen.sma200)),
            "5 Tage " + _kurs_prozent(zahlen.aenderung_5t_pct),
            "20 Tage " + _kurs_prozent(zahlen.aenderung_20t_pct),
        )
    )


def _preis(zeile: Zeile) -> str:
    if zeile.preis is None:
        return "—"
    stellen = 2 if abs(zeile.preis) >= 1 else 4
    betrag = de_zahl(zeile.preis, stellen)
    return f"{betrag} {zeile.waehrung}".rstrip()


def _sortiert(zeilen: Sequence[Zeile]) -> tuple[Zeile, ...]:
    return tuple(sorted(zeilen, key=lambda zeile: (zeile.name or zeile.symbol).lower()))


def _umbruch(text: str, einzug: int) -> str:
    breite = 88 - einzug
    zeilen = []
    rest = text
    while rest:
        if len(rest) <= breite:
            zeilen.append(rest)
            break
        bruch = rest.rfind(" ", 0, breite + 1)
        if bruch <= 0:
            bruch = breite
        zeilen.append(rest[:bruch])
        rest = rest[bruch:].lstrip()
    return "\n".join((" " * einzug) + zeile for zeile in zeilen)


def _kursreihe(werte, maximum: int = 80) -> tuple[float, ...]:
    fenster = tuple(werte)[-180:]
    if len(fenster) <= maximum:
        return tuple(round(float(wert), 4) for wert in fenster)
    letzter = maximum - 1
    return tuple(
        round(float(fenster[round(index * (len(fenster) - 1) / letzter)]), 4)
        for index in range(maximum)
    )


def _fehler(symbol: str, meldung: str) -> Zeile:
    return Zeile(symbol, symbol, "", None, None, fehler_urteil(meldung), None)


def _melde(meldungen: Sequence[Zeile], hinweis) -> None:
    for zeile in meldungen[:3]:
        hinweis(f"{zeile.symbol}: prüfen", zeile.urteil.grund)


def _technikzeilen(technik) -> tuple[str, ...]:
    if technik is None:
        return ()
    muster = ", ".join(technik.muster) if technik.muster else "Kein besonderes Muster"
    kennzahlen = " · ".join(
        (
            f"MACD {_opt_zahl(technik.macd)}",
            f"ATR {_opt_zahl(technik.atr)}",
            f"Trend {_opt_zahl(technik.trendstaerke)}",
            "Schwankung " + _kurs_prozent(technik.volatilitaet),
            "60 Tage " + _kurs_prozent(technik.rendite_60),
        )
    )
    zonen = " · ".join(
        (
            f"Stütze {_opt_zahl(technik.stuetze)}",
            f"Widerstand {_opt_zahl(technik.widerstand)}",
            f"52W {_opt_zahl(technik.hoch_52)} / {_opt_zahl(technik.tief_52)}",
            _relativ_text(technik),
        )
    )
    zeilen = [f"           Muster: {muster}", "           " + kennzahlen, "           " + zonen]
    if technik.hinweise:
        zeilen.append("           Hinweis: " + ", ".join(technik.hinweise))
    return tuple(zeilen)


def _relativ_text(technik) -> str:
    if technik.relativ is None:
        return "Vergleich fehlt"
    name = technik.index_titel or "Index"
    return f"gegen {name} {de_prozent(technik.relativ).replace(' %', '')} Punkte"


def _opt_zahl(wert: float | None) -> str:
    if wert is None:
        return "—"
    return de_zahl(wert, 1 if abs(wert) < 100 else 2)


def _signale_sichern(zeilen: Sequence[Zeile], moment: datetime, ausgabe: TextIO) -> None:
    zeit = moment.isoformat(timespec="minutes")
    try:
        for zeile in zeilen:
            if zeile.urteil.aktion == "fehler" or zeile.preis is None:
                continue
            signal_speichern(
                DATENBANK,
                zeile.symbol,
                zeit,
                zeile.urteil.aktion,
                zeile.preis,
                zeile.urteil.score,
                zeile.urteil.grund,
                _indikatoren(zeile),
            )
    except (OSError, sqlite3.Error) as fehler:
        ausgabe.write(f"Signale nicht gespeichert: {fehler}\n")


def _indikatoren(zeile: Zeile) -> str:
    technik = zeile.technik
    if technik is None:
        return "{}"
    return json.dumps(
        {
            "muster": list(technik.muster),
            "macd": technik.macd,
            "atr": technik.atr,
            "trend": technik.trendstaerke,
            "schwankung": technik.volatilitaet,
            "rendite_60": technik.rendite_60,
            "stuetze": technik.stuetze,
            "widerstand": technik.widerstand,
            "relativ": technik.relativ,
            "hinweise": list(technik.hinweise),
        },
        ensure_ascii=False,
    )


def _warte_text(sekunden: int) -> str:
    if sekunden < 120:
        return f"{sekunden} Sekunden"
    return f"{sekunden // 60} Minuten"


def _kurs_prozent(wert: float | None) -> str:
    if wert is None:
        return "—"
    return de_prozent(wert)


def _applescript(text: str) -> str:
    return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
