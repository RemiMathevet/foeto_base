#!/usr/bin/env python3
"""DAG pass 2: inter-organ edges with BioLORD RAG context.

Pre-embeds all foeto_term labels with BioLORD, then for each organ batch:
  1. Finds top-5 book chunks via vec_chunks similarity
  2. Finds top-20 most similar terms from OTHER organs
  3. Sends batch + candidates + book context to Qwen3.6-35B
  4. Stores inter-organ edges in foeto_edges (source='qwen_dag_p2')

Usage:
    python build_dag_qwen_p2.py                  # dry-run
    python build_dag_qwen_p2.py --apply          # write to DB
    python build_dag_qwen_p2.py --apply --organ cerveau
"""

import argparse
import json
import re
import sqlite3
import struct
import sys
import time
from pathlib import Path

import numpy as np
import requests

DB = str(Path(__file__).resolve().parent / "syndromes_foetaux.db")
LLM_URL = "http://127.0.0.1:8081/v1/chat/completions"
MODEL = "Qwen3.6-35B"
BATCH_SIZE = 10
MAX_TOKENS = 8000
TOP_K_CHUNKS = 5
TOP_K_CROSS = 20

SYSTEM_PROMPT = """Tu es expert en fœtopathologie. On te présente un groupe de termes d'un organe, des termes candidats d'AUTRES organes, et des extraits d'ouvrages de référence.

Propose UNIQUEMENT des liens INTER-ORGANES cliniquement significatifs.

Réponds avec un bloc ```json contenant:
{"edges":[{"source":"FOETO:...","target":"FOETO:...","relation":"...","confidence":0.0-1.0}]}

Règles:
- source = un terme du groupe principal, target = un terme candidat d'un AUTRE organe
- relations: diagnostic_différentiel, composante_de, évolution_de, associé_à
- confidence: 0.5=possible, 0.7=probable, 0.9=établi
- Ne propose QUE des liens dont tu es raisonnablement sûr, appuyés par le contexte fourni
- Pas de liens intra-organe (déjà faits en passe 1)"""


def serialize_vec(vec):
    return struct.pack(f"{len(vec)}f", *vec)


def _extract_json(text):
    blocks = re.findall(r"```json\s*([\s\S]*?)```", text)
    for block in reversed(blocks):
        try:
            return json.loads(block)
        except json.JSONDecodeError:
            continue
    for m in re.finditer(r'\{"edges"', text):
        start = m.start()
        depth = 0
        for i in range(start, len(text)):
            if text[i] == "{":
                depth += 1
            elif text[i] == "}":
                depth -= 1
                if depth == 0:
                    try:
                        return json.loads(text[start : i + 1])
                    except json.JSONDecodeError:
                        break
    return None


