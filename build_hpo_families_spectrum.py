#!/usr/bin/env python3
"""
Phase 1 : Enrichir les HPO par transfert gène-médié
Phase 2 : Construire syndrome_families (arborescence)
Phase 3 : Construire syndrome_spectrum (liens de proximité phénotypique)
Phase 4 : Re-enrichir les descriptions des syndromes mis à jour
"""

import json
import math
import re
import sqlite3
import sys
from collections import defaultdict

DB_PATH = "syndromes_foetaux.db"

# ─── Known family patterns for name-based detection ───────────────────
FAMILY_PATTERNS = {
    "RASopathies": [
        r"noonan", r"costello", r"cardio.facio.cutan", r"cfc\b",
        r"legius", r"nsml", r"leopard", r"neurofibromatose.*1",
    ],
    "Ciliopathies": [
        r"joubert", r"meckel", r"bardet.biedl", r"bbs\b",
        r"senior.lok", r"nephronophtise", r"polykystose",
        r"ciliopathie", r"jeune\b.*asphyxiante",
    ],
    "Cohesinopathies": [
        r"cornelia.de.lange", r"roberts\b", r"cohésinopathie",
    ],
    "Collagénopathies": [
        r"ehlers.danlos", r"ostéogenèse imparfaite", r"stickler",
        r"marshall\b.*syndrome", r"collagénopathie",
    ],
    "Dystroglycanopathies": [
        r"walker.warburg", r"muscle.eye.brain", r"fukuyama",
        r"dystroglycan", r"meb\b",
    ],
    "Craniosynostoses syndromiques": [
        r"apert", r"crouzon", r"pfeiffer.*syndrome", r"muenke",
        r"saethre.chotzen", r"craniosynostose",
    ],
    "Dysplasies squelettiques": [
        r"achondroplasie", r"hypochondroplasie", r"thanatophori",
        r"achondrogénèse", r"dysplasie.*spondylo", r"dysplasie.*diastrophi",
        r"chondrodysplasi", r"ostéochondrodysplasi",
    ],
    "Syndromes de Rett et apparentés": [
        r"\brett\b", r"mecp2", r"cdkl5.*déficien", r"foxg1",
    ],
    "Troubles du spectre Zellweger": [
        r"zellweger", r"adrénoleucodystrophie.*néonatale",
        r"refsum.*infantile", r"peroxysom",
    ],
    "Trisomies et aneuploïdies": [
        r"trisomie\s+\d", r"monosomie", r"turner", r"klinefelter",
        r"triple.x", r"47.*xyy", r"48.*xxyy",
    ],
    "Syndromes microdélétionnels": [
        r"microdélétion", r"délétion\s+\d+[pq]", r"williams",
        r"digeorge", r"smith.magenis", r"wolf.hirschhorn",
        r"cri.du.chat", r"angelman", r"prader.willi",
    ],
    "Glycosylation (CDG)": [
        r"cdg\b", r"glycosylation", r"pmm2",
    ],
    "RASopathies / voie MAPK": [
        r"ras\b", r"mapk", r"braf\b", r"kras\b", r"hras\b",
        r"raf1\b", r"sos1\b", r"shoc2",
    ],
    "Troubles mitochondriaux": [
        r"mitochondri", r"leigh\b", r"melas\b", r"merrf\b",
        r"kearns.sayre", r"pearson\b.*syndrome",
    ],
    "Laminopathies": [
        r"laminopathie", r"progeria", r"hutchinson.gilford",
        r"emery.dreifuss", r"dysplasie.*mandibuloacral",
    ],
    "Tubulinopathies": [
        r"tubulinopathie", r"lissencéphalie", r"polymicrogyrie",
        r"pachygyrie", r"double.cortex",
    ],
    "Syndromes de surcroissance": [
        r"beckwith.wiedemann", r"sotos", r"weaver\b",
        r"simpson.golabi", r"perlman", r"surcroissance",
        r"overgrowth",
    ],
    "CHARGE et apparentés": [
        r"\bcharge\b", r"chd7\b",
    ],
    "Holoprosencéphalies": [
        r"holoprosencéphalie", r"shh\b.*syndrome", r"hpe\b",
    ],
    "Fanconi et instabilité chromosomique": [
        r"fanconi", r"bloom\b", r"instabilité.*chromosom",
        r"ataxie.télangiectasie", r"nijmegen",
    ],
    "Mucopolysaccharidoses": [
        r"mucopolysaccharidos", r"mps\s", r"hurler", r"hunter\b",
        r"sanfilippo", r"morquio", r"maroteaux.lamy", r"sly\b.*syndrome",
    ],
    "Sphingolipidoses": [
        r"gaucher", r"niemann.pick", r"fabry", r"krabbe",
        r"tay.sachs", r"sphingolipidos",
    ],
    "Arthrogryposes": [
        r"arthrogrypose", r"akinésie.*fœtale", r"fetal akinesia",
        r"contractures.*congénitales", r"pterygium.*multiple",
        r"pena.shokeir",
    ],
    "Hydrops fetalis non immun": [
        r"hydrops", r"anasarque",
    ],
    "Dysplasies ectodermiques": [
        r"dysplasie.*ectoderm", r"ectodermal.*dysplasia",
    ],
    "Ichtyoses congénitales": [
        r"ichtyos", r"ichthyos", r"bébé.collodion", r"arlequin",
    ],
    "Épidermolyses bulleuses": [
        r"épidermolyse.*bulleuse", r"epidermolysis.*bullosa",
    ],
}

