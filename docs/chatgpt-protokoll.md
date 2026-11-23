# Auftrag an ChatGPT: Schwächen von MarktRadar finden

Du prüfst MarktRadar. Du lobst das System nicht und du glättest Lücken nicht. Du suchst Schwächen, falsche Anzeigen, fehlende Daten und Stellen, an denen Code oder Text mehr behauptet, als die Daten tragen.

Repository: https://github.com/Secret-Sebi/MarktRadar
Branch: `main`
Diese Datei: https://github.com/Secret-Sebi/MarktRadar/blob/main/docs/chatgpt-protokoll.md

## Lies zuerst diese Grenze

Dieser Commit veröffentlicht den lokalen Analysestand seit `0aa3ddf`, nicht nur dieses Dokument. Dazu gehören unter anderem `nachrichten_analyse.py`, `einfluss.py`, `ki_pruefung.py` und die zugehörigen Tests. `watchlist.txt` und die Datenbank bleiben draußen. Eine Datei, die in dem Commit fehlt, ist nicht veröffentlicht.

Leere `analyse`-Felder werden beim Öffnen des Fensters nachträglich gefüllt. Das JSON trägt `nachtraeglich` und `analysiert_um`. `zeit`, `wirkung_*` und `ki_genutzt` bleiben unverändert. Der Zuordnungstext wird nur aus schon gespeicherten Bewegungen geschrieben. Das ist keine damals bekannte Prognose und keine Ursache.

Die Datenbank `daten/markt.sqlite` liegt nicht auf GitHub. Die Zahlen unten sind eine Abfrage auf dem Mac am Montag, 23. November 2026, etwa 17:34 Uhr Berlin. Sie sind eine Momentaufnahme, keine Endbilanz. Die Messrunde kann danach weitergeschrieben haben.

## Was du nicht tun darfst

- Erfinde keine Kurse, Nachrichten, Fundamentaldaten, Wahrscheinlichkeiten, Erfolgsquoten oder Ursachen.
- Schreibe nicht, die KI sei besser geworden. Dafür gibt es keine bestandene unabhängige Prüfung.
- Eine positive Nachricht ist kein Kauf. Eine negative Nachricht ist kein Verkauf.
- Ein Kurs nach einer Meldung beweist nicht, dass die Meldung die Ursache war.
- Bestandene Unit-Tests bedeuten, dass geprüfte Funktionen laufen. Sie bedeuten nicht, dass Prognosen treffsicher sind.
- Paper-Trading ist keine echte Handelsleistung.
- 0,125 Prozent Gebühr je Seite und weitere 0,10 Prozent je Seite sind Annahmen. Spread und Slippage sind nicht gemessen.
- Schlage nicht vor, die Risikogrenzen zu lockern: 1 Prozent Risiko pro Trade, 10 Prozent Positionsgröße, 10 offene Positionen je Trader, 2 Prozent Tagesverlust, Pause bei 8 Prozent Drawdown, mindestens 10 Prozent Cash, kein Margin, keine Optionen, kein Echtgeld, keine echten Brokerorders.
- `aktion_aus_ki` darf keine Order auslösen. Alpaca ist nicht verbunden. Es gibt keine `.env` im Repository.

## Gemessener Stand, 23. November 2026, etwa 17:34 Uhr

Auswertungen: 627 Zeilen. Davon 611 mit Kursstatus `ok`, 15 ohne Status, 1 `unvollstaendig`. 98 Zeilen haben ein Schrittprotokoll. Davon sind 3 nach den Pflichtschritten vollständig. Ein vorhandener Kurs ist keine vollständige Analyse.

Fundamentalstände in diesen 98 Zeilen: 29 `ok`, 57 `fehlt`, 4 `nicht_verfuegbar`, 2 `nicht_anwendbar`, 6 ohne Stand.

Nachrichtenstände in diesen 98 Zeilen: 57 `ok`, 35 `fehler`, 6 ohne Stand. 35 Fehler sind Quellenausfälle, kein stilles Gelingen.

Nachrichten gesamt: 3.795. Davon `wirkung_1` gesetzt: 2.482. `ki_genutzt = 1` bleibt 2.482. Nach dem Nachtrag am 23. November 2026, etwa 17:45 Uhr, haben 3.795 Zeilen ein `analyse`-JSON mit `nachtraeglich` und 2.482 einen Zuordnungstext aus der gespeicherten Bewegung. Das ist keine damals bekannte Prognose.