def call_llm(prompt, retries=2):
    for attempt in range(retries + 1):
        try:
            r = requests.post(
                LLM_URL,
                json={
                    "model": MODEL,
                    "messages": [
                        {"role": "system", "content": SYSTEM_PROMPT},
                        {"role": "user", "content": prompt},
                    ],
                    "max_tokens": MAX_TOKENS,
                    "temperature": 0.2,
                },
                timeout=180,
            )
            r.raise_for_status()
            data = r.json()
            msg = data["choices"][0]["message"]
            text = msg.get("content") or msg.get("reasoning_content") or ""
            tokens = data.get("usage", {}).get("completion_tokens", 0)

            parsed = _extract_json(text)
            if parsed:
                return parsed, tokens
            if attempt < retries:
                print(f"  [retry {attempt+1}] no JSON", file=sys.stderr)
                continue
            return None, tokens
        except Exception as e:
            if attempt < retries:
                print(f"  [retry {attempt+1}] {e}", file=sys.stderr)
                time.sleep(2)
                continue
            print(f"  [FAIL] {e}", file=sys.stderr)
            return None, 0


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--organ", help="Single organ")
    args = parser.parse_args()

    # --- Phase A: pre-embed all term labels with BioLORD ---
    print("Loading BioLORD-2023...", flush=True)
    from sentence_transformers import SentenceTransformer
    biolord = SentenceTransformer("FremyCompany/BioLORD-2023")

    import sqlite_vec
    conn = sqlite3.connect(DB)
    conn.enable_load_extension(True)
    sqlite_vec.load(conn)
    conn.execute("PRAGMA journal_mode=WAL")

    all_terms = conn.execute(
        "SELECT id, organe, label_fr, label_en, type_patho, sous_type_patho, description_fr FROM foeto_terms ORDER BY id"
    ).fetchall()
    term_map = {t[0]: t for t in all_terms}

    print(f"Embedding {len(all_terms)} term labels...", flush=True)
    labels = [t[2] or t[3] or t[0] for t in all_terms]
    term_embeds = biolord.encode(labels, batch_size=128, normalize_embeddings=True, show_progress_bar=True)
    term_embeds = np.array(term_embeds, dtype=np.float32)

    id_list = [t[0] for t in all_terms]
    organ_list = [t[1] for t in all_terms]
    id_to_idx = {tid: i for i, tid in enumerate(id_list)}

    # Free BioLORD from GPU (keep embeddings in RAM)
    del biolord
    import torch
    if torch.cuda.is_available():
        torch.cuda.empty_cache()
    print("BioLORD unloaded, embeddings cached in RAM.\n", flush=True)

    # --- Phase B: build batches and call LLM ---
    organs = [args.organ] if args.organ else sorted(set(organ_list))

    batches = []
    for org in organs:
        org_ids = [i for i, o in enumerate(organ_list) if o == org]
        for start in range(0, len(org_ids), BATCH_SIZE):
            batch_idxs = org_ids[start : start + BATCH_SIZE]
            batches.append((org, batch_idxs))

    total = len(batches)
    print(f"{'DRY RUN' if not args.apply else 'APPLY'} — {total} batches\n", flush=True)

    total_edges = 0
    total_time = 0
    failures = 0

    for bi, (org, batch_idxs) in enumerate(batches):
        t0 = time.time()
        batch_ids = [id_list[i] for i in batch_idxs]
        batch_terms = [term_map[tid] for tid in batch_ids]

        # Mean embedding of batch
        batch_emb = term_embeds[batch_idxs].mean(axis=0)
        batch_emb /= np.linalg.norm(batch_emb)

        # Top-K book chunks via vec_chunks
        emb_blob = serialize_vec(batch_emb)
        chunks = conn.execute(
            """SELECT cm.chunk_text, cm.title, vec_chunks.distance
               FROM vec_chunks
               JOIN chunk_meta cm ON cm.rowid = vec_chunks.rowid
               WHERE vec_chunks.embedding MATCH ? AND cm.source_type = 'book'
               AND k = ?
               ORDER BY vec_chunks.distance""",
            (emb_blob, TOP_K_CHUNKS),
        ).fetchall()

        # Top-K cross-organ terms by cosine similarity
        other_mask = np.array([o != org for o in organ_list])
        other_idxs = np.where(other_mask)[0]
        if len(other_idxs) == 0:
            continue
        sims = term_embeds[other_idxs] @ batch_emb
        top_k = min(TOP_K_CROSS, len(other_idxs))
        top_cross_idx = other_idxs[np.argsort(sims)[-top_k:][::-1]]
        cross_terms = [(id_list[i], term_map[id_list[i]]) for i in top_cross_idx]

        # Build prompt
        lines = [f"=== GROUPE PRINCIPAL: {org} ({len(batch_terms)} termes) ==="]
        for t in batch_terms:
            desc = (t[6] or "")[:100].replace("\n", " ")
            lines.append(f"- {t[0]} | {t[2] or t[3]} | type={t[4] or '?'} | {desc}")

        lines.append(f"\n=== CANDIDATS INTER-ORGANES ({len(cross_terms)} termes) ===")
        for tid, t in cross_terms:
            desc = (t[6] or "")[:80].replace("\n", " ")
            lines.append(f"- {tid} | {t[1]} | {t[2] or t[3]} | {desc}")

        lines.append(f"\n=== CONTEXTE OUVRAGES DE RÉFÉRENCE ({len(chunks)} extraits) ===")
        for chunk_text, title, dist in chunks:
            lines.append(f"[{title} | dist={dist:.3f}]")
            lines.append(chunk_text[:600])
            lines.append("")

        prompt = "\n".join(lines)

        result, tokens = call_llm(prompt)
        elapsed = time.time() - t0
        total_time += elapsed

        edges = result.get("edges", []) if result else []
        # Filter: only truly inter-organ
        valid_edges = []
        for e in edges:
            src_org = term_map.get(e.get("source"), [None, None])[1]
            tgt_org = term_map.get(e.get("target"), [None, None])[1]
            if src_org and tgt_org and src_org != tgt_org:
                valid_edges.append(e)

        label = f"[{bi+1}/{total}] {org} ({len(batch_terms)}t)"
        if result is None:
            failures += 1
            print(f"  {label} — FAIL | {elapsed:.1f}s", flush=True)
            continue

        print(
            f"  {label} — {len(valid_edges)} inter-edges | {tokens} tok | {elapsed:.1f}s",
            flush=True,
        )

        if args.apply and valid_edges:
            for e in valid_edges:
                try:
                    conn.execute(
                        "INSERT OR IGNORE INTO foeto_edges (source_id, target_id, relation, confidence, source) VALUES (?, ?, ?, ?, 'qwen_dag_p2')",
                        (e["source"], e["target"], e["relation"], e.get("confidence", 0.7)),
                    )
                except sqlite3.IntegrityError:
                    pass
            total_edges += len(valid_edges)

        if args.apply and (bi + 1) % 10 == 0:
            conn.commit()

    if args.apply:
        conn.commit()

    print(f"\n{'='*50}")
    print(f"Done in {total_time:.0f}s ({total_time/60:.1f} min)")
    print(f"Failures: {failures}")
    if args.apply:
        print(f"New inter-organ edges: {total_edges}")
        n_total = conn.execute("SELECT COUNT(*) FROM foeto_edges").fetchone()[0]
        n_inter = conn.execute(
            """SELECT COUNT(*) FROM foeto_edges e
               JOIN foeto_terms ts ON e.source_id = ts.id
               JOIN foeto_terms tt ON e.target_id = tt.id
               WHERE ts.organe != tt.organe"""
        ).fetchone()[0]
        print(f"DB state: {n_total} total edges, {n_inter} inter-organ")

    conn.close()


if __name__ == "__main__":
    main()
