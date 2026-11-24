# Bekannte Probleme

Stand: 24. November 2026.

## Behoben in dieser Sitzung

`trainiere()` hat vorhandene `ki_beispiel`-Zeilen sofort übersprungen. Der Nachtrag von `ziel_von` und `ziel_bis` stand dahinter und lief nie. Regressionstest: `test_ki.ModellTests.test_fehlende_zielzeit_wird_nachgetragen_ohne_zweites_training`.

## Vergleich, der keine Qualität beweist

`prognose_vergleich.py` misst drei Regeln. Das ist ein technischer Vergleich, keine bessere Prognose. Die echten Horizonte wurden damit nicht neu gerechnet.

## Behoben am 24. November 2026, abends

Eine zweite Meldung am selben Kalendertag wird nicht mehr allein deshalb verworfen. Sie bleibt außen vor, wenn sie dieselbe Ereignis-Kennung hat oder ihr Zielzeitraum ein schon trainiertes Beispiel überlappt. Eine alte Zeile mit dem Grund „Gleicher Kalendertag, erstes Beispiel zählt“ wird beim nächsten Lauf dieses Symbols nachgeholt, wenn der Zielzeitraum frei ist. Die Zielzeit kommt aus den gespeicherten Schlüssen, wenn diese Reihe länger ist als die gerade geladene. Eine schon gemessene Prüfung mit Brier-Wert wird nicht durch „Nicht ausreichend trainiert“ ersetzt. Nichts davon gibt ein Modell frei.

## Offen

1. Alte Zeilen in `daten/markt.sqlite` haben die neuen Zeiten erst, wenn das Fenster das Symbol mit einer ausreichenden Kursreihe erneut verarbeitet. Ein Massenupdate wurde nicht gestartet.
2. Die gespeicherten Horizontprüfungen sind die alten Berichte. Horizonte 1 und 3 haben die Basisrate nicht geschlagen. Horizonte 5 und 20 hatten keine zeitlich späteren Testfälle. Nichts davon wurde neu gerechnet.
3. `aktion_aus_ki()` ist inaktiv. Das ist korrekt, solange kein Horizont freigegeben ist.
4. Nachrichtenklassen sind Schlüsselwörter. Dieselbe Meldung über mehrere Quellen kann noch als mehrere Zeilen existieren, wenn der Ereignisschlüssel sie nicht trifft.
5. Splits, Dividenden, Makro, Sektor und Kapitalströme fehlen. Sie werden nicht geschätzt.
6. Spread und Slippage sind nicht gemessen. Die Gebühr ist eine gekennzeichnete Annahme.
7. `haendler.py` bündelt zu viele Aufgaben.
8. GitHub Actions ist nicht veröffentlicht.
9. Die elf offenen historischen RSI-Fälle liegen über der neuen Grenze von zehn. Sie bleiben gespeichert und werden nicht gelernt. Neue Käufe für diesen Trader sind blockiert.
10. Unit-Tests ersetzen keine spätere Paper-Trading-Auswertung.

Keines dieser offenen Punkte darf durch eine gesenkte Schwelle oder eine erfundene Kennzahl geschlossen werden.