`ki_modell.beispiele`: 1.556. Das ist das alte gemischte Modell. Die lokale Änderung trainiert es nicht weiter. Auf GitHub kann der alte Pfad noch sichtbar sein. Die Lücke zwischen 1.556 Beispielen und 2.482 `ki_genutzt = 1` ist nicht umetikettiert. Eine Markierung ist kein Nachweis, dass trainiert wurde.

Neue lokale Liste `ki_beispiel`: 151 `trainiert`, 231 `ausgeschlossen`. Horizonte, alle `validiert = 0`: 1 und 3 je 43 Beispiele, 5 hat 37, 20 hat 28. Grund: nicht ausreichend trainiert. Freigegeben ist kein Horizont. Die Tabelle `prognose` hat 0 Zeilen. Es wird keine Wahrscheinlichkeit angezeigt.

Indizes in `kurse`: `^GDAXI` 505 Schlüsse, `^GSPC` 500 Schlüsse. Das sind Marktindizes, keine Branchenindizes.

Trader-Fälle: 33 offen, 0 abgeschlossen, 0 gelernt. Offen: RSI 11, Experiment 10, MACD 8, Trend 3, Momentum 1. `ki_haendler_version` 0, `ki_haendler_modell` 0, `ki_haendler_pruefung` 0. Die 11 RSI-Fälle sind alte offene Fälle. Sie werden nicht gelöscht und nicht als gelernt gezählt. Die Grenze von 10 gilt je Trader. Ob der Code auf GitHub den elften Kauf noch zulässt, musst du im veröffentlichten `haendler.py` prüfen. Lokal wird die Grenze vor weiteren Käufen derselben Runde geprüft.

Meta-AI, Eintrag 17, Zeit `2026-11-23T16:33:49Z`: Phase `seitwaerts` aus gespeicherten DAX-Schlüssen, 20-Tage-Rendite etwa -0,14 Prozent. `gewichte` leer, `krypto_gewichte` leer. Alle 37 Trader stehen in `unzuverlaessig`. Der Hinweis sagt, dass ohne bestandene unabhängige Prüfung keine Gewichtung gesetzt wird und die Risikogrenzen bleiben.

Lokale Tests: `python3 -m unittest discover`, 199 Tests, alle bestanden, nach dem Einfluss-Status. Das ist kein Beleg für Prognosequalität. Nicht gelaufen sind ein Verkauf mit anschließender Freigabe, ein Test gegen den ganzen Yahoo-Abruf und ein Neustart mitten in einer Transaktion.

## Schwächen, die schon belegt sind

