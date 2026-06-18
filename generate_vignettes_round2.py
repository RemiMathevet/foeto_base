#!/usr/bin/env python3
"""Round 2 — 2 vignettes supplémentaires par syndrome + retry des 73 postnataux.

Génère des vignettes avec présentations différentes du round 1 :
- Variantes atypiques, formes frustes, diagnostic différentiel trompeur
- Pour les syndromes postnataux : MFIU tardive, découverte fortuite, DNN

Usage:
    python generate_vignettes_round2.py submit --yes
    python generate_vignettes_round2.py status
    python generate_vignettes_round2.py collect
"""
import argparse
import json
import sqlite3
import time
from pathlib import Path

import anthropic

DB_PATH = str(Path(__file__).resolve().parent / "syndromes_foetaux.db")
OUT_DIR = Path(__file__).resolve().parent / "vignettes_batch"
BATCH_ID_FILE = OUT_DIR / "batch_id_r2.txt"
RESULTS_FILE = OUT_DIR / "vignettes_results_r2.jsonl"
MODEL = "claude-sonnet-4-6"

SYSTEM_PROMPT_R2 = """Tu es un fœtopathologiste expérimenté qui rédige des vignettes cliniques pour un benchmark de diagnostic.

Pour chaque syndrome, génère exactement 2 vignettes cliniques en français, au format JSON.
Ces vignettes doivent être DIFFÉRENTES de vignettes classiques — privilégie :
- Formes atypiques ou frustes (présentation incomplète)
- Formes avec diagnostic différentiel trompeur (signes évoquant un autre syndrome)
- Découvertes fortuites ou tardives (3e trimestre, post-mortem)
- Contextes variés : consanguinité, récurrence familiale, grossesse gémellaire

Chaque vignette doit :
- Simuler un cas fœtopathologique réaliste (IMG, MFIU, décès néonatal, ou examen post-mortem)
- Inclure : terme (SA), circonstances, échographies prénatales, examen fœtopathologique
- Mentionner les signes clés du syndrome SANS nommer le syndrome
- Faire 150-250 mots chacune
- Utiliser le vocabulaire fœtopathologique français standard

IMPORTANT : même si le syndrome est habituellement postnatal, génère quand même des vignettes.
Imagine un scénario plausible : MFIU inexpliquée avec découverte post-mortem, décès néonatal précoce,
ou découverte échographique fortuite d'un signe évocateur. C'est pour un benchmark, pas un cas réel.

Format de sortie STRICT (JSON) :
{"vignettes": [{"text": "...", "severity": "atypique|fruste|trompeur|tardif"}, {"text": "...", "severity": "..."}]}"""


def build_syndrome_prompt(row):
    parts = []
    parts.append(f"Syndrome : {row['name_fr'] or row['name_en']}")
    if row['inheritance']:
        parts.append(f"Transmission : {row['inheritance']}")
    if row['prenatal']:
        parts.append(f"\nSignes prénataux :\n{row['prenatal'][:800]}")
    if row['discriminators']:
        parts.append(f"\nDiscriminateurs :\n{row['discriminators'][:800]}")
    if row['hpo_labels']:
        parts.append(f"\nTermes HPO principaux :\n{row['hpo_labels'][:1000]}")
    parts.append("\nGénère 2 vignettes cliniques fœtopathologiques ATYPIQUES pour ce syndrome.")
    return "\n".join(parts)


