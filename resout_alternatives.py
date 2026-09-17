#!/usr/bin/env python3
"""Alternatives « or » -> plus petit ancetre commun dans HPO.

« Omphalocele or umbilical hernia » : poser les deux hpo_id affirmerait que le
syndrome porte les deux, ce que le livre ne dit pas. Le bon codage est leur
parent commun — ici HP:0004299 « Hernia of the abdominal wall », a UN saut de
chacun.

HPO est un GRAPHE, pas un arbre : Umbilical hernia a deux parents (Abnormal
umbilicus morphology ET Hernia of the abdominal wall). On calcule donc, pour
chaque membre, TOUS ses ancetres avec leur distance minimale, puis on retient
l'ancetre commun dont la distance maximale aux membres est la plus petite.

Lecture du resultat : distance 1-2 = parent informatif, la proposition se
verifie a l'oeil. Distance grande ou ancetre proche de « Phenotypic
abnormality » = le livre a mis cote a cote deux choses sans rapport, la ligne
part en arbitrage.

Usage : python3 resout_alternatives.py [--apply] [--tsv f.tsv] [--max-dist 3]
"""
import argparse
import re
import sqlite3
import sys
from collections import deque
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from decoupe_composites import build_index, lookup, SEP_OU, CONJ
from map_signes_hpo_obo import load_obo

DB = "/home/mathevet/Bureau/foeto_base/syndromes_foetaux.db"
OBO = "/home/mathevet/Bureau/akinator/orphadata_cache/hp.obo"
RACINES = {"HP:0000001", "HP:0000118"}          # « All », « Phenotypic abnormality »


def ancetres(obo, hid):
    """{ancetre: distance minimale}, le terme lui-meme a la distance 0."""
    d, q = {hid: 0}, deque([hid])
    while q:
        x = q.popleft()
        for p in obo.get(x, {}).get("parents", []):
            if p not in d:
                d[p] = d[x] + 1
                q.append(p)
    return d


def plus_petit_ancetre(obo, hids):
    communs = None
    for h in hids:
        a = ancetres(obo, h)
        communs = a if communs is None else {k: max(v, communs[k]) for k, v in a.items() if k in communs}
    communs = {k: v for k, v in (communs or {}).items() if k not in RACINES and k not in hids}
    if not communs:
        return None, None
    best = min(communs, key=lambda k: (communs[k], obo[k]["name"]))
    return best, communs[best]


def membres(signe):
    """Membres de l'alternative, nom de tete distribue.

    « Small or absent earlobes » -> ['Small earlobes', 'absent earlobes'].
    Sans ca « Small » seul ne se mappe pas et l'alternative est perdue : c'est
    ce qui bloquait 233 lignes sur 244 (2026-09-12).
    """
    parts = [CONJ.sub("", p.strip()).strip() for p in SEP_OU.split(signe)]
    parts = [p for p in parts if p]
    if len(parts) < 2:
        return parts
    tete = parts[-1].split()
    out = []
    for p in parts[:-1]:
        mots = p.split()
        out.append(p if len(mots) > 2 or len(tete) < 2 else " ".join(mots + tete[1:]))
    out.append(parts[-1])
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--tsv")
    ap.add_argument("--max-dist", type=int, default=3)
    ap.add_argument("--livre", help="ne traiter que ce livre")
    a = ap.parse_args()
    obo = load_obo(OBO)
    c = sqlite3.connect(DB)
    idx, idx_tok = build_index(c, obo)

    rows = c.execute("select id, signe from syndrome_signes_livres_candidats "
                     "where hpo_methode='alternative_ou'"
                     + (" and livre=?" if a.livre else ""), (a.livre,) if a.livre else ()).fetchall()
    resolus, trop_loin, partiels = [], [], []
    for rid, signe in rows:
        ms = membres(signe)
        hits = [lookup(idx, idx_tok, m) for m in ms]
        if len(ms) < 2 or not all(hits):
            partiels.append((rid, signe, ms, hits))
            continue
        hids = [h[0] for h in hits]
        anc, dist = plus_petit_ancetre(obo, hids)
        if anc and dist <= a.max_dist:
            resolus.append((rid, signe, ms, hids, anc, dist))
        else:
            trop_loin.append((rid, signe, hids, anc, dist))

    print(f"{len(rows)} alternatives « or »")
    print(f"  parent commun a distance <= {a.max_dist} : {len(resolus)}")
    print(f"  parent trop lointain                  : {len(trop_loin)}")
    print(f"  au moins un membre non mappe          : {len(partiels)}")
    vus = set()
    print("\nexemples résolus :")
    for rid, s, ms, hids, anc, d in resolus:
        if s.lower() in vus:
            continue
        vus.add(s.lower())
        print(f"  {s[:46]:46s} -> {anc} {obo[anc]['name'][:34]:34s} (d={d})")
        if len(vus) >= 14:
            break
    if trop_loin:
        print("\nexemples écartés (parent trop haut) :")
        for rid, s, hids, anc, d in trop_loin[:5]:
            print(f"  {s[:46]:46s} -> {obo.get(anc,{}).get('name','-')[:34]:34s} (d={d})")

    if a.tsv:
        with open(a.tsv, "w", encoding="utf-8") as f:
            f.write("signe_livre\tmembres\thpo_membres\tparent_propose\tlabel_parent\tdistance\tdefinition_parent\tdecision\n")
            seen = set()
            for rid, s, ms, hids, anc, d in resolus:
                if s.lower() in seen:
                    continue
                seen.add(s.lower())
                f.write(f"{s}\t{' | '.join(ms)}\t{'+'.join(hids)}\tPARENT:{anc}\t{obo[anc]['name']}\t{d}\t"
                        f"{obo[anc].get('def','')[:250]}\t\n")
            for rid, s, hids, anc, d in trop_loin:
                if s.lower() in seen:
                    continue
                seen.add(s.lower())
                f.write(f"{s}\t\t{'+'.join(hids)}\t\t{obo.get(anc,{}).get('name','')}\t{d if d else ''}\t\t\n")
        print(f"\n-> {a.tsv}")

    if a.apply:
        c.executemany("update syndrome_signes_livres_candidats "
                      "set hpo_id=?, hpo_methode='alternative_parent' where id=?",
                      [(f"PARENT:{anc}", rid) for rid, _, _, _, anc, _ in resolus])
        c.commit()
        print(f"\n{len(resolus)} lignes portees sur leur parent commun.")


if __name__ == "__main__":
    main()
