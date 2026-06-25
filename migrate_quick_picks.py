#!/usr/bin/env python3
"""Migration : créer les termes SLIDE_TAGS manquants + set viewer_quick=1 sur level 0."""
import sqlite3

DB = "/home/mathevet/Bureau/foeto_base/syndromes_foetaux.db"

# Termes SLIDE_TAGS manquants dans foeto_terms
NEW_TERMS = [
    # (id, label_fr, organe, viewer_level, viewer_id, axis, cr_description)
    ("FOETO:0100390", "Drépanocytose placentaire", "parenchyme", 0, "drepano",
     "pathologie", "On note des signes de drépanocytose placentaire (falciformation érythrocytaire intervilleuse)."),
    ("FOETO:0100391", "Fibrine périvillositaire augmentée", "parenchyme", 0, "fib_pv_augmentee",
     "pathologie", "On note une augmentation diffuse de la fibrine périvillositaire."),
    ("FOETO:0100392", "Calcifications", "parenchyme", 0, "calcifs",
     "pathologie", "On note une augmentation diffuse du nombre de calcifications."),
    ("FOETO:0100393", "Hémorragie intervilleuse", "parenchyme", 0, "hiv",
     "pathologie", "On note une hémorragie intervilleuse."),
    ("FOETO:0100394", "FIR Stage 3 — Funiculite concentrique", "cordon", 0, "fir_s3",
     "pathologie", "On note la présence d'une inflammation polynucléaire neutrophile des 3 vaisseaux ombilicaux (FIR stage 3)."),
    ("FOETO:0100395", "Maturation villositaire accélérée", "parenchyme", 0, "amv",
     "pathologie", "On note de multiples plages d'accélération de la maturation villositaire (AMV)."),
    ("FOETO:0100396", "ANSCT augmentés", "parenchyme", 0, "ansct",
     "pathologie", "On note une augmentation diffuse du nombre d'amas nucléaires syncytiotrophoblastiques (ANSCT)."),
]

# Termes level 1 qui doivent aussi être quick-pickable
PROMOTE_QUICK = [
    "necrose_laminaire_membranes",
    "chorangiomatose",
]


def main():
    conn = sqlite3.connect(DB)

    # 1. Insert missing terms
    for fid, label, organe, vlevel, vid, axis, cr_desc in NEW_TERMS:
        cur = conn.execute("SELECT 1 FROM foeto_terms WHERE id=?", (fid,))
        if cur.fetchone():
            print(f"  EXISTS {vid}")
            continue
        conn.execute(
            "INSERT INTO foeto_terms (id, label_fr, organe, domain, viewer_level, viewer_id, "
            "viewer_quick, axis, annotation_type, cr_description) "
            "VALUES (?, ?, ?, 'placenta', ?, ?, 1, ?, 'exam', ?)",
            (fid, label, organe, vlevel, vid, axis, cr_desc),
        )
        print(f"  CREATED {vid} ({organe})")

    # 2. Set viewer_quick=1 on ALL level 0 placenta terms (non-retention)
    cur = conn.execute(
        "UPDATE foeto_terms SET viewer_quick = 1 "
        "WHERE domain = 'placenta' AND viewer_level = 0 AND viewer_quick != 1 "
        "AND viewer_id NOT LIKE '%_ret' AND viewer_id NOT LIKE 'FOETO:%_ret'"
    )
    print(f"\nLevel 0 promoted to quick: {cur.rowcount}")

    # 3. Promote specific level 1 terms
    for vid in PROMOTE_QUICK:
        cur = conn.execute(
            "UPDATE foeto_terms SET viewer_quick = 1 WHERE viewer_id = ? AND viewer_quick != 1",
            (vid,),
        )
        if cur.rowcount:
            print(f"  QUICK {vid}")

    # 4. Summary
    print("\n── Quick picks par organe ──")
    for row in conn.execute(
        "SELECT organe, COUNT(*) FROM foeto_terms "
        "WHERE domain='placenta' AND viewer_quick=1 "
        "GROUP BY organe ORDER BY organe"
    ):
        print(f"  {row[0]:15s} {row[1]}")

    print("\n── Détail ──")
    for row in conn.execute(
        "SELECT organe, viewer_id, label_fr FROM foeto_terms "
        "WHERE domain='placenta' AND viewer_quick=1 "
        "ORDER BY organe, viewer_id"
    ):
        print(f"  [{row[0]:12s}] {row[1]:30s} {row[2]}")

    conn.commit()
    conn.close()
    print("\nDone.")


if __name__ == "__main__":
    main()
