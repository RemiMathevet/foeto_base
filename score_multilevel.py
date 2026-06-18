#!/usr/bin/env python3
"""Étape 2 — Scoring multi-niveau avec clusters HDBSCAN.

Pour chaque run benchmark :
1. Encode gold et proposed avec BioLORD
2. Trouve le syndrome DB le plus proche de chacun (cosine)
3. Compare leurs clusters HDBSCAN
4. Attribue un score 0-3 :
   - 3 = exact (cosine gold↔proposed ≥ 0.90 OU même syndrome DB)
   - 2 = famille (même cluster HDBSCAN)
   - 1 = cadre (cosine ≥ 0.50)
   - 0 = hors sujet

Usage:
    python score_multilevel.py                    # scorer hpo19b
    python score_multilevel.py qwen_35_9b_codex_v4
    python score_multilevel.py --all              # tous les tool_ids
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


def normalize_diag(text):
    if not text:
        return ""
    t = text.strip()
    t = re.sub(r"\(.*?\)", " ", t)
    t = re.sub(r"\s+", " ", t).strip()
    return t


def extract_top5(raw):
    if not raw:
        return []
    try:
        clean = raw.strip()
        if "```" in clean:
            for p in clean.split("```"):
                p = p.strip()
                if p.startswith("json"):
                    p = p[4:].strip()
                if p.startswith("{"):
                    try:
                        d = json.loads(p)
                        if "diagnostics" in d:
                            return [x.get("diagnostic", "") for x in d["diagnostics"]]
                    except json.JSONDecodeError:
                        continue
        d = json.loads(clean)
        diags = d.get("diagnostics") or []
        return [x.get("diagnostic", "") for x in diags if isinstance(x, dict)]
    except (json.JSONDecodeError, KeyError):
        idx = raw.rfind('{"diagnostics"')
        if idx >= 0:
            try:
                return [x.get("diagnostic", "") for x in json.loads(raw[idx:]).get("diagnostics", [])]
            except (json.JSONDecodeError, KeyError):
                pass
    return []


def load_syndrome_embeddings(syn_conn, model):
    """Build a matrix of BioLORD embeddings for all syndromes + their cluster IDs."""
    rows = syn_conn.execute("""
        SELECT s.id, s.name_fr, s.name_en, sc.cluster_id
        FROM syndromes s
        JOIN syndrome_clusters sc ON s.id = sc.syndrome_id
    """).fetchall()

    names = []
    sids = []
    clusters = []
    for sid, name_fr, name_en, cluster_id in rows:
        name = name_fr or name_en or sid
        names.append(name)
        sids.append(sid)
        clusters.append(cluster_id)

    print(f"Encoding {len(names)} syndrome names with BioLORD...")
    t0 = time.time()
    embs = model.encode(names, batch_size=64, show_progress_bar=True, normalize_embeddings=True)
    print(f"  {time.time()-t0:.1f}s")

    return sids, names, clusters, embs


def find_nearest_syndrome(query_emb, syndrome_embs, syndrome_ids, syndrome_clusters):
    """Find the nearest syndrome by cosine similarity."""
    cosines = query_emb @ syndrome_embs.T
    best_idx = np.argmax(cosines)
    return syndrome_ids[best_idx], syndrome_clusters[best_idx], float(cosines[best_idx])


def score_level(cos_direct, gold_cluster, proposed_cluster, gold_syn_cos, proposed_syn_cos):
    """Compute multi-level score 0-3."""
    if cos_direct >= 0.90:
        return 3
    if gold_cluster != -1 and proposed_cluster != -1 and gold_cluster == proposed_cluster:
        return 2
    if cos_direct >= 0.50:
        return 1
    return 0


def score_tool(tool_id, bench_conn, syn_conn, model, syndrome_data):
    """Score all runs for a given tool_id."""
    sids, snames, sclusters, sembs = syndrome_data

    rows = bench_conn.execute("""
        SELECT r.id, r.case_id, c.gold_diagnosis, r.output_raw, r.diagnosis_proposed,
               r.score_b, r.score_cosine
        FROM runs r JOIN cases c ON r.case_id = c.id
        WHERE r.tool_id = ?
        ORDER BY CAST(REPLACE(r.case_id, 'BENCH_FOETO_', '') AS INTEGER)
    """, (tool_id,)).fetchall()

    if not rows:
        print(f"No runs for tool_id={tool_id}")
        return

    # Collect all unique texts
    gold_texts = {}
    proposed_texts = {}
    best5_texts = {}

    for row in rows:
        cid = row[1]
        gold = normalize_diag(row[2])
        gold_texts[cid] = gold

        top5 = extract_top5(row[3])
        if top5:
            proposed_texts[cid] = normalize_diag(top5[0])
            best5_texts[cid] = [normalize_diag(d) for d in top5[:5]]
        elif row[4] and row[4] != "?":
            proposed_texts[cid] = normalize_diag(row[4])
            best5_texts[cid] = [proposed_texts[cid]]
        else:
            proposed_texts[cid] = ""
            best5_texts[cid] = []

    # Batch encode
    all_texts = set()
    for t in gold_texts.values():
        if t:
            all_texts.add(t)
    for t in proposed_texts.values():
        if t:
            all_texts.add(t)
    for diags in best5_texts.values():
        for t in diags:
            if t:
                all_texts.add(t)

    all_texts = list(all_texts)
    print(f"\nEncoding {len(all_texts)} unique diagnosis texts...")
    emb_list = model.encode(all_texts, batch_size=64, show_progress_bar=True, normalize_embeddings=True)
    emb_map = {text: emb for text, emb in zip(all_texts, emb_list)}

    # Score each run
    results = []
    level_counts = Counter()

    for row in rows:
        rid = row[0]
        cid = row[1]
        gold = gold_texts[cid]
        proposed = proposed_texts[cid]
        old_b = row[5] or 0
        old_cos = row[6] or 0.0

        if not gold or not proposed:
            results.append({
                "case_id": cid, "gold": gold[:45], "proposed": proposed[:45] if proposed else "?",
                "cos_direct": 0.0, "level": 0, "match_b": old_b,
                "gold_cluster": -1, "proposed_cluster": -1,
                "gold_syn": "", "proposed_syn": "",
            })
            level_counts[0] += 1
            continue

        g_emb = emb_map.get(gold)
        p_emb = emb_map.get(proposed)

        if g_emb is None or p_emb is None:
            results.append({
                "case_id": cid, "gold": gold[:45], "proposed": proposed[:45],
                "cos_direct": 0.0, "level": 0, "match_b": old_b,
                "gold_cluster": -1, "proposed_cluster": -1,
                "gold_syn": "", "proposed_syn": "",
            })
            level_counts[0] += 1
            continue

        cos_direct = float(g_emb @ p_emb)

        gold_syn_id, gold_cluster, gold_syn_cos = find_nearest_syndrome(g_emb, sembs, sids, sclusters)
        prop_syn_id, prop_cluster, prop_syn_cos = find_nearest_syndrome(p_emb, sembs, sids, sclusters)

        # Best-of-5 level
        best_level = score_level(cos_direct, gold_cluster, prop_cluster, gold_syn_cos, prop_syn_cos)

        for d in best5_texts.get(cid, [])[1:]:
            if d and d in emb_map:
                d_emb = emb_map[d]
                cos_d = float(g_emb @ d_emb)
                _, d_cluster, _ = find_nearest_syndrome(d_emb, sembs, sids, sclusters)
                lvl = score_level(cos_d, gold_cluster, d_cluster, gold_syn_cos, 0)
                best_level = max(best_level, lvl)

        level = score_level(cos_direct, gold_cluster, prop_cluster, gold_syn_cos, prop_syn_cos)
        level_counts[level] += 1

        gold_syn_name = snames[sids.index(gold_syn_id)] if gold_syn_id in sids else "?"
        prop_syn_name = snames[sids.index(prop_syn_id)] if prop_syn_id in sids else "?"

        results.append({
            "case_id": cid,
            "gold": gold[:45],
            "proposed": proposed[:45],
            "cos_direct": cos_direct,
            "level": level,
            "best_level": best_level,
            "match_b": old_b,
            "gold_cluster": gold_cluster,
            "proposed_cluster": prop_cluster,
            "gold_syn": gold_syn_name[:30],
            "proposed_syn": prop_syn_name[:30],
            "gold_syn_cos": gold_syn_cos,
            "prop_syn_cos": prop_syn_cos,
        })

    # Display
    n = len(results)
    n_with = sum(1 for r in results if r["proposed"] != "?")

    print(f"\n{'='*120}")
    print(f"SCORING MULTI-NIVEAU — {tool_id} — {n} runs ({n_with} avec réponse)")
    print(f"{'='*120}")

    LEVEL_LABELS = {3: "EXACT", 2: "FAMILLE", 1: "CADRE", 0: "HORS"}

    print(f"\n  Niveau 3 (exact)   : {level_counts[3]:>3d}/{n} ({level_counts[3]/max(n,1)*100:.1f}%)")
    print(f"  Niveau 2 (famille) : {level_counts[2]:>3d}/{n} ({level_counts[2]/max(n,1)*100:.1f}%)")
    print(f"  Niveau 1 (cadre)   : {level_counts[1]:>3d}/{n} ({level_counts[1]/max(n,1)*100:.1f}%)")
    print(f"  Niveau 0 (hors)    : {level_counts[0]:>3d}/{n} ({level_counts[0]/max(n,1)*100:.1f}%)")

    useful = level_counts[3] + level_counts[2]
    print(f"\n  Réponses utiles (exact+famille) : {useful}/{n} ({useful/max(n,1)*100:.1f}%)")

    # Best-of-5 levels
    best_level_counts = Counter()
    for r in results:
        best_level_counts[r.get("best_level", r["level"])] += 1

    print(f"\n  Best-of-5 :")
    for lv in [3, 2, 1, 0]:
        print(f"    Niveau {lv} ({LEVEL_LABELS[lv]:<7s}) : {best_level_counts[lv]:>3d}/{n} ({best_level_counts[lv]/max(n,1)*100:.1f}%)")

    # MATCH_RULES miss but family hit
    miss_but_family = [r for r in results if not r["match_b"] and r["level"] >= 2]
    if miss_but_family:
        print(f"\n  MISS en MATCH_RULES mais bonne famille ({len(miss_but_family)}) :")
        for r in miss_but_family:
            print(f"    {r['case_id']}: {r['gold'][:35]} → {r['proposed'][:35]} (cluster {r['gold_cluster']}={r['proposed_cluster']})")

    # Detail table
    print(f"\n{'Case ID':<20s} {'Lvl':>3s} {'B5':>3s} {'MB':>2s} {'Cos':>5s} | {'Gold':<35s} | {'Proposed':<35s} | {'G-Cl':>4s} {'P-Cl':>4s}")
    print("-" * 140)
    for r in results:
        mb = "OK" if r["match_b"] else ""
        lvl_label = LEVEL_LABELS[r["level"]]
        b5 = LEVEL_LABELS.get(r.get("best_level", r["level"]), "?")
        print(f"  {r['case_id']:<18s} {lvl_label:>5s} {b5:>5s} {mb:>2s} {r['cos_direct']:>5.3f} | "
              f"{r['gold']:<35s} | {r['proposed']:<35s} | {r['gold_cluster']:>4d} {r['proposed_cluster']:>4d}")

    # Update DB with multi-level scores
    print(f"\nUpdating score_multilevel in benchmark DB...")
    try:
        bench_conn.execute("ALTER TABLE runs ADD COLUMN score_multilevel INTEGER")
    except sqlite3.OperationalError:
        pass
    try:
        bench_conn.execute("ALTER TABLE runs ADD COLUMN score_multilevel_best5 INTEGER")
    except sqlite3.OperationalError:
        pass
    try:
        bench_conn.execute("ALTER TABLE runs ADD COLUMN gold_cluster INTEGER")
    except sqlite3.OperationalError:
        pass
    try:
        bench_conn.execute("ALTER TABLE runs ADD COLUMN proposed_cluster INTEGER")
    except sqlite3.OperationalError:
        pass

    for r, row in zip(results, rows):
        bench_conn.execute(
            "UPDATE runs SET score_multilevel = ?, score_multilevel_best5 = ?, "
            "gold_cluster = ?, proposed_cluster = ? WHERE id = ?",
            (r["level"], r.get("best_level", r["level"]),
             r["gold_cluster"], r["proposed_cluster"], row[0])
        )
    bench_conn.commit()
    print(f"  Updated {len(results)} runs")

    return results


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("tool_id", nargs="?", default="hpo19b")
    parser.add_argument("--all", action="store_true")
    parser.add_argument("--tools", nargs="+", help="Multiple tool_ids to compare")
    args = parser.parse_args()

    print("Loading BioLORD-2023...")
    model = SentenceTransformer(MODEL_NAME)

    import sqlite_vec
    syn_conn = sqlite3.connect(SYNDROME_DB)
    syn_conn.enable_load_extension(True)
    sqlite_vec.load(syn_conn)

    bench_conn = sqlite3.connect(BENCH_DB)
    bench_conn.row_factory = sqlite3.Row

    # Load syndrome embeddings once
    syndrome_data = load_syndrome_embeddings(syn_conn, model)

    if args.all:
        tool_ids = [r[0] for r in bench_conn.execute(
            "SELECT DISTINCT tool_id FROM runs ORDER BY tool_id"
        ).fetchall()]
    elif args.tools:
        tool_ids = args.tools
    else:
        tool_ids = [args.tool_id]

    all_results = {}
    for tid in tool_ids:
        print(f"\n{'#'*80}")
        print(f"# {tid}")
        print(f"{'#'*80}")
        results = score_tool(tid, bench_conn, syn_conn, model, syndrome_data)
        if results:
            all_results[tid] = results

    # Comparison table if multiple tools
    if len(all_results) > 1:
        print(f"\n{'='*100}")
        print(f"COMPARAISON MULTI-MODÈLES")
        print(f"{'='*100}")
        print(f"{'Tool ID':<30s} {'N':>4s} {'Exact':>6s} {'Fam':>6s} {'Cadre':>6s} {'Hors':>6s} {'Utile':>7s} {'MB-OK':>6s}")
        print("-" * 80)

        for tid, results in sorted(all_results.items()):
            n = len(results)
            lc = Counter(r["level"] for r in results)
            mb = sum(1 for r in results if r["match_b"])
            useful = lc[3] + lc[2]
            print(f"  {tid:<28s} {n:>4d} {lc[3]/n*100:>5.1f}% {lc[2]/n*100:>5.1f}% "
                  f"{lc[1]/n*100:>5.1f}% {lc[0]/n*100:>5.1f}% {useful/n*100:>6.1f}% {mb/n*100:>5.1f}%")

    syn_conn.close()
    bench_conn.close()
    print("\nDone.")


if __name__ == "__main__":
    main()
