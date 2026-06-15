#!/usr/bin/env python3
"""
Enrichit la table hpo_terms avec :
  - label_fr        : traduction officielle HPO (hp-fr.babelon.tsv)
  - aliases_fr      : synonymes FR cliniques (hp-fr.synonyms.tsv)
  - category        : système organique déduit de l'ontologie HPO (hp.obo)

Sources :
  hp.obo             — ontologie HPO (hiérarchie is_a)
  hp-fr.babelon.tsv  — traductions FR officielles (projet hpo-translations)
  hp-fr.synonyms.tsv — synonymes FR officiels
"""

import re
import sqlite3
import sys
from collections import defaultdict

DB_PATH = "syndromes_foetaux.db"
OBO_PATH = "hp.obo"
FR_LABELS_PATH = "hp-fr.babelon.tsv"
FR_SYNONYMS_PATH = "hp-fr.synonyms.tsv"

TOP_LEVEL_CATEGORIES = {
    "HP:0000119": "Génito-urinaire",
    "HP:0000152": "Tête / Cou",
    "HP:0000478": "Œil",
    "HP:0000598": "Oreille",
    "HP:0000707": "Système nerveux",
    "HP:0000769": "Sein",
    "HP:0000818": "Endocrinien",
    "HP:0001197": "Prénatal / Naissance",
    "HP:0001507": "Croissance",
    "HP:0001574": "Téguments",
    "HP:0001608": "Voix",
    "HP:0001626": "Cardiovasculaire",
    "HP:0001871": "Sang / Hématopoïèse",
    "HP:0001939": "Métabolisme",
    "HP:0002086": "Respiratoire",
    "HP:0002664": "Néoplasie",
    "HP:0002715": "Immunitaire",
    "HP:0025031": "Digestif",
    "HP:0025142": "Constitutionnel",
    "HP:0025354": "Cellulaire",
    "HP:0033127": "Musculo-squelettique",
    "HP:0040064": "Membres",
    "HP:0045027": "Thorax",
}


def parse_obo(path: str):
    """Parse hp.obo → dict of parents and names."""
    parents = defaultdict(list)
    names = {}
    current_id = None
    is_obsolete = False

    with open(path) as f:
        for line in f:
            line = line.rstrip()
            if line == "[Term]":
                current_id = None
                is_obsolete = False
            elif line.startswith("id: HP:"):
                current_id = line[4:]
            elif line.startswith("name: ") and current_id:
                names[current_id] = line[6:]
            elif line == "is_obsolete: true":
                is_obsolete = True
            elif line.startswith("is_a: HP:") and current_id and not is_obsolete:
                parent = line[6:].split(" !")[0].strip()
                parents[current_id].append(parent)

    return parents, names


def build_ancestors(parents: dict) -> dict[str, set[str]]:
    """Pour chaque terme, calcule l'ensemble de tous ses ancêtres."""
    cache = {}

    def _ancestors(hpo_id):
        if hpo_id in cache:
            return cache[hpo_id]
        result = set()
        for p in parents.get(hpo_id, []):
            result.add(p)
            result |= _ancestors(p)
        cache[hpo_id] = result
        return result

    for hpo_id in list(parents.keys()):
        _ancestors(hpo_id)
    return cache


def classify_term(hpo_id: str, ancestors: dict[str, set[str]]) -> str:
    """Trouve la catégorie organique via les ancêtres top-level."""
    ancs = ancestors.get(hpo_id, set())
    ancs.add(hpo_id)
    matches = []
    for top_id, label in TOP_LEVEL_CATEGORIES.items():
        if top_id in ancs:
            matches.append(label)
    if not matches:
        return "Autre"
    if len(matches) == 1:
        return matches[0]
    return matches[0]


def load_fr_labels(path: str) -> dict[str, str]:
    """Charge les traductions FR depuis hp-fr.babelon.tsv."""
    labels = {}
    with open(path) as f:
        for line in f:
            parts = line.rstrip("\n").split("\t")
            if len(parts) >= 7 and parts[3] == "rdfs:label" and parts[0].startswith("HP:"):
                labels[parts[0]] = parts[6]
    return labels


