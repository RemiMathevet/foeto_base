#!/usr/bin/env python3
"""Enrichissement syndromes malformations cérébrales de syndromes_foetaux.db.

Les cas cérébraux du benchmark v2 scorent 75% — confusions entre
sous-types de lissencéphalie, holoprosencéphalie, et anomalies
de la fosse postérieure. Enrichit les discriminateurs cliniques.
"""

import sqlite3
import shutil
from pathlib import Path

DB_PATH = Path("/home/mathevet/Bureau/foeto_base/syndromes_foetaux.db")

DISCRIMINATORS = {
    # --- Holoprosencéphalie ---
    "ORPHA:2162": (
        "HOLOPROSENCÉPHALIE (SHH/ZIC2/SIX3/TGIF1): Spectre continu de sévérité — "
        "ALOBAR (plus sévère: ventricule UNIQUE, thalamus fusionnés, "
        "cyclopie/proboscis/hypotélorisme sévère, létale) → "
        "SEMILOBAR (fusion frontale partielle, cornes occipitales séparées, "
        "hypotélorisme modéré) → "
        "LOBAR (séparation quasi-complète, dysplasie septale, incisive unique médiane). "
        "Règle fondamentale: 'the face predicts the brain' — "
        "la sévérité de la dysmorphie faciale corrèle avec la malformation cérébrale. "
        "DISCRIMINANT vs agénésie corps calleux: HPE = FUSION des hémisphères. "
        "ACC = hémisphères SÉPARÉS mais sans commissure inter-hémisphérique. "
        "QUAND PENSER CHROMOSOMIQUE: HPE + anomalies extra-cérébrales = "
        "trisomie 13 (50% des HPE chromosomiques) ou délétion 13q. "
        "EN PRÉNATAL: détectable dès 12 SA (alobar), 20 SA (semilobar/lobar)."
    ),
    # --- Walker-Warburg ---
    "ORPHA:899": (
        "WALKER-WARBURG (POMT1/POMT2/POMGnT1/FKRP/LARGE1): "
        "Triade: lissencéphalie type II COBBLESTONE + dystrophie musculaire congénitale "
        "+ anomalies oculaires SÉVÈRES (microphtalmie, décollement rétine, "
        "persistance vitré primitif, cataracte). TOUJOURS LÉTAL < 3 ans. CK élevées. "
        "Dystroglycanopathie la plus sévère du spectre. "
        "DISCRIMINANT vs MEB (Muscle-Eye-Brain): Walker-Warburg = LÉTAL, "
        "cobblestone DIFFUSE, anomalies oculaires SÉVÈRES (microphtalmie). "
        "MEB = survie possible, polymicrogyrie > cobblestone, "
        "anomalies oculaires MOINS sévères (myopie sévère > microphtalmie). "
        "DISCRIMINANT vs Fukuyama: Fukuyama = cobblestone + dystrophie musculaire "
        "MAIS anomalies oculaires ABSENTES ou MINIMES. Quasi-exclusif au Japon (FKTN). "
        "DISCRIMINANT vs lissencéphalie type I (LIS1): "
        "COBBLESTONE = surface irrégulière pavée (sur-migration neuronale). "
        "TYPE I = surface LISSE agyrique (sous-migration). Mécanisme OPPOSÉ. "
        "QUAND PENSER DYSTROGLYCANOPATHIE: lissencéphalie + anomalies oculaires "
        "+ CK élevées = cobblestone spectrum."
    ),
    # --- MEB ---
    "ORPHA:588": (
        "MEB / MUSCLE-EYE-BRAIN (POMGnT1 principalement): "
        "Même spectre dystroglycanopathie que Walker-Warburg mais MOINS SÉVÈRE. "
        "Survie possible jusqu'à l'âge adulte. Polymicrogyrie frontopariétale > "
        "cobblestone diffuse. Myopie sévère, glaucome congénital, "
        "dystrophie musculaire modérée. CK modérément élevées. "
        "DISCRIMINANT vs Walker-Warburg: MEB = SURVIE, polymicrogyrie > cobblestone, "
        "anomalies oculaires modérées. Walker-Warburg = LÉTAL, cobblestone diffuse."
    ),
    # --- Aicardi ---
    "ORPHA:50": (
        "AICARDI: Lié à l'X, FILLES uniquement (létal chez garçons, "
        "ou garçons 47,XXY). Triade PATHOGNOMONIQUE: "
        "agénésie totale/partielle du corps calleux + "
        "lacunes choriorétiniennes (lésions blanc-jaunâtre 'en confettis' au FO — "
        "PATHOGNOMONIQUE, aucun autre syndrome) + "
        "spasmes infantiles (syndrome de West). "
        "Souvent: anomalies vertébrales (hémivertèbres, côtes surnuméraires), "
        "hétérotopies périventriculaires. "
        "DISCRIMINANT: lacunes choriorétiniennes + ACC + épilepsie = Aicardi. "
        "DISCRIMINANT vs ACC isolée: Aicardi = TOUJOURS lacunes choriorétiniennes. "
        "DISCRIMINANT vs ACC + colobome: colobome ≠ lacunes choriorétiniennes "
        "(colobome = défaut de fermeture fissure optique; lacunes = atrophie "
        "rétinienne en confettis). "
        "SEXE: UNIQUEMENT filles."
    ),
    # --- L1 / CRASH ---
    "ORPHA:275543": (
        "L1 SYNDROME / CRASH / HSAS / MASA (L1CAM, Xq28): "
        "Hydrocéphalie congénitale + pouces en adduction "
        "(PATHOGNOMONIQUE de L1CAM — flexion permanente du pouce dans la paume) "
        "+ retard psychomoteur + agénésie/hypoplasie corps calleux + spasticité. "
        "GARÇONS uniquement (X-linked récessif). "
        "Spectre clinique variable: HSAS (forme sévère, hydrocéphalie + "
        "sténose aqueducale) → MASA (forme modérée, retard + aphasie + "
        "marche traînante + pouces en adduction). "
        "DISCRIMINANT: hydrocéphalie + pouces en adduction = L1 syndrome. "
        "Ce combo est quasi-PATHOGNOMONIQUE. "
        "DISCRIMINANT vs hydrocéphalie acquise/obstructive: "
        "L1 = hydrocéphalie + pouces en adduction + hypoplasie corps calleux. "
        "Hydrocéphalie acquise = PAS de pouces en adduction. "
        "SEXE: UNIQUEMENT garçons."
    ),
    # --- Dandy-Walker ---
    "ORPHA:217": (
        "DANDY-WALKER (sporadique ou génétique, hétérogène): "
        "Triade: hypoplasie/agénésie du VERMIS cérébelleux + "
        "dilatation kystique du 4ème ventricule + "
        "fosse postérieure élargie (surélévation tente du cervelet). "
        "Hydrocéphalie (80%). Retard variable. "
        "DISCRIMINANT vs méga-cisterna magna: Dandy-Walker = vermis ABSENT/HYPOPLASIQUE "
        "+ kyste communiquant avec V4. Méga-cisterna = vermis NORMAL + citernes dilatées. "
        "DISCRIMINANT vs kyste arachnoïdien FP: Dandy-Walker = communication avec V4. "
        "Kyste arachnoïdien = PAS de communication, vermis normal mais comprimé. "
        "DISCRIMINANT vs Joubert: Dandy-Walker = vermis hypoplasique + kyste FP "
        "SANS 'molar tooth sign'. Joubert = 'molar tooth sign' "
        "(vermis hypoplasique + pédoncules cérébelleux allongés horizontalement) "
        "+ anomalies rénales/hépatiques fréquentes."
    ),
    # --- Lissencéphalie LIS1 isolée ---
    "ORPHA:95232": (
        "LISSENCÉPHALIE LIS1 ISOLÉE (PAFAH1B1 = LIS1): "
        "Lissencéphalie à gradient POSTÉRIEUR (agyrie pariéto-occipitale > frontale). "
        "PAS de dysmorphie faciale (distinction clé vs Miller-Dieker). "
        "Microcéphalie progressive. Épilepsie sévère (spasmes infantiles → Lennox-Gastaut). "
        "Mutation ponctuelle ou délétion intragénique LIS1 (PAS de délétion 17p13.3). "
        "DISCRIMINANT vs Miller-Dieker: LIS1 isolée = PAS de dysmorphie faciale. "
        "Miller-Dieker = DÉLÉTION 17p13.3 = lissencéphalie + dysmorphie faciale "
        "CARACTÉRISTIQUE (front haut étroit, tempes creuses, chapeau de gendarme). "
        "DISCRIMINANT vs DCX (XLIS, ORPHA:2148): LIS1 = gradient POSTÉRIEUR. "
        "DCX = gradient ANTÉRIEUR (agyrie frontale > postérieure). "
        "Chez les filles DCX: band heterotopia subcorticale bilatérale. "
        "DISCRIMINANT vs cobblestone (type II): type I = surface LISSE. "
        "Type II = surface IRRÉGULIÈRE pavée."
    ),
    # --- DCX / Double cortine ---
    "ORPHA:2148": (
        "LISSENCÉPHALIE DCX / DOUBLE CORTINE (DCX, Xq22): "
        "Lissencéphalie à gradient ANTÉRIEUR (agyrie frontale > postérieure, "
        "OPPOSÉ à LIS1). X-linked: GARÇONS = lissencéphalie classique. "
        "FILLES = hétérotopie en bande subcorticale bilatérale "
        "(band heterotopia / double cortex — quasi-PATHOGNOMONIQUE de DCX). "
        "DISCRIMINANT vs LIS1: DCX = gradient ANTÉRIEUR. LIS1 = gradient POSTÉRIEUR. "
        "DISCRIMINANT: femme + hétérotopie en bande bilatérale = DCX. "
        "DISCRIMINANT vs Miller-Dieker: DCX = PAS de dysmorphie faciale. "
        "Miller-Dieker = dysmorphie + DÉLÉTION 17p13.3."
    ),
    # --- Norman-Roberts ---
    "ORPHA:89844": (
        "NORMAN-ROBERTS (RELN): Lissencéphalie + microcéphalie sévère + "
        "front FUYANT (sloping forehead) + nez proéminent + menton fuyant. "
        "Cervelet HYPOPLASIQUE (RELN = reeline, essentielle pour migration neuronale "
        "corticale ET cérébelleuse). Épilepsie sévère. "
        "DISCRIMINANT vs Miller-Dieker: Norman-Roberts = front FUYANT. "
        "Miller-Dieker = front HAUT et ÉTROIT. "
        "DISCRIMINANT vs LIS1 isolée: Norman-Roberts = microcéphalie sévère + "
        "dysmorphie faciale + CERVELET HYPOPLASIQUE. "
        "LIS1 isolée = PAS de dysmorphie, cervelet normal."
    ),
    # --- Apert ---
    "ORPHA:87": (
        "APERT (FGFR2, Ser252Trp ou Pro253Arg): "
        "Craniosynostose coronale bilatérale (turricéphalie/acrocéphalie) + "
        "syndactylie COMPLEXE mains ET pieds (moufle/mitten hand — "
        "fusion 2-3-4 doigts = PATHOGNOMONIQUE). Retard intellectuel variable. "
        "Acné sévère adolescence. Fente palatine (30%). "
        "DISCRIMINANT vs Crouzon: Apert = syndactylie COMPLEXE. "
        "Crouzon = PAS de syndactylie (même gène FGFR2 mais mutations différentes). "
        "DISCRIMINANT vs Pfeiffer: Apert = syndactylie en MOUFLE (fusion 2-3-4). "
        "Pfeiffer = pouces et hallux LARGES + divergents, syndactylie partielle. "
        "DISCRIMINANT vs Saethre-Chotzen: Apert = syndactylie SÉVÈRE (moufle). "
        "Saethre-Chotzen = syndactylie LÉGÈRE (2-3 doigts seulement). "
        "EN PRÉNATAL: craniosynostose + syndactylie = Apert."
    ),
    # --- ACC isolée ---
    "ORPHA:200": (
        "AGÉNÉSIE ISOLÉE DU CORPS CALLEUX: Agénésie totale ou partielle du CC "
        "SANS autre malformation cérébrale majeure. Peut être: sporadique, "
        "autosomique dominante, autosomique récessive, ou liée à l'X. "
        "Pronostic très variable: 50% développement normal, 50% retard variable. "
        "EN PRÉNATAL: colpocéphalie (dilatation cornes occipitales), "
        "ascension du 3ème ventricule, absence de cavum septi pellucidi. "
        "DISCRIMINANT vs Aicardi: ACC isolée = PAS de lacunes choriorétiniennes, "
        "PAS de spasmes infantiles. Aicardi = lacunes + spasmes + fille. "
        "DISCRIMINANT vs HPE: ACC = hémisphères SÉPARÉS. HPE = hémisphères FUSIONNÉS. "
        "QUAND CHERCHER UN SYNDROME: ACC + anomalies extra-cérébrales = syndromique. "
        "ACC + FO normal + développement normal = probablement isolée."
    ),
    # --- Hydranencéphalie ---
    "ORPHA:2177": (
        "HYDRANENCÉPHALIE: Destruction massive des hémisphères cérébraux "
        "avec remplacement par LCR — sac de liquide sous la voûte crânienne. "
        "Cause: occlusion bilatérale des artères carotides internes (vasculaire), "
        "infection (CMV, toxoplasmose), rarement génétique. "
        "Tronc cérébral et structures infratentorielles PRÉSERVÉS. "
        "DISCRIMINANT vs hydrocéphalie sévère: hydranencéphalie = cortex ABSENT "
        "(transillumination positive). Hydrocéphalie = cortex présent mais aminci. "
        "DISCRIMINANT vs HPE alobar: HPE = FUSION, structures médianes anormales, "
        "dysmorphie faciale. Hydranencéphalie = DESTRUCTION, structures médianes "
        "normales au départ. "
        "EN PRÉNATAL: diagnostic différentiel difficile avec hydrocéphalie massive. "
        "IRM fœtale = clé."
    ),
    # --- Porencéphalie ---
    "ORPHA:2940": (
        "PORENCÉPHALIE: Cavité kystique dans le parenchyme cérébral "
        "communiquant avec le système ventriculaire et/ou l'espace sous-arachnoïdien. "
        "Cause: vasculaire (AVC fœtal), COL4A1/COL4A2 (forme familiale), "
        "infection, traumatisme. "
        "DISCRIMINANT vs kyste arachnoïdien: porencéphalie = cavité "
        "INTRA-PARENCHYMATEUSE communiquant avec ventricules. "
        "Kyste arachnoïdien = EXTRA-PARENCHYMATEUX, ne communique pas. "
        "DISCRIMINANT vs schizencéphalie: porencéphalie = parois LISSES sans cortex. "
        "Schizencéphalie = fente bordée de CORTEX dysmorphique (polymicrogyrie)."
    ),
    # --- Schizencéphalie (familiale) ---
    "ORPHA:481986": (
        "SCHIZENCÉPHALIE: Fente trans-cérébrale bordée de cortex DYSMORPHIQUE "
        "(polymicrogyrie). Deux types: lèvres ouvertes (open-lip, plus sévère, "
        "fente large remplie de LCR) vs lèvres fermées (closed-lip, parois accolées). "
        "Unilatérale ou bilatérale. EMX2, SHH, SIX3 impliqués. "
        "DISCRIMINANT vs porencéphalie: schizencéphalie = fente bordée de "
        "POLYMICROGYRIE (cortex gris visible sur les bords). "
        "Porencéphalie = cavité à parois LISSES sans cortex. "
        "DISCRIMINANT: IRM = clé diagnostique. Polymicrogyrie péri-fissuraire "
        "= schizencéphalie."
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
    shutil.copy(DB_PATH, str(DB_PATH) + ".bak_pre_cerebrales_import")
    print(f"Backup: {DB_PATH}.bak_pre_cerebrales_import")

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
        if "CEREBRAL:" in old or "COBBLESTONE" in old or "PATHOGNOMONIQUE" in old:
            print(f"  SKIP disc: {sid} ({row['name_fr']}) — already enriched")
            continue

        if old:
            new_disc = old + " | CEREBRAL: " + disc_text
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
                data.get("omim", ""), data.get("category", "cérébral"),
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
                   VALUES (?, ?, ?, ?, 'master_cerebrales')""",
                (sid, hpo_id, freq_label(penetrance), penetrance),
            )
            stats["hpo_inserted"] += 1

    conn.commit()
    conn.close()

    print(f"\n=== Import master cérébrales terminé ===")
    for k, v in stats.items():
        print(f"  {k}: {v}")


if __name__ == "__main__":
    main()
