#!/usr/bin/env python3
"""Reecrit dans foeto_terms le triage des termes contre les fiches micro.

Source : fiches_lecture/triage_<organe>.tsv (id, label_fr, verdict, fiche,
sous_section, verbatim, raison). Trois colonnes ajoutees a foeto_terms :
  triage_verdict   LESION | NON_LESION | HORS_FICHE
  triage_fiche     fiche_<organe>.md
  triage_section   sous-section de la fiche (= section de grille pour LESION)
Les TSV _v1/_v2 du rein sont des brouillons : on lit triage_rein.tsv.
Les ids absents de foeto_terms (grades passes dans foeto_grades, fusions)
sont comptes et ignores.

Usage : python3 writeback_triage.py
"""
import csv
import glob
import sqlite3

DB = "/home/mathevet/Bureau/foeto_base/syndromes_foetaux.db"
TSV = "/home/mathevet/Bureau/fiches_lecture/triage_*.tsv"


def main():
    c = sqlite3.connect(DB)
    cols = {r[1] for r in c.execute("pragma table_info(foeto_terms)")}
    for col in ("triage_verdict", "triage_fiche", "triage_section"):
        if col not in cols:
            c.execute(f"alter table foeto_terms add column {col} TEXT")
    ids = {r[0] for r in c.execute("select id from foeto_terms")}
    n = absent = 0
    for f in sorted(glob.glob(TSV)):
        if "_v1" in f or "_v2" in f:
            continue
        for r in csv.DictReader(open(f, encoding="utf-8"), delimiter="\t"):
            if r["id"] not in ids:
                absent += 1
                continue
            c.execute("update foeto_terms set triage_verdict=?, triage_fiche=?, triage_section=? where id=?",
                      (r["verdict"], r["fiche"] or None, (r.get("sous_section") or "").strip() or None, r["id"]))
            n += 1
    c.commit()
    print(f"{n} termes tries ({absent} ids de TSV absents de foeto_terms, ignores)")
    for v, k in c.execute("select triage_verdict, count(*) from foeto_terms group by 1"):
        print(f"  {v}: {k}")


if __name__ == "__main__":
    main()
