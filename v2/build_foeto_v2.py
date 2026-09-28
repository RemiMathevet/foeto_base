#!/usr/bin/env python3
"""FOETO v2 — reconstruit foeto_v2.db depuis les sources curées, une par fiche.

  python3 v2/build_foeto_v2.py            # toutes les sources de v2/sources/
  python3 v2/build_foeto_v2.py rein       # une seule (la base est quand même refaite en entier)

La base est un artefact : elle est effacée et refaite à chaque passe.
Ce qui arrête la construction :
  · un verbatim introuvable mot pour mot dans la fiche (balisage markdown et
    blancs normalisés) ;
  · un lien, un négatif ou une correspondance qui vise un objet inexistant ;
  · un terme v1 de l'organe (syndromes_foetaux.db, lecture seule) absent de la
    correspondance, ou une correspondance vers un id v1 inconnu.
Les fiches et la v1 ne sont jamais écrites.
"""
import json
import re
import sqlite3
import sys
from pathlib import Path

ICI = Path(__file__).parent
SOURCES = ICI / "sources"
FICHES = Path("/home/mathevet/Bureau/fiches_lecture")   # fiche de TRAVAIL (la diffusion en est la sortie publique)
V1 = ICI.parent / "syndromes_foetaux.db"
SORTIE = ICI.parent / "foeto_v2.db"

TYPES = {"QUA", "NOR", "MES", "CON", "DIA"}
RELATIONS = {"critere_operationnel", "critere", "critere_non_refutant", "marqueur_gravite",
             "constant", "associe", "oriente", "exclut", "mime"}
NON_RECEVABLES = {"corpus CR"}
QUALITES = {"exacte", "partielle", "hors_fiche", "sans_equivalent"}

SCHEMA = """
create table signes (id text primary key, organe text, type text, k text, label_fr text,
                     section text, statut text, garde_fou text, fiche text);
create table grades (id text primary key, axe_id text references signes(id), rang integer,
                     label_fr text, borne text, statut text);
create table verbatims (objet_id text, source text, texte text, fiche text);
create table liens (de text, relation text, vers text);
create table negatifs (objet_id text, rang integer, pourquoi text);
create table correspondance_v1 (v1_id text primary key, v1_label text, v2_id text,
                                qualite text, note text);
"""


def norm(s):
    s = "\n".join(l.lstrip("> ") for l in s.splitlines())
    s = re.sub(r"[*`]", "", s)
    return re.sub(r"\s+", " ", s).strip()


def ident(code, t, k):
    return "FOETO2:PF.%s-%s-%s" % (code, t, k)


