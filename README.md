# MarktRadar

Lokales Kursprogramm für diesen Mac. Es öffnet kein Konto und keinen Server.

## Start

```bash
python3 beobachter.py
```

Oder die Datei `MarktRadar.command` doppelklicken.

Weitere Aufrufe:

```bash
python3 beobachter.py --terminal
python3 beobachter.py --einmal
```

## Dateien

- `beobachter.py` startet das Programm
- `analyse.py` bewertet die Kurse
- `kurse.py` holt die Kurse
- `technik.py` rechnet die Kennzahlen
- `database.py` speichert sie in `daten/markt.sqlite`
- `ansicht.py`, `fenster.py`, `seite.py` und `fenster_app/` sind die Anzeige
- `watchlist.txt` enthält die beobachteten Kürzel
- `zustand.json` speichert den letzten Stand
- `test_*.py` sind die Tests
