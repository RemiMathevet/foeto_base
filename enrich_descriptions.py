#!/usr/bin/env python3
"""
Enrichit description_md, prenatal_signs_summary, key_discriminators,
differential_diagnosis pour les syndromes haute relevance.

Approche data-driven : exploite HPO (fréquences, spécificité TF-IDF),
gènes, catégorie, hérédité pour construire les champs textuels.
Les diagnostics différentiels sont calculés par overlap phénotypique pondéré.
"""

import json
import math
import sqlite3
import sys
import re
from collections import defaultdict

DB_PATH = "syndromes_foetaux.db"

# ── Mapping HPO label → système organique (prenatal-relevant) ──────────
ORGAN_SYSTEM_PATTERNS = {
    "SNC / Cerveau": [
        r"cerebr", r"brain", r"holopros", r"corpus callosum", r"ventric(?!ular sep)",
        r"hydroceph", r"microceph", r"macroceph", r"anenceph", r"encephalocele",
        r"neural tube", r"lissenceph", r"polymicrogyria", r"dandy.walker",
        r"cerebell", r"myelomening", r"spina bifida", r"arnold.chiari",
        r"septo.optic", r"agenesis of.*corpus", r"neuronal migration",
        r"cortical dysplasia", r"schizenceph", r"porenceph",
    ],
    "Face / Crâne": [
        r"facial", r"cranio", r"cleft", r"palate", r"micrognathia", r"retrognathia",
        r"hypertelorism", r"hypotelorism", r"epicanth", r"palpebral",
        r"nasal", r"ear\b", r"auricular", r"preauricular", r"low.set ears",
        r"mandibul", r"maxill", r"frontal bossing", r"plagioceph",
        r"craniosynost", r"ptosis", r"coloboma", r"anophthalmia",
        r"microphthalmia", r"choanal", r"robin\b",
    ],
    "Cœur": [
        r"cardiac", r"heart", r"atrial", r"ventricul.*sept", r"atrioventricul",
        r"tetralogy", r"transposition", r"coarctation", r"hypoplastic.*heart",
        r"endocard", r"cardiomy", r"arrhythm", r"truncus", r"aortic",
        r"pulmonary.*stenosis", r"pulmonary.*atresia", r"ebstein",
        r"double outlet", r"single ventricle",
    ],
    "Poumons": [
        r"pulmonary hypoplasia", r"lung", r"diaphragm", r"hernia.*diaphragm",
        r"congenital.*diaphragm", r"pleural", r"respiratory",
        r"tracheo", r"laryngeal", r"bronch",
    ],
    "Rein / Urinaire": [
        r"renal", r"kidney", r"nephro", r"hydroneph", r"polycystic.*kidney",
        r"multicystic", r"dysplastic.*kidney", r"uretr", r"bladder",
        r"megacyst", r"anuri", r"oligohydra.*renal", r"potter",
    ],
    "Squelette / Membres": [
        r"skeletal", r"limb", r"short limb", r"rhizomel", r"mesomel",
        r"achondro", r"osteogene", r"thanatophoric", r"polydact",
        r"syndact", r"oligodact", r"ectrodact", r"brachydact", r"clinodact",
        r"camptodact", r"club.*foot", r"talipes", r"rocker.*bottom",
        r"vertebr", r"scoliosis", r"hemivertebr", r"rib\b", r"short rib",
        r"narrow.*chest", r"thorac", r"femur", r"tibia", r"fibula",
        r"radius", r"ulna", r"absent.*thumb", r"radial.*aplasia",
    ],
    "Abdomen / Digestif": [
        r"omphalocele", r"gastroschisis", r"intestin", r"atresia.*duoden",
        r"atresia.*esoph", r"atresia.*anal", r"imperfor", r"hirschsprung",
        r"abdomin", r"ascites", r"hepat", r"liver", r"spleen", r"splenom",
        r"hepatomeg", r"splenomeg", r"biliary",
    ],
    "Croissance / Biométrie": [
        r"growth retard", r"intrauterine growth", r"iugr", r"short stature",
        r"macrosom", r"large.*gestational", r"small.*gestational",
        r"failure to thrive", r"overgrowth", r"tall stature",
    ],
    "Liquide amniotique / Placenta": [
        r"oligohydra", r"polyhydra", r"anhydra", r"hydrops",
        r"placent", r"umbilical", r"non.immune hydrops", r"cystic hygroma",
        r"nuchal", r"edema.*fetal", r"fetal.*edema",
    ],
    "Peau / Tissus mous": [
        r"skin", r"cutaneous", r"ichthyos", r"epidermolysis",
        r"lymphedema", r"hemangioma", r"nevus", r"redundant skin",
        r"pterygium", r"webbed neck",
    ],
    "Génital": [
        r"cryptorchid", r"hypospadias", r"ambiguous.*genital",
        r"micropenis", r"genital", r"gonad", r"ovari", r"testes",
        r"sex reversal", r"müller",
    ],
    "Neurologique / Neuromusculaire": [
        r"hypotonia", r"hypertonia", r"seizure", r"spastic",
        r"arthrogryposis", r"fetal akinesia", r"contracture",
        r"reduced fetal movement", r"areflexia", r"myopath",
        r"neuropath", r"intellectual disab", r"developmental delay",
    ],
    "Œil": [
        r"cataract", r"glauco", r"retinal", r"optic nerve",
        r"visual impair", r"strabism", r"nystagm", r"aniridia",
        r"microphthalm", r"anophthalm", r"colobom",
    ],
}

