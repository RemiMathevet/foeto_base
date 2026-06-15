#!/usr/bin/env python3
"""Enrichissement métabolique de syndromes_foetaux.db.

Source : Saudubray 6e (Inborn Metabolic Diseases) + connaissances cliniques fœtopath.
Stratégie hybride :
  - Enrichir key_discriminators des syndromes existants
  - Compléter HPO pour NPA, NPC (0 HPO actuellement)
  - Ajouter syndromes manquants (Tay-Sachs, Sandhoff, MLD, Barth, Gaucher type 2)
  - Ajuster pénétrances HPO pour discriminer les sous-types
"""

import sqlite3
from pathlib import Path

DB_PATH = Path("/home/mathevet/Bureau/foeto_base/syndromes_foetaux.db")

# ============================================================
# 1. DISCRIMINATEURS CLINIQUES (key_discriminators)
#    Ajoutés aux syndromes existants pour aider le 9B à
#    différencier les sous-types au sein des sphingolipidoses
# ============================================================

DISCRIMINATORS = {
    "ORPHA:85212": (
        "GAUCHER PÉRINATAL LÉTAL: Arthrogrypose (40%), collodion baby, "
        "hydrops fetalis, hépatosplénomégalie massive, pancytopénie, "
        "ichthyose congénitale. Gène GBA1. "
        "DISCRIMINANT vs NPA: arthrogrypose + collodion + hydrops (absents dans NPA). "
        "DISCRIMINANT vs NPC périnatal: collodion + arthrogrypose (absents dans NPC)."
    ),
    "ORPHA:77292": (
        "NIEMANN-PICK TYPE A: Hépatosplénomégalie progressive (précoce, massive), "
        "hypotonie, tache rouge cerise maculaire (50%, rarement avant 6 mois), "
        "faciès poupin (visage bouffi, macroglosie, gencives hypertrophiques), "
        "retard psychomoteur précoce. Gène SMPD1. "
        "DISCRIMINANT vs Gaucher: PAS d'arthrogrypose, PAS de collodion, PAS d'hydrops. "
        "DISCRIMINANT vs NPC: NPA = forme infantile neuroviscérale sévère, NPC = ictère "
        "cholestatique néonatal + ascite/hydrops fœtal. "
        "DISCRIMINANT vs GM1: PAS de dysostose multiple, PAS de kyphose dorsolombaire."
    ),
    "ORPHA:216972": (
        "NIEMANN-PICK TYPE C PÉRINATAL: Hydrops fœtal OU ascite fœtale + "
        "splénomégalie, ictère cholestatique néonatal prolongé (1/3 cas), "
        "hépatosplénomégalie, insuffisance hépatique rapide possible. Gènes NPC1/NPC2. "
        "DISCRIMINANT vs NPA: ictère cholestatique + hydrops/ascite (absents dans NPA). "
        "DISCRIMINANT vs Gaucher périnatal: PAS d'arthrogrypose, PAS de collodion. "
        "Forme rapide fatale: cholestase + hépatosplénomégalie → décès < 6 mois."
    ),
    "ORPHA:79255": (
        "GM1 GANGLIOSIDOSE TYPE 1: Hypotonie à la naissance, faciès Hurler-like "
        "(visage bouffi, gencives hypertrophiques, nez déprimé), hépatosplénomégalie, "
        "tache rouge cerise (50%), kyphose dorsolombaire, dysostose multiple "
        "(élargissement diaphyses, vertèbres en bec). Forme néonatale sévère: "
        "cardiomyopathie + hydrops fœtal. Gène GLB1. "
        "DISCRIMINANT vs NPA: dysostose multiple + kyphose (absentes dans NPA). "
        "DISCRIMINANT vs MPS I: GM1 a tache rouge cerise + hypotonie précoce."
    ),
    "ORPHA:487": (
        "KRABBE (leucodystrophie à cellules globoïdes): Irritabilité extrême, "
        "hyperesthésie, crises de pleurs inconsolables, spasmes toniques sur stimulation, "
        "neuropathie périphérique précoce (vitesses conduction réduites), "
        "hypertonie → opisthotonus. PAS de tache rouge cerise, PAS d'organomégalie. "
        "Gène GALC. "
        "DISCRIMINANT vs Gaucher type 2: Krabbe = irritabilité + hyperesthésie + "
        "neuropathie périphérique. Gaucher 2 = opisthotonos + splénomégalie + strabisme. "
        "DISCRIMINANT vs MLD: Krabbe = début plus précoce (3-6 mois), irritabilité +++."
    ),
    "ORPHA:333": (
        "FARBER (lipogranulomatose): Tuméfaction articulaire douloureuse (arthrite), "
        "nodules sous-cutanés péri-articulaires, voix rauque/enrouement (atteinte "
        "laryngée). Triade pathognomonique: arthropathie + nodules + voix rauque. "
        "Hépatosplénomégalie variable, tache rouge cerise variable. "
        "Formes fœtales décrites. Gène ASAH1. "
        "DISCRIMINANT vs autres sphingolipidoses: arthrite + nodules + enrouement "
        "= quasi-pathognomonique de Farber."
    ),
    "ORPHA:75233": (
        "WOLMAN: Calcifications surrénaliennes bilatérales (pathognomonique, "
        "visibles en écho prénatale ou radio), hépatosplénomégalie massive, "
        "diarrhée/stéatorrhée, malabsorption, retard de croissance sévère. "
        "Gène LIPA. "
        "DISCRIMINANT: calcifications surrénaliennes = Wolman jusqu'à preuve du contraire. "
        "Aucune autre surcharge lysosomale n'a ce signe."
    ),
    "ORPHA:576": (
        "MUCOLIPIDOSE II (I-CELL DISEASE): Phénotype Hurler-like dès la naissance, "
        "dysostose multiple sévère, fractures prénatales, petite tête "
        "(sutures prématurément fusionnées), cardiomyopathie, coronaropathie sévère. "
        "Gènes GNPTAB/GNPTAG. "
        "DISCRIMINANT vs MPS I: ML II = début prénatal/néonatal (MPS I = début 1ère année), "
        "enzymes lysosomales très élevées dans le plasma (car pas d'adressage lysosomal). "
        "DISCRIMINANT vs GM1: ML II = PAS de tache rouge cerise."
    ),
    "ORPHA:584": (
        "MPS VII (SLY): Hydrops fetalis (présentation prénatale la plus fréquente, "
        "parfois seul signe), hépatosplénomégalie. Après résolution de l'hydrops: "
        "phénotype Hurler-like (dysostose multiple, faciès grossier, retard). "
        "Gène GUSB. "
        "DISCRIMINANT: hydrops fœtal non immun + hépatosplénomégalie = penser MPS VII. "
        "Seul MPS avec présentation fœtale fréquente par hydrops."
    ),
    "ORPHA:93473": (
        "MPS I HURLER: Diagnostic rarement néonatal (normal à la naissance). "
        "Faciès grossier progressif, hépatosplénomégalie, dysostose multiple "
        "(clavicules larges, côtes en rame, kyphose thoracolombaire), "
        "opacité cornéenne, hernies inguinales/ombilicales récurrentes, "
        "retard psychomoteur, valvulopathie. Gène IDUA. GAG: héparane + dermatane sulfate. "
        "DISCRIMINANT vs GM1: MPS I = opacité cornéenne, PAS de tache rouge cerise. "
        "DISCRIMINANT vs ML II: MPS I = début plus tardif (>6 mois)."
    ),
    "ORPHA:87876": (
        "SIALIDOSE TYPE 2: Hydrops fetalis (forme congénitale), faciès Hurler-like, "
        "dysostose multiple, hépatosplénomégalie, tache rouge cerise, "
        "myoclonies. Gène NEU1. "
        "DISCRIMINANT vs GM1: sialidose = myoclonies prééminentes. "
        "DISCRIMINANT vs galactosialidose: sialidose = déficit neuraminidase isolé. "
        "Galactosialidose = déficit combiné neuraminidase + β-galactosidase."
    ),
    "ORPHA:79318": (
        "PMM2-CDG (CDG-Ia): Mamelons inversés, distribution anormale de la graisse "
        "sous-cutanée (fat pads), strabisme convergent, retard psychomoteur, "
        "hypotonie cérébelleuse, atrophie olivo-ponto-cérébelleuse (IRM), "
        "péricardite, protéinurie. Gène PMM2. "
        "DISCRIMINANT: mamelons inversés + fat pads = quasi-pathognomonique de PMM2-CDG. "
        "Profil de transferrine anormal (isofocalisation) = test de dépistage."
    ),
    "ORPHA:365": (
        "POMPE (GSD II, déficit en maltase acide): Cardiomyopathie hypertrophique "
        "massive (forme infantile), hypotonie sévère (floppy baby), macroglossie, "
        "hépatomégalie, insuffisance respiratoire. Gène GAA. "
        "DISCRIMINANT: cardiomyopathie hypertrophique massive + hypotonie = Pompe. "
        "ECG: PR court, QRS amples. "
        "DISCRIMINANT vs Barth: Pompe = cardiomyopathie hypertrophique (pas dilatée), "
        "pas de neutropénie."
    ),
    "ORPHA:765": (
        "DÉFICIT EN PYRUVATE DÉSHYDROGÉNASE: Acidose lactique congénitale, "
        "malformations cérébrales (agénésie/hypoplasie du corps calleux, "
        "ventriculomégalie), dysmorphie faciale (front étroit, nez retroussé), "
        "hypotonie, épilepsie. Gène PDHA1 (X-lié). "
        "DISCRIMINANT: acidose lactique + agénésie corps calleux = PDH. "
        "DISCRIMINANT vs Leigh: PDH = malformations structurelles cérébrales "
        "(Leigh = lésions symétriques noyaux gris centraux à l'IRM)."
    ),
    "ORPHA:35": (
        "ACIDÉMIE PROPIONIQUE: Détresse néonatale (1ère semaine), "
        "acidose métabolique sévère avec trou anionique, hyperammoniémie, "
        "cétonurie, pancytopénie, cardiomyopathie. Gène PCCA/PCCB. "
        "DISCRIMINANT vs acidémie méthylmalonique: propionique = pas de methylmalonate "
        "dans les urines. Cliniquement quasi-indistinguables sans biochimie. "
        "DISCRIMINANT vs Pompe: pas de cardiomyopathie hypertrophique, "
        "acidose métabolique ++ (absente dans Pompe)."
    ),
    "ORPHA:228308": (
        "DÉFICIT EN CPT II NÉONATAL SÉVÈRE: Hépatomégalie, cardiomyopathie, "
        "arythmie, hypoglycémie hypocétotique, anomalies rénales (reins kystiques), "
        "dysmorphie faciale, malformations cérébrales possibles. Gène CPT2. "
        "DISCRIMINANT: hypoglycémie hypocétotique + cardiomyopathie + "
        "reins kystiques = CPT II. "
        "DISCRIMINANT vs Pompe: CPT II = hypoglycémie hypocétotique (absente dans Pompe)."
    ),
    "ORPHA:394529": (
        "MADD / ACIDURIE GLUTARIQUE TYPE II: Dysmorphie faciale (front large, "
        "nez court, hypertélorisme), reins kystiques/dysplasiques, "
        "hypoglycémie, acidose métabolique, odeur de pieds en sueur, "
        "hépatomégalie, cardiomyopathie. Gènes ETFA/ETFB/ETFDH. "
        "DISCRIMINANT: dysmorphie faciale + reins kystiques + odeur de pieds = MADD. "
        "DISCRIMINANT vs CPT II: MADD = dysmorphie faciale + acidose organique."
    ),
}