# Known gene → pathway mappings for family inference
GENE_PATHWAYS = {
    "PTPN11": "RAS/MAPK", "SOS1": "RAS/MAPK", "RAF1": "RAS/MAPK",
    "KRAS": "RAS/MAPK", "HRAS": "RAS/MAPK", "BRAF": "RAS/MAPK",
    "MAP2K1": "RAS/MAPK", "MAP2K2": "RAS/MAPK", "SHOC2": "RAS/MAPK",
    "RIT1": "RAS/MAPK", "NRAS": "RAS/MAPK", "RRAS": "RAS/MAPK",
    "LZTR1": "RAS/MAPK", "NF1": "RAS/MAPK", "SPRED1": "RAS/MAPK",
    "CBL": "RAS/MAPK", "RASA2": "RAS/MAPK", "SOS2": "RAS/MAPK",
    "FGFR1": "FGFR", "FGFR2": "FGFR", "FGFR3": "FGFR",
    "TWIST1": "Craniosynostose", "EFNB1": "Craniosynostose",
    "COL1A1": "Collagène_I", "COL1A2": "Collagène_I",
    "COL2A1": "Collagène_II", "COL11A1": "Collagène_XI",
    "COL11A2": "Collagène_XI", "COL9A1": "Collagène_IX",
    "SMN1": "Motoneurone", "SMN2": "Motoneurone",
    "NIPBL": "Cohésine", "SMC1A": "Cohésine", "SMC3": "Cohésine",
    "RAD21": "Cohésine", "HDAC8": "Cohésine",
    "MECP2": "Rett", "CDKL5": "Rett", "FOXG1": "Rett",
    "PEX1": "Peroxysome", "PEX2": "Peroxysome", "PEX3": "Peroxysome",
    "PEX5": "Peroxysome", "PEX6": "Peroxysome", "PEX7": "Peroxysome",
    "PEX10": "Peroxysome", "PEX12": "Peroxysome", "PEX13": "Peroxysome",
    "PEX14": "Peroxysome", "PEX16": "Peroxysome", "PEX19": "Peroxysome",
    "PEX26": "Peroxysome",
    "POMT1": "Dystroglycanopathie", "POMT2": "Dystroglycanopathie",
    "POMGNT1": "Dystroglycanopathie", "FKTN": "Dystroglycanopathie",
    "FKRP": "Dystroglycanopathie", "LARGE1": "Dystroglycanopathie",
    "ISPD": "Dystroglycanopathie",
    "TUBA1A": "Tubuline", "TUBB2B": "Tubuline", "TUBB3": "Tubuline",
    "TUBA8": "Tubuline", "TUBG1": "Tubuline",
    "BBS1": "BBS/Ciliopathie", "BBS2": "BBS/Ciliopathie",
    "BBS4": "BBS/Ciliopathie", "BBS5": "BBS/Ciliopathie",
    "BBS7": "BBS/Ciliopathie", "BBS9": "BBS/Ciliopathie",
    "BBS10": "BBS/Ciliopathie", "BBS12": "BBS/Ciliopathie",
    "MKKS": "BBS/Ciliopathie", "MKS1": "BBS/Ciliopathie",
    "CC2D2A": "Ciliopathie", "TMEM67": "Ciliopathie",
    "CEP290": "Ciliopathie", "RPGRIP1L": "Ciliopathie",
    "LMNA": "Laminopathie", "ZMPSTE24": "Laminopathie",
    "LMNB1": "Laminopathie", "LMNB2": "Laminopathie",
}


