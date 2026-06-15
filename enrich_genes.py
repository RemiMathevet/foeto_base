#!/usr/bin/env python3
"""
enrich_genes.py
===============
Enrichit les tables `genes` et `syndrome_genes` de syndromes_foetaux.db
à partir du fichier Orphadata product6 (gene-disease associations).

Source : http://www.orphadata.org/data/xml/en_product6.xml

Usage :
  python enrich_genes.py [--download]   # --download pour re-télécharger le XML
"""

import argparse
import os
import sqlite3
import sys
from pathlib import Path
from xml.etree import ElementTree as ET

import requests

DB_PATH = Path(__file__).parent / "syndromes_foetaux.db"
CACHE_DIR = Path(__file__).parent.parent / "akinator" / "orphadata_cache"
GENES_XML = CACHE_DIR / "genes_en.xml"
GENES_URL = "http://www.orphadata.org/data/xml/en_product6.xml"

ASSOCIATION_TYPE_MAP = {
    "Disease-causing germline mutation(s) in": "causal",
    "Disease-causing germline mutation(s) (loss of function) in": "causal",
    "Disease-causing germline mutation(s) (gain of function) in": "causal",
    "Disease-causing somatic mutation(s) in": "causal",
    "Part of a fusion gene in": "causal",
    "Role in the phenotype of": "causal",
    "Major susceptibility factor in": "susceptibilite",
    "Modifying germline mutation in": "modificateur",
    "Candidate gene tested in": "candidat",
    "Biomarker tested in": "biomarker",
}