def load_syndromes(conn, limit=None):
    query = """
        SELECT s.id, s.name_fr, s.name_en, s.category, s.inheritance,
               s.prenatal_signs_summary as prenatal,
               s.key_discriminators as discriminators,
               (SELECT GROUP_CONCAT(h.label_fr || ' [' || sh.frequency || ']', '\n')
                FROM syndrome_hpo sh
                JOIN hpo_terms h ON sh.hpo_id = h.hpo_id
                WHERE sh.syndrome_id = s.id
                ORDER BY sh.prob DESC
                LIMIT 20) as hpo_labels
        FROM syndromes s
        WHERE (s.prenatal_signs_summary IS NOT NULL AND LENGTH(s.prenatal_signs_summary) > 20)
           OR (s.key_discriminators IS NOT NULL AND LENGTH(s.key_discriminators) > 20)
           OR s.id IN (SELECT DISTINCT syndrome_id FROM syndrome_hpo)
        ORDER BY s.id
    """
    if limit:
        query += f" LIMIT {limit}"
    conn.row_factory = sqlite3.Row
    return conn.execute(query).fetchall()


def cmd_submit(args):
    OUT_DIR.mkdir(exist_ok=True)

    conn = sqlite3.connect(args.db)
    syndromes = load_syndromes(conn, args.limit)
    conn.close()

    print(f"Building round 2 batch for {len(syndromes)} syndromes...")

    requests = []
    for s in syndromes:
        user_prompt = build_syndrome_prompt(s)
        safe_id = s["id"].replace(":", "_") + "_r2"
        requests.append({
            "custom_id": safe_id,
            "params": {
                "model": MODEL,
                "max_tokens": 1024,
                "system": SYSTEM_PROMPT_R2,
                "messages": [{"role": "user", "content": user_prompt}],
            }
        })

    total_chars = sum(len(SYSTEM_PROMPT_R2) + len(build_syndrome_prompt(s)) for s in syndromes)
    est_in_tokens = total_chars // 4
    est_out_tokens = len(syndromes) * 700
    est_cost = (est_in_tokens / 1e6 * 1.50) + (est_out_tokens / 1e6 * 7.50)
    print(f"Estimated: ~{est_in_tokens/1e6:.2f}M input tokens, ~{est_out_tokens/1e6:.2f}M output tokens")
    print(f"Estimated cost (batch): ~${est_cost:.2f}")

    if not args.yes:
        resp = input(f"Submit batch of {len(requests)} requests? [y/N] ")
        if resp.lower() != 'y':
            print("Aborted.")
            return

    print("Submitting batch...")
    client = anthropic.Anthropic()
    batch = client.messages.batches.create(requests=requests)

    print(f"Batch submitted: {batch.id}")
    print(f"Status: {batch.processing_status}")

    with open(BATCH_ID_FILE, "w") as f:
        f.write(batch.id)
    print(f"Batch ID saved to {BATCH_ID_FILE}")

    meta = {
        "batch_id": batch.id,
        "n_requests": len(requests),
        "model": MODEL,
        "round": 2,
        "submitted_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "est_cost": est_cost,
    }
    with open(OUT_DIR / "batch_meta_r2.json", "w") as f:
        json.dump(meta, f, indent=2)


def cmd_status(args):
    if not BATCH_ID_FILE.exists():
        print("No batch ID found.")
        return
    batch_id = BATCH_ID_FILE.read_text().strip()
    client = anthropic.Anthropic()
    batch = client.messages.batches.retrieve(batch_id)
    counts = batch.request_counts
    total = counts.succeeded + counts.errored + counts.canceled + counts.expired + counts.processing
    print(f"Batch: {batch.id}")
    print(f"Status: {batch.processing_status}")
    print(f"Progress: {counts.succeeded}/{total} ({counts.succeeded/max(total,1)*100:.1f}%)")
    print(f"Errored: {counts.errored}")