def construire(src, c, v1):
    S = json.loads(src.read_text(encoding="utf-8"))
    code, organe = S["code"], S["organe"]
    # Plusieurs versions d'une même fiche peuvent se compléter (travail : corpus
    # du service + § 10 ; diffusion : Genest) — un verbatim tient s'il est dans l'une.
    fiches = {f: norm((FICHES / f).read_text(encoding="utf-8")) for f in S["fiches"]}
    ids, erreurs = {}, []

    def verbatims(oid, vs, ou):
        # Seuls les livres (et la prose de la fiche qui les cite) prouvent un signe :
        # la pratique du service ne compte pas devant eux (Rémi, 2026-09-28).
        if not vs and not ou.endswith(".conservee"):
            erreurs.append("aucun verbatim : %s" % ou)
        for source, texte in vs:
            if source in NON_RECEVABLES:
                erreurs.append("source non recevable pour un signe (%s) : %s" % (source, ou))
            ou_f = next((f for f, t in fiches.items() if norm(texte) in t), None)
            if not ou_f:
                erreurs.append("verbatim introuvable (%s, %s) : %s" % (ou, source, texte))
            c.execute("insert into verbatims values (?,?,?,?)", (oid, source, texte, ou_f))

    for x in S["signes"]:
        if x["t"] not in TYPES:
            erreurs.append("type inconnu %s : %s" % (x["t"], x["k"]))
        oid = ids[x["k"]] = ident(code, x["t"], x["k"])
        c.execute("insert into signes values (?,?,?,?,?,?,?,?,?)",
                  (oid, organe, x["t"], x["k"], x["l"], x["sec"], x.get("statut"), x.get("gf"), S["fiches"][0]))
        verbatims(oid, x["v"], x["k"])
    for a in S["axes"]:
        aid = ids[a["k"]] = ident(code, "AXE", a["k"])
        c.execute("insert into signes values (?,?,?,?,?,?,?,?,?)",
                  (aid, organe, "AXE", a["k"], a["l"], a["sec"], a.get("statut"), None, S["fiches"][0]))
        verbatims(aid, a["v"], a["k"])
        for g in a["grades"]:
            gid = ids["%s.%s" % (a["k"], g["k"])] = "%s.%s" % (aid, g["k"])
            c.execute("insert into grades values (?,?,?,?,?,?)",
                      (gid, aid, g["rang"], g["l"], g.get("borne"), g.get("statut")))
            verbatims(gid, g["v"], "%s.%s" % (a["k"], g["k"]))

    for de, rel, vers in S["liens"]:
        if rel not in RELATIONS or de not in ids or vers not in ids:
            erreurs.append("lien invalide : %s %s %s" % (de, rel, vers))
            continue
        c.execute("insert into liens values (?,?,?)", (ids[de], rel, ids[vers]))
    for k, rang, pourquoi in S["negatifs"]:
        if k not in ids:
            erreurs.append("négatif sur un objet inconnu : %s" % k)
            continue
        c.execute("insert into negatifs values (?,?,?)", (ids[k], rang, pourquoi))

    # Correspondance : chaque terme v1 de l'organe, une et une seule fois
    termes = dict(v1.execute("select id, label_fr from foeto_terms where organe = ?", (organe,)))
    for vid in sorted(set(termes) - set(S["v1"])):
        erreurs.append("terme v1 sans correspondance : %s « %s »" % (vid, termes[vid]))
    for vid, (cible, qualite, *note) in S["v1"].items():
        if vid not in termes:
            erreurs.append("id v1 inconnu pour l'organe : %s" % vid)
        if qualite not in QUALITES or (cible is not None and cible not in ids) or \
           ((cible is None) != (qualite in ("hors_fiche", "sans_equivalent"))):
            erreurs.append("correspondance invalide : %s → %s (%s)" % (vid, cible, qualite))
            continue
        c.execute("insert into correspondance_v1 values (?,?,?,?,?)",
                  (vid, termes.get(vid), ids.get(cible), qualite, note[0] if note else None))

    if erreurs:
        raise SystemExit("%s : %d erreur(s)\n  " % (src.name, len(erreurs)) + "\n  ".join(erreurs))
    q = lambda sql: c.execute(sql, (organe,)).fetchone()[0]
    print("%s — %d signes (%s), %d grades, %d verbatims, %d liens, %d négatifs, v1 : %s" % (
        organe, q("select count(*) from signes where organe = ?"),
        ", ".join("%s %d" % r for r in c.execute(
            "select type, count(*) from signes where organe = ? group by type", (organe,))),
        q("select count(*) from grades g join signes s on s.id = g.axe_id where s.organe = ?"),
        q("select count(*) from verbatims v join signes s on v.objet_id like s.id || '%' where s.organe = ? and s.type = 'AXE'")
        + q("select count(*) from verbatims v join signes s on v.objet_id = s.id where s.organe = ? and s.type != 'AXE'"),
        q("select count(*) from liens l join signes s on s.id = l.de where s.organe = ?"),
        q("select count(*) from negatifs n join signes s on s.id = n.objet_id where s.organe = ?"),
        ", ".join("%s %d" % r for r in c.execute(
            "select qualite, count(*) from correspondance_v1 where v1_id in (select id from v1.foeto_terms where organe = ?) group by 1",
            (organe,)))))


if __name__ == "__main__":
    noms = sys.argv[1:] or sorted(p.stem for p in SOURCES.glob("*.json"))
    tmp = SORTIE.with_suffix(".tmp")
    tmp.unlink(missing_ok=True)
    c = sqlite3.connect("file:%s" % tmp, uri=True)
    c.executescript(SCHEMA)
    c.execute("attach database ? as v1", ("file:%s?mode=ro" % V1,))
    v1 = sqlite3.connect("file:%s?mode=ro" % V1, uri=True)
    for n in noms:
        construire(SOURCES / (n + ".json"), c, v1)
    c.commit()
    c.close()
    tmp.replace(SORTIE)  # ponytail: la base est un artefact, refaite en entier à chaque passe
    print("→", SORTIE)
