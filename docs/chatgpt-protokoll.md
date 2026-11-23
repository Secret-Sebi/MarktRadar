# MarktRadar – Protokoll für ChatGPT

Stand: Montag, 23. November 2026, etwa 16:52 Uhr Berlin.
Quelle der Zahlen: die lokale Datenbank `daten/markt.sqlite`. Diese Datei liegt nicht auf GitHub.
GitHub `main` ist Commit `f7ca57f`. Danach gibt es lokale, noch nicht gepushte Änderungen an Suche, Messstatus und Tests. Das Fenster läuft mit diesem lokalen Stand auf `http://127.0.0.1:64841/`.

Lies dieses Protokoll, bevor du über Lernen, Trader oder Prognosen schreibst. Erfinde keine Kurse, keine Erfolgsquoten und kein „die KI ist besser geworden“.

## Was die beiden KIs sind

Es gibt zwei getrennte Lernwege.

1. Die Analyse-KI in `ki.py`. Ein einziges Modell für alle Aktien. Es lernt an Nachrichten, deren späterer Kurs schon bekannt ist.
2. Die KI-Trader in `haendler.py`. Jeder Trader hat eine eigene Regel, ein eigenes Paper-Buch und erst nach einem Verkauf einen Lernkandidaten. Die aktive Regel bleibt, bis eine spätere Prüfung besteht.

Ein Montag oder ein laufendes Fenster heißt nicht, dass dauernd gelernt wird.

## Analyse-KI: wie sie beim Messen lernt

Beim Messen einer Aktie ruft `beobachter.bewerte()` nacheinander Kurs, Technik, Nachrichten, dieses Modell, Fundamentaldaten und Muster auf.

Nachrichten landen in der Tabelle `nachrichten`. `lernen.nachtragen()` schreibt später die Kursänderung nach 1, 3, 5 und 20 Handelstagen in `wirkung_1`, `wirkung_3`, `wirkung_5` und `wirkung_20`. Das passiert erst, wenn diese späteren Schlüsse wirklich vorliegen. Vorher bleibt das Feld leer.

`ki.trainiere()` nimmt danach nur Zeilen mit `ki_genutzt = 0` und einem schon gesetzten `wirkung_1` oder `wirkung_5`. Die Eingabe darf nur Kurse verwenden, die vor dem Zeitpunkt der Nachricht lagen: Themenfeld, RSI geteilt durch 100, und ob der Schluss über dem 20-Tage-Schnitt lag. Das Ziel ist 1, wenn die spätere Bewegung positiv war, sonst 0. Ein Schritt ändert die Gewichte mit Lernrate 0,2 und begrenzt sie auf -5 bis 5. Dieselbe Nachricht wird danach mit `ki_genutzt = 1` markiert und nicht noch einmal trainiert. Pro Kalendertag und Aktie zählt nur ein Beispiel.

Das Modell ist eine Zeile in `ki_modell`, id 1. Es ist nicht je Aktie getrennt.

`schaetzung()` liefert erst ab 12 Beispielen eine Zahl. Diese Zahl ist keine freigegebene Wahrscheinlichkeit. `aktion_aus_ki()` gibt die ursprüngliche Entscheidung unverändert zurück und verwirft Modell, Schätzung und Prüfung. Die Messung wird durch dieses Modell also nicht zum Kauf oder Verkauf umetikettiert. Die Oberfläche darf die Zahl nicht als validierte Prognose zeigen.

`messe()` trainiert auf älteren Nachrichten derselben Aktie neu und zählt Treffer nur auf den letzten 12 Fällen. Dafür braucht es mindestens 24 Fälle. Das Ergebnis ist eine Trefferzahl, keine freigegebene Erfolgsquote für das Dashboard.

### Gemessener Stand der Analyse-KI

- `ki_modell.beispiele`: 1556. Am Sonntagabend, 22. November, waren es 1533. Seitdem sind 23 Beispiele dazugekommen.
- Nachrichten gesamt: 3778. Davon `ki_genutzt = 1`: 2482. `wirkung_1` ist bei 2482 Zeilen gesetzt.
- Nachrichten mit Zeitstempel von heute: 17. Davon `ki_genutzt = 1`: 0. Der nächste Handelstag nach diesen Meldungen ist noch nicht auswertbar, deshalb trainiert das Modell sie noch nicht.
- Heute neu gespeicherte Messzeilen in `auswertung`: 98. Davon vollständig nach dem Schrittprotokoll: 0. Bei allen 98 fehlt der Fundamental-Schritt. Bei 11 fehlt zusätzlich der Nachrichten-Schritt. Ein frischer Kurs allein ist keine vollständige Analyse.

Die Analyse-KI lernt also nur die Richtung nach einer bereits bekannten Nachricht. Sie lernt nicht aus Fundamentaldaten, nicht aus dem Muster und nicht als geprüfte Prognose. Prognosewahrscheinlichkeiten bleiben leer, solange keine bestandene, unveränderte Prüfung vorliegt.

## KI-Trader: was sie gemacht haben

