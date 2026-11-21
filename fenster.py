"""Eigenes dunkles Fenster. Die Zeichenfläche von Tk bleibt auf diesem Mac weiß."""

import json
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from io import StringIO
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from beobachter import (
    DATENBANK,
    FENSTER_PID,
    LISTE,
    UNIVERSUM,
    ZUSTAND,
    beobachte,
    fenster_merken,
    fenster_vergessen,
    haenge_an,
    lade_liste,
    lade_zustand,
    macos_hinweis,
    speichere_zustand,
    warte_sekunden,
)
from seite import fehler_stand, lade_stand, seite_html, stand_bauen

_CACHE = UNIVERSUM
_ERKLARUNG = (
    "Zuerst kommen die Namen aus deiner Liste. Danach DAX, MDAX, S&P 500 und Nasdaq 100.\n"
    "Ein Name erscheint nur in zwei Fällen.\n"
    "1. Dieser Rücksetzer kam bei ihm mindestens 8-mal vor, und drei Handelstage später lag der Kurs im Median höher.\n"
    "2. Der heutige Ausschlag ist für ihn selbst selten. Dafür brauche ich mindestens 8 eigene Tage, "
    "und der Tag muss größer sein als an 9 von 10 Tagen.\n"
    "Ein normaler Tag bleibt im Hintergrund, auch wenn er 3 % groß ist.\n"
    "Ohne frische Kurszeit steht dort: noch nicht neu gemessen. Das heißt nicht unwichtig.\n"
    "Die Kurszeit ist der Stand der Börse. Daneben steht, wann ich ihn gespeichert habe.\n"
    "Ist das Fenster zu und der Mac wach, läuft alle 30 Minuten eine Runde.\n"
    "Nachrichten aus etwa vier Monaten bleiben gespeichert, zusammen mit dem Kurs danach. "
    "Das ist ein zeitlicher Zusammenhang, keine Ursache. Eine einzelne Meldung wird nicht zur Regel.\n"
    "Namen ohne diesen Abruf kommen zuerst, bis zu 80 pro Runde.\n"
    "Geht der Vergleichsindex ähnlich, steht das am Namen. "
    "Eine Schlagzeile ohne den Firmennamen wird trotzdem keiner Aktie angehängt.\n"
    "Unter 60 ausgewerteten Handelstagen ändert das Modell keinen Vorschlag.\n"
    "Wird ein Name aus deiner Liste ungewöhnlich, kommt eine Mitteilung auf dem Mac."
)
_VIEWER = Path(__file__).resolve().parent / "fenster_app" / "Beobachter.app" / "Contents" / "MacOS" / "Beobachter"
_QUELLE = Path(__file__).resolve().parent / "fenster_app" / "Beobachter.swift"


def oeffne_fenster(sekunden, symbole) -> int:
    fenster_merken(FENSTER_PID)
    zustand = lade_zustand(ZUSTAND)
    bild = _Bild()
    sofort = threading.Event()
    zu = threading.Event()
    server = mach_server(bild, sofort.set)
    schleife = threading.Thread(
        target=_runde,
        args=(sekunden, symbole, zustand, bild, sofort, zu),
        daemon=True,
    )
    schleife.start()
    try:
        adresse = f"http://127.0.0.1:{server.server_address[1]}/"
        fenster = subprocess.Popen([str(_viewer()), adresse])
        return fenster.wait()
    finally:
        fenster_vergessen(FENSTER_PID)
        zu.set()
        sofort.set()
        server.shutdown()


def mach_server(bild, neu=None):
    _Handler.bild = bild
    _Handler.neu = neu or (lambda: None)
    _Handler.seite = seite_html().encode("utf-8")
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


class _Bild:
    def __init__(self, stand=None):
        self._stand = stand or lade_stand()
        self._sperre = threading.Lock()

    def lesen(self):
        with self._sperre:
            return self._stand

    def setzen(self, stand) -> None:
        with self._sperre:
            self._stand = stand


