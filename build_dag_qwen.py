#!/usr/bin/env python3
"""Build foeto_terms DAG (parent_id + foeto_edges) using Qwen3.6-35B local.

Groups terms by organe×type_patho, sends batches to llama-server,
parses JSON from reasoning_content, stores results.

Usage:
    python build_dag_qwen.py                  # dry-run (print JSON, don't write)
    python build_dag_qwen.py --apply          # write to DB
    python build_dag_qwen.py --apply --organ cerveau  # single organ
    python build_dag_qwen.py --resume         # skip already-processed batches
"""

import argparse
import json
import os
import re
import sqlite3
import sys
import time
from pathlib import Path

import requests

DB = str(Path(__file__).resolve().parent / "syndromes_foetaux.db")
LLM_URL = "http://127.0.0.1:8081/v1/chat/completions"
MODEL = "Qwen3.6-35B"
BATCH_SIZE = 10
MAX_TOKENS = 8000

SYSTEM_PROMPT = """Tu es expert en fœtopathologie. Pour un groupe de termes, propose la hiérarchie et les liens.

Réponds UNIQUEMENT avec un bloc ```json contenant:
{"terms":[{"id":"FOETO:...","parent_id":"FOETO:..." ou null,"edges":[{"target":"FOETO:...","relation":"..."}]}],"new_parents":[{"label_fr":"...","organe":"...","children_ids":["FOETO:..."]}]}

Règles:
- parent_id parmi la liste fournie ou null
- new_parents seulement si ≥3 enfants possibles
- relations: diagnostic_différentiel, composante_de, évolution_de, associé_à
- Que les relations cliniquement significatives"""


def get_batches(conn, organ_filter=None):
    """Group terms by organe×type_patho, yield batches of ≤BATCH_SIZE."""
    where = ""
    params = []
    if organ_filter:
        where = " WHERE organe = ?"
        params = [organ_filter]

    groups = conn.execute(
        f"SELECT organe, COALESCE(type_patho, '__none__') as tp, COUNT(*) as n "
        f"FROM foeto_terms{where} GROUP BY organe, tp ORDER BY organe, tp",
        params,
    ).fetchall()

    for organe, tp, n in groups:
        tp_real = None if tp == "__none__" else tp
        where_g = "WHERE organe = ? AND type_patho IS ?"
        params_g = [organe, tp_real]
        if tp_real is not None:
            where_g = "WHERE organe = ? AND type_patho = ?"

        terms = conn.execute(
            f"SELECT id, label_fr, label_en, axis, sous_type_patho, description_fr "
            f"FROM foeto_terms {where_g} ORDER BY id",
            params_g,
        ).fetchall()

        for i in range(0, len(terms), BATCH_SIZE):
            batch = terms[i : i + BATCH_SIZE]
            yield organe, tp_real, batch


def format_batch(organe, type_patho, terms):
    """Build the user prompt for a batch."""
    lines = [f"Organe: {organe} | Type patho: {type_patho or '(non typé)'}",
             f"{len(terms)} termes:\n"]
    for t in terms:
        desc = (t[5] or "")[:80].replace("\n", " ")
        line = f"- {t[0]} | {t[1] or t[2] or '?'}"
        if t[3]:
            line += f" | axe={t[3]}"
        if t[4]:
            line += f" | sous_type={t[4]}"
        if desc:
            line += f" | desc: {desc}"
        lines.append(line)
    return "\n".join(lines)


def _extract_json(text):
    """Extract JSON from LLM output (may be in reasoning with markdown)."""
    # Try ```json blocks first (last one wins)
    blocks = re.findall(r"```json\s*([\s\S]*?)```", text)
    for block in reversed(blocks):
        try:
            return json.loads(block)
        except json.JSONDecodeError:
            continue

    # Try balanced brace extraction starting from {"terms"
    for m in re.finditer(r'\{"terms"', text):
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

    # Try bare array
    for m in re.finditer(r"\[", text):
        start = m.start()
        depth = 0
        for i in range(start, len(text)):
            if text[i] == "[":
                depth += 1
            elif text[i] == "]":
                depth -= 1
                if depth == 0:
                    try:
                        arr = json.loads(text[start : i + 1])
                        if isinstance(arr, list) and arr:
                            return {"terms": arr, "new_parents": []}
                    except json.JSONDecodeError:
                        break

    return None


def call_llm(prompt, retries=2):
    """Call llama-server, extract JSON from reasoning_content or content."""
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
            tokens = data.get("usage", {})
            elapsed = data.get("timings", {}).get("predicted_ms", 0) / 1000

            parsed = _extract_json(text)
            if parsed:
                return parsed, tokens, elapsed

            if attempt < retries:
                print(f"  [retry {attempt+1}] no JSON found, retrying...", file=sys.stderr)
                continue
            return None, tokens, elapsed

        except Exception as e:
            if attempt < retries:
                print(f"  [retry {attempt+1}] error: {e}", file=sys.stderr)
                time.sleep(2)
                continue
            print(f"  [FAIL] {e}", file=sys.stderr)
            return None, {}, 0


