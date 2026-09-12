#!/usr/bin/env python3
"""Decoupe les formes COMPOSITES de syndrome_signes_livres_candidats.

Le livre enumere : « umbilical and inguinal hernias », « low-set posteriorly
rotated ears ». Une seule ligne porte alors deux signes, et aucun hpo_id ne
convient.

Regle de surete : on ne scinde QUE si TOUS les fragments se mappent
separement. Sinon on ne touche a rien — beaucoup de « and » ne sont pas des
enumerations mais un signe unique (« Syndactyly of second and third toes »,
« Wide gap between first and second toes »), et un decoupage naif les
detruirait.

Deux conjonctions, deux traitements :
  « and », « , », « / »  -> les signes COEXISTENT : on emet les deux hpo_id
  « or »                 -> ALTERNATIVE : emettre les deux serait faux ;
                            on signale la ligne (statut 'alternative') pour
                            arbitrage vers un parent commun, sans rien ecrire

Le verbatim n'est jamais touche : il reste celui de la phrase entiere, donc
la tracabilite vers le livre est intacte.

Usage : python3 decoupe_composites.py [--apply]
"""
import argparse
import re
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from map_signes_hpo_obo import load_obo, norm, toks, QUALIF

DB = "/home/mathevet/Bureau/foeto_base/syndromes_foetaux.db"
OBO = "/home/mathevet/Bureau/akinator/orphadata_cache/hp.obo"
SEP_ET = re.compile(r"\s+and/or\s+|\s+and\s+|\s*,\s*|\s*/\s*")
CONJ = re.compile(r"^(and|or)\s+|\s+(and|or)$", re.I)   # conjonctions orphelines
SEP_OU = re.compile(r"\s+or\s+")


def build_index(c, obo):
    RANK = {"NAME": 0, "EXACT": 1, "NARROW": 2, "BROAD": 3, "RELATED": 4}
    idx, idx_tok = {}, {}

    def put(form, hid, scope):
        n = norm(form)
        if not n:
            return
        if n not in idx or RANK[scope] < RANK[idx[n][1]]:
            idx[n] = (hid, scope)
        t = toks(form)
        if t and (t not in idx_tok or RANK[scope] < RANK[idx_tok[t][1]]):
            idx_tok[t] = (hid, scope)

    known = {r[0] for r in c.execute("select hpo_id from hpo_terms")}
    for hid, t in obo.items():
        if hid in known:
            put(t["name"], hid, "NAME")
            for f, s in t["syn"].items():
                put(f, hid, s)
    for hid, al in c.execute("select hpo_id, aliases_fr from hpo_terms"):
        for f in [x.strip() for x in (al or "").split("|") if x.strip()]:
            put(f, hid, "EXACT")
    return idx, idx_tok


def lookup(idx, idx_tok, s):
    n = norm(s)
    return idx.get(n) or idx.get(norm(QUALIF.sub(" ", n))) or idx_tok.get(toks(s))


def fragments(signe):
    """Fragments d'une enumeration, tete distribuee sur les fragments nus.

    « umbilical and inguinal hernias » -> ['umbilical hernias', 'inguinal hernias']
    Le dernier fragment porte le nom de tete ; on le recopie sur les precedents
    quand ils ne font qu'un ou deux mots (un qualificatif seul ne se mappe pas).
    """
    parts = [CONJ.sub("", p.strip()).strip() for p in SEP_ET.split(signe)]
    parts = [p for p in parts if p]
    if len(parts) < 2:
        return []
    tete = parts[-1].split()
    out = []
    for p in parts[:-1]:
        mots = p.split()
        out.append(p if len(mots) > 2 else " ".join(mots + tete[1:]) if len(tete) > 1 else p)
    out.append(parts[-1])
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()
    c = sqlite3.connect(DB)
    idx, idx_tok = build_index(c, load_obo(OBO))

    rows = c.execute("select id, signe from syndrome_signes_livres_candidats "
                     "where verbatim_ok=1 and (signe like '% and %' or signe like '%,%' "
                     "or signe like '%/%' or signe like '% or %')").fetchall()
    scinde, refuse, alt, deja = [], 0, [], 0
    for rid, signe in rows:
        if lookup(idx, idx_tok, signe):
            deja += 1                       # la forme entiere se mappe : on n'y touche pas
            continue
        if SEP_OU.search(signe) and not SEP_ET.search(signe):
            alt.append((rid, signe))
            continue
        frs = fragments(signe)
        hits = [lookup(idx, idx_tok, f) for f in frs] if frs else []
        if frs and all(hits):
            scinde.append((rid, signe, frs, [h[0] for h in hits]))
        else:
            refuse += 1

    print(f"{len(rows)} formes avec un separateur")
    print(f"  se mappent entieres, intactes      {deja:5d}")
    print(f"  SCINDEES (tous fragments mappes)   {len(scinde):5d}")
    print(f"  alternatives « or » a arbitrer     {len(alt):5d}")
    print(f"  refusees (un fragment ne mappe pas){refuse:5d}")
    print("\nexemples de découpage :")
    for rid, s, frs, hids in scinde[:12]:
        print(f"  {s[:52]:52s} -> {' + '.join(f'{f} [{h}]' for f, h in zip(frs, hids))[:84]}")
    if alt[:6]:
        print("\nexemples d'alternative « or » (non scindees) :")
        for rid, s in alt[:6]:
            print(f"  {s[:70]}")

    if a.apply:
        cols = [r[1] for r in c.execute("pragma table_info(syndrome_signes_livres_candidats)")]
        for col, typ in (("hpo_id", "TEXT"), ("hpo_portee", "TEXT"), ("hpo_methode", "TEXT")):
            if col not in cols:
                c.execute(f"alter table syndrome_signes_livres_candidats add column {col} {typ}")
        c.executemany("update syndrome_signes_livres_candidats set hpo_id=?, hpo_methode='composite_et' where id=?",
                      [("+".join(h), rid) for rid, _, _, h in scinde])
        c.executemany("update syndrome_signes_livres_candidats set hpo_methode='alternative_ou' where id=?",
                      [(rid,) for rid, _ in alt])
        c.commit()
        print(f"\n{len(scinde)} lignes scindees, {len(alt)} marquees 'alternative_ou'.")


if __name__ == "__main__":
    main()
