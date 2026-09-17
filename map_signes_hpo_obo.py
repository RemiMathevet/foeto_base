#!/usr/bin/env python3
"""Mapping signes de livres -> HPO en s'appuyant sur l'ONTOLOGIE OFFICIELLE
(hp.obo), et non sur nos seuls label_en/aliases_fr.

Pourquoi : hpo_terms ne porte ni definition ni portee de synonyme. hp.obo
declare 24 217 synonymes avec leur PORTEE, et c'est la portee qui decide :

  EXACT    meme concept          -> mapping sur
  NARROW   le synonyme est PLUS PRECIS que le terme HPO
  BROAD    le synonyme est PLUS LARGE  -> terme-parapluie : on pose le PARENT
                                          d'arborescence, pas le signe brut
  RELATED  voisin, pas equivalent -> JAMAIS automatique, arbitrage a la main

Sans cette distinction on ecrirait des faux : « low nasal bridge » est bien
EXACT sur HP:0005280 (HPO le declare, portee layperson), mais rien ne garantit
qu'il en aille de meme du suivant. Le doute se leve en lisant def: et comment:,
qui sont exportes dans le TSV d'arbitrage.

Ne fait AUCUN cosinus : un hpo_id faux coute plus cher qu'un trou.

Usage :
  python3 map_signes_hpo_obo.py                 mesure seule
  python3 map_signes_hpo_obo.py --tsv out.tsv   + table d'arbitrage des non mappes
  python3 map_signes_hpo_obo.py --apply         ecrit hpo_id / hpo_methode / hpo_portee
"""
import argparse
import re
import unicodedata
import sqlite3
from collections import Counter, defaultdict

DB = "/home/mathevet/Bureau/foeto_base/syndromes_foetaux.db"
OBO = "/home/mathevet/Bureau/akinator/orphadata_cache/hp.obo"

STOP = {"of", "the", "a", "an", "with", "or", "and", "in", "to", "at"}
QUALIF = re.compile(r"\b(severe|mild|moderate|marked|slight|profound|progressive|"
                    r"bilateral|unilateral|generalized|diffuse|partial|complete|congenital|variable)\b")


