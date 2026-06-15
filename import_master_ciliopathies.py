#!/usr/bin/env python3
"""Enrichissement ciliopathies de syndromes_foetaux.db.

Source : connaissances cliniques fœtopathologie + littérature ciliopathies.
Cible les confusions du benchmark v2 (cas 056-067, 6/12 = 50%) :
  - BBS → Meckel (manque discriminateurs)
  - Senior-Løken → ARPKD (SLS absent de la DB)
  - Néphronophtise → ARPKD (confusion rénale)
  - OFD type IV → OFD type 1 (manque discriminateurs sous-types)
  - Kartagener → situs inversus isolé (Kartagener absent de la DB)
"""

import sqlite3
from pathlib import Path

DB_PATH = Path("/home/mathevet/Bureau/foeto_base/syndromes_foetaux.db")


# ============================================================
# 1. SYNDROMES À CRÉER
# ============================================================

NEW_SYNDROMES = {
    "ORPHA:3156": {
        "name_fr": "Syndrome de Senior-Løken",
        "category": "ciliopathie",
        "omim": "266900",
    },
    "ORPHA:98473": {
        "name_fr": "Polykystose rénale autosomique récessive (ARPKD)",
        "category": "ciliopathie",
        "omim": "263200",
    },
    "ORPHA:1454_COACH": {
        # COACH = Joubert + fibrose hépatique, ORPHA:1454 existe déjà
        # (Joubert avec atteinte hépatique) — skip if exists
        "name_fr": "Syndrome COACH (Joubert + fibrose hépatique congénitale)",
        "category": "ciliopathie",
        "omim": "216360",
        "use_existing": "ORPHA:1454",
    },
    "ORPHA:2697_MS": {
        "name_fr": "Syndrome de Mainzer-Saldino (néphronophtise + rétinite pigmentaire + phalanges en cône)",
        "category": "ciliopathie",
        "omim": "266920",
        "use_existing": None,
    },
    "ORPHA:98861": {
        "name_fr": "Syndrome de Kartagener (dyskinésie ciliaire primitive avec situs inversus)",
        "category": "ciliopathie",
        "omim": "244400",
    },
}

# ============================================================
# 2. DISCRIMINATEURS CLINIQUES
# ============================================================

