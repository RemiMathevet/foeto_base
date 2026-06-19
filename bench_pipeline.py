#!/usr/bin/env python3
"""Pipeline benchmark : BioLORD retrieval → LLM re-ranking (Magos).

1. Charge BioLORD sur GPU, fait le retrieval matrice de convergence sur 25 cas v1.0
2. Libère le GPU (BioLORD déchargé)
3. Démarre Magos en background
4. Soumet les jobs de re-ranking au 35B puis au 27B
5. Affiche les résultats comparatifs et envoie par mail

Usage:
    python bench_pipeline.py
    python bench_pipeline.py --top 10 --models Qwen3.6-35B Qwen3.6-27B
    python bench_pipeline.py --skip-retrieval results.json   # reprend depuis un JSON existant
"""
import argparse
import json
import os
import signal
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

import requests

BENCH_DB = "/home/mathevet/Bureau/benchmark_foeto/foeto_bench.db"
SYND_DB = str(Path(__file__).resolve().parent / "syndromes_foetaux.db")
MAGOS_URL = "http://localhost:8200"
MAGOS_DIR = Path("/home/mathevet/Bureau/magos")
VENV_PYTHON = os.path.expanduser("~/Bureau/venv/bin/python3")
OUTPUT_DIR = Path(__file__).resolve().parent / "bench_results"

RERANK_SYSTEM = """Tu es un expert en fœtopathologie et dysmorphologie fœtale.
On te donne une vignette clinique fœtale et une liste de syndromes candidats issus d'un système de retrieval.
Tu dois re-classer ces candidats du plus probable au moins probable, en te basant sur la concordance phénotypique.

Réponds UNIQUEMENT avec un JSON array des syndrome_id triés du plus probable au moins probable.
Exemple: ["ORPHA:123", "ORPHA:456", "ORPHA:789"]

Ne donne aucune explication, juste le JSON array."""

RERANK_PROMPT_TEMPLATE = """## Vignette clinique

{clinical_text}

## Candidats (issus du retrieval, ordre initial)

{candidates_text}

## Ta tâche

Re-classe ces {n_candidates} syndromes du plus probable au moins probable. Réponds UNIQUEMENT avec un JSON array des syndrome_id."""


def load_v1_cases(n=25):
    conn = sqlite3.connect(BENCH_DB)
    conn.row_factory = sqlite3.Row
    cases = conn.execute("""
        SELECT id, clinical_text, gold_diagnosis, gold_orpha, syndrome_name
        FROM cases
        WHERE is_truncated = 0 AND length(clinical_text) > 50
          AND syndrome_name NOT LIKE '%|%'
        ORDER BY id
        LIMIT ?
    """, (n,)).fetchall()
    conn.close()
    return [dict(c) for c in cases]


def run_retrieval(cases, top_k=10):
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from convergence_matrix import ConvergenceMatrix

    print(f"\n{'='*70}")
    print(f"PHASE 1 — RETRIEVAL BioLORD ({len(cases)} cas, top-{top_k})")
    print(f"{'='*70}")

    cm = ConvergenceMatrix()
    print(f"Chunk→syndrome mapping: {cm._n_mapped}/{cm._n_total}")

    texts = [c["clinical_text"] for c in cases]
    t0 = time.time()
    batch_results = cm.query_batch(texts, top_k=top_k)
    elapsed = time.time() - t0

    results = []
    exact_t1 = exact_tk = 0
    for i, case in enumerate(cases):
        candidates = batch_results[i]
        gold_orpha = case["gold_orpha"]

        gold_rank = None
        for j, cand in enumerate(candidates):
            if cand["syndrome_id"] == gold_orpha:
                gold_rank = j + 1
                break

        if gold_rank == 1:
            exact_t1 += 1
        if gold_rank is not None:
            exact_tk += 1

        results.append({
            "case_id": case["id"],
            "gold_diagnosis": case["gold_diagnosis"],
            "gold_orpha": gold_orpha,
            "clinical_text": case["clinical_text"],
            "gold_rank_retrieval": gold_rank,
            "candidates": candidates,
        })

    cm.close()

    n = len(cases)
    print(f"\nRETRIEVAL — {n} cas, top-{top_k} (ORPHA scoring)")
    print(f"  Top-1 EXACT : {exact_t1}/{n} ({exact_t1/n*100:.0f}%)")
    print(f"  Top-{top_k} EXACT: {exact_tk}/{n} ({exact_tk/n*100:.0f}%)")

    return results, elapsed


def wait_magos_ready(timeout=120):
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            r = requests.get(f"{MAGOS_URL}/health", timeout=2)
            if r.status_code == 200:
                return True
        except requests.RequestException:
            pass
        time.sleep(2)
    return False


def start_magos():
    print("\nDémarrage de Magos en background...")
    proc = subprocess.Popen(
        [VENV_PYTHON, str(MAGOS_DIR / "magos.py")],
        cwd=str(MAGOS_DIR),
        stdout=open(MAGOS_DIR / "magos_bench.log", "w"),
        stderr=subprocess.STDOUT,
        preexec_fn=os.setpgrp,
    )
    print(f"  Magos PID: {proc.pid}")
    if not wait_magos_ready(timeout=30):
        raise RuntimeError("Magos ne répond pas après 30s")
    print("  Magos prêt.")
    return proc


