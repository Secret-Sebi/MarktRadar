# Prognosevalidierung

Stand: 24. November 2026.

## Trennung

`pruefe_faelle()` sortiert nach Zielbeginn. 36 Fälle trainieren, 36 validieren, 36 bleiben Test. Ein Ziel, das in den nächsten Abschnitt reicht, fällt aus dem linken Abschnitt. Unter 36 verbleibenden Fällen besteht die Prüfung nicht.

Die Validierung muss Brier und Log-Loss der konstanten Basisrate schlagen. Danach läuft ein Walk-forward auf den Blöcken vor dem Test. Erst dann wird der Test gemessen. Schlägt die Validierung fehl, bleibt `test` leer. Der Beginn des reservierten Tests wird trotzdem gespeichert. Spätere Läufe trainieren keine Fälle, deren Zielende nach dieser Grenze liegt.

Ein bereits bewerteter Test wird nicht erneut gewertet. `bestanden` wird nur wahr, wenn auch Kalibrierung und Test die Schwellen schaffen. Die Kalibrierung verlangt mindestens zwei belegte Körbe mit je mindestens fünf Fällen und höchstens 0,15 Abstand zwischen mittlerer Prognose und Trefferquote.

## Baselines

Die Vergleichsprognose ist die Trefferquote des Trainingsabschnitts, konstant auf Validierung und Test gelegt. Es gibt keinen zweiten Vergleich mit einem Momentum-Modell oder mit Buy-and-Hold innerhalb von `ki_pruefung.py`. Der Trader-Vergleich nutzt den passenden Index, wenn dessen Reihe vorliegt.

## Freigabe

`validiert` bleibt 0, solange der Bericht nicht besteht. `modell_fuer_anzeige()` gibt dann `None` zurück. Angezeigte Stärken sind keine Wahrscheinlichkeiten.

Die schon gespeicherten Prüfungsberichte der Horizonte 1, 3, 5 und 20 wurden in dieser Sitzung nicht neu gerechnet.

## Schwellen, die bleiben

108 Fälle insgesamt, 36 je Abschnitt, Kalibrierungsabstand 0,15. Diese Werte werden nicht gesenkt, um mehr Freigaben zu erzeugen.
