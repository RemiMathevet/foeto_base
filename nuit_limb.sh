#!/bin/bash
# Troisieme livre dans la matrice : limb.pdf (98 entites, atlas des malformations des
# membres). Extraction 35B -> chaine de mapping deterministe (obo, composites, regles,
# noms LLM) -> ORPHA -> reconstruction complete -> mail.
set -u
cd /home/mathevet/Bureau/foeto_base
PY=/home/mathevet/Bureau/venv/bin/python
LOG=logs_nuit_limb.log
cp syndromes_foetaux.db syndromes_foetaux.db.bak-20260912-limb
{
echo "=== $(date) extraction limb"
$PY -u extract_signes_livres.py --livre limb
echo "=== $(date) mapping"
$PY map_signes_hpo_obo.py --apply | tail -6
$PY decoupe_composites.py --apply | tail -2
$PY map_signes_hpo_regles.py --apply | tail -3
$PY -u nomme_signes_hpo.py --apply | tail -2
echo "=== $(date) orpha + reconstruction"
$PY build_syndrome_hpo_livres.py --apply | tail -2
$PY map_orpha_livres.py --apply | tail -4
$PY add_orpha_manquants.py --apply | tail -3
$PY add_family_members.py --livres | tail -1
$PY build_syndrome_hpo_livres.py --apply | tail -1
$PY build_parente_livres.py | head -1
$PY temoin_appendice_smith.py | head -1
$PY build_syndrome_foeto_livres.py | head -1
$PY render_fiche_syndrome.py --all /home/mathevet/Bureau/fiches_lecture/syndromes/ | tail -1
$PY build_signes_examen.py > /home/mathevet/Bureau/Hub_HTML/signes_examen_clinique.js
$PY build_signes_autopsie.py > /home/mathevet/Bureau/Hub_HTML/signes_autopsie.js
$PY build_toggles_json.py | tail -1
$PY embed_signes_html.py
cd /home/mathevet/Bureau/Hub_HTML && node verif.js autopsie.html | tail -1 && node verif.js examen_clinique.html | tail -1
git add autopsie.html examen_clinique.html && git commit -qm "Blocs SIGNES après l'entrée de limb.pdf dans la matrice

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01Ro8P4ccGEJLNgBgBJydK2N" && git log --oneline -1
cd /home/mathevet/Bureau/foeto_base && ./backup_bases.sh | tail -2
echo "=== $(date) fin"
} >> $LOG 2>&1
cd /home/mathevet/Bureau/tmux_supervisor/embeddings/pipeline_v2 && $PY - <<'PY'
import sys; from pathlib import Path
sys.path.insert(0, "."); import importlib; n = importlib.import_module("08_notify")
log = Path("/home/mathevet/Bureau/foeto_base/logs_nuit_limb.log").read_text()
n.send_email("Nuit limb — 98 entités de limb.pdf dans la matrice, reconstruction", log[-7000:], n.SMTP_USER)
PY