def stop_magos(proc):
    print("\nArrêt de Magos...")
    try:
        os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
        proc.wait(timeout=15)
    except Exception:
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
        except Exception:
            pass
    print("  Magos arrêté.")


def submit_rerank_job(case_result, model):
    candidates = case_result["candidates"]
    candidates_text = "\n".join(
        f"  {j+1}. {c['syndrome_id']} — {c['name']} (RRF={c['rrf_score']:.4f}, canaux={c['n_channels']})"
        for j, c in enumerate(candidates)
    )
    prompt = RERANK_PROMPT_TEMPLATE.format(
        clinical_text=case_result["clinical_text"][:3000],
        candidates_text=candidates_text,
        n_candidates=len(candidates),
    )

    payload = {
        "model": model,
        "prompt": prompt,
        "system": RERANK_SYSTEM,
        "priority": 3,
        "timeout_s": 600,
        "client_id": "bench_pipeline",
        "options": {"temperature": 0.1},
    }

    r = requests.post(f"{MAGOS_URL}/jobs", json=payload, timeout=10)
    r.raise_for_status()
    return r.json()["uuid"]


def wait_job(uuid, timeout=300):
    r = requests.get(
        f"{MAGOS_URL}/jobs/{uuid}/wait",
        params={"timeout": timeout, "include_content": "true"},
        timeout=timeout + 10,
    )
    r.raise_for_status()
    return r.json()


def parse_rerank_response(response_text):
    if not response_text:
        return []
    import re
    match = re.search(r'\[.*?\]', response_text, re.DOTALL)
    if not match:
        return []
    try:
        return json.loads(match.group())
    except json.JSONDecodeError:
        return []


def run_rerank(retrieval_results, model):
    n = len(retrieval_results)
    print(f"\n{'='*70}")
    print(f"RE-RANKING avec {model} ({n} cas)")
    print(f"{'='*70}")

    rerank_results = []
    exact_t1 = exact_tk = 0

    for i, res in enumerate(retrieval_results):
        uuid = submit_rerank_job(res, model)
        print(f"  [{i+1}/{n}] {res['case_id']} → job {uuid}", end="", flush=True)
        job = wait_job(uuid, timeout=600)
        case = res
        gold_orpha = case["gold_orpha"]

        if job["status"] != "done":
            print(f" ERREUR: {job.get('error', 'unknown')}")
            rerank_results.append({
                "case_id": case["case_id"],
                "gold_rank_rerank": None,
                "reranked_order": [],
                "status": "error",
                "error": job.get("error"),
            })
            continue

        response = job.get("response", "")
        reranked = parse_rerank_response(response)

        gold_rank = None
        for j, sid in enumerate(reranked):
            if sid == gold_orpha:
                gold_rank = j + 1
                break

        if gold_rank == 1:
            exact_t1 += 1
        if gold_rank is not None:
            exact_tk += 1

        rerank_results.append({
            "case_id": case["case_id"],
            "gold_rank_rerank": gold_rank,
            "reranked_order": reranked,
            "status": "done",
            "tokens_in": job.get("tokens_in"),
            "tokens_out": job.get("tokens_out"),
            "duration_s": job.get("duration_s"),
        })

        rank_str = str(gold_rank) if gold_rank else "-"
        retrieval_rank = case["gold_rank_retrieval"]
        ret_str = str(retrieval_rank) if retrieval_rank else "-"
        delta = ""
        if gold_rank and retrieval_rank:
            d = retrieval_rank - gold_rank
            delta = f" ({'+'if d>0 else ''}{d})" if d != 0 else " (=)"
        dur = job.get("duration_s", 0) or 0
        print(f" → ret={ret_str} rr={rank_str}{delta} ({dur:.0f}s)")

    print(f"\n{model} — RÉSULTATS")
    print(f"  Top-1 EXACT : {exact_t1}/{n} ({exact_t1/n*100:.0f}%)")
    print(f"  Top-K EXACT : {exact_tk}/{n} ({exact_tk/n*100:.0f}%)")

    return rerank_results, exact_t1, exact_tk