1. Die Analyse deckt das Universum nicht ab. 627 Zeilen haben einen Preis, nur 3 gespeicherte Messungen sind vollständig.
2. Fundamentaldaten fehlen in den meisten gespeicherten Schrittprotokollen. Eine Yahoo-Antwort ohne Krume war HTTP 401. Ob der Krume-Pfad auf GitHub schon liegt, siehst du nur im veröffentlichten `fundamental.py`.
3. Nachrichten sind Schlagzeilen von Yahoo und GDELT, kein Volltext, kein Sprachmodell. Die Stärke von -100 bis 100 ist eine Schlüsselwort-Einordnung, keine Wahrscheinlichkeit. `validiert` bleibt falsch.
4. Die gespeicherte Ereignisanalyse der alten Zeilen ist nachträglich. 2.482 Ein-Tages-Bewegungen sind gemessen, aber nicht als Ursache belegt.
5. Eine konkrete NVDA-Zeile vom 17. November 2026, 20:26 Uhr UTC, trägt eine Yahoo-Überschrift über erwartete Quartalszahlen und Colette Kress als interimistische Gastgeberin. `wirkung_1` ist etwa -3,30 Prozent. `wirkung_5` und der Indexvergleich fehlen. Daraus folgt keine Ursache. Andere NVIDIA-Überschriften in der Datenbank sind unbestätigt und dürfen nicht als Personalentscheidung über Jensen Huang ausgegeben werden.
6. Dieselbe Ereignisart am selben Tag soll nicht doppelt zählen. Zehn Artikel über dasselbe Ereignis sind damit nicht als ein geprüftes Ereignis-Cluster nachgewiesen, nur als Regel auf dem Schlüssel.
7. Verspätete Meldungen, mehr als sechs Stunden nach `zeit`, dürfen lokal nicht als damals bekannt gelten. Das ist eine Regel, keine gemessene Marktstudie.
8. Makro fehlt. Es gibt keine gespeicherte Reihe für Zinsen, Inflation, Arbeitsmarkt, Einkaufsmanagerindizes, Wechselkurse oder einen Wirtschaftskalender.
9. Kapitalströme fehlen. Volumen in den Kerzen ist keine Messung von Short Interest, ETF-Flüssen, Insiderdaten, Put/Call oder VIX.
10. Branche und Lieferkette fehlen. Der Hinweis NVIDIA auf AMD und AVGO ist eine feste Liste für Chip-, KI-, Produkt- und Personal-Ereignisse, keine Messung.
11. Technik rechnet RSI, MACD, Durchschnitte und Muster. Daraus ist keine validierte Prognose geworden.
12. Die sechs Bereiche werden lokal nur als Status gezeigt: vorhanden, fehlend, Fehler oder nicht validiert. Sie werden nicht zu einer Note addiert und ersetzen kein Modell.
13. Die Prognose-Tabelle ist leer. `empfehlung()` gibt im lokalen Code immer „keine ausreichende Datenbasis“ zurück. Kein Horizont hat 108 zeitlich getrennte Fälle mit bestandener Brier-, Log-Loss- und Kalibrierungsprüfung.
14. Die Trader haben keine abgeschlossene Paper-Position. Ohne Abschluss gibt es keinen Lernkandidaten. Skip und Hold zählen nicht. Kein Trader hat eine Strategie freigegeben.
15. Die Meta-AI bildet keine Mehrheit und setzt keine Gewichte. Sie kennt auch nicht, welcher Trader welche Nachrichtenkategorie kann. Dafür fehlen abgeschlossene Fälle.
16. Kosten sind Annahmen. Ein richtiger Richtungsruf wäre kein nachgewiesener Gewinn nach Spread, Slippage und Lücke.
17. Kurse sind verzögert, nicht Echtzeit. Intraday nach einer Meldung ist nicht gespeichert. Historische Wechselkurse für alte Umrechnungen sind nicht als eigene Reihe nachgewiesen.
18. Lernen läuft nur, solange der Mac die Runde ausführt. Aus ist kein Training.
19. Die Oberfläche lädt das HTML beim Start des Fensters einmal. Ein späteres Speichern der Seite ist ohne Neustart nicht sichtbar.
20. Das Universum ist eine lokale Liste, keine vollständige Börse. Suchreste und Restkürzel bleiben Namen, bis eine Quelle sie führt. Ein geöffnetes Symbol legt keinen Bestand an.
21. Die Benchmark ist nur DAX für `.DE` und S&P 500 für US-Titel. Ein fremder Index gibt eine Prüfung nicht frei. Krypto hat keine freigegebene Benchmark-Gewichtung.
22. Gleichzeitige Meldungen, schon laufende Kurse vor der Veröffentlichung und eingepreiste Erwartungen sind nicht als vollständige Event-Study umgesetzt. Der Satz „Wahrscheinlicher Einfluss“ wird bewusst nicht verwendet.

## Wonach du im veröffentlichten Code suchen sollst

Prüfe auf GitHub den Commit, der diese Datei enthält, und den Code, der wirklich in dem Commit liegt. Melde eine Schwäche nur mit Datei und konkreter Stelle oder mit einer der Zahlen oben.

Suche besonders nach:

- stillen Erfolgen, wenn eine Quelle fehlschlägt
- Prognosen oder Wahrscheinlichkeiten ohne `validiert`
- Käufen aus Nachrichten oder aus der Meta-AI
- Look-ahead, also Kursen oder Kennzahlen nach dem Entscheidungszeitpunkt
- vermischten Horizonten im alten `ki.py`
- Risikogrenzen, die nur einmal je Runde geprüft werden
- Anzeigen, die fehlende Daten als null, neutral oder Erfolg darstellen
- Tests, die eine Funktion aufrufen, aber keine Marktaussage prüfen
- Dokumentation, die neuer ist als der veröffentlichte Code

Wenn du eine Schwäche nicht im Commit siehst, schreibe „im veröffentlichten Stand nicht geprüft“ statt sie zu erfinden.

## Was weiterhin nicht gilt

Kein Trader hat gelernt. Kein Horizont ist validiert. 1.556 alte Beispiele und 151 neue Trainingszeilen sind keine Trefferquote. Spread und Slippage sind nicht gemessen. Die Meta-AI gewichtet nicht. Es wird kein echtes Geld gehandelt.
