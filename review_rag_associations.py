#!/usr/bin/env python3
"""Review RAG-only syndrome_foeto_v2 associations via Qwen 3.6-35B."""
import json
import sqlite3
import sys
import time
from pathlib import Path
from collections import defaultdict

import requests

DB = Path(__file__).resolve().parent / "syndromes_foetaux.db"
OUT = Path(__file__).resolve().parent / "rag_review_results.json"

LLM_URL = "http://127.0.0.1:8081/v1/chat/completions"

SYSTEM = """Tu es un expert en anatomie pathologique fœtale.

On te donne des associations entre un signe histologique FOETO et des syndromes/maladies.
Ces associations viennent d'un RAG automatique et n'ont pas été vérifiées.
Pour chaque association, tu reçois :
- Les HPO du signe FOETO
- Les HPO du syndrome
- Les HPO partagés entre les deux (s'il y en a)

Ta tâche : pour chaque association, dis si le syndrome est RÉELLEMENT pertinent pour ce signe.

Un syndrome est pertinent si :
- Le signe histologique est un élément connu du spectre phénotypique de ce syndrome
- OU les HPO partagés confirment un lien sémantique direct
- OU le signe est une conséquence directe/fréquente de ce syndrome

Un syndrome n'est PAS pertinent si :
- Les HPO partagés sont trop génériques (ex: "Microcephaly" seul ne suffit pas pour lier un signe cérébral précis)
- L'association est trop indirecte ou le RAG a confondu des termes proches
- Le syndrome n'a aucun rapport avec l'organe ou le type de lésion

Réponds UNIQUEMENT en JSON, un array :
[{"foeto_id": "...", "syndrome_id": "...", "verdict": "remove", "reason": "une phrase"}]

Ne renvoie QUE les associations à SUPPRIMER.
Les associations correctes ne doivent PAS apparaître."""

BATCH_SIZE = 8


def call_llm(messages, max_retries=2):
    for attempt in range(max_retries + 1):
        try:
            r = requests.post(LLM_URL, json={
                "model": "qwen3",
                "messages": messages,
                "max_tokens": 12000,
                "temperature": 0.2,
            }, timeout=300)
            r.raise_for_status()
            content = r.json()["choices"][0]["message"].get("content", "")
            if not content.strip():
                if attempt < max_retries:
                    time.sleep(3)
                    continue
                return []
            start = content.find("[")
            end = content.rfind("]") + 1
            if start == -1 or end == 0:
                return []
            raw = content[start:end].replace(",\n]", "\n]").replace(",]", "]")
            return json.loads(raw)
        except json.JSONDecodeError:
            raw = raw.rstrip().rstrip(",")
            if not raw.endswith("]"):
                raw += "\n]"
            try:
                return json.loads(raw)
            except:
                return []
        except Exception as e:
            print(f"    [error] {e}")
            if attempt < max_retries:
                time.sleep(5)
    return []


def load_hpo_cache(conn):
    """Pre-load HPO for all FOETO terms and syndromes."""
    foeto_hpo = defaultdict(list)
    for r in conn.execute("SELECT foeto_id, hpo_id FROM foeto_hpo"):
        foeto_hpo[r[0]].append(r[1])

    synd_hpo = defaultdict(list)
    for r in conn.execute("SELECT syndrome_id, hpo_id FROM syndrome_hpo"):
        synd_hpo[r[0]].append(r[1])

    hpo_labels = {}
    for r in conn.execute("SELECT hpo_id, label_en FROM hpo_terms"):
        hpo_labels[r[0]] = r[1]

    return foeto_hpo, synd_hpo, hpo_labels