Die Trader entscheiden mit festen Regeln in `entscheide()`. Eigene Gewichte dürfen einen Kauf nur ablehnen, wenn schon ein passendes Modell mit mindestens 12 Beispielen existiert und die Modellzahl unter 50 Prozent liegt. Dieses Modell existiert derzeit nicht.

Seit Montag, 23. November, 0:00 Uhr Berlin, bis zur letzten gespeicherten Entscheidung um 16:35 Uhr:

- 15587 Skip
- 7048 Hold
- 2 Buy
- 3 Sell

Die zwei Käufe, beide noch offen, mit dem Zusatz „Noch keine passenden Gewichte. Nicht zuverlässig.“:

- Momentum, Allianz `ALV.DE`, 14:19 Uhr. Grund der Regel: Schluss nach 20 Tagen und nach 5 Tagen höher.
- Trend, Amazon `AMZN`, 15:50 Uhr. Grund der Regel: Schluss über dem 20- und dem 50-Tage-Schnitt.

Die drei Verkäufe sind die Krypto-Regel „Schluss unter dem 50-Tage-Schnitt“, nicht ein gelerntes Modell:

- Krypto, Bitcoin, 23. November 00:08 Uhr
- Krypto, Solana, 00:13 Uhr
- Krypto, Ethereum, 04:10 Uhr

Offene Paper-Fälle in `ki_haendler_fall`: 33. Abgeschlossen: 0. Als gelernt markiert: 0.

- RSI 11
- Experiment 10
- MACD 8
- Trend 3
- Momentum 1

`ki_haendler_version`: 0. `ki_haendler_modell`: 0. `ki_haendler_pruefung`: 0. Die Meta-AI hat seit Sonntag, 22. November, 14:14 Uhr keinen neuen Eintrag. Ihre letzte Notiz bleibt „Keine Gewichtung“, Marktphase nicht gemessen.

## KI-Trader: wie sie lernen

Ein Kauf schreibt einen offenen Fall. Dabei wird nichts gelernt.

`_fall_zu()` läuft erst beim Verkauf. Dann werden Ausstieg, Nettoergebnis nach der Gebührenannahme und die Ausstiegszeit gespeichert. Spread und Slippage bleiben „nicht gemessen“. Wenn der Fall noch nicht gelernt wurde, ruft `_lerne()` einen Gewichtsschritt auf und speichert zwei Versionszeilen: das bisherige Modell und den Kandidaten mit dem Grund „Kandidat, nicht freigegeben“. Der Fall wird auf `gelernt = 1` gesetzt. Die aktive Regel und `ki_haendler_modell` bleiben unverändert.

`uebernehmen_wenn_besser()` übernimmt den Kandidaten nur, wenn `pruefe()` das Feld `besser` setzt. `pruefe()` trainiert nur auf früheren abgeschlossenen Fällen und prüft spätere. Unter 36 abgeschlossenen Fällen desselben Traders ist das Ergebnis „Nicht ausreichend Daten“. Ab 36 Fällen werden sie zeitlich in drei Teile geteilt. Der Test muss nach der Prüfung liegen.

Freigabe verlangt gleichzeitig:

- Die Prüfung wählt das Modell, weil sein mittleres Netto über dem der Regel liegt.
- Mindestens 12 spätere Testfälle, und das Modell nimmt mindestens 12 davon.
- Die untere Grenze dieser Ergebnisse liegt über 0 und über dem Mittel der Regel.
- Das Modellvermögen endet über dem Start, über der Regel und über einem Indexkauf derselben Haltedauer.
- Der Rückgang des Modells bleibt bei höchstens 8 Prozent und ist nicht schlechter als der der Regel.

Die Indexreihe für `^GDAXI` und `^GSPC` hat in `kurse` derzeit 0 Zeilen. Ohne diese Reihe ist die Benchmark „nicht gemessen“, und `besser` bleibt falsch. Selbst 36 Verkäufe geben dann nichts frei.

Keiner der 33 Fälle ist verkauft. Ein Trader hat höchstens 11 offene Fälle. Die Freigabe ist damit weder heute noch durch bloßes Weiterlaufen am Montag erreicht.

## Was nicht behauptet werden darf

- Die Trader haben heute nicht dazugelernt.
- Die Analyse-KI hat 23 weitere Nachrichtenbeispiele in das eine globale Modell geschrieben. Das ist kein Beweis, dass Prognosen besser wurden.
- 1556 Beispiele sind keine Trefferquote.
- Skip und Hold sind keine Lernschritte.
- Die Meta-AI gewichtet nichts und darf die Risikogrenzen nicht ändern.
- Es wird kein echtes Geld gehandelt. Alpaca ist nicht verbunden.

## Risikogrenzen, unverändert

Höchstens 1 Prozent Risiko pro Trade, 10 Prozent Positionsgröße, 10 offene Positionen, 2 Prozent Tagesverlust, Pause bei 8 Prozent Drawdown, mindestens 10 Prozent Cash. Kein Margin, keine Optionen, kein Echtgeld.
