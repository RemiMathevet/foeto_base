#!/usr/bin/env python3
"""Fiche syndrome = une VUE de la base, pas un texte genere.

Rien n'est redige ici. Chaque bloc est soit une requete, soit un verbatim copie
du livre avec sa reference. La fiche se recalcule quand la base change, et toute
assertion remonte a sa source — ce que la prose d'un LLM ne permet pas.

Blocs, dans l'ordre du raisonnement d'autopsie :
  FAMILLE          chapitre Spranger (niveau mecanisme) + categorie de la base
  IDENTITE         ORPHA, gene, transmission — verbatim ETIOLOGY de Smith
  SIGNES           syndrome_hpo_livres filtre foetal, par region d'examen,
                   niveau principal/occasionnel, frequence SI le livre chiffre
  COTATION V2      syndrome_foeto_v2 : le vocabulaire de paillasse et son score
  DIFFERENTIEL     syndromes.differential_diagnosis (chevauchement HPO calcule)
                   + discriminateurs
  EVOLUTION        verbatim NATURAL HISTORY
  DISCRIMINATEURS  verbatim COMMENT (present dans 53 % des entrees Smith)

Usage : python3 render_fiche_syndrome.py "<motif de titre>" [--orpha ORPHA:xxxx] [--md f.md]
"""
import argparse
import re
import sqlite3
import sys
from collections import defaultdict
from pathlib import Path

DB = "/home/mathevet/Bureau/foeto_base/syndromes_foetaux.db"
SMITH = Path("/home/mathevet/Bureau/Embedding_RAG_V2/chapitres/smith")
SPRANGER = Path("/home/mathevet/Bureau/Embedding_RAG_V2/chapitres/spranger")
SEC = re.compile(r"^(ABNORMALITIES|OCCASIONAL ABNORMALITIES|NATURAL HISTORY|ETIOLOGY|COMMENT|References)\s*$", re.M)

# regions d'examen, dans l'ordre du geste
ORDRE = ["growth", "craniofacial", "eyes", "ears", "mouth", "neck", "thorax", "heart",
         "abdomen", "genitourinary", "limbs", "skeletal", "skin", "neuro", "performance", "other"]
FR = {"growth": "Croissance", "craniofacial": "Craniofacial", "eyes": "Yeux", "ears": "Oreilles",
      "mouth": "Bouche", "neck": "Cou", "thorax": "Thorax", "heart": "Cœur", "abdomen": "Abdomen",
      "genitourinary": "Génito-urinaire", "limbs": "Membres", "skeletal": "Squelette",
      "skin": "Téguments", "neuro": "Système nerveux", "performance": "Développement", "other": "Autre"}


def sections(fichier, base):
    p = base / fichier.split("#")[0]
    if not p.exists():
        return {}
    parts = SEC.split(p.read_text(encoding="utf-8"))
    return {parts[i]: parts[i + 1].strip() for i in range(1, len(parts) - 1, 2)}