class _Handler(BaseHTTPRequestHandler):
    bild = _Bild()
    neu = staticmethod(lambda: None)
    seite = b""

    def do_GET(self):
        pfad = self.path.split("?", 1)[0]
        if pfad == "/stand":
            self._senden(json.dumps(self.bild.lesen(), ensure_ascii=False).encode("utf-8"), "application/json")
            return
        if pfad == "/neu":
            self.neu()
            self._senden(b'{"ok": true}', "application/json")
            return
        if pfad == "/suche":
            self._senden(json.dumps(_suche(self.path), ensure_ascii=False).encode("utf-8"), "application/json")
            return
        self._senden(self.seite, "text/html; charset=utf-8")

    def do_POST(self):
        pfad = self.path.split("?", 1)[0]
        if pfad == "/frage":
            self._frage()
            return
        if pfad != "/liste":
            self._senden(b'{"ok": false}', "application/json", 404)
            return
        laenge = int(self.headers.get("Content-Length") or "0")
        roh = self.rfile.read(laenge) if laenge else b"{}"
        try:
            symbol = str(json.loads(roh.decode("utf-8")).get("symbol") or "")
            meldung = haenge_an(LISTE, symbol)
        except (ValueError, json.JSONDecodeError) as fehler:
            self._senden(json.dumps({"ok": False, "meldung": str(fehler)}).encode("utf-8"), "application/json", 400)
            return
        self.neu()
        self._senden(json.dumps({"ok": True, "meldung": meldung}).encode("utf-8"), "application/json")

    def _frage(self) -> None:
        from gespraech import antwort

        laenge = int(self.headers.get("Content-Length") or "0")
        roh = self.rfile.read(min(laenge, 8000)) if laenge else b"{}"
        try:
            text = str(json.loads(roh.decode("utf-8")).get("text") or "")
        except (UnicodeDecodeError, json.JSONDecodeError):
            text = ""
        from auswertung import alle

        stand = dict(self.bild.lesen())
        stand["suche"] = lambda: alle(DATENBANK)
        satz = antwort(text, stand)
        self._senden(json.dumps({"antwort": satz}, ensure_ascii=False).encode("utf-8"), "application/json")

    def log_message(self, fmt, *args):
        return

    def _senden(self, inhalt: bytes, art: str, status: int = 200) -> None:
        self.send_response(status)
        self.send_header("Content-Type", art)
        self.send_header("Content-Length", str(len(inhalt)))
        self.end_headers()
        self.wfile.write(inhalt)


def _runde(sekunden, symbole, zustand, bild, sofort, zu) -> None:
    from datetime import datetime

    from analyse import BERLIN
    from auswertung import (
        chancen_nachtragen,
        merken,
        mess_runde,
        pause_bei_luecke,
        sende_hinweise,
    )
    from universum import lade_universum

    ausgabe = StringIO()
    while not zu.is_set():
        chancen_nachtragen(DATENBANK)
        watchlist = lade_liste(LISTE)
        luecke = 0
        if symbole:
            menge, gesamt, listenhinweis = symbole, len(symbole), ""
        else:
            from lernen import ohne_langen_abruf

            universum, listenhinweis = lade_universum(watchlist, _CACHE)
            menge = mess_runde(DATENBANK, universum, watchlist, int(datetime.now().timestamp()))
            gesamt = len(universum)
            luecke = len(ohne_langen_abruf(DATENBANK, universum))
        if not menge:
            moment = datetime.now(BERLIN)
            _zeigen(
                bild,
                (),
                False,
                _status(0, 0, gesamt, "", f"{listenhinweis} In den letzten 6 Stunden ist diese Liste gemessen."),
                moment,
                warte_sekunden(moment, sekunden),
                gesamt,
            )
            if zu.is_set():
                return
            sofort.wait(warte_sekunden(moment, sekunden))
            sofort.clear()
            continue
        _markiere(bild, True)
        _zeigen(
            bild,
            (),
            True,
            _status(0, len(menge), gesamt, "", listenhinweis),
            datetime.now(BERLIN),
            gesamt=gesamt,
            fertig=0,
            runde=len(menge),
        )

        runde = len(menge)
        gesamt_jetzt = gesamt
        hinweis_jetzt = listenhinweis
        rest = [3]

        def teilweise(zeilen, anzahl_runde=runde, anzahl_gesamt=gesamt_jetzt, hinweis=hinweis_jetzt, namen=watchlist, budget=rest):
            karten = stand_bauen(zeilen, datetime.now(BERLIN), 0, True)["karten"]
            merken(DATENBANK, karten)
            if budget[0] > 0:
                budget[0] -= sende_hinweise(DATENBANK, karten, namen, macos_hinweis, budget[0])
            name = karten[-1]["name"] if karten else ""
            _zeigen(
                bild,
                zeilen,
                True,
                _status(len(zeilen), anzahl_runde, anzahl_gesamt, name, hinweis),
                datetime.now(BERLIN),
                gesamt=anzahl_gesamt,
                fertig=len(zeilen),
                runde=anzahl_runde,
            )

        try:
            moment, zeilen, zustand, naechste = beobachte(
                menge, zustand, ausgabe, sekunden, bei_zeile=teilweise
            )
            speichere_zustand(ZUSTAND, zustand)
            if zeilen:
                karten = stand_bauen(zeilen, moment, naechste)["karten"]
                merken(DATENBANK, karten)
                if rest[0] > 0:
                    sende_hinweise(DATENBANK, karten, watchlist, macos_hinweis, rest[0])
            naechste = pause_bei_luecke(naechste, luecke)
            _zeigen(
                bild,
                zeilen,
                False,
                _status(len(menge), len(menge), gesamt, "", listenhinweis),
                moment,
                naechste,
                gesamt,
                fertig=len(menge),
                runde=len(menge),
            )
        except Exception as fehler:  # noqa: BLE001
            naechste = 60
            bild.setzen(fehler_stand(str(fehler)))
        if zu.is_set():
            return
        sofort.wait(naechste)
        sofort.clear()


