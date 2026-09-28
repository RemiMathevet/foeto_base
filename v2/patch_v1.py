#!/usr/bin/env python3
"""Patche FOETO v1 (syndromes_foetaux.db) avec les signes curés depuis les fiches.

Décision de Rémi (2026-09-28) : pas de seconde base. Les signes des fiches entrent
dans FOETO — le terme v1 existant est COMPLÉTÉ s'il est l'équivalent exact, sinon un
terme est CRÉÉ avec le numéro suivant de sa série — et sont tagués « verbatim ».
À terme, on ne garde que les termes tagués.

Entrée : foeto_v2.db (bâtie par build_foeto_v2.py depuis v2/sources, dépôt privé).
Ce qui entre : constats (CON), diagnostics (DIA), normaux et artefacts (NOR), axes
gradués (terme parent + foeto_grades), verbatims avec leur livre, code HPO, liens
sourcés par la fiche (foeto_edges, source « fiche:… »).
Ce qui entre aussi : les mesures (MES) — une mesure peut rendre un signe.
Ce qui n'entre pas : qualité de lecture (QUA), négatifs, garde-fous, statuts (ils
restent dans la fiche et la grille), placenta (à part).
Aucune fusion ni suppression ici : doublons exacts et anciens termes-grades sont listés
dans sources/ pour une passe fusionne.py (qui repointe les dépendants).

  python3 v2/patch_v1.py              # simulation : compte et écrit les listes, n'écrit rien en base
  python3 v2/patch_v1.py --appliquer  # sauvegarde horodatée, puis écriture
"""
import datetime as dt
import sqlite3
import sys
from pathlib import Path

ICI = Path(__file__).parent
V1 = ICI.parent / "syndromes_foetaux.db"
V2 = ICI.parent / "foeto_v2.db"
PRIVE = ICI / "sources"

EXCLUS = set()   # placenta, môles et jumeaux : pas encore de source
TYPES_IMPORTES = {"CON", "DIA", "NOR", "MES", "AXE"}   # une mesure peut rendre un signe (Rémi)
# fiche → (seau organe v1, code organe des identifiants)
ORGANES = {"rein": ("rein", "REN"), "vessie": ("rein", "REN"), "cerveau_moelle": ("cerveau", "CER"),
           "coeur": ("coeur", "COE"), "digestif": ("digestif", "DIG"), "foie": ("foie", "FOI"),
           "gonades": ("genital", "GEN"), "muscle": ("muscle", "MUS"), "oeil": ("oeil_oreille", "ORL"),
           "oreille": ("oeil_oreille", "ORL"), "pancreas": ("endocrine", "END"), "surrenales": ("endocrine", "END"),
           "thyroide": ("endocrine", "END"), "thymus": ("hematolymphoide", "HEM"), "rate": ("hematolymphoide", "HEM"),
           "peau": ("peau", "PEA"), "dysplasies_osseuses": ("squelette", "SQU"), "poumon": ("poumon", "POU"), "squelette": ("squelette", "SQU"),
           "retention": ("multi_organe", "MUL")}
# axes de la fiche rétention : l'organe témoin donne le seau
AXES_RETENTION = {"retention_foie": "foie", "retention_myocarde": "coeur", "retention_bronche": "poumon",
                  "retention_cartilage_tracheal": "poumon", "retention_poumon": "poumon",
                  "retention_tube_digestif": "digestif", "retention_surrenale": "surrenales",
                  "retention_pancreas": "pancreas", "retention_thymus": "thymus",
                  "retention_cortex_cerebral": "cerveau_moelle", "retention_externe": "peau",
                  "retention_rein_transversal": "rein"}
AXES_PLACENTA = {"seaux_placentaires", "retention_placenta_villosites", "retention_cordon"}
AXIS_V1 = {"CON": "pathologie", "DIA": "pathologie", "NOR": "architecture", "MES": "architecture"}

