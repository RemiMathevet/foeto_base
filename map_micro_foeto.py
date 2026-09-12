#!/usr/bin/env python3
"""Mapping DETERMINISTE des signes micro extraits (syndrome_micro_livres_candidats)
vers foeto_terms -> arbitrage_micro_foeto.tsv, a arbitrer par Remi.

Aucun LLM. Trois voies, par ordre de confiance :
  exact    label_en (ou label_fr) normalise contenu dans le signe ou le verbatim
  tokens   part des mots pleins du label FOETO retrouves dans signe+verbatim (>= 0,6)
  hpo      une forme anglaise NAME/EXACT d'un HPO retrouvee dans le signe, puis
           foeto_hpo -> terme FOETO
Les candidats sont restreints a l'organe du signe (organe LLM -> organes
FOETO) + multi_organe + parenchyme. Jusqu'a 3 candidats par signe ; colonne
`choix` vide a remplir : 1/2/3, un id FOETO, NON (pas de terme), NOUVEAU
(terme a creer).

Usage : python3 map_micro_foeto.py [sortie.tsv]
"""
import csv
import re
import sqlite3
import sys
import unicodedata
from collections import defaultdict

DB = "/home/mathevet/Bureau/foeto_base/syndromes_foetaux.db"
OUT = sys.argv[1] if len(sys.argv) > 1 else "/home/mathevet/Bureau/foeto_base/arbitrage_micro_foeto.tsv"

ORGANES = {
    "cerveau": r"brain|cerebell|medulla|cortex|white matter|gray matter|grey matter|spinal cord|leptomening|corpus callosum|cerebr|neuron|hippocamp|basal ganglia|brainstem|pons|olivary|ependym|choroid plexus|moelle|cervelet|encéphal|neurone|ganglions|thalam|hypothalam|pituitary|hypophys",
    "squelette": r"\bbone\b|cartilag|growth plate|metaphys|epiphys|physis|vertebr|rib|skeleton|osteo|chondr|\bos\b|periost|trabecul",
    "peau": r"skin|epiderm|dermis|hair|nail|peau|derme|follicle",
    "oeil_oreille": r"\beye|retina|lens|optic|cornea|iris|ciliary body|sclera|choroid\b|vitreous|cristallin|œil|oeil|rétine|ear\b|cochlea|inner ear|oreille",
    "placenta": r"placent|villi|villous|trophoblast|decidua|chorion|amnion|membranes|umbilical|cord\b|cordon",
    "membranes": r"membranes|amnion|chorion",
    "cordon": r"umbilical cord|cordon",
    "muscle": r"muscle|myofib|myopath|muscular|sarcomer",
    "rein": r"kidney|renal|glomerul|tubul|nephron|collecting duct|ureter|bladder|urinary|rein|rénal",
    "foie": r"liver|hepat|bile duct|biliary|portal|ductal plate|gallbladder|foie|hépat",
    "coeur": r"heart|myocard|endocard|valve|aort|cardiac|coronary|pulmonary artery|ductus|conduction|cœur|coeur",
    "poumon": r"lung|pulmon|alveol|bronch|trache|larynx|laryng|pleura|poumon",
    "endocrine": r"pancrea|adrenal|thyroid|parathyroid|pituitary|islet|endocrine|surrénal|thyroïd",
    "genital": r"gonad|testis|testic|ovar|uterus|vagina|genital|wolffian|müllerian|mullerian|prostate",
    "digestif": r"intestin|bowel|colon|stomach|gastric|esophag|oesophag|duoden|jejun|ileum|rectum|anus|enteric|myenteric|ganglion cells|digestif",
    "hematolymphoide": r"bone marrow|spleen|thymus|lymph|hematopoie|erythro|blood|rate\b|thymique|leukocyte|lymphocyte",
}
STOP = {"with", "and", "the", "of", "in", "or", "to", "a", "an", "by", "from", "at", "on", "de", "la", "le", "les", "des",
        "du", "et", "en", "avec", "par", "pour", "sur", "dans", "un", "une", "d", "l", "au", "aux", "cells", "cell",
        "tissue", "changes", "change", "increased", "decreased", "abnormal", "normal", "presence", "present", "absent",
        "absence", "focal", "diffuse", "marked", "mild", "severe", "cellules", "cellule", "tissu", "aspect", "anomalie",
        "anomalies", "type", "like", "shaped", "areas", "area", "features", "feature", "pattern"}


def norm(s):
    s = "".join(ch for ch in unicodedata.normalize("NFD", (s or "").lower()) if unicodedata.category(ch) != "Mn")
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9\s-]", " ", s)).strip()


