#!/usr/bin/env python3
"""Relève dans foeto_genes les gènes cités par un terme FOETO (2026-09-28).

Textes lus : description_fr, libellés, et verbatims de livres (foeto_verbatims).
Un symbole n'est retenu que s'il existe tel quel dans la table genes (4 552 symboles
officiels) — jamais un sigle quelconque en majuscules. Exclus : marqueurs d'IHC et
homonymes relevés à la main (GFAP, APP, secteurs CA1–4 de la corne d'Ammon, MADD
= acronyme de maladie), et toute mention dans un contexte d'immunomarquage.
Idempotent (clé foeto_id + gene_symbol). Écrit : foeto_genes (source description|verbatim).

  python3 v2/genes_des_textes.py              # simulation
  python3 v2/genes_des_textes.py --appliquer
"""
import re
import sqlite3
import sys
from pathlib import Path

DB = Path(__file__).parent.parent / "syndromes_foetaux.db"
EXCLUS = {"GFAP", "APP", "CA1", "CA2", "CA3", "CA4", "MADD"}
# contexte (60 car. autour) où un symbole désigne un marqueur ou autre chose qu'un gène en cause
CONTEXTE_EXCLU = re.compile(r"immuno|IHC|\bPLAP\b|lymphoïde associé", re.I)
TOK = re.compile(r"\b[A-Z][A-Z0-9]{2,}(?:-[A-Z0-9]+)?\b")


def main(appliquer):
    c = sqlite3.connect(DB if appliquer else "file:%s?mode=ro" % DB, uri=not appliquer)
    sym = {r[0] for r in c.execute("select symbol from genes") if len(r[0]) >= 3} - EXCLUS
    textes = [(i, t, "description") for i, t in c.execute(
        "select id, coalesce(description_fr,'') || ' ' || coalesce(label_fr,'') || ' ' || coalesce(label_en,'') "
        "from foeto_terms")]
    textes += [(i, t, "verbatim") for i, t in c.execute("select term_id, texte from foeto_verbatims")]
    paires = {}
    for i, t, src in textes:
        for m in TOK.finditer(t or ""):
            s = m.group(0)
            if s in sym and not CONTEXTE_EXCLU.search(t[max(0, m.start() - 60):m.end() + 60]):
                paires.setdefault((i, s), src)
    deja = {tuple(r) for r in c.execute("select foeto_id, gene_symbol from foeto_genes")}
    neufs = [(i, s, src) for (i, s), src in paires.items() if (i, s) not in deja]
    print("%d paires terme–gène relevées, %d nouvelles" % (len(paires), len(neufs)))
    if appliquer:
        c.executemany("insert or ignore into foeto_genes (foeto_id, gene_symbol, source) values (?,?,?)", neufs)
        c.commit()
        print("écrit :", c.execute("select count(*) from foeto_genes").fetchone()[0], "lignes dans foeto_genes")


if __name__ == "__main__":
    main("--appliquer" in sys.argv)
