#!/usr/bin/env python3
"""
init_syndromes_db.py
====================
Crée la base syndromes_foetaux.db et importe les données
depuis les JSON Akinator existants.

Sources :
  - akinator_data/akinator_foetopath_full.json      (3194 syndromes + signes)
  - akinator_data/02_phenotypes_hpo.json             (associations HPO détaillées)
  - akinator_data/03_disorders_classified.json       (catégories / relevance)
  - akinator_data/excluded_hpo_terms.json            (HPO exclus akinator)

Usage :
  python init_syndromes_db.py [--reset]
"""

import argparse
import json
import os
import re
import sqlite3
import sys
from pathlib import Path

DB_PATH = Path(__file__).parent / "syndromes_foetaux.db"
AKINATOR_DIR = Path(__file__).parent.parent / "akinator" / "akinator_data"

PRENATAL_HPO_PREFIXES = {
    "HP:0001511", "HP:0001562", "HP:0001561", "HP:0001622",
    "HP:0010880", "HP:0011425", "HP:0011436", "HP:0011438",
    "HP:0034058", "HP:0100767",
}

PRENATAL_KEYWORDS = {
    "fetal", "foetal", "prenatal", "prénatal", "antenatal",
    "amniotic", "amniotique", "oligohydramnios", "polyhydramnios",
    "hydrops", "hygroma", "nuchal", "nucal",
    "placenta", "omphalocele", "omphalocèle", "gastroschisis",
    "meconium", "méconium", "cystic hygroma",
    "intrauterine", "intra-utérin", "iugr", "rciu",
}

POSTNATAL_KEYWORDS = {
    "learning", "school", "speech delay", "walking",
    "developmental delay", "intellectual disability",
    "behavioral", "behaviour", "anxiety", "depression",
    "puberty", "menstrual", "infertility",
    "occupational", "dementia", "alzheimer",
}

