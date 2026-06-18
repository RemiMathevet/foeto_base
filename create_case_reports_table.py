#!/usr/bin/env python3
"""Crée la table case_reports dans syndromes_foetaux.db.

Table de cas cliniques résolus pour l'outil ORACULUM case_search.
Le 9B peut retrouver des cas similaires par matching HPO et raisonner
par analogie ("ce cas ressemble au cas X qui était un syndrome Y").
"""

import sqlite3
import shutil
from pathlib import Path

DB_PATH = Path("/home/mathevet/Bureau/foeto_base/syndromes_foetaux.db")


def main():
    shutil.copy(DB_PATH, str(DB_PATH) + ".bak_pre_case_reports")
    print(f"Backup: {DB_PATH}.bak_pre_case_reports")

    conn = sqlite3.connect(str(DB_PATH))

    conn.execute("""
        CREATE TABLE IF NOT EXISTS case_reports (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            syndrome_id     TEXT REFERENCES syndromes(id),
            gold_diagnosis  TEXT NOT NULL,
            clinical_text   TEXT NOT NULL,
            hpo_tags        TEXT,
            format          TEXT NOT NULL DEFAULT 'clinical_report'
                            CHECK(format IN ('clinical_report', 'hpo_structured', 'free_text', 'pubmed_abstract')),
            source          TEXT NOT NULL DEFAULT 'synthetic',
            source_model    TEXT,
            difficulty      TEXT,
            created_at      TEXT NOT NULL DEFAULT (datetime('now'))
        )
    """)

    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_case_reports_syndrome
        ON case_reports(syndrome_id)
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_case_reports_source
        ON case_reports(source)
    """)

    conn.execute("""
        CREATE VIRTUAL TABLE IF NOT EXISTS case_reports_fts
        USING fts5(
            clinical_text,
            gold_diagnosis,
            hpo_tags,
            content='case_reports',
            content_rowid='id'
        )
    """)

    conn.execute("""
        CREATE TRIGGER IF NOT EXISTS case_reports_ai AFTER INSERT ON case_reports BEGIN
            INSERT INTO case_reports_fts(rowid, clinical_text, gold_diagnosis, hpo_tags)
            VALUES (new.id, new.clinical_text, new.gold_diagnosis, new.hpo_tags);
        END
    """)
    conn.execute("""
        CREATE TRIGGER IF NOT EXISTS case_reports_ad AFTER DELETE ON case_reports BEGIN
            INSERT INTO case_reports_fts(case_reports_fts, rowid, clinical_text, gold_diagnosis, hpo_tags)
            VALUES ('delete', old.id, old.clinical_text, old.gold_diagnosis, old.hpo_tags);
        END
    """)
    conn.execute("""
        CREATE TRIGGER IF NOT EXISTS case_reports_au AFTER UPDATE ON case_reports BEGIN
            INSERT INTO case_reports_fts(case_reports_fts, rowid, clinical_text, gold_diagnosis, hpo_tags)
            VALUES ('delete', old.id, old.clinical_text, old.gold_diagnosis, old.hpo_tags);
            INSERT INTO case_reports_fts(rowid, clinical_text, gold_diagnosis, hpo_tags)
            VALUES (new.id, new.clinical_text, new.gold_diagnosis, new.hpo_tags);
        END
    """)

    conn.commit()

    count = conn.execute("SELECT COUNT(*) FROM case_reports").fetchone()[0]
    print(f"Table case_reports créée ({count} rows)")
    print("Index FTS5 créé sur clinical_text + gold_diagnosis + hpo_tags")

    conn.close()


if __name__ == "__main__":
    main()
