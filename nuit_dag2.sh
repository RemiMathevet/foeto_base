#!/bin/bash
# Suite de nuit_dag.sh (attend sa fin) : re-embarquer les blocs SIGNES dans les HTML V2
# + autotests + commit local ; score famille du banc ; copie sur les deux Toshibas ; mail.
set -u
PY=/home/mathevet/Bureau/venv/bin/python
LOG=/home/mathevet/Bureau/foeto_base/logs_nuit_dag2.log
while ps -p 3798622 >/dev/null 2>&1; do sleep 60; done
{
echo "=== $(date) embarquement HTML"
cd /home/mathevet/Bureau/foeto_base && $PY embed_signes_html.py
cd /home/mathevet/Bureau/Hub_HTML && node verif.js autopsie.html | tail -1 && node verif.js examen_clinique.html | tail -1
git add autopsie.html examen_clinique.html && git commit -qm "Blocs SIGNES régénérés après la nuit DAG (noms HPO, appendice de Smith)

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01Ro8P4ccGEJLNgBgBJydK2N" && git log --oneline -1
echo "=== $(date) score famille"
cd /home/mathevet/Bureau/benchmark_foeto && $PY rescore_famille.py
echo "=== $(date) copie Toshibas"
/home/mathevet/Bureau/foeto_base/backup_bases.sh
echo "=== $(date) fin"
} >> $LOG 2>&1
cd /home/mathevet/Bureau/tmux_supervisor/embeddings/pipeline_v2 && $PY - <<'PY'
import sys; from pathlib import Path
sys.path.insert(0, "."); import importlib; n = importlib.import_module("08_notify")
log = Path("/home/mathevet/Bureau/foeto_base/logs_nuit_dag2.log").read_text()
n.send_email("Nuit DAG (2) — HTML ré-embarqués, score famille, copie Toshibas", log[-6000:], n.SMTP_USER)
PY
