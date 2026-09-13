#!/bin/bash
# Reprise du ReAct HPO (crash KeyError sur un id obsolete au lot 16, recherche par racines
# et appariement par phrase corriges) APRES la nuit d'arbitrage : MAGOS n'a qu'un slot.
cd /home/mathevet/Bureau/foeto_base
PY=/home/mathevet/Bureau/venv/bin/python
while kill -0 212515 2>/dev/null; do sleep 120; done
# on rejoue TOUT : les 15 lots d'avant le crash avaient des index decales
sqlite3 syndromes_foetaux.db "update syndrome_signes_livres_candidats set hpo_id=null, hpo_portee=null, hpo_methode=null where hpo_methode='react_hpo'; delete from signes_fragments where modele like 'react_hpo%'"
$PY -u react_hpo.py --apply > logs_react_hpo.log 2>&1
./suite_arbitrage.sh 999999999
