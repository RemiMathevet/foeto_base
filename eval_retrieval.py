#!/usr/bin/env python3
"""Retrieval seul (matrice de convergence, sans LLM) sur les cas du banc.

Sert de mesure avant/apres un changement de corpus : gold_rank par cas, hit@1,
hit@k. Reutilise bench_pipeline.load_v1_cases / run_retrieval tels quels.

Usage : python3 eval_retrieval.py <sortie.json> [--n 20] [--top 20]
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from bench_pipeline import load_v1_cases, run_retrieval


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("out")
    ap.add_argument("--n", type=int, default=20)
    ap.add_argument("--top", type=int, default=20)
    a = ap.parse_args()
    cases = load_v1_cases(a.n)
    results, elapsed = run_retrieval(cases, top_k=a.top)
    ranks = {r["case_id"]: r["gold_rank_retrieval"] for r in results}
    json.dump({"n": len(cases), "top": a.top, "elapsed_s": elapsed, "ranks": ranks,
               "hit1": sum(1 for v in ranks.values() if v == 1),
               "hitk": sum(1 for v in ranks.values() if v is not None)},
              open(a.out, "w"), indent=1)
    print(f"-> {a.out}")


if __name__ == "__main__":
    main()
