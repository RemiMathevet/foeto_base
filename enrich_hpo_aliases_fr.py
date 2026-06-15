#!/usr/bin/env python3
"""Enrichissement des aliases_fr dans hpo_terms — variantes cliniques fœtopathologie.

Cible les termes HPO les plus fréquemment utilisés dans le syndrome_search
mais dont les aliases_fr sont absents ou incomplets. Ajoute les variantes
que les cliniciens utiliseraient naturellement en français.
"""

import sqlite3
import shutil
from pathlib import Path

DB_PATH = Path("/home/mathevet/Bureau/foeto_base/syndromes_foetaux.db")

ALIASES_TO_ADD: dict[str, list[str]] = {
    # --- Termes fréquents sans aliases (top du syndrome_search) ---
    "HP:0000238": [  # Hydrocéphalie
        "dilatation ventriculaire", "ventriculomégalie",
        "hydrocéphalie obstructive", "hydrocéphalie communicante",
        "dilatation des ventricules cérébraux",
    ],
    "HP:0002240": [  # Hépatomégalie
        "gros foie", "foie augmenté de volume", "hépatomégalie massive",
        "hépatomégalie modérée", "hépatosplénomégalie",
    ],
    "HP:0000126": [  # Hydronéphrose
        "dilatation pyélocalicielle", "dilatation des cavités rénales",
        "pyélectasie", "dilatation pyélique",
        "uropathie obstructive",
    ],
    "HP:0008947": [  # Hypotonie musculaire infantile
        "hypotonie néonatale", "bébé mou", "floppy baby",
        "floppy infant", "hypotonie axiale",
        "hypotonie périphérique", "hypotonie généralisée",
    ],
    "HP:0001562": [  # Oligoamnios
        "oligohydramnios", "liquide amniotique diminué",
        "anamnios", "anhyamnios",
    ],
    "HP:0001789": [  # Anasarque foetal
        "hydrops fetalis", "hydrops fœtal", "anasarque fœtale",
        "anasarque foeto-placentaire", "hydrops non immun",
        "HFNI", "œdème fœtal généralisé",
    ],
    "HP:0001636": [  # Tétralogie de Fallot
        "Fallot", "T4F", "TOF",
        "cardiopathie conotroncale",
    ],
    "HP:0008678": [  # Hypoplasie/aplasie rénale
        "agénésie rénale", "rein absent", "rein unique",
        "agénésie rénale bilatérale", "agénésie rénale unilatérale",
        "hypoplasie rénale", "reins hypoplasiques",
        "petits reins",
    ],
    "HP:0001638": [  # Cardiomyopathie
        "cardiomyopathie dilatée", "cardiomyopathie restrictive",
        "CMD", "CMR",
    ],
    "HP:0000961": [  # Cyanose
        "cyanose néonatale", "cyanose centrale",
        "cyanose périphérique", "coloration bleutée",
    ],
    "HP:0007360": [  # Aplasie/hypoplasie du cervelet
        "hypoplasie cérébelleuse", "agénésie cérébelleuse",
        "cervelet hypoplasique", "cervelet petit",
        "hypoplasie vermienne", "agénésie du vermis",
        "hypoplasie du vermis cérébelleux",
    ],
    "HP:0002033": [  # Têtée inefficace
        "troubles de succion", "difficultés alimentaires néonatales",
        "succion faible", "troubles de la déglutition néonatale",
        "alimentation difficile",
    ],
    "HP:0000962": [  # Hyperkératose
        "ichtyose", "peau épaissie", "kératose",
        "kératose folliculaire", "collodion baby",
        "bébé collodion",
    ],
    "HP:0012758": [  # Retard de développement neurologique
        "retard neurologique", "retard neurodéveloppemental",
        "retard des acquisitions",
    ],
    "HP:0000023": [  # Hernie inguinale
        "hernie inguinale bilatérale", "hernie inguinale congénitale",
    ],
    "HP:0001513": [  # Obésité
        "obésité morbide", "surpoids", "obésité tronculaire",
    ],
    "HP:0003312": [  # Forme anormale des corps vertébraux
        "platyspondylie", "vertèbres plates", "anomalies vertébrales",
        "dysplasie vertébrale", "vertèbres en papillon",
        "hémivertèbre", "vertèbres dysmorphiques",
    ],
    "HP:0000337": [  # Front large
        "front bombé", "front proéminent", "bossage frontal",
        "front haut", "front haut et large",
    ],
    "HP:0000319": [  # Philtrum plat
        "philtrum lisse", "philtrum effacé", "philtrum absent",
    ],
    "HP:0000445": [  # Nez large
        "racine nasale large", "nez aplati", "nez épaté",
        "base du nez large", "arête nasale large",
    ],
    "HP:0000501": [  # Glaucome
        "glaucome congénital", "buphtalmie",
        "glaucome infantile",
    ],
    "HP:0000717": [  # Autisme
        "trouble du spectre autistique", "TSA",
        "traits autistiques", "autisme infantile",
    ],
    "HP:0000668": [  # Hypodontie
        "dents manquantes", "agénésie dentaire",
        "oligodontie", "anodontie",
    ],
    # --- Termes avec aliases incomplets à enrichir ---
    "HP:0000003": [  # Polykystose rénale — n'a que "Dysplasie rénale polykystique"
        "reins polykystiques", "reins kystiques",
        "kystes rénaux multiples", "néphromégalie kystique",
        "maladie polykystique rénale", "PKD",
    ],
    "HP:0001339": [  # Lissencéphalie — n'a que "agyrie"
        "surface cérébrale lisse", "pachygyrie",
        "lissencéphalie type I", "lissencéphalie type II",
        "lissencéphalie cobblestone", "anomalie de la giration",
    ],
    "HP:0002089": [  # Hypoplasie pulmonaire — n'a que "Hypoplasie"
        "poumons hypoplasiques", "poumons petits",
        "hypoplasie pulmonaire bilatérale", "immaturité pulmonaire",
    ],
    "HP:0001639": [  # CMH — aliases anglais seulement
        "cardiomyopathie hypertrophique obstructive",
        "CMH", "hypertrophie septale asymétrique",
        "HCM",
    ],
    "HP:0001511": [  # RCIU — alias existant mais incomplet
        "RCIU", "hypotrophie fœtale", "petit pour l'âge gestationnel",
        "PAG", "SGA", "retard de croissance",
    ],
    "HP:0000476": [  # Hygroma kystique — déjà bien fourni mais ajout
        "hygroma cervical bilatéral", "lymphocèle cervicale",
    ],
    "HP:0001561": [  # Hydramnios
        "excès de liquide amniotique",
    ],
    "HP:0000175": [  # Fente palatine
        "fente labiale", "bec de lièvre", "chéiloschisis",
        "palatoschisis", "fente labio-alvéolo-palatine",
        "FLAP", "fente sous-muqueuse",
    ],
    "HP:0001631": [  # CIA
        "CIA", "foramen ovale perméable", "FOP",
    ],
    "HP:0000957": [  # Taches café au lait
        "taches café au lait", "café au lait spots",
        "macules pigmentées", "taches cutanées pigmentées",
    ],
    "HP:0001249": [  # Déficience intellectuelle — déjà riche mais ajout
        "retard intellectuel", "handicap mental",
        "déficience cognitive", "DI",
    ],
    "HP:0001250": [  # Épilepsie — déjà riche mais ajout spécifique
        "crises épileptiques", "crises convulsives",
        "épilepsie néonatale", "syndrome de West",
        "encéphalopathie épileptique",
    ],
    # --- Termes spécifiques fœtopathologie ---
    "HP:0000028": [  # Cryptorchidie
        "testicules non descendus", "ectopie testiculaire",
        "cryptorchidie bilatérale", "cryptorchidie unilatérale",
    ],
    "HP:0001762": [  # Pied bot
        "pied bot varus équin", "PBVE",
        "talipes equinovarus", "pieds bots",
        "pieds bots bilatéraux",
    ],
    "HP:0002751": [  # Cyphoscoliose
        "cyphose", "scoliose congénitale",
        "déformation rachidienne",
    ],
    "HP:0100790": [  # Hernie
        "hernie ombilicale", "omphalocèle",
        "laparoschisis", "gastroschisis",
        "hernie diaphragmatique", "hernie de coupole",
    ],
    "HP:0003298": [  # Spina bifida occulta
        "spina bifida", "dysraphisme spinal",
        "myéloméningocèle", "méningocèle",
        "défaut de fermeture du tube neural", "DFTN",
    ],
    "HP:0002421": [  # Mauvais contrôle de la tête
        "tenue de tête absente", "hypotonie cervicale",
        "contrôle céphalique retardé",
    ],
    "HP:0012448": [  # Myélination retardée
        "retard de myélinisation", "leucodystrophie",
        "anomalies de la substance blanche",
        "hypomyélinisation",
    ],
    "HP:0000963": [  # Peau fine
        "peau translucide", "peau fragile",
        "fragilité cutanée",
    ],
    "HP:0003272": [  # Anomalie osseuse de la hanche
        "luxation congénitale de hanche", "dysplasie de hanche",
        "LCH", "hanche luxable",
    ],
}


