#!/usr/bin/env python3
"""Entites « hpoa » : les vrais trous OMIM de nos livres, alimentes par phenotype.hpoa.

omim_sans_fiche_foetal.tsv (335) liste les phenotypes OMIM a profil foetal net
sans entree de livre. Deux cas :
  - sous-type d'une famille deja attestee (SRTD 20, OFD XVII…) : le parent porte
    les signes, on n'en fait rien ici (liste dans hpoa_sous_types.tsv) ;
  - vrai trou (ACDMPV, Stuve-Wiedemann, Bohring-Opitz…) : on cree l'entite avec
    livre='hpoa', ses signes venant des annotations HPO curees (source = OMIM via
    HPOA, evidence PCS/TAS + PMID). Ce n'est PAS un verbatim de livre : le champ
    verbatim porte l'enregistrement HPOA lui-meme (label, evidence, reference,
    frequence) et methode='hpoa', pour ne jamais le confondre avec Smith/GR.
Sous-type = coeur du nom (sans numero/romain/lettre/type) a Jaccard >= 0,4 avec
le coeur du nom d'une entite attestee.
entite_id = ORPHA si product1 donne UN mapping exact vers un ORPHA de la base,
sinon OMIM:<n>. Le debut vient de la colonne onset HPOA (table hpoa_debut).
Rejouable : purge livre='hpoa' au depart.

Usage : python3 add_entites_hpoa.py [--apply]
"""
import argparse
import csv
import re
import sqlite3
import xml.etree.ElementTree as ET
from collections import defaultdict

DB = "/home/mathevet/Bureau/foeto_base/syndromes_foetaux.db"
HPOA = "/home/mathevet/Bureau/HPO_Foeto/P620/hpo_data/phenotype.hpoa"
TSV = "/home/mathevet/Bureau/foeto_base/omim_sans_fiche_foetal.tsv"
ONSET_PRE = {"HP:0030674", "HP:0011461", "HP:0003577", "HP:0003623", "HP:0034199", "HP:0034198", "HP:0034197"}
STOP = {"syndrome", "type", "with", "and", "or", "of", "the", "autosomal", "recessive", "dominant", "x", "linked",
        "disease", "disorder", "syndromes", "sequence", "related", "de", "du", "la", "susceptibility", "to", "due", "in", "form", "familial", "hereditary", "congenital"}
# homonymes que le Jaccard prend pour des sous-types : Bohring-Opitz (ASXL1) ≠ Bohring-Opitz-like KLHL7,
# Meier-Gorlin ≠ Gorlin, SMA + fractures / SMALED2B ≠ Kennedy, lissencéphalie 7 (CDK5) ≠ VLDLR, cutis laxa IB (EFEMP2) ≠ LTBP4
FORCER_TROU = {"OMIM:605039", "OMIM:621512", "OMIM:616866", "OMIM:616867", "OMIM:618291", "OMIM:616342", "OMIM:614437"}
RX_NUM = re.compile(r"^(\d+[a-z]?|[ivx]+|[a-z])$")
NIVEAU = {"HP:0040280": "principal", "HP:0040281": "principal", "HP:0040282": "principal",
          "HP:0040283": "occasionnel", "HP:0040284": "occasionnel", "HP:0040285": "occasionnel"}
FREQ = {"HP:0040280": "obligatoire", "HP:0040281": "très fréquent", "HP:0040282": "fréquent",
        "HP:0040283": "occasionnel", "HP:0040284": "très rare", "HP:0040285": "exclu"}
REGION = {"Croissance": "growth", "Tête / Cou": "craniofacial", "Œil": "eyes", "Oreille": "ears", "Thorax": "thorax",
          "Cardiovasculaire": "heart", "Digestif": "abdomen", "Génito-urinaire": "genitourinary", "Membres": "limbs",
          "Musculo-squelettique": "skeletal", "Téguments": "skin", "Système nerveux": "neuro", "Respiratoire": "thorax"}


