#!/usr/bin/env python3
"""Bloc SIGNES embarque dans examen_clinique.html (V2) — structure MINIMALE.

Par item de la V1 (24, le grain du geste), sur son ancre HPO :
  chips    les chips V1 (vocabulaire maison) mappees a HPO quand une forme
           francaise correspond, PLUS les signes attestes les plus nommes par
           les fiches syndromes qui n'y sont pas deja — jamais a la place
  signes   la liste PLATE des signes attestes du sous-arbre (id, libelle, n)
  formes   les formes fr/en (NAME, EXACT, NARROW — jamais RELATED) groupees par
           signe, pour la recherche a 3 lettres

Pas d'aretes, pas de tri-etat ici : le relationnel vit dans le hub
(data.pazuzu), le HTML n'embarque que ce qu'il faut pour coder a la paillasse.

Usage : python3 build_signes_examen.py > /home/mathevet/Bureau/Hub_HTML/signes_examen_clinique.js
"""
import json
import re
import sqlite3
import sys
import unicodedata
from collections import defaultdict

DB = "/home/mathevet/Bureau/foeto_base/syndromes_foetaux.db"
N_TOP = 4

# item V1 -> ancre(s) HPO. aspect_general n'a pas de sous-arbre : etat du corps,
# pas un signe ; ses chips restent, codees quand un HPO existe (hydrops).
ANCRES = {
    "aspect_general": [], "symetrie": ["HP:0001507"], "proportions": ["HP:0001507"],
    "teguments": ["HP:0001574"], "pilosite": ["HP:0011362"],
    "crane": ["HP:0000929"], "fontanelles": ["HP:0011328"], "cheveux": ["HP:0011362"],
    "yeux": ["HP:0000478"], "nez": ["HP:0000366"], "bouche": ["HP:0000153"], "oreilles": ["HP:0000598"],
    "cou": ["HP:0025668"], "thorax": ["HP:0000765"],
    "abdomen": ["HP:0001438", "HP:0010866"], "dos": ["HP:0000925", "HP:0010301"], "cordon": ["HP:0010881"],
    "oge": ["HP:0000078"], "anus": ["HP:0004378"],
    "membres_sup": ["HP:0002817"], "mains": ["HP:0001155"], "ongles": ["HP:0001597"],
    "membres_inf": ["HP:0002814"], "pieds_morpho": ["HP:0001760"],
}
# les chips V1, telles qu'elles sont dans examen_clinique.html (a garder synchrone)
CHIPS_V1 = {
    "aspect_general": ["Macéré", "Hydropique", "Émacié", "Dysmorphique", "Momifié"],
    "symetrie": ["Asymétrie corporelle", "Hémihypertrophie", "Hémihypotrophie"],
    "proportions": ["Membres courts", "Tronc court", "Macrocéphalie relative", "Microcéphalie relative"],
    "teguments": ["Méconium", "Pâleur", "Ictère", "Cyanose", "Œdème", "Congestion", "Hémorragie", "Pétéchies", "Desquamation"],
    "pilosite": ["Hypertrichose", "Lanugo abondant", "Hypotrichose"],
    "crane": ["Dolichocéphalie", "Brachycéphalie", "Scaphocéphalie", "Turricéphalie", "Plagiocéphalie", "Front bombé", "Front fuyant"],
    "fontanelles": ["Fontanelle large", "Fontanelle punctiforme", "Sutures chevauchantes", "Craniosténose"],
    "cheveux": ["Implantation basse (nuque)", "Implantation basse (front)", "Épis anormaux", "Alopécie"],
    "yeux": ["Hypertélorisme", "Hypotélorisme", "Télécanthus", "Épicanthus", "Synophris", "Fentes obliques en haut", "Fentes obliques en bas", "Microphtalmie", "Anophtalmie", "Ptosis", "Colobome"],
    "nez": ["Racine large", "Ensellure marquée", "Narines antéversées", "Nez court", "Hypoplasie des ailes", "Aplasie"],
    "bouche": ["Fente labiale", "Fente palatine", "Microstomie", "Macrostomie", "Rétrognathie", "Micrognathie", "Philtrum long", "Philtrum lisse", "Lèvre supérieure fine", "Macroglossie"],
    "oreilles": ["Implantation basse", "Rotation postérieure", "Microtie", "Anotie", "Hélix replié", "Appendice pré-auriculaire", "Fistule pré-auriculaire"],
    "cou": ["Pterygium colli", "Cou court", "Hygroma"],
    "thorax": ["Étroit", "En tonneau", "En entonnoir", "En carène", "Mamelons écartés", "Mamelons surnuméraires"],
    "abdomen": ["Omphalocèle", "Laparoschisis", "Distendu", "Prune belly", "Excavé"],
    "dos": ["Spina bifida", "Scoliose", "Cyphose", "Fossette sacrale", "Appendice caudal"],
    "cordon": ["Artère ombilicale unique", "Nœud vrai", "Circulaire", "Grêle", "Insertion vélamenteuse"],
    "oge": ["Ambigus", "Hypospadias", "Épispadias", "Micropénis", "Cryptorchidie", "Hypertrophie clitoridienne", "Fusion des grandes lèvres"],
    "anus": ["Imperforation", "Position antérieure", "Fistule"],
    "membres_sup": ["Raccourcissement", "Agénésie", "Incurvation", "Amélie", "Phocomélie", "Rétraction articulaire"],
    "mains": ["Polydactylie préaxiale", "Polydactylie postaxiale", "Syndactylie", "Clinodactylie", "Camptodactylie", "Pouce en adduction", "Pli palmaire transverse unique", "Hockey stick"],
    "ongles": ["Hypoplasiques", "Absents", "Hyperconvexes", "Larges"],
    "membres_inf": ["Raccourcissement", "Agénésie", "Incurvation", "Amélie", "Phocomélie", "Rétraction articulaire"],
    "pieds_morpho": ["Pied bot varus équin", "Pied convexe (rocker-bottom)", "Polydactylie préaxiale", "Polydactylie postaxiale", "Syndactylie", "Sandal gap", "Talon proéminent"],
}
# chips V1 dont la forme maison n'est pas dans hpo_synonymes : codage explicite
MANUEL = {
    "Hydropique": "HP:0001789", "Pterygium colli": "HP:0000465", "Hygroma": "HP:0000476",
    "Étroit": "HP:0000774", "En entonnoir": "HP:0000767", "En carène": "HP:0000768",
    "Mamelons écartés": "HP:0006610", "Mamelons surnuméraires": "HP:0002558",
    "Fente labiale": "HP:0410030", "Ensellure marquée": "HP:0005280", "Racine large": "HP:0000431",
    "Fentes obliques en haut": "HP:0000582", "Fentes obliques en bas": "HP:0000494",
    "Implantation basse": "HP:0000369", "Rotation postérieure": "HP:0000358",
    "Pli palmaire transverse unique": "HP:0000954", "Pied bot varus équin": "HP:0001762",
    "Pied convexe (rocker-bottom)": "HP:0001838", "Sandal gap": "HP:0001852",
    "Imperforation": "HP:0002023", "Position antérieure": "HP:0001545",
    "Artère ombilicale unique": "HP:0001195", "Prune belly": "HP:0100775",
    "Ambigus": "HP:0000062", "Hypoplasiques": "HP:0001792", "Absents": "HP:0001798",
    "Craniosténose": "HP:0001363", "Fontanelle large": "HP:0000239",
    "Hémihypertrophie": "HP:0001528", "Membres courts": "HP:0009826", "Tronc court": "HP:0005815",
    "Microtie": "HP:0008551", "Polydactylie postaxiale": "HP:0100259", "Fossette sacrale": "HP:0000960",
    "Nez court": "HP:0003196", "Fistule pré-auriculaire": "HP:0004467", "Hélix replié": "HP:0011039",
    "Raccourcissement": None,        # relatif a l'item : code ci-dessous par item
    "Microcéphalie relative": None,  # relatif a la taille : pas un HPO
}
# chips dont le code depend de l'ITEM (« Raccourcissement » des membres sup vs inf)
MANUEL_ITEM = {
    ("membres_sup", "Raccourcissement"): "HP:0009824", ("membres_inf", "Raccourcissement"): "HP:0006385",
    ("membres_sup", "Agénésie"): "HP:0006496", ("membres_inf", "Agénésie"): "HP:0006385",
}


