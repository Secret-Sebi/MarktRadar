# Monitoring

Stand: 24. November 2026. TEILWEISE IMPLEMENTIERT.

Kurs, Nachrichten und späterer Kurs haben getrennte Zustände. Ein Schritt ist nur „läuft“, wenn das Backend genau diesen Schritt meldet.

Die Lernanzeige zeigt die gespeicherte Prüfung. Fehlt die Validierung, bleiben die Testzahlen leer. Der Modellvergleich hängt an diesem Bericht und gibt zusätzlich an, dass nichts freigegeben ist, solange die Prüfung nicht besteht.

Nicht implementiert: Feature-Drift, automatischer Rollback eines freigegebenen Modells und eine Alarmliste außerhalb des bestehenden Status. Ein freigegebenes Modell gibt es derzeit nicht, daher ist kein Rollback ausgeführt worden.
