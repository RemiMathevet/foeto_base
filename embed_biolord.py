#!/usr/bin/env python3
"""Embed GeneReviews + textbook chapters + PubMed cases with BioLORD-2023.
Stores vectors in sqlite-vec within syndromes_foetaux.db.

Usage:
    python embed_biolord.py                  # embed everything not yet embedded
    python embed_biolord.py --source gr      # only GeneReviews
    python embed_biolord.py --source books   # only textbook chapters
    python embed_biolord.py --source pubmed  # only PubMed case reports
    python embed_biolord.py --reembed        # force re-embed all
"""
import argparse, glob, json, os, re, sqlite3, struct, sys, time
import sqlite_vec
from pathlib import Path

DB_PATH = os.path.join(os.path.dirname(__file__), "syndromes_foetaux.db")
TEXTBOOKS_DIR = os.path.join(os.path.dirname(__file__), "textbooks")
MODEL_NAME = "FremyCompany/BioLORD-2023"
EMBEDDING_DIM = 768
BATCH_SIZE = 32
MAX_CHUNK_CHARS = 1500
OVERLAP_CHARS = 200


def get_model():
    from sentence_transformers import SentenceTransformer
    print(f"Loading {MODEL_NAME}...")
    model = SentenceTransformer(MODEL_NAME)
    print(f"  dim={model.get_sentence_embedding_dimension()}, max_seq={model.max_seq_length}")
    return model


def init_vec_tables(conn):
    conn.execute(f"""
        CREATE VIRTUAL TABLE IF NOT EXISTS vec_chunks
        USING vec0(embedding float[{EMBEDDING_DIM}])
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS chunk_meta (
            rowid       INTEGER PRIMARY KEY,
            source_type TEXT NOT NULL,
            source_id   TEXT NOT NULL,
            title       TEXT,
            chunk_index INTEGER DEFAULT 0,
            chunk_text  TEXT NOT NULL,
            embedded_at TEXT DEFAULT (datetime('now'))
        )
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_chunk_meta_source
        ON chunk_meta(source_type, source_id)
    """)
    conn.commit()


