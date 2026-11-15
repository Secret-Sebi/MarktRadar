"""Eigenes dunkles Fenster. Die Zeichenfläche von Tk bleibt auf diesem Mac weiß."""

import json
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from io import StringIO
from pathlib import Path

from beobachter import LISTE, ZUSTAND, beobachte, lade_liste, lade_zustand
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
        self._senden(self.seite, "text/html; charset=utf-8")

    def log_message(self, fmt, *args):
        return

    def _senden(self, inhalt: bytes, art: str) -> None:
        self.send_response(200)
        self.send_header("Content-Type", art)
        self.send_header("Content-Length", str(len(inhalt)))
        self.end_headers()
        self.wfile.write(inhalt)


def _runde(sekunden, symbole, zustand, bild, sofort, zu) -> None:
    ausgabe = StringIO()
    while not zu.is_set():
        _markiere(bild, True)
        try:
            moment, zeilen, zustand, naechste = beobachte(
                symbole or lade_liste(LISTE), zustand, ausgabe, sekunden
            )
            bild.setzen(stand_bauen(zeilen, moment, naechste))
        except Exception as fehler:
            naechste = 60
            bild.setzen(fehler_stand(str(fehler)))
        if zu.is_set():
            return
        sofort.wait(naechste)
        sofort.clear()


def _markiere(bild, arbeitet: bool) -> None:
    stand = dict(bild.lesen())
    stand["arbeitet"] = arbeitet
    bild.setzen(stand)


def _viewer() -> Path:
    if _VIEWER.exists():
        return _VIEWER
    subprocess.run(
        ["swiftc", "-O", "-o", str(_VIEWER), str(_QUELLE), "-framework", "Cocoa", "-framework", "WebKit"],
        check=True,
    )
    return _VIEWER
