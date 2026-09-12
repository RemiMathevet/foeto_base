#!/usr/bin/env python3
"""Mappe les signes extraits des livres (syndrome_signes_livres_candidats) vers
hpo_id — DETERMINISTE, aucun LLM : un identifiant d'ontologie ne s'invente pas.

Trois passes, de la plus sure a la plus permissive ; `methode` garde laquelle a
repondu pour qu'un arbitrage porte sur le bon sous-ensemble :
  exact     egalite stricte sur label_en ou sur un alias (apres normalisation)
  qualif    idem apres retrait des qualifieurs (severe, bilateral, mild, ...)
  tokens    egalite de l'ensemble des mots de contenu (ordre libre, pluriels)

Ce qui n'est PAS fait ici et ne doit pas l'etre : le cosinus BioLORD. Il
rapprocherait « polydactyly » de « syndactyly » sans que rien ne le signale, et
BioLORD est anglophone alors qu'une part des alias est en francais (fiche
feedback_biolord_monolingual_space). Ce qui ne matche pas reste non mappe et
sera arbitre a la main ou par un alias ajoute a hpo_terms.

Usage : python3 map_signes_hpo.py [--apply]
Sans --apply : mesure seule, rien n'est ecrit.
"""
import argparse
import re
import unicodedata
import sqlite3
from collections import Counter

DB = "/home/mathevet/Bureau/foeto_base/syndromes_foetaux.db"

QUALIF = re.compile(r"\b(severe|mild|moderate|marked|slight|profound|progressive|"
                    r"bilateral|unilateral|left|right|generalized|diffuse|focal|partial|complete|"
                    r"congenital|variable|occasional|frequent|recurrent|chronic|acute|"
                    r"abnormal|abnormality of|anomaly of|defect of|and related|features?|findings?)\b")
STOP = {"of", "the", "a", "an", "with", "or", "and", "in", "to", "at"}


def norm(s):
    s = (s or "").lower().strip()
    s = re.sub(r"\(.*?\)", " ", s)                 # « (MIM 187600) », « (rare) »
    # replier les diacritiques au lieu de les supprimer : [^a-z0-9] transformait
    # « kleeblattschädel » en « kleeblattsch del » et « macrocéphalie » en
    # « macroc phalie ». 40 % des 55 646 formes de hpo_synonymes etaient touchees
    # — dont tout le francais accentue (2026-09-12).
    s = "".join(ch for ch in unicodedata.normalize("NFD", s)
                if unicodedata.category(ch) != "Mn")
    s = re.sub(r"[^a-z0-9\s-]", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def toks(s):
    w = [re.sub(r"(ies|s)$", lambda m: "y" if m.group() == "ies" else "", x)
         for x in norm(s).split() if x not in STOP]
    return frozenset(w)


def build_index(c):
    exact, tok = {}, {}
    for hid, en, fr, al in c.execute(
            "select hpo_id, label_en, label_fr, aliases_fr from hpo_terms "
            "where context in ('prenatal','both') and is_excluded=0"):
        forms = [en, fr] + [x.strip() for x in (al or "").split("|")]
        for f in forms:
            n = norm(f)
            if not n:
                continue
            exact.setdefault(n, hid)
            exact.setdefault(norm(QUALIF.sub(" ", n)), hid)
            tok.setdefault(toks(f), hid)
    return exact, tok


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()
    c = sqlite3.connect(DB)
    exact, tok = build_index(c)
    rows = c.execute("select id, signe from syndrome_signes_livres_candidats where verbatim_ok=1").fetchall()

    out, stats = [], Counter()
    for rid, signe in rows:
        n = norm(signe)
        hid = exact.get(n)
        meth = "exact"
        if not hid:
            hid = exact.get(norm(QUALIF.sub(" ", n)))
            meth = "qualif"
        if not hid:
            hid = tok.get(toks(signe))
            meth = "tokens"
        if hid:
            out.append((hid, meth, rid))
            stats[meth] += 1
        else:
            stats["non mappe"] += 1

    n = len(rows)
    print(f"{n} signes verifies, {len(set(s for _, s in rows))} libelles distincts")
    for k in ("exact", "qualif", "tokens", "non mappe"):
        print(f"  {k:10s} {stats[k]:6d}  {stats[k]*100/n:5.1f} %")
    print(f"  -> mappes  {n - stats['non mappe']:6d}  {(n - stats['non mappe'])*100/n:5.1f} %")
    print(f"  hpo_id distincts atteints : {len(set(h for h, _, _ in out))}")

    if not a.apply:
        print("\n(mesure seule — relancer avec --apply pour ecrire)")
        return
    c.execute("alter table syndrome_signes_livres_candidats add column hpo_id TEXT") if "hpo_id" not in [
        r[1] for r in c.execute("pragma table_info(syndrome_signes_livres_candidats)")] else None
    c.execute("alter table syndrome_signes_livres_candidats add column hpo_methode TEXT") if "hpo_methode" not in [
        r[1] for r in c.execute("pragma table_info(syndrome_signes_livres_candidats)")] else None
    c.executemany("update syndrome_signes_livres_candidats set hpo_id=?, hpo_methode=? where id=?", out)
    c.commit()
    print(f"\n{len(out)} lignes mises a jour.")


if __name__ == "__main__":
    main()
