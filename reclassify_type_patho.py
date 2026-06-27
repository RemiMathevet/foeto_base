#!/usr/bin/env python3
"""Reclassify type_patho for FOETO terms via Qwen 3.6-35B (magos)."""
import json
import sqlite3
import sys
import time
from pathlib import Path

import requests

DB = Path(__file__).resolve().parent / "syndromes_foetaux.db"
OUT = Path(__file__).resolve().parent / "reclassify_results.json"

LLM_URL = "http://127.0.0.1:8081/v1/chat/completions"

TYPES_PATHO = [
    "histo normale",
    "malformation",
    "trophisme",
    "infectieux",
    "disruption",
    "MFIU",
    "dysplasie",
    "tumoral",
    "maladie metabo",
    "neuropathie",
]

SYSTEM = """Tu es un expert en anatomie pathologique fœtale et périnatale.

On te donne une liste de termes FOETO (signes histologiques ou macroscopiques) pour un organe donné.
Chacun est actuellement classé "histo normale". Ta tâche : identifier ceux qui sont MAL classés.

CATÉGORIES AUTORISÉES (liste fermée) :
- "histo normale" : anatomie normale, maturation, repères histologiques physiologiques
- "malformation" : anomalie de développement, défaut morphogénétique
- "trophisme" : RCIU, anasarque, ischémie, pathologie vasculaire, MVM, FVM, hydrops, hémorragie
- "infectieux" : chorioamniotite, villite, funiculite, infection fœtale
- "disruption" : destruction secondaire d'une structure normalement formée
- "MFIU" : mort fœtale in utero, macération, rétention
- "dysplasie" : anomalie de la croissance/différenciation cellulaire
- "tumoral" : tumeur, néoplasie, hamartome, chorangiome
- "maladie metabo" : surcharge, maladie métabolique
- "neuropathie" : atrophie musculaire, dénervation, myopathie

RÈGLE ABSOLUE : tu ne peux utiliser QUE les catégories ci-dessus. Ne JAMAIS en inventer.

Réponds UNIQUEMENT en JSON valide, un array d'objets pour les termes MAL classés :
[
  {
    "foeto_id": "FOETO:XXXXXXX",
    "label": "...",
    "proposed_type": "une des catégories ci-dessus",
    "reason": "une phrase courte"
  }
]

- Ne renvoie QUE les termes qui ne sont PAS de l'histo normale.
- Les termes véritablement normaux NE DOIVENT PAS apparaître dans ta réponse.
- Attention : certains termes décrivent des aspects normaux de l'organe fœtal (maturation, architecture, repères). Ils doivent rester "histo normale".
- En cas de doute, ne pas inclure le terme (conserver histo normale)."""

BATCH_SIZE = 25


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
            data = r.json()
            choice = data["choices"][0]
            content = choice["message"].get("content", "")
            if not content.strip():
                print(f"    [warn] empty content, attempt {attempt+1}")
                if attempt < max_retries:
                    time.sleep(3)
                    continue
                return []
            start = content.find("[")
            end = content.rfind("]") + 1
            if start == -1 or end == 0:
                print(f"    [warn] no JSON array found")
                return []
            raw = content[start:end]
            # Fix trailing comma
            raw = raw.replace(",\n]", "\n]").replace(",]", "]")
            return json.loads(raw)
        except json.JSONDecodeError:
            # Try to close truncated array
            raw = raw.rstrip().rstrip(",")
            if not raw.endswith("]"):
                raw += "\n]"
            try:
                return json.loads(raw)
            except json.JSONDecodeError as e:
                print(f"    [error] JSON parse failed: {e}")
                return []
        except Exception as e:
            print(f"    [error] {e}")
            if attempt < max_retries:
                time.sleep(5)
    return []


def process_organ(organ, terms):
    print(f"\n{'='*60}")
    print(f"  {organ}: {len(terms)} terms")
    print(f"{'='*60}")

    all_corrections = []

    for i in range(0, len(terms), BATCH_SIZE):
        batch = terms[i:i + BATCH_SIZE]
        print(f"  batch {i//BATCH_SIZE + 1}/{(len(terms) + BATCH_SIZE - 1)//BATCH_SIZE} ({len(batch)} terms)")

        term_lines = "\n".join(f"- {fid} | {label}" for fid, label in batch)
        user_msg = f"ORGANE : {organ}\n\nTERMES À VÉRIFIER :\n{term_lines}"

        messages = [
            {"role": "system", "content": SYSTEM},
            {"role": "user", "content": user_msg},
        ]

        results = call_llm(messages)
        valid = [r for r in results if isinstance(r, dict)
                 and r.get("proposed_type") in TYPES_PATHO
                 and r.get("proposed_type") != "histo normale"]
        hallucinated = [r for r in results if isinstance(r, dict)
                        and r.get("proposed_type") not in TYPES_PATHO]
        if hallucinated:
            print(f"    [warn] {len(hallucinated)} hallucinated types: "
                  f"{set(r.get('proposed_type') for r in hallucinated)}")

        print(f"    → {len(valid)} corrections")
        for r in valid:
            print(f"      {r['foeto_id']}: {r.get('label','')} → {r['proposed_type']} ({r.get('reason','')})")
        all_corrections.extend(valid)
        time.sleep(1)

    return all_corrections


def main():
    conn = sqlite3.connect(str(DB))
    rows = conn.execute("""
        SELECT id, label_fr, organe FROM foeto_terms
        WHERE type_patho = 'histo normale'
        ORDER BY organe, id
    """).fetchall()

    by_organ = {}
    for fid, label, organ in rows:
        by_organ.setdefault(organ, []).append((fid, label))

    print(f"Total: {len(rows)} 'histo normale' terms across {len(by_organ)} organs")

    all_results = {}
    total_corrections = 0

    for organ in sorted(by_organ):
        corrections = process_organ(organ, by_organ[organ])
        all_results[organ] = corrections
        total_corrections += len(corrections)

        # Save incrementally
        with open(OUT, "w") as f:
            json.dump(all_results, f, ensure_ascii=False, indent=2)

    print(f"\n{'='*60}")
    print(f"DONE: {total_corrections} corrections across {len(by_organ)} organs")
    print(f"Results saved to {OUT}")

    # Summary by proposed type
    from collections import Counter
    types = Counter(r["proposed_type"] for corrs in all_results.values() for r in corrs)
    for t, n in types.most_common():
        print(f"  {t}: {n}")

    conn.close()


if __name__ == "__main__":
    main()
