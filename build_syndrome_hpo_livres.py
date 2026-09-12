#!/usr/bin/env python3
"""syndrome_hpo_livres : la matrice syndrome x HPO ATTESTEE PAR UN LIVRE.

A cote de syndrome_hpo (70 731 liens Orphanet, frequence declaree, aucune
source), jamais fusionnee avec elle. Un signe non atteste par un livre pour un
syndrome n'existe pas dans cette table — c'est tout le point.

Ce qui la distingue :
  - chaque ligne porte son OUVRAGE, son entree et son VERBATIM : elle se verifie
  - la frequence n'est presente que si le livre la chiffre (jamais deduite)
  - le niveau vient du livre : « principal » (ABNORMALITIES chez Smith),
    « occasionnel » (OCCASIONAL ABNORMALITIES), « texte » (cite en prose)
  - est_parent=1 quand le codage est un noeud d'arborescence et non le signe
    brut (terme-parapluie du livre, ou alternative « X or Y » portee sur son
    plus petit ancetre commun)

Rattachement au syndrome : le titre du livre est apparie aux syndromes de la
base (name_en, name_fr, aliases) apres nettoyage du prefixe de groupe Smith
(« A Down Syndrome (Trisomy 21 Syndrome) » -> « down syndrome »). Une entree
non appariee garde son titre de livre dans syndrome_titre et syndrome_id reste
NULL : la ligne existe, elle est simplement en attente d'un rattachement.

Usage : python3 build_syndrome_hpo_livres.py [--apply]
"""
import argparse
import re
import sqlite3
import unicodedata
from collections import Counter

DB = "/home/mathevet/Bureau/foeto_base/syndromes_foetaux.db"
GROUPE = re.compile(r"^(?:[A-W]|\d+\.\d+)\s+")       # prefixe de groupe Smith (« K ») ou numero Spranger (« 1.1 »)
PARENTH = re.compile(r"\s*\([^)]*\)\s*$")


def norm(s):
    s = (s or "").lower().strip()
    s = "".join(c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn")
    s = re.sub(r"\b(syndrome|disease|sequence|association|spectrum|dysplasia)\b", " ", s)
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9\s]", " ", s)).strip()


def index_syndromes(c):
    idx = {}
    for sid, fr, en, al in c.execute("select id, name_fr, name_en, aliases from syndromes"):
        for f in [fr, en] + [x.strip() for x in (al or "").split("|") if x.strip()]:
            k = norm(f)
            if k and k not in idx:
                idx[k] = sid
    return idx


