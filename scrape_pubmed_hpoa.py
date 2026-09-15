#!/usr/bin/env python3
"""Abstracts PubMed pour les entites hpoa (vrais trous OMIM sans livre).

Reprend scrape_pubmed_cases (E-utilities, 3 req/s, insertion case_reports
format pubmed_abstract, source pubmed:<pmid>) avec deux requetes par entite :
  - generale : nom + case report + (fetal OR prenatal OR neonatal OR autopsy…)
  - PDP : nom + "Pediatr Dev Pathol"[Journal] (sans contrainte case report)
Le nom OMIM est souvent inverse (« Myopathy, congenital, compton-north ») :
au-dela de 4 mots utiles ou avec des virgules on cherche les mots en AND,
sinon la phrase exacte. syndrome_id = entite_id (ORPHA ou OMIM:<n>).
Deja present = meme (syndrome_id, pmid) ; rejouable.

Usage : nohup python3 -u scrape_pubmed_hpoa.py > logs_pubmed_hpoa.log &
"""
import importlib.util
import re
import sqlite3
import time
from pathlib import Path

import scrape_pubmed_cases as S

DB = Path("/home/mathevet/Bureau/foeto_base/syndromes_foetaux.db")
FOET = "(fetal OR fetus OR prenatal OR neonatal OR newborn OR autopsy OR stillbirth OR hydrops)"
SUFFIXES = re.compile(r",\s*(autosomal (recessive|dominant)|x-linked( (recessive|dominant))?|susceptibility to)", re.I)


def terme(nom):
    n = SUFFIXES.sub("", nom).replace("(", " ").replace(")", " ").strip()
    mots = [m for m in re.split(r"[\s,]+", n) if m and m.lower() not in S_STOP]
    if "," in n or len(mots) > 4:
        return " AND ".join(m.replace("-", " ") for m in mots)      # « "compton-north" » cité = 0 résultat, séparé = 7
    return f'"{n}"'


S_STOP = {"syndrome", "type", "with", "and", "or", "of", "the", "due", "to", "in"}


def esearch(term, retmax):
    r = S.requests.get(S.ESEARCH_URL, params={"db": "pubmed", "term": term, "retmax": retmax, "retmode": "json", "sort": "relevance"}, timeout=20)
    r.raise_for_status()
    return r.json().get("esearchresult", {}).get("idlist", [])


def main():
    c = sqlite3.connect(DB)
    ents = c.execute("""select e.entite_id, t.syndrome_titre from entites_livres e join entites_livres_titres t using(entite_id)
                        where e.livres='hpoa' order by e.entite_id""").fetchall()
    deja = {(s, p) for s, p in c.execute("select syndrome_id, pmid from case_reports where pmid is not null")}
    tot, pdp_tot, sans = 0, 0, []
    for i, (eid, nom) in enumerate(ents, 1):
        pm = {}
        # phrase exacte d'abord ; si rien, sans le numero de sous-type (« …contracture syndrome 10 » -> la famille)
        for t in dict.fromkeys([terme(nom), terme(re.sub(r"\s+\d+[A-Z]?$", "", nom))]):
            for q, k, tag in ((f"{t} AND case report AND {FOET}", 15, "gen"), (f'{t} AND "Pediatr Dev Pathol"[Journal]', 10, "pdp"), (f"{t} AND {FOET}", 10, "large")):
                if tag == "large" and pm:                      # repli sans « case report » seulement si rien
                    break
                try:
                    for p in esearch(q, k):
                        pm.setdefault(p, tag)
                except Exception as e:
                    print(f"  {eid} esearch {tag}: {e}", flush=True)
                time.sleep(S.RATE_LIMIT)
            if pm:
                break
        nouveaux = [p for p in pm if (eid, p) not in deja]
        n = 0
        if nouveaux:
            for art in S.fetch_abstracts(nouveaux):
                if len(art["abstract"]) < S.MIN_ABSTRACT_LEN:
                    continue
                txt = f"[{art['title']}]\n\n{art['abstract']}" + (f"\n\n(Published: {art['year']}, {art['journal']})" if art["year"] else "")
                c.execute("""insert into case_reports (syndrome_id, gold_diagnosis, clinical_text, hpo_tags, format, source, source_model, difficulty, pmid)
                             values (?,?,?,?,?,?,?,?,?)""",
                          (eid, nom, txt, S.extract_hpo_tags(art["abstract"]), "pubmed_abstract", f"pubmed:{art['pmid']}", None, "real_case", art["pmid"]))
                deja.add((eid, art["pmid"]))
                n += 1
                pdp_tot += pm.get(art["pmid"]) == "pdp"
            c.commit()
            time.sleep(S.RATE_LIMIT)
        tot += n
        if not pm:
            sans.append(f"{eid} {nom}")
        print(f"{i:3d}/{len(ents)} {eid:13s} {nom[:55]:55s} {len(pm):2d} pmid, {n:2d} nouveaux", flush=True)
    resume = f"{len(ents)} entités hpoa : {tot} abstracts insérés ({pdp_tot} PDP), {len(sans)} entités sans aucun PMID"
    print(resume)
    spec = importlib.util.spec_from_file_location("notify", "/home/mathevet/Bureau/tmux_supervisor/embeddings/pipeline_v2/08_notify.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    m.send_email("PubMed + PDP — entités hpoa", resume + "\n\nSans PMID :\n" + "\n".join(sans), m.SMTP_USER)


if __name__ == "__main__":
    main()
