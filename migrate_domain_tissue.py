#!/usr/bin/env python3
"""Migration : ajouter domain + éclater organe placenta en sous-organes.

- Nouvelle colonne `domain` : 'foetus' | 'placenta'
- organe 'placenta' → cordon / membranes / parenchyme / placenta_autre
- Nouvelle colonne `cr_description` : prose médicale pour CR

Idempotent, safe à re-lancer.
"""
import sqlite3

DB = "/home/mathevet/Bureau/foeto_base/syndromes_foetaux.db"

# ── Mapping viewer_id → tissue ──────────────────────────────────────────
# Termes spécifiquement cordon
CORDON = {
    "aou", "fir_s1", "fir_s2", "fir_g1", "fir_g2", "mavm",
    "funiculite", "insertion_velamenteuse_zone",
    "FOETO:0100238_ernst_ret", "FOETO:0100239_ernst_ret",
}

# Termes spécifiquement membranes
MEMBRANES = {
    "mir_s1", "mir_s2", "mir_s3", "mir_g1", "mir_g2",
    "chorio_s1", "chorio_s2", "chorio_s3", "chorio_chronique", "chorio_subaigue",
    "necrose_laminaire_membranes", "amnios_nodosum",
    "depot_meconium", "separation_chorioamniotique",
}

# Tout le reste placenta → parenchyme (default)

