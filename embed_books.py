#!/usr/bin/env python3
"""Embed reference books into BioLORD vector store for syndrome retrieval.

Reads PDFs from a directory, extracts text chapter by chapter,
chunks it, and embeds with BioLORD into syndromes_foetaux.db.

Usage:
    python embed_books.py /home/mathevet/Bureau/Livres/
    python embed_books.py /home/mathevet/Bureau/Livres/inbornerror.pdf
    python embed_books.py --list   # show already-embedded books
"""

import argparse
import os
import re
import sqlite3
import struct
import sys
from pathlib import Path

import numpy as np

DB_PATH = os.environ.get(
    "ORACULUM_SYNDROME_DB",
    str(Path(__file__).resolve().parent / "syndromes_foetaux.db"),
)

CHUNK_SIZE = 512
CHUNK_OVERLAP = 64

_ORPHA_RE = re.compile(r"^(ORPHA[_:]?\d+)[_\-\s]")


def parse_orpha_from_filename(stem):
    m = _ORPHA_RE.match(stem)
    if not m:
        return None, stem
    raw = m.group(1)
    orpha_id = raw.replace("ORPHA_", "ORPHA:").replace("ORPHA", "ORPHA:")
    if orpha_id.count(":") > 1:
        orpha_id = "ORPHA:" + orpha_id.split(":")[-1]
    label = stem[m.end():].strip(" _-")
    return orpha_id, label or stem


def serialize_vec(vec):
    return struct.pack(f"{len(vec)}f", *vec)


def extract_text_from_pdf(pdf_path):
    try:
        import pymupdf
    except ImportError:
        import fitz as pymupdf

    doc = pymupdf.open(str(pdf_path))
    pages = []
    for i, page in enumerate(doc):
        text = page.get_text("text")
        if text.strip():
            pages.append({"page": i + 1, "text": text})
    doc.close()
    return pages


def chunk_pages(pages, orpha_id, source_name, chunk_size=CHUNK_SIZE, overlap=CHUNK_OVERLAP):
    chunks = []
    for page_info in pages:
        text = page_info["text"].strip()
        if len(text) < 50:
            continue

        words = text.split()
        for i in range(0, len(words), chunk_size - overlap):
            chunk_words = words[i:i + chunk_size]
            if len(chunk_words) < 20:
                continue
            chunk_text = " ".join(chunk_words)
            chunks.append({
                "text": chunk_text,
                "orpha_id": orpha_id,
                "source": source_name,
                "page": page_info["page"],
                "source_type": "book",
            })

    return chunks


def embed_and_store(chunks, db_path=DB_PATH, batch_size=64):
    if not chunks:
        print("No chunks to embed.")
        return

    from sentence_transformers import SentenceTransformer
    print(f"Loading BioLORD-2023...")
    model = SentenceTransformer("FremyCompany/BioLORD-2023")

    texts = [c["text"] for c in chunks]
    print(f"Encoding {len(texts)} chunks...")
    embeddings = model.encode(texts, batch_size=batch_size, normalize_embeddings=True,
                              show_progress_bar=True)

    import sqlite_vec
    conn = sqlite3.connect(db_path)
    conn.enable_load_extension(True)
    sqlite_vec.load(conn)

    for i, chunk in enumerate(chunks):
        cur = conn.execute(
            "INSERT INTO chunk_meta (chunk_text, title, source_type, source_id) VALUES (?, ?, ?, ?)",
            (chunk["text"], chunk["orpha_id"], chunk["source_type"],
             f"{chunk['source']}_p{chunk['page']}"),
        )
        rowid = cur.lastrowid
        emb_blob = serialize_vec(embeddings[i])
        conn.execute(
            "INSERT INTO vec_chunks (rowid, embedding) VALUES (?, ?)",
            (rowid, emb_blob),
        )

    conn.commit()

    n = conn.execute(
        "SELECT COUNT(*) FROM chunk_meta WHERE source_type = 'book'"
    ).fetchone()[0]
    print(f"Done. Total book chunks in DB: {n}")
    conn.close()


def list_books(db_path=DB_PATH):
    conn = sqlite3.connect(db_path)
    rows = conn.execute("""
        SELECT title, COUNT(*) as n_chunks
        FROM chunk_meta WHERE source_type = 'book'
        GROUP BY title ORDER BY title
    """).fetchall()
    conn.close()

    if not rows:
        print("No books embedded yet.")
        return

    total = sum(r[1] for r in rows)
    print(f"Embedded books ({len(rows)} sources, {total} chunks):")
    for title, n in rows:
        print(f"  {n:>5d} chunks | {title}")


def process_path(path, db_path=DB_PATH):
    path = Path(path)

    if path.is_file() and path.suffix.lower() == ".pdf":
        pdfs = [path]
    elif path.is_dir():
        pdfs = sorted(path.glob("*.pdf"))
    else:
        print(f"Not a PDF or directory: {path}")
        return

    if not pdfs:
        print(f"No PDFs found in {path}")
        return

    conn = sqlite3.connect(db_path)
    existing = set(
        r[0] for r in conn.execute(
            "SELECT DISTINCT title FROM chunk_meta WHERE source_type = 'book'"
        ).fetchall()
    )
    conn.close()

    all_chunks = []
    for pdf in pdfs:
        orpha_id, label = parse_orpha_from_filename(pdf.stem)
        title_key = orpha_id or pdf.stem

        if title_key in existing:
            print(f"  SKIP (already embedded): {title_key}")
            continue

        if not orpha_id:
            print(f"  WARN no ORPHA prefix: {pdf.name} — chunks won't map to a syndrome")

        print(f"\n  Processing: {pdf.name} ({pdf.stat().st_size / 1024 / 1024:.1f} MB)")
        if orpha_id:
            print(f"    ORPHA: {orpha_id}  label: {label}")
        pages = extract_text_from_pdf(pdf)
        print(f"    {len(pages)} pages extracted")

        chunks = chunk_pages(pages, orpha_id or "unknown", title_key)
        print(f"    {len(chunks)} chunks created")
        all_chunks.extend(chunks)

    if all_chunks:
        print(f"\nTotal: {len(all_chunks)} new chunks to embed")
        embed_and_store(all_chunks, db_path=db_path)
    else:
        print("\nNothing new to embed.")


def main():
    parser = argparse.ArgumentParser(description="Embed reference books into BioLORD")
    parser.add_argument("path", nargs="?", help="PDF file or directory")
    parser.add_argument("--list", action="store_true", help="List embedded books")
    parser.add_argument("--db", default=DB_PATH)
    args = parser.parse_args()

    if args.list:
        list_books(args.db)
    elif args.path:
        process_path(args.path, db_path=args.db)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
