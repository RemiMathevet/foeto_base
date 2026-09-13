#!/bin/bash
# Nuit du 13 au 14/09 : arbitrage Next de TOUTES les lignes llm_nom sans choix (--tous,
# ~6 968 couples, ~5 h), puis suite_arbitrage.sh (Kimi sur les pas-surs, application,
# reconstruction, mail). Lancement differe : sleep jusqu'a l'heure passee en $1 (HH:MM).
cd /home/mathevet/Bureau/foeto_base
PY=/home/mathevet/Bureau/venv/bin/python
if [ -n "$1" ]; then
  while [ "$(date +%H:%M)" != "$1" ]; do sleep 30; done
fi
$PY -u arbitre_llm_nom.py --etape next --tous > logs_arbitre_next_tous.log 2>&1 &
NEXT=$!
./suite_arbitrage.sh $NEXT
