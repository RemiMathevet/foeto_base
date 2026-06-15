#!/usr/bin/env python3
"""Enrichissement syndromes chromosomiques rares de syndromes_foetaux.db.

Les 5 cas chromosomiques rares du benchmark (031-035) sont TOUS 0/5.
Le modèle connaît les syndromes mais ne les propose pas car :
  1. Les discriminateurs sont des listes HPO, pas des indices cliniques
  2. Le modèle dérive vers des syndromes monogéniques aux signes proches
  3. Il manque des syndromes courants (Cri du Chat, 22q11, Angelman...)

Stratégie : enrichir les discriminateurs avec des critères cliniques
orientés "quand penser chromosomique ?" + ajouter les syndromes
chromosomiques courants en fœtopathologie qui manqueraient.
"""

import sqlite3
from pathlib import Path

DB_PATH = Path("/home/mathevet/Bureau/foeto_base/syndromes_foetaux.db")

# ============================================================
# 1. DISCRIMINATEURS CLINIQUES — syndromes existants
# ============================================================

DISCRIMINATORS = {
    # --- Cas 031 : Miller-Dieker ---
    "ORPHA:531": (
        "MILLER-DIEKER (microdélétion 17p13.3): Lissencéphalie classique (type I, "
        "agyrie complète) + dysmorphie faciale SPÉCIFIQUE (front haut et étroit, "
        "tempes creuses, lèvre supérieure proéminente en chapeau de gendarme, "
        "nez court retroussé, microrétrognathie). "
        "ANOMALIE CHROMOSOMIQUE: délétion 17p13.3 incluant LIS1 + YWHAE. "
        "DISCRIMINANT vs lissencéphalie isolée (LIS1 seul): Miller-Dieker = "
        "TOUJOURS dysmorphie faciale caractéristique + lissencéphalie sévère grade 1. "
        "Mutation ponctuelle LIS1 = lissencéphalie postérieure + PAS de dysmorphie. "
        "DISCRIMINANT vs Norman-Roberts: NR = microcéphalie + lissencéphalie mais "
        "dysmorphie DIFFÉRENTE (front fuyant). Miller-Dieker = front haut+étroit. "
        "QUAND PENSER CHROMOSOMIQUE: lissencéphalie complète + dysmorphie = "
        "FISH/CGH array 17p13.3 en priorité."
    ),
    # --- Cas 032 : Tétrasomie 18p ---
    "ORPHA:3307": (
        "TÉTRASOMIE 18p (isochromosome 18p): Dysmorphie faciale modérée "
        "(microcéphalie, visage allongé, strabisme, oreilles basses), "
        "retard psychomoteur modéré à sévère, anomalies de la migration neuronale, "
        "hypotonie néonatale, anomalies vertébrales. "
        "Isochromosome surnuméraire = mosaïque fréquente. "
        "DISCRIMINANT vs délétion 1p36: tétrasomie 18p = anomalies migration neuronale "
        "fréquentes, philtrum long. 1p36 = hypotonie sévère + épilepsie + "
        "fontanelle large + cardiomyopathie. "
        "DISCRIMINANT vs trisomie 18: tétrasomie 18p = PAS de chevauchement doigts, "
        "PAS de pieds en piolet. Morphologie faciale différente. "
        "QUAND PENSER CHROMOSOMIQUE: retard + dysmorphie + anomalies migration "
        "neuronale sans étiologie monogénique évidente = CGH array."
    ),
    # --- Cas 033 : Jacobsen ---
    "ORPHA:2308": (
        "JACOBSEN (délétion 11q23-qter): Thrombopénie/pancytopénie (Paris-Trousseau), "
        "dysmorphie faciale (trigonocéphalie, ptosis, hypertélorisme, nez en V, "
        "bouche en carpe), cardiopathie congénitale (70%, défaut septal, "
        "cœur gauche hypoplasique), retard de croissance. "
        "ANOMALIE CHROMOSOMIQUE: délétion terminale 11q. "
        "DISCRIMINANT vs syndromes monogéniques: Jacobsen = thrombopénie "
        "de Paris-Trousseau (macro-thrombocytes avec granules α géants) = "
        "PATHOGNOMONIQUE. Trigonocéphalie + thrombopénie = Jacobsen. "
        "DISCRIMINANT vs Robinow: Jacobsen = thrombopénie + cardiopathie "
        "(Robinow = PAS de thrombopénie, brachydactylie, micropénis)."
    ),
    # --- Cas 034 : Potocki-Lupski ---
    "ORPHA:1713": (
        "POTOCKI-LUPSKI (microduplication 17p11.2): Hypotonie infantile, "
        "retard de langage, troubles du spectre autistique, "
        "difficultés alimentaires, apnées du sommeil, "
        "cardiopathie congénitale (variable), retard de croissance. "
        "RÉCIPROQUE de Smith-Magenis (délétion 17p11.2). "
        "ANOMALIE CHROMOSOMIQUE: duplication 17p11.2. "
        "DISCRIMINANT vs Smith-Magenis: Potocki-Lupski = hypotonie + autisme "
        "(Smith-Magenis = troubles du comportement + auto-mutilation + "
        "inversion du rythme circadien). "
        "DISCRIMINANT vs délétion 8p: Potocki-Lupski = PAS de cardiopathie "
        "conotroncale, PAS d'hypospadias."
    ),
    # --- Cas 035 : Warkany (trisomie 8 mosaïque) ---
    "ORPHA:96061": (
        "WARKANY (trisomie 8 mosaïque): Sillons palmaires et plantaires profonds "
        "(PATHOGNOMONIQUE), dysmorphie faciale (front proéminent, nez large, "
        "lèvre inférieure éversée), contractures articulaires, "
        "anomalies vertébrales/costales, agénésie du corps calleux (fréquente), "
        "intelligence limite. Trisomie 8 en MOSAÏQUE (non-mosaïque = létal). "
        "DISCRIMINANT: sillons palmaires/plantaires profonds = trisomie 8 "
        "jusqu'à preuve du contraire. Aucun autre syndrome n'a ce signe. "
        "DISCRIMINANT vs OFD4: Warkany = sillons plantaires profonds + "
        "anomalies vertébrales (OFD4 = fentes buccales + polydactylie + tibias courts)."
    ),
    # --- Autres chromosomiques courants à enrichir ---
    "ORPHA:280": (
        "WOLF-HIRSCHHORN (délétion 4p): Dysmorphie en casque de guerrier grec "
        "(PATHOGNOMONIQUE: glabelle proéminente, front haut, hypertélorisme, "
        "nez large avec racine haute, micro/rétrognathie). "
        "RCIU sévère, épilepsie précoce, fente labiopalatine (30%), "
        "cardiopathie (50%), colobome (25%). "
        "DISCRIMINANT: faciès en casque de guerrier = Wolf-Hirschhorn. "
        "Aucun syndrome monogénique ne reproduit cette dysmorphie."
    ),
    "ORPHA:1606": (
        "DÉLÉTION 1p36: Hypotonie sévère néonatale, fontanelle antérieure large, "
        "épilepsie précoce (souvent infantile), cardiomyopathie dilatée (30%), "
        "hypothyroïdie, surdité, dysmorphie (sourcils droits, yeux enfoncés, "
        "menton pointu). "
        "DISCRIMINANT: hypotonie sévère + fontanelle large + épilepsie + "
        "cardiomyopathie = penser 1p36. "
        "DISCRIMINANT vs Prader-Willi: 1p36 = épilepsie précoce + cardiomyopathie "
        "(Prader-Willi = PAS d'épilepsie, PAS de cardiomyopathie, cryptorchidie)."
    ),
    "ORPHA:884": (
        "PALLISTER-KILLIAN (tétrasomie 12p en mosaïque): Dysmorphie faciale "
        "caractéristique (front haut avec alopécie temporale bitemporale, "
        "hypertélorisme, lèvre supérieure fine, lèvre inférieure épaisse). "
        "Hernie diaphragmatique (30%), polydactylie postaxiale, "
        "taches cutanées hypo/hyperpigmentées en stries, "
        "retard sévère. Caryotype sur fibroblastes (PAS sur sang). "
        "DISCRIMINANT: alopécie bitemporale + taches pigmentaires en stries = "
        "Pallister-Killian. Caryotype sanguin souvent NORMAL (mosaïque tissulaire)."
    ),
    "ORPHA:904": (
        "WILLIAMS (microdélétion 7q11.23): Faciès elfique (périorbitaire plein, "
        "nez court retroussé, lèvres épaisses, bouche large, joues pleines), "
        "sténose aortique supravalvulaire (75%), hypercalcémie néonatale, "
        "personnalité hypersociable, retard psychomoteur modéré. Gène ELN + . "
        "DISCRIMINANT: sténose aortique supravalvulaire = Williams en priorité. "
        "DISCRIMINANT en prénatal: cardiopathie conotroncale + RCIU = penser Williams."
    ),
    "ORPHA:739": (
        "PRADER-WILLI (délétion 15q11-q13 paternelle): En prénatal/néonatal: "
        "hydramnios, mouvements fœtaux diminués, hypotonie néonatale SÉVÈRE "
        "(floppy infant), troubles de succion majeurs, cryptorchidie bilatérale, "
        "hypoplasie génitale. PAS d'épilepsie néonatale, PAS de cardiopathie. "
        "DISCRIMINANT: hypotonie néonatale sévère + troubles de succion + "
        "cryptorchidie + PAS d'épilepsie = Prader-Willi. "
        "Test de méthylation 15q11 = diagnostic."
    ),
}