CATEGORY_FR = {
    "malformatif": "malformatif",
    "metabolique": "métabolique",
    "neuromusculaire": "neuromusculaire",
    "chromosomique": "chromosomique",
    "squelettique": "squelettique",
    "vasculaire_placentaire": "vasculaire/placentaire",
    "tumoral": "tumoral",
    "infectieux": "infectieux",
    "autre": "autre",
}

INHERITANCE_FR = {
    "Autosomal dominant": "autosomique dominante",
    "Autosomique dominante": "autosomique dominante",
    "Autosomal recessive": "autosomique récessive",
    "Autosomique récessive": "autosomique récessive",
    "X-linked recessive": "récessive liée à l'X",
    "Récessive liée à l'X": "récessive liée à l'X",
    "X-linked dominant": "dominante liée à l'X",
    "Dominante liée à l'X": "dominante liée à l'X",
    "Mitochondrial": "mitochondriale",
    "Mitochondriale": "mitochondriale",
}


def classify_hpo(label_en: str) -> str:
    label_lower = label_en.lower()
    for system, patterns in ORGAN_SYSTEM_PATTERNS.items():
        for pat in patterns:
            if re.search(pat, label_lower):
                return system
    return "Autre"


def parse_inheritance(raw: str) -> list[str]:
    if not raw:
        return []
    try:
        items = json.loads(raw)
        return [INHERITANCE_FR.get(i, i) for i in items
                if i not in ("Non applicable", "Non disponible", "")]
    except (json.JSONDecodeError, TypeError):
        return []


def compute_idf(db: sqlite3.Connection) -> dict[str, float]:
    """IDF de chaque terme HPO = log(N / n_syndromes_with_term)."""
    total = db.execute("SELECT COUNT(*) FROM syndromes").fetchone()[0]
    rows = db.execute("""
        SELECT hpo_id, COUNT(DISTINCT syndrome_id) AS n
        FROM syndrome_hpo GROUP BY hpo_id
    """).fetchall()
    return {r["hpo_id"]: math.log((total + 1) / (r["n"] + 1)) for r in rows}


def get_all_syndrome_hpo(db: sqlite3.Connection) -> dict[str, set[str]]:
    """Mapping syndrome_id → set of hpo_ids."""
    rows = db.execute("SELECT syndrome_id, hpo_id FROM syndrome_hpo").fetchall()
    d = defaultdict(set)
    for r in rows:
        d[r["syndrome_id"]].add(r["hpo_id"])
    return d


