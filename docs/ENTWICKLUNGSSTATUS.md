# Entwicklungsstatus

Stand: 24. November 2026, nach dem Modellvergleich in `prognose_vergleich.py`.

Diese Datei ist der Einstieg nach einer Unterbrechung. Sie beschreibt den Code, nicht eine gewünschte Zukunft.

## 1. Aktueller Stand

MarktRadar misst Kurse, Nachrichten und spätere Kursreaktionen lokal. Horizonte und Trader-Regeln werden nur freigegeben, wenn ihre eigene Prüfung besteht. Kein Horizont ist freigegeben. Kein Trader hat 36 eigene Abschlüsse. `aktion_aus_ki()` gibt die ursprüngliche Aktion zurück und verändert sie nicht.

## 2. Abgeschlossene Phasen

Keine Phase aus dem Master-Auftrag ist abgeschlossen.

Erledigt und getestet:

- Vorhandene Trainingszeilen mit leerem Zielzeitraum werden nachgetragen, wenn die Kursbalken den Zeitraum rekonstruieren.
- Drei Regeln werden auf derselben Trennung verglichen: konstant, Momentum über dem 20-Tage-Schnitt, Logistik. Der Vergleich gibt nur die Logistik frei, und nur wenn die bestehende Prüfung besteht. Random Forest, Gradient Boosting und neuronale Netze sind nicht implementiert.

## 3. Offene Phasen

| Phase | Stand |
| --- | --- |
| 0 Bestand und vier Verantwortungen | In `docs/SYSTEMARCHITEKTUR.md`. Kein Umbau in vier Programme |
| 1 Forecasting | Vergleich von konstant, Momentum und Logistik. Keine Freigabe ohne die alte Prüfung |
| 2 Datenqualität | Zielzeit-Nachtrag korrigiert. Splits, Dividenden, Makro und Sektor fehlen |
| 3 Lernarchitektur | Zeitliche Trennung, Purging und Walk-forward sind im Code. Kein Experimentregister |
| 4 Weitere Modelltypen | Random Forest, Boosting und Netze fehlen. Bibliotheken sind nicht installiert |
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

Ergebnis am 24. November 2026 nach dem Modellvergleich: 232 Tests, 19,171 Sekunden, alle bestanden, keiner fehlgeschlagen, keiner übersprungen.

Der neue Test `test_fehlende_zielzeit_wird_nachgetragen_ohne_zweites_training` ist vor der Korrektur fehlgeschlagen und danach bestanden.

## 6. Fehlgeschlagene Tests

Keine im letzten Gesamtlauf.

## 7. Nicht getestete Komponenten

- Die echte Datenbank `daten/markt.sqlite` wurde nicht neu trainiert und nicht neu validiert.
- Kein Live-Abruf von Yahoo, Stooq oder CoinGecko in den Unit-Tests.
- Kein GitHub-Actions-Lauf. Der vorhandene Token darf keine Workflow-Datei veröffentlichen. `.github/` bleibt lokal.
- Paper-Konten, Watchlist und Energieeinstellungen wurden nicht angefasst.

## 8. Nächste konkrete Aufgaben

Hier weitermachen, nicht bei einem neuen System:

1. Das laufende Fenster die Zielzeiten beim nächsten natürlichen Durchlauf nachtragen lassen. Keinen Massenlauf starten und die gespeicherten Prüfungen nicht neu rechnen.
2. Die Schwellen 108, 36 und 0,15 nicht senken.
3. `aktion_aus_ki()` inaktiv lassen, bis ein Horizont freigegeben ist.
4. Keine Meta-Gewichte schreiben, solange kein Trader und kein Horizont die eigene Prüfung besteht.
5. Random Forest oder Boosting nur einbauen, wenn die Bibliothek vorhanden ist und derselbe zeitliche Test sie gegen die Konstante misst, ohne sie freizugeben.

## 9. Letzter bearbeiteter Stand

Zuletzt geändert: `ki.py` und `test_ki.py`. Unterschiedliche Meldungen bleiben erhalten, überlappende Ziele nicht. Eine gemessene Prüfung wird nicht gelöscht. Kein Modell ist freigegeben.

Vorheriger veröffentlichter Commit: `a5134ba`.
