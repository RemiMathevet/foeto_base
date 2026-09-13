#!/usr/bin/env python3
"""Applique les DECISIONS des TSV d'arbitrage a tout signe non mappe qui porte le
meme libelle — idempotent, a rejouer apres chaque extraction.

Pourquoi : « hearing loss » avait ete arbitre (HP:0000365) sur les lignes de Smith,
puis GeneReviews en a apporte 73 nouvelles, restees non mappees : la decision
n'etait pas une regle, seulement une ecriture. Ici la decision devient la regle.
  arbitrage_hpo_signes.tsv   signe_livre / decision : HP:x, PARENT:HP:x, NON
  arbitrage_llm_nom.tsv      signe / choix : HP:x ou NON (relu par Remi)
  arbitrage_regles_suffixe.tsv  signe / choix
Cle = libelle normalise (map_signes_hpo.norm). NON pose hpo_methode='arbitrage:non'
sans hpo_id, pour ne plus le representer.

Usage : python3 applique_arbitrages.py [--apply]
"""
import argparse
import csv
import sqlite3
from pathlib import Path

from map_signes_hpo import norm

DB = "/home/mathevet/Bureau/foeto_base/syndromes_foetaux.db"
TSV = [("arbitrage_hpo_signes.tsv", "signe_livre", "decision"),
       ("arbitrage_llm_nom.tsv", "signe", "choix"),
       ("arbitrage_regles_suffixe.tsv", "signe", "choix")]


def decisions():
    d = {}
    for f, ks, kd in TSV:
        p = Path(__file__).with_name(f)
        if not p.exists():
            continue
        for r in csv.DictReader(open(p, encoding="utf-8"), delimiter="\t"):
            v = (r.get(kd) or "").strip()
            if v and (v.startswith(("HP:", "PARENT:HP:")) or v.upper() == "NON"):
                d.setdefault(norm(r[ks]), v)
    return d


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()
    d = decisions()
    c = sqlite3.connect(DB)
    rows = c.execute("select id, signe from syndrome_signes_livres_candidats where hpo_id is null and verbatim_ok=1 "
                     "and coalesce(hpo_methode, '') <> 'arbitrage:non'").fetchall()
    out = [(d[norm(s)], rid) for rid, s in rows if norm(s) in d]
    pose = [(h, rid) for h, rid in out if h.upper() != "NON"]
    non = [rid for h, rid in out if h.upper() == "NON"]
    print(f"{len(d)} décisions ; {len(rows)} non mappés -> {len(pose)} posés, {len(non)} écartés (NON)")
    if a.apply:
        c.executemany("update syndrome_signes_livres_candidats set hpo_id=?, hpo_methode='arbitrage' where id=?", pose)
        c.executemany("update syndrome_signes_livres_candidats set hpo_methode='arbitrage:non' where id=?", [(r,) for r in non])
        c.commit()


if __name__ == "__main__":
    main()
