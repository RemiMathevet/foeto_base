#!/usr/bin/env python3
"""Enrichissement syndromes RASopathies de syndromes_foetaux.db.

Les cas rasopathies du benchmark v2 scorent 71% — le modèle confond
les sous-types au sein de la voie RAS/MAPK (Noonan vs CFC vs Costello).
Enrichit les discriminateurs cliniques pour chaque rasopathie.
"""

import sqlite3
import shutil
from pathlib import Path

DB_PATH = Path("/home/mathevet/Bureau/foeto_base/syndromes_foetaux.db")

DISCRIMINATORS = {
    "ORPHA:648": (
        "NOONAN (PTPN11/SOS1/RAF1/KRAS): RASopathie la plus fréquente (1/2000). "
        "Dysmorphie faciale (hypertélorisme, ptosis, oreilles basses rotées postérieurement, "
        "cou court avec pterygium colli), sténose pulmonaire VALVULAIRE (75%), "
        "cryptorchidie, petite taille proportionnée, pectus excavatum/carinatum, "
        "coagulopathie (facteur XI, thrombopénie). "
        "EN PRÉNATAL: hygroma kystique + cardiopathie + polyhydramnios = triade Noonan. "
        "DISCRIMINANT vs Turner: Noonan = caryotype NORMAL, les DEUX sexes. "
        "Turner = 45,X FÉMININ uniquement. "
        "DISCRIMINANT vs CFC: Noonan = retard intellectuel LÉGER ou ABSENT, "
        "PAS d'ichtyose, PAS d'anomalie des cheveux. "
        "CFC = retard SÉVÈRE + anomalies ectodermiques constantes. "
        "DISCRIMINANT vs Costello: Noonan = PAS de papillomes, "
        "PAS de peau lâche redundante. Costello = papillomes périorificiels. "
        "DISCRIMINANT vs LEOPARD: Noonan = PAS de lentigines. "
        "LEOPARD = lentigines multiples diffuses."
    ),
    "ORPHA:1340": (
        "CFC / CARDIO-FACIO-CUTANÉ (BRAF 75%/MEK1/MEK2/KRAS): "
        "Retard psychomoteur SÉVÈRE (vs léger dans Noonan), anomalies ectodermiques "
        "MAJEURES et CONSTANTES: cheveux crépus/clairsemés/absents (95%), "
        "ichtyose/kératose folliculaire (90%), sourcils clairsemés ou absents. "
        "Cardiopathie (sténose pulmonaire + CMH). "
        "PAS de lentigines (vs LEOPARD), PAS de papillomes (vs Costello). "
        "DISCRIMINANT vs Costello: CFC = ichtyose + cheveux CLAIRSEMÉS. "
        "Costello = peau LÂCHE redundante + papillomes + cheveux BOUCLÉS épais. "
        "DISCRIMINANT vs Noonan: CFC = retard TOUJOURS sévère + "
        "anomalies cutanées constantes (ichtyose). Noonan = retard variable, peau normale."
    ),
    "ORPHA:3071": (
        "COSTELLO (HRAS quasi-100%): Papillomes périorificiels "
        "(PATHOGNOMONIQUE — apparaissent vers 2-4 ans, nez, bouche, anus), "
        "peau lâche et redundante (surtout mains/pieds — plis palmaires profonds), "
        "macrocéphalie relative, cardiomyopathie hypertrophique (60%), "
        "cheveux bouclés et épais, risque TUMORAL élevé "
        "(rhabdomyosarcome 15%, neuroblastome, carcinome vésical). "
        "EN NÉONATAL: macrosomie + polyhydramnios + peau lâche. "
        "DISCRIMINANT: papillomes périorificiels = Costello. "
        "Aucune autre rasopathie n'a ce signe. "
        "DISCRIMINANT vs CFC: peau LÂCHE (pas ichtyosique), "
        "cheveux BOUCLÉS épais (pas clairsemés). "
        "QUAND PENSER TUMORAL: rasopathie + masse = Costello en priorité."
    ),
    "ORPHA:500": (
        "LEOPARD / NOONAN AVEC LENTIGINES (PTPN11 85%/RAF1/BRAF): "
        "Lentigines multiples diffuses (PATHOGNOMONIQUE — apparition enfance, "
        "augmentent avec l'âge, milliers de lésions à l'âge adulte). "
        "Surdité neurosensorielle (25%), cardiomyopathie hypertrophique "
        "(CMH > sténose pulmonaire, inversé par rapport à Noonan classique), "
        "anomalies ECG constantes, retard de croissance modéré. "
        "DISCRIMINANT: lentigines multiples diffuses = LEOPARD. "
        "Noonan classique = PAS de lentigines. "
        "DISCRIMINANT vs NF1: LEOPARD = lentigines DIFFUSES petites + CMH. "
        "NF1 = taches café au lait GRANDES (>5mm enfant) + neurofibromes."
    ),
    "ORPHA:636": (
        "NEUROFIBROMATOSE TYPE 1 (NF1): Critères diagnostiques: "
        "≥6 taches café au lait (>5mm prépubère, >15mm postpubère), "
        "≥2 neurofibromes cutanés OU 1 plexiforme, lentigines axillaires/inguinales "
        "(signe de Crowe), gliome des voies optiques, ≥2 nodules de Lisch (iris), "
        "dysplasie sphénoïde, pseudarthrose tibiale. "
        "EN PRÉNATAL: rarement détectable, pas de signe échographique spécifique. "
        "DISCRIMINANT vs Legius: NF1 = neurofibromes + Lisch + gliome optique. "
        "Legius = taches café au lait ISOLÉES sans neurofibromes, sans Lisch, sans tumeurs. "
        "DISCRIMINANT vs LEOPARD: NF1 = taches café au lait GRANDES (bords nets, "
        "coast-of-Maine). LEOPARD = lentigines PETITES diffuses (1-5mm)."
    ),
    "ORPHA:137605": (
        "LEGIUS (SPRED1): Taches café au lait + macrocéphalie + "
        "dysmorphie noonan-like (hypertélorisme, pectus). "
        "ABSENCE TOTALE de neurofibromes, ABSENCE de nodules de Lisch, "
        "ABSENCE de gliome optique, ABSENCE de tumeurs. "
        "Retard cognitif léger ou absent. "
        "DISCRIMINANT vs NF1: Legius = café au lait + faciès Noonan "
        "SANS neurofibromes ni Lisch ni tumeurs. "
        "Gène SPRED1 (voie RAS, en aval de NF1). "
        "QUAND Y PENSER: enfant avec taches café au lait typiques NF1 "
        "mais sans neurofibromes après puberté = tester SPRED1."
    ),
    "ORPHA:2701": (
        "NOONAN-LIKE AVEC CHEVEUX ANAGÈNES CADUCS (SHOC2 p.Ser2Gly): "
        "Phénotype Noonan + cheveux anagènes caducs (cheveux clairsemés, "
        "fins, cassants, croissance lente — pathognomonique de la mutation SHOC2). "
        "Peau foncée/hyperpigmentée, voix rauque, "
        "cardiopathie (sténose pulmonaire, défaut septal), "
        "retard de croissance, macrocéphalie relative. "
        "DISCRIMINANT vs Noonan classique: cheveux anagènes caducs + "
        "peau foncée = SHOC2. Noonan classique = cheveux NORMAUX. "
        "DISCRIMINANT vs CFC: CFC = cheveux clairsemés + ichtyose. "
        "SHOC2 = cheveux clairsemés + peau FONCÉE (pas ichtyosique)."
    ),
}

