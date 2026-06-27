#!/usr/bin/env python3
"""Migration : type_patho + sous_type_patho propagés depuis les chapitres sources."""
import sqlite3

DB = "/home/mathevet/Bureau/foeto_base/syndromes_foetaux.db"

# chapitre_pattern → (type_patho, sous_type_patho)
# Plus spécifique en premier — premier match gagne
CHAPTER_TYPES = [
    # ── Histo normale ──
    ("ernst_ch01_heart", ("histo normale", None)),
    ("ernst_ch03_lung", ("histo normale", None)),
    ("ernst_ch04_gi", ("histo normale", None)),
    ("ernst_ch05_liver", ("histo normale", None)),
    ("ernst_ch06_pancreas", ("histo normale", None)),
    ("ernst_ch07_salivary", ("histo normale", None)),
    ("ernst_ch08_kidney", ("histo normale", None)),
    ("ernst_ch10_testis", ("histo normale", None)),
    ("ernst_ch11_epididymis", ("histo normale", None)),
    ("ernst_ch12_vas_deferens", ("histo normale", None)),
    ("ernst_ch13_seminal", ("histo normale", None)),
    ("ernst_ch14_prostate", ("histo normale", None)),
    ("ernst_ch15_ovary", ("histo normale", None)),
    ("ernst_ch16_fallopian", ("histo normale", None)),
    ("ernst_ch17_uterus", ("histo normale", None)),
    ("ernst_ch18_vagina", ("histo normale", None)),
    ("ernst_ch19_external_genitalia", ("histo normale", None)),
    ("ernst_ch21_thyroid", ("histo normale", None)),
    ("ernst_ch22_parathyroid", ("histo normale", None)),
    ("ernst_ch23_pituitary", ("histo normale", None)),
    ("ernst_ch24_thymus", ("histo normale", None)),
    ("ernst_ch25_spleen", ("histo normale", None)),
    ("ernst_ch26_lymph_nodes", ("histo normale", None)),
    ("ernst_ch27_palatine", ("histo normale", None)),
    ("ernst_ch28_bone_marrow", ("histo normale", None)),
    ("ernst_ch29_brain", ("histo normale", None)),
    ("ernst_ch30_eye", ("histo normale", None)),
    ("ernst_ch32_bone", ("histo normale", None)),
    ("ernst_ch34_skin", ("histo normale", None)),
    ("ernst_ch35_mammary", ("histo normale", None)),
    ("ernst_ch36_placenta", ("histo normale", None)),
    ("ernst_2011", ("histo normale", None)),
    ("ashworth_ch01_anatomy", ("histo normale", None)),
    ("benirschke_ch01_examination", ("histo normale", None)),
    ("benirschke_ch02_macroscopic", ("histo normale", None)),
    ("benirschke_ch03_microscopic", ("histo normale", None)),
    ("benirschke_ch06_basic_villus", ("histo normale", None)),
    ("benirschke_ch07_villous_trees", ("histo normale", None)),
    ("benirschke_ch11_histologic", ("histo normale", None)),

    # ── MFIU / rétention ──
    ("ernst_ch37_maceration", ("MFIU", None)),
    ("genest_1992", ("MFIU", None)),
    ("keeling_ch15_macerated", ("MFIU", None)),

    # ── Infections ──
    ("devneuro_ch41_intrauterine_infection", ("infectieux", None)),
    ("keeling_ch09_infection", ("infectieux", None)),

    # ── Maladies métaboliques ──
    ("saudubray_ch06_galactosemia", ("maladie metabo", "galactosémie")),
    ("saudubray_ch07_fructose", ("maladie metabo", "fructose")),
    ("saudubray_ch12_krebs", ("maladie metabo", "cycle de Krebs")),
    ("saudubray_ch14_fao", ("maladie metabo", "β-oxydation")),
    ("saudubray_ch17_tyrosinemia", ("maladie metabo", "tyrosinémie")),
    ("saudubray_ch22_cerebral_organic", ("maladie metabo", "aciduries organiques")),
    ("saudubray_ch23_nkh", ("maladie metabo", "hyperglycinémie")),
    ("saudubray_ch28_carbohydrate", ("maladie metabo", "glucides")),
    ("saudubray_ch32_cholesterol", ("maladie metabo", "cholestérol")),
    ("saudubray_ch33_bile", ("maladie metabo", "acides biliaires")),
    ("saudubray_ch34_phospholipid", ("maladie metabo", "phospholipides")),
    ("saudubray_ch37_metals", ("maladie metabo", "métaux")),
    ("saudubray_ch38_sphingolipid", ("maladie metabo", "sphingolipidoses")),
    ("saudubray_ch39_mps", ("maladie metabo", "mucopolysaccharidoses")),
    ("saudubray_ch40_peroxisomal", ("maladie metabo", "peroxysomales")),
    ("saudubray_ch41_cdg", ("maladie metabo", "CDG")),
    ("saudubray_ch42_cystinosis", ("maladie metabo", "cystinose")),
    ("devneuro_ch28_carbohydrate", ("maladie metabo", "glucides")),
    ("devneuro_ch29_sphingolipid", ("maladie metabo", "sphingolipidoses")),
    ("devneuro_ch30_ncl", ("maladie metabo", "NCL")),
    ("devneuro_ch31_peroxisomal", ("maladie metabo", "peroxysomales")),
    ("devneuro_ch32_mitochondrial", ("maladie metabo", "mitochondriales")),
    ("devneuro_ch37_alexander", ("maladie metabo", "leucodystrophies")),
    ("devneuro_ch38_nbia", ("maladie metabo", "NBIA")),
    ("keeling_ch11_metabolic", ("maladie metabo", None)),
    ("ashworth_ch10_metabolic", ("maladie metabo", "surcharge cardiaque")),
    ("benirschke_ch24_fetal_storage", ("maladie metabo", "surcharge placentaire")),
    ("soffoet_ch20_metaboliques", ("maladie metabo", None)),

    # ── Malformations ──
    ("devneuro_ch02_neural_tube", ("malformation", "tube neural")),
    ("devneuro_ch03_midline", ("malformation", "ligne médiane")),
    ("devneuro_ch04_microcephaly", ("malformation", "microcéphalie")),
    ("devneuro_ch06_lissencephaly_type1", ("malformation", "migration neuronale")),
    ("devneuro_ch07_lissencephaly_type2", ("malformation", "migration neuronale")),
    ("devneuro_ch08_polymicrogyria", ("malformation", "migration neuronale")),
    ("devneuro_ch09_heterotopia", ("malformation", "migration neuronale")),
    ("devneuro_ch12_chiari", ("malformation", "fosse postérieure")),
    ("devneuro_ch13_dandy_walker", ("malformation", "fosse postérieure")),
    ("devneuro_ch15_cerebellar", ("malformation", "fosse postérieure")),
    ("ashworth_ch03_development", ("malformation", None)),
    ("ashworth_ch04_chd_i", ("malformation", "cardiopathie conotroncale")),
    ("ashworth_ch05_chd_ii", ("malformation", "cardiopathie septale")),
    ("ashworth_ch09_coronary", ("malformation", "coronaires")),
    ("soffoet_ch05_coeur", ("malformation", None)),
    ("soffoet_ch09_rein", ("malformation", None)),
    ("soffoet_ch11_cerveau", ("malformation", None)),
    ("soffoet_ch14_membres", ("malformation", None)),
    ("keeling_ch28_brain_malform", ("malformation", None)),

    # ── Disruptions ──
    ("devneuro_ch18_antenatal_disruptions", ("disruption", None)),
    ("devneuro_ch19_hemorrhagic", ("disruption", "hémorragique")),
    ("devneuro_ch20_white_matter", ("disruption", "substance blanche")),
    ("devneuro_ch21_gray_matter", ("disruption", "substance grise")),

    # ── Neuropathies ──
    ("devneuro_ch39_sma", ("neuropathie", "SMA")),
    ("keeling_ch29_brain_degener", ("neuropathie", None)),
    ("keeling_ch31_skeletal_muscle", ("neuropathie", "myopathies")),

    # ── Tumoral ──
    ("ashworth_ch13_tumours", ("tumoral", None)),
    ("benirschke_ch30_chorangiosis_tumours", ("tumoral", None)),

    # ── Trophisme ──
    ("soffoet_ch16_rciu", ("trophisme", "RCIU")),
    ("soffoet_ch17_anasarque", ("trophisme", "anasarque")),
    ("benirschke_ch20_diabetes", ("trophisme", "diabète")),
    ("benirschke_ch23_erythroblastosis", ("trophisme", "hydrops")),
    ("ashworth_ch06_ischaemia", ("trophisme", "ischémie")),

    # ── Pathologie vasculaire placentaire ──
    ("benirschke_ch19_mvm", ("trophisme", "MVM")),
    ("benirschke_ch22_fvm", ("trophisme", "FVM")),

    # ── Cardiomyopathies ──
    ("ashworth_ch07_cardiomyopathy", ("dysplasie", "cardiomyopathie")),
    ("ashworth_ch11_pericardium", ("malformation", "péricarde")),
    ("ashworth_ch12_fetal_cv", ("trophisme", None)),
    ("ashworth_ch15_sudden_death", ("MFIU", "mort subite")),

    # ── Séquence ──
    ("soffoet_ch18_morts_foetales", ("MFIU", None)),

    # ── Hématologie ──
    ("keeling_ch10_hematology", ("trophisme", "hématologie")),
    ("keeling_ch27_reticuloendothelial", ("histo normale", None)),

    # ── Organes spécifiques (Keeling/SOFFOET) ──
    ("keeling_ch21_respiratory", ("malformation", None)),
    ("keeling_ch22_alimentary", ("malformation", None)),
    ("keeling_ch23_liver", ("malformation", None)),
    ("keeling_ch24_urinary", ("malformation", None)),
    ("keeling_ch25_reproductive", ("malformation", None)),
    ("keeling_ch33_skin", ("malformation", None)),
    ("keeling_ch34_special_senses", ("malformation", None)),
    ("soffoet_ch06_poumons", ("malformation", None)),
    ("soffoet_ch07_digestif", ("malformation", None)),
    ("soffoet_ch08_genital", ("malformation", None)),
    ("soffoet_ch12_peau", ("malformation", None)),
    ("soffoet_ch13_squelette", ("malformation", None)),
    ("soffoet_ch23_syndromes", ("malformation", None)),

    # ── Placenta/membranes/cordon (pas typable mécanistiquement) ──
    ("benirschke_ch15_membranes", (None, None)),
    ("benirschke_ch16_umbilical", ("malformation", None)),
    ("benirschke_ch18_multiple", ("malformation", "gémellaire")),
    ("benirschke_ch26_uncertain", (None, None)),
    ("benirschke_ch27_mesenchymal", ("dysplasie", None)),
    ("soffoet_ch15_placenta", (None, None)),

    # ── Perineuro ──
    ("perineuro_s2_nervous_development", ("histo normale", None)),
    ("perineuro_s4_cellular", ("disruption", None)),
    ("perineuro_s4_gray_matter", ("disruption", "substance grise")),
    ("perineuro_s5_hydrocephalus", ("malformation", "hydrocéphalie")),
    ("perineuro_s5_neural_tube", ("malformation", "tube neural")),
]


