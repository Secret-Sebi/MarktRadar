# Paper-Trader

Stand: 24. November 2026. TEILWEISE IMPLEMENTIERT.

Die Trader in `haendler.py` haben unterschiedliche feste Regeln, eigene Fälle und eine eigene Positionsgrenze. Mehrere Regeln kaufen absichtlich nicht, weil Nachricht, Fundamentalzahl oder Volumen keine Kaufnote sind.

Ein Abschluss kann einen Kandidaten speichern. Die live Regel bleibt, bis `pruefe()` für genau diesen Trader besteht. Dafür fehlen 36 eigene Abschlüsse. Ein Kandidat überschreibt die Historie nicht.

`aktion_aus_ki()` gibt die ursprüngliche Aktion zurück. Eine nicht geprüfte Prognose steuert keinen Trader.

Nicht implementiert: ein Trader, der selbst eine neue Strategie sucht, Parameter ausprobiert und sie ohne die bestehende Prüfung einsetzt. Das bleibt offen, weil unkontrolliertes Suchen den Test verbrauchen würde.
