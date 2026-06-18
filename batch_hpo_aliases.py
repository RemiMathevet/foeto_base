#!/usr/bin/env python3
"""Generate French clinical aliases for HPO terms via Opus batch API.

Usage:
  python batch_hpo_aliases.py submit     # submit batch
  python batch_hpo_aliases.py status     # check status
  python batch_hpo_aliases.py collect    # collect results and update DB
"""

import sqlite3
import json
import sys
import os
import anthropic

DB_PATH = os.environ.get(
    "ORACULUM_SYNDROME_DB",
    "/home/mathevet/Bureau/foeto_base/syndromes_foetaux.db",
)
ENV_FILE = "/home/mathevet/Bureau/benchmark_foeto/.env_opus"
BATCH_ID_FILE = "/home/mathevet/Bureau/foeto_base/.hpo_aliases_batch_id"
RESULTS_FILE = "/home/mathevet/Bureau/foeto_base/.hpo_aliases_results.jsonl"

API_KEY = None
if os.path.exists(ENV_FILE):
    with open(ENV_FILE) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                if k == "ANTHROPIC_API_KEY":
                    API_KEY = v

MODEL = "claude-opus-4-6"
BATCH_SIZE = 25

SYSTEM_PROMPT = """Tu es un expert en terminologie médicale française, spécialisé en fœtopathologie, dysmorphologie et génétique clinique.

Pour chaque terme HPO fourni, génère des ALIAS CLINIQUES FRANÇAIS — les formulations qu'un médecin francophone utiliserait dans un compte-rendu d'examen fœtopathologique, d'échographie prénatale, ou de consultation de génétique.

Règles :
- Génère 3 à 8 alias par terme (synonymes, périphrases cliniques, termes d'usage courant)
- Inclus les formes avec/sans article, singulier/pluriel si pertinent
- Inclus les descriptions sémiologiques ("absence de X" pour aplasie, "petit X" pour hypoplasie, etc.)
- Inclus les termes d'échographie prénatale quand applicable
- N'inclus PAS le label original (déjà en DB)
- N'inclus PAS de traductions anglaises
- Sépare les alias par " | "

Réponds UNIQUEMENT au format JSON :
{
  "aliases": {
    "HP:XXXXXXX": "alias1 | alias2 | alias3",
    ...
  }
}"""


def get_hpo_to_process():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    rows_no_alias = conn.execute("""
        SELECT h.hpo_id, h.label_fr, h.label_en, h.category, h.context,
               COUNT(sh.syndrome_id) as n_syn
        FROM hpo_terms h
        LEFT JOIN syndrome_hpo sh ON h.hpo_id = sh.hpo_id
        WHERE h.is_excluded = 0
        AND (h.aliases_fr IS NULL OR h.aliases_fr = '')
        GROUP BY h.hpo_id
        HAVING n_syn > 0
        ORDER BY n_syn DESC
    """).fetchall()

    rows_english_only = conn.execute("""
        SELECT h.hpo_id, h.label_fr, h.label_en, h.category, h.context, h.aliases_fr,
               COUNT(sh.syndrome_id) as n_syn
        FROM hpo_terms h
        LEFT JOIN syndrome_hpo sh ON h.hpo_id = sh.hpo_id
        WHERE h.is_excluded = 0
        AND h.aliases_fr IS NOT NULL AND h.aliases_fr != ''
        AND h.aliases_fr NOT LIKE '%é%' AND h.aliases_fr NOT LIKE '%è%'
        AND h.aliases_fr NOT LIKE '%ê%' AND h.aliases_fr NOT LIKE '%à%'
        AND h.aliases_fr NOT LIKE '%ô%' AND h.aliases_fr NOT LIKE '%ù%'
        AND h.aliases_fr NOT LIKE '%ç%' AND h.aliases_fr NOT LIKE '%î%'
        AND h.aliases_fr NOT LIKE '%ü%' AND h.aliases_fr NOT LIKE '%â%'
        GROUP BY h.hpo_id
        HAVING n_syn > 0
        ORDER BY n_syn DESC
    """).fetchall()

    conn.close()

    all_hpo = []
    seen = set()
    for r in rows_no_alias:
        all_hpo.append(dict(r))
        seen.add(r["hpo_id"])
    for r in rows_english_only:
        if r["hpo_id"] not in seen:
            all_hpo.append(dict(r))

    return all_hpo


def build_requests(hpo_list):
    requests = []
    for i in range(0, len(hpo_list), BATCH_SIZE):
        batch = hpo_list[i:i + BATCH_SIZE]
        lines = []
        for h in batch:
            label = h["label_fr"] or h["label_en"]
            ctx = f" [{h['category']}]" if h.get("category") else ""
            en = f" (EN: {h['label_en']})" if h.get("label_en") else ""
            lines.append(f"- {h['hpo_id']}: {label}{ctx}{en}")

        user_msg = "Génère les alias cliniques français pour ces termes HPO :\n\n" + "\n".join(lines)

        custom_id = f"hpo_aliases_{i:04d}_{i + len(batch) - 1:04d}"
        requests.append({
            "custom_id": custom_id,
            "params": {
                "model": MODEL,
                "max_tokens": 4096,
                "system": SYSTEM_PROMPT,
                "messages": [{"role": "user", "content": user_msg}],
            },
        })

    return requests


