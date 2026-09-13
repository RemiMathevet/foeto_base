#!/usr/bin/env python3
"""ReAct HPO local : le modele choisit dans une LISTE de termes HPO trouves par l'index,
au lieu de nommer de memoire.

Cible : les signes de livres (verbatim_ok=1, hpo_id NULL) pour lesquels le 35B avait
propose un nom que l'index ne connait pas (signes_fragments.hpo_id NULL). Sur les 66
couples que ni Next ni Kimi ne tranchaient, le relecteur a tout resolu parce qu'il
avait l'index sous la main : on donne l'index au modele.
  1. recherche DETERMINISTE (Python, pas le modele) : pour chaque signe, les termes HPO
     dont le nom ou un synonyme NAME/EXACT partage des mots avec le signe et avec le
     nom que le 35B avait propose — Jaccard sur les mots pleins, top 10, avec la
     definition et le parent ;
  2. UN appel au 35B-direct par lot de 10 : il rend, par signe, un nom PRIS DANS LA
     LISTE (ou rien), avec « sur » ; un nom hors liste est refuse.
Sur -> hpo_id pose, hpo_methode='react_hpo' ; pas sur -> trace dans signes_fragments
(modele 'react_hpo?'), visible dans arbitrage_llm_nom.tsv, rien pose.

Usage : python3 react_hpo.py [--limit N] [--apply]
"""
import argparse
import json
import re
import sqlite3
import sys
import time
from collections import Counter, defaultdict

sys.path.insert(0, "/home/mathevet/Bureau/tmux_supervisor/magos")
import map_signes_hpo_obo as O
import map_signes_hpo_regles as R