def phase1_enrich_hpo(db):
    """Transfer HPO terms from gene-related syndromes to HPO-less syndromes."""
    print("=" * 60)
    print("PHASE 1 : Enrichissement HPO par transfert gène-médié")
    print("=" * 60)

    missing = db.execute("""
        SELECT s.id FROM syndromes s
        WHERE s.relevance = 'haute'
          AND s.id NOT IN (SELECT DISTINCT syndrome_id FROM syndrome_hpo)
          AND s.id IN (SELECT DISTINCT syndrome_id FROM syndrome_genes)
    """).fetchall()
    missing_ids = {r["id"] for r in missing}
    print(f"Syndromes sans HPO mais avec gènes : {len(missing_ids)}")

    gene_to_hpo = defaultdict(list)
    rows = db.execute("""
        SELECT sg.gene_symbol, sh.hpo_id, sh.frequency, sh.prob,
               sg.syndrome_id
        FROM syndrome_genes sg
        JOIN syndrome_hpo sh ON sh.syndrome_id = sg.syndrome_id
        WHERE sg.role = 'causal'
    """).fetchall()
    for r in rows:
        gene_to_hpo[r["gene_symbol"]].append({
            "hpo_id": r["hpo_id"],
            "frequency": r["frequency"],
            "prob": r["prob"],
            "source_syndrome": r["syndrome_id"],
        })
    print(f"Gènes avec HPO transférables : {len(gene_to_hpo)}")

    total_inserted = 0
    for sid in missing_ids:
        genes = db.execute(
            "SELECT gene_symbol, role FROM syndrome_genes WHERE syndrome_id = ?",
            (sid,)
        ).fetchall()

        hpo_candidates = defaultdict(lambda: {"prob": 0, "freq": None, "count": 0})
        for g in genes:
            sym = g["gene_symbol"]
            role_weight = 1.0 if g["role"] == "causal" else 0.5
            for entry in gene_to_hpo.get(sym, []):
                hpo_id = entry["hpo_id"]
                prob = (entry["prob"] or 0.5) * role_weight * 0.6
                if prob > hpo_candidates[hpo_id]["prob"]:
                    hpo_candidates[hpo_id]["prob"] = prob
                    hpo_candidates[hpo_id]["freq"] = entry["frequency"]
                hpo_candidates[hpo_id]["count"] += 1

        for hpo_id, data in hpo_candidates.items():
            existing = db.execute(
                "SELECT 1 FROM syndrome_hpo WHERE syndrome_id=? AND hpo_id=?",
                (sid, hpo_id)
            ).fetchone()
            if existing:
                continue
            prob = min(data["prob"], 0.7)
            db.execute(
                "INSERT INTO syndrome_hpo (syndrome_id, hpo_id, frequency, prob, source) VALUES (?,?,?,?,?)",
                (sid, hpo_id, data["freq"], prob, "gene_inferred")
            )
            total_inserted += 1

    db.commit()
    now_with = db.execute("""
        SELECT COUNT(DISTINCT syndrome_id) FROM syndrome_hpo
        WHERE source = 'gene_inferred'
    """).fetchone()[0]
    print(f"HPO transférés : {total_inserted} associations pour {now_with} syndromes")
    return total_inserted


