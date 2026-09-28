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
NON_RECEVABLES = {"corpus CR", "expérience"}   # la pratique ne compte pas devant les livres
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


# Une référence de livre dans la fiche : `[keeling, ch. 24]`, `[Genest I]`…
REF = re.compile(r"`\[([^\]`]+)\]`")
PAS_UN_LIVRE = ("corpus", "expérience", "experience", "foeto_terms", "gabarit")


def index_fiche(chemin):
    """Blocs de la fiche (ligne de tableau, ou paragraphe) : (texte normalisé, livres cités)."""
    blocs, para = [], []
    def clore():
        if para:
            brut = "\n".join(para)
            blocs.append((norm(brut), [r for r in REF.findall(brut)
                                       if not any(m in r.lower() for m in PAS_UN_LIVRE)]))
            para.clear()
    for ligne in chemin.read_text(encoding="utf-8").splitlines():
        if not ligne.strip() or ligne.lstrip().startswith(("|", "#")):
            clore()
            if ligne.strip():
                para.append(ligne)
                clore()
        else:
            para.append(ligne)
    clore()
    return blocs


def livres_de(index, texte):
    """Livres cités dans le(s) bloc(s) de la fiche qui contiennent ce texte."""
    n, vus = norm(texte), []
    for bloc, refs in index:
        if n in bloc:
            vus += [r for r in refs if r not in vus]
    return vus


def ident(code, t, k):
    return "FOETO2:PF.%s-%s-%s" % (code, t, k)


def construire(src, c, v1):
    S = json.loads(src.read_text(encoding="utf-8"))
    code, organe = S["code"], S["organe"]
    # Plusieurs versions d'une même fiche peuvent se compléter (travail : corpus
    # du service + § 10 ; diffusion : Genest) — un verbatim tient s'il est dans l'une.
    fiches = {f: norm((FICHES / f).read_text(encoding="utf-8")) for f in S["fiches"]}
    index = {f: index_fiche(FICHES / f) for f in S["fiches"]}
    ids, erreurs = {}, []

    def verbatims(oid, vs, ou, axe=False):
        # Seuls les livres prouvent un signe : la pratique du service ne compte pas
        # devant eux, et la prose de la fiche ne vaut que par le livre qu'elle cite
        # dans la même phrase ou la même case (Rémi, 2026-09-28).
        if not vs and not axe and not ou.endswith(".conservee"):
            erreurs.append("aucun verbatim : %s" % ou)
        for source, texte in vs:
            if source in NON_RECEVABLES:
                erreurs.append("source non recevable pour un signe (%s) : %s" % (source, ou))
            ou_f = next((f for f, t in fiches.items() if norm(texte) in t), None)
            if not ou_f:
                erreurs.append("verbatim introuvable (%s, %s) : %s" % (ou, source, texte))
            elif source == "fiche":
                livres = livres_de(index[ou_f], texte)
                if not livres:
                    erreurs.append("verbatim sans livre (%s) : %s" % (ou, texte))
                source = " + ".join(livres) or source
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
        verbatims(aid, a["v"], a["k"], axe=True)
        if not a["grades"]:
            erreurs.append("axe sans grade : %s — en faire un signe" % a["k"])
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

    # Correspondance v1. Périmètre « organe » (rein) : chaque terme v1 de l'organe.
    # Périmètre « triage » (défaut) : les termes que le triage v1 rattache à la
    # fiche ; LESION et NON_LESION se rattachent à la main, HORS_FICHE d'office.
    if S.get("v1_perimetre", "triage") == "organe":
        termes = dict(v1.execute("select id, label_fr from foeto_terms where organe = ?", (organe,)))
    else:
        nom_fiche = "%%%s%%" % Path(S["fiches"][-1]).name
        termes, hors = {}, {}
        for i, l, v in v1.execute("select id, label_fr, triage_verdict from foeto_terms where triage_fiche like ?",
                                  (nom_fiche,)):
            (hors if v == "HORS_FICHE" else termes)[i] = l
        for i in hors:
            S["v1"].setdefault(i, [None, "hors_fiche"])
        termes.update(hors)
    # un terme v1 trié vers deux fiches est rattaché par la première qui le porte
    deja = {r[0] for r in c.execute("select v1_id from correspondance_v1")}
    for vid in sorted(set(termes) - set(S["v1"]) - deja):
        erreurs.append("terme v1 sans correspondance : %s « %s »" % (vid, termes[vid]))
    for vid, (cible, qualite, *note) in S["v1"].items():
        if vid not in termes:
            erreurs.append("id v1 inconnu pour l'organe : %s" % vid)
        if qualite not in QUALITES or (cible is not None and cible not in ids) or \
           ((cible is None) != (qualite in ("hors_fiche", "sans_equivalent"))):
            erreurs.append("correspondance invalide : %s → %s (%s)" % (vid, cible, qualite))
            continue
        if vid in deja:
            erreurs.append("terme v1 déjà rattaché par une autre fiche : %s" % vid)
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
        q("select count(*) from liens l join signes s on l.de = s.id or l.de like s.id || '.%' where s.organe = ?"),
        q("select count(*) from negatifs n join signes s on n.objet_id = s.id or n.objet_id like s.id || '.%' where s.organe = ?"),
        ", ".join("%s %d" % r for r in c.execute(
            "select qualite, count(*) from correspondance_v1 where v1_id in (%s) group by 1"
            % ",".join("'%s'" % t for t in termes) if termes else "select 'aucun', 0"))))


if __name__ == "__main__":
    if sys.argv[1:2] == ["--essai"]:
        # Vérifie une source seule, en mémoire : rien n'est écrit (agents en parallèle).
        c = sqlite3.connect(":memory:")
        c.executescript(SCHEMA)
        c.execute("attach database ? as v1", ("file:%s?mode=ro" % V1,))
        construire(SOURCES / (sys.argv[2] + ".json"), c, sqlite3.connect("file:%s?mode=ro" % V1, uri=True))
        sys.exit(0)
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
