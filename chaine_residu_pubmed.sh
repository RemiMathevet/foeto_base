#!/bin/bash
# Residu non mappe des abstracts PubMed : histologie -> circuit micro (FOETO), parapluies,
# nommage 35B, ReAct HPO 35B (pas de Next : on juge le residu apres), matrice, fiches.
set -u
cd /home/mathevet/Bureau/foeto_base
PY=/home/mathevet/Bureau/venv/bin/python
LOG=logs_residu_pubmed.log
SCR=/tmp/claude-1000/-home-mathevet-Bureau/4f13eb96-cacc-4def-a641-1e1fb51bae36/scratchpad
cp syndromes_foetaux.db syndromes_foetaux.db.bak-$(date +%Y%m%d-%H%M)-residu
{
echo "=== $(date) micro"
$PY route_micro_pubmed.py --apply | tail -1
$PY map_micro_foeto.py $SCR/micro_tout.tsv | tail -2
$PY - <<'PYEOF'
import csv
rows = list(csv.DictReader(open("/tmp/claude-1000/-home-mathevet-Bureau/4f13eb96-cacc-4def-a641-1e1fb51bae36/scratchpad/micro_tout.tsv", encoding="utf-8"), delimiter="\t"))
pm = [r for r in rows if r["livre"] == "pubmed"]
with open("/home/mathevet/Bureau/foeto_base/arbitrage_micro_pubmed.tsv", "w", encoding="utf-8", newline="") as f:
    w = csv.DictWriter(f, fieldnames=rows[0].keys(), delimiter="\t"); w.writeheader(); w.writerows(pm)
print(f"arbitrage_micro_pubmed.tsv : {len(pm)} signes micro d'abstracts, {sum(1 for r in pm if r['choix'])} choix pré-remplis (exact)")
PYEOF
echo "=== $(date) regles + arbitrages"
$PY map_signes_hpo_regles.py --apply | tail -3
$PY applique_arbitrages.py --apply
echo "=== $(date) nommage 35B"
$PY -u nomme_signes_hpo.py --apply | tail -2
$PY resout_fragments.py --apply | head -1
echo "=== $(date) ReAct HPO 35B"
$PY -u react_hpo.py --apply | tail -3
echo "=== $(date) reconstruction"
$PY build_syndrome_hpo_livres.py --apply | tail -1
$PY add_entites_hpoa.py --apply | tail -1
$PY build_entites_livres.py | head -1
$PY build_parente_livres.py | head -1
$PY temoin_appendice_smith.py | head -1
$PY build_syndrome_foeto_livres.py | head -1
$PY render_fiche_entite.py --all /home/mathevet/Bureau/fiches_lecture/syndromes_entites/ | tail -1
sqlite3 syndromes_foetaux.db "select 'pubmed : '||count(*)||' liens, '||count(distinct syndrome_id)||' entités' from syndrome_hpo_livres where livre='pubmed'; select 'résidu pubmed non mappé : '||count(*)||' occurrences, '||count(distinct lower(signe))||' libellés' from syndrome_signes_livres_candidats where livre='pubmed' and verbatim_ok=1 and hpo_id is null and (hpo_methode is null or hpo_methode='')"
echo "=== $(date) fin"
} >> $LOG 2>&1
cd /home/mathevet/Bureau/tmux_supervisor/embeddings/pipeline_v2 && $PY - <<'PY'
import sys; from pathlib import Path
sys.path.insert(0, "."); import importlib; n = importlib.import_module("08_notify")
log = Path("/home/mathevet/Bureau/foeto_base/logs_residu_pubmed.log").read_text()
n.send_email("Résidu PubMed — micro routé, règles, nommage + ReAct 35B, reconstruction", log[-6000:], n.SMTP_USER,
             attachments=[Path("/home/mathevet/Bureau/foeto_base/arbitrage_micro_pubmed.tsv")])
PY
