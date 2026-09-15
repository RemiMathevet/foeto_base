#!/usr/bin/env python3
"""Extraction des signes par syndrome depuis Smith (grain syndrome) et Spranger
(grain famille) -> table syndrome_signes_livres_candidats, A RELIRE.

Statut de ce que ca produit : un PRE-TRI. Le LLM ne fait qu'isoler, dans le
texte du livre, les signes que le livre cite, chacun avec son verbatim. Il ne
mappe PAS vers HPO (fait ensuite, deterministe, par label_en / aliases), il ne
note pas la pertinence, il n'invente pas de frequence : la frequence n'est
gardee que si le livre la chiffre. Une ligne dont le verbatim ne se retrouve
pas dans le chunk est marquee verbatim_ok=0 et ne compte pas.

Smith donne lui-meme deux niveaux — « ABNORMALITIES » (avec ou sans %) et
« OCCASIONAL ABNORMALITIES » — qu'on garde tels quels dans `niveau` : c'est la
reponse naturelle a la question binaire/gradue (PREFECT foeto_base 5346afe04b4f).

Modele : Qwen3.6-35B-direct via MAGOS (extraction, pas de delibération),
T=0.2 — ce n'est pas un bras de banc, la regle de temperature native ne
s'applique pas.

Usage : python3 extract_signes_livres.py [--livre smith|spranger] [--limit N]
"""
import argparse
import json
import re
import sqlite3
import sys
import time
from pathlib import Path

sys.path.insert(0, "/home/mathevet/Bureau/tmux_supervisor/magos")
from magos_client import MagosClient

DB = "/home/mathevet/Bureau/foeto_base/syndromes_foetaux.db"
CHAP = Path("/home/mathevet/Bureau/Embedding_RAG_V2/chapitres")
MODEL = "Qwen3.6-35B-direct"
WIN, OVER = 20000, 800                          # fenetre ~5 000 tokens, recouvrement 800 car.

# Spranger decoupe a l'entite (split_spranger_entites.py) : le livre separe
# lui-meme signes cliniques et signes radiographiques. On extrait SECTION PAR
# SECTION et la modalite vient du livre — plus d'heuristique a inventer, ce que
# ni le verbatim ni la definition HPO ne permettaient (2026-09-12).
def _tol(phrase):
    return r"\s*".join(r"\s*".join(mot) for mot in phrase.split())


SECTIONS_SPRANGER = {
    "MAJOR CLINICAL FINDINGS": "clinique",
    "MAJOR RADIOGRAPHIC FEATURES": "radiographique",
}
RX_SPRANGER = re.compile(
    r"^[ \t]*(" + "|".join(_tol(k) for k in list(SECTIONS_SPRANGER) +
                            ["MAJOR DIFFERENTIAL DIAGNOSES", "COURSE AND PROGNOSIS",
                             "MODE OF INHERITANCE", "GENETICS", "REMARKS", "TREATMENT",
                             "BIBLIOGRAPHY"]) + r")[ \t]*$", re.M)


def sections_spranger(corps):
    """(modalite, texte) des seules sections porteuses de signes."""
    parts = RX_SPRANGER.split(corps)
    out = []
    for i in range(1, len(parts) - 1, 2):
        nom = re.sub(r"\s+", " ", parts[i]).upper()
        for cle, mod in SECTIONS_SPRANGER.items():
            if re.sub(r"\s+", "", nom) == re.sub(r"\s+", "", cle):
                out.append((mod, parts[i + 1].strip()))
    return out

SYSTEM = """You extract clinical signs from a reference textbook entry about ONE syndrome.
Return ONLY a JSON object, no prose:
{"syndrome": "<name as in the text>",
 "signes": [{"signe": "<short sign, English, as the book words it>",
             "verbatim": "<the exact phrase from the text, 5-25 words, copied verbatim>",
             "frequence": "<percentage exactly as written, e.g. '30%', or null>",
             "niveau": "<'principal' if listed under ABNORMALITIES / main features, 'occasionnel' if under OCCASIONAL ABNORMALITIES or described as occasional/rare, else 'texte'>",
             "region": "<growth|performance|craniofacial|eyes|ears|mouth|neck|thorax|heart|abdomen|genitourinary|limbs|skeletal|skin|neuro|other>"}]}
Rules: one entry per sign. Copy, never paraphrase, the verbatim. Never invent a percentage.
Skip natural history, etiology, genetics, references, management."""


RX_GR_CLIN = re.compile(r"Clinical Characteristics|Clinical Description|Suggestive Findings|Phenotyp|Establishing the Diagnosis|Natural History", re.I)
RX_GR_HORS = re.compile(r"Literature Cited|References|Molecular Genetics|Management|Genetic Counseling|Resources|Chapter Notes|Revision History|Differential Diagnosis|Treatment|Surveillance|Evaluation", re.I)


