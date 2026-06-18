#!/usr/bin/env python3
"""Étape 3 — Baseline embedding-only + carte de difficulté.

Pour chaque vignette clinique du benchmark :
1. Encode avec BioLORD → vecteur 768D
2. Cherche les top-10 chunks les plus proches dans vec_chunks
3. Déduplique par syndrome → top-10 syndromes uniques
4. Scoring multi-niveau sur top-1 ET top-5 (exact/famille/cadre/hors)
5. Delta de difficulté : cosine(nom_syndrome_gold, vignette_clinique)

Usage:
    python baseline_embedding.py              # 250 cas
    python baseline_embedding.py 100          # premiers 100 cas
    python baseline_embedding.py --top-k 20   # top-20 chunks
"""
import argparse
import json
import re
import sqlite3
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np
from sentence_transformers import SentenceTransformer

BENCH_DB = "/home/mathevet/Bureau/benchmark_foeto/foeto_bench.db"
SYNDROME_DB = str(Path(__file__).resolve().parent / "syndromes_foetaux.db")
MODEL_NAME = "FremyCompany/BioLORD-2023"

LEVEL_LABELS = {3: "EXACT", 2: "FAMILLE", 1: "CADRE", 0: "HORS"}


def normalize_diag(text):
    if not text:
        return ""
    t = re.sub(r"\(.*?\)", " ", text.strip())
    return re.sub(r"\s+", " ", t).strip()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("limit", nargs="?", type=int, default=250)
    parser.add_argument("--top-k", type=int, default=30)
    args = parser.parse_args()

    import sqlite_vec

    print("Loading BioLORD-2023...")
    model = SentenceTransformer(MODEL_NAME)

    bench = sqlite3.connect(BENCH_DB)
    bench.row_factory = sqlite3.Row
    cases = bench.execute(
        "SELECT id, gold_diagnosis, gold_category, clinical_text FROM cases "
        "ORDER BY CAST(REPLACE(id, 'BENCH_FOETO_', '') AS INTEGER) LIMIT ?",
        (args.limit,)
    ).fetchall()
    print(f"Loaded {len(cases)} benchmark cases")

    syn = sqlite3.connect(SYNDROME_DB)
    syn.enable_load_extension(True)
    sqlite_vec.load(syn)
    syn.row_factory = sqlite3.Row

    # Load syndrome clusters
    cluster_rows = syn.execute("""
        SELECT s.id, s.name_fr, s.name_en, sc.cluster_id
        FROM syndromes s
        JOIN syndrome_clusters sc ON s.id = sc.syndrome_id
    """).fetchall()

    syn_name_to_cluster = {}
    syn_names_list = []
    syn_ids_list = []
    syn_clusters_list = []
    for r in cluster_rows:
        name_fr = r["name_fr"] or ""
        name_en = r["name_en"] or ""
        cid = r["cluster_id"]
        syn_name_to_cluster[name_fr.lower()] = cid
        syn_name_to_cluster[name_en.lower()] = cid
        syn_names_list.append(name_fr or name_en or r["id"])
        syn_ids_list.append(r["id"])
        syn_clusters_list.append(cid)

    # Encode syndrome names for matching
    print("Encoding syndrome names...")
    t0 = time.time()
    syn_name_embs = model.encode(syn_names_list, batch_size=64, show_progress_bar=True,
                                  normalize_embeddings=True)
    print(f"  {len(syn_names_list)} names in {time.time()-t0:.1f}s")

    # Encode gold diagnoses for delta computation
    gold_texts = [normalize_diag(c["gold_diagnosis"]) for c in cases]
    gold_unique = list(set(t for t in gold_texts if t))
    print(f"Encoding {len(gold_unique)} unique gold diagnoses...")
    gold_embs = model.encode(gold_unique, batch_size=64, normalize_embeddings=True)
    gold_emb_map = {t: e for t, e in zip(gold_unique, gold_embs)}

    # Encode clinical vignettes
    print("Encoding clinical vignettes...")
    t0 = time.time()
    clinical_texts = [c["clinical_text"] for c in cases]
    case_embs = model.encode(clinical_texts, batch_size=32, show_progress_bar=True,
                              normalize_embeddings=True)
    print(f"  {len(cases)} vignettes in {time.time()-t0:.1f}s")

    # Build source_id → title mapping for chunk name resolution
    source_titles = {}
    meta_rows = syn.execute("SELECT DISTINCT source_id, title FROM chunk_meta").fetchall()
    for r in meta_rows:
        source_titles[r["source_id"]] = r["title"] or r["source_id"]

    def find_cluster_for_text(text_emb):
        """Find the nearest syndrome and its cluster for an embedding."""
        cosines = text_emb @ syn_name_embs.T
        best_idx = int(np.argmax(cosines))
        return syn_ids_list[best_idx], syn_clusters_list[best_idx], float(cosines[best_idx])

    def score_level(gold_cluster, proposed_cluster, cos_gold_proposed):
        if cos_gold_proposed >= 0.90:
            return 3
        if gold_cluster != -1 and proposed_cluster != -1 and gold_cluster == proposed_cluster:
            return 2
        if cos_gold_proposed >= 0.50:
            return 1
        return 0

    # Process each case
    results = []
    total = 0
    level_t1 = Counter()
    level_t5 = Counter()

    for case, case_emb in zip(cases, case_embs):
        cid = case["id"]
        gold = case["gold_diagnosis"]
        cat = case["gold_category"] or "?"
        gold_norm = normalize_diag(gold)

        if gold.lower().startswith("cas piège") or gold.lower().startswith("piège"):
            results.append({"case_id": cid, "gold": gold, "cat": cat, "status": "PIEGE",
                            "hits": [], "level_t1": -1, "level_t5": -1, "delta": 0.0})
            continue

        total += 1

        # Vector search against chunks
        emb_bytes = case_emb.astype(np.float32).tobytes()
        rows = syn.execute("""
            SELECT v.rowid, v.distance, m.title, m.source_type, m.source_id
            FROM vec_chunks v
            JOIN chunk_meta m ON v.rowid = m.rowid
            WHERE v.embedding MATCH ? AND k = ?
            ORDER BY v.distance
        """, (emb_bytes, args.top_k)).fetchall()

        # Deduplicate by source_id (= syndrome)
        hits = []
        seen = set()
        for r in rows:
            src_id = r["source_id"]
            if src_id in seen:
                continue
            seen.add(src_id)
            cosine = 1.0 - r["distance"]
            title = source_titles.get(src_id, r["title"] or src_id)
            hits.append({
                "syndrome": title,
                "cosine": cosine,
                "source": r["source_type"],
            })
            if len(hits) >= 10:
                break

        # Gold embedding + cluster
        gold_emb = gold_emb_map.get(gold_norm)
        if gold_emb is not None:
            gold_syn_id, gold_cluster, gold_syn_cos = find_cluster_for_text(gold_emb)
        else:
            gold_cluster = -1
            gold_syn_cos = 0.0

        # Delta: cosine(gold_name, clinical_vignette)
        delta = 0.0
        if gold_emb is not None:
            delta = float(gold_emb @ case_emb)

        # Score top-1
        if hits:
            hit1_emb_text = normalize_diag(hits[0]["syndrome"])
            if hit1_emb_text:
                h1_emb = model.encode([hit1_emb_text], normalize_embeddings=True)[0]
                cos_g_p = float(gold_emb @ h1_emb) if gold_emb is not None else 0.0
                _, h1_cluster, _ = find_cluster_for_text(h1_emb)
            else:
                cos_g_p = 0.0
                h1_cluster = -1
            lvl_t1 = score_level(gold_cluster, h1_cluster, cos_g_p)
        else:
            cos_g_p = 0.0
            lvl_t1 = 0

        # Score best-of-5
        best_lvl = lvl_t1
        for h in hits[1:5]:
            h_text = normalize_diag(h["syndrome"])
            if h_text:
                h_emb = model.encode([h_text], normalize_embeddings=True)[0]
                cos_h = float(gold_emb @ h_emb) if gold_emb is not None else 0.0
                _, h_cluster, _ = find_cluster_for_text(h_emb)
                best_lvl = max(best_lvl, score_level(gold_cluster, h_cluster, cos_h))

        level_t1[lvl_t1] += 1
        level_t5[best_lvl] += 1

        results.append({
            "case_id": cid, "gold": gold, "cat": cat,
            "hits": hits[:5],
            "cos_gold_top1": cos_g_p,
            "level_t1": lvl_t1,
            "level_t5": best_lvl,
            "delta": delta,
            "gold_cluster": gold_cluster,
        })

    # ── Display ──
    print(f"\n{'='*120}")
    print(f"BASELINE EMBEDDING-ONLY — {total} cas scorables")
    print(f"{'='*120}")

    print(f"\n  Scoring multi-niveau TOP-1 :")
    for lv in [3, 2, 1, 0]:
        print(f"    Niveau {lv} ({LEVEL_LABELS[lv]:<7s}) : {level_t1[lv]:>3d}/{total} ({level_t1[lv]/max(total,1)*100:.1f}%)")
    useful_t1 = level_t1[3] + level_t1[2]
    print(f"    Utile (exact+famille)   : {useful_t1}/{total} ({useful_t1/max(total,1)*100:.1f}%)")

    print(f"\n  Scoring multi-niveau TOP-5 :")
    for lv in [3, 2, 1, 0]:
        print(f"    Niveau {lv} ({LEVEL_LABELS[lv]:<7s}) : {level_t5[lv]:>3d}/{total} ({level_t5[lv]/max(total,1)*100:.1f}%)")
    useful_t5 = level_t5[3] + level_t5[2]
    print(f"    Utile (exact+famille)   : {useful_t5}/{total} ({useful_t5/max(total,1)*100:.1f}%)")

    # By category
    cat_stats = defaultdict(lambda: {"total": 0, "t1": Counter(), "t5": Counter(), "deltas": []})
    for r in results:
        if r["level_t1"] == -1:
            continue
        cs = cat_stats[r["cat"]]
        cs["total"] += 1
        cs["t1"][r["level_t1"]] += 1
        cs["t5"][r["level_t5"]] += 1
        cs["deltas"].append(r["delta"])

    print(f"\n  {'Catégorie':<35s} {'N':>4s} {'Ex1':>4s} {'Fm1':>4s} {'Ut1':>5s} | {'Ex5':>4s} {'Fm5':>4s} {'Ut5':>5s} | {'Δ-moy':>6s}")
    print("  " + "-" * 90)
    for cat in sorted(cat_stats.keys()):
        cs = cat_stats[cat]
        n = cs["total"]
        ut1 = cs["t1"][3] + cs["t1"][2]
        ut5 = cs["t5"][3] + cs["t5"][2]
        d_mean = np.mean(cs["deltas"]) if cs["deltas"] else 0.0
        print(f"  {cat[:33]:<35s} {n:>4d} {cs['t1'][3]:>4d} {cs['t1'][2]:>4d} {ut1/n*100:>4.0f}% | "
              f"{cs['t5'][3]:>4d} {cs['t5'][2]:>4d} {ut5/n*100:>4.0f}% | {d_mean:>6.3f}")

    # Delta analysis
    scorable = [r for r in results if r["level_t1"] != -1]
    deltas = [r["delta"] for r in scorable]
    d_arr = np.array(deltas)

    print(f"\n  Delta embedding (cosine nom_gold ↔ vignette_clinique) :")
    print(f"    Mean:   {d_arr.mean():.3f}")
    print(f"    Median: {np.median(d_arr):.3f}")
    print(f"    Std:    {d_arr.std():.3f}")
    print(f"    Min:    {d_arr.min():.3f}  Max: {d_arr.max():.3f}")

    # Delta vs difficulty
    easy = [r for r in scorable if r["delta"] >= 0.50]
    medium = [r for r in scorable if 0.30 <= r["delta"] < 0.50]
    hard = [r for r in scorable if r["delta"] < 0.30]

    print(f"\n  Delta → difficulté :")
    for label, group in [("Facile (Δ≥0.50)", easy), ("Moyen (0.30≤Δ<0.50)", medium), ("Difficile (Δ<0.30)", hard)]:
        if not group:
            continue
        n_g = len(group)
        t1_exact = sum(1 for r in group if r["level_t1"] == 3)
        t1_useful = sum(1 for r in group if r["level_t1"] >= 2)
        t5_exact = sum(1 for r in group if r["level_t5"] == 3)
        t5_useful = sum(1 for r in group if r["level_t5"] >= 2)
        print(f"    {label:<25s} : {n_g:>3d} cas | T1: {t1_exact:>2d} exact, {t1_useful:>2d} utile ({t1_useful/n_g*100:.0f}%) | "
              f"T5: {t5_exact:>2d} exact, {t5_useful:>2d} utile ({t5_useful/n_g*100:.0f}%)")

    # Detail table
    print(f"\n{'Case ID':<20s} {'T1':>7s} {'T5':>7s} {'Cos':>5s} {'Δ':>5s} {'GCl':>4s} | {'Gold':<35s} | {'Top-1 Embedding':<35s}")
    print("-" * 140)
    for r in scorable:
        t1_label = LEVEL_LABELS[r["level_t1"]]
        t5_label = LEVEL_LABELS[r["level_t5"]]
        top1_name = r["hits"][0]["syndrome"][:35] if r["hits"] else "?"
        cos = r["cos_gold_top1"] if "cos_gold_top1" in r else 0.0
        print(f"  {r['case_id']:<18s} {t1_label:>7s} {t5_label:>7s} {cos:>5.3f} {r['delta']:>5.3f} {r['gold_cluster']:>4d} | "
              f"{r['gold'][:35]:<35s} | {top1_name:<35s}")

    # Save results JSON
    out_path = Path(__file__).resolve().parent / "baseline_embedding_results.json"
    save_data = {
        "total": total,
        "level_t1": {str(k): v for k, v in level_t1.items()},
        "level_t5": {str(k): v for k, v in level_t5.items()},
        "delta_mean": float(d_arr.mean()),
        "delta_median": float(np.median(d_arr)),
        "results": [{
            "case_id": r["case_id"],
            "gold": r["gold"],
            "cat": r["cat"],
            "level_t1": r["level_t1"],
            "level_t5": r["level_t5"],
            "delta": float(r["delta"]),
            "gold_cluster": int(r.get("gold_cluster", -1)),
            "top1": r["hits"][0]["syndrome"] if r["hits"] else None,
            "top1_cos": float(r["hits"][0]["cosine"]) if r["hits"] else 0.0,
        } for r in results if r["level_t1"] != -1],
    }
    with open(out_path, "w") as f:
        json.dump(save_data, f, ensure_ascii=False, indent=2)
    print(f"\nResults saved to {out_path}")

    bench.close()
    syn.close()
    print("Done.")


if __name__ == "__main__":
    main()
