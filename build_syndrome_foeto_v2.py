#!/usr/bin/env python3
"""Build syndrome_foeto_v2: direct FOETO extraction from vignettes + RAG passages.

For each syndrome:
  1. Extract FOETO terms from its clinical vignettes (synthetic_vignettes)
  2. Query RAG V2 (BioLORD) for top-k passages about the syndrome
  3. Extract FOETO terms from RAG passages
  4. Compute composite score: w_vignette * P_vignette + w_rag * P_rag

Replaces the indirect HPO-mediated noisy-OR in syndrome_foeto.
"""
import sqlite3
import sys
import time
from pathlib import Path

import numpy as np

# Lazy imports — heavy
_model = None
_vec_loaded = False

DB_PATH = str(Path(__file__).resolve().parent / "syndromes_foetaux.db")
RAG_DB_PATH = str(Path(__file__).resolve().parent.parent / "Embedding_RAG_V2" / "rag_v2.db")

W_VIGNETTE = 0.7
W_RAG = 0.3
RAG_TOP_K = 15
MIN_SCORE = 0.05


def _process_syndrome(args):
    sid, vig_texts, rag_text, db_path = args
    from foeto_extractor import FOETOExtractor
    ext_local = FOETOExtractor(db_path)

    n_vig = len(vig_texts)
    foeto_vig_counts = {}
    for text in vig_texts:
        matches = ext_local.extract(text, min_confidence=0.6)
        seen = set()
        for m in matches:
            if m.negated or m.foeto_id in seen:
                continue
            seen.add(m.foeto_id)
            foeto_vig_counts[m.foeto_id] = foeto_vig_counts.get(m.foeto_id, 0) + 1

    foeto_rag = set()
    if rag_text:
        for m in ext_local.extract(rag_text, min_confidence=0.6):
            if not m.negated:
                foeto_rag.add(m.foeto_id)

    rows = []
    for fid in set(foeto_vig_counts.keys()) | foeto_rag:
        p_vig = foeto_vig_counts.get(fid, 0) / n_vig if n_vig > 0 else 0.0
        p_rag = 1.0 if fid in foeto_rag else 0.0
        score = W_VIGNETTE * p_vig + W_RAG * p_rag
        if score < MIN_SCORE:
            continue
        n_vig_hits = foeto_vig_counts.get(fid, 0)
        src = []
        if n_vig_hits > 0:
            src.append("vignette")
        if fid in foeto_rag:
            src.append("rag")
        rows.append((sid, fid, round(score, 4), round(p_vig, 4), round(p_rag, 4),
                     n_vig_hits, n_vig, 1 if fid in foeto_rag else 0, "+".join(src)))
    return rows


