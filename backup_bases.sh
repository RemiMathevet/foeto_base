#!/bin/bash
# Copie des bases (HPO, FOETO, syndromes, RAG) et de tout le travail vers les deux
# Toshibas : /media/toshibaN/Base_backup/ (miroir rsync, jamais de --delete ; les
# .bak-* de la DB et les venv restent hors copie). Ne lit rien sous SAUVEGARDE_2024.
set -u
SRC=/home/mathevet/Bureau
DIRS="foeto_base Embedding_RAG_V2 HPO_Foeto/P620/hpo_data akinator fiches_lecture Hub_HTML foetodata_hub benchmark_foeto magos tmux_supervisor/embeddings/pipeline_v2 tmux_supervisor/magos"
EXCL="--exclude=venv --exclude=__pycache__ --exclude=*.bak-* --exclude=*.bak_* --exclude=node_modules --exclude=*.pyc --exclude=.canon_* --exclude=graphify-out --exclude=outputs --exclude=syndromes_foetaux_dead.db*"
for T in /media/toshiba1 /media/toshiba2; do
  [ -d "$T" ] || { echo "$T absent"; continue; }
  D="$T/Base_backup"; mkdir -p "$D"
  for d in $DIRS; do
    mkdir -p "$D/$d"
    rsync -a $EXCL "$SRC/$d/" "$D/$d/" 2>&1 | tail -1
  done
  # instantane date de la base de syndromes (la seule qui bouge chaque jour)
  mkdir -p "$D/snapshots"
  cp "$SRC/foeto_base/syndromes_foetaux.db" "$D/snapshots/syndromes_foetaux_$(date +%Y%m%d).db"
  echo "$(date) $T : $(du -sh "$D" | cut -f1)" | tee -a "$D/journal.txt"
done
