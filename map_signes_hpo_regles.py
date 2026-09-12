#!/usr/bin/env python3
"""Reprise des signes de livres NON mappes (hpo_id NULL) par des regles lexicales
deterministes, apres map_signes_hpo_obo / decoupe_composites / arbitrages.

Regles, dans l'ordre, chacune tracee dans hpo_methode = 'regle:<nom>' :
  equiv     equivalences lexicales sures : encephalomeningocele / meningoencephalocele
            -> encephalocele, hypotonicity -> hypotonia, hypertonicity -> hypertonia,
            nostrils -> nares, singulier/pluriel du dernier mot
  qualif    retrait des mots de frequence / degre en tete (« some », « occasional »,
            « relative », « tendency to », « usually »…) puis des qualificatifs de
            map_signes_hpo_obo.QUALIF
  with      « X with Y » : X et Y mappes separement -> X+Y (les deux coexistent) ;
            un seul mappe -> celui-la, methode 'regle:with_partiel' (l'autre reste
            dans le libelle, verbatim intact)
  suffixe   suppression des 1 ou 2 premiers mots si le reste (>= 2 mots) est un
            NAME/EXACT : « marked ocular hypertelorism » -> « ocular hypertelorism ».
            PROPOSITION seule (TSV), jamais appliquee : le mot retire peut porter le
            sens (« absent » radius).
RELATED reste exclu partout. --apply ecrit equiv/qualif/with ; le TSV liste les
suffixes a arbitrer.

Usage : python3 map_signes_hpo_regles.py [--apply] [--tsv arbitrage_regles.tsv]
"""
import argparse
import re
import sqlite3
from collections import Counter

import map_signes_hpo_obo as O

EQUIV = [(r"\b(encephalomeningocele|meningoencephalocele|encephalomeningoceles)\b", "encephalocele"),
         (r"\bhypotonicity\b", "hypotonia"), (r"\bhypertonicity\b", "hypertonia"),
         (r"\bnostrils?\b", "nares"), (r"\bmeningomyelocele\b", "myelomeningocele"),
         (r"\bhyperextensibility\b", "hyperextensible"), (r"\bhyperextensible joints\b", "joint hypermobility"),
         (r"\bsimian crease\b", "single transverse palmar crease"), (r"\bmongoloid slant\b", "upslanted palpebral fissures"),
         (r"\bantimongoloid slant\b", "downslanted palpebral fissures")]
TETE = re.compile(r"^(some|occasional|occasionally|frequent|frequently|usually|often|rarely|rare|tendency to|tendency toward|"
                  r"relatively|relative|mildly|slightly|rather|early|late|later|apparent|apparently|variable|"
                  r"possible|possibly|may be|may have|sometimes|prominent|somewhat|minor|major)\s+")


def index(obo, ours):
    RANK = {"NAME": 0, "EXACT": 1, "NARROW": 2, "BROAD": 3, "RELATED": 4}
    idx, idx_tok = {}, {}
    def put(form, hid, scope):
        n = O.norm(form)
        if not n:
            return
        if idx.get(n) is None or RANK[scope] < RANK[idx[n][1]]:
            idx[n] = (hid, scope)
        t = O.toks(form)
        if idx_tok.get(t) is None or RANK[scope] < RANK[idx_tok[t][1]]:
            idx_tok[t] = (hid, scope)
    for hid, t in obo.items():
        put(t["name"], hid, "NAME")
        for form, scope in t["syn"].items():
            put(form, hid, scope)
    for hid, (en, al) in ours.items():
        for form in [x.strip() for x in (al or "").split("|") if x.strip()]:
            put(form, hid, "EXACT")
    return idx, idx_tok


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--tsv", default="/home/mathevet/Bureau/foeto_base/arbitrage_regles_suffixe.tsv")
    a = ap.parse_args()
    obo = O.load_obo(O.OBO)
    c = sqlite3.connect(O.DB)
    ours = {r[0]: (r[1], r[2]) for r in c.execute("select hpo_id, label_en, aliases_fr from hpo_terms")}
    idx, idx_tok = index(obo, ours)
    noms = {h: t["name"] for h, t in obo.items()}

    def lookup(s):
        """(hpo_id, portee) ou None ; RELATED exclu"""
        n = O.norm(s)
        hit = idx.get(n) or idx.get(O.norm(O.QUALIF.sub(" ", n))) or idx_tok.get(O.toks(s))
        return hit if hit and hit[1] != "RELATED" else None

    def singulier(s):
        return re.sub(r"(ies)$", "y", re.sub(r"(?<!s)s$", "", s)) if not s.endswith("ss") else s

    rows = c.execute("""select id, signe from syndrome_signes_livres_candidats
                        where verbatim_ok=1 and hpo_id is null and (hpo_methode is null or hpo_methode='')""").fetchall()
    res, stats, suff = [], Counter(), {}
    for rid, signe in rows:
        s = signe.strip().lower()
        hit, meth = None, None
        # equiv
        e = s
        for rx, rep in EQUIV:
            e = re.sub(rx, rep, e)
        for cand in {e, singulier(e), re.sub(r"(\w+)$", lambda m: m[1] + "s", e)}:
            if cand != s and (h := lookup(cand)):
                hit, meth = h, "equiv"; break
        # qualif
        if not hit:
            q = TETE.sub("", e)
            q = TETE.sub("", q)
            q2 = O.norm(O.QUALIF.sub(" ", q))
            for cand in {q, q2, singulier(q2)}:
                if cand and cand != s and (h := lookup(cand)):
                    hit, meth = h, "qualif"; break
        # with
        if not hit and " with " in e:
            x, y = [t.strip() for t in e.split(" with ", 1)]
            hx, hy = lookup(x) or lookup(TETE.sub("", x)), lookup(y) or lookup(TETE.sub("", y))
            if hx and hy:
                hit, meth = ((hx[0] + "+" + hy[0]), "with"), "with"
            elif hx or hy:
                hit, meth = (hx or hy), "with_partiel"
        if hit:
            res.append((hit[0], hit[1] if meth != "with" else "with", f"regle:{meth}", rid))
            stats[meth] += 1
            continue
        # suffixe : proposition
        mots = O.norm(e).split()
        for k in (1, 2):
            if len(mots) - k >= 2:
                cand = " ".join(mots[k:])
                h = idx.get(cand)
                if h and h[1] in ("NAME", "EXACT"):
                    suff.setdefault((O.norm(e), cand, h[0]), []).append(rid)
                    stats["suffixe (proposé)"] += 1
                    break
        else:
            stats["reste"] += 1
    print(f"{len(rows)} signes non mappés repris :")
    for k, v in stats.most_common():
        print(f"  {k:20s} {v}")
    with open(a.tsv, "w", encoding="utf-8") as f:
        f.write("signe\tsuffixe\thpo_id\tlabel_hpo\toccurrences\tchoix\n")
        for (s, cand, h), ids in sorted(suff.items(), key=lambda x: -len(x[1])):
            f.write(f"{s}\t{cand}\t{h}\t{noms.get(h, '')}\t{len(ids)}\t\n")
    print(f"propositions suffixe : {len(suff)} libellés -> {a.tsv}")
    if a.apply:
        c.executemany("update syndrome_signes_livres_candidats set hpo_id=?, hpo_portee=?, hpo_methode=? where id=?", res)
        c.commit()
        print(f"{len(res)} lignes écrites")


if __name__ == "__main__":
    main()
