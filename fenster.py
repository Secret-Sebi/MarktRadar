"""Eigenes dunkles Fenster. Die Zeichenfläche von Tk bleibt auf diesem Mac weiß."""

import json
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from io import StringIO
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from beobachter import LISTE, ZUSTAND, beobachte, haenge_an, lade_liste, lade_zustand
from seite import fehler_stand, lade_stand, seite_html, stand_bauen

_VIEWER = Path(__file__).resolve().parent / "fenster_app" / "Beobachter.app" / "Contents" / "MacOS" / "Beobachter"
_QUELLE = Path(__file__).resolve().parent / "fenster_app" / "Beobachter.swift"


def oeffne_fenster(sekunden, symbole) -> int:
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
        satz = antwort(text, self.bild.lesen())
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

    ausgabe = StringIO()
    while not zu.is_set():
        symbole_jetzt = symbole or lade_liste(LISTE)
        _markiere(bild, True)
        start = _mit_lernen(dict(bild.lesen()))
        start["status"] = "Der erste Kurs wird geladen."
        bild.setzen(start)

        gesamt = len(symbole_jetzt)

        def teilweise(zeilen, anzahl=gesamt):
            stand = _mit_lernen(stand_bauen(zeilen, datetime.now(BERLIN), 0, True))
            stand["status"] = f"{len(zeilen)} von {anzahl} geladen"
            bild.setzen(stand)

        try:
            moment, zeilen, zustand, naechste = beobachte(
                symbole_jetzt, zustand, ausgabe, sekunden, bei_zeile=teilweise
            )
            bild.setzen(_mit_lernen(stand_bauen(zeilen, moment, naechste)))
        except Exception as fehler:  # noqa: BLE001
            naechste = 60
            bild.setzen(fehler_stand(str(fehler)))
        if zu.is_set():
            return
        sofort.wait(naechste)
        sofort.clear()


def _mit_lernen(stand: dict) -> dict:
    from beobachter import DATENBANK
    from lernen import einfluss, fortschritt

    return {
        **stand,
        "lernen": fortschritt(DATENBANK),
        "nachrichten": {"tag": einfluss(DATENBANK, 1), "woche": einfluss(DATENBANK, 7)},
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