DISCRIMINATORS = {
    # --- Meckel vs BBS vs Joubert ---
    "ORPHA:564": (
        "MECKEL-GRUBER: Triade classique = encéphalocèle occipitale + polykystose "
        "rénale bilatérale + polydactylie postaxiale. Fibrose hépatique (ductal plate "
        "malformation). LÉTAL (incompatible avec la vie). Gènes MKS1-13 (CC2D2A, TMEM67...). "
        "DISCRIMINANT vs BBS: Meckel = LÉTAL + encéphalocèle (jamais dans BBS). "
        "BBS = VIABLE + obésité + anomalies génitales + rétinite pigmentaire. "
        "DISCRIMINANT vs Joubert: Meckel = encéphalocèle (Joubert = signe de la dent "
        "molaire au TDM/IRM sans encéphalocèle). Meckel est le phénotype sévère du "
        "spectre ciliopathie, Joubert le modéré."
    ),
    "ORPHA:110": (
        "BARDET-BIEDL: Hexadactylie postaxiale + obésité tronculaire + "
        "rétinite pigmentaire (dystrophie rétinienne) + anomalies rénales "
        "(néphronophtise, rarement kystique) + anomalies génitales (hypogonadisme, "
        "hypospadias, cryptorchidie) + retard cognitif variable. VIABLE. Gènes BBS1-21. "
        "DISCRIMINANT vs Meckel: BBS = VIABLE, PAS d'encéphalocèle, obésité ++ "
        "(absente Meckel). En prénatal: polydactylie + reins hyperéchogènes + "
        "anomalies génitales = BBS. Polydactylie + gros reins kystiques + "
        "encéphalocèle = Meckel. "
        "DISCRIMINANT vs Joubert: BBS = PAS de signe de la dent molaire, "
        "obésité + rétinite + anomalies génitales."
    ),
    "ORPHA:475": (
        "JOUBERT ISOLÉ: Signe de la dent molaire (molar tooth sign) à l'IRM/écho "
        "= hypoplasie vermis cérébelleux + pédoncules cérébelleux supérieurs épaissis. "
        "Hypotonie néonatale, apnées/tachypnées néonatales, ataxie cérébelleuse, "
        "apraxie oculomotrice. PAS d'atteinte rénale ni hépatique dans la forme isolée. "
        "Gènes >40 (JBTS1-35: CC2D2A, TMEM67, CEP290, AHI1...). "
        "DISCRIMINANT vs Meckel: Joubert = VIABLE, PAS d'encéphalocèle, "
        "signe de la dent molaire (pas de MTS dans Meckel). "
        "DISCRIMINANT vs BBS: Joubert = PAS d'obésité, PAS de rétinite pigmentaire "
        "(sauf sous-types oculorénaux)."
    ),
    # --- Sous-types Joubert ---
    "ORPHA:1454": (
        "JOUBERT + ATTEINTE HÉPATIQUE (COACH): Signe de la dent molaire + "
        "fibrose hépatique congénitale (ductal plate malformation) + "
        "colobome choroïdien. Cholestase néonatale possible. "
        "Gènes: TMEM67, CC2D2A, RPGRIP1L. "
        "DISCRIMINANT vs Joubert isolé: COACH = atteinte hépatique + colobome. "
        "DISCRIMINANT vs Meckel: COACH = VIABLE, pas d'encéphalocèle."
    ),
    "ORPHA:2318": (
        "JOUBERT OCULORÉNAL: Signe de la dent molaire + néphronophtise + "
        "dystrophie rétinienne (= Senior-Løken + MTS). "
        "C'est le chevauchement Joubert/Senior-Løken. Gène CEP290 fréquent. "
        "DISCRIMINANT vs Senior-Løken: présence du signe de la dent molaire."
    ),
    "ORPHA:220497": (
        "JOUBERT + ATTEINTE RÉNALE: Signe de la dent molaire + "
        "néphronophtise ou reins kystiques. PAS de dystrophie rétinienne. "
        "DISCRIMINANT vs Joubert oculorénal: pas d'atteinte rétinienne."
    ),
    # --- Senior-Løken / NPHP / ARPKD ---
    "ORPHA:3156": (
        "SENIOR-LØKEN: Néphronophtise + dystrophie rétinienne (rétinite pigmentaire). "
        "Ciliopathie rénale + oculaire SANS anomalie du SNC (pas de MTS). "
        "Gènes NPHP1-16 (CEP290, IQCB1, SDCCAG8...). "
        "DISCRIMINANT vs NPHP isolée: SLS = rétinite pigmentaire (absente NPHP isolée). "
        "DISCRIMINANT vs Joubert oculorénal: SLS = PAS de signe de la dent molaire. "
        "DISCRIMINANT vs ARPKD: SLS = reins petits hyperéchogènes (ARPKD = gros reins "
        "avec kystes médullaires). Rétinite pigmentaire absente dans ARPKD."
    ),
    "ORPHA:93591": (
        "NÉPHRONOPHTISE INFANTILE: Reins petits hyperéchogènes (perte différenciation "
        "cortico-médullaire), PAS de gros kystes. Fibrose tubulo-interstitielle. "
        "Polyurie-polydipsie. Progression vers insuffisance rénale terminale. "
        "Gènes NPHP1-20 (NPHP1 = délétion homozygote fréquente). "
        "DISCRIMINANT vs ARPKD: NPHP = reins PETITS et hyperéchogènes "
        "(ARPKD = reins GROS avec microkystes). "
        "DISCRIMINANT vs Senior-Løken: NPHP isolée = PAS de rétinite pigmentaire."
    ),
    "ORPHA:98473": (
        "ARPKD: Gros reins bilatéraux avec microkystes des tubes collecteurs "
        "(aspect hyperéchogène en fuseau), oligoamnios (si sévère), "
        "fibrose hépatique congénitale constante (sévérité variable), "
        "hypertension artérielle. Gène PKHD1. "
        "DISCRIMINANT vs NPHP: ARPKD = GROS reins (NPHP = petits reins). "
        "ARPKD = microkystes des tubes collecteurs (NPHP = fibrose interstitielle). "
        "DISCRIMINANT vs Meckel: ARPKD = PAS de polydactylie, PAS d'encéphalocèle, "
        "PAS de malformation cérébrale. Reins SEULS (+ foie)."
    ),
    # --- Mainzer-Saldino ---
    "ORPHA:2697_MS": (
        "MAINZER-SALDINO: Néphronophtise + dystrophie rétinienne + "
        "phalanges en cône (cone-shaped epiphyses) + ataxie cérébelleuse. "
        "C'est une ciliopathie du spectre Joubert/SLS avec atteinte osseuse. "
        "Gènes: IFT172, IFT140, WDR19. "
        "DISCRIMINANT vs Senior-Løken: Mainzer-Saldino = phalanges en cône "
        "(anomalie osseuse spécifique absente SLS). "
        "DISCRIMINANT vs Joubert: atteinte osseuse spécifique."
    ),
    # --- Kartagener / DCP ---
    "ORPHA:244": (
        "DYSKINÉSIE CILIAIRE PRIMITIVE: Infections respiratoires récurrentes "
        "(bronchectasies), sinusite chronique, otite moyenne chronique, "
        "infertilité masculine. Situs inversus dans 50% des cas (= Kartagener). "
        "Gènes >50 (DNAI1, DNAH5, CCDC39...). "
        "DISCRIMINANT vs situs inversus isolé: DCP = infections respiratoires "
        "récurrentes + bronchectasies. Situs inversus isolé = asymptomatique."
    ),
    "ORPHA:98861": (
        "KARTAGENER: Sous-type de dyskinésie ciliaire primitive AVEC situs inversus totalis. "
        "Triade: situs inversus + bronchectasies + sinusite chronique. "
        "DISCRIMINANT vs situs inversus isolé: Kartagener = infections respiratoires "
        "chroniques. Situs inversus isolé = pas d'infections."
    ),
    # --- OFD sous-types ---
    "ORPHA:2750": (
        "OFD TYPE 1: Dominant X-lié (létal chez le garçon), FILLES UNIQUEMENT. "
        "Fentes linguales/labiales, hamartomes buccaux, brachydactylie avec "
        "clinodactylie, polykystose rénale (tardive), alopécie. Gène OFD1. "
        "DISCRIMINANT vs OFD IV: OFD1 = X-lié (filles seules), "
        "alopécie, PAS de tibias courts. "
        "DISCRIMINANT vs Meckel: OFD1 = VIABLE, atteinte buccale prédominante."
    ),
    "ORPHA:2753": (
        "OFD TYPE IV (Mohr-Majewski): Autosomique récessif, garçons ET filles. "
        "Fentes linguales, polydactylie préaxiale ET postaxiale, "
        "tibias courts, malformations cérébrales (agénésie vermis, "
        "anomalies fosse postérieure). Plus sévère que OFD1. "
        "DISCRIMINANT vs OFD1: OFD4 = garçons atteints, tibias courts, "
        "polydactylie préaxiale (OFD1 = que postaxiale). "
        "DISCRIMINANT vs Joubert: OFD4 = fentes buccales + tibias courts."
    ),
    # --- Alström ---
    "ORPHA:64": (
        "ALSTRÖM: Dystrophie rétinienne précoce (cone-rod), "
        "cardiomyopathie dilatée infantile, obésité tronculaire, "
        "résistance à l'insuline/diabète type 2, surdité neurosensorielle, "
        "atteinte rénale progressive. PAS de polydactylie, PAS de retard cognitif. "
        "Gène ALMS1. "
        "DISCRIMINANT vs BBS: Alström = PAS de polydactylie, PAS de retard cognitif, "
        "cardiomyopathie (rare dans BBS). BBS = polydactylie + retard."
    ),
    # --- Jeune (dysplasie thoracique asphyxiante) ---
    "ORPHA:474": (
        "JEUNE (dysplasie thoracique asphyxiante): Thorax étroit long, "
        "côtes courtes, polydactylie postaxiale (variable, ~20%), "
        "atteinte rénale progressive (néphronophtise/kystique), "
        "dystrophie rétinienne possible, fibrose hépatique. Gènes IFT80, DYNC2H1, WDR19. "
        "DISCRIMINANT vs SRPS: Jeune = VIABLE (SRPS = souvent létal). "
        "Jeune a thorax étroit mais moins sévère que SRPS. "
        "DISCRIMINANT vs Ellis-van Creveld: Jeune = PAS de malformation cardiaque "
        "(EVC = canal atrioventriculaire), PAS d'anomalies unguéales/dentaires."
    ),
}