def cmd_collect(args):
    if not BATCH_ID_FILE.exists():
        print("No batch ID found.")
        return
    batch_id = BATCH_ID_FILE.read_text().strip()
    client = anthropic.Anthropic()
    batch = client.messages.batches.retrieve(batch_id)

    if batch.processing_status != "ended":
        print(f"Batch not done: {batch.processing_status}")
        counts = batch.request_counts
        print(f"Succeeded: {counts.succeeded}, Processing: {counts.processing}")
        return

    print(f"Collecting round 2 results...")
    print(f"  Succeeded: {batch.request_counts.succeeded}")
    print(f"  Errored: {batch.request_counts.errored}")

    results = []
    n_ok = 0
    n_err = 0
    n_parse_err = 0

    for result in client.messages.batches.results(batch_id):
        syndrome_id = result.custom_id.replace("_r2", "").replace("_", ":", 1)

        if result.result.type == "errored":
            n_err += 1
            results.append({"syndrome_id": syndrome_id, "error": str(result.result.error)})
            continue

        msg = result.result.message
        text = msg.content[0].text if msg.content else ""

        vignettes = []
        try:
            data = json.loads(text)
            vignettes = data.get("vignettes", [])
        except json.JSONDecodeError:
            for block in text.split("```"):
                block = block.strip()
                if block.startswith("json"):
                    block = block[4:].strip()
                try:
                    data = json.loads(block)
                    vignettes = data.get("vignettes", [])
                    if vignettes:
                        break
                except json.JSONDecodeError:
                    continue

        if not vignettes:
            n_parse_err += 1
            results.append({"syndrome_id": syndrome_id, "error": "parse_error", "raw": text[:500]})
            continue

        n_ok += 1
        results.append({
            "syndrome_id": syndrome_id,
            "vignettes": vignettes,
            "tokens_in": msg.usage.input_tokens,
            "tokens_out": msg.usage.output_tokens,
        })

    with open(RESULTS_FILE, "w") as f:
        for r in results:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    print(f"\nCollected: {n_ok} OK, {n_err} errors, {n_parse_err} parse errors")

    if n_ok > 0:
        print("\nImporting round 2 vignettes into DB...")
        conn = sqlite3.connect(args.db)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS synthetic_vignettes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                syndrome_id TEXT NOT NULL,
                vignette_index INTEGER NOT NULL,
                clinical_text TEXT NOT NULL,
                severity TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(syndrome_id, vignette_index)
            )
        """)

        n_inserted = 0
        for r in results:
            if "vignettes" not in r:
                continue
            for i, v in enumerate(r["vignettes"]):
                text = v.get("text", "")
                severity = v.get("severity", "atypique")
                if len(text) < 50:
                    continue
                vignette_idx = i + 2  # round 2 → indices 2, 3
                try:
                    conn.execute(
                        "INSERT OR REPLACE INTO synthetic_vignettes "
                        "(syndrome_id, vignette_index, clinical_text, severity) VALUES (?, ?, ?, ?)",
                        (r["syndrome_id"], vignette_idx, text, severity)
                    )
                    n_inserted += 1
                except sqlite3.IntegrityError:
                    pass

        conn.commit()
        conn.close()
        print(f"  Inserted {n_inserted} vignettes (indices 2-3)")

    total_in = sum(r.get("tokens_in", 0) for r in results)
    total_out = sum(r.get("tokens_out", 0) for r in results)
    cost = (total_in / 1e6 * 1.50) + (total_out / 1e6 * 7.50)
    print(f"\nTokens: {total_in:,} in + {total_out:,} out")
    print(f"Cost (batch rate): ${cost:.2f}")

    # Total stats
    conn = sqlite3.connect(args.db)
    n_total = conn.execute("SELECT COUNT(*) FROM synthetic_vignettes").fetchone()[0]
    n_syn = conn.execute("SELECT COUNT(DISTINCT syndrome_id) FROM synthetic_vignettes").fetchone()[0]
    conn.close()
    print(f"\nTotal in DB: {n_total} vignettes for {n_syn} syndromes")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["submit", "status", "collect"])
    parser.add_argument("--db", default=DB_PATH)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--yes", "-y", action="store_true")
    args = parser.parse_args()

    if args.command == "submit":
        cmd_submit(args)
    elif args.command == "status":
        cmd_status(args)
    elif args.command == "collect":
        cmd_collect(args)


if __name__ == "__main__":
    main()
