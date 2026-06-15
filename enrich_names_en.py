#!/usr/bin/env python3
"""
enrich_names_en.py
==================
Enrichit le champ name_en des syndromes depuis les XML Orphadata anglais.

Sources (par ordre de priorité) :
  - ages_en.xml       (7374 entries — la plus large)
  - hpo_en.xml        (4337 entries)
  - genes_en.xml      (4128 entries)
"""

import sqlite3
import sys
from pathlib import Path
from xml.etree import ElementTree as ET

DB_PATH = Path(__file__).parent / "syndromes_foetaux.db"
CACHE_DIR = Path(__file__).parent.parent / "akinator" / "orphadata_cache"

SOURCES = [
    ("ages_en.xml", "DisorderList", "Disorder"),
    ("genes_en.xml", "DisorderList", "Disorder"),
]


def extract_names_from_hpo(xml_path: Path) -> dict:
    """hpo_en.xml has a different structure."""
    names = {}
    tree = ET.parse(str(xml_path))
    root = tree.getroot()
    for wrapper in root.find("HPODisorderSetStatusList"):
        d = wrapper.find("Disorder")
        if d is None:
            continue
        orpha = d.findtext("OrphaCode", "").strip()
        name = d.findtext("Name", "").strip()
        if orpha and name:
            names[f"ORPHA:{orpha}"] = name
    return names


def extract_names_from_standard(xml_path: Path, list_tag: str, item_tag: str) -> dict:
    names = {}
    tree = ET.parse(str(xml_path))
    root = tree.getroot()
    container = root.find(list_tag)
    if container is None:
        return names
    for d in container:
        orpha = d.findtext("OrphaCode", "").strip()
        name = d.findtext("Name", "").strip()
        if orpha and name:
            names[f"ORPHA:{orpha}"] = name
    return names


def main():
    if not DB_PATH.exists():
        print(f"ERROR: {DB_PATH} not found.")
        sys.exit(1)

    all_names = {}

    # Load all sources, later sources overwrite earlier ones
    for filename, list_tag, item_tag in SOURCES:
        path = CACHE_DIR / filename
        if not path.exists():
            print(f"  SKIP: {path} not found")
            continue
        print(f"Parsing {filename} ...")
        names = extract_names_from_standard(path, list_tag, item_tag)
        print(f"  → {len(names)} names")
        all_names.update(names)

    # HPO file (special structure)
    hpo_path = CACHE_DIR / "hpo_en.xml"
    if hpo_path.exists():
        print(f"Parsing hpo_en.xml ...")
        names = extract_names_from_hpo(hpo_path)
        print(f"  → {len(names)} names")
        all_names.update(names)

    print(f"\nTotal unique English names collected: {len(all_names)}")

    conn = sqlite3.connect(str(DB_PATH))
    cur = conn.cursor()

    cur.execute("SELECT id, name_en FROM syndromes")
    syndromes = {row[0]: row[1] for row in cur.fetchall()}

    updated = 0
    already = 0
    not_found = 0

    for sid, current_name_en in syndromes.items():
        if sid in all_names:
            new_name = all_names[sid]
            if current_name_en and current_name_en.strip():
                already += 1
                continue
            cur.execute("UPDATE syndromes SET name_en = ?, updated_at = datetime('now') WHERE id = ?",
                        (new_name, sid))
            updated += 1
        else:
            not_found += 1

    conn.commit()

    print(f"\nResults:")
    print(f"  Updated:    {updated}")
    print(f"  Already set: {already}")
    print(f"  Not found:  {not_found} (no English name in sources)")
    print(f"  Total syndromes: {len(syndromes)}")

    # Verify Bosma/arhinia
    cur.execute("SELECT id, name_fr, name_en FROM syndromes WHERE name_fr LIKE '%rhini%' OR name_en LIKE '%rhini%'")
    for row in cur.fetchall():
        print(f"\n  Check: {row[0]} → FR: {row[1]} | EN: {row[2]}")

    conn.close()
    print("\nDone.")


if __name__ == "__main__":
    main()