# ============================================================
# 3. HPO POUR NOUVEAUX SYNDROMES
# ============================================================

SYNDROME_HPO = {
    # Senior-Løken
    "ORPHA:3156": [
        ("HP:0000090", 0.95, "Néphronophtise"),
        ("HP:0000510", 0.90, "Dystrophie rétinienne"),
        ("HP:0000580", 0.85, "Rétinite pigmentaire"),
        ("HP:0000083", 0.90, "Insuffisance rénale"),
        ("HP:0000089", 0.60, "Anomalie rénale tubulo-interstitielle"),
        ("HP:0004727", 0.40, "Reins petits hyperéchogènes"),
        ("HP:0000556", 0.70, "Dystrophie rétinienne"),
        ("HP:0000505", 0.50, "Cécité"),
        ("HP:0001263", 0.30, "Retard global de développement"),
    ],
    # ARPKD
    "ORPHA:98473": [
        ("HP:0000107", 0.95, "Reins kystiques"),
        ("HP:0000113", 0.95, "Polykystose rénale"),
        ("HP:0000105", 0.95, "Gros reins bilatéraux"),
        ("HP:0001407", 0.90, "Fibrose hépatique"),
        ("HP:0001409", 0.60, "Dilatation des voies biliaires intrahépatiques"),
        ("HP:0000822", 0.50, "Hypertension artérielle"),
        ("HP:0000083", 0.70, "Insuffisance rénale"),
        ("HP:0001562", 0.40, "Oligoamnios"),
        ("HP:0002089", 0.30, "Hypoplasie pulmonaire"),
        ("HP:0001789", 0.10, "Anasarque foetal"),
    ],
    # Mainzer-Saldino
    "ORPHA:2697_MS": [
        ("HP:0000090", 0.90, "Néphronophtise"),
        ("HP:0000580", 0.85, "Rétinite pigmentaire"),
        ("HP:0010230", 0.80, "Phalanges en cône"),
        ("HP:0001260", 0.60, "Ataxie cérébelleuse"),
        ("HP:0000083", 0.70, "Insuffisance rénale"),
        ("HP:0001263", 0.40, "Retard global de développement"),
    ],
    # Kartagener
    "ORPHA:98861": [
        ("HP:0011400", 0.99, "Situs inversus totalis"),
        ("HP:0002110", 0.90, "Bronchectasie"),
        ("HP:0011109", 0.85, "Sinusite chronique"),
        ("HP:0000388", 0.80, "Otite moyenne chronique"),
        ("HP:0000789", 0.70, "Infertilité"),
        ("HP:0002643", 0.60, "Dextrocardie"),
        ("HP:0002205", 0.80, "Infections respiratoires récurrentes"),
        ("HP:0012236", 0.50, "Toux chronique productive"),
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
        actual_id = info.get("use_existing", sid)
        if actual_id and actual_id != sid:
            existing = conn.execute("SELECT id FROM syndromes WHERE id=?", (actual_id,)).fetchone()
            if existing:
                print(f"  USE EXISTING: {actual_id} for {info['name_fr']}")
                continue

        existing = conn.execute("SELECT id FROM syndromes WHERE id=?", (sid,)).fetchone()
        if existing:
            print(f"  SKIP: {sid} already in DB")
            continue
        conn.execute(
            """INSERT INTO syndromes (id, name_fr, category, omim, relevance)
               VALUES (?, ?, ?, ?, ?)""",
            (sid, info["name_fr"], info["category"], info.get("omim"), "high"),
        )
        print(f"  NEW: {sid} — {info['name_fr']}")
        stats["new_syndromes"] += 1

    # --- Étape 2 : Discriminateurs ---
    for sid, disc_text in DISCRIMINATORS.items():
        row = conn.execute(
            "SELECT id, key_discriminators FROM syndromes WHERE id=?", (sid,)
        ).fetchone()
        if not row:
            print(f"  WARN: {sid} not in DB, skipping discriminator")
            continue

        old = row["key_discriminators"] or ""
        if "CILIOPATHIE" in old or "DISCRIMINANT vs" in old:
            if "DISCRIMINANT vs BBS" in old or "DISCRIMINANT vs Meckel" in old:
                print(f"  SKIP disc: {sid} already has ciliopathy discriminators")
                continue

        if old:
            new_disc = old + " | CILIOPATHIE: " + disc_text
        else:
            new_disc = disc_text

        conn.execute(
            "UPDATE syndromes SET key_discriminators=?, updated_at=datetime('now') WHERE id=?",
            (new_disc, sid),
        )
        stats["discriminators_updated"] += 1

    # --- Étape 3 : HPO ---
    for sid, hpo_list in SYNDROME_HPO.items():
        syndrome_exists = conn.execute(
            "SELECT id FROM syndromes WHERE id=?", (sid,)
        ).fetchone()
        if not syndrome_exists:
            print(f"  WARN: {sid} not in DB, skipping HPO")
            continue

        for hpo_id, penetrance, label_fr in hpo_list:
            existing_hpo = conn.execute(
                "SELECT hpo_id FROM hpo_terms WHERE hpo_id=?", (hpo_id,)
            ).fetchone()
            if not existing_hpo:
                conn.execute(
                    "INSERT INTO hpo_terms (hpo_id, label_fr, label_en, context) VALUES (?, ?, ?, ?)",
                    (hpo_id, label_fr, label_fr, "both"),
                )
                stats["new_hpo_terms"] += 1

            existing_link = conn.execute(
                "SELECT prob FROM syndrome_hpo WHERE syndrome_id=? AND hpo_id=?",
                (sid, hpo_id),
            ).fetchone()

            if existing_link:
                if penetrance > (existing_link["prob"] or 0):
                    conn.execute(
                        "UPDATE syndrome_hpo SET prob=?, frequency=?, source=? "
                        "WHERE syndrome_id=? AND hpo_id=?",
                        (penetrance, freq_label(penetrance), "ciliopathie_master",
                         sid, hpo_id),
                    )
                    stats["hpo_updated"] += 1
            else:
                conn.execute(
                    "INSERT INTO syndrome_hpo (syndrome_id, hpo_id, prob, frequency, source) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (sid, hpo_id, penetrance, freq_label(penetrance), "ciliopathie_master"),
                )
                stats["hpo_inserted"] += 1

    conn.commit()
    conn.close()

    print(f"\n=== Import master ciliopathies terminé ===")
    for k, v in stats.items():
        print(f"  {k}: {v}")


if __name__ == "__main__":
    main()