def format_report(retrieval_results, all_rerank, retrieval_elapsed, models):
    n = len(retrieval_results)
    lines = []
    lines.append(f"BENCHMARK PIPELINE — {n} cas v1.0, {time.strftime('%Y-%m-%d %H:%M')}")
    lines.append("=" * 70)

    # Retrieval stats
    ret_t1 = sum(1 for r in retrieval_results if r["gold_rank_retrieval"] == 1)
    ret_tk = sum(1 for r in retrieval_results if r["gold_rank_retrieval"] is not None)
    top_k = len(retrieval_results[0]["candidates"]) if retrieval_results else 10
    lines.append(f"\nRETRIEVAL (BioLORD 5-channel RRF, {retrieval_elapsed:.1f}s)")
    lines.append(f"  Top-1 : {ret_t1}/{n} ({ret_t1/n*100:.0f}%)")
    lines.append(f"  Top-{top_k}: {ret_tk}/{n} ({ret_tk/n*100:.0f}%)")

    for model in models:
        rr = all_rerank[model]
        t1 = sum(1 for r in rr if r.get("gold_rank_rerank") == 1)
        tk = sum(1 for r in rr if r.get("gold_rank_rerank") is not None)
        errors = sum(1 for r in rr if r.get("status") == "error")
        lines.append(f"\nRE-RANKING — {model}")
        lines.append(f"  Top-1 : {t1}/{n} ({t1/n*100:.0f}%)")
        lines.append(f"  Top-K : {tk}/{n} ({tk/n*100:.0f}%)")
        if errors:
            lines.append(f"  Erreurs: {errors}")

    lines.append(f"\n{'Case':<22s} {'Gold':<35s} {'Ret':>4s}", )
    for model in models:
        short = model.split("-")[0][:5] + model.split("-")[-1][:4]
        lines.append(f" {short:>6s}")
    lines.append("")
    lines.append("-" * (65 + 7 * len(models)))

    # Per-case detail
    detail_lines = []
    for i, ret in enumerate(retrieval_results):
        ret_rank = str(ret["gold_rank_retrieval"]) if ret["gold_rank_retrieval"] else "-"
        line = f"  {ret['case_id']:<20s} {ret['gold_diagnosis'][:33]:<35s} {ret_rank:>4s}"
        for model in models:
            rr = all_rerank[model][i]
            rr_rank = str(rr["gold_rank_rerank"]) if rr.get("gold_rank_rerank") else "-"
            line += f" {rr_rank:>6s}"
        detail_lines.append(line)

    # Rebuild header as single string
    header = f"{'Case':<22s} {'Gold':<35s} {'Ret':>4s}"
    for model in models:
        short = model.replace("Qwen3.6-", "Q")
        header += f" {short:>6s}"
    lines_final = lines[:lines.index(f"\n{'Case':<22s} {'Gold':<35s} {'Ret':>4s}")]
    lines_final.append(f"\n{header}")
    lines_final.append("-" * len(header))
    lines_final.extend(detail_lines)

    return "\n".join(lines_final)


def send_report(report_text, html=None):
    sys.path.insert(0, "/home/mathevet/Bureau/tmux_supervisor/embeddings/pipeline_v2")
    from importlib import import_module
    notify = import_module("08_notify")
    notify.send_email(
        subject=f"[FoetoBase] Benchmark pipeline — {time.strftime('%d/%m %H:%M')}",
        body=report_text,
        to="remimathevet@gmail.com",
    )
    print("\nRapport envoyé par mail.")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--top", type=int, default=10)
    parser.add_argument("--n-cases", type=int, default=25)
    parser.add_argument("--models", nargs="+", default=["Qwen3.6-35B", "Qwen3.6-27B"])
    parser.add_argument("--skip-retrieval", type=str, default=None,
                        help="Path to existing retrieval JSON to skip phase 1")
    parser.add_argument("--no-mail", action="store_true")
    args = parser.parse_args()

    OUTPUT_DIR.mkdir(exist_ok=True)

    if args.skip_retrieval:
        print(f"Chargement retrieval depuis {args.skip_retrieval}")
        with open(args.skip_retrieval) as f:
            data = json.load(f)
        retrieval_results = data["cases"]
        retrieval_elapsed = data.get("elapsed_s", 0)
    else:
        cases = load_v1_cases(args.n_cases)
        print(f"Chargé {len(cases)} cas v1.0")
        retrieval_results, retrieval_elapsed = run_retrieval(cases, top_k=args.top)

        out_path = OUTPUT_DIR / f"retrieval_{int(time.time())}.json"
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump({
                "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
                "n_cases": len(cases),
                "top_k": args.top,
                "elapsed_s": retrieval_elapsed,
                "cases": retrieval_results,
            }, f, ensure_ascii=False, indent=2)
        print(f"\nRetrieval sauvé → {out_path}")

    import gc
    import torch
    gc.collect()
    if torch.cuda.is_available():
        torch.cuda.empty_cache()
    print("\nGPU libéré (BioLORD déchargé).")

    magos_proc = start_magos()
    all_rerank = {}

    try:
        for model in args.models:
            rerank_results, t1, tk = run_rerank(retrieval_results, model)
            all_rerank[model] = rerank_results
    finally:
        stop_magos(magos_proc)

    report = format_report(retrieval_results, all_rerank, retrieval_elapsed, args.models)
    print(f"\n{report}")

    full_out = OUTPUT_DIR / f"pipeline_{int(time.time())}.json"
    with open(full_out, "w", encoding="utf-8") as f:
        json.dump({
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
            "models": args.models,
            "retrieval_elapsed_s": retrieval_elapsed,
            "retrieval": retrieval_results,
            "rerank": {m: all_rerank[m] for m in args.models},
        }, f, ensure_ascii=False, indent=2)
    print(f"\nRésultats complets → {full_out}")

    if not args.no_mail:
        send_report(report)


if __name__ == "__main__":
    main()
