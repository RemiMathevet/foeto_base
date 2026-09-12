#!/usr/bin/env python3
"""Ajoute a la table syndromes les ORPHA que les livres (Smith, Spranger) nomment
et que la base n'avait pas, puis pose l'ORPHA sur syndrome_hpo_livres et charge
leurs annotations HPO Orphanet (product4) dans syndrome_hpo.

Resolution du titre -> ORPHA sur TOUT Orphanet (en_product1.xml), memes voies que
map_orpha_livres.py : MIM du titre, nom/synonyme exact (titre entier ou sans
parenthese), nom OMIM (phenotype.hpoa). Pas de jaccard : un ORPHA qu'on cree
doit etre sur. Les titres non resolus sont listes (arbitrage_orpha_ajouts.tsv).

Lignes creees : name_en/name_fr (fr_product1.xml), omim, orpha_code, type
(DisorderType), category deduite du livre (Spranger -> squelettique ; Smith par
lettre : A/B chromosomique, K/L/M/N squelettique, O/S metabolique, sinon
malformatif), relevance 'moyenne', source marquee dans aliases ('livre:<titre>').
syndrome_hpo : frequence Orphanet -> prob comme l'existant (0,95/0,85/0,5/0,15/0,02),
source 'orphanet', HPO absents de hpo_terms ignores.

Usage : python3 add_orpha_manquants.py [--apply]
"""
import argparse
import csv
import re
import sqlite3
import xml.etree.ElementTree as ET
from collections import defaultdict
from pathlib import Path

import map_orpha_livres as M

FR1 = Path("/home/mathevet/Bureau/foeto_base/orphadata/fr_product1.xml")
P4 = Path("/home/mathevet/Bureau/akinator/orphadata_cache/hpo_en.xml")
OUT = "/home/mathevet/Bureau/foeto_base/arbitrage_orpha_ajouts.tsv"
PROB = {"Obligate (100%)": 0.95, "Very frequent (99-80%)": 0.85, "Frequent (79-30%)": 0.5,
        "Occasional (29-5%)": 0.15, "Very rare (<4-1%)": 0.02, "Excluded (0%)": None}