def entries_genereviews():
    """GeneReviews (genereviews_full) : les sections CLINIQUES de chaque chapitre, en
    fenetres ; les chapitres dont l'ORPHA (par MIM) est un syndrome 'haute' de la base
    SANS aucune attestation de livre passent en premier — c'est la ou la matrice manque."""
    import json
    import sqlite3
    c = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    mim2orpha = {}
    for sid, om in c.execute("select id, omim from syndromes where omim is not null and omim <> ''"):
        for m in om.split(","):
            mim2orpha.setdefault(m.strip(), sid)
    try:
        import xml.etree.ElementTree as ET
        for d in ET.parse("/home/mathevet/Bureau/foeto_base/orphadata/en_product1.xml").getroot().iter("Disorder"):
            sid = "ORPHA:" + d.findtext("OrphaCode")
            for r in d.iter("ExternalReference"):
                if r.findtext("Source") == "OMIM":
                    mim2orpha.setdefault(r.findtext("Reference"), sid)
    except Exception:
        pass
    haute = {r[0] for r in c.execute("select id from syndromes where relevance='haute'")}
    attestes = {r[0] for r in c.execute("select distinct syndrome_id from syndrome_hpo_livres where syndrome_id is not null")}
    chaps = []
    for slug, title, om, sj in c.execute("select slug, title, omim_ids, sections_json from genereviews_full"):
        secs = [x for x in json.loads(sj or "[]") if RX_GR_CLIN.search(x["path"]) and not RX_GR_HORS.search(x["path"].split(">")[-1])]
        if not secs:
            continue
        body = "\n\n".join(f"## {x['path'].split('>')[-1].strip()}\n{x['text']}" for x in secs)
        orphas = {mim2orpha[m] for m in re.findall(r"\d{6}", om or "") if m in mim2orpha}
        prio = 0 if any(o in haute and o not in attestes for o in orphas) else (1 if orphas & haute else 2)
        chaps.append((prio, slug, title.replace(" - GeneReviews® - NCBI Bookshelf", "").strip(), body))
    chaps.sort()
    for i, (prio, slug, title, body) in enumerate(chaps):
        if len(body) <= WIN:
            yield slug, i, title, body
        else:
            step = WIN - OVER
            for k, start in enumerate(range(0, len(body), step)):
                yield f"{slug}#w{k:02d}", i, title, body[start:start + WIN]
                if start + WIN >= len(body) or k >= 2:
                    break


def entries_pubmed():
    """Abstracts PubMed (case_reports, scrape_pubmed_hpoa) des entites hpoa : un abstract =
    une entree, fichier = <pmid>@<entite_id> (le meme PMID peut servir deux entites) ;
    build_syndrome_hpo_livres lit l'entite dans ce nom. Troisieme etage de preuve,
    tague livre='pubmed', jamais confondu avec un livre."""
    c = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    for cid, sid, pmid, titre, txt in c.execute("""select id, syndrome_id, pmid, gold_diagnosis, clinical_text from case_reports
            where format='pubmed_abstract' and pmid is not null
              and syndrome_id in (select entite_id from entites_livres where livres like '%hpoa%') order by id"""):
        yield f"{pmid}@{sid}", cid, titre, txt[:WIN]


