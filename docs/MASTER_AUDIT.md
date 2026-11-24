# Master-Audit

Stand: 24. November 2026. Quelle ist der Code auf `main` plus die Korrektur an `trainiere()`. Das ist eine Prüfung der bestehenden Wege, kein Nachweis besserer Prognosen.

## Datenfluss einer Runde

`beobachter.py` holt Kurse, ruft `bewerte()` auf und schreibt danach den Fensterstatus. `lernen.aktualisiere()` speichert Nachrichten und misst spätere Renditen nur aus vorhandenen Balken. `ki.trainiere()` baut je Horizont 1, 3, 5 und 20 ein Beispiel, wenn Wirkung und Zielzeit bekannt sind. `ki_pruefung.pruefe_faelle()` bewertet erst die Validierung und nur danach den Test. `haendler.py` entscheidet mit festen Regeln. `papier.py` führt virtuelle Bücher. `aktion_aus_ki()` verändert die Aktion nicht.

## Module

| Bereich | Dateien | Was der Code tut |
| --- | --- | --- |
| Kurse | `kurse.py`, `quellen.py`, `quellen_stooq.py`, `quellen_coingecko.py`, `euro.py` | Yahoo, dann Stooq. Krypto über CoinGecko in Euro. Historische Wechselkurse je Balken. Pence einmal nach Pfund |
| Nachrichten | `lernen.py`, `nachrichten_analyse.py` | Yahoo und GDELT, Überschriften, Schlüsselwortklassen. Wirkung erst nach echten späteren Kursen |
| Fundamental | `fundamental.py` | Yahoo quoteSummary mit Crumb. Fehler werden nicht sechs Stunden als „fehlt“ gecacht |
| Technik | `technik.py` | Indikatoren aus gespeicherten Schlüssen |
| Einfluss | `einfluss.py` | Sechs Bereiche. Makro, Kapitalströme und Branche bleiben fehlend |
| Prognose | `ki.py`, `ki_pruefung.py`, `prognose.py` | Online-Logistik je Horizont. `prognose` speichert Zeilen mit leeren Wahrscheinlichkeiten |
| Trader | `haendler.py` | Viele feste Regeln, eigene Fälle, eigene 10-Positions-Grenze |
| Papier | `papier.py` | Virtuelle Konten. Kein Live-Broker |
| Fenster | `fenster.py`, `fenster_app/seite.html` | Lokales Fenster auf 127.0.0.1 |

## Weg einer Prognose

1. Eine Meldung braucht einen Zeitpunkt und genug Kurse davor.
2. `merkmale()` benutzt nur Balken vor diesem Zeitpunkt.
3. Das Ziel ist das Vorzeichen der gemessenen Wirkung über 1, 3, 5 oder 20 Handelsbalken.
4. `zielzeit()` speichert Beginn und Ende dieses Balkenabstands.
5. Ohne beide Zeiten kommt das Beispiel nicht in `pruefe_faelle()`.
6. Training, Validierung und Test sind chronologische Drittel zu je 36 Fällen.
7. Überlappende Zielzeiträume werden entfernt. Ein schon reservierter Test wird nicht erneut zum Training.
8. `modell_fuer_anzeige()` liefert nur Gewichte, wenn `ki_horizont.validiert = 1` und Einsatzgewichte existieren. Das ist derzeit nicht der Fall.
9. `prognose.empfehlung()` bleibt „KEINE AUSREICHENDE DATENBASIS“.

## Weg des Lernens

Analyse-KI: `schritt()` ändert Gewichte nur für ein neues Beispiel. Ein zweiter Aufruf trainiert dieselbe Nachricht nicht noch einmal. Die Prüfung schreibt `einsatz_gewichte` nur bei bestandenem Test. Das alte `ki_modell` mit 1556 Beispielen wird nicht weiter vermischt.

Trader: ein Abschluss kann einen Kandidaten in `ki_haendler_version` speichern. `ki_haendler_modell` wird nur ersetzt, wenn `pruefe()` für diesen Trader besteht. Dafür fehlen 36 eigene Abschlüsse. Die Anzeige zählt je `haendler`, nicht die Summe aller Trader.

Meta: `ki_haendler_meta` speichert einen Text. Die Gewichte darin sind leer. Eine Marktphase ist eine Indexrechnung, keine übernommene Trader-Meinung.

## Gefundener Fehler

In `trainiere()` stand vor der Zielzeitprüfung ein `continue`, sobald `ki_beispiel` die Nachricht schon enthielt. `_ziel_nachtragen()` war dadurch unerreichbar. Alte Zeilen ohne `ziel_von` und `ziel_bis` blieben leer und fehlten in der Prüfung, obwohl die Balken den Zeitraum rekonstruieren konnten.

Die Prüfung läuft jetzt zuerst. Eine vorhandene Zeile bekommt die Zeiten nur, wenn `zielzeit()` sie aus den übergebenen Balken bildet. Eine schon gesetzte Zeit wird nicht überschrieben. Zu kurze Balken lassen die Felder leer. Es entsteht keine zweite Zeile und kein zweiter `schritt()`.

## Was nicht behauptet wird

- Die Modelle sind nicht besser geworden.
- Die Nachrichtenanalyse erklärt keine Kurse.
- Die Trader haben keine Strategie selbst entwickelt.
- Die Meta-KI gewichtet niemanden.
- 228 bestandene Unit-Tests sind kein Handelserfolg.