def bild_zeilen(
    frisch: int,
    gesamt: int,
    nachrichten_da: int,
    runde_fertig: int,
    runde_von: int,
    abgeschlossen: int,
    offen: int,
) -> tuple[dict, ...]:
    zeilen = []
    if gesamt > 0:
        zeilen.append({"name": "Frische Kurszeit", "wert": int(frisch), "von": int(gesamt)})
        zeilen.append({"name": "Nachrichten, 4 Monate", "wert": int(nachrichten_da), "von": int(gesamt)})
    faelle = int(abgeschlossen) + int(offen)
    if faelle > 0:
        zeilen.append({"name": "Meldung mit späterem Kurs", "wert": int(abgeschlossen), "von": faelle})
    if runde_von > 0:
        zeilen.append({"name": "Diese Runde", "wert": int(runde_fertig), "von": int(runde_von)})
    return tuple(zeilen)


def _zeigen(bild, zeilen, arbeitet: bool, status: str, moment, naechste: int = 0, gesamt: int = 0, fertig: int = 0, runde: int = 0) -> None:
    from analyse import einschaetzung_satz
    from auswertung import mit_kurszeit, sichtbar

    stand = _mit_lernen(stand_bauen(zeilen, moment, naechste, arbeitet))
    karten = sichtbar(DATENBANK)
    frisch = mit_kurszeit(DATENBANK, int(moment.timestamp()))
    wartend = max(int(gesamt) - frisch, 0)
    nachrichten_da, listen_groesse = _archiv_zahlen()
    lernen = stand.get("lernen") or {}
    stand["karten"] = tuple(sorted(karten, key=_reihenfolge))
    stand["status"] = status
    stand["einschaetzung"] = einschaetzung_satz(
        sum(1 for karte in karten if isinstance(karte.get("aufwaerts"), (int, float)) and not isinstance(karte.get("aufwaerts"), bool)),
        frisch,
        int(lernen.get("modell") or 0),
    )
    stand["bild"] = bild_zeilen(
        frisch,
        int(gesamt) or listen_groesse,
        nachrichten_da,
        fertig,
        runde,
        int(lernen.get("abgeschlossen") or 0),
        int(lernen.get("offen") or 0),
    )
    stand["erklaerung"] = _ERKLARUNG
    if karten:
        wort = "Name ist" if len(karten) == 1 else "Namen sind"
        stand["briefing"] = f"{len(karten)} {wort} gerade ungewöhnlich."
        stand["leer"] = ""
    elif wartend:
        stand["briefing"] = "Noch nichts Ungewöhnliches."
        stand["leer"] = f"Noch nicht neu gemessen: {wartend} von {gesamt}. Das heißt nicht, dass sie unwichtig sind."
    else:
        stand["briefing"] = "Noch nichts Ungewöhnliches."
        stand["leer"] = "Alle gemessenen Namen haben eine frische Kurszeit. Keiner davon ist für sich selbst ungewöhnlich."
    bild.setzen(stand)


