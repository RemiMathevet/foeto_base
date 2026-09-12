#!/usr/bin/env python3
"""Signes de livres restes sans hpo_id apres toutes les regles. Sondage (2026-09-12) :
ce ne sont PAS des phrases longues mais des paraphrases atomiques (« Refractive
error », « Acquired cataracts », « Speckling of iris (Brushfield spots) ») — le
decoupage n'y peut rien (1/40).

Le 35B propose donc pour chaque libelle le NOM OFFICIEL du terme HPO qui lui
correspond (pas un identifiant) ; l'identifiant vient ensuite de l'index hp.obo
par egalite exacte (NAME/EXACT/NARROW). Un nom invente ne se resout pas et la
ligne reste vide ; un nom resolu est marque hpo_methode='llm_nom' et va dans
arbitrage_llm_nom.tsv pour relecture — le risque restant est semantique
(terme plausible mais voisin), pas un identifiant halluciné.

Usage : python3 nomme_signes_hpo.py [--limit N] [--apply]
"""
import argparse
import json
import re
import sqlite3
import sys
import time
from collections import Counter

sys.path.insert(0, "/home/mathevet/Bureau/tmux_supervisor/magos")
import map_signes_hpo_obo as O
import map_signes_hpo_regles as R

MODEL = "Qwen3.6-35B-direct"
LOT = 40
SYSTEM = """For each clinical sign phrase from a dysmorphology textbook, give the OFFICIAL name of the
Human Phenotype Ontology (HPO) term that means the same thing, exactly as HPO spells it
(e.g. "Refractive error" -> "Abnormality of refraction"; "Acquired cataracts" -> "Cataract";
"Speckling of iris (Brushfield spots)" -> "Brushfield spots"; "Hypoplasia of midphalanx of fifth finger" ->
"Hypoplasia of the middle phalanx of the 5th finger"). If the phrase holds two signs, give both names.
If no HPO term matches (behaviour, treatment, vague wording), return an empty list. Never invent a name.
Return ONLY JSON: {"items": [{"i": <index>, "hpo": ["<HPO term name>", ...]}, ...]}"""


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

    def lookup(s):
        n = O.norm(s)
        hit = idx.get(n) or idx.get(O.norm(O.QUALIF.sub(" ", n))) or idx_tok.get(O.toks(s))
        if not hit:
            q = O.norm(R.TETE.sub("", R.TETE.sub("", s)))
            hit = idx.get(q) or idx_tok.get(O.toks(q))
        return hit[0] if hit and hit[1] != "RELATED" else None

    c.execute("""create table if not exists signes_fragments (candidat_id integer, fragment text, hpo_id text,
                 modele text, cree_le text default (datetime('now')))""")
    fait = {r[0] for r in c.execute("select distinct candidat_id from signes_fragments")}
    rows = [r for r in c.execute("""select id, signe from syndrome_signes_livres_candidats
                                    where verbatim_ok=1 and hpo_id is null and (hpo_methode is null or hpo_methode='')
                                    order by id""") if r[0] not in fait]
    if a.limit:
        rows = rows[:a.limit]
    cl = MagosClient(client_id="scinde-signes")
    st = Counter()
    for k in range(0, len(rows), LOT):
        lot = rows[k:k + LOT]
        prompt = "\n".join(f"{i}. {s}" for i, (_, s) in enumerate(lot))
        t0 = time.time()
        try:
            r = cl.submit_and_wait(MODEL, prompt, system=SYSTEM, priority=6, timeout_s=600, wait_timeout=900,
                                   options={"temperature": 0.1, "num_predict": 6000})
            m = re.search(r"\{.*\}", r.get("response") or "", re.S)
            items = json.loads(m.group())["items"] if m else []
        except Exception as e:
            print(f"  lot {k//LOT}: ERREUR {e}", flush=True); st["erreur"] += 1
            continue
        par_i = {int(x.get("i", -1)): x.get("hpo") or [] for x in items if isinstance(x, dict)}
        for i, (rid, s) in enumerate(lot):
            noms = [f.strip() for f in par_i.get(i, []) if isinstance(f, str) and f.strip()][:2]
            st["noms_proposes"] += len(noms)
            hids = []
            for f in noms:
                n = O.norm(f)
                hit = idx.get(n)                       # egalite exacte seulement : le nom, pas l'id
                h = hit[0] if hit and hit[1] in ("NAME", "EXACT", "NARROW") else None
                st["noms_resolus"] += bool(h)
                c.execute("insert into signes_fragments(candidat_id, fragment, hpo_id, modele) values(?,?,?,?)", (rid, f, h, MODEL))
                if h and h not in hids:
                    hids.append(h)
            if not noms:
                c.execute("insert into signes_fragments(candidat_id, fragment, hpo_id, modele) values(?,?,?,?)", (rid, "__AUCUN__", None, MODEL))
            if hids:
                st["signes_codes"] += 1
                if a.apply:
                    c.execute("update syndrome_signes_livres_candidats set hpo_id=?, hpo_portee='LLM_NOM', hpo_methode='llm_nom' where id=?",
                              ("+".join(hids), rid))
            else:
                st["signes_sans_code"] += 1
        c.commit()
        print(f"  lot {k//LOT + 1}/{(len(rows) + LOT - 1)//LOT} : {len(lot)} signes, {time.time()-t0:3.0f} s — codés cumulés {st['signes_codes']}", flush=True)
    print(f"\n{len(rows)} signes repris : {dict(st)}")
    # relecture : un libelle -> les noms resolus (le risque est semantique)
    with open("/home/mathevet/Bureau/foeto_base/arbitrage_llm_nom.tsv", "w", encoding="utf-8") as f:
        f.write("signe\tnom_propose\thpo_id\tlabel_hpo\tn\tchoix\n")
        for sg, fr, h, n in c.execute("""select c.signe, f.fragment, f.hpo_id, count(*) from signes_fragments f
                                        join syndrome_signes_livres_candidats c on c.id=f.candidat_id
                                        where f.hpo_id is not null group by lower(c.signe), f.hpo_id order by count(*) desc"""):
            f.write(f"{sg}\t{fr}\t{h}\t{obo.get(h, {}).get('name', '')}\t{n}\t\n")


if __name__ == "__main__":
    main()
