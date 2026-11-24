# Entwicklungsstatus

Stand: 24. November 2026, nach der Korrektur in `trainiere()`.

Diese Datei ist der Einstieg nach einer Unterbrechung. Sie beschreibt den Code, nicht eine gewünschte Zukunft.

## 1. Aktueller Stand

MarktRadar misst Kurse, Nachrichten und spätere Kursreaktionen lokal. Horizonte und Trader-Regeln werden nur freigegeben, wenn ihre eigene Prüfung besteht. Kein Horizont ist freigegeben. Kein Trader hat 36 eigene Abschlüsse. `aktion_aus_ki()` gibt die ursprüngliche Aktion zurück und verändert sie nicht.

## 2. Abgeschlossene Phasen

Keine Phase aus dem Master-Auftrag ist abgeschlossen.

Erledigt in dieser Sitzung ist nur ein Ausschnitt von Phase 1 und ein Fehler aus Phase 2:

- Die Bestandsaufnahme liegt in `docs/MASTER_AUDIT.md`.
- Vorhandene Trainingszeilen mit leerem Zielzeitraum werden nachgetragen, wenn die ursprünglichen Kursbalken den Zeitraum rekonstruieren. Vollständige Zeilen bleiben unverändert. Fehlende Balken erzeugen keinen erfundenen Zeitraum.

## 3. Offene Phasen

| Phase | Stand |
| --- | --- |
| 1 Audit | Dokumentiert, nicht jede Zeile jedes Moduls gelesen |
| 2 Datenqualität | Zielzeit-Nachtrag korrigiert. Splits, Dividenden, Makro und Sektor fehlen |
| 3 Lernarchitektur | Zeitliche Trennung, Purging und Walk-forward sind im Code. Kein Experimentregister |
| 4 Prognosemodelle | Ein logistisches Modell je Horizont. Keine freigegebene Qualität |
| 5 KI-Trader | Getrennte Regeln und Zähler. Kein selbständiges Strategieerfinden |
| 6 Meta-KI | Phase wird gespeichert. Gewichte bleiben leer |
| 7 Selbstüberwachung | Einzelstatus für Kurs, Nachrichten und späteren Kurs. Kein Drift-Monitor |
| 8 Gesamtsystem | 228 Unit-Tests bestanden. Kein Nachweis am echten Markt |

## 4. Kritische Fehler

Behoben und mit Regressionstest gesichert: `trainiere()` hat vorhandene Beispiele übersprungen, bevor `_ziel_nachtragen()` lief. Dadurch blieben alte Zeilen ohne `ziel_von` und `ziel_bis`.

Offen und blockierend für eine Freigabe:

- Gespeicherte Horizonte haben die Prüfung nicht bestanden oder keine zeitlich getrennten Testfälle.
- Alte Prüfungs-JSON-Zeilen wurden nicht neu gerechnet. Ihre Brier-Zahlen stammen aus dem früheren Lauf.
- Viele ältere `ki_beispiel`-Zeilen haben noch keine Zielzeiten. Sie bleiben aus der Prüfung, bis eine spätere Messung des jeweiligen Symbols die Balken liefert.
- Nachrichten sind Schlüsselwörter, keine belegte Ursache.
- Makro, Kapitalströme und Branche sind bewusst leer.

## 5. Erfolgreiche Tests

Befehl: `/usr/bin/python3 -m unittest discover -q`

Ergebnis am 24. November 2026: 228 Tests, 19,259 Sekunden, alle bestanden, keiner fehlgeschlagen, keiner übersprungen.

Der neue Test `test_fehlende_zielzeit_wird_nachgetragen_ohne_zweites_training` ist vor der Korrektur fehlgeschlagen und danach bestanden.

## 6. Fehlgeschlagene Tests

Keine im letzten Gesamtlauf.

## 7. Nicht getestete Komponenten

- Die echte Datenbank `daten/markt.sqlite` wurde nicht neu trainiert und nicht neu validiert.
- Kein Live-Abruf von Yahoo, Stooq oder CoinGecko in den Unit-Tests.
- Kein GitHub-Actions-Lauf. Der vorhandene Token darf keine Workflow-Datei veröffentlichen. `.github/` bleibt lokal.
- Paper-Konten, Watchlist und Energieeinstellungen wurden nicht angefasst.

## 8. Nächste konkrete Aufgaben

1. Das laufende Fenster die Zielzeiten beim nächsten natürlichen Durchlauf eines Symbols nachtragen lassen. Keinen Massenlauf über die ganze Datenbank starten.
2. Die Schwellen 108 Beispiele, 36 je Abschnitt und Kalibrierung 0,15 nicht senken.
3. `aktion_aus_ki()` inaktiv lassen, bis ein Horizont `validiert = 1` hat und Einsatzgewichte existieren.
4. Herkunftszeiten nur speichern, wenn die Quelle sie liefert. Keine historischen Fenster schätzen.
5. Erst danach weitere Merkmale prüfen. Ein neues Merkmal ist kein Fortschritt, solange es die Baseline nicht im unabhängigen Test schlägt.

## 9. Letzter bearbeiteter Stand

Zuletzt geändert: `ki.py` Funktion `trainiere()`, Test in `test_ki.py`, diese Dokumente.

Vorheriger veröffentlichter Commit: `602c2bd`.
