#!/usr/bin/env python3
"""Enrichissement hydrops fœtal non immun dans syndromes_foetaux.db.

Le modèle force un syndrome spécifique quand le cas est un hydrops
sans étiologie identifiable. On enrichit :
1. L'entrée principale ORPHA:363999 avec classification étiologique + arbre décisionnel
2. Les syndromes causant fréquemment un hydrops avec discriminateurs "QUAND PENSER HYDROPS"
3. Ajout de syndromes manquants (chorioangiome, TTTS)
"""

import sqlite3
import shutil
from pathlib import Path

DB_PATH = Path("/home/mathevet/Bureau/foeto_base/syndromes_foetaux.db")

# ORPHA:363999 — enrichissement majeur de l'entrée principale
HYDROPS_MAIN_ALIASES = (
    "hydrops fetalis, hydrops fœtal, anasarque fœtale, "
    "anasarque foeto-placentaire, hydrops non immun, HFNI, "
    "hydrops non immunologique, anasarque fœtoplacentaire non immune"
)

HYDROPS_MAIN_DISCRIMINATORS = (
    "HYDROPS FŒTAL NON IMMUN — Classification étiologique par fréquence: "
    "CARDIOVASCULAIRE (20-30%): cardiopathies structurelles complexes, "
    "tachyarythmie supraventriculaire, tumeurs cardiaques (rhabdomyome, "
    "tératome péricardique), cardiomyopathie, fermeture prématurée canal artériel. "
    "CHROMOSOMIQUE (15%): Turner 45,X (50% des hydrops chromosomiques), "
    "trisomies 21/18/13, triploïdie. "
    "ANÉMIE (10%): alpha-thalassémie majeure (Hb Bart's), parvovirus B19, "
    "hémorragie fœto-maternelle, allo-immunisation Kell. "
    "LYMPHATIQUE (5-10%): malformation lymphatique primitive, "
    "Noonan (RASopathie), hygroma kystique. "
    "MÉTABOLIQUE (2-5%): Gaucher périnatal, MPS VII (Sly), galactosialidose, "
    "Niemann-Pick type A/C, I-cell disease. "
    "INFECTIEUX (5-10%): parvovirus B19 (anémie), CMV, toxoplasmose, syphilis congénitale. "
    "THORACIQUE: CPAM/MAC, hernie diaphragmatique, épanchement pleural. "
    "PLACENTAIRE: chorioangiome, syndrome transfuseur-transfusé (jumeaux), "
    "thrombose veine ombilicale. "
    "IDIOPATHIQUE (15-30%): diagnostic d'exclusion après bilan complet. "
    "DIAGNOSTIC DESCRIPTIF ACCEPTABLE: Quand le bilan étiologique complet "
    "(échographie morpho, caryotype/CGH, bilan infectieux TORCH, "
    "test de Kleihauer, bilan métabolique, Doppler) est négatif, "
    "le diagnostic 'hydrops fœtal non immun idiopathique' est LÉGITIME "
    "et PRÉFÉRABLE à forcer un syndrome. "
    "ARBRE DÉCISIONNEL: "
    "Hydrops + cardiopathie structurelle → étiologie cardiovasculaire. "
    "Hydrops + hygroma kystique + fille → Turner (caryotype). "
    "Hydrops + hygroma kystique + garçon ou caryotype normal → Noonan (gènes RAS). "
    "Hydrops + anémie fœtale (Doppler ACM pic systolique élevé) → Bart's / parvovirus / hémorragie. "
    "Hydrops + hépatomégalie + splénomégalie → métabolique (Gaucher, NPA, MPS VII). "
    "Hydrops + calcifications cérébrales + RCIU → infectieux (CMV, toxoplasmose). "
    "Hydrops + masse placentaire → chorioangiome. "
    "Hydrops + jumeaux monochoriaux → TTTS. "
    "Hydrops isolé sans orientation → bilan exhaustif puis idiopathique."
)

