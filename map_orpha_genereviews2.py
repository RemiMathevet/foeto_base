#!/usr/bin/env python3
"""Seconde passe ORPHA pour les entrees GeneReviews restees sans identite (429 entites,
261 foetales) — sans jamais inventer un numero : tout ORPHA vient d'en_product1.xml,
la methode est ecrite dans syndromes.aliases (orpha_via:...).

Trois voies, de la plus sure a la moins sure, chacune tracee :
  titre   Jaccard des mots pleins entre le titre GR (variantes : sans « -Related »,
          « Disorder(s) », « Deficiency » -> « deficiency of ») et le nom ou un
          synonyme Orphanet ; pose si >= 0,6 (le nom exact etait deja fait)
  mim     MIM de phenotype du chapitre -> ORPHA (product1) ; pose si Jaccard >= 0,3
          (la passe 1 exigeait 0,5)
  gene    symbole de gene dans le TITRE (« PEX7-Related ... », « KAT6B Disorders »)
          ou genereviews_full.genes -> maladies du gene (product6) ; pose si le gene
          n'a qu'UNE maladie Orphanet et Jaccard >= 0,15, ou plusieurs et Jaccard >= 0,4 ; titre pose si >= 0,75 (0,6 laissait passer
          CPT1A -> CPT II, nonkinesigenic -> kinesigenic) ; numeros/romains identiques exiges
Coherence GENE : quand le titre porte un symbole (« ATP6V0A2-Related Cutis Laxa »),
l'ORPHA retenu doit lister ce gene dans product6 — sinon il n'est pas sur (« Cutis
laxa » ORPHA:209, groupe sans gene, fusionnait ATP6V0A2 et EFEMP2 en une entite ;
« TRPV4-Related » tombait sur Albers-Schonberg par « autosomal dominant »). Les mots
autosomal/dominant/recessive/linked/related/disorder/spectrum/overview ne comptent pas.
En dessous des seuils : arbitrage_orpha_genereviews.tsv (Remi). Les ORPHA crees
portent aliases 'genereviews:<slug>|orpha_via:<voie> j=<score>'.

Usage : python3 map_orpha_genereviews2.py [--apply]
"""
import argparse
import csv
import json
import re
import sqlite3
import xml.etree.ElementTree as ET
from collections import defaultdict

import map_orpha_livres as M

FR1 = "/home/mathevet/Bureau/foeto_base/orphadata/fr_product1.xml"
P6 = "/home/mathevet/Bureau/akinator/orphadata_cache/genes_en.xml"
TSV = "/home/mathevet/Bureau/foeto_base/arbitrage_orpha_genereviews.tsv"
RX_GENE = re.compile(r"\b([A-Z][A-Z0-9]{1,7}\d[A-Z0-9]*|[A-Z]{3,8})\b")


def variantes_gr(title):
    t = re.sub(r"\s*\(.*?\)", "", title).strip()
    out = [t]
    t2 = re.sub(r"\b[A-Z][A-Z0-9]*\d[A-Z0-9]*-(Related|Associated)\s+", "", t)   # PEX7-Related X
    t2 = re.sub(r"\b[A-Z]{3,}-(Related|Associated)\s+", "", t2)
    out.append(t2)
    out.append(re.sub(r"\b(Disorders?|Spectrum|Overview|Syndromes?)\b", "", t2).strip())
    if t2.endswith(" Deficiency"):
        out.append("deficiency of " + t2[:-11])
    return [x for x in dict.fromkeys(out) if len(x) >= 4]


GENERIQUE = {"autosomal", "dominant", "recessive", "linked", "related", "associated", "disorder", "disorders",
             "spectrum", "overview", "syndrome", "syndromes", "disease", "diseases", "type", "form", "forms"}


def toks(s):
    return M.toks(s) - GENERIQUE


RX_NUM = re.compile(r"^(\d+[a-z]?|[ivx]+|[a-z]\d+|\d+[a-z]|[a-z]{1,2})$")
HERED = {"dominant", "recessive", "linked"}


def nums(texte):
    """numeros, chiffres romains, lettres isolees (1, II, VA, 2a) — sur le texte brut,
    M.toks ecarte les tokens d'une lettre"""
    return {w for w in M.norm(texte).split() if RX_NUM.match(w) and w not in ("x",)} | ({"x"} if " x linked" in " " + M.norm(texte) else set())


def hered(texte):
    return {w for w in M.norm(texte).split() if w in HERED}