CAT_SMITH = {"A": "chromosomique", "B": "chromosomique", "K": "squelettique", "L": "squelettique",
             "M": "squelettique", "N": "squelettique", "O": "metabolique", "S": "metabolique"}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()
    c = sqlite3.connect(M.DB)
    connus = {r[0] for r in c.execute("select id from syndromes")}

    # --- tout Orphanet ------------------------------------------------------
    noms, mim2orpha, info = defaultdict(set), defaultdict(set), {}
    for d in ET.parse(M.P1).getroot().iter("Disorder"):
        sid = "ORPHA:" + d.findtext("OrphaCode")
        info[sid] = {"name_en": d.findtext("Name"), "type": d.find("DisorderType/Name").text if d.find("DisorderType/Name") is not None else None,
                     "omim": ",".join(r.findtext("Reference") for r in d.iter("ExternalReference") if r.findtext("Source") == "OMIM")}
        for el in [d.find("Name")] + list(d.iter("Synonym")):
            if el is not None and M.norm(el.text):
                noms[M.norm(el.text)].add(sid)
        for mim in info[sid]["omim"].split(","):
            if mim:
                mim2orpha[mim].add(sid)
    fr = {"ORPHA:" + d.findtext("OrphaCode"): d.findtext("Name") for d in ET.parse(FR1).getroot().iter("Disorder")}
    mim_nom = {}
    for line in M.HPOA.open(encoding="utf-8"):
        if line.startswith("OMIM:"):
            mim, nom = line.split("\t")[:2]
            mim_nom[mim[5:]] = nom
    for mim, nom in mim_nom.items():
        for sid in mim2orpha.get(mim, ()):
            for f in (nom, re.sub(r"\s+\d+[a-z]?$", "", nom), re.sub(r",.*$", "", nom)):
                if M.norm(f):
                    noms[M.norm(f)].add(sid)

    ents = c.execute("""select distinct syndrome_titre, livre from syndrome_hpo_livres
                        where niveau_entree='syndrome' and syndrome_id is null order by livre, syndrome_titre""").fetchall()
    rows, a_creer = [], {}
    for titre, livre in ents:
        cands, meth = set(), ""
        for mim in re.findall(r"\b(\d{6})\b", titre):
            cands |= mim2orpha.get(mim, set())
        if cands:
            meth = "mim"
        else:
            for i, v in enumerate(M.variantes(titre)[:2]):
                if M.norm(v) in noms:
                    cands |= noms[M.norm(v)]; meth = "nom"
        # un seul candidat, et pour « nom » un nom Orphanet qui n'ajoute rien au titre
        ok = len(cands) == 1
        if ok and meth == "nom":
            sid = next(iter(cands)); tt, tn = M.toks(titre), M.toks(info[sid]["name_en"])
            ok = bool(tn) and not (tn - tt - {w for w in tn if w.isdigit()})
        sid = sorted(cands)[0] if cands else ""
        rows.append({"livre": livre, "titre": titre, "methode": meth, "orpha": sid,
                     "nom_orpha": info.get(sid, {}).get("name_en", ""),
                     "autres": " ; ".join(f"{x} {info[x]['name_en']}" for x in sorted(cands)[1:]),
                     "choix": sid if ok else ""})
        if ok:
            a_creer.setdefault(sid, []).append((titre, livre))
    # un TSV deja arbitre (colonne choix remplie) prime sur le calcul et n'est pas ecrase
    if Path(OUT).exists():
        prev = {x["titre"]: x["choix"] for x in csv.DictReader(open(OUT, encoding="utf-8"), delimiter="\t") if x["choix"]}
        if prev:
            for r in rows:
                if prev.get(r["titre"]) and prev[r["titre"]] in info:
                    r["choix"] = prev[r["titre"]]
            a_creer = {}
            for r in rows:
                if r["choix"]:
                    a_creer.setdefault(r["choix"], []).append((r["titre"], r["livre"]))
    else:
        with open(OUT, "w", encoding="utf-8", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(rows[0].keys()), delimiter="\t")
            w.writeheader(); w.writerows(rows)
    print(f"{len(rows)} titres sans ORPHA : {sum(1 for r in rows if r['choix'])} résolus sûrs "
          f"({len(a_creer)} ORPHA, dont {sum(1 for s in a_creer if s in connus)} déjà en table), "
          f"{sum(1 for r in rows if not r['choix'])} à arbitrer -> {OUT}")
    if not a.apply:
        return

    # --- creation + annotations HPO ----------------------------------------
    hpo_ok = {r[0] for r in c.execute("select hpo_id from hpo_terms")}
    p4 = {}
    for d in ET.parse(P4).getroot().iter("Disorder"):
        p4["ORPHA:" + d.findtext("OrphaCode")] = [(x.findtext("HPO/HPOId"), x.findtext("HPOFrequency/Name")) for x in d.iter("HPODisorderAssociation")]
    n_new = n_hpo = n_pose = 0
    for sid, titres in a_creer.items():
        titre, livre = titres[0]
        if sid not in connus:
            m = re.match(r"^([A-W]) ", titre)
            cat = "squelettique" if livre == "spranger_entites" else CAT_SMITH.get(m[1] if m else "", "malformatif")
            i = info[sid]
            c.execute("""insert into syndromes(id, name_fr, name_en, omim, orpha_code, type, category, relevance, aliases)
                         values(?,?,?,?,?,?,?,?,?)""",
                      (sid, fr.get(sid) or i["name_en"], i["name_en"], i["omim"] or None, sid.split(":")[1],
                       i["type"], cat, "moyenne", "livre:" + " | ".join(t for t, _ in titres)))
            for h, freq in p4.get(sid, []):
                if h in hpo_ok and PROB.get(freq) is not None:
                    c.execute("insert or ignore into syndrome_hpo(syndrome_id,hpo_id,frequency,prob,source,prob_orphanet) values(?,?,?,?,?,?)",
                              (sid, h, freq, PROB[freq], "orphanet", PROB[freq]))
                    n_hpo += 1
            connus.add(sid); n_new += 1
        for t, _ in titres:
            c.execute("update syndrome_hpo_livres set syndrome_id=? where syndrome_titre=? and syndrome_id is null", (sid, t))
            n_pose += 1
    c.commit()
    print(f"{n_new} ORPHA créés, {n_hpo} annotations HPO Orphanet chargées, {n_pose} titres rattachés")
    for l, n, m in c.execute("""select livre, count(*), sum(syndrome_id is not null) from
        (select distinct syndrome_titre, syndrome_id, livre from syndrome_hpo_livres where niveau_entree='syndrome') group by 1"""):
        print(f"  {l}: {m}/{n}")


if __name__ == "__main__":
    main()