# ============================================================
# 2. SYNDROMES À CRÉER (absents de la DB)
# ============================================================

NEW_SYNDROMES = {
    "ORPHA:845": {
        "name_fr": "Maladie de Tay-Sachs (gangliosidose GM2, variant B)",
        "category": "metabolique",
        "omim": "272800",
    },
    "ORPHA:796": {
        "name_fr": "Maladie de Sandhoff (gangliosidose GM2, variant 0)",
        "category": "metabolique",
        "omim": "268800",
    },
    "ORPHA:512": {
        "name_fr": "Leucodystrophie métachromatique",
        "category": "metabolique",
        "omim": "250100",
    },
    "ORPHA:111": {
        "name_fr": "Syndrome de Barth (acidurie 3-méthylglutaconique type II)",
        "category": "metabolique",
        "omim": "302060",
    },
    "ORPHA:77259": {
        "name_fr": "Maladie de Gaucher type 2 (neuronopathique aigu)",
        "category": "metabolique",
        "omim": "230900",
    },
}

NEW_DISCRIMINATORS = {
    "ORPHA:845": (
        "TAY-SACHS: Sursaut exagéré au bruit (hyperacousie) = signe cardinal, "
        "hypotonie progressive, tache rouge cerise maculaire (quasi-constante), "
        "macrocéphalie progressive (>18 mois), convulsions. "
        "PAS d'organomégalie, PAS de dysostose. Gène HEXA. "
        "DISCRIMINANT vs Sandhoff: Tay-Sachs = PAS d'organomégalie, "
        "PAS d'anomalies osseuses (Sandhoff = organomégalie + os). "
        "DISCRIMINANT vs GM1: Tay-Sachs = PAS de dysostose multiple."
    ),
    "ORPHA:796": (
        "SANDHOFF: Même tableau que Tay-Sachs (sursaut, tache rouge cerise, "
        "hypotonie, macrocéphalie) PLUS organomégalie (hépatosplénomégalie) "
        "et anomalies osseuses. Gène HEXB. "
        "DISCRIMINANT vs Tay-Sachs: Sandhoff = organomégalie + anomalies osseuses. "
        "DISCRIMINANT vs GM1: Sandhoff = PAS de faciès Hurler-like."
    ),
    "ORPHA:512": (
        "MLD (leucodystrophie métachromatique): Forme infantile tardive (début 1-2 ans), "
        "régression motrice (marche → chute), hypotonie puis spasticité, "
        "aréflexie ostéotendineuse (neuropathie périphérique), "
        "atrophie optique, leucodystrophie symétrique à l'IRM. Gène ARSA. "
        "DISCRIMINANT vs Krabbe: MLD = début plus tardif (>12 mois vs 3-6 mois), "
        "moins d'irritabilité, aréflexie tendineuse. "
        "DISCRIMINANT vs leucodystrophies autres: sulfatides urinaires élevés."
    ),
    "ORPHA:111": (
        "BARTH: Cardiomyopathie dilatée (début néonatal/infantile), "
        "neutropénie cyclique ou chronique, myopathie squelettique, "
        "retard de croissance, acidurie 3-méthylglutaconique. "
        "Transmission X-liée (garçons uniquement). Gène TAFAZZIN (TAZ). "
        "DISCRIMINANT: cardiomyopathie dilatée + neutropénie + garçon = Barth. "
        "DISCRIMINANT vs Pompe: Barth = dilatée (pas hypertrophique), neutropénie."
    ),
    "ORPHA:77259": (
        "GAUCHER TYPE 2 (neuronopathique aigu): Rétroflexion cervicale, "
        "opisthotonus, strabisme, troubles de déglutition, splénomégalie constante, "
        "atteinte du tronc cérébral. Début 3-6 mois. Décès < 2 ans. Gène GBA1. "
        "DISCRIMINANT vs Gaucher périnatal: type 2 = PAS d'hydrops, PAS de collodion, "
        "PAS d'arthrogrypose. Rétroflexion cervicale + strabisme = type 2. "
        "DISCRIMINANT vs Krabbe: Gaucher 2 = splénomégalie constante (absente Krabbe)."
    ),
}