def submit():
    if not API_KEY:
        print("ERROR: ANTHROPIC_API_KEY not found in .env_opus")
        sys.exit(1)

    hpo_list = get_hpo_to_process()
    print(f"HPO to process: {len(hpo_list)}")

    requests = build_requests(hpo_list)
    print(f"Batch requests: {len(requests)} (paquets de {BATCH_SIZE})")

    client = anthropic.Anthropic(api_key=API_KEY)
    batch = client.messages.batches.create(requests=requests)

    with open(BATCH_ID_FILE, "w") as f:
        f.write(batch.id)

    print(f"Batch submitted: {batch.id}")
    print(f"Status: {batch.processing_status}")
    est_cost = len(hpo_list) * 0.001
    print(f"Estimated cost: ~${est_cost:.1f} (batch -50%)")


def status():
    if not os.path.exists(BATCH_ID_FILE):
        print("No batch ID found. Run 'submit' first.")
        return

    with open(BATCH_ID_FILE) as f:
        batch_id = f.read().strip()

    client = anthropic.Anthropic(api_key=API_KEY)
    batch = client.messages.batches.retrieve(batch_id)

    print(f"Batch: {batch_id}")
    print(f"Status: {batch.processing_status}")
    counts = batch.request_counts
    print(f"  processing: {counts.processing}")
    print(f"  succeeded:  {counts.succeeded}")
    print(f"  errored:    {counts.errored}")
    print(f"  canceled:   {counts.canceled}")
    print(f"  expired:    {counts.expired}")


def collect():
    if not os.path.exists(BATCH_ID_FILE):
        print("No batch ID found.")
        return

    with open(BATCH_ID_FILE) as f:
        batch_id = f.read().strip()

    client = anthropic.Anthropic(api_key=API_KEY)
    batch = client.messages.batches.retrieve(batch_id)

    if batch.processing_status != "ended":
        print(f"Batch not done yet: {batch.processing_status}")
        return

    conn = sqlite3.connect(DB_PATH)
    n_updated = 0
    n_errors = 0

    with open(RESULTS_FILE, "w") as out:
        for result in client.messages.batches.results(batch_id):
            out.write(json.dumps({"custom_id": result.custom_id, "type": result.result.type}) + "\n")

            if result.result.type != "succeeded":
                n_errors += 1
                continue

            msg = result.result.message
            text = msg.content[0].text if msg.content else ""

            try:
                clean = text.strip()
                if clean.startswith("```"):
                    clean = clean.split("\n", 1)[1]
                    clean = clean.rsplit("```", 1)[0]
                start = clean.find("{")
                end = clean.rfind("}") + 1
                if start >= 0 and end > start:
                    clean = clean[start:end]
                data = json.loads(clean)
                aliases_dict = data.get("aliases", {})
            except (json.JSONDecodeError, KeyError) as e:
                print(f"  Parse error for {result.custom_id}: {e}")
                n_errors += 1
                continue

            for hpo_id, new_aliases in aliases_dict.items():
                if not new_aliases or not new_aliases.strip():
                    continue

                existing = conn.execute(
                    "SELECT aliases_fr FROM hpo_terms WHERE hpo_id = ?", (hpo_id,)
                ).fetchone()

                if existing and existing[0]:
                    merged = existing[0] + " | " + new_aliases.strip()
                else:
                    merged = new_aliases.strip()

                # Deduplicate
                parts = [p.strip() for p in merged.split("|")]
                seen = set()
                deduped = []
                for p in parts:
                    p_lower = p.lower()
                    if p_lower not in seen and p:
                        seen.add(p_lower)
                        deduped.append(p)

                conn.execute(
                    "UPDATE hpo_terms SET aliases_fr = ? WHERE hpo_id = ?",
                    (" | ".join(deduped), hpo_id),
                )
                n_updated += 1

    conn.commit()
    conn.close()

    print(f"Updated: {n_updated} HPO terms")
    print(f"Errors: {n_errors}")
    print(f"Results saved to {RESULTS_FILE}")


def main():
    if len(sys.argv) < 2:
        print("Usage: python batch_hpo_aliases.py [submit|status|collect]")
        sys.exit(1)

    cmd = sys.argv[1]
    if cmd == "submit":
        submit()
    elif cmd == "status":
        status()
    elif cmd == "collect":
        collect()
    else:
        print(f"Unknown command: {cmd}")
        sys.exit(1)


if __name__ == "__main__":
    main()