def load_fr_synonyms(path: str) -> dict[str, list[str]]:
    """Charge les synonymes FR depuis hp-fr.synonyms.tsv."""
    synonyms = defaultdict(list)
    with open(path) as f:
        for line in f:
            parts = line.rstrip("\n").split("\t")
            if len(parts) >= 2 and parts[0].startswith("HP:"):
                for syn in parts[1].split("|"):
                    syn = syn.strip()
                    if syn:
                        synonyms[parts[0]].append(syn)
    return synonyms


def deduplicate_synonyms(syns: list[str], label_fr: str | None) -> list[str]:
    """Déduplique les synonymes, retire ceux identiques au label_fr."""
    seen = set()
    result = []
    label_lower = (label_fr or "").lower().strip()
    for s in syns:
        key = s.lower().strip()
        if key and key != label_lower and key not in seen:
            seen.add(key)
            result.append(s.strip())
    return result


def main():
    print("Parsing hp.obo...")
    parents, names = parse_obo(OBO_PATH)
    print(f"  {len(names)} termes dans l'ontologie")

    print("Construction de l'arbre d'ancêtres...")
    ancestors = build_ancestors(parents)

    print(f"Chargement traductions FR depuis {FR_LABELS_PATH}...")
    fr_labels = load_fr_labels(FR_LABELS_PATH)
    print(f"  {len(fr_labels)} traductions")

    print(f"Chargement synonymes FR depuis {FR_SYNONYMS_PATH}...")
    fr_synonyms = load_fr_synonyms(FR_SYNONYMS_PATH)
    print(f"  {len(fr_synonyms)} termes avec synonymes")

    db = sqlite3.connect(DB_PATH)
    db.row_factory = sqlite3.Row

    cols = [r[1] for r in db.execute("PRAGMA table_info(hpo_terms)").fetchall()]
    if "aliases_fr" not in cols:
        print("Ajout de la colonne aliases_fr...")
        db.execute("ALTER TABLE hpo_terms ADD COLUMN aliases_fr TEXT")

    all_terms = db.execute("SELECT hpo_id, label_en FROM hpo_terms").fetchall()
    total = len(all_terms)
    print(f"\nEnrichissement de {total} termes HPO...")

    n_fr = 0
    n_cat = 0
    n_alias = 0

    for i, row in enumerate(all_terms, 1):
        hpo_id = row["hpo_id"]

        label_fr = fr_labels.get(hpo_id)
        category = classify_term(hpo_id, ancestors)
        raw_syns = fr_synonyms.get(hpo_id, [])
        aliases = deduplicate_synonyms(raw_syns, label_fr)
        aliases_str = " | ".join(aliases) if aliases else None

        if label_fr:
            n_fr += 1
        if category != "Autre":
            n_cat += 1
        if aliases_str:
            n_alias += 1

        db.execute("""
            UPDATE hpo_terms
            SET label_fr = COALESCE(?, label_fr),
                category = ?,
                aliases_fr = ?
            WHERE hpo_id = ?
        """, (label_fr, category, aliases_str, hpo_id))

        if i % 1000 == 0:
            db.commit()
            print(f"  [{i}/{total}]")

    db.commit()

    print(f"\n--- Résultat ---")
    print(f"  label_fr  remplis : {n_fr}/{total} ({100*n_fr/total:.1f}%)")
    print(f"  category  remplis : {n_cat}/{total} ({100*n_cat/total:.1f}%)")
    print(f"  aliases_fr remplis: {n_alias}/{total} ({100*n_alias/total:.1f}%)")

    print("\nDistribution par catégorie :")
    for row in db.execute("""
        SELECT category, COUNT(*) AS n
        FROM hpo_terms
        GROUP BY category
        ORDER BY n DESC
    """).fetchall():
        print(f"  {row['category']:30s} {row['n']:>5d}")

    print("\nExemples :")
    for row in db.execute("""
        SELECT hpo_id, label_en, label_fr, aliases_fr, category
        FROM hpo_terms
        WHERE aliases_fr IS NOT NULL
        ORDER BY RANDOM()
        LIMIT 10
    """).fetchall():
        print(f"  {row['hpo_id']} | {row['label_en']}")
        print(f"    FR: {row['label_fr']}")
        print(f"    Alias: {row['aliases_fr']}")
        print(f"    Cat: {row['category']}")

    db.close()
    print("\nTerminé.")


if __name__ == "__main__":
    main()
