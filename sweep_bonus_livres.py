#!/usr/bin/env python3
"""Balayage du bonus d'attestation — CPU seul, aucun modele.

Mesure le RANG DU GOLD dans le classement de syndrome_search, pour plusieurs
valeurs du bonus. Isole l'outil du modele qui le consomme : un run 9B melangerait
les deux et coûterait des heures de GPU pour une question qui se tranche en SQL.

Formule mesuree (bonus, jamais penalite) :
    p = prob_orphanet * (1 + BONUS)  si le couple (syndrome, hpo) est atteste
        prob_orphanet                sinon

Pourquoi un bonus et pas un coefficient reducteur : en penalisant les liens NON
attestes, on retire du score aux syndromes COUVERTS par un livre pour ce que
l'extraction n'a pas encore, pendant que les syndromes non couverts gardent tout.
Mesure du 2026-09-12 sur le cas 006 : le gold passait du rang 3 au rang 6 quand
le coefficient baissait. Avec un bonus, l'absence d'attestation ne coûte rien.

Les signes de la vignette sont extraits par hpo_extractor.py — le meme chemin que
la matrice de convergence, donc les rangs sont comparables a ceux du banc.

Usage : python3 sweep_bonus_livres.py [--n 100] [--bonus 0,0.25,0.5,1,2]
"""
import argparse
import sqlite3
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from hpo_extractor import HPOExtractor

DB = "/home/mathevet/Bureau/foeto_base/syndromes_foetaux.db"
BENCH = "/home/mathevet/Bureau/benchmark_foeto/foeto_bench.db"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=100)
    ap.add_argument("--bonus", default="0,0.25,0.5,1,2,3")
    ap.add_argument("--top", type=int, default=20)
    a = ap.parse_args()
    bonus = [float(x) for x in a.bonus.split(",")]

    c = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    b = sqlite3.connect(f"file:{BENCH}?mode=ro", uri=True)
    b.row_factory = sqlite3.Row

    atteste = {(r[0], r[1]) for r in c.execute(
        "select syndrome_id, hpo_id from syndrome_hpo_livres where syndrome_id is not null")}
    liens = {}
    for sid, hid, prob in c.execute(
            """select sh.syndrome_id, sh.hpo_id, sh.prob from syndrome_hpo sh
               join hpo_terms t on t.hpo_id = sh.hpo_id
               where t.context in ('prenatal','both') and t.is_excluded = 0"""):
        liens.setdefault(hid, []).append((sid, prob if prob else 0.5))

    cas = b.execute("""select id, clinical_text, gold_orpha, gold_category, version from cases
                       where gold_orpha is not null and gold_orpha <> ''
                         and is_truncated = 0 and length(clinical_text) > 50
                       order by id limit ?""", (a.n,)).fetchall()
    ex = HPOExtractor(DB)
    print(f"{len(cas)} cas, {len(atteste)} couples attestés, {sum(len(v) for v in liens.values())} liens Orphanet fœtaux\n")

    rangs = {bo: [] for bo in bonus}
    par_cat = {bo: Counter() for bo in bonus}
    # Ventilation par VERSION : plus de 1 000 vignettes sur 1 300 sont generees,
    # et certaines a partir de syndrome_hpo. Les retrouver avec syndrome_hpo est
    # circulaire — le temoin est gonfle, donc le gain mesure est ecrase. Le bonus,
    # lui, vient de syndrome_hpo_livres, source independante du generateur. Si le
    # comportement est le meme sur 1.0 (non generee) et sur 2.0_synthetic, la
    # circularite ne mord pas ; sinon seule la strate 1.0 fait foi.
    par_ver = {bo: Counter() for bo in bonus}
    n_cat, n_ver = Counter(), Counter()
    for k, cas_i in enumerate(cas, 1):
        hpos = {m.hpo_id for m in ex.extract(cas_i["clinical_text"])}
        if not hpos:
            continue
        n_cat[cas_i["gold_category"]] += 1
        n_ver[cas_i["version"]] += 1
        for bo in bonus:
            sc = {}
            for h in hpos:
                for sid, p in liens.get(h, []):
                    sc[sid] = sc.get(sid, 0.0) + (p * (1 + bo) if (sid, h) in atteste else p)
            ordre = [s for s, _ in sorted(sc.items(), key=lambda x: -x[1])]
            r = ordre.index(cas_i["gold_orpha"]) + 1 if cas_i["gold_orpha"] in ordre else None
            rangs[bo].append(r)
            if r == 1:
                par_cat[bo][cas_i["gold_category"]] += 1
                par_ver[bo][cas_i["version"]] += 1
        if k % 25 == 0:
            print(f"  {k}/{len(cas)}", flush=True)

    n = len(rangs[bonus[0]])
    print(f"\n{n} cas avec au moins un HPO extrait\n")
    print(f"{'bonus':>7s} {'hit@1':>7s} {'hit@5':>7s} {'hit@' + str(a.top):>7s} {'rang médian':>12s}")
    for bo in bonus:
        rs = rangs[bo]
        h1 = sum(1 for r in rs if r == 1)
        h5 = sum(1 for r in rs if r and r <= 5)
        hk = sum(1 for r in rs if r and r <= a.top)
        med = sorted(r for r in rs if r)
        print(f"{bo:7.2f} {h1:7d} {h5:7d} {hk:7d} {med[len(med)//2] if med else '-':>12}")

    print(f"\nhit@1 par VERSION de vignette\n{'version':22s} {'n':>5s} " +
          " ".join(f"{bo:>7.2f}" for bo in bonus))
    for ver, nv in n_ver.most_common():
        print(f"{str(ver)[:22]:22s} {nv:5d} " +
              " ".join(f"{par_ver[bo][ver]*100//nv:6d}%" for bo in bonus))

    cats = [c for c, v in n_cat.most_common() if v >= 5]
    if cats:
        print(f"\nhit@1 par catégorie (≥5 cas)\n{'catégorie':34s} " +
              " ".join(f"{bo:>6.2f}" for bo in bonus))
        for cat in cats:
            print(f"{cat[:34]:34s} " + " ".join(f"{par_cat[bo][cat]*100//n_cat[cat]:6d}%" for bo in bonus))


if __name__ == "__main__":
    main()