def phase2_families(db):
    """Build syndrome_families from gene pathways, name patterns, and gene sharing."""
    print("\n" + "=" * 60)
    print("PHASE 2 : Construction des familles de syndromes")
    print("=" * 60)

    db.execute("DROP TABLE IF EXISTS syndrome_family_members")
    db.execute("DROP TABLE IF EXISTS syndrome_families")
    db.execute("""
        CREATE TABLE syndrome_families (
            family_id TEXT PRIMARY KEY,
            family_name TEXT NOT NULL,
            description TEXT,
            mechanism TEXT,
            n_members INTEGER DEFAULT 0
        )
    """)
    db.execute("""
        CREATE TABLE syndrome_family_members (
            family_id TEXT NOT NULL,
            syndrome_id TEXT NOT NULL,
            confidence REAL DEFAULT 1.0,
            PRIMARY KEY (family_id, syndrome_id),
            FOREIGN KEY (family_id) REFERENCES syndrome_families(family_id),
            FOREIGN KEY (syndrome_id) REFERENCES syndromes(id)
        )
    """)

    syndromes = db.execute(
        "SELECT id, name_fr, name_en, category FROM syndromes WHERE relevance='haute'"
    ).fetchall()
    syn_by_id = {s["id"]: dict(s) for s in syndromes}

    assignments = defaultdict(list)

    # ── Method 1: Name pattern matching ──
    for sid, s in syn_by_id.items():
        name = (s["name_fr"] or "").lower() + " " + (s["name_en"] or "").lower()
        for family_name, patterns in FAMILY_PATTERNS.items():
            for pat in patterns:
                if re.search(pat, name, re.IGNORECASE):
                    assignments[family_name].append((sid, 0.9))
                    break

    # ── Method 2: Gene pathway clustering ──
    gene_rows = db.execute("""
        SELECT sg.syndrome_id, sg.gene_symbol
        FROM syndrome_genes sg
        JOIN syndromes s ON sg.syndrome_id = s.id
        WHERE s.relevance = 'haute' AND sg.role = 'causal'
    """).fetchall()

    syndrome_pathways = defaultdict(set)
    for r in gene_rows:
        pathway = GENE_PATHWAYS.get(r["gene_symbol"])
        if pathway:
            syndrome_pathways[r["syndrome_id"]].add(pathway)

    pathway_to_family = {
        "RAS/MAPK": "RASopathies",
        "FGFR": "Craniosynostoses syndromiques",
        "Collagène_I": "Collagénopathies",
        "Collagène_II": "Collagénopathies",
        "Collagène_XI": "Collagénopathies",
        "Collagène_IX": "Collagénopathies",
        "Cohésine": "Cohesinopathies",
        "Rett": "Syndromes de Rett et apparentés",
        "Peroxysome": "Troubles du spectre Zellweger",
        "Dystroglycanopathie": "Dystroglycanopathies",
        "Tubuline": "Tubulinopathies",
        "BBS/Ciliopathie": "Ciliopathies",
        "Ciliopathie": "Ciliopathies",
        "Laminopathie": "Laminopathies",
        "Craniosynostose": "Craniosynostoses syndromiques",
    }

    for sid, pathways in syndrome_pathways.items():
        for pw in pathways:
            fam = pathway_to_family.get(pw)
            if fam:
                existing = [s for s, _ in assignments.get(fam, [])]
                if sid not in existing:
                    assignments[fam].append((sid, 0.8))

    # ── Method 3: Gene-sharing clustering (connected components) ──
    # Syndromes sharing ≥2 causal genes and not yet assigned
    assigned_sids = set()
    for members in assignments.values():
        for sid, _ in members:
            assigned_sids.add(sid)

    syn_genes = defaultdict(set)
    for r in gene_rows:
        syn_genes[r["syndrome_id"]].add(r["gene_symbol"])

    unassigned = [sid for sid in syn_genes if sid not in assigned_sids]
    gene_clusters = []
    visited = set()

    for sid in unassigned:
        if sid in visited:
            continue
        cluster = {sid}
        queue = [sid]
        while queue:
            current = queue.pop(0)
            for other in unassigned:
                if other in cluster or other in visited:
                    continue
                shared = syn_genes[current] & syn_genes[other]
                if len(shared) >= 2:
                    cluster.add(other)
                    queue.append(other)
        if len(cluster) >= 2:
            gene_clusters.append(cluster)
            visited |= cluster

    auto_id = 0
    for cluster in gene_clusters:
        auto_id += 1
        shared_genes = set.intersection(*(syn_genes[s] for s in cluster))
        if not shared_genes:
            all_genes = set.union(*(syn_genes[s] for s in cluster))
            gene_label = ", ".join(sorted(all_genes)[:5])
        else:
            gene_label = ", ".join(sorted(shared_genes)[:5])
        fam_name = f"Cluster génique {gene_label}"
        for sid in cluster:
            assignments[fam_name].append((sid, 0.7))

    # ── Insert families ──
    family_counter = 0
    for fam_name, members in assignments.items():
        if len(members) < 2:
            continue
        family_counter += 1
        fam_id = f"FAM:{family_counter:04d}"

        unique_members = {}
        for sid, conf in members:
            if sid not in unique_members or conf > unique_members[sid]:
                unique_members[sid] = conf

        mechanism = "name_pattern"
        if fam_name.startswith("Cluster génique"):
            mechanism = "shared_genes"
        elif any(sid for sid, conf in members if conf == 0.8):
            mechanism = "gene_pathway"

        db.execute(
            "INSERT INTO syndrome_families VALUES (?,?,?,?,?)",
            (fam_id, fam_name, None, mechanism, len(unique_members))
        )

        for sid, conf in unique_members.items():
            db.execute(
                "INSERT OR IGNORE INTO syndrome_family_members VALUES (?,?,?)",
                (fam_id, sid, conf)
            )

    db.commit()

    total_fam = db.execute("SELECT COUNT(*) FROM syndrome_families").fetchone()[0]
    total_mem = db.execute("SELECT COUNT(*) FROM syndrome_family_members").fetchone()[0]
    assigned_unique = db.execute("SELECT COUNT(DISTINCT syndrome_id) FROM syndrome_family_members").fetchone()[0]
    print(f"Familles créées : {total_fam}")
    print(f"Membres total : {total_mem}")
    print(f"Syndromes assignés : {assigned_unique} / {len(syn_by_id)}")

    top = db.execute("""
        SELECT f.family_name, f.n_members, f.mechanism
        FROM syndrome_families f ORDER BY f.n_members DESC LIMIT 15
    """).fetchall()
    for f in top:
        print(f"  {f['family_name']} — {f['n_members']} membres ({f['mechanism']})")