def match_chapter(sources: str) -> tuple[str | None, str | None]:
    """Match a sources string against CHAPTER_TYPES patterns."""
    for ch in sources.split("|"):
        ch = ch.strip()
        for pattern, (tp, stp) in CHAPTER_TYPES:
            if ch.startswith(pattern) or pattern in ch:
                return tp, stp
    return None, None


def main():
    conn = sqlite3.connect(DB)

    rows = conn.execute(
        "SELECT id, sources FROM foeto_terms WHERE sources IS NOT NULL AND sources != ''"
    ).fetchall()

    n_typed = 0
    n_subtyped = 0
    stats: dict[str, int] = {}

    for fid, sources in rows:
        tp, stp = match_chapter(sources)
        if tp:
            conn.execute(
                "UPDATE foeto_terms SET type_patho=? WHERE id=? AND type_patho IS NULL",
                (tp, fid),
            )
            n_typed += 1
            stats[tp] = stats.get(tp, 0) + 1
        if stp:
            conn.execute(
                "UPDATE foeto_terms SET sous_type_patho=? WHERE id=? AND sous_type_patho IS NULL",
                (stp, fid),
            )
            n_subtyped += 1

    # Retention terms → MFIU
    cur = conn.execute(
        "UPDATE foeto_terms SET type_patho='MFIU' "
        "WHERE axis='retention' AND type_patho IS NULL"
    )
    n_ret = cur.rowcount

    conn.commit()

    print(f"Typés: {n_typed}, sous-typés: {n_subtyped}, rétention→MFIU: {n_ret}")
    print(f"\n── Par type_patho ──")
    for tp, n in sorted(stats.items(), key=lambda x: -x[1]):
        print(f"  {tp:20s} {n}")

    # Non typés
    n_null = conn.execute("SELECT COUNT(*) FROM foeto_terms WHERE type_patho IS NULL").fetchone()[0]
    n_total = conn.execute("SELECT COUNT(*) FROM foeto_terms").fetchone()[0]
    print(f"\nNon typés: {n_null}/{n_total}")

    conn.close()


if __name__ == "__main__":
    main()
