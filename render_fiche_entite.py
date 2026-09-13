#!/usr/bin/env python3
"""Fiche par ENTITE (entites_livres) : un syndrome, tous les livres qui le decrivent
fusionnes, chaque ligne gardant sa source. Rien n'est redige : c'est une
concatenation ordonnee de ce que la base tient, sans LLM.

  §1 famille (Smith par la lettre, Spranger par le groupe, base par l'ORPHA)
  §2 identite : les entrees fusionnees, debut de manifestation, part foetale,
     ETIOLOGY de Smith en verbatim
  §3 signes attestes, dans l'ordre de l'examen : UNE ligne par HPO, avec chaque
     livre qui l'atteste (niveau, frequence) — le verbatim de Smith de preference
  §3b radiographie (Spranger)
  §4 cotation V2, §5 differentiel (Spranger ecrit / parente calculee / Orphanet en
  repli), §6 evolution, §7 micro attestee, §8 commentaire, §9 radio verbatim

Usage : python3 render_fiche_entite.py ORPHA:2655 [--md sortie.md]
        python3 render_fiche_entite.py --all DOSSIER
"""
import argparse
import json
import re
import sqlite3
import sys
from collections import defaultdict
from pathlib import Path

import render_fiche_syndrome as R

DB = R.DB
try:
    TITRES_SPR = json.loads(Path("/home/mathevet/Bureau/Embedding_RAG_V2/chapitres/spranger/_titres_groupes.json").read_text(encoding="utf-8"))
except Exception:
    TITRES_SPR = {}


def slug_de(s):
    return re.sub(r"_+", "_", re.sub(r"[^a-z0-9]+", "_", s.lower())).strip("_")[:70]