def apply_results(conn, result):
    """Write parent_id and edges to DB."""
    n_parent = 0
    n_edge = 0

    conn.execute("""
        CREATE TABLE IF NOT EXISTS foeto_edges (
            source_id TEXT NOT NULL,
            target_id TEXT NOT NULL,
            relation TEXT NOT NULL,
            confidence REAL DEFAULT 1.0,
            source TEXT DEFAULT 'qwen_dag',
            PRIMARY KEY (source_id, target_id, relation)
        )
    """)

    for t in result.get("terms", []):
        pid = t.get("parent_id")
        if pid:
            existing = conn.execute(
                "SELECT parent_id FROM foeto_terms WHERE id = ?", (t["id"],)
            ).fetchone()
            if existing and existing[0] is None:
                conn.execute(
                    "UPDATE foeto_terms SET parent_id = ? WHERE id = ? AND parent_id IS NULL",
                    (pid, t["id"]),
                )
                n_parent += 1

        for e in t.get("edges", []):
            try:
                conn.execute(
                    "INSERT OR IGNORE INTO foeto_edges (source_id, target_id, relation) VALUES (?, ?, ?)",
                    (t["id"], e["target"], e["relation"]),
                )
                n_edge += 1
            except sqlite3.IntegrityError:
                pass

    for np in result.get("new_parents", []):
        label = np.get("label_fr", "")
        organe = np.get("organe", "")
        if label and len(np.get("children_ids", [])) >= 3:
            print(f"  SUGGESTED PARENT: {label} ({organe}) -> {np['children_ids']}")

    return n_parent, n_edge


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true", help="Write results to DB")
    parser.add_argument("--organ", help="Process single organ only")
    parser.add_argument("--resume", action="store_true", help="Skip batches with existing edges")
    args = parser.parse_args()

    conn = sqlite3.connect(DB)
    conn.execute("PRAGMA journal_mode=WAL")

    batches = list(get_batches(conn, args.organ))
    total = len(batches)
    total_terms = sum(len(b[2]) for b in batches)

    print(f"{'DRY RUN' if not args.apply else 'APPLY'} — {total} batches, {total_terms} terms")
    print(f"Estimated time: {total * 30 // 60}–{total * 45 // 60} min\n")

    total_parents = 0
    total_edges = 0
    total_time = 0
    skipped = 0

    for i, (organe, tp, terms) in enumerate(batches):
        batch_ids = [t[0] for t in terms]
        label = f"[{i+1}/{total}] {organe}/{tp or 'none'} ({len(terms)} terms)"

        if args.resume:
            has_edges = conn.execute(
                f"SELECT COUNT(*) FROM foeto_edges WHERE source_id IN ({','.join('?'*len(batch_ids))})",
                batch_ids,
            ).fetchone()[0]
            if has_edges > 0:
                skipped += 1
                continue

        prompt = format_batch(organe, tp, terms)
        result, tokens, elapsed = call_llm(prompt)
        total_time += elapsed

        if result is None:
            print(f"  {label} — FAILED (no JSON)")
            continue

        n_terms_out = len(result.get("terms", []))
        n_edges_out = sum(len(t.get("edges", [])) for t in result.get("terms", []))
        n_parents_out = sum(1 for t in result.get("terms", []) if t.get("parent_id"))

        print(f"  {label} — {n_parents_out} parents, {n_edges_out} edges, {elapsed:.1f}s, "
              f"tokens={tokens.get('completion_tokens', '?')}")

        if args.apply:
            np, ne = apply_results(conn, result)
            total_parents += np
            total_edges += ne
            if (i + 1) % 10 == 0:
                conn.commit()
        else:
            if i < 3:
                print(json.dumps(result, ensure_ascii=False, indent=2)[:800])

    if args.apply:
        conn.commit()

    print(f"\n{'='*50}")
    print(f"Done in {total_time:.0f}s ({total_time/60:.1f} min)")
    if skipped:
        print(f"Skipped: {skipped} batches (resume)")
    if args.apply:
        print(f"Applied: {total_parents} parent_id, {total_edges} edges")
        n_with_parent = conn.execute(
            "SELECT COUNT(*) FROM foeto_terms WHERE parent_id IS NOT NULL"
        ).fetchone()[0]
        n_edges = conn.execute(
            "SELECT COUNT(*) FROM foeto_edges"
        ).fetchone()[0]
        print(f"DB state: {n_with_parent} terms with parent, {n_edges} total edges")

    conn.close()


if __name__ == "__main__":
    main()
