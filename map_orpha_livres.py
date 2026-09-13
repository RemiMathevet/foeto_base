#!/usr/bin/env python3
"""Rattachement ORPHA des entrees de livres (Smith, Spranger) — deterministe.

Avant : 169/311 Smith et 77/210 Spranger appariees sur name_fr/name_en de la
table syndromes seule (omim rempli sur 17 lignes, aliases sur 33).
Sources ajoutees :
  orphadata/en_product1.xml   nomenclature Orphanet : synonymes anglais + references
                              externes OMIM (ORPHA <-> MIM)
  HPO_Foeto/P620/hpo_data/phenotype.hpoa   noms des maladies OMIM (MIM <-> nom)
Voies, par confiance :
  mim      un numero MIM du titre (Spranger) -> ORPHA par la reference externe
  nom      une forme du titre == nom/synonyme Orphanet ou nom OMIM -> ORPHA
  jaccard  mots pleins du titre vs noms Orphanet (>= 0,75) : PROPOSITION seule
Ecrit arbitrage_orpha.tsv ; --apply pose syndrome_id sur syndrome_hpo_livres
pour mim et nom (jaccard reste a arbitrer), et ne remplace jamais un ORPHA
deja pose. Ne cree pas d'ORPHA absent de la table syndromes.

Usage : python3 map_orpha_livres.py [--apply]
"""
import argparse
import csv
import re
import sqlite3
import unicodedata
import xml.etree.ElementTree as ET
from collections import defaultdict
from pathlib import Path

DB = "/home/mathevet/Bureau/foeto_base/syndromes_foetaux.db"
P1 = Path("/home/mathevet/Bureau/foeto_base/orphadata/en_product1.xml")
HPOA = Path("/home/mathevet/Bureau/HPO_Foeto/P620/hpo_data/phenotype.hpoa")
OUT = "/home/mathevet/Bureau/foeto_base/arbitrage_orpha.tsv"
STOP = {"syndrome", "syndromes", "disease", "disorder", "sequence", "association", "type", "types", "and", "or",
        "of", "the", "with", "a", "an", "in", "to", "de", "du", "des", "la", "le", "les", "et"}


def norm(s):
    s = "".join(ch for ch in unicodedata.normalize("NFD", (s or "").lower()) if unicodedata.category(ch) != "Mn")
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9\s]", " ", s)).strip()


def toks(s):
    return {w for w in norm(s).split() if w not in STOP and len(w) > 1}