NEW_SYNDROMES: dict = {}

SYNDROME_HPO: dict[str, list[tuple[str, str, str, float]]] = {}


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
    shutil.copy(DB_PATH, str(DB_PATH) + ".bak_pre_rasopathies_import")
    print(f"Backup: {DB_PATH}.bak_pre_rasopathies_import")

    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row

    stats = {"discriminators_updated": 0, "new_syndromes": 0, "hpo_inserted": 0}

    for sid, disc_text in DISCRIMINATORS.items():
        row = conn.execute(
            "SELECT id, name_fr, key_discriminators FROM syndromes WHERE id=?", (sid,)
        ).fetchone()
        if not row:
            print(f"  WARN: {sid} not in DB, skipping")
            continue

        old = row["key_discriminators"] or ""
        if "RASOPATHIE" in old or "PATHOGNOMONIQUE" in old:
            print(f"  SKIP disc: {sid} ({row['name_fr']}) — already enriched")
            continue

        if old:
            new_disc = old + " | RASOPATHIE: " + disc_text
        else:
            new_disc = disc_text

        conn.execute(
            "UPDATE syndromes SET key_discriminators=?, updated_at=datetime('now') WHERE id=?",
            (new_disc, sid),
        )
        stats["discriminators_updated"] += 1
        print(f"  DISC: {sid} ({row['name_fr']})")

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
                data.get("omim", ""), data.get("category", "rasopathie"),
                data.get("relevance", "haute"), data.get("key_discriminators", ""),
            ),
        )
        stats["new_syndromes"] += 1
        print(f"  NEW: {sid} ({data['name_fr']})")

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
                   VALUES (?, ?, ?, ?, 'master_rasopathies')""",
                (sid, hpo_id, freq_label(penetrance), penetrance),
            )
            stats["hpo_inserted"] += 1

    conn.commit()
    conn.close()

    print(f"\n=== Import master rasopathies terminé ===")
    for k, v in stats.items():
        print(f"  {k}: {v}")


if __name__ == "__main__":
    main()