def norm(s):
    s = (s or "").lower().strip()
    s = re.sub(r"\(.*?\)", " ", s)
    # replier les diacritiques au lieu de les supprimer : [^a-z0-9] transformait
    # « kleeblattschädel » en « kleeblattsch del » et « macrocéphalie » en
    # « macroc phalie ». 40 % des 55 646 formes de hpo_synonymes etaient touchees
    # — dont tout le francais accentue (2026-09-12).
    s = "".join(ch for ch in unicodedata.normalize("NFD", s)
                if unicodedata.category(ch) != "Mn")
    s = re.sub(r"[^a-z0-9\s-]", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def toks(s):
    return frozenset(re.sub(r"(ies|s)$", lambda m: "y" if m.group() == "ies" else "", w)
                     for w in norm(s).split() if w not in STOP)


def load_obo(path):
    """{hpo_id: {name, definition, comment, parents[], syn:{forme: portee}}}"""
    terms, cur = {}, None
    for line in open(path, encoding="utf-8"):
        line = line.rstrip("\n")
        if line == "[Term]":
            if cur and cur["id"]:            # un nouveau [Term] n'ecrasait pas
                terms[cur["id"]] = cur       # le precedent : 19 943 termes perdus
            cur = {"id": None, "name": "", "def": "", "comment": "", "parents": [], "syn": {}, "obsolete": False}
        elif line.startswith("[") and cur:
            if cur["id"]:
                terms[cur["id"]] = cur
            cur = None
        elif cur is not None:
            if line.startswith("id: HP:"):
                cur["id"] = line[4:].strip()
            elif line.startswith("name: "):
                cur["name"] = line[6:].strip()
                cur["obsolete"] = cur["name"].startswith("obsolete ")
            elif line.startswith("def: "):
                m = re.match(r'def: "(.*)"', line)
                cur["def"] = m.group(1) if m else ""
            elif line.startswith("comment: "):
                cur["comment"] = line[9:].strip()
            elif line.startswith("is_a: HP:"):
                cur["parents"].append(line[6:].split("!")[0].strip())
            elif line.startswith("synonym: "):
                m = re.match(r'synonym: "(.*?)"\s+(EXACT|NARROW|BROAD|RELATED)', line)
                if m:
                    cur["syn"][m.group(1)] = m.group(2)
            elif line.startswith("is_obsolete: true"):
                cur["obsolete"] = True
    if cur and cur["id"]:
        terms[cur["id"]] = cur
    return {k: v for k, v in terms.items() if not v["obsolete"]}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tsv")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--top", type=int, default=300, help="lignes de la table d'arbitrage")
    ap.add_argument("--livre", help="ne mapper que ce livre (les autres, déjà arbitrés, ne bougent pas)")
    a = ap.parse_args()

    obo = load_obo(OBO)
    c = sqlite3.connect(DB)
    foetal = {r[0] for r in c.execute(
        "select hpo_id from hpo_terms where context in ('prenatal','both') and is_excluded=0")}
    ours = {r[0]: (r[1], r[2]) for r in c.execute("select hpo_id, label_en, aliases_fr from hpo_terms")}

    # index forme -> (hpo_id, portee) ; le meilleur scope gagne
    RANK = {"NAME": 0, "EXACT": 1, "NARROW": 2, "BROAD": 3, "RELATED": 4}
    idx, idx_tok = {}, {}

    def put(form, hid, scope):
        n = norm(form)
        if not n:
            return
        prev = idx.get(n)
        if prev is None or RANK[scope] < RANK[prev[1]]:
            idx[n] = (hid, scope)
        t = toks(form)
        prev = idx_tok.get(t)
        if prev is None or RANK[scope] < RANK[prev[1]]:
            idx_tok[t] = (hid, scope)

    for hid, t in obo.items():
        put(t["name"], hid, "NAME")
        for form, scope in t["syn"].items():
            put(form, hid, scope)
    for hid, (en, al) in ours.items():            # nos alias FR par-dessus, en EXACT
        for form in [x.strip() for x in (al or "").split("|") if x.strip()]:
            put(form, hid, "EXACT")

    rows = c.execute("select id, signe, region from syndrome_signes_livres_candidats where verbatim_ok=1"
                     + (" and livre=?" if a.livre else ""), (a.livre,) if a.livre else ()).fetchall()
    out, stats, miss = [], Counter(), Counter()
    miss_region = defaultdict(Counter)
    related, related_cnt = {}, Counter()
    def cnt_region(r):
        return r or "?"
    for rid, signe, region in rows:
        n = norm(signe)
        # la meilleure portee parmi les trois voies, pas la premiere qui repond :
        # « renal cysts » est un synonyme RELATED (pluriel) de HP:0000107 dont le NOM
        # a exactement les memes mots — le NAME par tokens doit gagner
        hits = [h for h in (idx.get(n), idx.get(norm(QUALIF.sub(" ", n))), idx_tok.get(toks(signe))) if h]
        hit = min(hits, key=lambda h: RANK[h[1]]) if hits else None
        if not hit:
            stats["non mappé"] += 1
            miss[n] += 1
            miss_region[n][region or "?"] += 1
            continue
        hid, scope = hit
        stats[scope] += 1
        if scope == "RELATED":                 # voisin, jamais equivalent : a la main
            related[norm(signe)] = (cnt_region(region), hid)
            related_cnt[norm(signe)] += 1
            stats["à arbitrer"] += 1
            continue
        stats["fœtal" if hid in foetal else "hors filtre fœtal"] += 1
        out.append((hid, scope, rid))

    n = len(rows)
    print(f"{n} signes vérifiés, {len({s for _, s, _ in rows})} libellés distincts")
    print("  par portée du synonyme HPO :")
    for k in ("NAME", "EXACT", "NARROW", "BROAD", "RELATED", "non mappé"):
        if stats[k]:
            print(f"    {k:10s} {stats[k]:6d}  {stats[k]*100/n:5.1f} %")
    mapped = n - stats["non mappé"] - stats["à arbitrer"]
    print(f"  -> mappés {mapped:6d}  {mapped*100/n:5.1f} %   (dont {stats['fœtal']} dans le filtre fœtal, "
          f"{stats['hors filtre fœtal']} postnatal)")
    print(f"  hpo_id distincts : {len({h for h, _, _ in out})}")
    print(f"  non mappés : {stats['non mappé']} occurrences, {len(miss)} libellés")

    if a.tsv:
        with open(a.tsv, "w", encoding="utf-8") as f:
            f.write("signe_livre\toccurrences\tregion\tcandidat_hpo\tlabel_hpo\tportee_proposee\t"
                    "definition_hpo\tcommentaire_hpo\tdecision\n")
            lignes = [(s, cnt, None) for s, cnt in miss.most_common(a.top)]
            lignes += [(s, related_cnt[s], related[s][1]) for s in related]
            lignes.sort(key=lambda x: -x[1])
            for s, cnt, force in lignes:
                # meilleur candidat : recouvrement de tokens le plus fort
                ts = toks(s)
                best, score = None, 0.0
                if force:
                    t = obo.get(force, {})
                    reg = related[s][0]
                    f.write(f"{s}\t{cnt}\t{reg}\t{force}\t{t.get('name','')}\tRELATED (déclaré par HPO)\t"
                            f"{t.get('def','')[:300]}\t{t.get('comment','')[:200]}\t\n")
                    continue
                for form, (hid, scope) in idx.items():
                    tf = toks(form)
                    if not tf:
                        continue
                    j = len(ts & tf) / len(ts | tf)
                    if j > score:
                        best, score = (hid, form, scope), j
                reg = miss_region[s].most_common(1)[0][0]
                if best and score >= 0.4:
                    hid, form, scope = best
                    t = obo.get(hid, {})
                    f.write(f"{s}\t{cnt}\t{reg}\t{hid}\t{t.get('name','')}\t{scope} (j={score:.2f})\t"
                            f"{t.get('def','')[:300]}\t{t.get('comment','')[:200]}\t\n")
                else:
                    f.write(f"{s}\t{cnt}\t{reg}\t\t\t\t\t\t\n")
        print(f"\nTable d'arbitrage ({a.top} libellés) -> {a.tsv}")
        print("  colonne `decision` à remplir : l'hpo_id retenu, PARENT:<hpo_id> pour un "
              "terme-parapluie, ou NON si aucun terme ne convient.")

    if a.apply:
        cols = [r[1] for r in c.execute("pragma table_info(syndrome_signes_livres_candidats)")]
        for col in ("hpo_id", "hpo_methode", "hpo_portee"):
            if col not in cols:
                c.execute(f"alter table syndrome_signes_livres_candidats add column {col} TEXT")
        c.executemany("update syndrome_signes_livres_candidats set hpo_id=?, hpo_portee=?, hpo_methode='obo' where id=?", out)
        c.commit()
        print(f"\n{len(out)} lignes mises à jour.")


if __name__ == "__main__":
    main()
