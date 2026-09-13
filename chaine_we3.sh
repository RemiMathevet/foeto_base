#!/bin/bash
# Ordre corrige (Remi, 13/09 17 h 40) : ReAct HPO D'ABORD (1 h, +5 000 mappings), puis la nuit
# d'arbitrage Next --tous qui juge AUSSI les choix ReAct, puis Kimi, application, reconstruction, mail.
cd /home/mathevet/Bureau/foeto_base
PY=/home/mathevet/Bureau/venv/bin/python
sqlite3 syndromes_foetaux.db "update syndrome_signes_livres_candidats set hpo_id=null, hpo_portee=null, hpo_methode=null where hpo_methode='react_hpo'; delete from signes_fragments where modele like 'react_hpo%'"
$PY -u react_hpo.py --apply > logs_react_hpo.log 2>&1
./nuit_arbitrage.sh