SCHEMA_SQL = """
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

-- ============================================================
-- SYNDROMES
-- ============================================================
CREATE TABLE IF NOT EXISTS syndromes (
    id              TEXT PRIMARY KEY,       -- ORPHA:XXXXX
    name_fr         TEXT NOT NULL,
    name_en         TEXT,
    omim            TEXT,                   -- OMIM number(s), comma-sep
    orpha_code      TEXT,                   -- numeric part
    type            TEXT,                   -- Maladie, Groupe, etc.
    category        TEXT NOT NULL,          -- malformatif, metabolique, ...
    relevance       TEXT,                   -- haute, moyenne, basse
    prevalence      REAL,
    inheritance     TEXT,                   -- JSON array
    ages_of_onset   TEXT,                   -- JSON array

    -- champs pédagogiques (remplis progressivement)
    description_md          TEXT,
    prenatal_signs_summary  TEXT,
    key_discriminators      TEXT,
    differential_diagnosis  TEXT,           -- JSON array of syndrome IDs
    difficulty_score        REAL,           -- calculé : overlap HPO

    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at      TEXT NOT NULL DEFAULT (datetime('now'))
);

-- ============================================================
-- HPO TERMS
-- ============================================================
CREATE TABLE IF NOT EXISTS hpo_terms (
    hpo_id          TEXT PRIMARY KEY,       -- HP:XXXXXXX
    label_en        TEXT NOT NULL,
    label_fr        TEXT,
    category        TEXT,                   -- organ system
    context         TEXT NOT NULL DEFAULT 'both'
                    CHECK(context IN ('prenatal','postnatal','both')),
    is_excluded     INTEGER NOT NULL DEFAULT 0
);

-- ============================================================
-- SYNDROME <-> HPO  (coeur de la base)
-- ============================================================
CREATE TABLE IF NOT EXISTS syndrome_hpo (
    syndrome_id     TEXT NOT NULL REFERENCES syndromes(id),
    hpo_id          TEXT NOT NULL REFERENCES hpo_terms(hpo_id),
    frequency       TEXT,                   -- Orphanet label
    prob            REAL,                   -- bayesian prob (akinator)
    source          TEXT DEFAULT 'orphanet',
    PRIMARY KEY (syndrome_id, hpo_id)
);

-- ============================================================
-- GENES
-- ============================================================
CREATE TABLE IF NOT EXISTS genes (
    symbol          TEXT PRIMARY KEY,
    name            TEXT,
    omim            TEXT
);

CREATE TABLE IF NOT EXISTS syndrome_genes (
    syndrome_id     TEXT NOT NULL REFERENCES syndromes(id),
    gene_symbol     TEXT NOT NULL REFERENCES genes(symbol),
    role            TEXT DEFAULT 'causal'
                    CHECK(role IN ('causal','modificateur','susceptibilite')),
    source          TEXT,
    PRIMARY KEY (syndrome_id, gene_symbol)
);

-- ============================================================
-- REFERENCES (lien vers littérature / pageindex)
-- ============================================================
CREATE TABLE IF NOT EXISTS syndrome_references (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    syndrome_id     TEXT NOT NULL REFERENCES syndromes(id),
    source          TEXT NOT NULL,          -- OMIM, Orphanet, PubMed, GeneReviews
    identifier      TEXT,                   -- PMID, OMIM#, etc.
    url             TEXT,
    citation        TEXT,
    pageindex_id    TEXT                    -- lien vers chunk pageindex (RAG)
);

-- ============================================================
-- INDEX
-- ============================================================
CREATE INDEX IF NOT EXISTS idx_syndrome_hpo_hpo ON syndrome_hpo(hpo_id);
CREATE INDEX IF NOT EXISTS idx_syndrome_hpo_syn ON syndrome_hpo(syndrome_id);
CREATE INDEX IF NOT EXISTS idx_syndromes_cat    ON syndromes(category);
CREATE INDEX IF NOT EXISTS idx_hpo_context      ON hpo_terms(context);
CREATE INDEX IF NOT EXISTS idx_syndrome_genes_gene ON syndrome_genes(gene_symbol);
CREATE INDEX IF NOT EXISTS idx_syndrome_refs    ON syndrome_references(syndrome_id);

-- ============================================================
-- VIEWS
-- ============================================================
CREATE VIEW IF NOT EXISTS v_syndrome_summary AS
SELECT
    s.id,
    s.name_fr,
    s.category,
    s.relevance,
    COUNT(sh.hpo_id) AS n_hpo_total,
    SUM(CASE WHEN h.context = 'prenatal' THEN 1 ELSE 0 END) AS n_hpo_prenatal,
    SUM(CASE WHEN h.context = 'postnatal' THEN 1 ELSE 0 END) AS n_hpo_postnatal,
    SUM(CASE WHEN h.context = 'both' THEN 1 ELSE 0 END) AS n_hpo_both,
    GROUP_CONCAT(sg.gene_symbol) AS genes
FROM syndromes s
LEFT JOIN syndrome_hpo sh ON s.id = sh.syndrome_id
LEFT JOIN hpo_terms h ON sh.hpo_id = h.hpo_id
LEFT JOIN syndrome_genes sg ON s.id = sg.syndrome_id
GROUP BY s.id;

CREATE VIEW IF NOT EXISTS v_prenatal_signs AS
SELECT
    s.id AS syndrome_id,
    s.name_fr,
    sh.hpo_id,
    h.label_en,
    h.label_fr,
    sh.frequency,
    sh.prob
FROM syndromes s
JOIN syndrome_hpo sh ON s.id = sh.syndrome_id
JOIN hpo_terms h ON sh.hpo_id = h.hpo_id
WHERE h.context IN ('prenatal', 'both')
ORDER BY s.id, sh.prob DESC;
"""


def classify_hpo_context(hpo_id: str, label: str, excluded_ids: set) -> str:
    """Tag un terme HPO comme prenatal / postnatal / both."""
    label_lower = label.lower()

    if hpo_id in excluded_ids:
        pass

    for prefix in PRENATAL_HPO_PREFIXES:
        if hpo_id.startswith(prefix):
            return "prenatal"

    if any(kw in label_lower for kw in PRENATAL_KEYWORDS):
        return "prenatal"

    if any(kw in label_lower for kw in POSTNATAL_KEYWORDS):
        return "postnatal"

    return "both"


