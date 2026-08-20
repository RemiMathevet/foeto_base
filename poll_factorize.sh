#!/bin/bash
# Attend la fin du batch de factorisation, collecte, et notifie par mail.
#   nohup ./poll_factorize.sh > poll_factorize.log 2>&1 &
set -u
cd "$(dirname "$0")"
source ~/Bureau/venv/bin/activate
NOTIFY=~/Bureau/tmux_supervisor/embeddings/pipeline_v2/08_notify.py
MARKER=.factorize_done

while true; do
    OUT=$(python -u factorize_terms.py status 2>&1)
    echo "$(date '+%F %T') $OUT"
    case "$OUT" in
        *ended*) break ;;
    esac
    sleep 120
done

python -u factorize_terms.py collect 2>&1 | tee .factorize_collect.txt
touch "$MARKER"

python -u "$NOTIFY" \
    --subject "FOETO — factorisation placenta terminée (662 termes)" \
    --body "$(cat .factorize_collect.txt)" \
    --to remimathevet@gmail.com \
    --attach factorisation.tsv vocabulaire_facettes.txt
