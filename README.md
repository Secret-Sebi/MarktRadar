# MarktRadar

Lokales Kursprogramm für diesen Mac. Es kauft nichts und verbindet sich mit keinem Broker.

Das Fenster lädt seine Seite von einem Programm auf diesem Mac, nur unter `127.0.0.1`. Das ist kein Server im Internet. `daten/markt.sqlite` bleibt lokal und wird nicht ins Repository gelegt. Die ausführbare Datei `fenster_app/Beobachter.app` wird neu gebaut, wenn `Beobachter.swift` neuer ist.

## Start

```bash
python3 beobachter.py
```

Oder `MarktRadar.command` doppelklicken. Die Liste zeigt Namen, Preis, Quelle und Zeitpunkt. Eine Empfehlung, was zu prüfen oder zu verkaufen ist, gibt es nicht. Links bleibt ein Gespräch. Es antwortet nur aus den geladenen Kursen.

```bash
python3 beobachter.py --terminal
python3 beobachter.py --einmal
python3 -m unittest
```

## Daten

Jeder Kurs zeigt Quelle, Art, Status, Kurszeit, Währung und Handelsplatz. Liegt ein zweiter echter Preis in derselben Währung vor, steht die Abweichung dazu. Fehlt der zweite Preis, steht „Abgleich fehlt“.

- **Yahoo Finance** ist die erste Quelle für Aktien, ETFs, Indizes und Krypto. Das ist ein verzögerter Chart-Abruf, kein Echtzeit-Feed und nicht der Preis in Trade Republic. Endpunkt: `query1.finance.yahoo.com/v8/finance/chart`.
- **Stooq** liefert tägliche Schlusskurse, wenn Yahoo für eine Aktie oder einen ETF ausfällt. Endpunkt: `stooq.com/q/d/l/?s=…&i=d`. Die Datei enthält keine Währung und keine Splits. Deshalb gibt es daraus kein Einstiegssignal.
- **CoinGecko** ist die Ersatzquelle für `…-USD`-Paare, in Euro. Genutzt werden `/simple/price?vs_currencies=eur` und `/coins/{id}/market_chart?vs_currency=eur`. Ohne Schlüssel gilt das öffentliche Limit von ungefähr 5 Abrufen pro Minute. Ein optionaler Schlüssel kommt aus `COINGECKO_API_KEY` und wird als `x-cg-demo-api-key` gesendet. Auch diese Kurse erzeugen kein Einstiegssignal.
- Krypto wird zuerst als Euro-Paar bei Yahoo gefragt (`BTC-EUR` für `BTC-USD`). Dollar, Pfund und andere Währungen werden mit dem aktuellen Yahoo-Wechselkurs `{Währung}EUR=X` in Euro umgerechnet. Fehlt der Wechselkurs, bleibt die Ursprungswährung stehen. Das ist nicht der Preis in Trade Republic.

Fehlt eine verlässliche Reihe, bleibt der Status `Daten unvollständig` oder `veraltet`. Das Programm setzt dann kein Signal „Einstieg prüfen“ und keinen Sparplan-Hinweis.

Alpha Vantage ist nicht angebunden. Dafür wäre ein eigener Schlüssel und das Tageslimit der Gratisstufe nötig. Lege den Schlüssel nicht in den Code.

## Suche

Im Fenster filtert das Suchfeld die geladenen Karten. **Kürzel suchen** fragt Yahoo und CoinGecko. Ein Treffer wird an `watchlist.txt` angehängt. Vorhandene Zeilen und Kommentare bleiben. Die alte Grenze von 48 Kürzeln gilt nicht mehr.

## Lernen aus Nachrichten

Oben in der Liste steht, wie viele Fälle abgeschlossen sind und was für eine Trefferquote noch fehlt. Darunter die drei Meldungen mit der größten späteren Kursbewegung, umschaltbar auf Tag oder Woche, mit den Namen aus der Überschrift. Ohne 5 spätere Handelstage heißt es, dass der Einfluss fehlt.