def main():
    shutil.copy(DB_PATH, str(DB_PATH) + ".bak_pre_aliases_enrichment")
    print(f"Backup: {DB_PATH}.bak_pre_aliases_enrichment")

    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row

    stats = {"updated": 0, "skipped_not_found": 0, "aliases_added": 0}

    for hpo_id, new_aliases in ALIASES_TO_ADD.items():
        row = conn.execute(
            "SELECT hpo_id, label_fr, aliases_fr FROM hpo_terms WHERE hpo_id=?",
            (hpo_id,),
        ).fetchone()
        if not row:
            print(f"  NOT FOUND: {hpo_id}")
            stats["skipped_not_found"] += 1
            continue

        existing = row["aliases_fr"] or ""
        existing_lower = existing.lower()

        to_add = []
        for alias in new_aliases:
            if alias.lower() not in existing_lower and alias.lower() != (row["label_fr"] or "").lower():
                to_add.append(alias)

        if not to_add:
            continue

        if existing:
            updated = existing + " | " + " | ".join(to_add)
        else:
            updated = " | ".join(to_add)

        conn.execute(
            "UPDATE hpo_terms SET aliases_fr=? WHERE hpo_id=?",
            (updated, hpo_id),
        )
        stats["updated"] += 1
        stats["aliases_added"] += len(to_add)
        print(f"  {hpo_id} ({row['label_fr']}): +{len(to_add)} aliases")

    conn.commit()
    conn.close()

    print(f"\n=== Enrichissement aliases HPO terminé ===")
    for k, v in stats.items():
        print(f"  {k}: {v}")


if __name__ == "__main__":
    main()