MODEL = "Qwen3.6-35B-direct"
LOT = 10
TOP = 10
SYSTEM = """You map clinical sign phrases from dysmorphology / fetal pathology textbooks to Human Phenotype
Ontology (HPO) terms. For each phrase you get a verbatim sentence from the book and a NUMBERED LIST of
candidate HPO terms found by a lexical search (name, definition, parent). Choose the candidate whose meaning
matches the phrase — same concept, not more specific than what the book says (prefer the parent when the
book is vaguer). If none matches, choose none. Copy the candidate name EXACTLY as listed. "sur" is true only
when the match is clear.
Return ONLY JSON: {"items": [{"i": <phrase index>, "phrase": "<the phrase, copied>", "nom": "<candidate name or empty>", "sur": true|false}, ...]}"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()
    from magos_client import MagosClient
    c = sqlite3.connect(O.DB)
    obo = O.load_obo(O.OBO)
    ours = {r[0]: (r[1], r[2]) for r in c.execute("select hpo_id, label_en, aliases_fr from hpo_terms")}
    idx, idx_tok = R.index(obo, ours)
    # index inverse mot -> termes (formes NAME/EXACT seulement)
    formes = defaultdict(set)              # hpo_id -> {frozenset de racines}
    par_mot = defaultdict(set)
    STOP_REQ = {"abnormal", "abnormality", "morphology", "of", "the", "anomaly", "defect"}

    def racines(mots):
        # aganglionosis / aganglionic, porencephaly / porencephalic : racine = 7 premieres lettres
        return frozenset(w[:7] if len(w) > 7 else w for w in mots if w not in STOP_REQ)

    for k, (hid, scope) in idx_tok.items():
        if scope in ("NAME", "EXACT") and k and hid in obo:      # obsoletes (dans nos alias) ecartes
            r = racines(k)
            if r:
                formes[hid].add(r)
                for w in r:
                    par_mot[w].add(hid)

    def chercher(*textes):
        score = Counter()
        for t in textes:
            q = racines(O.toks(t))
            if not q:
                continue
            cands = Counter()
            for w in q:
                for hid in par_mot.get(w, ()):
                    cands[hid] += 1
            for hid, _ in cands.most_common(400):
                j = max(len(q & f) / len(q | f) for f in formes[hid])
                score[hid] = max(score[hid], j)
        return [h for h, s in score.most_common(TOP) if s > 0]

    fait = {r[0] for r in c.execute("select distinct candidat_id from signes_fragments where modele like 'react_hpo%'")}
    rows = [r for r in c.execute("""select s.id, s.signe, s.verbatim, s.livre, s.syndrome_titre, group_concat(f.fragment, ' | ')
                                    from syndrome_signes_livres_candidats s join signes_fragments f on f.candidat_id = s.id
                                    where s.verbatim_ok=1 and s.hpo_id is null and f.hpo_id is null and f.fragment <> '__AUCUN__'
                                    group by s.id order by s.id""") if r[0] not in fait]
    if a.limit:
        rows = rows[:a.limit]
    cl = MagosClient(client_id="react-hpo")
    st = Counter()
    print(f"{len(rows)} signes, lots de {LOT}, modèle {MODEL}", flush=True)
    for k in range(0, len(rows), LOT):
        lot = rows[k:k + LOT]
        listes, blocs = [], []
        for i, (rid, signe, verb, livre, titre, frags) in enumerate(lot):
            cands = chercher(signe, *(frags or "").split(" | "))
            listes.append(cands)
            if not cands:
                st["sans candidat"] += 1
            lignes = [f'   {j+1}. "{obo[h]["name"]}" — {(obo[h].get("def") or "")[:110]} [parent: {obo[obo[h]["parents"][0]]["name"] if obo[h].get("parents") and obo[h]["parents"][0] in obo else ""}]'
                      for j, h in enumerate(cands)]
            blocs.append(f'{i}. phrase: "{signe}"\n   book ({livre}, {titre[:40]}): "{(verb or "")[:250]}"\n' + "\n".join(lignes))
        t0 = time.time()
        try:
            rep = cl.submit_and_wait(MODEL, "\n\n".join(blocs), system=SYSTEM, priority=6, timeout_s=900, wait_timeout=1200,
                                     options={"temperature": 0.1, "num_predict": 2500})
            raw = rep.get("response") or ""
            m = re.search(r"\{.*\}", raw, re.S)
            items = json.loads(m.group())["items"] if m else []
        except Exception as e:
            print(f"  lot {k//LOT + 1}: ERREUR {e}", flush=True); st["erreur"] += 1
            continue
        # appariement par la PHRASE recopiee (les index glissaient d'un cran quand le modele
        # sautait un item), l'index en repli
        par_phrase = {O.norm(x.get("phrase") or ""): x for x in items if isinstance(x, dict)}
        par_i = {int(x.get("i", -1)): x for x in items if isinstance(x, dict)}
        for i, (rid, signe, *_r) in enumerate(lot):
            x = par_phrase.get(O.norm(signe)) or par_i.get(i) or {}
            nom, sur = (x.get("nom") or "").strip(), bool(x.get("sur"))
            noms_ok = {obo[h]["name"].lower(): h for h in listes[i]}
            h = noms_ok.get(nom.lower()) if nom else None       # un nom hors liste est refuse
            if not h:
                st["aucun"] += 1
                c.execute("insert into signes_fragments(candidat_id, fragment, hpo_id, modele) values(?,?,?,?)", (rid, nom or "__AUCUN__", None, "react_hpo"))
                continue
            st["sûr" if sur else "pas sûr"] += 1
            c.execute("insert into signes_fragments(candidat_id, fragment, hpo_id, modele) values(?,?,?,?)", (rid, nom, h, "react_hpo" if sur else "react_hpo?"))
            if sur and a.apply:
                c.execute("update syndrome_signes_livres_candidats set hpo_id=?, hpo_portee='REACT', hpo_methode='react_hpo' where id=?", (h, rid))
        c.commit()
        print(f"  lot {k//LOT + 1}/{(len(rows) + LOT - 1)//LOT} : {time.time()-t0:3.0f} s — {dict(st)}", flush=True)
    print(f"\n{len(rows)} signes : {dict(st)}")
    import nomme_signes_hpo
    nomme_signes_hpo.ecrire_tsv(c, obo)


if __name__ == "__main__":
    main()
