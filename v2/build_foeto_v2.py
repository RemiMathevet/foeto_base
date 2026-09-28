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
                     section text, statut text, garde_fou text, fiche text, hpo text);
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


# Une référence de livre dans la fiche, avec ou sans backticks : [keeling, ch. 24],
# `[Genest I]`, [spranger], [pubmed …]… Liste fermée d'ouvrages : corpus CR,
# expérience, foeto_terms… ne sont pas des livres.
LIVRES = ("ernst", "keeling", "soffoet", "verdijk", "ashworth", "benirschke", "genest", "vogel",
          "khong", "horii", "devneuro", "perineuro", "spranger", "amsterdam", "lherminecoulomb",
          "saudubray", "pubmed")   # un article PubMed compte comme un livre (Rémi, 2026-09-28)
REF = re.compile(r"\[([^\[\]]{2,80})\]")


def refs(texte):
    return [r.strip("` ") for r in REF.findall(texte) if r.strip("` ").lower().startswith(LIVRES)]


def hors_livre(texte):
    """L'unité se réclame d'une source qui n'est pas un livre ([corpus CR], [expérience]…) :
    elle n'hérite alors d'aucun livre du contexte."""
    return any(not r.strip("` ").lower().startswith(LIVRES) and
               any(m in r.lower() for m in ("corpus", "expérience", "experience", "foeto_terms"))
               for r in REF.findall(texte))


def index_fiche(chemin):
    """Unités de la fiche : (texte normalisé, livres de l'unité, livres du contexte).
    Unité = ligne de tableau, élément de liste, citation en bloc ou paragraphe.
    Un paragraphe ordinaire ne vaut que par ses propres références. Les tableaux, et
    dans une liste ou une citation le seul texte entre guillemets, héritent de la
    dernière référence posée dans leur section « ## »
    (la fiche annonce « Table 5 de [Genest I] » puis enchaîne tableaux et sous-titres),
    plus, pour un tableau, celles de son en-tête et d'une ligne « Source … ci-dessus »."""
    L = chemin.read_text(encoding="utf-8").splitlines()
    out, i, avant = [], 0, []
    liste = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s")
    while i < len(L):
        l = L[i]
        if l.startswith("## "):
            avant = refs(l)
            i += 1
            continue
        if l.lstrip().startswith("|"):
            j = i
            while j < len(L) and L[j].lstrip().startswith("|"):
                j += 1
            rangs = L[i:j]
            ctx = refs(rangs[0]) + avant + [r for x in rangs
                                             if re.search(r"\|\s*\**source|ci-dessus", x, re.I) for r in refs(x)]
            out += [(norm(x), refs(x), [] if hors_livre(x) else ctx, None) for x in rangs]
            i = j
            continue
        if not l.strip() or l.lstrip().startswith("#"):
            avant = refs(l) or avant
            i += 1
            continue
        genre = "cit" if l.lstrip().startswith(">") else "liste" if liste.match(l) else "para"
        j, bloc = i + 1, [l]
        while j < len(L) and L[j].strip() and not L[j].lstrip().startswith(("|", "#")) \
                and (L[j].lstrip().startswith(">") == (genre == "cit")) \
                and not (genre == "liste" and liste.match(L[j])):
            bloc.append(L[j])
            j += 1
        t = "\n".join(bloc)
        # liste ou citation en bloc : seul le texte cité ENTRE GUILLEMETS hérite du livre
        # d'au-dessus — un encadré « Ce qu'il ne faut pas conclure » est de la fiche.
        cites = [norm(m) for m in re.findall(r"«([^«»]+)»|“([^“”]+)”|\"([^\"]+)\"", t) for m in m if m]
        out.append((norm(t), refs(t), avant if genre != "para" and not hors_livre(t) else [], cites))
        avant = refs(t) or avant
        i = j
    return out


def livres_de(index, texte):
    """Livres qui portent ce texte : ceux de son unité, à défaut ceux de son contexte."""
    n, propres, ctx = norm(texte), [], []
    for u, r, c, cites in index:
        if n in u:
            propres += [x for x in r if x not in propres]
            if cites is None or any(n in q for q in cites):
                ctx += [x for x in c if x not in ctx]
    return propres or ctx


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

    def verbatims(oid, vs, quoi, axe=False):
        # Seuls les livres prouvent un signe : la pratique du service ne compte pas
        # devant eux, et la prose de la fiche ne vaut que par le livre qu'elle cite
        # dans la même phrase ou la même case (Rémi, 2026-09-28).
        if not vs and not axe and not quoi.endswith(".conservee"):
            erreurs.append("aucun verbatim : %s" % quoi)
        for source, texte in vs:
            if source in NON_RECEVABLES:
                erreurs.append("source non recevable pour un signe (%s) : %s" % (source, quoi))
            # toutes les versions de la fiche : on garde celle où le texte porte un livre
            ou = [(f, livres_de(index[f], texte)) for f, t in fiches.items() if norm(texte) in t]
            if not ou:
                erreurs.append("verbatim introuvable (%s, %s) : %s" % (quoi, source, texte))
                ou_f = None
            else:
                ou_f, livres = max(ou, key=lambda x: bool(x[1]))
                if not livres:
                    erreurs.append("verbatim sans livre (%s) : %s" % (quoi, texte))
                # la source est le livre que la fiche cite, pas l'étiquette posée à la main
                source = " + ".join(livres) or source
            c.execute("insert into verbatims values (?,?,?,?)", (oid, source, texte, ou_f))

    for x in S["signes"]:
        if x["t"] not in TYPES:
            erreurs.append("type inconnu %s : %s" % (x["t"], x["k"]))
        oid = ids[x["k"]] = ident(code, x["t"], x["k"])
        # HPO complète FOETO (un code phénotypique en plus), il ne le remplace pas
        if x.get("hpo") and not re.fullmatch(r"HP:\d{7}", x["hpo"]):
            erreurs.append("code HPO illisible : %s %s" % (x["k"], x["hpo"]))
        c.execute("insert into signes values (?,?,?,?,?,?,?,?,?,?)",
                  (oid, organe, x["t"], x["k"], x["l"], x["sec"], x.get("statut"), x.get("gf"), S["fiches"][0], x.get("hpo")))
        verbatims(oid, x["v"], x["k"])
    for a in S["axes"]:
        aid = ids[a["k"]] = ident(code, "AXE", a["k"])
        c.execute("insert into signes values (?,?,?,?,?,?,?,?,?,?)",
                  (aid, organe, "AXE", a["k"], a["l"], a["sec"], a.get("statut"), None, S["fiches"][0], None))
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
