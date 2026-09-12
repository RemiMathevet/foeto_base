#!/bin/bash
# Nuit du 12 au 13 sept. : (1) noms HPO proposes par le 35B pour les signes non mappes,
# resolus par egalite exacte ; (2) re-extraction dirigee par l'appendice de Smith ;
# puis reconstruction matrice -> parente -> temoin -> micro -> fiches -> blocs HTML/hub.
set -u
cd /home/mathevet/Bureau/foeto_base
PY=/home/mathevet/Bureau/venv/bin/python
LOG=logs_nuit_dag.log
cp syndromes_foetaux.db syndromes_foetaux.db.bak-20260912-nuit
{
echo "=== $(date) nomme_signes_hpo"
$PY -u nomme_signes_hpo.py --apply
echo "=== $(date) temoin_reextraction"
$PY -u temoin_reextraction.py --apply
echo "=== $(date) reconstruction"
$PY build_syndrome_hpo_livres.py --apply | tail -4
$PY build_parente_livres.py | head -2
$PY temoin_appendice_smith.py | head -1
$PY build_syndrome_foeto_livres.py | head -1
$PY render_fiche_syndrome.py --all /home/mathevet/Bureau/fiches_lecture/syndromes/ | tail -1
$PY build_signes_examen.py > /home/mathevet/Bureau/Hub_HTML/signes_examen_clinique.js
$PY build_signes_autopsie.py > /home/mathevet/Bureau/Hub_HTML/signes_autopsie.js
$PY build_toggles_json.py | tail -1
echo "=== $(date) fin"
} >> $LOG 2>&1
cd /home/mathevet/Bureau/tmux_supervisor/embeddings/pipeline_v2 && $PY - <<'PY'
import sys, re; from pathlib import Path
sys.path.insert(0, "."); import importlib; n = importlib.import_module("08_notify")
log = Path("/home/mathevet/Bureau/foeto_base/logs_nuit_dag.log").read_text()
resume = "\n".join(l for l in log.splitlines() if l.startswith("===") or "signes repris" in l or "attestations retrouvées" in l or "syndrome_hpo_livres :" in l or "testables" in l or "entités" in l or "fiches ->" in l or "signes attestes" in l)
n.send_email("Nuit DAG — noms HPO, re-extraction appendice, matrice reconstruite", resume, n.SMTP_USER,
             attachments=[Path("/home/mathevet/Bureau/foeto_base/arbitrage_llm_nom.tsv")])
PY