def entries(livre):
    if livre == "genereviews":
        yield from entries_genereviews()
        return
    if livre == "pubmed":
        yield from entries_pubmed()
        return
    if livre == "spranger_entites":
        for f in sorted((CHAP / livre).glob("e*.txt")):
            lignes = f.read_text(encoding="utf-8").split("\n", 4)
            num, titre, corps = lignes[0].strip(), lignes[2].strip(), lignes[4] if len(lignes) > 4 else ""
            for mod, txt in sections_spranger(corps):
                if len(txt) > 80:
                    yield f"{f.name}#{mod}", int(num), f"{titre} [{mod}]", txt[:WIN]
        return
    for f in sorted((CHAP / livre).glob("ch*.txt")):
        lines = f.read_text(encoding="utf-8").split("\n", 4)
        num, title, body = lines[0].strip(), lines[2].strip(), lines[4] if len(lines) > 4 else ""
        if livre == "smith" and not re.match(r"^[A-W] ", title):
            continue                              # intro, ch. 2-5, appendice : pas des syndromes
        if livre == "limb" and int(num) < 5:
            continue                              # limb.pdf : ch. 1-4 = developpement, examen, radio, chirurgie
        if len(body) <= WIN:
            yield f.name, int(num), title, body
        else:                                     # Spranger : 53 k car. par famille en mediane
            step = WIN - OVER
            for i, start in enumerate(range(0, len(body), step)):
                yield f"{f.name}#w{i:02d}", int(num), title, body[start:start + WIN]
                if start + WIN >= len(body):
                    break


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--livre", choices=["smith", "spranger", "spranger_entites", "limb", "genereviews", "pubmed", "all"], default="all")
    ap.add_argument("--limit", type=int, default=0)
    a = ap.parse_args()
    c = sqlite3.connect(DB)
    c.execute("""CREATE TABLE IF NOT EXISTS syndrome_signes_livres_candidats (
        id INTEGER PRIMARY KEY, livre TEXT, fichier TEXT, entree_num INTEGER, syndrome_titre TEXT,
        syndrome_llm TEXT, signe TEXT, verbatim TEXT, verbatim_ok INTEGER, frequence TEXT,
        niveau TEXT, region TEXT, modele TEXT, extrait_le TEXT DEFAULT (datetime('now')))""")
    if "modalite" not in [r[1] for r in c.execute("pragma table_info(syndrome_signes_livres_candidats)")]:
        c.execute("alter table syndrome_signes_livres_candidats add column modalite TEXT")
    done = {(r[0], r[1]) for r in c.execute("select livre, fichier from syndrome_signes_livres_candidats")}
    cl = MagosClient(client_id="extract-signes-livres")
    livres = ["smith", "spranger_entites"] if a.livre == "all" else [a.livre]
    n = 0
    for livre in livres:
        for fname, num, title, body in entries(livre):
            if (livre, fname) in done:
                continue
            if a.limit and n >= a.limit:
                break
            t0 = time.time()
            try:
                r = cl.submit_and_wait(MODEL, f"TEXTBOOK ENTRY ({livre}, {title}):\n\n{body}",
                                       system=SYSTEM, priority=6, timeout_s=900, wait_timeout=1200,
                                       options={"temperature": 0.2, "num_predict": 12000})
                raw = r.get("response") or ""
                m = re.search(r"\{.*\}", raw, re.S)
                try:
                    d = json.loads(m.group()) if m else {}
                except json.JSONDecodeError:
                    # JSON tronque (3 cas le 2026-09-12 : le modele a boucle et
                    # depasse la fenetre). On recupere les objets signe COMPLETS
                    # deja ecrits plutot que de tout perdre.
                    objs = re.findall(r"\{[^{}]*\}", m.group() if m else raw)
                    sig = []
                    for o in objs:
                        try:
                            sig.append(json.loads(o))
                        except json.JSONDecodeError:
                            pass
                    d = {"syndrome": None, "signes": sig, "_tronque": 1}
                    print(f"    (JSON tronque : {len(sig)} signes recuperes sur {len(objs)} objets)", flush=True)
            except Exception as e:
                print(f"  {livre}/{fname}: ERREUR {e}", flush=True)
                c.execute("insert into syndrome_signes_livres_candidats(livre,fichier,entree_num,syndrome_titre,signe,verbatim_ok,modele) values(?,?,?,?,?,?,?)",
                          (livre, fname, num, title, f"__ERREUR__ {e}"[:200], 0, MODEL))
                c.commit(); continue
            rows, ok = [], 0
            norm = re.sub(r"\s+", " ", body.lower())
            for s in d.get("signes", []) or []:
                v = (s.get("verbatim") or "").strip()
                vok = 1 if v and re.sub(r"\s+", " ", v.lower())[:60] in norm else 0
                ok += vok
                rows.append((livre, fname, num, title, d.get("syndrome"), (s.get("signe") or "").strip(),
                             v, vok, s.get("frequence"), s.get("niveau"), s.get("region"), MODEL,
                             fname.split("#")[1] if "#" in fname else None))
            if not rows:
                rows = [(livre, fname, num, title, d.get("syndrome"), "__VIDE__", "", 0, None, None, None, MODEL,
                         fname.split("#")[1] if "#" in fname else None)]
            c.executemany("insert into syndrome_signes_livres_candidats(livre,fichier,entree_num,syndrome_titre,syndrome_llm,signe,verbatim,verbatim_ok,frequence,niveau,region,modele,modalite) values(?,?,?,?,?,?,?,?,?,?,?,?,?)", rows)
            c.commit(); n += 1
            print(f"  {livre}/{fname[:52]:52s} {len(rows):3d} signes, {ok:3d} verbatim ok, "
                  f"{sum(1 for x in rows if x[8]):3d} chiffres, {time.time()-t0:4.0f} s", flush=True)
    # LIKE '__%' matchait TOUT ('_' = joker d'un caractere en SQL) : le recap
    # affichait 0 alors que la table en portait 14 994 (2026-09-12).
    tot = c.execute("select count(*), sum(verbatim_ok), sum(frequence is not null), count(distinct fichier) "
                    "from syndrome_signes_livres_candidats where signe not like '\\_\\_%' escape '\\'").fetchone()
    print(f"\nTable : {tot[0]} signes, {tot[1]} verbatim ok, {tot[2]} chiffres, {tot[3]} entrees", flush=True)


if __name__ == "__main__":
    main()