# ============================================================
# 3. HPO À AJOUTER (pour syndromes avec 0 HPO ou nouveaux)
# ============================================================

SYNDROME_HPO = {
    # NPA (ORPHA:77292) — actuellement 0 HPO
    "ORPHA:77292": [
        ("HP:0001433", 0.95, "Hépatosplénomégalie"),
        ("HP:0001252", 0.90, "Hypotonie musculaire"),
        ("HP:0010729", 0.50, "Tâche rouge cerise de la macula"),
        ("HP:0001263", 0.85, "Retard global de développement"),
        ("HP:0001288", 0.80, "Troubles de la marche"),
        ("HP:0002240", 0.95, "Hépatomégalie"),
        ("HP:0001744", 0.95, "Splénomégalie"),  # actually full splénomégalie
        ("HP:0001508", 0.70, "Retard staturo-pondéral"),
        ("HP:0001250", 0.60, "Spasticité"),
        ("HP:0001249", 0.50, "Déficience intellectuelle"),
        ("HP:0002015", 0.50, "Dysphagie"),
        ("HP:0000952", 0.40, "Ictère"),
    ],
    # NPC périnatal (ORPHA:216972) — actuellement 0 HPO
    "ORPHA:216972": [
        ("HP:0001433", 0.90, "Hépatosplénomégalie"),
        ("HP:0001789", 0.60, "Anasarque foetal"),
        ("HP:0001791", 0.50, "Ascite foetale"),
        ("HP:0001396", 0.70, "Cholestase"),
        ("HP:0006579", 0.60, "Ictère néonatal prolongé"),
        ("HP:0002240", 0.90, "Hépatomégalie"),
        ("HP:0001744", 0.80, "Splénomégalie"),
        ("HP:0001252", 0.60, "Hypotonie musculaire"),
        ("HP:0001399", 0.40, "Insuffisance hépatique"),
        ("HP:0002910", 0.30, "Augmentation des transaminases"),
    ],
    # MADD sévère néonatale (ORPHA:394529) — actuellement 0 HPO
    "ORPHA:394529": [
        ("HP:0000252", 0.30, "Microcéphalie"),
        ("HP:0000316", 0.70, "Hypertélorisme"),
        ("HP:0000431", 0.60, "Narines antéversées"),
        ("HP:0000175", 0.20, "Fente palatine"),
        ("HP:0000107", 0.80, "Reins kystiques"),
        ("HP:0001942", 0.90, "Acidose métabolique"),
        ("HP:0001943", 0.85, "Hypoglycémie"),
        ("HP:0002240", 0.80, "Hépatomégalie"),
        ("HP:0001638", 0.60, "Cardiomyopathie"),
        ("HP:0001252", 0.80, "Hypotonie musculaire"),
        ("HP:0001319", 0.70, "Hypotonie néonatale"),
    ],
    # Tay-Sachs (ORPHA:845)
    "ORPHA:845": [
        ("HP:0002267", 0.95, "Réaction de sursaut exagérée"),
        ("HP:0010780", 0.90, "Hyperacousie"),
        ("HP:0001252", 0.90, "Hypotonie musculaire"),
        ("HP:0010729", 0.90, "Tâche rouge cerise de la macula"),
        ("HP:0004481", 0.80, "Macrocéphalie progressive"),
        ("HP:0001250", 0.70, "Spasticité"),
        ("HP:0001263", 0.90, "Retard global de développement"),
        ("HP:0001249", 0.85, "Déficience intellectuelle"),
        ("HP:0001336", 0.60, "Myoclonies"),
        ("HP:0002197", 0.50, "Crises généralisées"),
        ("HP:0000543", 0.60, "Optic disc pallor"),
    ],
    # Sandhoff (ORPHA:796)
    "ORPHA:796": [
        ("HP:0002267", 0.95, "Réaction de sursaut exagérée"),
        ("HP:0010780", 0.90, "Hyperacousie"),
        ("HP:0001252", 0.90, "Hypotonie musculaire"),
        ("HP:0010729", 0.85, "Tâche rouge cerise de la macula"),
        ("HP:0004481", 0.70, "Macrocéphalie progressive"),
        ("HP:0001433", 0.60, "Hépatosplénomégalie"),
        ("HP:0001250", 0.70, "Spasticité"),
        ("HP:0001263", 0.90, "Retard global de développement"),
        ("HP:0001249", 0.85, "Déficience intellectuelle"),
        ("HP:0000943", 0.30, "Dysostose multiple"),
    ],
    # MLD (ORPHA:512)
    "ORPHA:512": [
        ("HP:0001252", 0.85, "Hypotonie musculaire"),
        ("HP:0001250", 0.80, "Spasticité"),
        ("HP:0001263", 0.90, "Retard global de développement"),
        ("HP:0001288", 0.85, "Troubles de la marche"),
        ("HP:0001315", 0.70, "Aréflexie"),
        ("HP:0007141", 0.80, "Démyélinisation sensorimotrice"),
        ("HP:0000648", 0.60, "Atrophie optique"),
        ("HP:0001249", 0.85, "Déficience intellectuelle"),
        ("HP:0002197", 0.50, "Crises généralisées"),
        ("HP:0002134", 0.70, "Anomalies de la substance blanche"),
    ],
    # Barth (ORPHA:111)
    "ORPHA:111": [
        ("HP:0001644", 0.90, "Cardiomyopathie dilatée"),
        ("HP:0001875", 0.85, "Neutropénie"),
        ("HP:0003236", 0.70, "Élévation des CPK"),
        ("HP:0001508", 0.80, "Retard staturo-pondéral"),
        ("HP:0001252", 0.70, "Hypotonie musculaire"),
        ("HP:0003128", 0.40, "Acidose lactique"),
        ("HP:0001943", 0.50, "Hypoglycémie"),
        ("HP:0002151", 0.30, "Intolérance à l'exercice"),
    ],
    # Gaucher type 2 (ORPHA:77259)
    "ORPHA:77259": [
        ("HP:0001744", 0.95, "Splénomégalie"),
        ("HP:0002240", 0.80, "Hépatomégalie"),
        ("HP:0001433", 0.85, "Hépatosplénomégalie"),
        ("HP:0002179", 0.70, "Opisthotonus"),
        ("HP:0000486", 0.80, "Strabisme"),
        ("HP:0002015", 0.80, "Dysphagie"),
        ("HP:0001252", 0.85, "Hypotonie musculaire"),
        ("HP:0001250", 0.70, "Spasticité"),
        ("HP:0001263", 0.80, "Retard global de développement"),
        ("HP:0002197", 0.50, "Crises généralisées"),
        ("HP:0011968", 0.60, "Troubles de l'alimentation"),
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
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row

    stats = {
        "discriminators_updated": 0,
        "new_syndromes": 0,
        "hpo_inserted": 0,
        "hpo_updated": 0,
        "new_hpo_terms": 0,
    }

    # --- Étape 1 : Créer les syndromes manquants ---
    for sid, info in NEW_SYNDROMES.items():
        existing = conn.execute("SELECT id FROM syndromes WHERE id=?", (sid,)).fetchone()
        if existing:
            print(f"  SKIP: {sid} déjà en DB ({info['name_fr']})")
            continue
        conn.execute(
            """INSERT INTO syndromes (id, name_fr, category, omim, relevance)
               VALUES (?, ?, ?, ?, ?)""",
            (sid, info["name_fr"], info["category"], info.get("omim"), "high"),
        )
        print(f"  NEW: {sid} — {info['name_fr']}")
        stats["new_syndromes"] += 1

    # --- Étape 2 : Ajouter/mettre à jour les discriminateurs ---
    all_disc = {**DISCRIMINATORS, **NEW_DISCRIMINATORS}
    for sid, disc_text in all_disc.items():
        row = conn.execute(
            "SELECT id, key_discriminators FROM syndromes WHERE id=?", (sid,)
        ).fetchone()
        if not row:
            print(f"  WARN: {sid} not in DB, skipping discriminator")
            continue

        old = row["key_discriminators"] or ""
        if "DISCRIMINANT" in old and "DISCRIMINANT" in disc_text:
            # Already has metabolic discriminators
            if "Saudubray" in old:
                print(f"  SKIP disc: {sid} already enriched")
                continue
            new_disc = old + " | SAUDUBRAY_METAB: " + disc_text
        elif old:
            new_disc = old + " | SAUDUBRAY_METAB: " + disc_text
        else:
            new_disc = disc_text

        conn.execute(
            "UPDATE syndromes SET key_discriminators=?, updated_at=datetime('now') WHERE id=?",
            (new_disc, sid),
        )
        stats["discriminators_updated"] += 1

    # --- Étape 3 : Ajouter les HPO ---
    for sid, hpo_list in SYNDROME_HPO.items():
        for hpo_id, penetrance, label_fr in hpo_list:
            # Ensure HPO term exists
            existing_hpo = conn.execute(
                "SELECT hpo_id FROM hpo_terms WHERE hpo_id=?", (hpo_id,)
            ).fetchone()
            if not existing_hpo:
                conn.execute(
                    "INSERT INTO hpo_terms (hpo_id, label_fr, label_en, context) VALUES (?, ?, ?, ?)",
                    (hpo_id, label_fr, label_fr, "both"),
                )
                stats["new_hpo_terms"] += 1

            # Check existing link
            existing_link = conn.execute(
                "SELECT prob FROM syndrome_hpo WHERE syndrome_id=? AND hpo_id=?",
                (sid, hpo_id),
            ).fetchone()

            if existing_link:
                if penetrance > (existing_link["prob"] or 0):
                    conn.execute(
                        "UPDATE syndrome_hpo SET prob=?, frequency=?, source=? "
                        "WHERE syndrome_id=? AND hpo_id=?",
                        (penetrance, freq_label(penetrance), "saudubray_metab",
                         sid, hpo_id),
                    )
                    stats["hpo_updated"] += 1
            else:
                conn.execute(
                    "INSERT INTO syndrome_hpo (syndrome_id, hpo_id, prob, frequency, source) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (sid, hpo_id, penetrance, freq_label(penetrance), "saudubray_metab"),
                )
                stats["hpo_inserted"] += 1

    conn.commit()
    conn.close()

    print(f"\n=== Import master métabolique terminé ===")
    for k, v in stats.items():
        print(f"  {k}: {v}")


if __name__ == "__main__":
    main()
