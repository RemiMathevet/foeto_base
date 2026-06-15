#!/usr/bin/env python3
"""
RAG query engine : prend une description clinique en entrée,
interroge syndromes_foetaux.db pour trouver les syndromes candidats,
et injecte les fiches enrichies dans le prompt du LLM local.

Usage:
    python3 rag_query.py "RCIU, agénésie du corps calleux, polydactylie postaxiale"
    python3 rag_query.py --interactive
    python3 rag_query.py --api http://localhost:8082/v1/chat/completions "signes cliniques..."
"""

import argparse
import json
import re
import sqlite3
import sys
import requests

DB_PATH = "syndromes_foetaux.db"
DEFAULT_API = "http://localhost:8082/v1/chat/completions"

SYSTEM_PROMPT = """\
Tu es un assistant expert en foetopathologie. Tu aides au diagnostic différentiel
à partir de signes cliniques prénataux.

On t'a fourni des fiches de syndromes candidats extraites d'une base de données
de {n_syndromes} syndromes fœtaux. Chaque fiche contient : description, signes
prénataux, discriminateurs clés, et diagnostics différentiels calculés par
overlap phénotypique.

À partir des signes cliniques fournis par l'utilisateur et des fiches candidates :
1. Classe les syndromes du plus probable au moins probable
2. Explique pour chaque candidat quels signes matchent et lesquels sont absents
3. Propose des examens complémentaires discriminants
4. Si aucun candidat ne colle bien, dis-le explicitement

Raisonne étape par étape. Sois rigoureux.\
"""


def search_syndromes(db: sqlite3.Connection, clinical_signs: str, top_n: int = 10) -> list[dict]:
    """Recherche les syndromes par matching HPO textuel sur les signes cliniques."""
    signs = [s.strip().lower() for s in re.split(r"[,;/\n]+", clinical_signs) if s.strip()]
    if not signs:
        return []

    scored = {}

    for sign in signs:
        w = f"%{sign}%"
        rows = db.execute("""
            SELECT DISTINCT sh.syndrome_id, sh.prob,
                   h.label_en, h.label_fr
            FROM syndrome_hpo sh
            JOIN hpo_terms h ON sh.hpo_id = h.hpo_id
            WHERE (h.label_en LIKE ? OR h.label_fr LIKE ?)
        """, (w, w)).fetchall()

        for r in rows:
            sid = r["syndrome_id"]
            if sid not in scored:
                scored[sid] = {"id": sid, "score": 0, "matched_signs": [], "total_prob": 0}
            prob = r["prob"] if r["prob"] else 0.5
            scored[sid]["score"] += prob
            scored[sid]["total_prob"] += prob
            label = r["label_fr"] or r["label_en"]
            if label not in scored[sid]["matched_signs"]:
                scored[sid]["matched_signs"].append(label)

    ranked = sorted(scored.values(), key=lambda x: x["score"], reverse=True)[:top_n]

    results = []
    for item in ranked:
        s = db.execute("""
            SELECT id, name_fr, name_en, category, relevance, inheritance,
                   description_md, prenatal_signs_summary,
                   key_discriminators, differential_diagnosis
            FROM syndromes WHERE id = ?
        """, (item["id"],)).fetchone()
        if s:
            results.append({
                **dict(s),
                "match_score": item["score"],
                "matched_signs": item["matched_signs"],
                "n_matched": len(item["matched_signs"]),
            })

    return results


def format_fiches(syndromes: list[dict]) -> str:
    parts = []
    for i, s in enumerate(syndromes, 1):
        matched = ", ".join(s["matched_signs"])
        fiche = f"""--- Candidat {i} : {s['name_fr']} ({s['id']}) ---
Catégorie : {s['category']} | Relevance : {s['relevance'] or '?'}
Signes matchés ({s['n_matched']}) : {matched}
Score : {s['match_score']:.2f}

Description : {s.get('description_md') or 'N/A'}

Signes prénataux :
{s.get('prenatal_signs_summary') or 'N/A'}

Discriminateurs clés :
{s.get('key_discriminators') or 'N/A'}

Diagnostic différentiel :
{s.get('differential_diagnosis') or 'N/A'}
"""
        parts.append(fiche)
    return "\n".join(parts)


def query_llm(api_url: str, system: str, user_prompt: str) -> str:
    payload = {
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": 0.4,
        "max_tokens": 4096,
        "stream": False,
    }
    try:
        r = requests.post(api_url, json=payload, timeout=600)
        r.raise_for_status()
        return r.json()["choices"][0]["message"]["content"]
    except Exception as e:
        return f"[Erreur LLM] {e}"


def run_query(clinical_signs: str, api_url: str, db_path: str = DB_PATH):
    db = sqlite3.connect(db_path)
    db.row_factory = sqlite3.Row

    total = db.execute("SELECT COUNT(*) FROM syndromes").fetchone()[0]

    print(f"Recherche dans {total} syndromes...")
    candidates = search_syndromes(db, clinical_signs)

    if not candidates:
        print("Aucun syndrome candidat trouvé.")
        db.close()
        return

    print(f"{len(candidates)} candidats trouvés. Envoi au LLM...\n")

    fiches = format_fiches(candidates)
    system = SYSTEM_PROMPT.format(n_syndromes=total)
    user_prompt = f"""Signes cliniques observés :
{clinical_signs}

Voici les {len(candidates)} syndromes candidats extraits de la base :

{fiches}

Analyse ces candidats et propose un diagnostic différentiel argumenté."""

    response = query_llm(api_url, system, user_prompt)
    print(response)
    db.close()


def main():
    parser = argparse.ArgumentParser(description="RAG foetopathologie")
    parser.add_argument("signs", nargs="?", help="Signes cliniques (séparés par virgules)")
    parser.add_argument("--api", default=DEFAULT_API, help="URL LLM local")
    parser.add_argument("--db", default=DB_PATH, help="Base SQLite")
    parser.add_argument("--interactive", action="store_true", help="Mode interactif")
    args = parser.parse_args()

    if args.interactive:
        print("=== FOETO-BASE RAG — Mode interactif ===")
        print(f"LLM : {args.api}")
        print("Tapez vos signes cliniques, 'q' pour quitter.\n")
        while True:
            try:
                signs = input("Signes > ").strip()
            except (EOFError, KeyboardInterrupt):
                break
            if signs.lower() in ("q", "quit", "exit"):
                break
            if signs:
                run_query(signs, args.api, args.db)
                print("\n" + "=" * 60 + "\n")
    elif args.signs:
        run_query(args.signs, args.api, args.db)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
