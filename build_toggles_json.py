#!/usr/bin/env python3
"""JSON de navigation par toggles pour les HTML d'examen — une source, trois profondeurs.

Par section (ancre HPO, fiche Hub_HTML 062e09a99af9) :
  toggles   les 4 signes que le plus de fiches syndromes nomment (f15d08318631),
            ou ceux coches « oui » dans toggles_proposes.tsv si Remi l'a arbitre
  arbre     les signes ATTESTES de la section, relies par les aretes HPO ; les
            noeuds intermediaires non attestes ne sont la que pour relier
            (« nav »), on ne les coche pas
  formes    les synonymes fr/en (NAME, EXACT, NARROW — jamais RELATED) des signes
            attestes, pour l'autocompletion a 3 lettres

Aucun verbatim de livre : des libelles HPO et des comptes. Servable sans verrou.

Usage : python3 build_toggles_json.py [sortie.json]
"""
import csv
import json
import re
import sqlite3
import sys
from collections import defaultdict
from pathlib import Path

DB = "/home/mathevet/Bureau/foeto_base/syndromes_foetaux.db"
TSV = Path("/home/mathevet/Bureau/foeto_base/toggles_proposes.tsv")
OUT = sys.argv[1] if len(sys.argv) > 1 else "/home/mathevet/Bureau/foetodata_hub/static/toggles_demo.json"

# module HTML, section, ancres (plusieurs ancres = plusieurs sous-arbres dans la meme section)
SECTIONS = [
    ("examen_clinique", "Général — croissance", ["HP:0001507", "HP:0001197"]),
    ("examen_clinique", "Tête — crâne", ["HP:0000929"]),
    ("examen_clinique", "Tête — face", ["HP:0000271"]),
    ("examen_clinique", "Tête — œil", ["HP:0000478"]),
    ("examen_clinique", "Tête — oreille", ["HP:0000598"]),
    ("examen_clinique", "Cou", ["HP:0000464"]),
    ("examen_clinique", "Thorax", ["HP:0000765"]),
    ("examen_clinique", "Périnée — génital", ["HP:0000078"]),
    ("examen_clinique", "Membres supérieurs", ["HP:0002817"]),
    ("examen_clinique", "Membres inférieurs", ["HP:0002814"]),
    ("examen_clinique", "Téguments", ["HP:0001574"]),
    ("autopsie", "Cœur", ["HP:0001626"]),
    ("autopsie", "Poumons", ["HP:0002086"]),
    ("autopsie", "Digestif", ["HP:0025031"]),
    ("autopsie", "Rein et voies urinaires", ["HP:0000077", "HP:0000079"]),
    ("autopsie", "Endocrine", ["HP:0000818"]),
    ("autopsie", "Système nerveux", ["HP:0000707"]),
]


def main():
    c = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    lab = {h: (fr or en) for h, fr, en in c.execute("select hpo_id, label_fr, label_en from hpo_terms")}
    foet = {r[0] for r in c.execute("select hpo_id from hpo_terms where context in ('prenatal','both') and is_excluded=0")}
    att = {r[0]: r[1] for r in c.execute(
        "select hpo_id, count(distinct syndrome_titre) from v_syndrome_hpo_livres_foetal where est_parent=0 group by 1")}
    desc, parents = defaultdict(set), defaultdict(set)
    for h, a, d in c.execute("select hpo_id, ancestor_id, distance from hpo_ancestors"):
        desc[a].add(h)
        if d == 1:
            parents[h].add(a)
    syn = defaultdict(list)
    for h, f, lg in c.execute("select hpo_id, forme, langue from hpo_synonymes where portee in ('NAME','EXACT','NARROW')"):
        syn[h].append((f, lg))

    # arbitrage de Remi s'il existe : colonne retenu_en_toggle = oui
    choisis = defaultdict(list)
    if TSV.exists():
        for r in csv.DictReader(open(TSV, encoding="utf-8"), delimiter="\t"):
            if (r.get("retenu_en_toggle") or "").strip().lower() == "oui":
                choisis[r["section"]].append(r["hpo_id"])

    out = []
    for module, nom, ancres in SECTIONS:
        sub = set()
        for a in ancres:
            sub |= desc[a]
        sub &= foet
        attestes = {h for h in sub if att.get(h)}
        # noeuds de l'arbre : attestes + leurs ancetres a l'interieur du sous-arbre (pour relier)
        noeuds = set(attestes)
        for h in attestes:
            noeuds |= {x for x in desc_ancestors(h, parents, sub)}
        noeuds |= set(ancres)
        arbre = []
        for h in noeuds:
            ps = [p for p in parents[h] if p in noeuds]
            arbre.append({"id": h, "label": lab.get(h, h), "n": att.get(h, 0),
                          "parents": ps, "nav": h not in attestes})
        arbre.sort(key=lambda x: (-x["n"], x["label"]))
        # toggles : arbitrage TSV, sinon top 4 par nombre de fiches
        cle = {"Général — croissance": "general — croissance", "Tête — crâne": "tete — crane",
               "Tête — face": "tete — face", "Tête — œil": "tete — oeil", "Tête — oreille": "tete — oreille",
               "Cou": "cou", "Thorax": "thorax", "Périnée — génital": "perinee — genital",
               "Membres supérieurs": "membres sup", "Membres inférieurs": "membres inf", "Téguments": "teguments",
               "Cœur": "autopsie — coeur", "Poumons": "autopsie — poumons", "Digestif": "autopsie — digestif",
               "Rein et voies urinaires": "autopsie — rein", "Endocrine": "autopsie — endocrine",
               "Système nerveux": "autopsie — neuro"}.get(nom, nom)
        top = choisis.get(cle) or [h for _, h in sorted(((att[h], h) for h in attestes), reverse=True)[:4]]
        formes = [{"id": h, "f": f, "lg": lg} for h in attestes for f, lg in syn.get(h, [])]
        out.append({"module": module, "section": nom, "ancres": ancres,
                    "toggles": [{"id": h, "label": lab.get(h, h), "n": att.get(h, 0)} for h in top],
                    "arbre": arbre, "formes": formes,
                    "stats": {"candidats": len(sub), "attestes": len(attestes)}})

    Path(OUT).write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")
    tot_a = sum(len(s["arbre"]) for s in out); tot_f = sum(len(s["formes"]) for s in out)
    print(f"{len(out)} sections, {tot_a} nœuds d'arbre, {tot_f} formes -> {OUT} ({Path(OUT).stat().st_size // 1024} Ko)")


def desc_ancestors(h, parents, sub):
    """ancetres de h restant dans le sous-arbre de la section"""
    seen, stack = set(), [h]
    while stack:
        x = stack.pop()
        for p in parents.get(x, ()):
            if p in sub and p not in seen:
                seen.add(p); stack.append(p)
    return seen


if __name__ == "__main__":
    main()
