#!/bin/bash
cd "$(dirname "$0")" || exit 1
echo "MarktRadar öffnet sich. Dieses Terminal kannst du offen lassen."
echo "Beenden: Fenster schließen oder Ctrl+C."
exec python3 beobachter.py