def toks(s):
    out = set()
    for w in norm(s).replace("-", " ").split():
        if len(w) < 4 or w in STOP:
            continue
        w = re.sub(r"(ies)$", "y", w)
        w = re.sub(r"(es|s)$", "", w) if len(w) > 4 else w
        out.add(w[:8])          # prefixe : fibrosis/fibrotic/fibrose se rejoignent
    return out


def organes_de(organe):
    o = norm(organe or "")
    out = {k for k, rx in ORGANES.items() if re.search(rx, o)}
    return out or set(ORGANES)  # organe inconnu : on cherche partout


def main():
    c = sqlite3.connect(DB)
    ft = c.execute("select id, organe, label_fr, label_en, triage_verdict from foeto_terms").fetchall()
    par_org = defaultdict(list)
    for fid, org, fr, en, v in ft:
        par_org[org].append((fid, fr, en, v, toks(en or ""), toks(fr or ""), norm(en or ""), norm(fr or "")))
    # formes anglaises HPO -> foeto via foeto_hpo
    f2h = defaultdict(set)
    for fid, h in c.execute("select foeto_id, hpo_id from foeto_hpo"):
        f2h[h].add(fid)
    formes_hpo = [(norm(f), h) for h, f in c.execute(
        "select hpo_id, forme from hpo_synonymes where langue='en' and portee in ('NAME','EXACT') and length(forme) >= 8")
        if h in f2h]
    lab = {fid: (fr or en) for fid, org, fr, en, v in ft}
    org_of = {fid: org for fid, org, fr, en, v in ft}

    rows = c.execute("""select id, syndrome_titre, syndrome_id, livre, chapitre, organe, attribution, signe, verbatim
                        from syndrome_micro_livres_candidats where verbatim_ok=1 order by syndrome_titre, livre, id""").fetchall()
    out, n_exact, n_tok, n_hpo, n_zero = [], 0, 0, 0, 0
    for rid, titre, sid, livre, chap, organe, attr, signe, verb in rows:
        orgs = organes_de(organe) | {"multi_organe", "parenchyme"}
        # le SIGNE est l'unite ; le verbatim porte souvent plusieurs constats
        # (« mural thrombosis » -> Calcifications parce que la phrase les cite) :
        # une correspondance sur le verbatim seul vaut moins, jamais 1,0
        nsig, nverb = norm(signe), norm(verb)
        tsig, tverb = toks(signe), toks(verb)
        cands = {}
        for org in orgs:
            for fid, fr, en, v, ten, tfr, nen, nfr in par_org.get(org, []):
                if v == "NON_LESION":
                    continue
                for nl in (nen, nfr):
                    if nl and len(nl) >= 8:
                        if nl in nsig:
                            cands[fid] = max(cands.get(fid, 0), 1.0)
                        elif nl in nverb:
                            cands[fid] = max(cands.get(fid, 0), 0.8)
                for tl in (ten, tfr):
                    if len(tl) >= 2:
                        for tt, coef in ((tsig, 0.9), (tverb, 0.7)):
                            sc = len(tl & tt) / len(tl)
                            if sc >= 0.6:
                                cands[fid] = max(cands.get(fid, 0), round(sc * coef, 2))
        ns = norm(signe)
        for f, h in formes_hpo:
            if f in ns:
                for fid in f2h[h]:
                    if org_of.get(fid) in orgs:
                        cands[fid] = max(cands.get(fid, 0), 0.5)
        # un terme de STRUCTURE NORMALE (-NOR-) n'est pas une lesion : jamais pre-rempli,
        # plafonne a 0,6 (« vacuolization of the syncytiotrophoblast » -> Syncytiotrophoblaste)
        for fid in list(cands):
            if "-NOR-" in fid:
                cands[fid] = min(cands[fid], 0.6)
        top = sorted(cands.items(), key=lambda x: -x[1])[:3]
        if not top:
            n_zero += 1
        elif top[0][1] >= 1.0:
            n_exact += 1
        elif top[0][1] > 0.5:
            n_tok += 1
        else:
            n_hpo += 1
        rec = {"id": rid, "syndrome": titre, "syndrome_id": sid, "livre": livre, "chapitre": chap,
               "organe_llm": organe, "attribution": attr, "signe": signe, "verbatim": verb}
        for i in range(3):
            if i < len(top):
                fid, sc = top[i]
                rec[f"cand{i+1}"] = f"{fid} | {lab[fid]} | {org_of[fid]} | {sc}"
            else:
                rec[f"cand{i+1}"] = ""
        rec["choix"] = "1" if top and top[0][1] >= 1.0 else ""
        out.append(rec)
    with open(OUT, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(out[0].keys()), delimiter="\t")
        w.writeheader(); w.writerows(out)
    print(f"{len(out)} signes -> {OUT}\n  exact {n_exact} (choix pre-rempli) · tokens {n_tok} · hpo seul {n_hpo} · sans candidat {n_zero}")


if __name__ == "__main__":
    main()
