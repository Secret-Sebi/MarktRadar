# Lernsystem

Stand: 24. November 2026.

## Analyse

`trainiere()` lernt je Horizont das Vorzeichen der später gemessenen Wirkung. Merkmale kommen aus Kursen vor der Meldung und aus der Nachrichtenklasse. Dieselbe Nachricht und derselbe Horizont erzeugen nur eine Zeile.

Ein vorhandenes Beispiel wird nicht ein zweites Mal in `schritt()` gegeben. Fehlen nur die Zielzeiten, werden sie nachgetragen. Ein Beispiel ohne rekonstruierbares Fenster bleibt ohne Zeiten und damit außerhalb der Prüfung.

Die Anzeige zählt trainierte Beispiele. Diese Zahl ist kein Lernanteil und keine Trefferquote.

## Trader

Ein Verkauf kann einen Fall in `ki_haendler_fall` schließen. `_lerne` speichert höchstens einen Kandidaten. Die live Regel bleibt, bis `pruefe()` für genau diesen Trader besteht. Dafür braucht er 36 eigene Abschlüsse, eine zeitliche Trennung, einen gemessenen Benchmark und ein Ergebnis, das nach der Kostenannahme besser ist als die bisherige Regel.

Die Kostenannahme ist 0,125 Prozent je Seite. Spread und Slippage stehen als „nicht gemessen“.

36 Abschlüsse sind der Beginn einer Prüfung, keine Freigabe.

## Was Lernen hier nicht ist

Feste RSI-, MACD- und Trendregeln laufen auch ohne bestandene Prüfung. Das ist Ausführung gespeicherter Regeln, kein Nachweis, dass die Regel dazugelernt hat. Eine neue Variante wird nicht automatisch eingesetzt.