Nachrichten kommen von Yahoo Finance und GDELT, aber höchstens alle 30 Minuten pro Kürzel. Gespeichert wird etwa vier Monate zurück, plus der Kurs an den Tagen danach. Yahoo liefert nur die neuesten Meldungen, der längere Rückblick kommt von GDELT. Namen ohne diesen Abruf kommen vor den schon gespeicherten, bis zu 80 pro Runde, mit kürzerer Pause, solange welche fehlen. Eine einzelne Überschrift ist kein Grund und keine Wiederholungsregel. Eine Meldung wird nur zugeordnet, wenn Kürzel oder Name in der Überschrift stehen. Geht der Vergleichsindex an dem Tag ähnlich, steht das am Namen. Eine Schlagzeile ohne den Firmennamen wird trotzdem keiner Aktie angehängt. Eine Branchenwirkung wird nicht geschätzt. Das Programm merkt sich Überschrift, Quelle, Zeitpunkt und Link in der lokalen Datei `daten/markt.sqlite`. Liegt der Vergleichsindex vor, wird die Bewegung nach fünf Handelstagen auch gegen diesen Index gerechnet. Das bleibt ein zeitlicher Zusammenhang, keine Ursache.

Sobald fünf spätere Handelstage als echte Kurse vorliegen, speichert es die Bewegung nach 1, 3, 5 und 20 Handelstagen. Kurse vor der Meldung zählen nicht. Beim nächsten Durchlauf fließt der neue Fall in den Median ein. Ab acht Fällen und einem Median von mindestens minus 1 % nach fünf Handelstagen wird aus „Einstieg prüfen“ oder „Sparplan“ ein „Abwarten“. Ein positives Muster erzeugt kein Kaufsignal.

Unter acht Fällen oder ohne spätere Kurse bleibt der technische Hinweis stehen, mit dem Vermerk „kleine Stichprobe“ oder dass die Wirkung noch fehlt. Das ist ein Zusammenhang, keine Ursache.

Zusätzlich zieht ein logistisches Modell seine Gewichte nach. Es sieht nur Kurse vor der Meldung, den RSI, ob der Kurs über der 20-Tage-Linie liegt, und sechs Schlagwort-Themen. Es lernt, ob der nächste Handelstag höher schloss, sobald dieser Tag vorliegt. Unter 60 ausgewerteten Handelstagen bleibt das eine kleine Stichprobe und ändert keinen Vorschlag. Wird ein Name aus der eigenen Liste ungewöhnlich, kommt eine Mitteilung auf dem Mac. Eine Zahl aus wenigen Tagen ist kein Auftrag. Ein kurzes Fenster für die nächsten 1–3 Handelstage erscheint nur, wenn dieser Rücksetzer in den eigenen Kursen mindestens 8-mal vorkam und der Median nach 3 Handelstagen positiv war. Gemessen werden DAX, MDAX, S&P 500 und Nasdaq 100, plus die watchlist. Ein Name bleibt nur sichtbar, solange die Kurszeit jünger als 36 Stunden ist. Zuerst wird die eigene Liste gemessen. Ein Tag erscheint nur, wenn er für diesen Namen größer ist als an 9 von 10 eigenen Tagen. Ist das Fenster zu und der Mac wach, holt `python3 beobachter.py --nachholen` alle 30 Minuten eine Runde nach. Ausgeschaltet rechnet das Programm nicht.

Ein Kurs ohne Zeitpunkt gilt als unvollständig. Krypto, die älter als zwei Tage ist, gilt als veraltet, Aktien und ETFs nach zehn Tagen. Der Euro-Kurs nutzt nur den heutigen Wechselkurs. Die Prozente bleiben die der Originalwährung. Alte Stände sind keine historischen Eurokurse. Eine Meldung kann mehreren Namen gehören, wenn dieselbe URL gespeichert wird. Banken, Versicherungen und Immobilien bekommen keine positive Fundamentalnote. Weniger als fünf echte Kennzahlen ergeben keine Gesamtnote.

Unternehmenszahlen kommen nur, wenn Yahoo sie in `quoteSummary` liefert: KGV, Wachstum, Marge, Verschuldung, Free Cashflow, Dividende, Eigenkapitalrendite und Branche. Fehlende Felder bleiben leer. Ein Vergleich mit Wettbewerbern fehlt.

## Tests

```bash
python3 -m unittest
```
