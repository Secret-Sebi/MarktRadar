# Modellvalidierung

Stand: 24. November 2026.

Die Freigabe bleibt `ki_pruefung.pruefe_faelle()`: 36 Training, 36 Validierung, 36 Test, Purging über die gespeicherten Zielzeiten, Walk-forward, Brier und Log-Loss gegen die konstante Basis, Kalibrierung mit Abstand 0,15.

`prognose_vergleich.py` hängt denselben Fällen einen Vergleich an. Er öffnet den Test nicht zusätzlich. Momentum kann die Validierung schlagen und bleibt trotzdem gesperrt.

Die gespeicherten Horizonte der echten Datenbank sind nicht neu bewertet worden. Ihre alten Berichte enthalten den Vergleich noch nicht.
