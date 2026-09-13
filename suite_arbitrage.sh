#!/bin/bash
# Suite de la passe Next (arbitre_llm_nom --etape next) : second avis externe sur les
# « pas sûrs », application des choix, reconstruction, mail. Attend le PID de la passe Next.
cd /home/mathevet/Bureau/foeto_base
PY=/home/mathevet/Bureau/venv/bin/python
ATTEND=$1
while kill -0 "$ATTEND" 2>/dev/null; do sleep 60; done
eval "$(grep '^export OPENROUTER_API_KEY=' ~/.bashrc)"
{
# Second avis : plus Kimi (14/80 tranchés, noms hors HPO) — le relecteur (Claude) avec
# l'index sous la main, le lendemain, sur arbitrage_openrouter.tsv (Rémi, 13/09 19 h).
echo "=== $(date) pas-sûrs de Next -> arbitrage_openrouter.tsv, relecture Claude le lendemain"
echo "=== $(date) application + reconstruction"
$PY applique_arbitrages.py --apply
$PY build_syndrome_hpo_livres.py --apply | tail -1
$PY build_entites_livres.py | head -1
$PY build_parente_livres.py | head -1
$PY temoin_appendice_smith.py | head -1
$PY render_fiche_syndrome.py --all /home/mathevet/Bureau/fiches_lecture/syndromes/ | tail -1
$PY render_fiche_entite.py --all /home/mathevet/Bureau/fiches_lecture/syndromes_entites/ | tail -1
echo "=== $(date) fin"
} >> logs_arbitrage.log 2>&1
$PY - <<'PYEOF'
import sys; sys.path.insert(0, "/home/mathevet/Bureau/tmux_supervisor/embeddings/pipeline_v2")
import os; os.chdir("/home/mathevet/Bureau/tmux_supervisor/embeddings/pipeline_v2")
import importlib; n = importlib.import_module("08_notify")
from pathlib import Path
log = Path("/home/mathevet/Bureau/foeto_base/logs_arbitrage.log").read_text()
nx = max(Path("/home/mathevet/Bureau/foeto_base").glob("logs_arbitre_next*.log"), key=lambda p: p.stat().st_mtime).read_text()
n.send_email("Arbitrage llm_nom — Next puis avis externe, reconstruction", nx[-3000:] + "\n\n" + log[-5000:], n.SMTP_USER,
             attachments=[Path("/home/mathevet/Bureau/foeto_base/arbitrage_openrouter.tsv")])
PYEOF