SCHEMA = """
create table if not exists foeto_tags (term_id text, tag text, primary key (term_id, tag));
create table if not exists foeto_verbatims (term_id text, grade text, source text, texte text, fiche text,
                                            unique (term_id, grade, texte));
create table if not exists foeto_v2_import (v2_id text primary key, v1_id text, mode text, date text);
create table if not exists foeto_hpo_verifie (term_id text, hpo_id text, source text, primary key (term_id, hpo_id));
"""


# Type d'un nouveau terme sans terme v1 proche : mots-clés du libellé → séries v1.
# ponytail: heuristique lexicale — la liste sources/patch_v1_nouveaux.tsv est à relire avant --appliquer.
import re as _re
TYPE_MOTS = [("INF", r"infect|inclusion|virus|viral|cmv|herpès|herpes|toxoplasm|syphil|listéri|candid|bactéri|"
                     r"abcès|pneumon|pneumopath|inflamm|granulom|polynucl|infiltrat|chorio|"
                     r"cardite|hépatite|néphrite|encéphalite|méningite|colite|péritonite|villite|amniotite|"
                     r"funisite|vascularite|myosite|thyroïdite|pancréatite|ostéite|dermite|pneumonite"),
             ("TUM", r"tumeur|néoplas|blastome|carcinome|sarcome|tératome|hamartome|angiome|lymphangiome|"
                     r"rhabdomyome|fibrome|nodule blast|néphroblastom|nevus|mélanome"),
             ("VAS", r"infarct|ischém|nécrose|hémorrag|thromb|embol|congestion|vascul|artér|veine|veineux|"
                     r"capillaire|anévrism|hématome|calcification"),
             ("MET", r"surcharge|dépôt|lipid|glycog|stéatose|pigment|fer\b|sidérose|hémosidér|cholest|"
                     r"inclusions? lysosom|métabol|mitochond|vacuol")]


def type_par_mots(label):
    l = label.lower()
    for t, rx in TYPE_MOTS:
        if _re.search(rx, l):
            return t
    return "MAL"


def seau(organe, k, typ):
    if organe == "retention" and typ == "AXE" and k in AXES_RETENTION:
        return ORGANES[AXES_RETENTION[k]]
    return ORGANES[organe]