# ── Mapping viewer_id → cr_description (prose médicale) ─────────────────
CR_DESCRIPTIONS = {
    # Level 0 diagnostics
    "chi": "L'espace intervilleux présente une inflammation histiocytaire diffuse (CHI).",
    "chorangiose": "On note de multiples foyers de villosités distales hypervascularisées (chorangiose).",
    "chorangiomatose": "On note de multiples foyers de chorangiomatose.",
    "dvm": "On note un retard de maturation villositaire.",
    "nidf": "On note la présence de multiples travées NIDF.",
    "vue_low": "On note de multiples foyers de villite d'étiologie indéterminée (VUE bas grade).",
    "vue_high": "On note de multiples foyers de villite d'étiologie indéterminée de haut grade (VUE haut grade).",
    "deciduite_chronique": "On note un infiltrat lympho-plasmocytaire de la décidue basale (déciduite chronique).",
    "fvm_low": "On note de multiples foyers de villosités avasculaires focales (FVM low grade).",
    "fvm_high": "On note un thrombus des gros vaisseaux (FVM high grade).",
    "mvm_arteriopathie": "On note une artériopathie déciduale (MVM).",
    "mvm_hypoplasie_vd": "On note une hypoplasie villositaire distale (MVM).",
    "mvm_infarctus": "On note un ou plusieurs infarctus villositaires (MVM).",
    "mvm_maturation_acc": "On note une maturation villositaire accélérée (MVM).",
    "dysplasie_mesenchymateuse": "On note un aspect de dysplasie mésenchymateuse placentaire.",
    # FIR (cordon)
    "fir_s1": "On note la présence d'une inflammation polynucléaire neutrophile de la média de la veine ombilicale (FIR stage 1).",
    "fir_s2": "On note la présence d'une inflammation polynucléaire neutrophile de la média de la veine ombilicale et d'une artère ombilicale (FIR stage 2).",
    "fir_g1": "Réponse inflammatoire fœtale de grade 1.",
    "fir_g2": "Funiculite nécrosante (FIR grade 2).",
    "mavm": "Nécrose vasculaire myocytaire associée au méconium (MAVM).",
    "aou": "Artère ombilicale unique.",
    "funiculite": "Funiculite aiguë (réponse fœtale à l'infection).",
    "insertion_velamenteuse_zone": "Insertion vélamenteuse du cordon ombilical.",
    # MIR (membranes)
    "mir_s1": "Infiltrat inflammatoire à PNN de la décidue sans extension au chorion ni nécrose de l'amnios (MIR stage 1).",
    "mir_s2": "Infiltrat inflammatoire à PNN de la décidue avec extensions au chorion sans nécrose de l'amnios (MIR stage 2).",
    "mir_s3": "Infiltrat inflammatoire à PNN de la décidue et du chorion avec nécrose de l'amnios (MIR stage 3).",
    "mir_g1": "Réponse inflammatoire maternelle de grade 1.",
    "mir_g2": "Abcès sous-chorial / karyorrhexis (MIR grade 2).",
    "chorio_s1": "Chorioamniotite aiguë sous-choriale (stade 1).",
    "chorio_s2": "Chorioamniotite aiguë modérée (stade 2).",
    "chorio_s3": "Chorioamniotite nécrosante (stade 3).",
    "chorio_chronique": "Chorioamniotite chronique.",
    "chorio_subaigue": "Chorioamniotite subaiguë.",
    "necrose_laminaire_membranes": "On note une nécrose laminaire de la décidue.",
    "amnios_nodosum": "Amnios nodosum.",
    "depot_meconium": "Dépôt de méconium dans l'amnion.",
    "separation_chorioamniotique": "Séparation chorioamniotique.",
    # Parenchyme - level 1
    "infarctus": "Infarctus villositaire.",
    "hrp": "Hématome rétro-placentaire.",
    "nidf_region": "Dépôt massif de fibrinoïde périvillositaire.",
    "thrombus_intervilleux": "Thrombus intervilleux.",
    "thrombus_plaque_choriale": "Thrombus de la plaque choriale.",
    "thrombose_sous_choriale": "Thrombose sous-choriale massive (môle de Breus).",
    "chorangiome": "Chorangiome placentaire.",
    "erythroblastose": "Érythroblastose placentaire (érythropoïèse extra-hépatique villositaire).",
    "fvm_segmentaire": "Malperfusion vasculaire fœtale segmentaire.",
    "vasculopathie_thrombotique": "Vasculopathie thrombotique fœtale.",
    "accreta_spectrum": "Placenta accreta spectrum.",
    "lobe_accessoire": "Lobe placentaire accessoire (succenturié).",
    "placentomegalie_hydriques": "Placentomégalie avec villosités hydriques.",
    "anastomose_gemellaire": "Anastomose vasculaire fœto-fœtale (jumeaux monochorioniques).",
    # Parenchyme - level 2
    "arteriopathie_deciduale": "Artériopathie déciduale de la plaque basale.",
    "atherose_aigue": "Athérose aiguë déciduale.",
    "necrose_fibrinoide_art": "Nécrose fibrinoïde de la paroi artérielle déciduale.",
    "necrose_fibrinoide_iv": "Nécrose fibrinoïde intravillositaire.",
    "agglutination_villositaire": "Agglutination villositaire par fibrinoïde périvillositaire.",
    "chorangiose_histo": "Hypercapillarisation des villosités terminales (chorangiose histologique).",
    "oedeme_villositaire": "Œdème villositaire.",
    "hypoplasie_villositaire_distale": "Déficience des villosités terminales (hypoplasie villositaire distale).",
    "noeuds_syncytiaux": "Noeuds syncytiaux augmentés.",
    "senescence_trophoblastique": "Sénescence trophoblastique.",
    "vcei": "Villite chronique d'étiologie inconnue (VCEI).",
    "villite_aigue": "Villite aiguë.",
    "villite_basale": "Villite basale chronique.",
    "villite_chronique": "Villite chronique.",
    "villite_granulomateuse": "Villite granulomateuse.",
    "villite_lymphoplasmocytaire": "Villite chronique lympho-plasmocytaire.",
    "villite_necrosante": "Villite nécrosante.",
    "villosites_avasculaires": "Villosités avasculaires.",
    "intervillosite_periinfarctus": "Intervillosite aiguë réactionnelle périinfarctus.",
    "macrophages_meconium": "Macrophages pigmentés au méconium.",
    "hyperplasie_hofbauer": "Hyperplasie des cellules de Hofbauer.",
    "hemosiderine_chorionique": "Hémosidérine dans les macrophages chorioniques.",
    "erythroblastes_exces": "Érythroblastes fœtaux en excès dans la circulation placentaire.",
    "condensation_chromatine": "Condensation chromatinienne des noyaux syncytiaux.",
    "epaississement_mb_trophoblastique": "Épaississement de la membrane basale trophoblastique.",
    "accumulation_glycogene_syncytio": "Accumulation de glycogène dans le syncytiotrophoblaste.",
    "accumulation_lysosomale": "Accumulation lysosomale de glycogène dans le placenta.",
    "vacuolisation_syncytio": "Vacuolisation du syncytiotrophoblaste.",
    "vacuolisation_cytotropho": "Vacuolisation du cytotrophoblaste villositaire.",
    "vacuolisation_hofbauer": "Vacuolisation des cellules de Hofbauer.",
    "vacuolisation_decidues": "Vacuolisation des décidues (cellules déciduales).",
}


