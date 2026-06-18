#!/usr/bin/env python3
"""Embed synthetic vignettes + existing chunks with BioLORD AND PubMedBERT.

Step 1: Add 10687 vignettes to vec_chunks (BioLORD) — source_type='vignette'
Step 2: Embed ALL chunks (14840 existing + 10687 vignettes) with PubMedBERT → vec_pubmedbert
Step 3: CCA analysis between the two embedding spaces

Usage:
    python embed_vignettes_dual.py biolord    # step 1 only
    python embed_vignettes_dual.py pubmedbert # step 2 only
    python embed_vignettes_dual.py cca        # step 3 only
    python embed_vignettes_dual.py all        # all steps
"""
import argparse
import os
import sqlite3
import struct
import sys
import time
from pathlib import Path

import numpy as np

DB_PATH = str(Path(__file__).resolve().parent / "syndromes_foetaux.db")
BIOLORD = "FremyCompany/BioLORD-2023"
PUBMEDBERT = "microsoft/BiomedNLP-BiomedBERT-base-uncased-abstract-fulltext"
BATCH_SIZE = 64


def serialize_vec(vec):
    return struct.pack(f"{len(vec)}f", *vec)


def deserialize_vec(blob):
    n = len(blob) // 4
    return np.array(struct.unpack(f"{n}f", blob), dtype=np.float32)


def get_conn():
    import sqlite_vec
    conn = sqlite3.connect(DB_PATH)
    conn.enable_load_extension(True)
    sqlite_vec.load(conn)
    return conn


def load_vignettes(conn):
    rows = conn.execute(
        "SELECT id, syndrome_id, vignette_index, clinical_text "
        "FROM synthetic_vignettes WHERE length(clinical_text) > 50"
    ).fetchall()
    return rows


def step_biolord(conn):
    """Embed vignettes with BioLORD into vec_chunks/chunk_meta."""
    existing = set(
        r[0] for r in conn.execute(
            "SELECT DISTINCT source_id FROM chunk_meta WHERE source_type = 'vignette'"
        ).fetchall()
    )

    vignettes = load_vignettes(conn)
    todo = [(vid, sid, vidx, text) for vid, sid, vidx, text in vignettes
            if f"{sid}_v{vidx}" not in existing]

    if not todo:
        print("All vignettes already embedded with BioLORD.")
        return

    print(f"BioLORD: {len(todo)} vignettes to embed (CPU mode)")

    from sentence_transformers import SentenceTransformer
    model = SentenceTransformer(BIOLORD)

    texts = [t[3] for t in todo]
    print(f"Encoding {len(texts)} vignettes...")
    t0 = time.time()
    embeddings = model.encode(texts, batch_size=BATCH_SIZE, show_progress_bar=True,
                              normalize_embeddings=True, device="cpu")
    elapsed = time.time() - t0
    print(f"  {elapsed:.1f}s ({len(texts)/elapsed:.0f}/s)")

    print("Storing in vec_chunks...")
    for i, (vid, sid, vidx, text) in enumerate(todo):
        source_id = f"{sid}_v{vidx}"
        conn.execute(
            "INSERT INTO chunk_meta (source_type, source_id, title, chunk_index, chunk_text) "
            "VALUES (?, ?, ?, ?, ?)",
            ("vignette", source_id, sid, vidx, text),
        )
        rowid = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        conn.execute(
            "INSERT INTO vec_chunks (rowid, embedding) VALUES (?, ?)",
            (rowid, serialize_vec(embeddings[i])),
        )
        if (i + 1) % 1000 == 0:
            conn.commit()
            print(f"  {i+1}/{len(todo)}")

    conn.commit()

    stats = conn.execute(
        "SELECT source_type, COUNT(*) FROM chunk_meta GROUP BY source_type"
    ).fetchall()
    print("\nchunk_meta stats:")
    for st, n in stats:
        print(f"  {st}: {n}")
    print(f"Done — {len(todo)} vignettes embedded with BioLORD.")
    del model


