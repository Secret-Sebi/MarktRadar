# Schnittstellen

Stand: 24. November 2026.

Es gibt keine separaten Klassen mit den Namen aus dem Auftrag. Die benutzten Verträge sind die Rückgaben, die der Code wirklich schreibt.

| Vertrag im Auftrag | Tatsächliche Form | Stand |
| --- | --- | --- |
| ForecastContract | Prüfungswörterbuch plus `vergleich.modelle` | TEILWEISE. Wahrscheinlichkeiten in `prognose` bleiben leer |
| TraderSignalContract | Entscheidungstext und Zeile in `ki_haendler_fall` | TEILWEISE. `aktion_aus_ki()` verändert die Aktion nicht |
| TraderPerformanceContract | Zähler je `haendler` in `lernen._pruefung_balken` | TEILWEISE. 36 Abschlüsse sind keine Freigabe |
| StrategyCandidateContract | Zeile in `ki_haendler_version` | TEILWEISE. Kandidat ersetzt die Regel nicht |
| MarketRegimeContract | Text in `ki_haendler_meta` | TEILWEISE. Phase aus dem Index, Gewichte leer |
| MetaForecastContract | nicht vorhanden | NICHT IMPLEMENTIERT |
| ModelHealthContract | `vergleich` und der Prüfungssatz | TEILWEISE |
| SystemAlertContract | Schrittstatus `wartet`, `läuft`, `erfolgreich`, `fehlgeschlagen`, `nicht verfügbar` | TEILWEISE |

Pflicht jeder Prognosefreigabe: `bestanden` aus `pruefe_faelle()`, nicht aus dem Vergleich allein.
