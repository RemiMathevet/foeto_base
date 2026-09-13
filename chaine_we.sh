#!/bin/bash
# Heures creuses du week-end (Rémi, 13/09 17 h) : ReAct HPO local sur les ~7 258 signes,
# puis directement la nuit d'arbitrage (Next --tous, Kimi, application, reconstruction, mail).
cd /home/mathevet/Bureau/foeto_base
PY=/home/mathevet/Bureau/venv/bin/python
$PY -u react_hpo.py --apply > logs_react_hpo.log 2>&1
./nuit_arbitrage.sh
