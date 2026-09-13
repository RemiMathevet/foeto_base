#!/usr/bin/env python3
"""Rattache aux familles EXISTANTES les syndromes ajoutes apres leur construction.

phase2_families (build_hpo_families_spectrum.py) DROPPE et renumerote les
familles, et ne lit que relevance='haute' : on ne la relance pas — les FAM:xxxx
sont references par syndrome_foeto_livres et extract_micro_livres.FAMILLES.
Ici : memes FAMILY_PATTERNS (methode 1, name_fr + name_en, confiance 0,9),
memes voies geniques (methode 2, 0,8) si syndrome_genes les connait, sur les
syndromes qui ne sont dans aucune famille. Insere, met n_members a jour.

Usage : python3 add_family_members.py [--tous]   (defaut : aliases like 'livre:%')
"""
import argparse
import re
import sqlite3
from collections import defaultdict

from build_hpo_families_spectrum import FAMILY_PATTERNS, GENE_PATHWAYS

DB = "/home/mathevet/Bureau/foeto_base/syndromes_foetaux.db"
PATHWAY_TO_FAMILY = {
    "RAS/MAPK": "RASopathies", "FGFR": "Craniosynostoses syndromiques", "Collagène_I": "Collagénopathies",
    "Collagène_II": "Collagénopathies", "Collagène_XI": "Collagénopathies", "Collagène_IX": "Collagénopathies",
    "Cohésine": "Cohesinopathies", "Rett": "Syndromes de Rett et apparentés", "Peroxysome": "Troubles du spectre Zellweger",
    "Dystroglycanopathie": "Dystroglycanopathies", "Tubuline": "Tubulinopathies", "BBS/Ciliopathie": "Ciliopathies",
    "Ciliopathie": "Ciliopathies", "Laminopathie": "Laminopathies", "Craniosynostose": "Craniosynostoses syndromiques",
}


# familles absentes de phase2, creees ici si besoin (Remi, 2026-09-12) : patterns sur
# name_fr + name_en, genes causaux ; on balaie TOUS les syndromes pour celles-la
EXTRA_FAMILIES = {
    "Fibrillinopathies et syndromes marfanoïdes": {
        "patterns": [r"marfan", r"arachnodactyl", r"loeys.dietz", r"shprintzen.goldberg", r"weill.marchesani"],
        "genes": ["FBN1", "FBN2", "TGFBR1", "TGFBR2", "SMAD3", "TGFB2", "TGFB3", "SKI"]},
    "Ostéochondromatoses et enchondromatoses": {
        "patterns": [r"exostos", r"ost[ée]ochondrom", r"enchondromat", r"ollier", r"maffucci", r"m[ée]tachondromat"],
        "genes": ["EXT1", "EXT2"]},
    "Alagille et cholangiopathies syndromiques": {
        "patterns": [r"alagille", r"art[ée]rioh[ée]pati", r"paucit.*bili", r"pauvret.*bili"],
        "genes": ["JAG1", "NOTCH2"]},
    "Ossifications hétérotopiques (FOP, POH)": {
        "patterns": [r"fibrodysplasi.*ossificans", r"ossificans progressiva", r"h[ée]t[ée]roplasi.*osseuse", r"osseous heteroplasia", r"ossification h[ée]t[ée]rotopique"],
        "genes": ["ACVR1"]},
}


# un gene partage n'est pas une appartenance : JAG1 met la tetralogie de Fallot chez
# Alagille, SKI met la deletion 1p36 chez les marfanoides (Remi, 2026-09-12)
EXCLUS = {("Alagille et cholangiopathies syndromiques", "ORPHA:3303"),
          ("Fibrillinopathies et syndromes marfanoïdes", "ORPHA:1606")}


# familles EXISTANTES dont phase2 ne connaissait qu'une partie des membres : patterns
# et genes ajoutes, appliques a toute la base (Remi, 2026-09-13 : « Ciliopathies, 3 membres »)
ENRICHIR = {
    "Ciliopathies": {
        "patterns": [r"jeune", r"asphyxiating thoracic", r"thoracique asphyxiante", r"short.rib", r"côtes courtes",
                     r"ellis.van.creveld", r"chondroectodermal", r"or[ao].?faci[ao].?digital", r"senior.l[oø]ken",
                     r"nephronophthisis", r"n[ée]phronophtise", r"sensenbrenner", r"cranioectodermal",
                     r"mainzer.saldino", r"hydrolethalus", r"alstr[oö]m", r"acrocallosal", r"joubert", r"meckel",
                     r"bardet.biedl", r"mckusick.kaufman", r"ciliopath"],
        "genes": ["IFT80", "IFT172", "IFT140", "DYNC2H1", "WDR34", "WDR60", "NEK1", "TTC21B", "EVC", "EVC2",
                  "OFD1", "NPHP1", "NPHP3", "NPHP4", "CEP290", "TMEM67", "RPGRIP1L", "CC2D2A", "MKS1", "TMEM216",
                  "B9D1", "B9D2", "TCTN1", "TCTN2", "TCTN3", "KIF7", "INPP5E", "ARL13B", "AHI1", "BBS1", "BBS2",
                  "BBS4", "BBS10", "BBS12", "WDR19", "WDR35", "IFT122", "IFT43", "TTC8", "HYLS1", "ALMS1"]},
}


