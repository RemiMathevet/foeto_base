#!/usr/bin/env python3
"""Debut de manifestation d'un chapitre GeneReviews, lu dans son TEXTE clinique.

553 des 781 entites decrites par GeneReviews seul n'ont pas d'age Orphanet, et la
part de signes dans le filtre foetal ne discrimine rien (mediane 0,55 partout).
Ici : on compte, dans les sections cliniques (memes RX_GR_CLIN / RX_GR_HORS que
l'extraction), les marqueurs prenataux/neonataux et les marqueurs tardifs ;
la preuve est la phrase du livre qui porte le marqueur (extraits).
  verdict = prenatal   >= 3 marqueurs prenataux et plus que de tardifs
            postnatal  aucun marqueur prenatal (a 1-2 : Shprintzen-Goldberg, EB simplex — on garde)
            incertain  sinon
Table genereviews_debut (slug, titre, n_prenatal, n_tardif, verdict, extraits).
Orphanet, quand il a un age, prime (build_entites_livres).

Usage : python3 onset_genereviews.py
"""
import json
import re
import sqlite3

from extract_signes_livres import RX_GR_CLIN, RX_GR_HORS

DB = "/home/mathevet/Bureau/foeto_base/syndromes_foetaux.db"
RX_PRE = re.compile(r"\b(prenatal(?:ly)?|antenatal(?:ly)?|fetal|fetus(?:es)?|in utero|ultrasound|sonograph\w*|at birth|newborns?|neonat\w+|"
                    r"congenital(?:ly)?|stillb\w+|perinatal(?:ly)?|polyhydramnios|hydrops|birth weight|lethal)\b", re.I)
RX_TARD = re.compile(r"\b(adult(?:s|hood)?|adolescen\w+|(?:second|third|fourth|fifth|sixth) decade|later in life|late[- ]onset|"
                     r"juvenile|(?:[2-9]|\d{2}) years of age|teen\w*)\b", re.I)


def main():
    c = sqlite3.connect(DB)
    c.execute("drop table if exists genereviews_debut")
    c.execute("create table genereviews_debut (slug text primary key, titre text, n_prenatal integer, n_tardif integer, verdict text, extraits text)")
    k = {"prenatal": 0, "postnatal": 0, "incertain": 0}
    for slug, title, sj in c.execute("select slug, title, sections_json from genereviews_full"):
        secs = [x for x in json.loads(sj or "[]") if RX_GR_CLIN.search(x["path"]) and not RX_GR_HORS.search(x["path"].split(">")[-1])]
        txt = " ".join(x["text"] for x in secs)
        pre, tard = RX_PRE.findall(txt), RX_TARD.findall(txt)
        verdict = "prenatal" if len(pre) >= 3 and len(pre) > len(tard) else ("postnatal" if not pre else "incertain")
        # la preuve : jusqu'a 3 phrases du livre portant un marqueur prenatal
        phrases = [p.strip() for p in re.split(r"(?<=[.;])\s+", txt) if RX_PRE.search(p)][:3]
        c.execute("insert into genereviews_debut values(?,?,?,?,?,?)",
                  (slug, title.replace(" - GeneReviews® - NCBI Bookshelf", "").strip(), len(pre), len(tard), verdict, " | ".join(phrases)[:1500]))
        k[verdict] += 1
    c.commit()
    print(f"{sum(k.values())} chapitres : {k}")
    for v in ("prenatal", "postnatal"):
        print(f"  {v}:", " ; ".join(t[:38] for t, in c.execute("select titre from genereviews_debut where verdict=? order by random() limit 6", (v,))))


if __name__ == "__main__":
    main()