def find_differentials(
    sid: str,
    my_hpo: set[str],
    all_hpo: dict[str, set[str]],
    idf: dict[str, float],
    syndrome_names: dict[str, str],
    syndrome_cats: dict[str, str],
    top_n: int = 8,
) -> list[dict]:
    """Trouve les syndromes les plus proches par overlap HPO pondéré IDF."""
    if not my_hpo:
        return []
    scores = []
    for other_sid, other_hpo in all_hpo.items():
        if other_sid == sid:
            continue
        overlap = my_hpo & other_hpo
        if len(overlap) < 3:
            continue
        score = sum(idf.get(h, 1.0) for h in overlap)
        jaccard = len(overlap) / len(my_hpo | other_hpo)
        scores.append({
            "id": other_sid,
            "name": syndrome_names.get(other_sid, other_sid),
            "category": syndrome_cats.get(other_sid, ""),
            "overlap": len(overlap),
            "total_mine": len(my_hpo),
            "total_other": len(other_hpo),
            "jaccard": jaccard,
            "idf_score": score,
        })
    scores.sort(key=lambda x: x["idf_score"], reverse=True)
    return scores[:top_n]


def generate_description_md(
    name_fr: str, name_en: str, category: str, inheritance: list[str],
    genes: list[dict], hpo_by_system: dict[str, list], omim: str,
) -> str:
    cat_fr = CATEGORY_FR.get(category, category)
    parts = []

    intro = f"Syndrome {cat_fr}"
    if inheritance:
        intro += f" de transmission {', '.join(inheritance)}"
    intro += "."

    if genes:
        causal = [g for g in genes if g["role"] == "causal"]
        if causal:
            symbols = ", ".join(g["symbol"] for g in causal[:5])
            if len(causal) == 1:
                gene_name = causal[0].get("name", "")
                if gene_name:
                    intro += f" Causé par des mutations du gène {symbols} ({gene_name})."
                else:
                    intro += f" Causé par des mutations du gène {symbols}."
            else:
                intro += f" Gènes causaux : {symbols}."
                if len(causal) > 5:
                    intro += f" ({len(causal)} gènes identifiés au total.)"

    parts.append(intro)

    systems_affected = [s for s in hpo_by_system if s != "Autre" and len(hpo_by_system[s]) > 0]
    if systems_affected:
        atteintes = ", ".join(systems_affected[:6]).lower()
        parts.append(f"Atteinte principale : {atteintes}.")

    if omim:
        parts.append(f"OMIM : {omim}.")

    return " ".join(parts)


def generate_prenatal_summary(hpo_by_system: dict[str, list]) -> str:
    prenatal_relevant = [
        "SNC / Cerveau", "Face / Crâne", "Cœur", "Poumons",
        "Rein / Urinaire", "Squelette / Membres", "Abdomen / Digestif",
        "Croissance / Biométrie", "Liquide amniotique / Placenta",
        "Peau / Tissus mous", "Génital",
    ]
    lines = []
    for system in prenatal_relevant:
        terms = [t for t in hpo_by_system.get(system, [])
                 if t.get("context") != "postnatal"]
        if not terms:
            continue
        terms_sorted = sorted(terms, key=lambda t: -(t.get("prob") or 0))
        items = []
        for t in terms_sorted[:6]:
            label = t["label"]
            freq = t.get("frequency", "")
            if freq:
                short = freq.split("(")[0].strip() if "(" in freq else freq
                items.append(f"{label} [{short}]")
            else:
                items.append(label)
        lines.append(f"- **{system}** : {', '.join(items)}")
    return "\n".join(lines) if lines else "Données prénatales non disponibles."


def generate_discriminators(
    hpo_terms: list[dict], idf: dict[str, float], top_n: int = 6
) -> str:
    if not hpo_terms:
        return "Pas de discriminant identifié."
    scored = []
    for t in hpo_terms:
        spec = idf.get(t["hpo_id"], 1.0)
        prob = t.get("prob") or 0.5
        score = spec * prob
        scored.append((t, score, spec))
    scored.sort(key=lambda x: x[1], reverse=True)

    lines = []
    for t, score, spec in scored[:top_n]:
        label = t["label"]
        freq = t.get("frequency", "")
        specificity = "très spécifique" if spec > 5 else "spécifique" if spec > 3 else "modérément spécifique"
        freq_short = ""
        if freq:
            freq_short = f" ({freq.split('(')[0].strip()})" if "(" in freq else f" ({freq})"
        lines.append(f"- {label}{freq_short} — {specificity}")
    return "\n".join(lines)