def load_json(filename: str):
    path = AKINATOR_DIR / filename
    if not path.exists():
        print(f"  WARN: {path} not found, skipping")
        return None
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def import_syndromes(cur, full_data: list, classified: dict):
    """Import syndromes depuis akinator_foetopath_full.json + classified."""
    count = 0
    for entry in full_data:
        orpha_code = entry.get("orpha_code", "")
        syndrome_id = orpha_code if orpha_code.startswith("ORPHA:") else f"ORPHA:{orpha_code}"
        numeric = re.sub(r"[^0-9]", "", orpha_code)

        classified_entry = classified.get(numeric, {})
        category = entry.get("category") or classified_entry.get("category", "autre")
        relevance = entry.get("relevance") or classified_entry.get("relevance")

        cur.execute("""
            INSERT OR IGNORE INTO syndromes
            (id, name_fr, orpha_code, type, category, relevance,
             prevalence, inheritance, ages_of_onset)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            syndrome_id,
            entry.get("name_fr", ""),
            numeric,
            entry.get("type"),
            category,
            relevance,
            entry.get("prevalence"),
            json.dumps(entry.get("inheritance", []), ensure_ascii=False),
            json.dumps(entry.get("ages_of_onset", []), ensure_ascii=False),
        ))
        count += 1
    return count


def import_hpo_and_associations(cur, full_data: list, phenotypes_hpo: dict,
                                 excluded_hpo: set):
    """Import les termes HPO et les associations syndrome↔HPO."""
    hpo_seen = set()
    assoc_count = 0

    for entry in full_data:
        orpha_code = entry.get("orpha_code", "")
        syndrome_id = orpha_code if orpha_code.startswith("ORPHA:") else f"ORPHA:{orpha_code}"
        signes = entry.get("signes", {})

        for hpo_id, info in signes.items():
            label = info.get("label", "")

            if hpo_id not in hpo_seen:
                context = classify_hpo_context(hpo_id, label, excluded_hpo)
                cur.execute("""
                    INSERT OR IGNORE INTO hpo_terms (hpo_id, label_en, context, is_excluded)
                    VALUES (?, ?, ?, ?)
                """, (
                    hpo_id,
                    label,
                    context,
                    1 if hpo_id in excluded_hpo else 0,
                ))
                hpo_seen.add(hpo_id)

            cur.execute("""
                INSERT OR IGNORE INTO syndrome_hpo
                (syndrome_id, hpo_id, frequency, prob, source)
                VALUES (?, ?, ?, ?, 'orphanet')
            """, (
                syndrome_id,
                hpo_id,
                info.get("freq"),
                info.get("prob"),
            ))
            assoc_count += 1

    # Compléter avec 02_phenotypes_hpo.json (peut contenir des associations
    # supplémentaires pour des syndromes du fichier full sans signes)
    if phenotypes_hpo:
        for disorder_id, phenos in phenotypes_hpo.items():
            syndrome_id = f"ORPHA:{disorder_id}"
            for p in phenos:
                hpo_id = p["hpo_id"]
                label = p.get("hpo_label", "")

                if hpo_id not in hpo_seen:
                    context = classify_hpo_context(hpo_id, label, excluded_hpo)
                    cur.execute("""
                        INSERT OR IGNORE INTO hpo_terms
                        (hpo_id, label_en, context, is_excluded)
                        VALUES (?, ?, ?, ?)
                    """, (
                        hpo_id,
                        label,
                        context,
                        1 if hpo_id in excluded_hpo else 0,
                    ))
                    hpo_seen.add(hpo_id)

                cur.execute("""
                    INSERT OR IGNORE INTO syndrome_hpo
                    (syndrome_id, hpo_id, frequency, prob, source)
                    VALUES (?, ?, ?, ?, 'orphanet_hpo')
                """, (
                    syndrome_id,
                    hpo_id,
                    p.get("frequency"),
                    p.get("prob"),
                ))
                assoc_count += 1

    return len(hpo_seen), assoc_count


def compute_difficulty_scores(cur):
    """Calcule un score de difficulté basé sur le chevauchement HPO inter-syndromes."""
    cur.execute("""
        UPDATE syndromes SET difficulty_score = (
            SELECT COALESCE(MAX(overlap_pct), 0)
            FROM (
                SELECT
                    sh2.syndrome_id AS other_id,
                    ROUND(
                        100.0 * COUNT(*) /
                        NULLIF((SELECT COUNT(*) FROM syndrome_hpo WHERE syndrome_id = syndromes.id), 0),
                    1) AS overlap_pct
                FROM syndrome_hpo sh1
                JOIN syndrome_hpo sh2 ON sh1.hpo_id = sh2.hpo_id
                    AND sh2.syndrome_id != syndromes.id
                WHERE sh1.syndrome_id = syndromes.id
                GROUP BY sh2.syndrome_id
            )
        )
    """)
    return cur.rowcount


def print_stats(cur):
    """Affiche les stats post-import."""
    stats = {}
    for label, query in [
        ("Syndromes", "SELECT COUNT(*) FROM syndromes"),
        ("HPO terms", "SELECT COUNT(*) FROM hpo_terms"),
        ("  prenatal", "SELECT COUNT(*) FROM hpo_terms WHERE context='prenatal'"),
        ("  postnatal", "SELECT COUNT(*) FROM hpo_terms WHERE context='postnatal'"),
        ("  both", "SELECT COUNT(*) FROM hpo_terms WHERE context='both'"),
        ("  excluded (tagged)", "SELECT COUNT(*) FROM hpo_terms WHERE is_excluded=1"),
        ("Associations syndrome↔HPO", "SELECT COUNT(*) FROM syndrome_hpo"),
        ("Categories", "SELECT COUNT(DISTINCT category) FROM syndromes"),
    ]:
        cur.execute(query)
        val = cur.fetchone()[0]
        stats[label] = val
        print(f"  {label}: {val}")

    print("\n  Par catégorie :")
    cur.execute("""
        SELECT category, COUNT(*) as n FROM syndromes
        GROUP BY category ORDER BY n DESC
    """)
    for row in cur.fetchall():
        print(f"    {row[0]}: {row[1]}")

    print("\n  Top 10 syndromes par difficulté (overlap HPO max) :")
    cur.execute("""
        SELECT name_fr, difficulty_score,
               (SELECT COUNT(*) FROM syndrome_hpo WHERE syndrome_id=s.id) as n_hpo
        FROM syndromes s
        WHERE difficulty_score IS NOT NULL
        ORDER BY difficulty_score DESC
        LIMIT 10
    """)
    for row in cur.fetchall():
        print(f"    {row[1]:5.1f}%  ({row[2]:3d} HPO)  {row[0][:70]}")

    print("\n  Contexte HPO — exemples prenatal :")
    cur.execute("""
        SELECT hpo_id, label_en FROM hpo_terms
        WHERE context='prenatal' LIMIT 10
    """)
    for row in cur.fetchall():
        print(f"    {row[0]}: {row[1]}")


def main():
    parser = argparse.ArgumentParser(description="Init syndromes_foetaux.db")
    parser.add_argument("--reset", action="store_true",
                        help="Drop and recreate the database")
    args = parser.parse_args()

    if args.reset and DB_PATH.exists():
        print(f"[RESET] Removing {DB_PATH}")
        DB_PATH.unlink()

    if DB_PATH.exists():
        print(f"Database already exists: {DB_PATH}")
        print("Use --reset to recreate from scratch.")
        sys.exit(1)

    print(f"Creating {DB_PATH} ...")

    # --- Load JSON sources ---
    print("Loading JSON sources ...")
    full_data = load_json("akinator_foetopath_full.json")
    if full_data is None:
        print("ERROR: akinator_foetopath_full.json is required")
        sys.exit(1)

    classified = load_json("03_disorders_classified.json") or {}
    phenotypes_hpo = load_json("02_phenotypes_hpo.json")
    excluded_list = load_json("excluded_hpo_terms.json") or []
    excluded_hpo = {e["hpo_id"] for e in excluded_list if "hpo_id" in e}
    print(f"  Loaded {len(full_data)} syndromes, "
          f"{len(classified)} classified, "
          f"{len(excluded_hpo)} excluded HPO")

    # --- Create DB ---
    conn = sqlite3.connect(str(DB_PATH))
    cur = conn.cursor()
    cur.executescript(SCHEMA_SQL)

    # --- Import ---
    print("\nImporting syndromes ...")
    n_syn = import_syndromes(cur, full_data, classified)
    print(f"  → {n_syn} syndromes")

    print("Importing HPO terms & associations ...")
    n_hpo, n_assoc = import_hpo_and_associations(
        cur, full_data, phenotypes_hpo, excluded_hpo
    )
    print(f"  → {n_hpo} HPO terms, {n_assoc} associations")

    print("Computing difficulty scores (HPO overlap) ...")
    n_diff = compute_difficulty_scores(cur)
    print(f"  → {n_diff} syndromes scored")

    conn.commit()

    # --- Stats ---
    print("\n" + "=" * 60)
    print("DATABASE STATS")
    print("=" * 60)
    print_stats(cur)

    conn.close()
    print(f"\nDone. Database: {DB_PATH}")
    print(f"Size: {DB_PATH.stat().st_size / 1024:.0f} KB")


if __name__ == "__main__":
    main()
