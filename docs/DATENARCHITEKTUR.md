# Datenarchitektur

Stand: 24. November 2026.

Rohkurse und Nachrichten liegen in `daten/markt.sqlite`. Features für die Prognose entstehen in `ki.merkmale()` nur aus Balken vor der Meldung. Das Ziel und `ziel_von` / `ziel_bis` kommen aus späteren Balken in `lernen.zielzeit()`.

`ki_beispiel` ist die Trainingszeile. `ki_horizont` hält Gewichte, Prüfung und Einsatzgewichte. Einsatzgewichte werden nur bei bestandener Prüfung geschrieben.

`prognose` ist die unveränderliche Prognosezeile. Vorhandene Zeilen werden nicht überschrieben. Die Wahrscheinlichkeiten sind NULL.

Traderfälle liegen in `ki_haendler_fall` mit der Spalte `haendler`. Papierkonten liegen getrennt davon in `papier.py`.

Migrationen sind `CREATE TABLE IF NOT EXISTS` und `ALTER TABLE ADD COLUMN`. Es wird keine Tabelle geleert.
