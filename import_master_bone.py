#!/usr/bin/env python3
"""Import master bone dysplasia JSON into syndromes_foetaux.db.

Enrichit les entrées existantes (key_discriminators, syndrome_hpo)
et crée les entrées manquantes.
"""

import json
import sqlite3
from pathlib import Path

MASTER_PATH = Path("/home/mathevet/Bureau/FoetoPath_Luminarium/Foeto/Foekinator/akinator_master_Bone_Dysplasias_foet.json")
DB_PATH = Path("/home/mathevet/Bureau/foeto_base/syndromes_foetaux.db")

OMIM_TO_ORPHA = {
    "OMIM:190685": "ORPHA:870",
    "OMIM:300082": "ORPHA:3380",
    "OMIM:163950": "ORPHA:881",
    "OMIM:300083": "ORPHA:3378",
    "OMIM:188400": "ORPHA:567",
    "OMIM:304340": "ORPHA:648",
    "OMIM:173800": "ORPHA:2911",
    "OMIM:108300": "ORPHA:828",
    "OMIM:236100": "ORPHA:2162",
    "OMIM:214800": "ORPHA:138",
    "OMIM:192350": "ORPHA:887",
    "OMIM:100100": "ORPHA:2655",
    "OMIM:262600": "ORPHA:216804",
    "OMIM:270400": "ORPHA:818",
    "OMIM:265000": "ORPHA:994",
    "OMIM:300998": "ORPHA:199",
    "OMIM:187600": "ORPHA:1860",
    "OMIM:100800": "ORPHA:15",
    "OMIM:146000": "ORPHA:429",
    "OMIM:166210": "ORPHA:216804",
    "OMIM:101200": "ORPHA:87",
    "OMIM:101400": "ORPHA:794",
    "OMIM:602849": "ORPHA:53271",
    "OMIM:200610": "ORPHA:93298",
    "OMIM:183900": "ORPHA:94068",
    "OMIM:256100": "ORPHA:564",
    "OMIM:608022": "ORPHA:475",
    "OMIM:607872": "ORPHA:912",
    "OMIM:600725": "ORPHA:87",
    "OMIM:187601": "ORPHA:93274",
    "OMIM:156500": "ORPHA:166038",
    "OMIM:222600": "ORPHA:628",
    "OMIM:208500": "ORPHA:474",
    "OMIM:255500": "ORPHA:289",
    "OMIM:259420": "ORPHA:216812",
    "OMIM:211990": "ORPHA:140",
    "OMIM:119600": "ORPHA:1452",
    "OMIM:101600": "ORPHA:710",
    "OMIM:231670": "ORPHA:446",
    "OMIM:253310": "ORPHA:899",
    "OMIM:210200": "ORPHA:110",
    "OMIM:250250": "ORPHA:175",
    "OMIM:260400": "ORPHA:811",
    "OMIM:607014": "ORPHA:93473",
    "OMIM:156530": "ORPHA:2635",
    "OMIM:150250": "ORPHA:503",
    "OMIM:302960": "ORPHA:35173",
    "OMIM:215100": "ORPHA:177",
    "OMIM:610967": "ORPHA:216820",
    "OMIM:241500": "ORPHA:247623",
    "OMIM:259700": "ORPHA:667",
    "OMIM:180700": "ORPHA:97360",
    "OMIM:277300": "ORPHA:2311",
    "OMIM:156550": "ORPHA:485",
    "OMIM:277610": "ORPHA:2282",
    "OMIM:277180": "ORPHA:672",
    "OMIM:174200": "ORPHA:672",
    "OMIM:253220": "ORPHA:584",
    "OMIM:230500": "ORPHA:79255",
    "OMIM:168400": "ORPHA:2635",
    "OMIM:600972": "ORPHA:93299",
    "OMIM:256050": "ORPHA:56304",
    "OMIM:251450": "ORPHA:1425",
    "OMIM:614078": "ORPHA:263463",
    "OMIM:613091": "ORPHA:1505",
    "OMIM:263520": "ORPHA:1506",
    "OMIM:269860": "ORPHA:1507",
    "OMIM:601559": "ORPHA:3206",
    "OMIM:210720": "ORPHA:2637",
    "OMIM:602535": "ORPHA:561",
    "OMIM:277590": "ORPHA:3447",
    "OMIM:201750": "ORPHA:83",
    "OMIM:201000": "ORPHA:65759",
    "OMIM:602875": "ORPHA:40",
    "OMIM:268300": "ORPHA:3103",
    "OMIM:134780": "ORPHA:1988",
    "OMIM:154400": "ORPHA:245",
    "OMIM:228520": "ORPHA:2019",
    "OMIM:275630": "ORPHA:98907",
    "OMIM:252500": "ORPHA:576",
    "OMIM:616145": "ORPHA:1388",
    "OMIM:304120": "ORPHA:90652",
    "OMIM:308050": "ORPHA:139",
    "OMIM:112240": "ORPHA:2050",
    "OMIM:216340": "ORPHA:3472",
    "OMIM:258315": "ORPHA:93328",
    "OMIM:249700": "ORPHA:2632",
    "OMIM:200700": "ORPHA:2098",
    "OMIM:156400": "ORPHA:33067",
    "OMIM:256550": "ORPHA:87876",
    "OMIM:269920": "ORPHA:834",
    "OMIM:112310": "ORPHA:1263",
    "OMIM:108721": "ORPHA:56305",
    "OMIM:215045": "ORPHA:84064",
    "OMIM:151050": "ORPHA:2658",
    "OMIM:218600": "ORPHA:1225",
    "OMIM:210710": "ORPHA:2636",
    "OMIM:602361": "ORPHA:2763",
    "OMIM:151210": "ORPHA:85166",
}