def step_pubmedbert(conn):
    """Embed ALL chunks + vignettes with PubMedBERT into vec_pubmedbert."""
    conn.execute("""
        CREATE VIRTUAL TABLE IF NOT EXISTS vec_pubmedbert
        USING vec0(embedding float[768])
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS pubmedbert_status (
            chunk_rowid INTEGER PRIMARY KEY,
            embedded_at TEXT DEFAULT (datetime('now'))
        )
    """)
    conn.commit()

    existing = set(
        r[0] for r in conn.execute("SELECT chunk_rowid FROM pubmedbert_status").fetchall()
    )

    all_chunks = conn.execute(
        "SELECT rowid, chunk_text FROM chunk_meta WHERE length(chunk_text) > 50"
    ).fetchall()

    todo = [(rowid, text) for rowid, text in all_chunks if rowid not in existing]

    if not todo:
        print("All chunks already embedded with PubMedBERT.")
        return

    print(f"PubMedBERT: {len(todo)} chunks to embed (CPU mode)")

    from sentence_transformers import SentenceTransformer
    model = SentenceTransformer(PUBMEDBERT)

    texts = [t[1] for t in todo]
    print(f"Encoding {len(texts)} chunks...")
    t0 = time.time()
    embeddings = model.encode(texts, batch_size=BATCH_SIZE, show_progress_bar=True,
                              normalize_embeddings=True, device="cpu")
    elapsed = time.time() - t0
    print(f"  {elapsed:.1f}s ({len(texts)/elapsed:.0f}/s)")

    print("Storing in vec_pubmedbert...")
    for i, (rowid, _) in enumerate(todo):
        conn.execute(
            "INSERT INTO vec_pubmedbert (rowid, embedding) VALUES (?, ?)",
            (rowid, serialize_vec(embeddings[i])),
        )
        conn.execute(
            "INSERT INTO pubmedbert_status (chunk_rowid) VALUES (?)", (rowid,)
        )
        if (i + 1) % 1000 == 0:
            conn.commit()
            print(f"  {i+1}/{len(todo)}")

    conn.commit()

    total = conn.execute("SELECT COUNT(*) FROM pubmedbert_status").fetchone()[0]
    print(f"Done — {len(todo)} chunks embedded. Total PubMedBERT vectors: {total}")
    del model