def jac(a, b):
    return len(a & b) / max(1, len(a | b))


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
                noms[sid].add((frozenset(toks(el.text)), el.text))
    fr = {"ORPHA:" + d.findtext("OrphaCode"): d.findtext("Name") for d in ET.parse(FR1).getroot().iter("Disorder")}
    gene2orpha = defaultdict(set)
    for d in ET.parse(P6).getroot().iter("Disorder"):
        sid = "ORPHA:" + d.findtext("OrphaCode")
        for s in d.iter("Symbol"):
            gene2orpha[s.text.strip()].add(sid)
    mim_pheno = {line[5:11] for line in M.HPOA.open(encoding="utf-8") if line.startswith("OMIM:")}
    gr = {slug: (title.replace(" - GeneReviews® - NCBI Bookshelf", "").strip(),
                 [str(m) for m in json.loads(om or "[]") if str(m) in mim_pheno], json.loads(g or "[]"))
          for slug, title, om, g in c.execute("select slug, title, omim_ids, genes from genereviews_full")}
    foet = dict(c.execute("select entite_id, foetale from entites_livres"))
    ent_de = dict(c.execute("select syndrome_titre, entite_id from entites_livres_titres"))
    ents = c.execute("""select distinct syndrome_titre, entree from syndrome_hpo_livres
                        where livre='genereviews' and syndrome_id is null""").fetchall()
    rows, poses, crees = [], 0, 0
    for titre, entree in ents:
        slug = entree.split("#")[0]
        title, mims, genes = gr.get(slug, (titre, [], []))
        genes = set(genes) | {g for g in RX_GENE.findall(title) if g in gene2orpha}
        best = None                                   # (score_norme, voie, sid, j)
        for v in variantes_gr(title):
            tv = toks(v)
            for sid, formes in noms.items():
                j, f = max(((jac(tv, f), txt) for f, txt in formes), default=(0, ""))
                if j >= 0.3 and (best is None or j > best[3]):
                    best = (j, "titre", sid, j, v, f)
        tt = toks(title)
        for m in mims:
            for sid in mim2orpha.get(m, ()):
                j, f = max(((jac(tt, f), txt) for f, txt in noms.get(sid, ())), default=(0, ""))
                if best is None or best[1] != "titre" or best[3] < 0.6:
                    if j >= 0.15 and (best is None or best[1] == "mim" and j > best[3] or best[1] == "gene"):
                        best = (j, "mim", sid, j, title, f)
        if best is None or best[3] < 0.3:
            for g in genes:
                sids = gene2orpha[g]
                for sid in sids:
                    j, f = max(((jac(tt, f), txt) for f, txt in noms.get(sid, ())), default=(0, ""))
                    seuil = 0.15 if len(sids) == 1 else 0.4
                    if j >= seuil and (best is None or j > best[3]):
                        best = (j, f"gene:{g}" + ("" if len(sids) == 1 else f"({len(sids)})"), sid, j, title, f)
        if best is None:
            continue
        j, voie, sid, _, tq, tf = best
        sur = (voie == "titre" and j >= 0.75) or (voie == "mim" and j >= 0.3) or \
              (voie.startswith("gene") and (("(" not in voie and j >= 0.15) or j >= 0.4))
        # coherence gene : un symbole dans le titre doit se retrouver sur l'ORPHA
        genes_titre = {g for g in RX_GENE.findall(title) if g in gene2orpha}
        if genes_titre and not any(sid in gene2orpha[g] for g in genes_titre):
            sur = False; voie += " ≠gène"
        # numeros et chiffres romains (1A / II, VA / II) et prefixe « non » (nonkinesigenic /
        # kinesigenic) doivent coincider : sinon c'est un voisin, pas la maladie
        tq_t, tf_t = toks(tq), toks(tf)
        if nums(tq) != nums(tf) or any(w.startswith("non") and w[3:] in tf_t for w in tq_t):
            sur = False; voie += " ≠num"
        # un GROUPE Orphanet (« Leukodystrophy ») n'est retenu que pour un chapitre qui est
        # lui-meme un panorama (Overview / Disorders / Spectrum) : POLR3-Related Leukodystrophy
        # n'est pas « Leukodystrophy »
        if (info[sid][1] or "").startswith(("Group", "Category")) and not re.search(r"Overview|Disorders|Spectrum", title):
            sur = False; voie += " ≠groupe"
        if hered(tq) and hered(tf) and hered(tq) != hered(tf):
            sur = False; voie += " ≠hérédité"
        # une forme partagee par plusieurs ORPHA (« Adenosine deaminase deficiency » = ADA-SCID
        # et ADA2) est ambigue : pas sure
        if voie == "titre" and sum(1 for s2, fs in noms.items() if any(txt == tf for _, txt in fs)) > 1:
            sur = False; voie += " ≠ambigu"
        e = ent_de.get(titre, "")
        rows.append({"slug": slug, "titre_gr": title, "foetale": foet.get(e, ""), "orpha": sid, "nom_orpha": info[sid][0],
                     "voie": voie, "jaccard": round(j, 2), "sur": int(sur), "choix": ""})
        if sur and a.apply:
            if sid not in connus:
                nm, typ, om = info[sid]
                c.execute("""insert into syndromes(id, name_fr, name_en, omim, orpha_code, type, category, relevance, aliases)
                             values(?,?,?,?,?,?,?,?,?)""",
                          (sid, fr.get(sid) or nm, nm, om or None, sid.split(":")[1], typ, "malformatif", "moyenne",
                           f"genereviews:{slug}|orpha_via:{voie} j={j:.2f}"))
                connus.add(sid); crees += 1
            else:
                c.execute("update syndromes set aliases = coalesce(aliases,'') || ? where id=?", (f"|genereviews:{slug}|orpha_via:{voie} j={j:.2f}", sid))
            c.execute("update syndrome_hpo_livres set syndrome_id=? where syndrome_titre=? and syndrome_id is null", (sid, titre))
            poses += 1
    if a.apply:
        c.commit()
    with open(TSV, "w", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()), delimiter="\t", lineterminator="\n")
        w.writeheader(); w.writerows(sorted(rows, key=lambda r: (r["sur"], -r["jaccard"])))
    n_sur = sum(r["sur"] for r in rows)
    print(f"{len(ents)} entrées GR sans ORPHA : {len(rows)} candidats, {n_sur} sûrs ({sum(1 for r in rows if r['sur'] and r['foetale']==1)} fœtaux), "
          f"{len(rows)-n_sur} à arbitrer -> {TSV}" + (f" ; appliqué : {poses} posés, {crees} ORPHA créés" if a.apply else ""))
    for r in [x for x in rows if x["sur"]][:12]:
        print(f"  {r['voie']:14s} j={r['jaccard']:.2f} {r['titre_gr'][:42]:42s} -> {r['orpha']} {r['nom_orpha'][:40]}")


if __name__ == "__main__":
    main()
