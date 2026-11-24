# Forecasting

Stand: 24. November 2026. TEILWEISE IMPLEMENTIERT.

## Was läuft

`trainiere()` speichert je Horizont 1, 3, 5 und 20 ein Beispiel mit Merkmalen, Ziel und Zielzeit. `pruefe_faelle()` trennt Training, Validierung und Test. `prognose_vergleich.vergleiche()` misst auf derselben Trennung drei Regeln:

- konstant: die Trefferquote des Trainings
- momentum: getrennte Trefferquoten, je nachdem ob der letzte Schluss über dem 20-Tage-Schnitt lag
- logistisch: das vorhandene Online-Modell

Der Test einer Regel wird nur gemessen, wenn diese Regel die konstante Basis in der Validierung schlägt und die Prüfung den Test bereits geöffnet hat. `freigegeben` im Vergleich wird nur für die Logistik wahr, und nur wenn `pruefe_faelle()` selbst besteht. Momentum und die Konstante werden nie freigegeben.

`prognose.py` legt Zeilen an und lässt die Wahrscheinlichkeiten leer. Die Empfehlung bleibt `KEINE AUSREICHENDE DATENBASIS`.

## Was nicht läuft

Random Forest, Gradient Boosting und neuronale Netze sind nicht implementiert. `sklearn`, XGBoost und LightGBM sind nicht installiert. Es wird kein Modell daraus vorgetäuscht.

Makro, Branche und Kapitalströme fehlen weiterhin. Nachrichten bleiben Schlüsselwortklassen und sind keine belegte Ursache.

Kein Horizont der echten Datenbank ist durch diesen Vergleich neu geprüft oder freigegeben worden.
