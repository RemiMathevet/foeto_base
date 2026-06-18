#!/usr/bin/env python3
"""Sweep top-K pour tracer la courbe recall@K de la convergence matrix v2."""
import sqlite3
import time
from collections import defaultdict

import numpy as np

from convergence_matrix import ConvergenceMatrix, _score_level, LEVEL_RANK

K_VALUES = [5, 10, 15, 20, 30, 50]
MAX_K = max(K_VALUES)


def sweep():
    cm = ConvergenceMatrix(rrf_k=30)
    print(f"Chunk→syndrome mapping: {cm._n_mapped}/{cm._n_total}")

    bench_conn = sqlite3.connect("/home/mathevet/Bureau/benchmark_foeto/foeto_bench.db")
    bench_conn.row_factory = sqlite3.Row
    cases = bench_conn.execute("""
        SELECT id, clinical_text, gold_diagnosis
        FROM cases WHERE is_truncated = 0 AND length(clinical_text) > 50
        ORDER BY id
    """).fetchall()
    bench_conn.close()
    n = len(cases)

    print(f"\nRetrieving top-{MAX_K} for {n} cases...")
    texts = [c["clinical_text"] for c in cases]
    golds = [c["gold_diagnosis"] for c in cases]

    batch_results = cm.query_batch(texts, top_k=MAX_K)

    syn_rows = cm.conn.execute(
        "SELECT s.id, s.name_fr, s.name_en, sc.cluster_id "
        "FROM syndromes s LEFT JOIN syndrome_clusters sc ON s.id = sc.syndrome_id"
    ).fetchall()
    syn_names, syn_ids, syn_clusters = [], [], {}
    for row in syn_rows:
        name = row["name_fr"] or row["name_en"] or row["id"]
        syn_names.append(name)
        syn_ids.append(row["id"])
        syn_clusters[row["id"]] = row["cluster_id"] if row["cluster_id"] is not None else -1

    all_names = set(golds)
    all_names.update(syn_names)
    for res_list in batch_results:
        for r in res_list:
            all_names.add(r["name"])
    all_names = list(all_names)

    print(f"Encoding {len(all_names)} unique names for scoring...")
    name_embs = cm.biolord.encode(all_names, batch_size=64, normalize_embeddings=True,
                                   show_progress_bar=True)
    emb_map = {name: emb for name, emb in zip(all_names, name_embs)}
    syn_emb_matrix = np.stack([emb_map[n] for n in syn_names])

    def find_gold_cluster(gold_emb):
        cosines = gold_emb @ syn_emb_matrix.T
        best_idx = np.argmax(cosines)
        if cosines[best_idx] >= 0.85:
            return syn_clusters.get(syn_ids[best_idx], -1)
        return None

    # Score each candidate once, store per-case level list
    case_levels = []
    for i in range(n):
        gold_emb = emb_map.get(golds[i])
        candidates = batch_results[i]
        if not candidates or gold_emb is None:
            case_levels.append(["HORS"] * MAX_K)
            continue

        gold_cluster = find_gold_cluster(gold_emb)
        lvls = []
        for cand in candidates:
            c_emb = emb_map.get(cand["name"])
            if c_emb is None:
                lvls.append("HORS")
                continue
            cos = float(gold_emb @ c_emb)
            c_cluster = syn_clusters.get(cand["syndrome_id"], -1)
            lvls.append(_score_level(cos, gold_cluster, c_cluster))
        while len(lvls) < MAX_K:
            lvls.append("HORS")
        case_levels.append(lvls)

    # Evaluate at each K
    print(f"\n{'='*80}")
    print(f"RECALL@K CURVE — {n} cases, RRF k=30")
    print(f"Canaux: BioLORD + HPO structuré + Akinator + FTS5 (4 canaux)")
    print(f"{'='*80}")
    print(f"\n{'K':>4s} | {'Utile (E+F)':>12s} | {'EXACT':>12s} | {'FAMILLE':>12s} | {'CADRE':>12s} | {'HORS':>12s}")
    print("-" * 78)

    results = []
    for k in K_VALUES:
        counts = {"EXACT": 0, "FAMILLE": 0, "CADRE": 0, "HORS": 0}
        for lvls in case_levels:
            best = "HORS"
            for l in lvls[:k]:
                if LEVEL_RANK[l] > LEVEL_RANK[best]:
                    best = l
            counts[best] += 1

        useful = counts["EXACT"] + counts["FAMILLE"]
        useful_cadre = useful + counts["CADRE"]
        print(f"  {k:>2d} | {useful:>4d} ({useful/n*100:>5.1f}%) | "
              f"{counts['EXACT']:>4d} ({counts['EXACT']/n*100:>5.1f}%) | "
              f"{counts['FAMILLE']:>4d} ({counts['FAMILLE']/n*100:>5.1f}%) | "
              f"{counts['CADRE']:>4d} ({counts['CADRE']/n*100:>5.1f}%) | "
              f"{counts['HORS']:>4d} ({counts['HORS']/n*100:>5.1f}%)")
        results.append({"k": k, "useful": useful, "useful_pct": useful/n*100,
                        "useful_cadre": useful_cadre, "useful_cadre_pct": useful_cadre/n*100,
                        **counts})

    # Also show "utile+cadre" curve (if LLM can work with "dans le cadre")
    print(f"\n{'K':>4s} | {'Utile+Cadre':>12s}")
    print("-" * 25)
    for r in results:
        print(f"  {r['k']:>2d} | {r['useful_cadre']:>4d} ({r['useful_cadre_pct']:>5.1f}%)")

    print(f"\n  → Plafond LLM si re-rank top-K (utile = EXACT+FAMILLE) :")
    for r in results:
        print(f"     K={r['k']:>2d} : {r['useful_pct']:.1f}%")

    cm.close()


if __name__ == "__main__":
    sweep()