def phase3_spectrum(db):
    """Compute pairwise phenotypic similarity for spectrum edges."""
    print("\n" + "=" * 60)
    print("PHASE 3 : Construction du spectre phénotypique")
    print("=" * 60)

    db.execute("DROP TABLE IF EXISTS syndrome_spectrum")
    db.execute("""
        CREATE TABLE syndrome_spectrum (
            syndrome_id_1 TEXT NOT NULL,
            syndrome_id_2 TEXT NOT NULL,
            similarity REAL NOT NULL,
            shared_hpo INTEGER NOT NULL,
            shared_genes INTEGER DEFAULT 0,
            jaccard REAL NOT NULL,
            same_family INTEGER DEFAULT 0,
            PRIMARY KEY (syndrome_id_1, syndrome_id_2)
        )
    """)

    # Load all HPO associations for high-relevance syndromes
    rows = db.execute("""
        SELECT sh.syndrome_id, sh.hpo_id
        FROM syndrome_hpo sh
        JOIN syndromes s ON sh.syndrome_id = s.id
        WHERE s.relevance = 'haute'
    """).fetchall()

    syn_hpo = defaultdict(set)
    for r in rows:
        syn_hpo[r["syndrome_id"]].add(r["hpo_id"])

    # Load gene associations
    gene_rows = db.execute("""
        SELECT sg.syndrome_id, sg.gene_symbol
        FROM syndrome_genes sg
        JOIN syndromes s ON sg.syndrome_id = s.id
        WHERE s.relevance = 'haute'
    """).fetchall()
    syn_genes = defaultdict(set)
    for r in gene_rows:
        syn_genes[r["syndrome_id"]].add(r["gene_symbol"])

    # Load family co-membership
    fam_rows = db.execute("SELECT syndrome_id, family_id FROM syndrome_family_members").fetchall()
    syn_families = defaultdict(set)
    for r in fam_rows:
        syn_families[r["syndrome_id"]].add(r["family_id"])

    # Compute IDF
    total_syn = len(syn_hpo)
    hpo_df = defaultdict(int)
    for hpos in syn_hpo.values():
        for h in hpos:
            hpo_df[h] += 1
    idf = {h: math.log((total_syn + 1) / (n + 1)) for h, n in hpo_df.items()}

    sids = sorted(syn_hpo.keys())
    n = len(sids)
    print(f"Syndromes avec HPO : {n}")
    print(f"Calcul de {n*(n-1)//2} paires...")

    edges = []
    batch = []
    MIN_SHARED = 5
    MIN_JACCARD = 0.04

    for i in range(n):
        if i % 200 == 0 and i > 0:
            print(f"  {i}/{n}...")
        s1 = sids[i]
        h1 = syn_hpo[s1]
        g1 = syn_genes.get(s1, set())
        f1 = syn_families.get(s1, set())

        for j in range(i + 1, n):
            s2 = sids[j]
            h2 = syn_hpo[s2]

            shared = h1 & h2
            n_shared = len(shared)
            if n_shared < MIN_SHARED:
                continue

            union = len(h1 | h2)
            jaccard = n_shared / union if union else 0
            if jaccard < MIN_JACCARD:
                continue

            idf_score = sum(idf.get(h, 1.0) for h in shared)
            max_idf = sum(idf.get(h, 1.0) for h in h1) + sum(idf.get(h, 1.0) for h in h2)
            similarity = (2 * idf_score / max_idf) if max_idf else 0

            g2 = syn_genes.get(s2, set())
            shared_g = len(g1 & g2)

            f2 = syn_families.get(s2, set())
            same_fam = 1 if f1 & f2 else 0

            batch.append((s1, s2, round(similarity, 4), n_shared, shared_g,
                          round(jaccard, 4), same_fam))

            if len(batch) >= 5000:
                db.executemany(
                    "INSERT INTO syndrome_spectrum VALUES (?,?,?,?,?,?,?)",
                    batch
                )
                batch = []

    if batch:
        db.executemany(
            "INSERT INTO syndrome_spectrum VALUES (?,?,?,?,?,?,?)",
            batch
        )
    db.commit()

    total_edges = db.execute("SELECT COUNT(*) FROM syndrome_spectrum").fetchone()[0]
    avg_sim = db.execute("SELECT ROUND(AVG(similarity),3) FROM syndrome_spectrum").fetchone()[0]
    max_sim = db.execute("SELECT ROUND(MAX(similarity),3) FROM syndrome_spectrum").fetchone()[0]
    with_genes = db.execute("SELECT COUNT(*) FROM syndrome_spectrum WHERE shared_genes > 0").fetchone()[0]
    with_fam = db.execute("SELECT COUNT(*) FROM syndrome_spectrum WHERE same_family = 1").fetchone()[0]

    print(f"Edges spectre : {total_edges}")
    print(f"Similarité moyenne : {avg_sim}, max : {max_sim}")
    print(f"Avec gènes partagés : {with_genes}")
    print(f"Même famille : {with_fam}")

    top_pairs = db.execute("""
        SELECT s1.name_fr, s2.name_fr, sp.similarity, sp.shared_hpo, sp.jaccard
        FROM syndrome_spectrum sp
        JOIN syndromes s1 ON sp.syndrome_id_1 = s1.id
        JOIN syndromes s2 ON sp.syndrome_id_2 = s2.id
        ORDER BY sp.similarity DESC
        LIMIT 10
    """).fetchall()
    print("\nTop 10 paires les plus proches :")
    for p in top_pairs:
        print(f"  {p[0]} ↔ {p[1]} — sim={p[2]}, shared={p[3]}, J={p[4]}")


