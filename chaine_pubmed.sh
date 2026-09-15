#!/bin/bash
# Abstracts PubMed/PDP des entites hpoa -> signes (35B, verbatim = phrase de l'abstract)
# -> mapping deterministe hp.obo -> matrice (livre='pubmed', 3e etage de preuve)
# -> entites hpoa reposees (build_syndrome_hpo_livres DROP la table) -> fiches.
# Rejouable : l'extraction saute ce qui est deja en table.
set -u
cd /home/mathevet/Bureau/foeto_base
PY=/home/mathevet/Bureau/venv/bin/python
LOG=logs_chaine_pubmed.log
cp syndromes_foetaux.db syndromes_foetaux.db.bak-$(date +%Y%m%d-%H%M)-pubmed
{
echo "=== $(date) extraction pubmed"
$PY -u extract_signes_livres.py --livre pubmed
echo "=== $(date) mapping"
$PY map_signes_hpo_obo.py --apply | tail -6
$PY decoupe_composites.py --apply | tail -2
$PY map_signes_hpo_regles.py --apply | tail -3
$PY applique_arbitrages.py --apply
$PY -u nomme_signes_hpo.py --apply | tail -2
$PY resout_fragments.py --apply | head -1
echo "=== $(date) reconstruction"
$PY build_syndrome_hpo_livres.py --apply | tail -1
$PY add_entites_hpoa.py --apply | tail -1
$PY build_entites_livres.py | head -1
$PY build_parente_livres.py | head -1
$PY temoin_appendice_smith.py | head -1
$PY build_syndrome_foeto_livres.py | head -1
$PY render_fiche_entite.py --all /home/mathevet/Bureau/fiches_lecture/syndromes_entites/ | tail -1
sqlite3 syndromes_foetaux.db "select 'pubmed : '||count(*)||' liens, '||count(distinct syndrome_id)||' entités' from syndrome_hpo_livres where livre='pubmed'"
./backup_bases.sh | tail -2
echo "=== $(date) fin"
} >> $LOG 2>&1
cd /home/mathevet/Bureau/tmux_supervisor/embeddings/pipeline_v2 && $PY - <<'PY'
import sys; from pathlib import Path
sys.path.insert(0, "."); import importlib; n = importlib.import_module("08_notify")
log = Path("/home/mathevet/Bureau/foeto_base/logs_chaine_pubmed.log").read_text()
n.send_email("Chaîne PubMed — abstracts hpoa dans la matrice (livre=pubmed), reconstruction", log[-8000:], n.SMTP_USER)
PY
