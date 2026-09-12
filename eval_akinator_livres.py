#!/usr/bin/env python3
"""L'Akinator sur NOTRE base : le moteur bayesien (akinator_engine.AkinatorEngine)
nourri par la matrice attestee (syndrome_hpo_livres, jamais fusionnee a Orphanet),
evalue sur les cas du banc sans poser de questions — on lui donne d'un coup les
HPO du cas (oui / non) et on lit le rang de l'ORPHA gold.

Deux canaux compares :
  orphanet  akinator_data/akinator_foetopath_full.json (syndrome_hpo Orphanet)
            — CIRCULAIRE sur les cas synthetiques du banc, qui ont ete ecrits
            depuis ces memes annotations (PREFECT : 41 % vs 6 %) ; borne haute
  livres    construit ici depuis v_syndrome_hpo_livres_foetal — independant
Deux entrees :
  json      phenotype_json du cas (codage HPO propre, is_present oui/non)
  texte     hpo_extractor sur clinical_text (le realiste)
Sorties : top-1, top-5, top-1 famille (syndrome_family_members), gold couvert
(l'ORPHA gold a-t-il seulement une ligne dans le canal ?), sur 001-020 puis 800.

Usage : python3 eval_akinator_livres.py [--n 800]
"""
import argparse
import json
import re
import sqlite3
import sys
import tempfile
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, "/home/mathevet/Bureau/akinator")
sys.path.insert(0, "/home/mathevet/Bureau/foeto_base")
from akinator_engine import AkinatorEngine

DB = "/home/mathevet/Bureau/foeto_base/syndromes_foetaux.db"
BENCH = "/home/mathevet/Bureau/benchmark_foeto/foeto_bench.db"
ORPHA_JSON = "/home/mathevet/Bureau/akinator/akinator_data/akinator_foetopath_full.json"
NIV = {"principal": 0.85, "texte": 0.5, "occasionnel": 0.25}


def data_livres(c):
    ent = {}
    lab = dict(c.execute("select hpo_id, coalesce(label_fr, label_en) from hpo_terms"))
    for sid, titre, h, freq, niveau, est_parent, cat in c.execute(
            """select coalesce(v.syndrome_id, 'LIVRE:' || v.syndrome_titre), v.syndrome_titre, v.hpo_id, v.frequence,
                      v.niveau, v.est_parent, s.category
               from v_syndrome_hpo_livres_foetal v left join syndromes s on s.id = v.syndrome_id
               where v.niveau_entree = 'syndrome'"""):
        p = None
        if freq:
            m = re.search(r"(\d+(?:[.,]\d+)?)\s*%", freq)
            if m:
                p = min(0.95, max(0.05, float(m.group(1).replace(",", ".")) / 100))
        if p is None:
            p = NIV.get(niveau, 0.5)
        if est_parent:
            p = min(p, 0.4)
        e = ent.setdefault(sid, {"orpha_code": sid, "name_fr": titre, "type": "", "inheritance": [],
                                 "category": cat or "livre", "relevance": "haute", "prevalence": 0.001, "signes": {}})
        if p > e["signes"].get(h, {}).get("prob", 0):
            e["signes"][h] = {"label": lab.get(h, h), "prob": p, "freq": freq or niveau}
    return list(ent.values())


def rang(engine, obs, gold):
    st = engine.new_session()
    for h, present in obs:
        if h in engine.all_signs:
            st = engine.update(st, h, "oui" if present else "non")
    ordre = sorted(st.posteriors.items(), key=lambda x: -x[1])
    codes = [k for k, _ in ordre]
    return (codes.index(gold) + 1) if gold in codes else None, codes[:5]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=800)
    a = ap.parse_args()
    c = sqlite3.connect(DB)
    fam = defaultdict(set)
    for fid, sid in c.execute("select family_id, syndrome_id from syndrome_family_members"):
        fam[sid].add(fid)
    tmp = Path(tempfile.gettempdir()) / "akinator_livres.json"
    tmp.write_text(json.dumps(data_livres(c)), encoding="utf-8")
    moteurs = {"orphanet": AkinatorEngine(ORPHA_JSON, relevance_filter=["haute", "moyenne"]),
               "livres": AkinatorEngine(str(tmp))}
    from hpo_extractor import get_extractor
    ext = get_extractor()
    b = sqlite3.connect(BENCH)
    cas = b.execute("select id, gold_orpha, phenotype_json, clinical_text from cases where gold_orpha is not null order by id").fetchall()
    lots = {"001-020": [x for x in cas if int(x[0].split("_")[-1]) <= 20], f"tous ({len(cas)})": cas[:a.n]}
    print(f"{'lot':14s} {'canal':9s} {'entrée':6s} {'n':>4} {'gold∈canal':>10} {'top1':>6} {'top5':>6} {'fam1':>6}")
    for nom_lot, L in lots.items():
        for nom_m, eng in moteurs.items():
            for entree in ("json", "texte"):
                n = couv = t1 = t5 = f1 = 0
                for cid, gold, pj, txt in L:
                    if entree == "json":
                        pl = json.loads(pj or "[]")
                        obs = [(x["hpo_id"], bool(x.get("is_present", True))) if isinstance(x, dict) else (x, True)
                               for x in (pl if isinstance(pl, list) else pl.get("phenotypes", []))]
                    else:
                        obs = [(m.hpo_id, not m.negated) for m in ext.extract(txt or "")]
                    if not obs:
                        continue
                    n += 1
                    couv += gold in eng.syndromes
                    r, top = rang(eng, obs, gold)
                    t1 += r == 1; t5 += bool(r and r <= 5)
                    f1 += bool(top and (top[0] == gold or fam.get(top[0], set()) & fam.get(gold, set())))
                if n:
                    print(f"{nom_lot:14s} {nom_m:9s} {entree:6s} {n:4d} {100*couv/n:9.0f}% {100*t1/n:5.0f}% {100*t5/n:5.0f}% {100*f1/n:5.0f}%")


if __name__ == "__main__":
    main()
