#!/usr/bin/env python3
"""Rattache les diagnostics des fiches (termes FOETO tagués verbatim, type DIA) à leur ORPHA.

Table foeto_dia_orpha (term_id, syndrome_id, methode) : l'akinator y lit quels liens de
fiche (foeto_edges, source « fiche » : critère, constant, exclut…) versent dans la
matrice syndrome × signe. Méthode « nom exact » (libellé = name_fr ou name_en, hors
précision entre parenthèses) ou « arbitrage » (liste ci-dessous, relue le 2026-09-28).
Écartés à l'arbitrage : Chiari (fiche = type II, candidat type I), OI 2A et 2B/3 (seul
l'OI générique existe), arthrogrypose distale (candidat 5D), PKDA (absente de syndromes).

  python3 v2/dia_orpha.py [--appliquer]
"""
import re
import sqlite3
import sys
import unicodedata
from pathlib import Path

DB = Path(__file__).parent.parent / "syndromes_foetaux.db"
ARBITRAGE = {
    "FOETO:PF.CER-MAL-016": "ORPHA:200", "FOETO:PF.CER-MAL-191": "ORPHA:51577",
    "FOETO:PF.DIG-INF-004": "ORPHA:391673", "FOETO:PF.SQU-MAL-166": "ORPHA:1865",
    "FOETO:PF.SQU-MAL-179": "ORPHA:93270", "FOETO:PF.SQU-MAL-180": "ORPHA:93269",
    "FOETO:PF.SQU-MAL-181": "ORPHA:93268", "FOETO:PF.FOI-MAL-072": "ORPHA:60",
    "FOETO:PF.FOI-MAL-018": "ORPHA:485426", "FOETO:PF.MUS-RET-014": "ORPHA:2020",
    "FOETO:PF.MUS-MAL-027": "ORPHA:597", "FOETO:PF.MUS-MAL-028": "ORPHA:596",
    "FOETO:PF.MUS-MAL-029": "ORPHA:171430", "FOETO:PF.MUS-MAL-033": "ORPHA:273",
    "FOETO:PF.ORL-MAL-083": "ORPHA:782", "FOETO:PF.ORL-MAL-085": "ORPHA:293603",
    "FOETO:PF.ORL-INF-007": "ORPHA:293", "FOETO:PF.ORL-INF-014": "ORPHA:293",
    "FOETO:PF.ORL-MAL-092": "ORPHA:290", "FOETO:PF.ORL-INF-009": "ORPHA:858",
    "FOETO:PF.END-MAL-079": "ORPHA:657", "FOETO:PF.END-MAL-082": "ORPHA:294415",
    "FOETO:PF.FOI-MAL-077": "ORPHA:98473", "FOETO:PF.REN-MAL-083": "ORPHA:98473",
    "FOETO:PF.HEM-MAL-049": "ORPHA:116", "FOETO:PF.REN-MAL-114": "ORPHA:322",
    "FOETO:PF.REN-MAL-115": "ORPHA:2241", "FOETO:PF.REN-MAL-118": "ORPHA:2970",
    "FOETO:PF.REN-MAL-084": "ORPHA:93111", "FOETO:PF.REN-DYS-001": "ORPHA:3033",
    # CMV congénital : le rapprochement de noms proposait « entérovirus » — faux
    "FOETO:PF.FOI-INF-005": "ORPHA:294", "FOETO:PF.ORL-INF-006": "ORPHA:294",
    "FOETO:PF.ORL-INF-015": "ORPHA:294", "FOETO:PF.END-INF-004": "ORPHA:294",
    "FOETO:PF.END-INF-006": "ORPHA:294", "FOETO:PF.END-INF-012": "ORPHA:294",
    "FOETO:PF.REN-INF-002": "ORPHA:294",
}


def cle(s):
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower()
    s = re.split(r" \(| — ", s)[0]
    s = re.sub(r"\b(syndrome|de|du|des|la|le|les|d|l|type)\b", " ", re.sub(r"[^a-z0-9 ]", " ", s))
    return " ".join(s.split())


def main(appliquer):
    c = sqlite3.connect(DB if appliquer else "file:%s?mode=ro" % DB, uri=not appliquer)
    dia = list(c.execute("select t.id, t.label_fr from foeto_terms t join foeto_v2_import m on m.v1_id = t.id "
                         "where m.v2_id like '%-DIA-%'"))
    noms = {}
    for i, fr, en in c.execute("select id, name_fr, name_en from syndromes"):
        for x in (fr, en):
            if x:
                noms.setdefault(cle(x), set()).add(i)
    orpha = {r[0] for r in c.execute("select id from syndromes")}
    lignes = []
    for t, l in dia:
        if t in ARBITRAGE:
            assert ARBITRAGE[t] in orpha, ARBITRAGE[t]
            lignes.append((t, ARBITRAGE[t], "arbitrage"))
        elif len(noms.get(cle(l), ())) == 1:
            lignes.append((t, next(iter(noms[cle(l)])), "nom exact"))
    print("%d diagnostics de fiche, %d rattachés à un ORPHA (%d nom exact, %d arbitrage)" % (
        len(dia), len(lignes), sum(m == "nom exact" for *_, m in lignes), sum(m == "arbitrage" for *_, m in lignes)))
    if appliquer:
        c.execute("create table if not exists foeto_dia_orpha (term_id text, syndrome_id text, methode text, "
                  "primary key (term_id, syndrome_id))")
        c.execute("delete from foeto_dia_orpha")
        c.executemany("insert into foeto_dia_orpha values (?,?,?)", lignes)
        c.commit()


if __name__ == "__main__":
    main("--appliquer" in sys.argv)
