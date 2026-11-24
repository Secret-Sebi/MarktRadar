# Architektur

Stand: 24. November 2026.

## Schichten

Die Sammlung liegt in `beobachter.py` und `lernen.py`. Die Prüfung liegt in `ki_pruefung.py` und `haendler.pruefe()`. Die Anzeige liest gespeicherte Sätze und erfindet keine Wahrscheinlichkeit.

Eine zentrale Regel hat eine Stelle:

- Euro-Umrechnung: `euro.nach_euro()`
- Zielzeit: `lernen.zielzeit()`
- Horizontprüfung: `ki_pruefung.pruefe_faelle()`
- Trader-Freigabe: `haendler.pruefe()`
- Positionsgrenze: `haendler.platz_frei()`
- Papierstatus: `papier.py`, Datei `daten/papier_zustand.json`

## Was getrennt bleibt

Aktien und Krypto nutzen getrennte Trader-Regeln. Der Vergleichsindex ist für `.DE` der DAX und für US-Kürzel der S&P 500. Ein fremder Index zählt nicht als Benchmark.

Jeder Horizont hat eigene Zeilen in `ki_horizont` und `ki_beispiel`. Ein gutes 1-Tage-Ergebnis gilt nicht für 20 Tage.

## Bekannte Grenzen der Struktur

`haendler.py` ist deutlich größer als eine übersichtliche Datei. Die Regeln, die Prüfung und das Papierkonto liegen dort zusammen. Eine Aufteilung ist sinnvoll, aber kein Ersatz für fehlende Abschlüsse.

Es gibt kein Experimentregister. Wer Parameter am Test verändert, kann das im Code noch nicht als verbrauchten Test kennzeichnen, außer über die gespeicherte Grenze `test_von`.

GitHub Actions liegt lokal in `.github/` und ist nicht auf `main`, weil der Token keine Workflow-Berechtigung hat.