def differentiels(c, orpha, syn, n_max=5, par_diag=6):
    """Pour chaque differentiel : les signes FOETAUX qui separent, dans les deux sens.

    Un differentiel sans signe discriminant est une information en soi — c'est le
    cas ou il faut le genotype. On le dit plutot que de laisser la section vide.
    """
    noms = re.findall(r"\*\*(.+?)\*\*", syn["differential_diagnosis"] or "")[:n_max]
    atteste = {r[0] for r in c.execute("select distinct hpo_id from syndrome_hpo_livres where syndrome_id=?", (orpha,))}

    def signes(sid):
        return {r["hpo_id"]: (r["label_fr"] or r["label_en"]) for r in c.execute(
            """select sh.hpo_id, t.label_fr, t.label_en from syndrome_hpo sh
               join hpo_terms t on t.hpo_id=sh.hpo_id where sh.syndrome_id=?
               and t.context in ('prenatal','both') and t.is_excluded=0""", (sid,))}

    mes = signes(orpha)
    out = []
    for nom in noms:
        r = c.execute("select id, name_fr from syndromes where name_fr=?", (nom,)).fetchone()
        if not r:
            continue
        ses = signes(r["id"])
        comm = len(set(mes) & set(ses))
        ici = [(h, lab, "  ✓livre" if h in atteste else "") for h, lab in mes.items() if h not in ses]
        la_bas = [(h, lab, "") for h, lab in ses.items() if h not in mes]
        ici.sort(key=lambda x: (not x[2], x[1]))        # les attestes d'abord
        out.append((r["id"], r["name_fr"], comm, ici[:par_diag], la_bas[:par_diag]))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("motif", nargs="?", default="")
    ap.add_argument("--orpha")
    ap.add_argument("--md")
    ap.add_argument("--titre", help="titre EXACT d'entree (mode serie)")
    ap.add_argument("--all", metavar="DOSSIER", help="rend toutes les entrees de niveau syndrome dans DOSSIER")
    a = ap.parse_args()
    if a.all:
        return serie(Path(a.all))
    c = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    c.row_factory = sqlite3.Row
    L = []

    if a.titre:
        sig = c.execute("""select * from v_syndrome_hpo_livres_foetal
                           where syndrome_titre = ? order by niveau, region""", (a.titre,)).fetchall()
        a.motif = a.titre
    else:
        sig = c.execute("""select * from v_syndrome_hpo_livres_foetal
                           where syndrome_titre like ? order by niveau, region""",
                        (f"%{a.motif}%",)).fetchall()
    if not sig:
        raise SystemExit(f"aucune attestation pour « {a.motif} »")
    titre = sig[0]["syndrome_titre"]
    fichier, livre = sig[0]["entree"], sig[0]["livre"]
    orpha = a.orpha or sig[0]["syndrome_id"]
    syn = c.execute("select * from syndromes where id=?", (orpha,)).fetchone() if orpha else None

    L.append(f"# {syn['name_fr'] if syn else titre}")
    L.append(f"\n*Fiche composée depuis la base — chaque ligne remonte à sa source. "
             f"{len(sig)} signes attestés, filtre fœtal appliqué.*\n")

    # --- FAMILLE ----------------------------------------------------------
    L.append("## 1. Famille")
    fam = c.execute("""select distinct syndrome_titre, entree from syndrome_hpo_livres
                       where niveau_entree='famille' and (syndrome_titre like '%FGFR3%'
                          or syndrome_titre like ? )""", (f"%{a.motif}%",)).fetchall()
    if syn:
        L.append(f"- **Catégorie** (base) : {syn['category']}")
    for f in fam:
        L.append(f"- **Chapitre Spranger** : {f['syndrome_titre']}  \n  `{f['entree']}`")
    if not fam:
        L.append("- *(aucun chapitre de famille apparié — à rattacher)*")

    # --- IDENTITE ---------------------------------------------------------
    secs = sections(fichier, SMITH if livre == "smith" else SPRANGER)
    L.append("\n## 2. Identité")
    if syn:
        L.append(f"- **ORPHA** : {syn['id']} — *{syn['name_en']}*")
        if syn["omim"]:
            L.append(f"- **OMIM** : {syn['omim']}")
    L.append(f"- **Entrée du livre** : {titre}  \n  `{livre}/{fichier}`")
    if secs.get("ETIOLOGY"):
        L.append(f"\n> {secs['ETIOLOGY'][:700]}\n>\n> — *{livre}, {titre}, ETIOLOGY*")

    # --- SIGNES -----------------------------------------------------------
    # Clinique et radio sont SEPARES a la lecture — deux temps de l'examen —
    # mais forment une seule unite diagnostique : rien ne les pondere
    # differemment, la radio foetale etant systematique (Remi, 2026-09-12).
    L.append("\n## 3. Signes attestés, dans l'ordre de l'examen")
    clin = [s for s in sig if s["modalite"] != "radiographique"]
    radio = [s for s in sig if s["modalite"] == "radiographique"]

    def bloc(lignes):
        par_reg = defaultdict(list)
        for s in lignes:
            par_reg[s["region"] or "other"].append(s)
        for reg in ORDRE + [r for r in par_reg if r not in ORDRE]:
            if reg not in par_reg:
                continue
            L.append(f"\n#### {FR.get(reg, reg)}")
            L.append("| signe | HPO | niveau | fréquence | source |")
            L.append("|---|---|---|---|---|")
            vus = set()
            for s in sorted(par_reg[reg], key=lambda x: (x["niveau"] != "principal", x["signe_livre"])):
                if (s["hpo_id"], s["livre"]) in vus:
                    continue
                vus.add((s["hpo_id"], s["livre"]))
                lab = s["label_fr"] or s["label_en"]
                par = " *(parent)*" if s["est_parent"] else ""
                L.append(f"| {s['signe_livre']} | `{s['hpo_id']}` {lab}{par} | {s['niveau']} | "
                         f"{s['frequence'] or '—'} | {s['livre'].replace('_entites', '')} |")

    L.append("\n### 3a. Examen clinique et autopsie")
    bloc(clin)
    if radio:
        L.append("\n### 3b. Radiographie")
        bloc(radio)
        L.append("\n*Les descriptions radiologiques de Spranger sont plus fines que le grain HPO : "
                 "seules 29 % trouvent un code. Les autres vivent dans le verbatim de la section "
                 "MAJOR RADIOGRAPHIC FEATURES, reproduit au §7.*")

    # --- COTATION V2 ------------------------------------------------------
    L.append("\n## 4. Cotation V2 (vocabulaire de paillasse)")
    if orpha:
        v2 = c.execute("""select t.id, t.label_fr, t.organe, v.score, v.source
                          from syndrome_foeto_v2 v join foeto_terms t on t.id=v.foeto_id
                          where v.syndrome_id=? order by v.score desc""", (orpha,)).fetchall()
        if v2:
            L.append("| terme FOETO | organe | score | canal |")
            L.append("|---|---|---|---|")
            for r in v2:
                L.append(f"| {r['label_fr']} `{r['id']}` | {r['organe']} | {r['score']:.3f} | {r['source']} |")
        else:
            L.append("*(aucune cotation V2)*")
    L.append("\n*Le score V2 vient des vignettes et du RAG, pas des livres : il dit ce que la "
             "PRATIQUE associe au syndrome, là où le §3 dit ce que la LITTÉRATURE atteste. "
             "Les deux se lisent ensemble, jamais l'un pour l'autre.*")

    # --- DIFFERENTIEL -----------------------------------------------------
    L.append("\n## 5. Diagnostic différentiel — et ce qui tranche")
    # d'abord ce que le LIVRE ecrit (Spranger, MAJOR DIFFERENTIAL DIAGNOSES) :
    # un paragraphe par syndrome a distinguer, avec les criteres — source
    # verifiable, contrairement au chevauchement Orphanet qui suit en repli
    dl = c.execute("""select diff_nom, diff_syndrome_id, verbatim, syndrome_titre from syndrome_diff_livres
                      where syndrome_titre like ? order by id""", (f"%{a.motif}%",)).fetchall()
    if dl:
        L.append(f"\n### 5a. Selon le livre — *spranger, {dl[0]['syndrome_titre']}, MAJOR DIFFERENTIAL DIAGNOSES*")
        for d in dl:
            nom = d["diff_nom"] or "(sans nom)"
            orpha = f"  `{d['diff_syndrome_id']}`" if d["diff_syndrome_id"] else ""
            L.append(f"\n**{nom}**{orpha}  \n> {d['verbatim'][:600]}")
        L.append("\n### 5b. Par chevauchement HPO (Orphanet) — en repli")
    if syn:
        for autre_id, autre_nom, comm, ici, la_bas in differentiels(c, orpha, syn):
            L.append(f"\n### {autre_nom}  `{autre_id}`")
            L.append(f"{comm} signes en commun.")
            if ici:
                L.append(f"\n**En faveur de {syn['name_fr']}** — présent ici, absent chez l'autre :\n")
                for h, lab, att in ici:
                    L.append(f"- {lab} `{h}`{att}")
            if la_bas:
                L.append(f"\n**En faveur de {autre_nom}** — présent chez l'autre, absent ici :\n")
                for h, lab, att in la_bas:
                    L.append(f"- {lab} `{h}`{att}")
            if not ici and not la_bas:
                L.append("\n*Aucun signe fœtal ne les sépare dans la base — à trancher sur le "
                         "génotype ou la radiographie.*")
        L.append("\n*Calculé sur syndrome_hpo (Orphanet), filtre fœtal appliqué. « ✓livre » marque "
                 "les signes que syndrome_hpo_livres atteste aussi — ceux-là sont vérifiables, "
                 "les autres sont déclaratifs.*")

    # --- EVOLUTION / COMMENT ---------------------------------------------
    if secs.get("NATURAL HISTORY"):
        L.append("\n## 6. Évolution")
        L.append(f"> {secs['NATURAL HISTORY'][:1200]}\n>\n> — *{livre}, {titre}, NATURAL HISTORY*")
    # --- MICRO ATTESTEE (syndrome_foeto_livres) --------------------------
    micro = c.execute("""select * from syndrome_foeto_livres
                         where syndrome_titre = ? or (? is not null and syndrome_id = ?)
                         order by case niveau when 'direct' then 0 when 'contexte' then 1 else 2 end,
                                  age, organe, livre""", (titre, orpha, orpha)).fetchall()
    if micro:
        L.append("\n## 7. Micro attestée")
        L.append("\n*Signes histologiques que les livres de pathologie attribuent à cette entité — "
                 "verbatim et source à chaque ligne. « Selon le groupe » = histologie décrite pour la famille, "
                 "héritée, jamais une attestation directe. GeneReviews décrit une biopsie postnatale, pas la lame fœtale.*")
        vus, bloc = set(), None
        for m in micro:
            k = m["verbatim"][:60].lower()     # meme phrase, deux formulations du signe : une ligne
            if k in vus:
                continue
            vus.add(k)
            b = ("Selon le groupe — " + m["famille"]) if m["niveau"] == "famille" else \
                ("Attesté pour l'entité" if m["niveau"] == "direct" else "Par contexte (le passage en parle sans la nommer dans la phrase)")
            if b != bloc:
                L.append(f"\n### {b}")
                bloc = b
            fo = f" `{m['foeto_id']}`" if m["foeto_id"] else " *(terme FOETO à créer)*"
            age = " — *biopsie postnatale*" if m["age"] == "postnatal" else ""
            L.append(f"- **{m['signe']}** ({m['organe'] or '?'}){fo} — « {m['verbatim']} » "
                     f"[{m['livre']}, {m['chapitre']}]{age}")
        L.append("\n*Composé depuis syndrome_foeto_livres (arbitrage première passe, statut arbitrage_ia).*")
    else:
        L.append("\n## 7. Micro attestée")
        L.append("\n*Aucune histologie attestée dans le corpus pour cette entité — ni en direct, ni par sa famille. "
                 "La lame est celle de ses malformations, portées par les grilles d'organe.*")

    if secs.get("COMMENT"):
        L.append("\n## 8. Commentaire du livre")
        L.append(f"> {secs['COMMENT'][:1200]}\n>\n> — *{livre}, {titre}, COMMENT*")
    # verbatim radiographique de Spranger, pour ce que HPO ne code pas
    sp = c.execute("""select distinct entree, syndrome_titre from syndrome_hpo_livres
                      where livre='spranger_entites' and syndrome_titre like ?""", (f"%{a.motif}%",)).fetchone()
    if sp:
        chemin = Path("/home/mathevet/Bureau/Embedding_RAG_V2/chapitres/spranger_entites") / sp["entree"].split("#")[0]
        if chemin.exists():
            corps = chemin.read_text(encoding="utf-8")
            m = re.search(r"^[ \t]*M\s*A\s*J\s*O\s*R\s+R\s*A\s*D\s*I\s*O\s*G\s*R\s*A\s*P\s*H\s*I\s*C\s+F\s*E\s*A\s*T\s*U\s*R\s*E\s*S[ \t]*$(.*?)^[ \t]*M\s*A\s*J\s*O\s*R\s+D", corps, re.M | re.S)
            if m:
                L.append("\n## 9. Sémiologie radiologique — verbatim Spranger")
                L.append("> " + re.sub(r"\n+", "\n> ", m.group(1).strip())[:1500])
                L.append(f">\n> — *spranger, {sp['syndrome_titre']}, MAJOR RADIOGRAPHIC FEATURES*")

    md = "\n".join(L)
    if a.md:
        Path(a.md).write_text(md, encoding="utf-8")
        print(f"-> {a.md} ({len(md)} car.)")
    else:
        print(md)


def serie(dossier):
    """Toutes les entrees de niveau syndrome -> un .md par entree, en sous-processus
    (le rendu est ecrit pour une entree ; on ne le refactore pas pour 500)."""
    import subprocess
    dossier.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    ents = c.execute("""select distinct syndrome_titre, syndrome_id, livre from syndrome_hpo_livres
                        where niveau_entree='syndrome' order by livre, syndrome_titre""").fetchall()
    ok = 0
    for titre, sid, livre in ents:
        slug = re.sub(r"_+", "_", re.sub(r"[^a-z0-9]+", "_", titre.lower())).strip("_")[:70]
        out = dossier / f"{livre.replace('_entites', '')}__{slug}.md"
        cmd = [sys.executable, __file__, "--titre", titre, "--md", str(out)]
        if sid:
            cmd += ["--orpha", sid]
        r = subprocess.run(cmd, capture_output=True, text=True)
        if r.returncode == 0:
            ok += 1
        else:
            print(f"  !! {titre[:60]} : {r.stderr.strip()[-120:]}", flush=True)
        if ok % 50 == 0 and ok:
            print(f"  {ok}/{len(ents)}", flush=True)
    print(f"{ok}/{len(ents)} fiches -> {dossier}")


if __name__ == "__main__":
    main()