def main(appliquer):
    v2 = sqlite3.connect("file:%s?mode=ro" % V2, uri=True)
    v2.row_factory = sqlite3.Row
    if appliquer:
        bak = V1.with_name("syndromes_foetaux.db.bak_%s_patch_v2" % dt.datetime.now().strftime("%Y%m%d_%H%M%S"))
        src = sqlite3.connect(V1)
        dst = sqlite3.connect(bak)
        src.backup(dst)
        dst.close()
        src.close()
        print("sauvegarde :", bak)
        v1 = sqlite3.connect(V1)
    else:
        v1 = sqlite3.connect("file:%s?mode=ro" % V1, uri=True)
    v1.row_factory = sqlite3.Row
    if appliquer:
        v1.executescript(SCHEMA)
    deja = {}
    if appliquer or v1.execute("select 1 from sqlite_master where name='foeto_v2_import'").fetchone():
        deja = {r["v2_id"]: r["v1_id"] for r in v1.execute("select v2_id, v1_id from foeto_v2_import")}

    existants = {r["id"] for r in v1.execute("select id from foeto_terms")}
    typ_de = {r["id"]: r["id"].split("-")[1] if r["id"].count("-") >= 2 else None for r in
              v1.execute("select id from foeto_terms where id like 'FOETO:PF.%'")}
    seq = {}
    for (i,) in v1.execute("select id from foeto_terms where id like 'FOETO:PF.%'"):
        try:
            org, typ, n = i[len("FOETO:PF."):].split("-")
            seq[(org, typ)] = max(seq.get((org, typ), 0), int(n))
        except ValueError:
            pass

    corr = {}
    for r in v2.execute("select v1_id, v2_id, qualite from correspondance_v1 where v2_id is not null"):
        corr.setdefault(r["v2_id"], []).append((r["qualite"], r["v1_id"]))

    signes = [r for r in v2.execute("select * from signes order by organe, type, k")
              if r["organe"] not in EXCLUS and r["type"] in TYPES_IMPORTES
              and not (r["organe"] == "retention" and r["type"] == "AXE" and r["k"] in AXES_PLACENTA)]

    cible, nouveaux, completes, doublons, a_choisir = {}, [], [], [], []
    for s in signes:
        exacts = sorted(v for q, v in corr.get(s["id"], []) if q == "exacte" and v in existants)
        partiels = sorted(v for q, v in corr.get(s["id"], []) if q == "partielle" and v in existants)
        if s["id"] in deja:
            cible[s["id"]] = deja[s["id"]]
            continue
        if exacts and s["type"] != "AXE":
            cible[s["id"]] = exacts[0]
            completes.append((s, exacts[0]))
            doublons += [(s, exacts[0], d) for d in exacts[1:]]
            continue
        _, org = seau(s["organe"], s["k"], s["type"])
        if s["type"] == "AXE":
            typ, orig = "RET" if "retention" in s["k"] else "NOR", "axe"
        elif partiels and typ_de.get(partiels[0]):
            typ, orig = typ_de[partiels[0]], "terme v1 proche " + partiels[0]
        else:
            typ = "NOR" if s["type"] in ("NOR", "MES") else type_par_mots(s["label_fr"])
            orig = {"NOR": "normal (type v2)", "MES": "mesure (type v2)"}.get(s["type"], "mots-clés du libellé")
            a_choisir.append(s)
        seq[(org, typ)] = seq.get((org, typ), 0) + 1
        nid = "FOETO:PF.%s-%s-%03d" % (org, typ, seq[(org, typ)])
        cible[s["id"]] = nid
        nouveaux.append((s, nid, orig))

    grades = [g for g in v2.execute("select g.*, s.id sid from grades g join signes s on s.id = g.axe_id")
              if g["sid"] in cible]
    liens = [l for l in v2.execute("select * from liens")
             if (l["de"].split(".")[0] if l["de"].count(".") > 1 else l["de"]) in cible
             and (l["vers"].split(".")[0] if l["vers"].count(".") > 1 else l["vers"]) in cible]

    def parent(x):   # grade → son axe
        return x.rsplit(".", 1)[0] if x.count(".") > 1 else x

    # listes de revue (dépôt privé) — jamais réécrites par une passe qui n'a rien de nouveau
    ecrire = bool(nouveaux or completes)
    ecrire and (PRIVE / "patch_v1_nouveaux.tsv").write_text(
        "v1_id\torgane\ttype_v2\tlibellé\torigine du type\n" +
        "".join("%s\t%s\t%s\t%s\t%s\n" % (n, s["organe"], s["type"], s["label_fr"], o) for s, n, o in nouveaux),
        encoding="utf-8")
    ecrire and (PRIVE / "patch_v1_doublons_a_fusionner.tsv").write_text(
        "survivant\tdoublon\tlibellé v2\n" +
        "".join("%s\t%s\t%s\n" % (a, b, s["label_fr"]) for s, a, b in doublons), encoding="utf-8")
    grades_v1 = [(r["v1_id"], r["v2_id"]) for r in v2.execute(
        "select v1_id, v2_id from correspondance_v1 where qualite = 'exacte' and v2_id like '%-AXE-%.%'")]
    ecrire and (PRIVE / "patch_v1_termes_grades_a_replier.tsv").write_text(
        "terme v1 (grade écrit en terme)\tgrade v2\n" + "".join("%s\t%s\n" % g for g in grades_v1), encoding="utf-8")

    print("signes importés : %d (%d complètent un terme v1, %d nouveaux termes, dont %d au type par défaut)"
          % (len(signes), len(completes), len(nouveaux), len(a_choisir)))
    print("grades : %d · liens de fiche : %d · doublons exacts à fusionner : %d · termes-grades à replier : %d"
          % (len(grades), len(liens), len(doublons), len(grades_v1)))
    if not appliquer:
        print("simulation — rien n'est écrit. Listes : sources/patch_v1_*.tsv")
        return

    today = dt.date.today().isoformat()
    for s, nid, _ in nouveaux:
        org_v1, _ = seau(s["organe"], s["k"], s["type"])
        axis = ("retention" if "retention" in s["k"] else "maturation") if s["type"] == "AXE" else AXIS_V1[s["type"]]
        livres = "|".join(sorted({r["source"] for r in v2.execute("select source from verbatims where objet_id = ?",
                                                                    (s["id"],))}))
        v1.execute("""insert into foeto_terms (id, organe, label_fr, code, axis, sources, type_new, triage_fiche,
                      triage_section, domain) values (?,?,?,?,?,?,?,?,?, 'foetus')""",
                   (nid, org_v1, s["label_fr"], s["k"], axis, livres, nid.split("-")[1], s["fiche"], s["section"]))
    for sid, tid in cible.items():
        v1.execute("insert or ignore into foeto_tags values (?, 'verbatim')", (tid,))
        v1.execute("insert or ignore into foeto_v2_import values (?,?,?,?)",
                   (sid, tid, "nouveau" if tid not in existants else "complété", today))
        for r in v2.execute("select * from verbatims where objet_id = ?", (sid,)):
            v1.execute("insert or ignore into foeto_verbatims values (?,?,?,?,?)",
                       (tid, None, r["source"], r["texte"], r["fiche"]))
        h = v2.execute("select hpo from signes where id = ?", (sid,)).fetchone()[0]
        if h and not v1.execute("select 1 from foeto_hpo where foeto_id = ? and hpo_id = ?", (tid, h)).fetchone():
            v1.execute("insert into foeto_hpo (foeto_id, hpo_id) values (?,?)", (tid, h))
        if h:   # foeto_hpo mêle d'anciens liens non vérifiés : le code arbitré est aussi tracé à part
            v1.execute("insert or ignore into foeto_hpo_verifie values (?,?, 'arbitrage fiches')", (tid, h))
    for g in grades:
        tid = cible[g["sid"]]
        ax = v2.execute("select label_fr from signes where id = ?", (g["sid"],)).fetchone()[0]
        desc = " · ".join(x for x in ("rang %d" % g["rang"], g["borne"], g["statut"]) if x)
        if not v1.execute("select 1 from foeto_grades where term_id = ? and grade = ?", (tid, g["label_fr"])).fetchone():
            v1.execute("insert into foeto_grades (term_id, axe, grade, desc_fr) values (?,?,?,?)",
                       (tid, ax, g["label_fr"], desc))
        for r in v2.execute("select * from verbatims where objet_id = ?", (g["id"],)):
            v1.execute("insert or ignore into foeto_verbatims values (?,?,?,?,?)",
                       (tid, g["label_fr"], r["source"], r["texte"], r["fiche"]))
    for l in liens:
        a, b = cible[parent(l["de"])], cible[parent(l["vers"])]
        if a != b and not v1.execute("select 1 from foeto_edges where source_id=? and target_id=? and relation=?",
                                     (a, b, l["relation"])).fetchone():
            v1.execute("insert into foeto_edges (source_id, target_id, relation, confidence, source) "
                       "values (?,?,?,?,?)", (a, b, l["relation"], 1.0, "fiche"))
    v1.commit()
    print("appliqué : %d termes tagués verbatim, %d créés" % (
        v1.execute("select count(*) from foeto_tags where tag='verbatim'").fetchone()[0], len(nouveaux)))


if __name__ == "__main__":
    main("--appliquer" in sys.argv)