def phase4_re_enrich_descriptions(db):
    """Re-run description enrichment for syndromes that gained HPO via phase 1."""
    print("\n" + "=" * 60)
    print("PHASE 4 : Re-enrichissement des descriptions (syndromes mis à jour)")
    print("=" * 60)

    # Import functions from enrich_descriptions
    sys.path.insert(0, ".")
    from enrich_descriptions import (
        compute_idf, get_all_syndrome_hpo, generate_description_md,
        generate_prenatal_summary, generate_discriminators,
        generate_differential, find_differentials, classify_hpo,
        parse_inheritance, CATEGORY_FR,
    )

    idf = compute_idf(db)
    all_syndrome_hpo = get_all_syndrome_hpo(db)

    name_rows = db.execute("SELECT id, name_fr, category FROM syndromes").fetchall()
    syndrome_names = {r["id"]: r["name_fr"] for r in name_rows}
    syndrome_cats = {r["id"]: r["category"] for r in name_rows}

    updated_sids = db.execute("""
        SELECT DISTINCT syndrome_id FROM syndrome_hpo WHERE source = 'gene_inferred'
    """).fetchall()
    updated_sids = [r["syndrome_id"] for r in updated_sids]
    print(f"Syndromes à re-enrichir : {len(updated_sids)}")

    for sid in updated_sids:
        s = db.execute(
            "SELECT * FROM syndromes WHERE id = ?", (sid,)
        ).fetchone()
        if not s:
            continue

        genes = [dict(g) for g in db.execute("""
            SELECT g.symbol, g.name, sg.role
            FROM syndrome_genes sg JOIN genes g ON sg.gene_symbol = g.symbol
            WHERE sg.syndrome_id = ? ORDER BY sg.role, g.symbol
        """, (sid,)).fetchall()]

        hpo_raw = db.execute("""
            SELECT h.hpo_id, h.label_en, h.label_fr, h.context, sh.frequency, sh.prob
            FROM syndrome_hpo sh JOIN hpo_terms h ON sh.hpo_id = h.hpo_id
            WHERE sh.syndrome_id = ? ORDER BY sh.prob DESC NULLS LAST
        """, (sid,)).fetchall()

        hpo_terms = []
        hpo_by_system = defaultdict(list)
        for h in hpo_raw:
            label = h["label_fr"] if h["label_fr"] else h["label_en"]
            entry = {
                "hpo_id": h["hpo_id"], "label": label,
                "label_en": h["label_en"], "frequency": h["frequency"],
                "prob": h["prob"], "context": h["context"],
            }
            hpo_terms.append(entry)
            system = classify_hpo(h["label_en"] or "")
            hpo_by_system[system].append(entry)

        inheritance = parse_inheritance(s["inheritance"])

        desc = generate_description_md(
            s["name_fr"], s["name_en"], s["category"],
            inheritance, genes, hpo_by_system, s["omim"],
        )
        prenatal = generate_prenatal_summary(hpo_by_system)
        discrim = generate_discriminators(hpo_terms, idf)

        my_hpo_set = all_syndrome_hpo.get(sid, set())
        diffs = find_differentials(
            sid, my_hpo_set, all_syndrome_hpo, idf,
            syndrome_names, syndrome_cats,
        )
        differential = generate_differential(diffs)

        db.execute("""
            UPDATE syndromes SET
                description_md=?, prenatal_signs_summary=?,
                key_discriminators=?, differential_diagnosis=?,
                updated_at=datetime('now')
            WHERE id=?
        """, (desc, prenatal, discrim, differential, sid))

    db.commit()
    print(f"Re-enrichis : {len(updated_sids)} syndromes")


def main():
    db = sqlite3.connect(DB_PATH)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("PRAGMA foreign_keys=ON")

    phase1_enrich_hpo(db)
    phase2_families(db)
    phase3_spectrum(db)
    phase4_re_enrich_descriptions(db)

    print("\n" + "=" * 60)
    print("TERMINÉ")
    print("=" * 60)
    db.close()


if __name__ == "__main__":
    main()