def rendre(c, eid):
    e = c.execute("select * from entites_livres where entite_id=?", (eid,)).fetchone()
    if not e:
        raise SystemExit(f"entité inconnue : {eid}")
    titres = c.execute("select livre, syndrome_titre, entree from entites_livres_titres where entite_id=? order by livre", (eid,)).fetchall()
    tl = [t["syndrome_titre"] for t in titres]
    q = ",".join("?" * len(tl))
    orpha = e["orpha"]
    syn = c.execute("select * from syndromes where id=?", (orpha,)).fetchone() if orpha else None
    L = [f"# {e['nom']}",
         f"\n*Fiche composée depuis la base — {len(titres)} entrée(s) de livre fusionnée(s), chaque ligne remonte à sa source. "
         f"Filtre fœtal appliqué aux signes.*\n"]

    # §1
    L.append("## 1. Famille")
    fam = []
    for t in titres:
        m = re.match(r"^([A-W]) ", t["syndrome_titre"]) if t["livre"] == "smith" else None
        if m and m[1] in R.SMITH_CAT:
            fam.append(f"- **Catégorie Smith** : {m[1]} — {R.SMITH_CAT[m[1]]}")
        m = re.match(r"^(\d+)\.\d+\s", t["syndrome_titre"]) if t["livre"] == "spranger_entites" else None
        if m:
            chap = sorted(R.SPRANGER.glob(f"ch{int(m[1]):02d}_*.txt"))
            if chap:
                fam.append(f"- **Groupe Spranger** : {m[1]} — {TITRES_SPR.get(m[1], chap[0].stem[5:].replace('_', ' '))}")
    if orpha:
        for fid, nom in c.execute("""select f.family_id, f.family_name from syndrome_family_members m
                                     join syndrome_families f on f.family_id = m.family_id where m.syndrome_id = ?""", (orpha,)):
            fam.append(f"- **Famille** (base, {fid}) : {nom}")
    if syn:
        fam.append(f"- **Catégorie** (base) : {syn['category']}")
    L.extend(dict.fromkeys(fam) or ["- *(aucune famille rattachée)*"])

    # §2
    L.append("\n## 2. Identité")
    if orpha:
        L.append(f"- **ORPHA** : {orpha} — *{syn['name_en'] if syn else ''}*")
    deb = c.execute("select debut from entites_livres where entite_id=?", (eid,)).fetchone()
    if deb and deb[0]:
        L.append(f"- **Début de manifestation** ({'Orphanet' if 'GeneReviews' not in deb[0] else 'GeneReviews, texte'}) : {deb[0].split(' (')[0]}")
        if "GeneReviews" in deb[0]:
            for e_gr, in c.execute("select entree from entites_livres_titres where entite_id=? and livre='genereviews'", (eid,)):
                x = c.execute("select n_prenatal, n_tardif, extraits from genereviews_debut where slug=?", (e_gr.split('#')[0],)).fetchone()
                if x and x["extraits"]:
                    L.append(f"  - {x['n_prenatal']} marqueurs prénataux, {x['n_tardif']} tardifs — « {x['extraits'].split(' | ')[0][:300]} »")
    n_tot = c.execute(f"select count(distinct hpo_id) from syndrome_hpo_livres where syndrome_titre in ({q}) and est_parent=0", tl).fetchone()[0]
    n_foet = c.execute(f"select count(distinct hpo_id) from v_syndrome_hpo_livres_foetal where syndrome_titre in ({q}) and est_parent=0", tl).fetchone()[0]
    L.append(f"- **Signes fœtaux attestés** : {n_foet} sur {n_tot} signes des livres ({100*n_foet//max(n_tot,1)} %)")
    for t in titres:
        L.append(f"- **Entrée** : {t['syndrome_titre']} — *{t['livre'].replace('_entites', '')}* `{t['entree'].split('#')[0]}`")
    secs = {}
    for t in titres:
        if t["livre"] == "smith":
            secs = R.sections(t["entree"], R.SMITH)
            if secs.get("ETIOLOGY"):
                L.append(f"\n> {secs['ETIOLOGY'][:900]}\n>\n> — *smith, {t['syndrome_titre']}, ETIOLOGY*")
            break

    # §3 : une ligne par HPO, toutes sources
    sig = c.execute(f"""select * from v_syndrome_hpo_livres_foetal where syndrome_titre in ({q}) and est_parent=0
                        order by region, hpo_id, livre""", tl).fetchall()
    par_hpo = defaultdict(list)
    for s in sig:
        par_hpo[(s["modalite"] == "radiographique", s["hpo_id"])].append(s)
    lab = dict(c.execute("select hpo_id, coalesce(label_fr, label_en) from hpo_terms"))

    def ligne(rows):
        h = rows[0]["hpo_id"]
        srcs = []
        for r in sorted(rows, key=lambda r: (r["livre"] != "smith", r["livre"])):
            tag = r["livre"].replace("_entites", "")
            if r["frequence"]:
                tag += f" {r['frequence']}"
            elif r["niveau"] and r["niveau"] != "texte":
                tag += f" {r['niveau']}"
            if tag not in srcs:
                srcs.append(tag)
        v = next((r for r in rows if r["livre"] == "smith"), rows[0])
        return f"- **{lab.get(h, h)}** `{h}` — {' · '.join(srcs)}  \n  « {v['verbatim'][:160]} »"

    def bloc(radio):
        regs = defaultdict(list)
        for (rad, h), rows in par_hpo.items():
            if rad == radio:
                regs[rows[0]["region"] or "other"].append(rows)
        for reg in R.ORDRE + [r for r in regs if r not in R.ORDRE]:
            if reg in regs:
                L.append(f"\n#### {R.FR.get(reg, reg)}")
                # les signes que plusieurs livres attestent en premier, puis principal, puis nom
                for rows in sorted(regs[reg], key=lambda rs: (-len({r['livre'] for r in rs}), rs[0]["niveau"] != "principal", lab.get(rs[0]["hpo_id"], ""))):
                    L.append(ligne(rows))
    L.append("\n## 3. Signes attestés, dans l'ordre de l'examen")
    L.append("\n*Une ligne par signe HPO ; après le tiret, chaque livre qui l'atteste avec la fréquence s'il la chiffre "
             "ou le niveau qu'il lui donne (principal / occasionnel). Verbatim de Smith de préférence.*")
    L.append("\n### 3a. Examen clinique et autopsie")
    bloc(False)
    if any(rad for rad, _ in par_hpo):
        L.append("\n### 3b. Radiographie (Spranger)")
        bloc(True)

    # §4 cotation V2 (vocabulaire de paillasse), comme la fiche par livre
    if orpha:
        v2 = c.execute("""select f.label_fr, sf.prob from syndrome_foeto sf join foeto_terms f on f.id = sf.foeto_id
                          where sf.syndrome_id = ? and sf.prob >= 0.3 order by sf.prob desc limit 12""", (orpha,)).fetchall()
        if v2:
            L.append("\n## 4. Cotation V2 (vocabulaire de paillasse)")
            L.append("\n*Termes FOETO liés à l'ORPHA (syndrome_foeto, synthétique — indicatif, pas une preuve).*")
            for r in v2:
                L.append(f"- {r['label_fr']} ({r['prob']:.2f})")

    # §5
    L.append("\n## 5. Diagnostic différentiel — et ce qui tranche")
    dl = c.execute(f"select diff_nom, diff_syndrome_id, verbatim, syndrome_titre from syndrome_diff_livres where syndrome_titre in ({q}) order by id", tl).fetchall()
    if dl:
        L.append(f"\n### 5a. Selon le livre — *spranger, {dl[0]['syndrome_titre']}, MAJOR DIFFERENTIAL DIAGNOSES*")
        for d in dl:
            L.append(f"\n**{d['diff_nom'] or '(sans nom)'}**{('  `' + d['diff_syndrome_id'] + '`') if d['diff_syndrome_id'] else ''}  \n> {d['verbatim'][:600]}")
    par = c.execute("""select * from syndrome_parente_livres where a = ? and b <> ? order by score desc limit 6""", (eid, eid)).fetchall()
    if par:
        L.append("\n### 5c. Par chevauchement des signes attestés par les livres")
        L.append("\n*Jaccard pondéré par l'information des termes HPO, sur les signes attestés (signe et ancêtres), entre entités — "
                 "un syndrome décrit par trois livres compte une fois.*")
        for d in par:
            nb = c.execute("select nom from entites_livres where entite_id=?", (d["b"],)).fetchone()
            L.append(f"\n**{nb['nom'] if nb else d['b']}** `{d['b']}` — score {d['score']:.2f} ({d['n_partages']} communs)")
            if d["partages"]:
                L.append(f"- communs : {d['partages']}")
            if d["disc_b"]:
                L.append(f"- il a, elle non : {d['disc_b']}")
            if d["disc_a"]:
                L.append(f"- elle a, lui non : {d['disc_a']}")
    if syn and syn["differential_diagnosis"]:
        L.append("\n### 5b. Par chevauchement HPO (Orphanet) — en repli")
        for autre_id, autre_nom, comm, ici, la_bas in R.differentiels(c, orpha, syn):
            L.append(f"\n**{autre_nom}** `{autre_id}` — {comm} signes communs")
            if ici:
                L.append("- ici et pas là : " + " ; ".join(f"{l}{a}" for h, l, a in ici))
            if la_bas:
                L.append("- là et pas ici : " + " ; ".join(l for h, l, a in la_bas))

    # §6-§9
    if secs.get("NATURAL HISTORY"):
        L.append("\n## 6. Évolution")
        L.append(f"> {secs['NATURAL HISTORY'][:1200]}\n>\n> — *smith, NATURAL HISTORY*")
    micro = c.execute(f"""select * from syndrome_foeto_livres where syndrome_titre in ({q}) or (? is not null and syndrome_id = ?)
                          order by case niveau when 'direct' then 0 when 'contexte' then 1 else 2 end, age, organe, livre""",
                      tl + [orpha, orpha]).fetchall()
    L.append("\n## 7. Micro attestée")
    if micro:
        vus, blocn = set(), None
        for m in micro:
            k = m["verbatim"][:60].lower()
            if k in vus:
                continue
            vus.add(k)
            b = ("Selon le groupe — " + m["famille"]) if m["niveau"] == "famille" else \
                ("Attesté pour l'entité" if m["niveau"] == "direct" else "Par contexte")
            if b != blocn:
                L.append(f"\n### {b}"); blocn = b
            fo = f" `{m['foeto_id']}`" if m["foeto_id"] else " *(terme FOETO à créer)*"
            age = " — *biopsie postnatale*" if m["age"] == "postnatal" else ""
            L.append(f"- **{m['signe']}** ({m['organe'] or '?'}){fo} — « {m['verbatim']} » [{m['livre']}, {m['chapitre']}]{age}")
    else:
        L.append("\n*Aucune histologie attestée dans le corpus pour cette entité — ni en direct, ni par sa famille.*")
    if secs.get("COMMENT"):
        L.append("\n## 8. Commentaire du livre")
        L.append(f"> {secs['COMMENT'][:1200]}\n>\n> — *smith, COMMENT*")
    for t in titres:
        if t["livre"] == "spranger_entites":
            chemin = Path("/home/mathevet/Bureau/Embedding_RAG_V2/chapitres/spranger_entites") / t["entree"].split("#")[0]
            if chemin.exists():
                m = re.search(r"^[ \t]*M\s*A\s*J\s*O\s*R\s+R\s*A\s*D\s*I\s*O\s*G\s*R\s*A\s*P\s*H\s*I\s*C\s+F\s*E\s*A\s*T\s*U\s*R\s*E\s*S[ \t]*$(.*?)^[ \t]*M\s*A\s*J\s*O\s*R\s+D",
                              chemin.read_text(encoding="utf-8"), re.M | re.S)
                if m:
                    L.append("\n## 9. Sémiologie radiologique — verbatim Spranger")
                    L.append("> " + re.sub(r"\n+", "\n> ", m.group(1).strip())[:1500])
                    L.append(f">\n> — *spranger, {t['syndrome_titre']}, MAJOR RADIOGRAPHIC FEATURES*")
            break
    return "\n".join(L)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("entite", nargs="?")
    ap.add_argument("--md")
    ap.add_argument("--all", metavar="DOSSIER")
    a = ap.parse_args()
    c = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    c.row_factory = sqlite3.Row
    if a.all:
        d = Path(a.all); d.mkdir(parents=True, exist_ok=True)
        ents = c.execute("select entite_id, nom, orpha, livres from entites_livres order by nom").fetchall()
        ok = 0
        with open(d / "_index.tsv", "w", encoding="utf-8") as idx:
            idx.write("fichier\tentite\tnom\torpha\tlivres\tdebut\tn_foetal\tn_total\n")
            for e in ents:
                try:
                    md = rendre(c, e["entite_id"])
                except SystemExit:
                    continue
                nom_f = (e["orpha"].replace(":", "_").lower() + "__" if e["orpha"] else "livre__") + slug_de(e["nom"]) + ".md"
                (d / nom_f).write_text(md, encoding="utf-8"); ok += 1
                deb = re.search(r"Début de manifestation\*\* \([^)]*\) : (.+)", md)
                nf = re.search(r"Signes fœtaux attestés\*\* : (\d+) sur (\d+)", md)
                idx.write(f"{nom_f}\t{e['entite_id']}\t{e['nom']}\t{e['orpha'] or ''}\t{e['livres']}\t{deb[1] if deb else ''}\t{nf[1] if nf else 0}\t{nf[2] if nf else 0}\n")
        print(f"{ok}/{len(ents)} fiches par entité -> {d} (+ _index.tsv)")
        return
    md = rendre(c, a.entite)
    if a.md:
        Path(a.md).write_text(md, encoding="utf-8"); print(f"-> {a.md} ({len(md)} car.)")
    else:
        print(md)


if __name__ == "__main__":
    main()