def norm(s):
    s = "".join(ch for ch in unicodedata.normalize("NFD", (s or "").lower()) if unicodedata.category(ch) != "Mn")
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9\s-]", " ", s)).strip()


def main():
    c = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    lab = {h: (fr or en) for h, fr, en in c.execute("select hpo_id, label_fr, label_en from hpo_terms")}
    foet = {r[0] for r in c.execute("select hpo_id from hpo_terms where context in ('prenatal','both') and is_excluded=0")}
    att = {r[0]: r[1] for r in c.execute(
        "select hpo_id, count(distinct syndrome_titre) from v_syndrome_hpo_livres_foetal where est_parent=0 group by 1")}
    desc = defaultdict(set)
    for h, a in c.execute("select hpo_id, ancestor_id from hpo_ancestors"):
        desc[a].add(h)
    formes = defaultdict(list)
    par_forme = {}
    # pour la recherche embarquee : toutes les formes FRANCAISES + le seul nom
    # anglais officiel (NAME). Les synonymes anglais restent dans le hub —
    # ils triplaient le bloc (358 Ko) pour ce qu'on ne tape pas a la paillasse.
    for h, f, lg, portee in c.execute("select hpo_id, forme, langue, portee from hpo_synonymes where portee in ('NAME','EXACT','NARROW')"):
        par_forme.setdefault(norm(f), h)
        if lg == "fr" or portee == "NAME":
            formes[h].append(f)

    out, n_code, n_chips = {}, 0, 0
    for item, ancres in ANCRES.items():
        sub = set()
        for a in ancres:
            sub |= desc[a] | {a}
        sub &= foet
        chips = []
        for v in CHIPS_V1[item]:
            h = MANUEL_ITEM.get((item, v)) or MANUEL.get(v) or par_forme.get(norm(v))
            if h and h not in foet:
                h = None
            chips.append({"l": v, "id": h})
            n_chips += 1; n_code += bool(h)
        deja = {ch["id"] for ch in chips if ch["id"]}
        for _, h in sorted(((att[h], h) for h in sub if att.get(h) and h not in deja), reverse=True)[:N_TOP]:
            chips.append({"l": lab[h], "id": h, "att": 1})
        signes = sorted(({"id": h, "l": lab[h], "n": att[h]} for h in sub if att.get(h)), key=lambda x: -x["n"])
        fm = {h: sorted(set(formes.get(h, [])), key=str.lower) for h in sub if att.get(h)}
        out[item] = {"ancres": ancres, "chips": chips, "signes": signes, "formes": fm}

    js = "/* genere par foeto_base/build_signes_examen.py — ne pas editer a la main */\nvar SIGNES = " + \
         json.dumps(out, ensure_ascii=False, separators=(",", ":")) + ";\n"
    sys.stdout.write(js)
    tot_s = sum(len(v["signes"]) for v in out.values()); tot_f = sum(len(x) for v in out.values() for x in v["formes"].values())
    sys.stderr.write(f"{len(out)} items | chips V1 codees {n_code}/{n_chips} | {tot_s} signes attestes | {tot_f} formes | {len(js)//1024} Ko\n")


if __name__ == "__main__":
    main()