def creer_familles(c):
    """cree les EXTRA_FAMILIES manquantes et y rattache tous les syndromes de la base ;
    enrichit les familles ENRICHIR sur toute la base"""
    fam_id = {n: f for f, n in c.execute("select family_id, family_name from syndrome_families")}
    genes = defaultdict(set)
    for sid, g in c.execute("select syndrome_id, gene_symbol from syndrome_genes where role='causal'"):
        genes[sid].add(g)
    tous = c.execute("select id, name_fr, name_en from syndromes").fetchall()
    for fname, spec in ENRICHIR.items():
        if fname not in fam_id:
            continue
        n = 0
        for sid, fr, en in tous:
            nom = f"{fr or ''} {en or ''}".lower()
            conf = 0.9 if any(re.search(p, nom, re.I) for p in spec["patterns"]) else \
                   0.8 if genes.get(sid, set()) & set(spec["genes"]) else None
            if conf:
                n += c.execute("insert or ignore into syndrome_family_members values(?,?,?)", (fam_id[fname], sid, conf)).rowcount
        print(f"  {fam_id[fname]} {fname} : +{n} membres")
    creer_familles_extra(c, fam_id, genes, tous)


def creer_familles_extra(c, fam_id, genes, tous):
    """cree les EXTRA_FAMILIES manquantes et y rattache tous les syndromes de la base"""
    nxt = 1 + max(int(f.split(":")[1]) for f in fam_id.values())
    for fname, spec in EXTRA_FAMILIES.items():
        if fname not in fam_id:
            fid = f"FAM:{nxt:04d}"; nxt += 1
            c.execute("insert into syndrome_families values(?,?,?,?,?)", (fid, fname, None, "name_pattern", 0))
            fam_id[fname] = fid
        fid = fam_id[fname]
        n = 0
        for sid, fr, en in tous:
            nom = f"{fr or ''} {en or ''}".lower()
            conf = 0.9 if any(re.search(p, nom, re.I) for p in spec["patterns"]) else \
                   0.8 if genes.get(sid, set()) & set(spec["genes"]) else None
            if conf and (fname, sid) not in EXCLUS:
                c.execute("insert or ignore into syndrome_family_members values(?,?,?)", (fid, sid, conf)); n += 1
        print(f"  {fid} {fname} : {n} membres")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tous", action="store_true", help="tous les syndromes sans famille, pas seulement ceux des livres")
    ap.add_argument("--livres", action="store_true", help="tout syndrome rattache a une entree de livre (syndrome_hpo_livres)")
    ap.add_argument("--creer", action="store_true", help="cree les EXTRA_FAMILIES manquantes et les peuple sur toute la base")
    a = ap.parse_args()
    c = sqlite3.connect(DB)
    if a.creer:
        creer_familles(c)
    fam_id = {n: f for f, n in c.execute("select family_id, family_name from syndrome_families")}
    deja = {r[0] for r in c.execute("select distinct syndrome_id from syndrome_family_members")}
    where = "" if a.tous else ("where id in (select syndrome_id from syndrome_hpo_livres)" if a.livres else "where aliases like 'livre:%'")
    cibles = [r for r in c.execute(f"select id, name_fr, name_en from syndromes {where}") if r[0] not in deja]
    genes = defaultdict(set)
    for sid, g in c.execute("select syndrome_id, gene_symbol from syndrome_genes where role='causal'"):
        genes[sid].add(g)
    n = 0
    for sid, fr, en in cibles:
        nom = f"{fr or ''} {en or ''}".lower()
        for fname, pats in FAMILY_PATTERNS.items():
            if fname in fam_id and any(re.search(p, nom, re.I) for p in pats):
                c.execute("insert or ignore into syndrome_family_members values(?,?,?)", (fam_id[fname], sid, 0.9)); n += 1
                print(f"  {sid} {en or fr} -> {fname}")
        for g in genes.get(sid, ()):
            fname = PATHWAY_TO_FAMILY.get(GENE_PATHWAYS.get(g, ""))
            if fname in fam_id:
                c.execute("insert or ignore into syndrome_family_members values(?,?,?)", (fam_id[fname], sid, 0.8)); n += 1
                print(f"  {sid} {en or fr} -> {fname} (gène {g})")
    c.execute("update syndrome_families set n_members = (select count(*) from syndrome_family_members m where m.family_id = syndrome_families.family_id)")
    c.commit()
    print(f"{len(cibles)} syndromes examinés, {n} rattachements")


if __name__ == "__main__":
    main()