def generate_differential(diffs: list[dict]) -> str:
    if not diffs:
        return "Pas de diagnostic différentiel identifié par overlap phénotypique."
    lines = []
    for d in diffs:
        overlap_pct = d["overlap"] / d["total_mine"] * 100 if d["total_mine"] else 0
        cat = CATEGORY_FR.get(d["category"], d["category"])
        lines.append(
            f"- **{d['name']}** ({cat}) — "
            f"{d['overlap']} signes communs ({overlap_pct:.0f}% de chevauchement, "
            f"Jaccard {d['jaccard']:.2f})"
        )
    return "\n".join(lines)


def main():
    db = sqlite3.connect(DB_PATH)
    db.row_factory = sqlite3.Row

    print("Calcul IDF des termes HPO...")
    idf = compute_idf(db)

    print("Chargement des associations HPO...")
    all_syndrome_hpo = get_all_syndrome_hpo(db)

    print("Chargement noms et catégories...")
    name_rows = db.execute("SELECT id, name_fr, category FROM syndromes").fetchall()
    syndrome_names = {r["id"]: r["name_fr"] for r in name_rows}
    syndrome_cats = {r["id"]: r["category"] for r in name_rows}

    syndromes = db.execute("""
        SELECT id, name_fr, name_en, omim, category, inheritance, aliases
        FROM syndromes
        WHERE relevance = 'haute'
          AND (description_md IS NULL OR description_md = '')
        ORDER BY name_fr
    """).fetchall()

    total = len(syndromes)
    print(f"Syndromes haute relevance à enrichir : {total}")

    done = 0
    for i, s in enumerate(syndromes, 1):
        sid = s["id"]

        genes = db.execute("""
            SELECT g.symbol, g.name, sg.role
            FROM syndrome_genes sg
            JOIN genes g ON sg.gene_symbol = g.symbol
            WHERE sg.syndrome_id = ?
            ORDER BY sg.role, g.symbol
        """, (sid,)).fetchall()
        genes = [dict(g) for g in genes]

        hpo_raw = db.execute("""
            SELECT h.hpo_id, h.label_en, h.label_fr, h.context,
                   sh.frequency, sh.prob
            FROM syndrome_hpo sh
            JOIN hpo_terms h ON sh.hpo_id = h.hpo_id
            WHERE sh.syndrome_id = ?
            ORDER BY sh.prob DESC NULLS LAST
        """, (sid,)).fetchall()

        hpo_terms = []
        hpo_by_system = defaultdict(list)
        for h in hpo_raw:
            label = h["label_fr"] if h["label_fr"] else h["label_en"]
            entry = {
                "hpo_id": h["hpo_id"],
                "label": label,
                "label_en": h["label_en"],
                "frequency": h["frequency"],
                "prob": h["prob"],
                "context": h["context"],
            }
            hpo_terms.append(entry)
            system = classify_hpo(h["label_en"] or "")
            hpo_by_system[system].append(entry)

        inheritance = parse_inheritance(s["inheritance"])

        description_md = generate_description_md(
            s["name_fr"], s["name_en"], s["category"],
            inheritance, genes, hpo_by_system, s["omim"],
        )

        prenatal_summary = generate_prenatal_summary(hpo_by_system)

        discriminators = generate_discriminators(hpo_terms, idf)

        my_hpo_set = all_syndrome_hpo.get(sid, set())
        diffs = find_differentials(
            sid, my_hpo_set, all_syndrome_hpo, idf,
            syndrome_names, syndrome_cats,
        )
        differential = generate_differential(diffs)

        db.execute("""
            UPDATE syndromes SET
                description_md = ?,
                prenatal_signs_summary = ?,
                key_discriminators = ?,
                differential_diagnosis = ?,
                updated_at = datetime('now')
            WHERE id = ?
        """, (description_md, prenatal_summary, discriminators, differential, sid))

        if i % 100 == 0:
            db.commit()
            print(f"  [{i}/{total}] {sid} — {s['name_fr']}")

        done += 1

    db.commit()
    db.close()
    print(f"\nTerminé : {done} syndromes enrichis.")


if __name__ == "__main__":
    main()