def main():
    import sqlite_vec
    from sentence_transformers import SentenceTransformer
    from foeto_extractor import FOETOExtractor

    ext = FOETOExtractor(DB_PATH)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    rag_conn = sqlite3.connect(RAG_DB_PATH)
    rag_conn.row_factory = sqlite3.Row
    rag_conn.enable_load_extension(True)
    sqlite_vec.load(rag_conn)

    # Get all syndromes with vignettes
    syndromes = conn.execute("""
        SELECT DISTINCT s.id, COALESCE(s.name_fr, s.name_en, s.id) as name
        FROM syndromes s
        JOIN synthetic_vignettes sv ON sv.syndrome_id = s.id
        ORDER BY s.id
    """).fetchall()

    # Batch-encode all syndrome names
    print(f"Encoding {len(syndromes)} syndrome names...")
    model = SentenceTransformer("FremyCompany/BioLORD-2023")
    syn_names = [s["name"] for s in syndromes]
    syn_embeddings = model.encode(syn_names, batch_size=64, show_progress_bar=True)

    # Pre-fetch RAG passages for all syndromes in batch
    print("Fetching RAG passages...")
    syn_rag_texts: dict[str, str] = {}
    for i, syn in enumerate(syndromes):
        q_blob = syn_embeddings[i].astype(np.float32).tobytes()
        rows = rag_conn.execute("""
            SELECT m.chunk_text
            FROM vec_chunks v
            JOIN chunk_meta m ON m.rowid = v.rowid
            WHERE v.embedding MATCH ? AND k = ?
            ORDER BY v.distance
        """, [q_blob, RAG_TOP_K]).fetchall()
        syn_rag_texts[syn["id"]] = "\n".join(r[0] for r in rows)
        if (i + 1) % 500 == 0:
            print(f"  RAG fetched: {i+1}/{len(syndromes)}")

    print(f"Processing {len(syndromes)} syndromes...")

    # Create v2 table
    conn.execute("DROP TABLE IF EXISTS syndrome_foeto_v2")
    conn.execute("""
        CREATE TABLE syndrome_foeto_v2 (
            syndrome_id TEXT,
            foeto_id TEXT,
            score REAL,
            p_vignette REAL,
            p_rag REAL,
            n_vignette_hits INTEGER,
            n_vignettes INTEGER,
            n_rag_hits INTEGER,
            source TEXT,
            PRIMARY KEY (syndrome_id, foeto_id)
        )
    """)

    # Pre-load all vignettes grouped by syndrome
    print("Loading vignettes...")
    all_vignettes: dict[str, list[str]] = {}
    for row in conn.execute("SELECT syndrome_id, clinical_text FROM synthetic_vignettes"):
        all_vignettes.setdefault(row["syndrome_id"], []).append(row["clinical_text"])

    from concurrent.futures import ProcessPoolExecutor, as_completed

    work = [
        (syn["id"], all_vignettes.get(syn["id"], []), syn_rag_texts.get(syn["id"], ""), DB_PATH)
        for syn in syndromes
    ]

    t0 = time.time()
    total_pairs = 0
    done = 0
    n_workers = min(16, len(work))
    print(f"Extracting FOETO terms with {n_workers} workers...")

    with ProcessPoolExecutor(max_workers=n_workers) as pool:
        futures = {pool.submit(_process_syndrome, w): w[0] for w in work}
        for fut in as_completed(futures):
            rows = fut.result()
            if rows:
                conn.executemany("INSERT INTO syndrome_foeto_v2 VALUES (?,?,?,?,?,?,?,?,?)", rows)
                total_pairs += len(rows)
            done += 1
            if done % 200 == 0 or done == len(work):
                elapsed = time.time() - t0
                rate = done / elapsed
                eta = (len(work) - done) / rate if rate > 0 else 0
                print(f"  [{done}/{len(work)}] {total_pairs} pairs | {rate:.1f} syn/s | ETA {eta/60:.0f}min")
                conn.commit()

    conn.commit()

    # Stats
    conn.execute("CREATE INDEX IF NOT EXISTS idx_sfv2_syn ON syndrome_foeto_v2(syndrome_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_sfv2_foeto ON syndrome_foeto_v2(foeto_id)")

    n_total = conn.execute("SELECT COUNT(*) FROM syndrome_foeto_v2").fetchone()[0]
    n_syn = conn.execute("SELECT COUNT(DISTINCT syndrome_id) FROM syndrome_foeto_v2").fetchone()[0]
    n_foeto = conn.execute("SELECT COUNT(DISTINCT foeto_id) FROM syndrome_foeto_v2").fetchone()[0]
    n_both = conn.execute("SELECT COUNT(*) FROM syndrome_foeto_v2 WHERE source='vignette+rag'").fetchone()[0]
    n_vig_only = conn.execute("SELECT COUNT(*) FROM syndrome_foeto_v2 WHERE source='vignette'").fetchone()[0]
    n_rag_only = conn.execute("SELECT COUNT(*) FROM syndrome_foeto_v2 WHERE source='rag'").fetchone()[0]
    avg_score = conn.execute("SELECT AVG(score) FROM syndrome_foeto_v2").fetchone()[0]

    elapsed = time.time() - t0
    print(f"\n{'='*60}")
    print(f"syndrome_foeto_v2 built in {elapsed:.0f}s")
    print(f"  {n_total} pairs | {n_syn} syndromes | {n_foeto} FOETO terms")
    print(f"  vignette+rag: {n_both} | vignette only: {n_vig_only} | rag only: {n_rag_only}")
    print(f"  avg score: {avg_score:.3f}")
    print(f"  (vs syndrome_foeto v1: {conn.execute('SELECT COUNT(*) FROM syndrome_foeto').fetchone()[0]} pairs)")

    conn.close()
    rag_conn.close()


if __name__ == "__main__":
    main()