# ============================================================
# 2. SYNDROMES CHROMOSOMIQUES COURANTS MANQUANTS
# ============================================================

NEW_SYNDROMES = {}

# Vérifier si Cri du Chat, Angelman, 22q11, Smith-Magenis sont dans la DB
SYNDROMES_TO_CHECK = {
    "ORPHA:281": "Cri du Chat",
    "ORPHA:72": "Angelman",
    "ORPHA:567": "DiGeorge/22q11",
    "ORPHA:819": "Smith-Magenis",
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
        "missing_in_db": [],
    }

    # --- Check which common chromo syndromes are missing ---
    for sid, name in SYNDROMES_TO_CHECK.items():
        row = conn.execute("SELECT id, name_fr FROM syndromes WHERE id=?", (sid,)).fetchone()
        if row:
            print(f"  OK: {sid} — {row['name_fr']}")
        else:
            print(f"  MISSING: {sid} — {name}")
            stats["missing_in_db"].append(f"{sid} ({name})")

    # --- Enrichir les discriminateurs ---
    for sid, disc_text in DISCRIMINATORS.items():
        row = conn.execute(
            "SELECT id, key_discriminators FROM syndromes WHERE id=?", (sid,)
        ).fetchone()
        if not row:
            print(f"  WARN: {sid} not in DB, skipping")
            continue

        old = row["key_discriminators"] or ""
        if "QUAND PENSER CHROMOSOMIQUE" in old or "ANOMALIE CHROMOSOMIQUE" in old:
            print(f"  SKIP disc: {sid} already has chromosomal discriminators")
            continue

        if old:
            new_disc = old + " | CHROMO_RARE: " + disc_text
        else:
            new_disc = disc_text

        conn.execute(
            "UPDATE syndromes SET key_discriminators=?, updated_at=datetime('now') WHERE id=?",
            (new_disc, sid),
        )
        stats["discriminators_updated"] += 1

    # --- Syndromes chromosomiques supplémentaires courants ---
    # Ajouter des discriminateurs aux syndromes courants qui existent déjà
    EXTRA_DISC = {}

    # Cri du Chat
    cri = conn.execute("SELECT id FROM syndromes WHERE name_fr LIKE '%Cri du chat%' OR name_fr LIKE '%cri-du-chat%' OR name_fr LIKE '%5p-%'").fetchone()
    if cri:
        EXTRA_DISC[cri["id"]] = (
            "CRI DU CHAT (délétion 5p): Cri aigu caractéristique du nouveau-né "
            "(PATHOGNOMONIQUE, aigu comme un miaulement de chat), "
            "microcéphalie, faciès rond avec hypertélorisme, "
            "retard psychomoteur sévère, hypotonie. "
            "DISCRIMINANT: cri aigu néonatal = Cri du Chat jusqu'à preuve du contraire."
        )

    # Angelman
    ang = conn.execute("SELECT id FROM syndromes WHERE name_fr LIKE '%Angelman%'").fetchone()
    if ang:
        EXTRA_DISC[ang["id"]] = (
            "ANGELMAN (délétion 15q11-q13 maternelle): Rire inapproprié et fréquent "
            "(happy puppet), ataxie, épilepsie, microcéphalie progressive, "
            "fascination pour l'eau, retard sévère avec ABSENCE de langage. "
            "DISCRIMINANT vs Prader-Willi: MÊME locus 15q11 mais empreinte opposée. "
            "Angelman = rire + ataxie + épilepsie. Prader-Willi = hypotonie + obésité."
        )

    # DiGeorge / 22q11
    dg = conn.execute("SELECT id FROM syndromes WHERE name_fr LIKE '%22q11%' OR name_fr LIKE '%DiGeorge%' OR name_fr LIKE '%vélocardiofacial%'").fetchone()
    if dg:
        EXTRA_DISC[dg["id"]] = (
            "DÉLÉTION 22q11.2 (DiGeorge/vélocardiofacial): Cardiopathie conotroncale "
            "(tétralogie de Fallot, interruption arc aortique, truncus arteriosus), "
            "fente palatine/insuffisance vélopharyngée, hypoplasie thymique (immunodéficit), "
            "hypocalcémie néonatale, dysmorphie (nez tubulaire, philtrum court, "
            "oreilles petites postéro-rotées). "
            "DISCRIMINANT: cardiopathie conotroncale + hypocalcémie + "
            "hypoplasie thymique = 22q11 en priorité. "
            "Anomalie chromosomique LA PLUS FRÉQUENTE après trisomies (1/4000)."
        )

    # Smith-Magenis
    sm = conn.execute("SELECT id FROM syndromes WHERE name_fr LIKE '%Smith-Magenis%'").fetchone()
    if sm:
        EXTRA_DISC[sm["id"]] = (
            "SMITH-MAGENIS (délétion 17p11.2): Troubles du comportement sévères "
            "(auto-mutilation, auto-étreinte = self-hugging), "
            "inversion du rythme circadien (élévation diurne mélatonine), "
            "brachycéphalie, face plate, retard modéré. Gène RAI1. "
            "RÉCIPROQUE de Potocki-Lupski (duplication 17p11.2). "
            "DISCRIMINANT: auto-étreinte (self-hug) + inversion circadienne = Smith-Magenis."
        )

    for sid, disc_text in EXTRA_DISC.items():
        old = conn.execute(
            "SELECT key_discriminators FROM syndromes WHERE id=?", (sid,)
        ).fetchone()
        old_val = old["key_discriminators"] or "" if old else ""
        if "CHROMO_RARE" in old_val or "PATHOGNOMONIQUE" in old_val:
            print(f"  SKIP extra disc: {sid}")
            continue
        if old_val:
            new_disc = old_val + " | CHROMO_RARE: " + disc_text
        else:
            new_disc = disc_text
        conn.execute(
            "UPDATE syndromes SET key_discriminators=?, updated_at=datetime('now') WHERE id=?",
            (new_disc, sid),
        )
        stats["discriminators_updated"] += 1

    conn.commit()
    conn.close()

    print(f"\n=== Import master chromosomiques rares terminé ===")
    for k, v in stats.items():
        print(f"  {k}: {v}")
    if stats["missing_in_db"]:
        print(f"\n  ⚠ Syndromes manquants: {', '.join(stats['missing_in_db'])}")


if __name__ == "__main__":
    main()