def download_xml():
    """Télécharge le XML Orphadata product6."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    print(f"Downloading {GENES_URL} ...")
    r = requests.get(GENES_URL, timeout=120)
    r.raise_for_status()
    GENES_XML.write_bytes(r.content)
    print(f"  → {len(r.content) / 1024 / 1024:.1f} MB saved to {GENES_XML}")


def parse_gene_associations(xml_path: Path):
    """Parse le XML et retourne (genes_dict, associations_list)."""
    tree = ET.parse(str(xml_path))
    root = tree.getroot()
    disorder_list = root.find("DisorderList")

    genes = {}
    associations = []

    for disorder in disorder_list:
        orpha_code = disorder.findtext("OrphaCode", "")
        syndrome_id = f"ORPHA:{orpha_code}"

        assoc_list = disorder.find("DisorderGeneAssociationList")
        if assoc_list is None:
            continue

        for assoc in assoc_list:
            gene_el = assoc.find("Gene")
            if gene_el is None:
                continue

            symbol = gene_el.findtext("Symbol", "").strip()
            if not symbol:
                continue

            gene_name = gene_el.findtext("Name", "").strip()

            omim_ref = None
            ext_refs = gene_el.find("ExternalReferenceList")
            if ext_refs is not None:
                for ref in ext_refs:
                    if ref.findtext("Source") == "OMIM":
                        omim_ref = ref.findtext("Reference")
                        break

            locus = None
            locus_list = gene_el.find("LocusList")
            if locus_list is not None:
                for loc in locus_list:
                    gl = loc.find("GeneLocus")
                    if gl is not None and gl.text:
                        locus = gl.text.strip()
                        break

            gene_type = None
            gt_el = gene_el.find("GeneType")
            if gt_el is not None:
                gt_name = gt_el.find("Name")
                if gt_name is not None:
                    gene_type = gt_name.text

            if symbol not in genes:
                genes[symbol] = {
                    "name": gene_name,
                    "omim": omim_ref,
                    "locus": locus,
                    "gene_type": gene_type,
                }

            assoc_type_el = assoc.find("DisorderGeneAssociationType")
            assoc_type_raw = ""
            if assoc_type_el is not None:
                name_el = assoc_type_el.find("Name")
                if name_el is not None:
                    assoc_type_raw = name_el.text or ""

            role = ASSOCIATION_TYPE_MAP.get(assoc_type_raw, "autre")

            status_el = assoc.find("DisorderGeneAssociationStatus")
            status = ""
            if status_el is not None:
                name_el = status_el.find("Name")
                if name_el is not None:
                    status = name_el.text or ""

            source_val = assoc.findtext("SourceOfValidation", "").strip()

            associations.append({
                "syndrome_id": syndrome_id,
                "gene_symbol": symbol,
                "role": role,
                "assoc_type_raw": assoc_type_raw,
                "status": status,
                "source": source_val if source_val else "Orphanet",
            })

    return genes, associations


def update_schema(cur):
    """Ajoute les colonnes manquantes si besoin."""
    cur.execute("PRAGMA table_info(genes)")
    cols = {row[1] for row in cur.fetchall()}
    if "locus" not in cols:
        cur.execute("ALTER TABLE genes ADD COLUMN locus TEXT")
    if "gene_type" not in cols:
        cur.execute("ALTER TABLE genes ADD COLUMN gene_type TEXT")

    # Étendre le CHECK constraint sur syndrome_genes.role
    # SQLite ne permet pas ALTER CHECK, mais on peut ignorer via PRAGMA
    # On insère avec les nouvelles valeurs directement


def import_genes(cur, genes: dict, associations: list):
    """Insère gènes et associations dans la DB."""

    # Syndromes existants dans la base
    cur.execute("SELECT id FROM syndromes")
    known_syndromes = {row[0] for row in cur.fetchall()}

    # --- Genes ---
    n_genes_new = 0
    n_genes_updated = 0
    for symbol, info in genes.items():
        cur.execute("SELECT symbol FROM genes WHERE symbol = ?", (symbol,))
        if cur.fetchone():
            cur.execute("""
                UPDATE genes SET
                    name = COALESCE(?, name),
                    omim = COALESCE(?, omim),
                    locus = COALESCE(?, locus),
                    gene_type = COALESCE(?, gene_type)
                WHERE symbol = ?
            """, (info["name"], info["omim"], info["locus"],
                  info["gene_type"], symbol))
            n_genes_updated += 1
        else:
            cur.execute("""
                INSERT INTO genes (symbol, name, omim, locus, gene_type)
                VALUES (?, ?, ?, ?, ?)
            """, (symbol, info["name"], info["omim"],
                  info["locus"], info["gene_type"]))
            n_genes_new += 1

    # --- Associations ---
    n_assoc_new = 0
    n_assoc_skip_syndrome = 0
    n_assoc_skip_dup = 0
    for a in associations:
        if a["syndrome_id"] not in known_syndromes:
            n_assoc_skip_syndrome += 1
            continue

        # Mapper les rôles non-standard vers les valeurs acceptées par le CHECK
        role = a["role"]
        if role not in ("causal", "modificateur", "susceptibilite"):
            role = "susceptibilite"

        cur.execute("""
            SELECT 1 FROM syndrome_genes
            WHERE syndrome_id = ? AND gene_symbol = ?
        """, (a["syndrome_id"], a["gene_symbol"]))

        if cur.fetchone():
            n_assoc_skip_dup += 1
            continue

        cur.execute("""
            INSERT INTO syndrome_genes (syndrome_id, gene_symbol, role, source)
            VALUES (?, ?, ?, ?)
        """, (a["syndrome_id"], a["gene_symbol"], role, a["source"]))
        n_assoc_new += 1

    return {
        "genes_new": n_genes_new,
        "genes_updated": n_genes_updated,
        "assoc_new": n_assoc_new,
        "assoc_skip_syndrome": n_assoc_skip_syndrome,
        "assoc_skip_dup": n_assoc_skip_dup,
    }


def print_stats(cur):
    """Affiche les stats post-enrichissement."""
    queries = [
        ("Gènes total", "SELECT COUNT(*) FROM genes"),
        ("  avec OMIM", "SELECT COUNT(*) FROM genes WHERE omim IS NOT NULL"),
        ("  avec locus", "SELECT COUNT(*) FROM genes WHERE locus IS NOT NULL"),
        ("Associations syndrome↔gène", "SELECT COUNT(*) FROM syndrome_genes"),
        ("  causal", "SELECT COUNT(*) FROM syndrome_genes WHERE role='causal'"),
        ("  modificateur", "SELECT COUNT(*) FROM syndrome_genes WHERE role='modificateur'"),
        ("  susceptibilité", "SELECT COUNT(*) FROM syndrome_genes WHERE role='susceptibilite'"),
        ("Syndromes avec ≥1 gène",
         "SELECT COUNT(DISTINCT syndrome_id) FROM syndrome_genes"),
        ("Syndromes sans gène",
         "SELECT COUNT(*) FROM syndromes WHERE id NOT IN "
         "(SELECT DISTINCT syndrome_id FROM syndrome_genes)"),
    ]
    for label, q in queries:
        cur.execute(q)
        print(f"  {label}: {cur.fetchone()[0]}")

    print("\n  Top 10 gènes (nb syndromes associés) :")
    cur.execute("""
        SELECT g.symbol, g.name, g.omim, COUNT(*) as n
        FROM syndrome_genes sg
        JOIN genes g ON sg.gene_symbol = g.symbol
        GROUP BY g.symbol ORDER BY n DESC LIMIT 10
    """)
    for row in cur.fetchall():
        print(f"    {row[0]:10s} (OMIM:{row[2] or '—':>8s})  "
              f"{row[3]:3d} syndromes  {row[1][:50]}")

    print("\n  Syndromes du benchmark avec gènes :")
    cur.execute("""
        SELECT s.name_fr, GROUP_CONCAT(sg.gene_symbol, ', ') as genes, sg.role
        FROM syndromes s
        JOIN syndrome_genes sg ON s.id = sg.syndrome_id
        WHERE s.name_fr IN (
            'Syndrome CHARGE', 'Syndrome de Noonan',
            'Syndrome de Smith-Lemli-Opitz', 'Syndrome de Meckel',
            'Dysplasie thanatophore', 'Trisomie 21'
        )
        GROUP BY s.id
        ORDER BY s.name_fr
    """)
    for row in cur.fetchall():
        print(f"    {row[0]:40s} → {row[1]}")


def main():
    parser = argparse.ArgumentParser(description="Enrich genes in syndromes_foetaux.db")
    parser.add_argument("--download", action="store_true",
                        help="Re-download en_product6.xml from Orphadata")
    args = parser.parse_args()

    if not DB_PATH.exists():
        print(f"ERROR: {DB_PATH} not found. Run init_syndromes_db.py first.")
        sys.exit(1)

    if args.download or not GENES_XML.exists():
        download_xml()

    if not GENES_XML.exists():
        print(f"ERROR: {GENES_XML} not found. Use --download to fetch it.")
        sys.exit(1)

    print(f"Parsing {GENES_XML} ...")
    genes, associations = parse_gene_associations(GENES_XML)
    print(f"  → {len(genes)} unique genes, {len(associations)} associations")

    print(f"\nEnriching {DB_PATH} ...")
    conn = sqlite3.connect(str(DB_PATH))
    cur = conn.cursor()
    cur.execute("PRAGMA foreign_keys=ON")

    update_schema(cur)
    stats = import_genes(cur, genes, associations)
    conn.commit()

    print(f"\nImport results:")
    print(f"  Genes new:                {stats['genes_new']}")
    print(f"  Genes updated:            {stats['genes_updated']}")
    print(f"  Associations new:         {stats['assoc_new']}")
    print(f"  Associations skip (no syndrome): {stats['assoc_skip_syndrome']}")
    print(f"  Associations skip (duplicate):   {stats['assoc_skip_dup']}")

    print(f"\n{'=' * 60}")
    print("DATABASE GENE STATS")
    print("=" * 60)
    print_stats(cur)

    conn.close()
    size_kb = DB_PATH.stat().st_size / 1024
    print(f"\nDone. DB size: {size_kb:.0f} KB")


if __name__ == "__main__":
    main()