def main():
    conn = sqlite3.connect(str(DB))
    conn.row_factory = sqlite3.Row

    rows = conn.execute("""
        SELECT sf.foeto_id, ft.label_fr, ft.organe,
               sf.syndrome_id, s.name_en, s.name_fr
        FROM syndrome_foeto_v2 sf
        JOIN foeto_terms ft ON sf.foeto_id = ft.id
        JOIN syndromes s ON sf.syndrome_id = s.id
        WHERE sf.source = 'rag' AND sf.score = 0.30
        ORDER BY ft.organe, sf.foeto_id
    """).fetchall()

    print(f"Total RAG-only associations: {len(rows)}")
    print("Loading HPO cache...")
    foeto_hpo, synd_hpo, hpo_labels = load_hpo_cache(conn)
    print(f"  FOETO terms with HPO: {len(foeto_hpo)}, syndromes with HPO: {len(synd_hpo)}")

    # Group by organ
    by_organ = defaultdict(list)
    for r in rows:
        by_organ[r["organe"]].append(dict(r))

    all_results = {}
    total_removed = 0

    for organ in sorted(by_organ):
        assocs = by_organ[organ]
        print(f"\n{'='*60}")
        print(f"  {organ}: {len(assocs)} associations")
        print(f"{'='*60}")

        organ_removes = []

        # Group by foeto_id for cleaner prompts
        by_foeto = defaultdict(list)
        for a in assocs:
            by_foeto[a["foeto_id"]].append(a)

        foeto_ids = list(by_foeto.keys())
        # Build batches by foeto term count
        batch_items = []
        current_batch = []
        current_count = 0
        for fid in foeto_ids:
            n = len(by_foeto[fid])
            if current_count + n > BATCH_SIZE and current_batch:
                batch_items.append(current_batch)
                current_batch = [fid]
                current_count = n
            else:
                current_batch.append(fid)
                current_count += n
        if current_batch:
            batch_items.append(current_batch)

        for bi, batch_fids in enumerate(batch_items):
            batch_assocs = []
            for fid in batch_fids:
                batch_assocs.extend(by_foeto[fid])

            print(f"  batch {bi+1}/{len(batch_items)} ({len(batch_assocs)} associations)")

            lines = []
            for a in batch_assocs:
                name = a["name_en"] or a["name_fr"] or a["syndrome_id"]
                fhpo = foeto_hpo.get(a["foeto_id"], [])
                shpo = synd_hpo.get(a["syndrome_id"], [])
                shared = set(fhpo) & set(shpo)
                fhpo_str = ", ".join(f"{h} ({hpo_labels.get(h, '')})" for h in fhpo[:5])
                shpo_str = ", ".join(f"{h} ({hpo_labels.get(h, '')})" for h in shpo[:8])
                shared_str = ", ".join(f"{h} ({hpo_labels.get(h, '')})" for h in shared) if shared else "AUCUN"
                lines.append(
                    f"- {a['foeto_id']} ({a['label_fr']})\n"
                    f"  HPO signe: [{fhpo_str}]\n"
                    f"  ↔ {a['syndrome_id']} ({name})\n"
                    f"  HPO syndrome: [{shpo_str}{'...' if len(shpo)>8 else ''}]\n"
                    f"  HPO partagés: [{shared_str}]"
                )

            user_msg = f"ORGANE : {organ}\n\nASSOCIATIONS À VÉRIFIER :\n\n" + "\n\n".join(lines)
            messages = [
                {"role": "system", "content": SYSTEM},
                {"role": "user", "content": user_msg},
            ]

            results = call_llm(messages)
            removes = [r for r in results if isinstance(r, dict) and r.get("verdict") == "remove"]
            print(f"    → {len(removes)} to remove")

            for r in removes[:3]:
                print(f"      {r.get('foeto_id','')} ↔ {r.get('syndrome_id','')}: {r.get('reason','')}")
            if len(removes) > 3:
                print(f"      ... and {len(removes)-3} more")

            organ_removes.extend(removes)
            time.sleep(1)

        all_results[organ] = organ_removes
        total_removed += len(organ_removes)

        # Save incrementally
        with open(OUT, "w") as f:
            json.dump(all_results, f, ensure_ascii=False, indent=2)

    print(f"\n{'='*60}")
    print(f"DONE: {total_removed} associations to remove out of {len(rows)}")
    print(f"Results saved to {OUT}")
    conn.close()


if __name__ == "__main__":
    main()
