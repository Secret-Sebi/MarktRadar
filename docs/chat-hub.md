# Chat-Hub: Lauf vom 23. November abends bis zum 24. November 2026

Du analysierst einen abgeschlossenen Messlauf von MarktRadar. Du lobst ihn nicht. Du schreibst nicht, die KI sei besser geworden. Du erfindest keine Gedanken, die nicht als Text in der Datenbank stehen.

Abfrage auf dem Mac: Dienstag, 24. November 2026, 15:36 Uhr Berlin. Die Datenbank `daten/markt.sqlite` liegt nicht auf GitHub. Die Lernanzeige, die Sperre für überlappende Zielzeiträume und die Pence-Korrektur liegen auf `main`. Die Zahlen bleiben diese Abfrage.

Der spätere Tagesstand vom 24. November 2026, 23:14 Uhr Berlin, steht in `docs/lernen-2026-11-24.md`. Die Zahlen hier nicht mit dem Tagesstand mischen.

## Was es nicht gibt

Es gibt kein Protokoll, in dem die KI einen Gedankengang aufschreibt. Gespeichert sind Regeln, Zähler und der Grund einer Prüfung. Ein Satz wie „die KI hat erkannt“ ist nur zulässig, wenn derselbe Satz unten als gespeicherter `grund` steht.

Eine bestandene Unit-Test-Suite ist keine Trefferquote. Paper-Zahlen sind eine lokale Simulation zum letzten Kurs. 0,125 Prozent Gebühr je Seite sind eine Annahme. Spread, Slippage und Benchmark dieses einen Verkaufs sind als „nicht gemessen“ gespeichert.

## Ob der Mac lief

In `ki_haendler_entscheidung` liegt in jeder UTC-Stunde von `2026-11-23T17` bis `2026-11-24T14` mindestens eine Entscheidung. Das ist 18:00 Uhr Berlin am 23. November bis 15:00 Uhr Berlin am 24. November. Die Runde war in diesem Fenster nicht aus. Ein ausgeschalteter Mac hätte diese Zeilen nicht geschrieben.

Die meisten Zeilen sind `SKIP` oder `HOLD`. Das sind keine Lernfälle.

## Was die Auswertung über Nacht gespeichert hat

`ki_beispiel`, Status `trainiert`: 643 Zeilen. Davon haben 438 kein Feld `erfasst`. Diese Spalte gab es vorher nicht. Die alten Zeilen wurden nicht nachträglich mit einer Uhrzeit gefüllt. Sie zählen nur in der Summe.

Neue Stempel:

- 204 Zeilen in der Berliner Stunde ab 23:00 Uhr am 23. November
- 1 Zeile in der Berliner Stunde ab 11:00 Uhr am 24. November

Die Oberfläche zeigte deshalb um 15:31 Uhr: Gesamt 643, Heute 1, Seit einer Woche 205, Seit einem Monat 205. Woche und Monat sind gleich, weil nur diese 205 einen Stempel haben. Die Einheit heißt Beispiele. Ein Beispiel ist eine gespeicherte Übung an einer Meldung. Das ist keine bestandene Prüfung und kein Prozent von einem unbekannten Ziel.

Dieselben 643 Zeilen stehen als Zähler auf den Horizonten: 1 Handelstag 181, 3 Handelstage 178, 5 Handelstage 158, 20 Handelstage 126. Alle vier haben `validiert = 0`.

Das alte `ki_modell` bleibt bei 1.556 Beispielen. Es wurde von diesem Lauf nicht als das neue Modell weitertrainiert.

`ki_genutzt = 1` steht an 2.485 Nachrichten. Am 23. November, etwa 17:45 Uhr, waren es 2.482. Eine Markierung ist kein Nachweis, dass die Zeile in `ki_beispiel` trainiert wurde. 2.485 Markierungen und 643 Trainingszeilen sind nicht dasselbe.

## Wie die Horizont-Prüfung entschieden hat

Die Prüfung schreibt einen Grund. Sie schreibt keine Begründung in Sätzen darüber hinaus.

Horizont 1, `n = 181`, `bestanden = false`. Gespeicherter Grund: „Validierung schlägt die Basisrate nicht“. Brier etwa 0,374 gegen eine Basis von etwa 0,222. Log-Loss etwa 0,952 gegen etwa 0,637. Höher ist hier schlechter. In einem belegten Fach mit 21 Fällen lag die mittlere Vorhersage bei etwa 0,68 und die Trefferquote bei etwa 0,10. Das ist der gespeicherte Kalibrierungsblock, nicht eine neue Rechnung.

