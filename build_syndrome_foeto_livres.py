#!/usr/bin/env python3
"""syndrome_foeto_livres : signes HISTOLOGIQUES attestes par les livres, par syndrome.

Source : arbitrage_micro_foeto.tsv (colonne choix) joint a
syndrome_micro_livres_candidats (verbatim, livre, chapitre, organe, attribution).
  choix = FOETO:...  -> foeto_id renseigne
  choix = NOUVEAU    -> foeto_id NULL, le signe reste (libelle du livre) : la fiche
                        l'affiche comme « terme a creer »
  choix = NON        -> ecarte
Propagation de l'histologie de GROUPE (niveau='famille', jamais confondue avec
une attestation directe) :
  FAM:xxxx  -> membres de syndrome_family_members (par ORPHA)
  SPRFAM:N  -> entites Spranger « N.x » (par titre)
age : GeneReviews = 'postnatal' (biopsie, pas lame foetale), le reste 'foetal'.
Ne touche jamais syndrome_foeto / syndrome_foeto_v2 (synthetiques).

Usage : python3 build_syndrome_foeto_livres.py
"""
import csv
import re
import sqlite3

DB = "/home/mathevet/Bureau/foeto_base/syndromes_foetaux.db"
TSV = "/home/mathevet/Bureau/foeto_base/arbitrage_micro_foeto.tsv"


def main():
    c = sqlite3.connect(DB)
    c.execute("drop table if exists syndrome_foeto_livres")
    c.execute("""create table syndrome_foeto_livres (
        id integer primary key,
        syndrome_titre text,          -- titre d'entree (fiches) ; NULL pour un membre de famille par ORPHA
        syndrome_id text,             -- ORPHA si rattache
        foeto_id text references foeto_terms(id),   -- NULL = terme a creer
        signe text, verbatim text, livre text, chapitre text, organe text,
        niveau text check(niveau in ('direct','contexte','famille')),
        age text check(age in ('foetal','postnatal')),
        famille text,                 -- id + nom du groupe pour niveau='famille'
        statut text default 'arbitrage_ia',
        candidat_id integer)""")
    cand = {r[0]: r[1:] for r in c.execute(
        "select id, syndrome_titre, syndrome_id, livre, chapitre, organe, attribution, signe, verbatim from syndrome_micro_livres_candidats")}
    membres = {}
    for fid, sid in c.execute("select family_id, syndrome_id from syndrome_family_members"):
        membres.setdefault(fid, []).append(sid)
    noms = dict(c.execute("select family_id, family_name from syndrome_families"))
    titres_spr = [r[0] for r in c.execute("select distinct syndrome_titre from syndrome_hpo_livres where livre='spranger_entites'")]
    n_dir = n_fam = n_new = 0
    for x in csv.DictReader(open(TSV, encoding="utf-8"), delimiter="\t"):
        ch = x["choix"].strip()
        if ch == "NON" or not ch:
            continue
        foeto = ch if ch.startswith("FOETO:") else None
        n_new += foeto is None
        titre, sid, livre, chap, organe, attr, signe, verb = cand[int(x["id"])]
        age = "postnatal" if livre == "genereviews" else "foetal"
        base = (foeto, signe, verb, livre, chap, organe, age, int(x["id"]))
        if sid and sid.startswith("FAM:"):
            fam = f"{sid} {noms.get(sid, '')}"
            for m in membres.get(sid, []):
                c.execute("insert into syndrome_foeto_livres(syndrome_titre,syndrome_id,foeto_id,signe,verbatim,livre,chapitre,organe,niveau,age,famille,candidat_id) values(?,?,?,?,?,?,?,?,?,?,?,?)",
                          (None, m, *base[:6], "famille", age, fam, base[7]))
                n_fam += 1
        elif sid and sid.startswith("SPRFAM:"):
            num = sid.split(":")[1]
            fam = f"{sid} {titre}"
            for t in titres_spr:
                if re.match(rf"^{num}\.\d+\s", t):
                    c.execute("insert into syndrome_foeto_livres(syndrome_titre,syndrome_id,foeto_id,signe,verbatim,livre,chapitre,organe,niveau,age,famille,candidat_id) values(?,?,?,?,?,?,?,?,?,?,?,?)",
                              (t, None, *base[:6], "famille", age, fam, base[7]))
                    n_fam += 1
        else:
            c.execute("insert into syndrome_foeto_livres(syndrome_titre,syndrome_id,foeto_id,signe,verbatim,livre,chapitre,organe,niveau,age,famille,candidat_id) values(?,?,?,?,?,?,?,?,?,?,?,?)",
                      (titre, sid, *base[:6], "contexte" if attr == "contexte" else "direct", age, None, base[7]))
            n_dir += 1
    c.execute("create index if not exists idx_sfl_titre on syndrome_foeto_livres(syndrome_titre)")
    c.execute("create index if not exists idx_sfl_sid on syndrome_foeto_livres(syndrome_id)")
    c.commit()
    ns = c.execute("select count(distinct coalesce(syndrome_titre, syndrome_id)) from syndrome_foeto_livres").fetchone()[0]
    nf = c.execute("select count(distinct coalesce(syndrome_titre, syndrome_id)) from syndrome_foeto_livres where niveau='famille'").fetchone()[0]
    print(f"{n_dir} lignes directes/contexte ({n_new} sans terme FOETO), {n_fam} lignes de famille -> "
          f"{ns} entités couvertes ({nf} par famille seulement ou aussi)")
    for l, k in c.execute("select livre, count(*) from syndrome_foeto_livres group by 1 order by 2 desc"):
        print(f"  {l:18s} {k}")


if __name__ == "__main__":
    main()