def step_cca(conn):
    """CCA analysis between BioLORD and PubMedBERT embedding spaces."""
    from sklearn.cross_decomposition import CCA
    from collections import defaultdict

    print("Loading all embeddings in bulk...")
    t0 = time.time()

    bio_rows = conn.execute("SELECT rowid, embedding FROM vec_chunks").fetchall()
    bio_map = {r[0]: deserialize_vec(r[1]) for r in bio_rows}
    print(f"  BioLORD: {len(bio_map)} vectors ({time.time()-t0:.1f}s)")

    t1 = time.time()
    pub_rows = conn.execute("SELECT rowid, embedding FROM vec_pubmedbert").fetchall()
    pub_map = {r[0]: deserialize_vec(r[1]) for r in pub_rows}
    print(f"  PubMedBERT: {len(pub_map)} vectors ({time.time()-t1:.1f}s)")

    paired_rowids = sorted(set(bio_map.keys()) & set(pub_map.keys()))
    print(f"  Paired: {len(paired_rowids)}")

    if len(paired_rowids) < 100:
        print("Too few paired embeddings.")
        return

    X_bio = np.stack([bio_map[r] for r in paired_rowids])
    X_pub = np.stack([pub_map[r] for r in paired_rowids])
    print(f"  Matrices: {X_bio.shape}, {X_pub.shape}")

    # Subsample for CCA (5K is statistically sufficient for 50 components)
    MAX_CCA = 5000
    if len(paired_rowids) > MAX_CCA:
        rng = np.random.RandomState(42)
        idx = rng.choice(len(paired_rowids), MAX_CCA, replace=False)
        X_bio_cca = X_bio[idx]
        X_pub_cca = X_pub[idx]
        print(f"  Subsampled {MAX_CCA} for CCA fitting")
    else:
        X_bio_cca = X_bio
        X_pub_cca = X_pub

    n_components = 50
    print(f"\nRunning CCA with {n_components} components...")
    t0 = time.time()
    cca = CCA(n_components=n_components, max_iter=500)
    X_bio_c, X_pub_c = cca.fit_transform(X_bio_cca, X_pub_cca)
    elapsed = time.time() - t0
    print(f"  CCA fit in {elapsed:.1f}s")

    correlations = []
    for i in range(n_components):
        r = np.corrcoef(X_bio_c[:, i], X_pub_c[:, i])[0, 1]
        correlations.append(r)

    print(f"\nCanonical correlations (top 20):")
    for i, r in enumerate(correlations[:20]):
        bar = "#" * int(r * 40)
        print(f"  CC{i+1:>2d}: {r:.4f} {bar}")

    high_corr = sum(1 for r in correlations if r > 0.7)
    med_corr = sum(1 for r in correlations if 0.4 <= r <= 0.7)
    low_corr = sum(1 for r in correlations if r < 0.4)
    print(f"\n  High (>0.7): {high_corr}, Medium (0.4-0.7): {med_corr}, Low (<0.4): {low_corr}")

    total_var = sum(r**2 for r in correlations)
    cum_var = 0
    for i, r in enumerate(correlations):
        cum_var += r**2
        if cum_var / total_var > 0.90:
            print(f"  90% shared variance in {i+1} components")
            break

    # Residual analysis by source_type
    print("\n--- Residual analysis by source_type ---")
    source_map = {r[0]: r[1] for r in conn.execute("SELECT rowid, source_type FROM chunk_meta").fetchall()}

    # Project full data onto CCA space
    X_bio_proj = X_bio @ cca.x_weights_
    X_pub_proj = X_pub @ cca.y_weights_
    X_bio_recon = X_bio_proj @ np.linalg.pinv(cca.x_weights_)
    X_pub_recon = X_pub_proj @ np.linalg.pinv(cca.y_weights_)

    bio_residuals = np.linalg.norm(X_bio - X_bio_recon, axis=1)
    pub_residuals = np.linalg.norm(X_pub - X_pub_recon, axis=1)

    res_by_type = defaultdict(lambda: {"bio": [], "pub": [], "n": 0})
    for i, rid in enumerate(paired_rowids):
        st = source_map.get(rid, "unknown")
        res_by_type[st]["bio"].append(bio_residuals[i])
        res_by_type[st]["pub"].append(pub_residuals[i])
        res_by_type[st]["n"] += 1

    print(f"{'Source':<15s} {'N':>6s} {'BioLORD res':>12s} {'PubMedBERT res':>14s} {'Ratio B/P':>10s}")
    print("-" * 60)
    for st in sorted(res_by_type.keys()):
        d = res_by_type[st]
        bio_mean = np.mean(d["bio"])
        pub_mean = np.mean(d["pub"])
        ratio = bio_mean / max(pub_mean, 1e-10)
        print(f"  {st:<13s} {d['n']:>6d} {bio_mean:>12.4f} {pub_mean:>14.4f} {ratio:>10.2f}")

    # Global cosine agreement
    cosines = np.sum(X_bio * X_pub, axis=1)
    print(f"\nDirect cosine BioLORD↔PubMedBERT:")
    print(f"  Mean: {cosines.mean():.4f}, Std: {cosines.std():.4f}")
    print(f"  Min:  {cosines.min():.4f}, Max: {cosines.max():.4f}")

    # Cosine agreement by source type
    print(f"\nCosine by source type:")
    for st in sorted(res_by_type.keys()):
        indices = [i for i, rid in enumerate(paired_rowids) if source_map.get(rid) == st]
        cos_st = cosines[indices]
        print(f"  {st:<13s}: mean={cos_st.mean():.4f}, std={cos_st.std():.4f}")

    out_path = Path(__file__).resolve().parent / "cca_weights.npz"
    np.savez(out_path,
             x_weights=cca.x_weights_,
             y_weights=cca.y_weights_,
             correlations=np.array(correlations),
             x_mean=cca._x_mean,
             y_mean=cca._y_mean)
    print(f"\nCCA weights saved to {out_path}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("step", choices=["biolord", "pubmedbert", "cca", "all"])
    args = parser.parse_args()

    os.environ["CUDA_VISIBLE_DEVICES"] = ""

    conn = get_conn()

    if args.step in ("biolord", "all"):
        step_biolord(conn)

    if args.step in ("pubmedbert", "all"):
        step_pubmedbert(conn)

    if args.step in ("cca", "all"):
        step_cca(conn)

    conn.close()
    print("\n✓ All done.")


if __name__ == "__main__":
    main()