Horizont 3, `n = 178`, derselbe Grund. Brier etwa 0,544 gegen etwa 0,279. Log-Loss etwa 1,377 gegen etwa 0,751. Ein Fach mit 26 Fällen: mittlere Vorhersage etwa 0,78, Trefferquote etwa 0,12.

Horizont 5, `n = 158`, Grund: „Testfälle liegen nicht nach der Prüfung“. Brier ist `null`. Die Fallzahl liegt über 108. Die zeitliche Trennung ist nicht bestanden. Daraus wird keine Trefferquote.

Horizont 20, `n = 126`, derselbe Grund, Brier `null`.

Kein Horizont ist freigegeben. `prognose` hat 0 Zeilen. Angezeigte Stärken bleiben ohne Wahrscheinlichkeit.

## Was die Trader entschieden haben

Gespeichert sind die Regeltexte, nicht eine Beratung.

Käufe, Uhrzeit Berlin:

- 23. November, 18:11, Momentum, `AMZN`. Grund beginnt mit: „Der Schluss liegt nach 20 Tagen und nach 5 Tagen höher.“ Die Meldung ist `sonstiges`, Stimmung neutral, Stärke 0. Im Text steht: keine validierte Wahrscheinlichkeit.
- 23. November, 23:39, Momentum `AAPL` und `TSLA`, MACD `AAPL` und `TSLA`, Trend `AAPL` und `TSLA`, Statistik `SIE.DE`. Momentum und Trend nennen dieselbe Kursregel und eine neutrale Meldung ohne validierte Wahrscheinlichkeit. MACD: „Die MACD-Linie liegt über der Signallinie. Noch keine passenden Gewichte. Nicht zuverlässig.“ Statistik: „Mindestens 30 unabhängige Fälle mit gemessenem Vorsprung. Noch keine passenden Gewichte. Nicht zuverlässig.“
- 24. November, 01:01, Statistik, `AMD`, derselbe Statistik-Satz.

Verkäufe, Uhrzeit Berlin:

- 24. November, 00:20, Krypto, `SOL-USD`: „Der Schluss liegt unter dem 50-Tage-Schnitt.“
- 24. November, 02:44, Krypto, `BTC-USD`, derselbe Satz.
- 24. November, 04:06, Krypto, `ETH-USD`, derselbe Satz.
- 24. November, 10:06, MACD, `AIR.DE`: „Die MACD-Linie liegt unter der Signallinie.“

Nur der letzte Verkauf hat einen abgeschlossenen Trader-Fall geschrieben. Für die drei Krypto-Verkäufe liegt in `ki_haendler_fall` kein Abschluss.

Offene Fälle jetzt: 41. RSI 11, Experiment 10, MACD 9, Trend 5, Momentum 4, Statistik 2. Am 23. November nachmittags waren 33 offen und 0 zu. Die 11 RSI-Fälle sind weiter offen. Sie sind nicht gelöscht und nicht als gelernt gezählt. Die Grenze von 10 gilt je Trader. RSI bleibt bei 11 alten offenen Fällen.

## Der eine Abschluss

`ki_haendler_fall` id 15, Händler MACD, Symbol `AIR.DE`. Einstieg 190,00, Ausstieg 194,96, Menge 5. Brutto 24,80. Gebühr Annahme 1,19 plus 1,22. Netto 22,39. Spread „nicht gemessen“. Slippage „nicht gemessen“. Benchmark „nicht gemessen“. Ausstiegszeit `2026-11-24T09:06:06Z`, also 10:06 Uhr Berlin. Quelle `simulation`.

`gelernt = 1` an diesem Fall heißt: der Abschluss wurde als Kandidat gespeichert. Es heißt nicht, dass die Regel ersetzt wurde.

`ki_haendler_version` 1: „Start, nicht eingesetzt“. Version 2: „Kandidat, nicht freigegeben“, 1 Beispiel, dieselbe Sekunde. `ki_haendler_pruefung`: `besser = 0`, Grund: „Weniger als 36 abgeschlossene Fälle für Training, Prüfung und Test.“ `test_n = 1`. `ki_haendler_modell` hat 0 Zeilen. Die aktive Regel wurde nicht ersetzt.

