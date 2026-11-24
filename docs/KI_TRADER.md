# KI-Trader

Stand: 24. November 2026.

## Was eigenständig ist

Jeder Eintrag in `haendler.py` hat eine eigene Regel, einen eigenen Namen und eigene Zeilen in `ki_haendler_fall`. Die Positionsgrenze von 10 offenen Fällen und 3 Käufen je Runde gilt je Trader. Die Anzeige zählt abgeschlossene und offene Fälle je `haendler`.

Aktienregeln und Kryptoregeln kaufen nicht im jeweils anderen Universum. Nachrichten-, Fundamental- und mehrere Markregeln kaufen nicht. Ihr Text sagt, dass die Kennzahl oder die Meldung kein Kaufgrund ist.

## Was nicht eigenständig ist

Die Regeln sind fest im Code. Ein Trader erzeugt keine neue Strategie, testet sie nicht historisch und ersetzt nicht selbst seine Regel. Ein Kandidat in `ki_haendler_version` ist nicht eingesetzt.

`aktion_aus_ki()` löscht die übergebenen Modellwerte und gibt die ursprüngliche Aktion zurück. Das ist Absicht, solange kein Horizont freigegeben ist. Eine nicht geprüfte Wahrscheinlichkeit darf die Regel und die Risikogrenzen nicht überschreiben.

## Risikogrenzen

Weiterhin gilt: 1 Prozent geplantes Risiko, 10 Prozent Positionsgröße, 10 offene Positionen je Trader, 2 Prozent Tagesverlust, Pause bei 8 Prozent Drawdown, 10 Prozent Cash. Kein Hebel, keine Optionen, kein Live-Auftrag. Diese Zahlen wurden nicht verändert.

## Letzter gemessener Stand der Fälle

Am 24. November 2026, gelesen aus der laufenden Statusschnittstelle: Experiment 0/10, MACD 2/8, Momentum 0/4, RSI 0/11, Statistik 0/2, Trend 0/5, jeweils abgeschlossen/offen. Keiner kann die unabhängige Prüfung starten. Die 11 offenen RSI-Fälle wurden nicht gelöscht.
