#!/usr/bin/env python3
"""Une ENTITE = un syndrome, quel que soit le nombre de livres qui le decrivent.

Le meme syndrome existait autant de fois que d'entrees de livres (thanatophore :
Smith, Spranger, GeneReviews), sous des titres differents : dans l'onglet
Familles il apparaissait en double, ses « discriminants » etaient les signes qu'un
livre cite et pas l'autre, et son plus proche voisin etait lui-meme (Remi,
2026-09-13). Ici on resout l'identite, deterministe :
  entite_id = ORPHA quand l'entree en a un (deja pose : MIM, noms, arbitrages)
            = NOM:<titre normalise sans prefixe/parenthese/type> sinon — deux
              entrees sans ORPHA de deux livres au meme nom fusionnent
Tables : entites_livres (entite_id, nom, orpha, n_titres, livres, debut, foetale) et
entites_livres_titres (entite_id, livre, syndrome_titre, entree).
debut = ages Orphanet (ages_of_onset) sinon le verdict lexical du texte GeneReviews
(genereviews_debut) ; foetale = 0 quand ce debut exclut le prenatal/neonatal
(Orphanet sans Prenatal/Neonatal, ou GeneReviews sans aucun marqueur prenatal),
1 sinon — ne s'applique qu'aux entites decrites par GeneReviews SEUL : Smith,
Spranger et limb sont les corpus de reference, on ne les ecarte pas (Angelman,
Kozlowski, 49,XXXXY ont un age Orphanet « Petite enfance » et restent). La parente, les
familles et les fiches foetales du hub ignorent foetale = 0.
build_parente_livres, famille_signes et render_fiche_entite lisent l'entite.

Usage : python3 build_entites_livres.py
"""
import json
import re
import sqlite3
import unicodedata
from collections import defaultdict

DB = "/home/mathevet/Bureau/foeto_base/syndromes_foetaux.db"


def norm(s):
    s = "".join(ch for ch in unicodedata.normalize("NFD", (s or "").lower()) if unicodedata.category(ch) != "Mn")
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9\s]", " ", s)).strip()


def cle_nom(titre):
    t = re.sub(r"^(?:[A-W]|\d+(?:\.\d+)?)\s+", "", titre)               # « K », « 1.1 », « 14 »
    t = re.sub(r"\s*\((?:MIM|OMIM)[^)]*\)", "", t)
    t = re.sub(r"\(.*?\)", "", t)
    # la virgule porte souvent le TYPE (« Mesomelic Dysplasia, Kantaputra Type ») : on la garde
    t = re.sub(r"\b(syndrome|sequence|association|disease|disorder)s?\b", "", t, flags=re.I)
    k = norm(t)
    return "NOM:" + (k or norm(titre))


def main():
    c = sqlite3.connect(DB)
    rows = c.execute("""select distinct livre, syndrome_titre, syndrome_id, entree from syndrome_hpo_livres
                        where niveau_entree='syndrome'""").fetchall()
    noms_orpha = dict(c.execute("select id, coalesce(name_fr, name_en) from syndromes"))
    ages = {}
    for sid, a in c.execute("select id, ages_of_onset from syndromes where ages_of_onset not in ('', '[]')"):
        try:
            ages[sid] = ", ".join(json.loads(a))
        except Exception:
            ages[sid] = a
    gr_debut = {s: v for s, v in c.execute("select slug, verdict from genereviews_debut")} if c.execute(
        "select 1 from sqlite_master where name='genereviews_debut'").fetchone() else {}
    GR_FR = {"prenatal": "Prénatal/Néonatal (GeneReviews, texte)", "postnatal": "Postnatal (GeneReviews, texte)", "incertain": "Incertain (GeneReviews, texte)"}

    def debut_de(key, ts):
        gr_seul = all(l == "genereviews" for l, _, _ in ts)
        if key in ages:
            return ages[key], int(not gr_seul or "Prénatal" in ages[key] or "Néonatal" in ages[key] or "Tous âges" in ages[key])
        v = [gr_debut[e.split("#")[0]] for l, _, e in ts if l == "genereviews" and e.split("#")[0] in gr_debut]
        if v and gr_seul:
            best = "prenatal" if "prenatal" in v else ("incertain" if "incertain" in v else "postnatal")
            return GR_FR[best], int(best != "postnatal")
        return (GR_FR[v[0]] if v else None), 1
    groupes = defaultdict(list)
    for livre, titre, sid, entree in rows:
        key = sid if sid else cle_nom(titre)
        groupes[key].append((livre, titre, entree))
    c.execute("drop table if exists entites_livres_titres")
    c.execute("drop table if exists entites_livres")
    c.execute("create table entites_livres (entite_id text primary key, nom text, orpha text, n_titres integer, livres text, debut text, foetale integer)")
    c.execute("create table entites_livres_titres (entite_id text, livre text, syndrome_titre text, entree text)")
    for key, ts in groupes.items():
        titres = sorted({t for _, t, _ in ts})
        livres = sorted({l for l, _, _ in ts})
        # nom d'affichage : Orphanet si ORPHA, sinon le titre de Smith de preference, sans prefixe
        if key.startswith("ORPHA:"):
            nom = noms_orpha.get(key) or re.sub(r"^(?:[A-W]|\d+(?:\.\d+)?)\s+", "", titres[0])
        else:
            pref = [t for l, t, _ in ts if l == "smith"] or titres
            nom = re.sub(r"^(?:[A-W]|\d+(?:\.\d+)?)\s+", "", pref[0])
        debut, foet = debut_de(key, ts)
        c.execute("insert into entites_livres values(?,?,?,?,?,?,?)", (key, nom, key if key.startswith("ORPHA:") else None, len(titres), ",".join(livres), debut, foet))
        for livre, titre, entree in sorted({(l, t, e.split("#")[0]) for l, t, e in ts}):   # Spranger : #clinique / #radiographique = une entrée
            c.execute("insert into entites_livres_titres values(?,?,?,?)", (key, livre, titre, entree))
    c.execute("create index idx_elt_titre on entites_livres_titres(syndrome_titre)")
    c.commit()
    n = c.execute("select count(*) from entites_livres").fetchone()[0]
    multi = c.execute("select count(*) from entites_livres where n_titres > 1").fetchone()[0]
    sans = c.execute("select count(*) from entites_livres where orpha is null").fetchone()[0]
    fus_nom = c.execute("select count(*) from entites_livres where orpha is null and n_titres > 1").fetchone()[0]
    nf = c.execute("select count(*) from entites_livres where foetale=0").fetchone()[0]
    nd = c.execute("select count(*) from entites_livres where debut is null").fetchone()[0]
    print(f"{len(rows)} entrées de livres -> {n} entités ; {multi} décrites par plusieurs livres ; "
          f"{sans} sans ORPHA dont {fus_nom} fusionnées par le nom ; {nf} non fœtales (écartées), {nd} sans début connu")
    for e, nom, k, l in c.execute("select entite_id, nom, n_titres, livres from entites_livres where n_titres >= 3 order by n_titres desc limit 6"):
        print(f"  {e:14s} {nom[:40]:40s} {k} entrées ({l})")


if __name__ == "__main__":
    main()