Ein Papiergewinn in einem Fall ist kein Nachweis, dass MACD etwas gelernt hat.

## Meta

Letzter Eintrag id 39, `2026-11-24T14:31:05Z`, also 15:31 Uhr Berlin. Phase `fallend` aus gespeicherten Schlüssen von `^GDAXI`. 20-Tage-Rendite etwa -2,41 Prozent. Am 23. November nachmittags stand dort `seitwaerts` und etwa -0,14 Prozent. Das ist eine neue Rechnung auf dem Index, keine neue Intelligenz. `gewichte` leer, `krypto_gewichte` leer. Der Hinweis sagt: keine Gewichtung ohne bestandene unabhängige Prüfung, Risikogrenzen bleiben, Nachrichten sind nicht als Gewichtung freigegeben.

## Nachrichten und Kurse

Nachrichten gesamt: 3.885. Davon haben 81 eine `zeit` ab dem 23. November, 18:00 Uhr Berlin. `wirkung_1` ist bei 2.488 Zeilen gesetzt, `wirkung_3` bei 1.930, `wirkung_5` bei 1.528, `wirkung_20` bei 872. Am 23. November, etwa 17:45 Uhr, waren es 3.795 Nachrichten und 2.482 mit `wirkung_1`. Die Differenz ist kein Nachweis, dass jede neue Zeile über Nacht gemessen wurde. Eine spätere Kursbewegung bleibt eine Zuordnung, keine Ursache.

`auswertung`: weiter 627 Zeilen. Datenstatus unverändert 611 `ok`, 15 leer, 1 `unvollstaendig`. Das Fenster zeigte um 15:30 Uhr eine andere Zählung der geladenen Namen: 623 erfasst, 608 mit aktuellem Kurs, 14 vollständig, 594 teilweise, 15 fehlgeschlagen. Die Tabellenzeile und die Fensterzählung sind nicht dieselbe Menge. Ein Kurs ist keine vollständige Analyse.

Papier bleibt lokal. Einzelne Kontozeilen um 15:21 Uhr Berlin tragen die Quelle „letzter Kurs“. Daraus wird hier keine Systemrendite gerechnet. Es gibt keine echte Order. Alpaca ist nicht verbunden.

## Was bei der Anzeige festgehalten wurde

Die Oberfläche sollte nicht „Prozent gelernt“ zeigen. Ein Ziel von 100 Prozent ist nicht definiert. Sichtbar sind vier Zähler in der Einheit Beispiele. Die Aufteilung nach Horizont und die 0 von 36 abgeschlossenen Trader-Fällen liegen unter „Mehr“. Ein blaues Licht bedeutet, dass die Runde einen Namen gerade holt oder dass er in der Warteschlange steht. Ein Licht ist kein Lernerfolg.

Der Stempel `erfasst` gilt erst für Beispiele, die nach dem Ergänzen der Spalte geschrieben wurden. Die 438 älteren Zeilen absichtlich nicht auf „gestern“ oder „heute“ zu setzen, ist die ehrliche Lücke. Sie ist keine vergessene Stunde.

## Auftrag

Prüfe diesen Lauf gegen den Code auf `main` und gegen das, was nur lokal liegt. Melde eine Schwäche nur mit einer Zahl aus diesem Hub oder mit einer Stelle im veröffentlichten Commit. Wenn du sie dort nicht siehst, schreibe „im veröffentlichten Stand nicht geprüft“.

Besonders:

- Horizonte 1 und 3 sind schlechter als die konstante Basisrate. Das ist ein Fehlschlag der Prüfung, kein Fortschritt.
- Horizonte 5 und 20 haben genug Fälle für den Zähler 108 und bestehen die zeitliche Trennung nicht.
- Ein Abschluss von 36 nötigen Fällen gibt keine Regel frei.
- `gelernt = 1` am Fall AIR.DE ist ein Kandidat, kein eingesetztes Modell.
- 643 Beispiele, 205 mit Uhrzeit und 1 Beispiel heute sind Zähler. Sie sind keine Trefferquote.
- Käufe aus Momentum, Trend, MACD und Statistik bleiben die alte Regel. Die mitgeschriebene Nachricht ist neutral und nicht validiert.
- Die Meta-Phase `fallend` setzt keine Gewichte.
- Die Datenbank dieses Berichts ist nicht der Stand auf GitHub.