# Discriminateurs "QUAND PENSER HYDROPS" pour syndromes existants
DISCRIMINATORS = {
    "ORPHA:881": (
        "HYDROPS: Turner = cause chromosomique #1 d'hydrops fœtal. "
        "Hygroma kystique cervical bilatéral + hydrops + fille = 45,X. "
        "Peut se résoudre spontanément in utero (Turner viable) "
        "ou évoluer vers mort fœtale. Caryotype en urgence. "
        "QUAND PENSER TURNER: hydrops + hygroma + FILLE. "
        "Si GARÇON ou caryotype normal → penser Noonan."
    ),
    "ORPHA:648": (
        "HYDROPS: Noonan = cause lymphatique/génétique d'hydrops. "
        "Hygroma kystique + hydrops + caryotype NORMAL = penser Noonan (RASopathie). "
        "Surtout si cardiopathie associée (sténose pulmonaire). "
        "QUAND PENSER NOONAN: hydrops + hygroma + caryotype normal + cardiopathie."
    ),
    "ORPHA:85212": (
        "HYDROPS: Gaucher périnatal = cause métabolique classique d'hydrops sévère. "
        "Hépatosplénomégalie MASSIVE + hydrops + ichtyose/collodion baby = "
        "Gaucher type 2 périnatal létal. Activité glucocérébrosidase effondrée. "
        "QUAND PENSER GAUCHER: hydrops + hépato-splénomégalie + ichtyose/collodion."
    ),
    "ORPHA:584": (
        "HYDROPS: MPS VII (Sly) = cause métabolique d'hydrops avec dysmorphie. "
        "Hydrops + faciès grossier/épaissi + dysostose multiplex = penser MPS VII. "
        "Activité β-glucuronidase urinaire/leucocytaire. "
        "QUAND PENSER MPS VII: hydrops + faciès épaissi + anomalies squelettiques."
    ),
    "ORPHA:163596": (
        "ALPHA-THALASSÉMIE MAJEURE (Hb Bart's): Hydrops sévère précoce "
        "(2ème trimestre) + anémie fœtale SÉVÈRE (Doppler ACM: pic systolique "
        "très élevé) + hépatomégalie + placentomégalie. "
        "Délétion homozygote des 4 gènes alpha-globine (--/--). "
        "PATHOGNOMONIQUE: électrophorèse Hb = Hb Bart's (γ4) quasi-exclusive. "
        "Fréquent en Asie du Sud-Est, bassin méditerranéen. LÉTAL sans transfusion in utero. "
        "DISCRIMINANT vs parvovirus: Bart's = anémie CHRONIQUE dès T2 + "
        "PAS de séroconversion IgM parvovirus. Parvovirus = anémie AIGUË + séroconversion."
    ),
}

# Nouveaux syndromes à ajouter
NEW_SYNDROMES = {
    "ORPHA:99927": {
        "name_fr": "Chorioangiome placentaire géant",
        "name_en": "Giant placental chorioangioma",
        "omim": "",
        "category": "placentaire",
        "relevance": "haute",
        "key_discriminators": (
            "CHORIOANGIOME PLACENTAIRE GÉANT (>5 cm): Tumeur vasculaire bénigne "
            "du placenta. Hydrops par insuffisance cardiaque à haut débit "
            "(shunt artério-veineux dans la tumeur). "
            "Échographie: masse placentaire arrondie bien limitée "
            "hyperéchogène/hétérogène à la face FŒTALE du placenta. "
            "Polyhydramnios + hydrops + anémie fœtale. "
            "DISCRIMINANT: masse PLACENTAIRE + hydrops = chorioangiome. "
            "PAS de masse fœtale (vs tératome sacrococcygien). "
            "Traitement: embolisation / coagulation laser des vaisseaux nourriciers."
        ),
    },
    "ORPHA:77269": {
        "name_fr": "Syndrome transfuseur-transfusé (TTTS)",
        "name_en": "Twin-to-twin transfusion syndrome",
        "omim": "",
        "category": "placentaire",
        "relevance": "haute",
        "key_discriminators": (
            "SYNDROME TRANSFUSEUR-TRANSFUSÉ (TTTS): UNIQUEMENT grossesse gémellaire "
            "monochoriale biamniotique. Déséquilibre hémodynamique par anastomoses "
            "placentaires artério-veineuses. "
            "RECEVEUR: polyhydramnios + hydrops + cardiomégalie + macrosomie + "
            "vessie distendue. "
            "DONNEUR: oligoamnios sévère (stuck twin) + RCIU + anémie + "
            "vessie non visible. "
            "Classification Quintero: I (discordance LA) → II (vessie donneur non visible) "
            "→ III (Doppler anormal) → IV (hydrops) → V (mort d'un jumeau). "
            "DISCRIMINANT: grossesse gémellaire monochoriale + discordance volume "
            "amniotique = TTTS jusqu'à preuve du contraire. "
            "Traitement: photocoagulation laser des anastomoses (stade ≥II)."
        ),
    },
}

SYNDROME_HPO: dict[str, list[tuple[str, str, str, float]]] = {
    "ORPHA:99927": [
        ("HP:0001789", "Hydrops fetalis", "Anasarque foetal", 0.70),
        ("HP:0001561", "Polyhydramnios", "Hydramnios", 0.80),
        ("HP:0001903", "Anemia", "Anémie", 0.60),
        ("HP:0011904", "Placentomegaly", "Placentomégalie", 0.90),
        ("HP:0001635", "Congestive heart failure", "Insuffisance cardiaque", 0.50),
    ],
    "ORPHA:77269": [
        ("HP:0001789", "Hydrops fetalis", "Anasarque foetal", 0.50),
        ("HP:0001561", "Polyhydramnios", "Hydramnios", 0.90),
        ("HP:0001562", "Oligohydramnios", "Oligoamnios", 0.90),
        ("HP:0001511", "Intrauterine growth retardation", "Retard de croissance intra-utérin", 0.70),
        ("HP:0001635", "Congestive heart failure", "Insuffisance cardiaque", 0.40),
    ],
}


