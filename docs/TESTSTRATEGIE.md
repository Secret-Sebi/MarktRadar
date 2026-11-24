# Teststrategie

Stand: 24. November 2026.

## Befehl

```
/usr/bin/python3 -m unittest discover -q
```

Python ist `/usr/bin/python3`, Version 3.9.6. Neue Annotationen brauchen `from __future__ import annotations`.

## Letzter Lauf

24. November 2026: 228 Tests, 19,259 Sekunden, alle bestanden, 0 fehlgeschlagen, 0 übersprungen.

Vor der Korrektur ist `test_fehlende_zielzeit_wird_nachgetragen_ohne_zweites_training` fehlgeschlagen. Nach dem Entfernen des frühen `continue` ist derselbe Test bestanden. Der Gesamtlauf danach war grün.

## Was die Tests prüfen

- Zielzeiten aus echten Balken, keine erfundenen Fenster
- Kein zweites Training und keine zweite Zeile beim Nachtrag
- Vollständige Zielzeiten bleiben stehen
- Zu kurze Reihen bleiben leer
- Validierung schreibt keine Testkennzahl
- Ein gehaltener Test wandert nicht ins Training
- Trader zählen nur eigene Abschlüsse
- Pence hängt nicht am Hinweistext
- Ein Schritt ist nur „läuft“, wenn das Backend das meldet
- `aktion_aus_ki()` lässt die Aktion unverändert

## Was sie nicht prüfen

Sie rufen keine echten Netzquellen. Sie beweisen nicht, dass ein Horizont den Markt schlägt. Sie prüfen die echte Datei `daten/markt.sqlite` nicht.

## CI

Ein Workflow liegt lokal und ist nicht auf GitHub. Der Token darf `workflow` nicht schreiben. Tests laufen deshalb lokal nach jeder Änderung, nicht in GitHub Actions.