def coeur(nom):
    return {t for t in re.sub(r"[^a-z0-9 ]", " ", nom.lower()).split() if t not in STOP and not RX_NUM.match(t)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()
    c = sqlite3.connect(DB)
    ent = [(e, coeur(n)) for e, n in c.execute("select entite_id, nom from entites_livres where livres not like '%hpoa%'")]
    rows = list(csv.DictReader(open(TSV, encoding="utf-8"), delimiter="\t"))
    trous, sous = [], []
    for r in rows:
        k = coeur(r["nom"])
        proche = max(((len(k & e) / len(k | e), eid) for eid, e in ent if k | e), default=(0, None))
        (sous if proche[0] >= 0.4 and r["omim"] not in FORCER_TROU else trous).append((r, proche))
    with open("/home/mathevet/Bureau/foeto_base/hpoa_sous_types.tsv", "w", encoding="utf-8") as f:
        w = csv.writer(f, delimiter="\t")
        w.writerow(["omim", "nom", "entite_proche", "jaccard"])
        for r, (j, eid) in sorted(sous, key=lambda x: x[0]["nom"]):
            w.writerow([r["omim"], r["nom"], eid, round(j, 2)])
    print(f"{len(rows)} OMIM : {len(sous)} sous-types d'une famille attestée (hpoa_sous_types.tsv), {len(trous)} vrais trous")

    # OMIM -> ORPHA exact, present dans la base et pas deja une entite
    orphas = {o for o, in c.execute("select id from syndromes where id like 'ORPHA:%'")}
    deja = {o for o, in c.execute("select orpha from entites_livres where orpha is not null")}
    mim2orpha = defaultdict(set)
    for dis in ET.parse("/home/mathevet/Bureau/foeto_base/orphadata/en_product1.xml").getroot().iter("Disorder"):
        sid = "ORPHA:" + dis.findtext("OrphaCode")
        for x in dis.iter("ExternalReference"):
            if x.findtext("Source") == "OMIM" and (x.findtext("DisorderMappingRelation/Name") or "").startswith("E "):
                mim2orpha[x.findtext("Reference")].add(sid)
    voulus = {r["omim"] for r, _ in trous}
    hpo_ok = dict(c.execute("select hpo_id, coalesce(label_fr, label_en) from hpo_terms"))
    cat = dict(c.execute("select hpo_id, category from hpo_terms"))
    annots, onsets = defaultdict(list), defaultdict(set)
    for line in open(HPOA, encoding="utf-8"):
        if not line.startswith("OMIM:"):
            continue
        f = line.rstrip("\n").split("\t")
        if f[0] not in voulus or f[2] == "NOT":
            continue
        if f[6]:
            onsets[f[0]].add(f[6])
        if f[3] in hpo_ok:
            annots[f[0]].append(f)
    if not a.apply:
        for r, _ in sorted(trous, key=lambda x: -int(x[0]["score"]))[:40]:
            o = mim2orpha.get(r["omim"][5:], set()) & orphas - deja
            print(f"  {r['omim']:12s} {r['nom'][:60]:60s} {len(annots[r['omim']]):3d} HPO  {','.join(sorted(o)) or 'OMIM'}")
        return
    c.execute("delete from syndrome_hpo_livres where livre='hpoa'")
    c.execute("create table if not exists hpoa_debut (entree text primary key, verdict text)")
    c.execute("delete from hpoa_debut")
    n = 0
    for r, _ in trous:
        mim = r["omim"]
        o = mim2orpha.get(mim[5:], set()) & orphas - deja
        sid = next(iter(o)) if len(o) == 1 else mim
        for f in annots[mim]:
            hid, ref, ev, onset, freq = f[3], f[4], f[5], f[6], f[7]
            verbatim = f"{hpo_ok[hid]} — annotation HPOA {ev} {ref}" + (f", fréquence {freq}" if freq else "") + (f", début {onset}" if onset else "")
            c.execute("""insert into syndrome_hpo_livres (syndrome_id, syndrome_titre, niveau_entree, hpo_id, livre, entree,
                         signe_livre, verbatim, frequence, niveau, region, est_parent, methode, modalite)
                         values (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                      (sid, r["nom"], "syndrome", hid, "hpoa", mim, hpo_ok[hid], verbatim,
                       FREQ.get(freq, freq or None), NIVEAU.get(freq, "texte"), REGION.get(cat.get(hid), "other"), 0, "hpoa", None))
            n += 1
        pre = onsets[mim] & ONSET_PRE
        c.execute("insert into hpoa_debut values (?,?)", (mim, "Prénatal/Néonatal (HPOA, onset)" if pre else ("Postnatal (HPOA, onset)" if onsets[mim] else None)))
    c.commit()
    print(f"{n} liens hpoa insérés pour {len(trous)} entités ; relancer build_entites_livres → parenté → fiches")


if __name__ == "__main__":
    main()
