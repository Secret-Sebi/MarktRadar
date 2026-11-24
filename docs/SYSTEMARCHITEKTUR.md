# Systemarchitektur

Stand: 24. November 2026.

Die vier Bereiche sind Verantwortungen. Sie sind nicht vier getrennte Programme.

| System | Stand | Wo es im Code liegt |
| --- | --- | --- |
| 1 Forecasting | TEILWEISE IMPLEMENTIERT | `ki.py`, `ki_pruefung.py`, `prognose_vergleich.py`, `prognose.py` |
| 2 Paper-Trader | TEILWEISE IMPLEMENTIERT | `haendler.py`, `papier.py` |
| 3 Meta-KI | NICHT IMPLEMENTIERT als Gewichtung | `ki_haendler_meta` speichert nur einen Text mit leeren Gewichten |
| 4 Monitoring | TEILWEISE IMPLEMENTIERT | Schrittstatus in `beobachter.py` und `fenster.py`, Prüfungstext in `lernen.py` |

Gemeinsame Daten liegen in `daten/markt.sqlite`. Kurse, Nachrichten und Fundamentaldaten bleiben die vorhandenen Module.

Eine Freigabe gibt es nur über `ki_pruefung.pruefe_faelle()` für die Logistik und über `haendler.pruefe()` für einen einzelnen Trader. Der Modellvergleich darf diese Entscheidung nicht ersetzen.