def freq_label(penetrance: float) -> str:
    if penetrance >= 0.80:
        return "Very frequent (99-80%)"
    elif penetrance >= 0.30:
        return "Frequent (79-30%)"
    elif penetrance >= 0.05:
        return "Occasional (29-5%)"
    else:
        return "Very rare (<4-1%)"


def main():
    shutil.copy(DB_PATH, str(DB_PATH) + ".bak_pre_hydrops_import")
    print(f"Backup: {DB_PATH}.bak_pre_hydrops_import")

    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row

    stats = {
        "discriminators_updated": 0,
        "new_syndromes": 0,
        "hpo_inserted": 0,
        "hydrops_main_enriched": False,
    }

    # --- 1. Enrichir l'entrée principale ORPHA:363999 ---
    main_row = conn.execute(
        "SELECT id, aliases, key_discriminators FROM syndromes WHERE id='ORPHA:363999'"
    ).fetchone()
    if main_row:
        old_aliases = main_row["aliases"] or ""
        if "HFNI" not in old_aliases:
            if old_aliases:
                new_aliases = old_aliases + ", " + HYDROPS_MAIN_ALIASES
            else:
                new_aliases = HYDROPS_MAIN_ALIASES
            conn.execute(
                "UPDATE syndromes SET aliases=? WHERE id='ORPHA:363999'",
                (new_aliases,),
            )
            print(f"  ALIASES: ORPHA:363999 — aliases enrichis")

        old_disc = main_row["key_discriminators"] or ""
        if "ARBRE DÉCISIONNEL" not in old_disc:
            conn.execute(
                "UPDATE syndromes SET key_discriminators=?, updated_at=datetime('now') WHERE id='ORPHA:363999'",
                (HYDROPS_MAIN_DISCRIMINATORS,),
            )
            stats["hydrops_main_enriched"] = True
            print(f"  DISC MAIN: ORPHA:363999 — classification étiologique + arbre décisionnel")
    else:
        print(f"  WARN: ORPHA:363999 not found!")

    # --- 2. Discriminateurs "QUAND PENSER HYDROPS" ---
    for sid, disc_text in DISCRIMINATORS.items():
        row = conn.execute(
            "SELECT id, name_fr, key_discriminators FROM syndromes WHERE id=?", (sid,)
        ).fetchone()
        if not row:
            print(f"  WARN: {sid} not in DB, skipping")
            continue

        old = row["key_discriminators"] or ""
        if "HYDROPS:" in old or "ALPHA-THALASSEMIE" in old.replace("É", "E"):
            print(f"  SKIP disc: {sid} ({row['name_fr']}) — already enriched")
            continue

        if old:
            new_disc = old + " | HYDROPS: " + disc_text
        else:
            new_disc = disc_text

        conn.execute(
            "UPDATE syndromes SET key_discriminators=?, updated_at=datetime('now') WHERE id=?",
            (new_disc, sid),
        )
        stats["discriminators_updated"] += 1
        print(f"  DISC: {sid} ({row['name_fr']})")

    # --- 3. Nouveaux syndromes ---
    for sid, data in NEW_SYNDROMES.items():
        existing = conn.execute("SELECT id FROM syndromes WHERE id=?", (sid,)).fetchone()
        if existing:
            print(f"  SKIP new: {sid} already exists")
            continue
        conn.execute(
            """INSERT INTO syndromes
               (id, name_fr, name_en, omim, category, relevance,
                key_discriminators, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, datetime('now'), datetime('now'))""",
            (
                sid, data["name_fr"], data.get("name_en", ""),
                data.get("omim", ""), data["category"],
                data["relevance"], data["key_discriminators"],
            ),
        )
        stats["new_syndromes"] += 1
        print(f"  NEW: {sid} ({data['name_fr']})")

    # --- 4. HPO links ---
    for sid, hpo_list in SYNDROME_HPO.items():
        for hpo_id, label_en, label_fr, penetrance in hpo_list:
            existing_hpo = conn.execute(
                "SELECT hpo_id FROM hpo_terms WHERE hpo_id=?", (hpo_id,)
            ).fetchone()
            if not existing_hpo:
                conn.execute(
                    "INSERT INTO hpo_terms (hpo_id, label_en, label_fr) VALUES (?, ?, ?)",
                    (hpo_id, label_en, label_fr),
                )

            existing_link = conn.execute(
                "SELECT syndrome_id FROM syndrome_hpo WHERE syndrome_id=? AND hpo_id=?",
                (sid, hpo_id),
            ).fetchone()
            if existing_link:
                continue

            conn.execute(
                """INSERT INTO syndrome_hpo (syndrome_id, hpo_id, frequency, prob, source)
                   VALUES (?, ?, ?, ?, 'master_hydrops')""",
                (sid, hpo_id, freq_label(penetrance), penetrance),
            )
            stats["hpo_inserted"] += 1

    conn.commit()
    conn.close()

    print(f"\n=== Import master hydrops terminé ===")
    for k, v in stats.items():
        print(f"  {k}: {v}")


if __name__ == "__main__":
    main()
