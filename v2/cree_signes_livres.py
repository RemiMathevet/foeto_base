#!/usr/bin/env python3
"""Crée dans FOETO les signes histologiques des livres restés NOUVEAU (2026-09-28).

Entrée : arbitrage_micro_foeto.tsv (choix = NOUVEAU) — signes copiés des livres par
le 35B, verbatim vérifié contre le passage — et v2/signes_livres_decisions.py
(rattachement à un terme existant, doublon, ou terme à créer : organe, type, libellé fr).
Effet : termes créés (numéro suivant de leur série), tagués « verbatim », verbatims de
livre dans foeto_verbatims, correspondance dans foeto_v2_import (clé LIVRE:…,
idempotent), et choix du TSV mis à jour — build_syndrome_foeto_livres.py à relancer.

  python3 v2/cree_signes_livres.py              # simulation
  python3 v2/cree_signes_livres.py --appliquer  # sauvegarde puis écriture
"""
import csv
import datetime as dt
import re
import sqlite3
import sys
import unicodedata
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from signes_livres_decisions import D  # noqa: E402

BASE = Path(__file__).parent.parent
DB = BASE / "syndromes_foetaux.db"
TSV = BASE / "arbitrage_micro_foeto.tsv"
ORGANE_V1 = {"CER": "cerveau", "COE": "coeur", "SQU": "squelette", "HEM": "hematolymphoide", "ORL": "oeil_oreille",
             "PEA": "peau", "DIG": "digestif", "REN": "rein", "FOI": "foie", "POU": "poumon", "GEN": "genital",
             "MUS": "muscle", "MUL": "multi_organe", "END": "endocrine",
             "PP.PLA": "placenta", "PP.MEM": "membranes", "PP.COR": "cordon"}


def n(s):
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower()
    return " ".join(re.sub(r"[^a-z0-9 ]", " ", s).split())


def resout(i, vus=()):
    d = D[i]
    if isinstance(d, str) and d.startswith(">"):
        j = int(d[1:])
        assert j not in vus, "cycle %s" % i
        return resout(j, vus + (i,))
    return i, d


def main(appliquer):
    rows = list(csv.DictReader(open(TSV, encoding="utf-8"), delimiter="\t"))
    champs = list(rows[0].keys())
    groupes = {}
    for r in rows:
        if r["choix"] == "NOUVEAU":
            groupes.setdefault((r["organe_llm"].lower(), n(r["signe"])), []).append(r)
    if not groupes:
        print("aucun signe NOUVEAU : rien à créer")
        return
    cles = sorted(groupes, key=lambda k: (k[0], n(groupes[k][0]["signe"])))
    assert len(cles) == len(D), "la liste a changé (%d signes, %d décisions) : refaire les décisions" % (len(cles), len(D))

    c = sqlite3.connect(DB if appliquer else "file:%s?mode=ro" % DB, uri=not appliquer)
    existants = {r[0] for r in c.execute("select id from foeto_terms")}
    seq = {}
    for (i,) in c.execute("select id from foeto_terms where id like 'FOETO:PF.%' or id like 'FOETO:PP.%'"):
        m = re.fullmatch(r"FOETO:(PF|PP)\.([A-Z]+)-([A-Z]+)-(\d+)", i)
        if m:
            k = (m[2] if m[1] == "PF" else "PP." + m[2], m[3])
            seq[k] = max(seq.get(k, 0), int(m[4]))
    deja = dict(c.execute("select v2_id, v1_id from foeto_v2_import where v2_id like 'LIVRE:%'"))

    cible, nouveaux = {}, {}
    for idx in range(len(cles)):
        racine, d = resout(idx)
        if isinstance(d, str):
            assert d.startswith("=FOETO:") and d[1:] in existants, d
            cible[idx] = d[1:]
            continue
        cle_import = "LIVRE:%s|%s" % cles[racine]
        if cle_import in deja:
            cible[idx] = deja[cle_import]
        elif racine in nouveaux:
            cible[idx] = nouveaux[racine][0]
        else:
            org, typ, lib = d
            seq[(org, typ)] = seq.get((org, typ), 0) + 1
            pref = org if org.startswith("PP.") else "PF." + org
            nid = "FOETO:%s-%s-%03d" % (pref, typ, seq[(org, typ)])
            nouveaux[racine] = (nid, org, typ, lib, cle_import)
            cible[idx] = nid
    print("%d signes → %d termes créés, %d rattachés à un terme existant, %d doublons de la liste"
          % (len(cles), len(nouveaux), sum(isinstance(D[i], str) and D[i].startswith("=") for i in D),
             sum(isinstance(D[i], str) and D[i].startswith(">") for i in D)))
    if not appliquer:
        for nid, org, typ, lib, _ in list(nouveaux.values())[:8]:
            print("  ", nid, lib)
        print("simulation — rien n'est écrit")
        return

    bak = DB.with_name(DB.name + ".bak_%s_signes_livres" % dt.datetime.now().strftime("%Y%m%d_%H%M%S"))
    b = sqlite3.connect(bak)
    c.backup(b)
    b.close()
    print("sauvegarde :", bak)
    today = dt.date.today().isoformat()
    for racine, (nid, org, typ, lib, cle_import) in nouveaux.items():
        grp = groupes[cles[racine]]
        livres = "|".join(sorted({"%s %s" % (r["livre"], r["chapitre"]) for r in grp}))
        c.execute("""insert into foeto_terms (id, organe, label_fr, label_en, axis, sources, type_new, domain)
                     values (?,?,?,?,?,?,?,?)""",
                  (nid, ORGANE_V1[org], lib, grp[0]["signe"], "architecture" if typ == "NOR" else "pathologie",
                   livres, typ, "placenta" if org.startswith("PP.") else "foetus"))
        c.execute("insert or ignore into foeto_v2_import values (?,?,?,?)", (cle_import, nid, "livre", today))
    for idx, tid in cible.items():
        c.execute("insert or ignore into foeto_tags values (?, 'verbatim')", (tid,))
        for r in groupes[cles[idx]]:
            c.execute("insert or ignore into foeto_verbatims values (?,?,?,?,?)",
                      (tid, None, "%s, %s" % (r["livre"], r["chapitre"]), r["verbatim"], "livre"))
            r["choix"] = tid
    c.commit()
    w = csv.DictWriter(open(TSV, "w", encoding="utf-8", newline=""), fieldnames=champs, delimiter="\t",
                       lineterminator="\n")
    w.writeheader()
    w.writerows(rows)
    print("appliqué : %d termes créés ; TSV mis à jour — relancer build_syndrome_foeto_livres.py" % len(nouveaux))


if __name__ == "__main__":
    main("--appliquer" in sys.argv)