def variantes(titre):
    """Formes a essayer pour un titre de livre, de la plus complete a la plus nue."""
    t = GROUPE.sub("", titre).strip()
    t = re.sub(r"\s*\((?:MIM|OMIM)[^)]*\)", "", t).strip()   # « (MIM 187600, 187601) » n'est pas un nom
    out = [t, PARENTH.sub("", t)]
    # Spranger : « Thanatophoric Dysplasia, Types 1 and 2 » -> essayer aussi avant la virgule
    if "," in t:
        out.append(t.split(",")[0].strip())
    m = re.search(r"\(([^)]+)\)", t)
    if m:
        # la parenthese liste souvent PLUSIEURS synonymes separes par des virgules :
        # « (Cornelia De Lange Syndrome, De Lange Syndrome) » -> deux formes a essayer
        out += [x.strip() for x in re.split(r"[,;/]", m.group(1)) if x.strip()]
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()
    c = sqlite3.connect(DB)
    idx = index_syndromes(c)

    # Les chapitres de Spranger sont des FAMILLES (« Dysplasias With Predominant
    # Metaphyseal Involvement »), pas des syndromes : ne pas les compter comme
    # des appariements rates. Le niveau est porte en colonne (PREFECT foeto_base
    # 5346afe04b4f : famille -> syndrome -> signe).
    rows = c.execute("""select livre, fichier, syndrome_titre, signe, verbatim, frequence,
                               niveau, region, hpo_id, hpo_methode, modalite
                        from syndrome_signes_livres_candidats
                        where verbatim_ok=1 and hpo_id is not null""").fetchall()

    out, stats, non_app = [], Counter(), Counter()
    for livre, fichier, titre, signe, verbatim, freq, niveau, region, hpo, meth, modalite in rows:
        niveau_entree = "famille" if livre == "spranger" else "syndrome"
        # l'extraction par section suffixait le titre « [clinique] » / « [radiographique] » :
        # la modalite est une COLONNE, le titre reste celui de l'entite (2026-09-12)
        titre = re.sub(r"\s*\[(clinique|radiographique)\]\s*$", "", titre)
        sid = None
        for v in variantes(titre):
            sid = idx.get(norm(v))
            if sid:
                break
        if niveau_entree == "famille":
            stats["famille (Spranger)"] += 1
        else:
            stats["apparie" if sid else "non apparie"] += 1
            if not sid:
                non_app[titre] += 1
        est_parent = 1 if (hpo or "").startswith("PARENT:") else 0
        for h in (hpo or "").replace("PARENT:", "").split("+"):
            if h.startswith("HP:"):
                out.append((sid, titre, niveau_entree, h, livre, fichier, signe, verbatim,
                            freq, niveau, region, est_parent, meth, modalite))
                stats["liens"] += 1

    print(f"{len(rows)} signes codes -> {stats['liens']} liens syndrome x HPO")
    print(f"  entrees de niveau FAMILLE (Spranger)       : {stats['famille (Spranger)']}")
    print(f"  entrees appariees a un syndrome de la base : {stats['apparie']}")
    print(f"  non appariees (titre conserve)             : {stats['non apparie']}")
    print(f"  syndromes distincts non apparies           : {len(non_app)}")
    print("\nles 10 titres non apparies les plus fournis :")
    for t, n in non_app.most_common(10):
        print(f"  {n:4d}  {t[:66]}")

    if a.apply:
        c.execute("DROP TABLE IF EXISTS syndrome_hpo_livres")
        c.execute("""CREATE TABLE syndrome_hpo_livres (
            id INTEGER PRIMARY KEY,
            syndrome_id TEXT REFERENCES syndromes(id),   -- NULL si pas encore apparie
            syndrome_titre TEXT NOT NULL,                -- titre du livre, toujours present
            niveau_entree TEXT NOT NULL,                 -- famille (Spranger) | syndrome (Smith)
            hpo_id TEXT NOT NULL REFERENCES hpo_terms(hpo_id),
            livre TEXT NOT NULL, entree TEXT NOT NULL,
            signe_livre TEXT NOT NULL, verbatim TEXT NOT NULL,
            frequence TEXT,                              -- seulement si le livre chiffre
            niveau TEXT,                                 -- principal | occasionnel | texte
            region TEXT,
            est_parent INTEGER NOT NULL DEFAULT 0,       -- noeud d'arborescence, pas le signe brut
            methode TEXT,
            modalite TEXT,                               -- clinique | radiographique (Spranger) | NULL (Smith)
            cree_le TEXT NOT NULL DEFAULT (datetime('now')))""")
        c.executemany("""INSERT INTO syndrome_hpo_livres
            (syndrome_id, syndrome_titre, niveau_entree, hpo_id, livre, entree, signe_livre,
             verbatim, frequence, niveau, region, est_parent, methode, modalite)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", out)
        c.execute("CREATE INDEX idx_shl_syndrome ON syndrome_hpo_livres(syndrome_id)")
        c.execute("CREATE INDEX idx_shl_hpo ON syndrome_hpo_livres(hpo_id)")
        c.execute("CREATE INDEX idx_shl_titre ON syndrome_hpo_livres(syndrome_titre)")
        c.commit()
        n, s, h, f = c.execute("""select count(*), count(distinct syndrome_titre),
                                  count(distinct hpo_id), sum(frequence is not null)
                                  from syndrome_hpo_livres""").fetchone()
        print(f"\nsyndrome_hpo_livres : {n} liens, {s} syndromes, {h} HPO distincts, {f} chiffres.")


if __name__ == "__main__":
    main()