def main():
    conn = sqlite3.connect(DB)
    conn.execute("PRAGMA foreign_keys=OFF")

    # ── 1. Add columns ──────────────────────────────────────────────────
    cols = {r[1] for r in conn.execute("PRAGMA table_info(foeto_terms)").fetchall()}

    if "domain" not in cols:
        conn.execute("ALTER TABLE foeto_terms ADD COLUMN domain TEXT")
        print("Added column: domain")

    if "cr_description" not in cols:
        conn.execute("ALTER TABLE foeto_terms ADD COLUMN cr_description TEXT")
        print("Added column: cr_description")

    # ── 2. Set domain for ALL terms ──────────────────────────────────────
    conn.execute("UPDATE foeto_terms SET domain = 'placenta' WHERE organe = 'placenta'")
    conn.execute("UPDATE foeto_terms SET domain = 'foetus' WHERE organe != 'placenta' AND domain IS NULL")
    r = conn.execute("SELECT domain, COUNT(*) FROM foeto_terms GROUP BY domain").fetchall()
    print(f"Domain set: {dict(r)}")

    # ── 3. Remap organe for placenta terms with viewer_id ────────────────
    # Get all placenta terms with viewer_id
    rows = conn.execute(
        "SELECT id, viewer_id FROM foeto_terms WHERE organe = 'placenta' AND viewer_level IS NOT NULL"
    ).fetchall()

    n_cordon = n_membranes = n_parenchyme = 0
    for fid, vid in rows:
        if vid in CORDON:
            conn.execute("UPDATE foeto_terms SET organe = 'cordon' WHERE id = ?", (fid,))
            n_cordon += 1
        elif vid in MEMBRANES:
            conn.execute("UPDATE foeto_terms SET organe = 'membranes' WHERE id = ?", (fid,))
            n_membranes += 1
        else:
            conn.execute("UPDATE foeto_terms SET organe = 'parenchyme' WHERE id = ?", (fid,))
            n_parenchyme += 1

    # Non-viewer placenta terms: keep organe='placenta' (descriptive/reference terms)
    # They'll have domain='placenta' for filtering
    remaining = conn.execute(
        "SELECT COUNT(*) FROM foeto_terms WHERE organe = 'placenta'"
    ).fetchone()[0]

    print(f"Viewer terms remapped: cordon={n_cordon}, membranes={n_membranes}, parenchyme={n_parenchyme}")
    print(f"Non-viewer placenta terms kept as organe='placenta': {remaining}")

    # ── 4. Set cr_description from mapping ───────────────────────────────
    n_cr = 0
    for vid, desc in CR_DESCRIPTIONS.items():
        cur = conn.execute(
            "UPDATE foeto_terms SET cr_description = ? WHERE viewer_id = ? AND cr_description IS NULL",
            (desc, vid),
        )
        n_cr += cur.rowcount
    print(f"CR descriptions set: {n_cr}")

    # ── 5. Verify ────────────────────────────────────────────────────────
    print("\n── Résultat ──")
    for row in conn.execute(
        "SELECT organe, COUNT(*) FROM foeto_terms WHERE domain = 'placenta' GROUP BY organe ORDER BY organe"
    ):
        print(f"  {row[0]:20s} {row[1]}")

    print("\nTermes avec cr_description:")
    n = conn.execute("SELECT COUNT(*) FROM foeto_terms WHERE cr_description IS NOT NULL").fetchone()[0]
    print(f"  {n} termes")

    conn.commit()
    conn.close()
    print("\nDone.")


if __name__ == "__main__":
    main()
