# Datenqualität

Stand: 24. November 2026.

## Kurse

Yahoo ist die erste Quelle, Stooq der Ersatz. Krypto kommt von CoinGecko, Euro zuerst. Ein fehlender Kurs wird nicht als 0 gespeichert. Negative Schlüsse werden verworfen.

Wechselkurse historischer Balken kommen aus dem letzten Kurs, der nicht nach dem Balken liegt und nicht älter als vier Kalendertage ist. Ein einzelner Tageskurs schreibt die historische Reihe nicht in Euro um. GBp und GBX werden einmal durch 100 geteilt. Ob das schon geschehen ist, merkt eine lokale Variable, nicht ein deutscher Hinweistext. Fehlt der Euro-Kurs, bleibt die Währung Pfund.

## Zeit

Nachrichtenzeit, Kurszeit und Erfassungszeit sind verschiedene Felder, wo sie existieren. `ziel_von` ist der erste Balken ab der Meldung. `ziel_bis` ist der Balken nach 1, 3, 5 oder 20 vorhandenen Schlüssen. Wochenenden und fehlende Tage zählen nicht extra, weil sie keine Balken sind. Es gibt keinen eigenen Feiertagskalender.

## Zielzeiten alter Zeilen

Zeilen ohne `ziel_von` und `ziel_bis` trainieren nicht erneut. `trainiere()` trägt die Zeiten nach, wenn die übergebene Reihe denselben Balkenabstand wie `wirkung()` ergibt. Ist das Ende noch nicht da, bleiben die Felder leer. Die Prüfung liest solche Zeilen nicht. Es werden keine Zeiten geschätzt.

## Was fehlt

Splits und Dividenden werden nicht als eigene Kapitalmaßnahmen geführt. Makroreihen, Branchenindizes, Short Interest und Optionsflüsse sind nicht gespeichert. `einfluss.py` zeigt diese Lücken als fehlend.

Ein Fallback darf keinen ungeprüften Ersatzkurs liefern. Wenn Yahoo und Stooq sich widersprechen, gewinnt nicht still der zweite Wert: der Ersatz wird nur benutzt, wenn die erste Quelle fehlschlägt, und der Datenstatus bleibt an der gelieferten Qualität hängen.
