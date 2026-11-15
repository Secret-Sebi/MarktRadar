# MarktRadar

Lokales Kursprogramm für diesen Mac. Es kauft nichts und verbindet sich mit keinem Broker.

## Start

```bash
python3 beobachter.py
```

Oder `MarktRadar.command` doppelklicken.

```bash
python3 beobachter.py --terminal
python3 beobachter.py --einmal
python3 -m unittest
```

## Daten

Jeder Kurs zeigt Quelle, Art und Status.

- **Yahoo Finance** ist die erste Quelle für Aktien, ETFs, Indizes und Krypto. Das ist ein verzögerter Chart-Abruf, kein Echtzeit-Feed und nicht der Preis in Trade Republic. Endpunkt: `query1.finance.yahoo.com/v8/finance/chart`.
- **Stooq** liefert tägliche Schlusskurse, wenn Yahoo für eine Aktie oder einen ETF ausfällt. Endpunkt: `stooq.com/q/d/l/?s=…&i=d`. Die Datei enthält keine Währung und keine Splits. Deshalb gibt es daraus kein Einstiegssignal.
- **CoinGecko** ist die Ersatzquelle für `…-USD`-Paare, in Euro. Genutzt werden `/simple/price?vs_currencies=eur` und `/coins/{id}/market_chart?vs_currency=eur`. Ohne Schlüssel gilt das öffentliche Limit von ungefähr 5 Abrufen pro Minute. Ein optionaler Schlüssel kommt aus `COINGECKO_API_KEY` und wird als `x-cg-demo-api-key` gesendet. Auch diese Kurse erzeugen kein Einstiegssignal.
- Krypto wird zuerst als Euro-Paar bei Yahoo gefragt (`BTC-EUR` für `BTC-USD`). Dollar, Pfund und andere Währungen werden mit dem aktuellen Yahoo-Wechselkurs `{Währung}EUR=X` in Euro umgerechnet. Fehlt der Wechselkurs, bleibt die Ursprungswährung stehen. Das ist nicht der Preis in Trade Republic.

Fehlt eine verlässliche Reihe, bleibt der Status `Daten unvollständig` oder `veraltet`. Das Programm setzt dann kein Signal „Einstieg prüfen“ und keinen Sparplan-Hinweis.

Alpha Vantage ist nicht angebunden. Dafür wäre ein eigener Schlüssel und das Tageslimit der Gratisstufe nötig. Lege den Schlüssel nicht in den Code.

## Suche

Im Fenster filtert das Suchfeld die geladenen Karten. **Kürzel suchen** fragt Yahoo und CoinGecko. Ein Treffer wird an `watchlist.txt` angehängt. Vorhandene Zeilen und Kommentare bleiben. Die alte Grenze von 48 Kürzeln gilt nicht mehr.

## Lernen aus Nachrichten

Jeder Durchlauf holt Meldungen von Yahoo Finance und GDELT. Eine Meldung wird nur einem Kürzel zugeordnet, wenn die Überschrift dazu passt. Das Programm merkt sich Überschrift, Quelle, Zeitpunkt und Link in `daten/markt.sqlite`.

Sobald fünf spätere Handelstage als echte Kurse vorliegen, speichert es die Bewegung nach 1, 3, 5 und 20 Handelstagen. Kurse vor der Meldung zählen nicht. Beim nächsten Durchlauf fließt der neue Fall in den Median ein. Ab acht Fällen und einem Median von mindestens minus 1 % nach fünf Handelstagen wird aus „Einstieg prüfen“ oder „Sparplan“ ein „Abwarten“. Ein positives Muster erzeugt kein Kaufsignal.

Unter acht Fällen oder ohne spätere Kurse bleibt der technische Hinweis stehen, mit dem Vermerk „kleine Stichprobe“ oder dass die Wirkung noch fehlt. Das ist ein Zusammenhang, keine Ursache.

Zusätzlich zieht ein logistisches Modell seine Gewichte nach. Es sieht nur Kurse vor der Meldung und lernt, ob der Kurs fünf Handelstage später höher stand. Jeder abgeschlossene Fall wird einmal gelernt und in `ki_modell` gespeichert. Ab 12 Fällen nennt es eine Chance. Unter 35 % wird aus einem Einstieg ein Abwarten. Ab 65 % kann aus „Kein klarer Vorteil“ ein „Prüfen“ werden, aber nur bei vollständigen Kursdaten. Das ist keine Garantie und kein Chatmodell.

Fundamentaldaten sind weiterhin nicht angebunden.

## Tests

```bash
python3 -m unittest
```