# Entries to create fresh (no ORPHA in DB)
# LOCAL IDs or OMIM IDs without ORPHA match
NEW_ENTRIES = {
    "OMIM:616482": {
        "name_fr": "Dysplasie SADDAN (FGFR3)",
        "category": "squelettique",
    },
    "LOCAL:OI_IIC": {
        "name_fr": "Ostéogenèse imparfaite type IIC (os dense)",
        "category": "squelettique",
    },
    "LOCAL:RAINE": {
        "name_fr": "Dysplasie de Raine (ostéosclérose létale)",
        "category": "squelettique",
    },
    "OMIM:614592": {
        "name_fr": "Bent bone dysplasia (FGFR2)",
        "category": "squelettique",
    },
    "OMIM:276820": {
        "name_fr": "Syndrome d'Al-Awadi/Raas-Rothschild",
        "category": "squelettique",
    },
    "LOCAL:KOZTSUR": {
        "name_fr": "Hyperostose corticale dysplasique (Kozlowski-Tsuruta)",
        "category": "squelettique",
    },
    "OMIM:215140": {
        "name_fr": "Dysplasie de Greenberg (HEM skeletal dysplasia)",
        "category": "squelettique",
    },
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
    with open(MASTER_PATH) as f:
        master = json.load(f)

    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row

    stats = {"updated_discriminators": 0, "updated_hpo": 0, "inserted_hpo": 0,
             "new_syndromes": 0, "skipped": 0, "new_hpo_terms": 0}

    for disease in master["diseases"]:
        did = disease["disease_id"]
        orpha_id = OMIM_TO_ORPHA.get(did)

        if not orpha_id and did not in NEW_ENTRIES:
            stats["skipped"] += 1
            continue

        if orpha_id:
            row = conn.execute("SELECT id FROM syndromes WHERE id=?", (orpha_id,)).fetchone()
            if not row:
                print(f"  WARN: {orpha_id} not in DB for {disease['disease_name']}")
                stats["skipped"] += 1
                continue
            syndrome_id = orpha_id
        else:
            syndrome_id = did
            info = NEW_ENTRIES[did]
            conn.execute(
                """INSERT OR IGNORE INTO syndromes (id, name_fr, category, omim, relevance)
                   VALUES (?, ?, ?, ?, ?)""",
                (did, info["name_fr"], info["category"],
                 did.replace("OMIM:", "") if did.startswith("OMIM:") else None,
                 "high"),
            )
            stats["new_syndromes"] += 1

        notes_parts = []
        for pheno in disease["phenotypes"]:
            hpo_id = pheno["hpo_id"]
            penetrance = pheno["penetrance"]
            source = pheno.get("source", "master_bone")
            note = pheno.get("notes", "")

            if note:
                notes_parts.append(f"{pheno['hpo_name_fr']}: {note} (p={penetrance})")

            existing_hpo = conn.execute(
                "SELECT hpo_id FROM hpo_terms WHERE hpo_id=?", (hpo_id,)
            ).fetchone()
            if not existing_hpo:
                conn.execute(
                    "INSERT INTO hpo_terms (hpo_id, label_fr, label_en, context) VALUES (?, ?, ?, ?)",
                    (hpo_id, pheno["hpo_name_fr"], pheno["hpo_name_fr"], "both"),
                )
                stats["new_hpo_terms"] += 1

            existing_link = conn.execute(
                "SELECT prob FROM syndrome_hpo WHERE syndrome_id=? AND hpo_id=?",
                (syndrome_id, hpo_id),
            ).fetchone()

            if existing_link:
                if penetrance > (existing_link["prob"] or 0):
                    conn.execute(
                        "UPDATE syndrome_hpo SET prob=?, frequency=?, source=? WHERE syndrome_id=? AND hpo_id=?",
                        (penetrance, freq_label(penetrance), f"master_bone/{source}",
                         syndrome_id, hpo_id),
                    )
                    stats["updated_hpo"] += 1
            else:
                conn.execute(
                    "INSERT INTO syndrome_hpo (syndrome_id, hpo_id, prob, frequency, source) VALUES (?, ?, ?, ?, ?)",
                    (syndrome_id, hpo_id, penetrance, freq_label(penetrance),
                     f"master_bone/{source}"),
                )
                stats["inserted_hpo"] += 1

        if notes_parts:
            discriminators = "; ".join(notes_parts)
            existing_disc = conn.execute(
                "SELECT key_discriminators FROM syndromes WHERE id=?", (syndrome_id,)
            ).fetchone()
            old = existing_disc["key_discriminators"] or ""
            if old:
                new_disc = old + " | MASTER_BONE: " + discriminators
            else:
                new_disc = discriminators
            conn.execute(
                "UPDATE syndromes SET key_discriminators=?, updated_at=datetime('now') WHERE id=?",
                (new_disc, syndrome_id),
            )
            stats["updated_discriminators"] += 1

    conn.commit()
    conn.close()

    print(f"\n=== Import master bone dysplasia terminé ===")
    for k, v in stats.items():
        print(f"  {k}: {v}")


if __name__ == "__main__":
    main()