def chunk_text(text, max_chars=MAX_CHUNK_CHARS, overlap=OVERLAP_CHARS):
    if not text or len(text.strip()) < 50:
        return []
    text = re.sub(r"\n{3,}", "\n\n", text.strip())
    if len(text) <= max_chars:
        return [text]

    chunks = []
    start = 0
    while start < len(text):
        end = start + max_chars
        if end < len(text):
            # Try to break at paragraph or sentence boundary
            for sep in ["\n\n", "\n", ". ", ", "]:
                pos = text.rfind(sep, start + max_chars // 2, end)
                if pos > start:
                    end = pos + len(sep)
                    break
        chunks.append(text[start:end].strip())
        start = end - overlap
    return [c for c in chunks if len(c) > 50]


def embed_batch(model, texts):
    embeddings = model.encode(texts, batch_size=BATCH_SIZE, show_progress_bar=False,
                              normalize_embeddings=True)
    return embeddings


def serialize_vec(vec):
    return struct.pack(f"{len(vec)}f", *vec)


def get_existing(conn, source_type):
    rows = conn.execute(
        "SELECT DISTINCT source_id FROM chunk_meta WHERE source_type = ?",
        [source_type],
    ).fetchall()
    return {r[0] for r in rows}


def prepare_genereviews(conn, existing):
    rows = conn.execute(
        "SELECT slug, title, clinical_text, differential, genotype_phenotype FROM genereviews WHERE clinical_text IS NOT NULL"
    ).fetchall()

    items = []
    for slug, title, clinical, diff, genopheno in rows:
        if slug in existing:
            continue
        parts = []
        if clinical:
            parts.append(clinical)
        if diff and len(diff) > 50:
            parts.append(f"Differential Diagnosis:\n{diff}")
        if genopheno and len(genopheno) > 50:
            parts.append(f"Genotype-Phenotype:\n{genopheno}")
        full = "\n\n".join(parts)
        chunks = chunk_text(full)
        for i, c in enumerate(chunks):
            items.append(("genereviews", slug, title or slug, i, c))
    return items


def prepare_textbooks(conn, existing):
    items = []
    if not os.path.isdir(TEXTBOOKS_DIR):
        return items

    for fpath in sorted(glob.glob(os.path.join(TEXTBOOKS_DIR, "*"))):
        fname = os.path.basename(fpath)
        if fname in existing:
            continue

        ext = Path(fpath).suffix.lower()
        text = None

        if ext == ".txt":
            with open(fpath, encoding="utf-8", errors="replace") as f:
                text = f.read()
        elif ext == ".pdf":
            try:
                import fitz  # PyMuPDF
                doc = fitz.open(fpath)
                text = "\n\n".join(page.get_text() for page in doc)
                doc.close()
            except ImportError:
                try:
                    from pdfminer.high_level import extract_text
                    text = extract_text(fpath)
                except ImportError:
                    print(f"  SKIP {fname}: no PDF reader (install PyMuPDF or pdfminer)")
                    continue
        elif ext in (".docx",):
            try:
                import docx
                doc = docx.Document(fpath)
                text = "\n".join(p.text for p in doc.paragraphs)
            except ImportError:
                print(f"  SKIP {fname}: install python-docx")
                continue
        elif ext in (".md", ".rst"):
            with open(fpath, encoding="utf-8", errors="replace") as f:
                text = f.read()
        else:
            print(f"  SKIP {fname}: unsupported format {ext}")
            continue

        if not text or len(text.strip()) < 100:
            print(f"  SKIP {fname}: too short")
            continue

        title = Path(fname).stem.replace("_", " ").replace("-", " ")
        chunks = chunk_text(text)
        for i, c in enumerate(chunks):
            items.append(("textbook", fname, title, i, c))

    return items


def prepare_pubmed(conn, existing):
    rows = conn.execute(
        "SELECT id, gold_diagnosis, clinical_text FROM case_reports WHERE clinical_text IS NOT NULL AND length(clinical_text) > 100"
    ).fetchall()

    items = []
    for cid, gold, text in rows:
        sid = str(cid)
        if sid in existing:
            continue
        chunks = chunk_text(text)
        for i, c in enumerate(chunks):
            items.append(("pubmed", sid, gold or f"case_{cid}", i, c))
    return items


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", choices=["gr", "books", "pubmed", "all"], default="all")
    parser.add_argument("--reembed", action="store_true")
    args = parser.parse_args()

    conn = sqlite3.connect(DB_PATH)
    conn.enable_load_extension(True)
    sqlite_vec.load(conn)
    init_vec_tables(conn)

    all_items = []

    if args.source in ("gr", "all"):
        existing = set() if args.reembed else get_existing(conn, "genereviews")
        items = prepare_genereviews(conn, existing)
        print(f"GeneReviews: {len(items)} chunks to embed")
        all_items.extend(items)

    if args.source in ("books", "all"):
        existing = set() if args.reembed else get_existing(conn, "textbook")
        items = prepare_textbooks(conn, existing)
        print(f"Textbooks: {len(items)} chunks to embed")
        all_items.extend(items)

    if args.source in ("pubmed", "all"):
        existing = set() if args.reembed else get_existing(conn, "pubmed")
        items = prepare_pubmed(conn, existing)
        print(f"PubMed: {len(items)} chunks to embed")
        all_items.extend(items)

    if not all_items:
        print("Nothing to embed.")
        conn.close()
        return

    print(f"\nTotal: {len(all_items)} chunks to embed with {MODEL_NAME}")
    model = get_model()

    texts = [item[4] for item in all_items]

    print(f"Encoding {len(texts)} chunks...")
    t0 = time.time()
    embeddings = model.encode(texts, batch_size=BATCH_SIZE, show_progress_bar=True,
                              normalize_embeddings=True)
    elapsed = time.time() - t0
    print(f"Encoded in {elapsed:.1f}s ({len(texts)/elapsed:.0f} chunks/s)")

    print("Storing in sqlite-vec...")
    for i, (src_type, src_id, title, chunk_idx, chunk_text_val) in enumerate(all_items):
        conn.execute(
            "INSERT INTO chunk_meta (source_type, source_id, title, chunk_index, chunk_text) VALUES (?, ?, ?, ?, ?)",
            [src_type, src_id, title, chunk_idx, chunk_text_val],
        )
        rowid = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        conn.execute(
            "INSERT INTO vec_chunks (rowid, embedding) VALUES (?, ?)",
            [rowid, serialize_vec(embeddings[i])],
        )
        if (i + 1) % 500 == 0:
            conn.commit()
            print(f"  {i+1}/{len(all_items)} stored")

    conn.commit()

    stats = conn.execute("""
        SELECT source_type, COUNT(*) as n, COUNT(DISTINCT source_id) as n_sources
        FROM chunk_meta GROUP BY source_type
    """).fetchall()
    print("\nFinal stats:")
    for src, n, ns in stats:
        print(f"  {src}: {n} chunks from {ns} sources")

    total = conn.execute("SELECT COUNT(*) FROM vec_chunks").fetchone()[0]
    print(f"  Total vectors in index: {total}")

    conn.close()
    print("Done.")


if __name__ == "__main__":
    main()
