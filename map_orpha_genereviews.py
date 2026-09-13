#!/usr/bin/env python3
"""ORPHA des entrees GeneReviews de la matrice : par les MIM du chapitre
(genereviews_full.omim_ids -> references externes Orphanet, product1), puis par
le nom/synonyme exact sur tout Orphanet. Cree l'ORPHA dans syndromes s'il manque
(memes champs que add_orpha_manquants, categorie 'malformatif', relevance
'moyenne', aliases 'genereviews:<slug>'), sans annotations HPO Orphanet (la
matrice porte deja les signes du chapitre). Un chapitre a plusieurs MIM ->
l'ORPHA le plus frequent parmi eux, sinon le premier ; tracé dans arbitrage.

Usage : python3 map_orpha_genereviews.py [--apply]
"""
import argparse
import json
import re
import sqlite3
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict

import map_orpha_livres as M

FR1 = "/home/mathevet/Bureau/foeto_base/orphadata/fr_product1.xml"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()
    c = sqlite3.connect(M.DB)
    connus = {r[0] for r in c.execute("select id from syndromes")}
    info, mim2orpha, noms = {}, defaultdict(set), defaultdict(set)
    for d in ET.parse(M.P1).getroot().iter("Disorder"):
        sid = "ORPHA:" + d.findtext("OrphaCode")
        typ = d.find("DisorderType/Name")
        info[sid] = (d.findtext("Name"), typ.text if typ is not None else None,
                     ",".join(r.findtext("Reference") for r in d.iter("ExternalReference") if r.findtext("Source") == "OMIM"))
        for r in d.iter("ExternalReference"):
            if r.findtext("Source") == "OMIM":
                mim2orpha[r.findtext("Reference")].add(sid)
        for el in [d.find("Name")] + list(d.iter("Synonym")):
            if el is not None and M.norm(el.text):
                noms[M.norm(el.text)].add(sid)
    fr = {"ORPHA:" + d.findtext("OrphaCode"): d.findtext("Name") for d in ET.parse(FR1).getroot().iter("Disorder")}
    # omim_ids de GeneReviews melange MIM de PHENOTYPE et MIM de GENE (SLC2A2 138160…) :
    # un MIM de gene retombe sur n'importe quelle maladie du gene (les galactosemies et
    # les glycogenoses sortaient « Fanconi-Bickel »). On ne garde que les MIM de
    # phenotype = ceux que phenotype.hpoa annote comme maladies.
    mim_pheno = set()
    for line in M.HPOA.open(encoding="utf-8"):
        if line.startswith("OMIM:"):
            mim_pheno.add(line[5:11])
    gr = {slug: (title.replace(" - GeneReviews® - NCBI Bookshelf", "").strip(), [m for m in json.loads(om or "[]") if str(m) in mim_pheno])
          for slug, title, om in c.execute("select slug, title, omim_ids from genereviews_full")}
    formes_de = defaultdict(list)
    for k, v in noms.items():
        for sid in v:
            formes_de[sid].append(k)
    ents = c.execute("""select distinct syndrome_titre, entree from syndrome_hpo_livres
                        where livre='genereviews' and syndrome_id is null""").fetchall()
    n = crees = 0
    for titre, entree in ents:
        slug = entree.split("#")[0]
        title, mims = gr.get(slug, (titre, []))
        # omim_ids cite aussi les MIM des diagnostics differentiels du chapitre (Duarte
        # galactosemia porte 227810 = Fanconi-Bickel) : un ORPHA par MIM n'est retenu que
        # si son nom ou un synonyme partage des mots pleins avec le titre du chapitre
        tt = M.toks(title)
        # le NOM exact d'abord (« Glycogen Storage Disease Type I » est un synonyme
        # Orphanet de ORPHA:364), les MIM ensuite, avec recouvrement fort du titre
        cands = Counter()
        for v in M.variantes(title)[:2]:
            for sid in noms.get(M.norm(v), ()):
                cands[sid] += 1
        meth = "nom"
        if not cands:
            for m in mims:
                for sid in mim2orpha.get(str(m), ()):
                    formes = formes_de.get(sid, [])
                    if any(len(tt & M.toks(f)) / max(1, len(tt | M.toks(f))) >= 0.5 for f in formes):
                        cands[sid] += 1
            meth = "mim"
        if not cands:
            continue
        sid = cands.most_common(1)[0][0]
        if a.apply:
            if sid not in connus:
                nm, typ, om = info[sid]
                c.execute("""insert into syndromes(id, name_fr, name_en, omim, orpha_code, type, category, relevance, aliases)
                             values(?,?,?,?,?,?,?,?,?)""",
                          (sid, fr.get(sid) or nm, nm, om or None, sid.split(":")[1], typ, "malformatif", "moyenne", f"genereviews:{slug}"))
                connus.add(sid); crees += 1
            c.execute("update syndrome_hpo_livres set syndrome_id=? where syndrome_titre=? and syndrome_id is null", (sid, titre))
        n += 1
    if a.apply:
        c.commit()
    print(f"{len(ents)} entrées GeneReviews sans ORPHA : {n} résolues, {crees} ORPHA créés")


if __name__ == "__main__":
    main()
