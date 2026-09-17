#!/usr/bin/env python3
"""Range les embryofœtopathies non génétiques dans leur catégorie, au lieu de
« malformatif » où Orphanet les noie parmi 1 900 entrées.

    python3 categoriser_embryofoetopathies.py            # applique
    python3 categoriser_embryofoetopathies.py --dry-run  # montre

Trois catégories, dans syndromes.category :
  teratogene   médicament, toxique ou maladie maternelle (alcool, valproate,
               AVK, diabète, PCU, hyperthermie…)
  infectieux   infection congénitale (CMV, toxoplasmose, rubéole, syphilis…) —
               la catégorie existait déjà, on y ajoute ce qui manquait
  sequence     mécanique ou vasculaire, sans cause génique propre (brides
               amniotiques, disruption cérébrale ; les séquences gémellaires
               restent dans les catégories placentaires)

La liste est explicite (ORPHA → catégorie) : pas de regex sur les noms, pour
ne pas ranger « Silver-Russell par disomie maternelle » avec les tératogènes.
Idempotent ; sauvegarde de la base avant écriture.
"""
import argparse
import shutil
import sqlite3
import datetime as dt
from pathlib import Path

DB = Path(__file__).resolve().parent / "syndromes_foetaux.db"

CATEGORIES = {
    "teratogene": [
        "ORPHA:1915",    # Fetal alcohol syndrome
        "ORPHA:1926",    # Diabetic embryopathy
        "ORPHA:2209",    # Maternal phenylketonuria syndrome
        "ORPHA:1920",    # Toluene embryopathy
        "ORPHA:1919",    # Phenobarbital embryopathy
        "ORPHA:1917",    # Fetal methylmercury syndrome
        "ORPHA:1923",    # Methimazole embryofetopathy
        "ORPHA:485358",  # Propylthiouracil embryofetopathy
        "ORPHA:226313",  # Congenital hypothyroidism due to maternal intake of antithyroid drugs
        "ORPHA:1912",    # Fetal hydantoin syndrome
        "ORPHA:370076",  # Fetal carbamazepine syndrome
        "ORPHA:1913",    # Fetal trimethadione syndrome
        "ORPHA:1906",    # Fetal valproate spectrum disorder
        "ORPHA:1918",    # Fetal minoxidil syndrome
        "ORPHA:1911",    # Cocaine embryofetopathy
        "ORPHA:1910",    # Fetal iodine syndrome
        "ORPHA:1914",    # Vitamin K antagonist embryofetopathy
        "ORPHA:1908",    # Aminopterin/methotrexate embryofetopathy
        "ORPHA:1909",    # Indomethacin embryofetopathy
        "ORPHA:268249",  # Mycophenolate mofetil embryopathy
        "ORPHA:3312",    # Thalidomide embryopathy
        "ORPHA:2305",    # Isotretinoin syndrome
        "ORPHA:2306",    # Isotretinoin-like syndrome
        "ORPHA:40366",   # Acitretin/etretinate embryopathy
        "ORPHA:2216",    # Maternal hyperthermia-induced birth defects
        "ORPHA:398124",  # Neonatal lupus erythematosus (anticorps maternels)
    ],
    "infectieux": [
        "ORPHA:294",     # Fetal cytomegalovirus syndrome
        "ORPHA:858",     # Congenital toxoplasmosis
        "ORPHA:290",     # Congenital rubella syndrome
        "ORPHA:291",     # Congenital varicella syndrome
        "ORPHA:295",     # Fetal parvovirus syndrome
        "ORPHA:499009",  # Congenital syphilis
        "ORPHA:293",     # Congenital herpes simplex virus infection
    ],
    "sequence": [
        "ORPHA:295000",  # Amniotic band syndrome
        "ORPHA:1665",    # Sporadic fetal brain disruption sequence
        # TTTS, TAPS, TRAP restent dans les catégories placentaires curées
        # (placentaire / vasculaire_placentaire) : c'est là qu'on les cherche.
    ],
}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    cx = sqlite3.connect(DB)
    changements = []
    for cat, ids in CATEGORIES.items():
        for sid in ids:
            r = cx.execute("SELECT name_en, category FROM syndromes WHERE id=?", (sid,)).fetchone()
            if not r:
                print(f"  ? {sid} absent de la base")
                continue
            if r[1] != cat:
                changements.append((sid, r[0], r[1], cat))
    for sid, nom, avant, apres in changements:
        print(f"  {sid:14} {nom[:50]:50} {avant or '—':22} → {apres}")
    if not changements:
        print("rien à changer.")
        return
    if a.dry_run:
        print(f"{len(changements)} changement(s) — simulation.")
        return
    sauvegarde = DB.with_name(f"syndromes_foetaux.db.bak-{dt.datetime.now():%Y%m%d-%H%M}")
    shutil.copy2(DB, sauvegarde)
    cx.executemany("UPDATE syndromes SET category=?, updated_at=datetime('now') WHERE id=?",
                   [(apres, sid) for sid, _, _, apres in changements])
    cx.commit()
    print(f"{len(changements)} changement(s) appliqué(s) — sauvegarde {sauvegarde.name}")
    for cat in CATEGORIES:
        n = cx.execute("SELECT COUNT(*) FROM syndromes WHERE category=?", (cat,)).fetchone()[0]
        print(f"  {cat}: {n}")


if __name__ == "__main__":
    main()