def variantes(titre):
    t = re.sub(r"^[\dA-Z]+[\.\d]*\s+", "", titre)
    t = re.sub(r"\s*\((?:MIM|OMIM)[^)]*\)", "", t).strip()
    out = [t, re.sub(r"\(.*?\)", "", t).strip()]
    if "," in t:
        out.append(re.sub(r"\(.*?\)", "", t.split(",")[0]).strip())
    for m in re.findall(r"\(([^)]+)\)", t):
        out += [x.strip() for x in re.split(r"[,;/]", m) if x.strip()]
    return [x for x in dict.fromkeys(out) if len(x) >= 4]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()
    c = sqlite3.connect(DB)
    connus = {r[0] for r in c.execute("select id from syndromes")}

    # --- index des noms -> ORPHA (table + Orphanet) et MIM -> ORPHA -----------
    noms = defaultdict(set)          # forme normalisee -> {ORPHA}
    principaux = defaultdict(set)    # forme = NOM officiel (table ou Orphanet), pas un synonyme
    mim2orpha = defaultdict(set)
    orpha_nom = {}
    for sid, fr, en, al in c.execute("select id, name_fr, name_en, aliases from syndromes"):
        orpha_nom[sid] = en or fr
        for f in [fr, en] + [x for x in (al or "").split("|")]:
            if norm(f):
                noms[norm(f)].add(sid)
        for f in (fr, en):
            if norm(f):
                principaux[norm(f)].add(sid)
    root = ET.parse(P1).getroot()
    n_syn = 0
    for d in root.iter("Disorder"):
        sid = "ORPHA:" + d.findtext("OrphaCode")
        if sid not in connus:
            continue
        for el in [d.find("Name")] + list(d.iter("Synonym")):
            if el is not None and norm(el.text):
                noms[norm(el.text)].add(sid); n_syn += 1
        if norm(d.findtext("Name")):
            principaux[norm(d.findtext("Name"))].add(sid)
        for ref in d.iter("ExternalReference"):
            if ref.findtext("Source") == "OMIM":
                mim2orpha[ref.findtext("Reference")].add(sid)
    # noms OMIM (phenotype.hpoa) -> MIM -> ORPHA
    mim_nom = {}
    if HPOA.exists():
        for line in HPOA.open(encoding="utf-8"):
            if line.startswith("OMIM:"):
                mim, nom = line.split("\t")[:2]
                mim_nom[mim[5:]] = nom
    for mim, nom in mim_nom.items():
        for sid in mim2orpha.get(mim, ()):
            # « Meckel syndrome 1 » -> aussi sans le numero de type
            for f in (nom, re.sub(r"\s+\d+[a-z]?$", "", nom), re.sub(r",.*$", "", nom)):
                if norm(f):
                    noms[norm(f)].add(sid)
    tok_index = [(sid, toks(n)) for n, sids in noms.items() for sid in sids if len(toks(n)) >= 2]
    print(f"index : {len(noms)} formes, {len(mim2orpha)} MIM -> ORPHA, {n_syn} noms/synonymes Orphanet")

    ents = c.execute("""select distinct syndrome_titre, syndrome_id, livre from syndrome_hpo_livres
                        where niveau_entree='syndrome' order by livre, syndrome_titre""").fetchall()
    rows, poses = [], 0
    for titre, sid, livre in ents:
        if sid:
            continue
        cands, meth = set(), None
        for mim in re.findall(r"\b(\d{6})\b", titre):
            cands |= mim2orpha.get(mim, set())
        if cands:
            meth = "mim"
        else:
            vs = variantes(titre)
            for i, v in enumerate(vs):
                if norm(v) in noms:
                    cands |= noms[norm(v)]
                    # un fragment de parenthese (« Chondrodysplasia Punctata » dans
                    # « ... (Chondrodysplasia Punctata, Rhizomelic Type) ») attrape un
                    # synonyme court d'une autre entite : proposition, pas auto
                    meth = "nom" if i <= 1 and meth != "nom_partiel" else "nom_partiel"
        if not cands:
            tt = toks(titre)
            best = []
            for osid, tk in tok_index:
                j = len(tt & tk) / len(tt | tk) if tt | tk else 0
                if j >= 0.75:
                    best.append((j, osid))
            for j, osid in sorted(best, reverse=True)[:3]:
                cands.add(osid)
            if cands:
                meth = "jaccard"
        # plusieurs ORPHA pour une forme (« Meckel syndrome » est aussi un synonyme de
        # 439897) : celui dont c'est le NOM officiel l'emporte
        if meth == "nom" and len(cands) > 1:
            off = {sid for v in vs for sid in principaux.get(norm(v), ()) if sid in cands}
            if len(off) == 1:
                cands = off
        cands = sorted(cands)
        auto = meth in ("mim", "nom") and len(cands) == 1
        # « VACTERL Association » -> « VACTERL with hydrocephalus », « Robin Sequence » ->
        # « ...-Pierre Robin syndrome », « SMD Kozlowski » -> « Autosomal recessive SMD » :
        # le nom Orphanet est PLUS specifique que le titre. Auto seulement si le nom
        # Orphanet n'ajoute aucun mot plein au titre (mim : l'auteur a ecrit le numero)
        if auto and meth == "nom":
            tt, tn = toks(titre), toks(orpha_nom.get(cands[0], ""))
            auto = bool(tn) and not (tn - tt - {w for w in tn if w.isdigit()})
        rows.append({"livre": livre, "titre": titre, "methode": meth or "", "orpha": cands[0] if cands else "",
                     "nom_orpha": orpha_nom.get(cands[0], "") if cands else "",
                     "autres": " ; ".join(f"{x} {orpha_nom.get(x, '')}" for x in cands[1:]),
                     "choix": cands[0] if auto else ""})
        if a.apply and auto:
            c.execute("update syndrome_hpo_livres set syndrome_id=? where syndrome_titre=? and syndrome_id is null", (cands[0], titre))
            poses += 1
    with open(OUT, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()), delimiter="\t")
        w.writeheader(); w.writerows(rows)
    if a.apply:
        c.commit()
    from collections import Counter
    cnt = Counter((r["methode"], bool(r["choix"])) for r in rows)
    print(f"{len(rows)} entrées sans ORPHA -> {OUT}")
    for (m, ok), k in sorted(cnt.items()):
        print(f"  {m or 'aucun':8s} {'auto' if ok else 'à arbitrer':11s} {k}")
    if a.apply:
        print(f"{poses} ORPHA posés sur syndrome_hpo_livres")
        for l, n, m in c.execute("""select livre, count(*), sum(syndrome_id is not null) from
            (select distinct syndrome_titre, syndrome_id, livre from syndrome_hpo_livres where niveau_entree='syndrome') group by 1"""):
            print(f"  {l}: {m}/{n}")


if __name__ == "__main__":
    main()