def _reihenfolge(karte) -> tuple:
    wert = karte.get("aufwaerts")
    name = str(karte.get("name") or "").lower()
    if isinstance(wert, bool) or not isinstance(wert, (int, float)):
        return (1, 0.0, name)
    return (0, -float(wert), name)


def _status(fertig: int, runde: int, gesamt: int, name: str, hinweis: str) -> str:
    from datetime import datetime

    from analyse import BERLIN
    from auswertung import mit_kurszeit

    frisch = mit_kurszeit(DATENBANK, int(datetime.now(BERLIN).timestamp()))
    wartend = max(gesamt - frisch, 0)
    zeilen = [hinweis] if hinweis else []
    zeilen.append("Zuerst die Namen aus deiner Liste, danach die übrigen.")
    if name:
        zeilen.append(f"Gerade: {name}.")
    zeilen.append(f"Diese Runde: {fertig} von {runde}.")
    zeilen.append(f"Mit frischer Kurszeit: {frisch} von {gesamt}.")
    zeilen.append(f"Noch nicht neu gemessen: {wartend}.")
    zeilen.append(_archiv_satz())
    from lernen import fortschritt

    kurz = fortschritt(DATENBANK).get("kurz") or ""
    if kurz:
        zeilen.append(kurz)
    return "\n".join(zeilen)


def _archiv_zahlen() -> tuple[int, int]:
    from lernen import ohne_langen_abruf
    from universum import lade_universum

    universum, _hinweis = lade_universum(lade_liste(LISTE), _CACHE)
    if not universum:
        return 0, 0
    fehlend = len(ohne_langen_abruf(DATENBANK, universum))
    return len(universum) - fehlend, len(universum)


def _archiv_satz() -> str:
    da, gesamt = _archiv_zahlen()
    if not gesamt:
        return "Die Namensliste ist noch nicht geladen."
    if da < gesamt:
        return f"Vier Monate Nachrichten fehlen noch bei {gesamt - da} von {gesamt}."
    return "Die vier Monate Nachrichten sind für diese Liste gespeichert."


def _namen(stand: dict) -> dict[str, str]:
    return {
        karte["symbol"]: karte["name"]
        for karte in stand.get("karten", ())
        if karte.get("symbol") and karte.get("name")
    }


def _mit_lernen(stand: dict) -> dict:
    from beobachter import DATENBANK
    from lernen import einfluss, fortschritt

    return {
        **stand,
        "lernen": fortschritt(DATENBANK),
        "nachrichten": {
            "tag": einfluss(DATENBANK, 1, namen=_namen(stand)),
            "woche": einfluss(DATENBANK, 7, namen=_namen(stand)),
            "monate": einfluss(DATENBANK, 120, namen=_namen(stand), grenze=8),
        },
    }


def _suche(pfad: str) -> dict:
    from suche import suche

    text = parse_qs(urlparse(pfad).query).get("q", [""])[0]
    try:
        treffer = suche(text)
    except Exception as fehler:  # noqa: BLE001
        return {"treffer": [], "meldung": str(fehler)[:180]}
    return {
        "treffer": [
            {"symbol": eintrag.symbol, "name": eintrag.name, "typ": eintrag.typ, "boerse": eintrag.boerse, "quelle": eintrag.quelle}
            for eintrag in treffer
        ],
        "meldung": "" if treffer else "Nichts gefunden oder die Quelle antwortet nicht.",
    }


def _markiere(bild, arbeitet: bool) -> None:
    stand = dict(bild.lesen())
    stand["arbeitet"] = arbeitet
    bild.setzen(stand)


def _viewer() -> Path:
    quelle_neuer = _QUELLE.exists() and (not _VIEWER.exists() or _QUELLE.stat().st_mtime > _VIEWER.stat().st_mtime)
    if not quelle_neuer and _VIEWER.exists():
        return _VIEWER
    subprocess.run(
        ["swiftc", "-O", "-o", str(_VIEWER), str(_QUELLE), "-framework", "Cocoa", "-framework", "WebKit"],
        check=True,
    )
    return _VIEWER
