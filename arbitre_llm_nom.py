#!/usr/bin/env python3
"""Premier arbitrage des mappings llm_nom / llm_nom_tok par un modele plus gros que
celui qui les a proposes, puis un second avis externe sur ce dont il n'est pas sur.

Doctrine inchangee : le modele ne rend jamais un identifiant. Il juge un couple
(signe du livre, terme HPO propose) avec la definition HPO, les parents et un
verbatim du livre sous les yeux, et repond OK / PARENT (le terme est plus precis
que le livre : on pose son parent) / AUTRE <nom officiel> (resolu par l'index,
sinon « pas sur ») / NON (non codable), avec « sur » vrai ou faux.
  --etape next        Qwen3.8-Flash-Next via MAGOS (177B totaux, lent, batch) ;
                      les verdicts surs vont dans la colonne choix du TSV, les
                      autres dans arbitrage_openrouter.tsv
  --etape openrouter  les « pas sur » a un LLM externe (avis.py : gemini, claude,
                      gpt...) ; ce qui reste « pas sur » reste pour Remi
Lots de 20, JSON, reprise sur le TSV (une ligne deja choisie n'est pas rejouee).

Usage : python3 arbitre_llm_nom.py --etape next [--limit N]
        python3 arbitre_llm_nom.py --etape openrouter [--modele claude]
"""
import argparse
import csv
import json
import os
import re
import sqlite3
import sys
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, "/home/mathevet/Bureau/tmux_supervisor/magos")
sys.path.insert(0, "/home/mathevet/Bureau")
import map_signes_hpo_obo as O
import map_signes_hpo_regles as R

TSV = Path("/home/mathevet/Bureau/foeto_base/arbitrage_llm_nom.tsv")
TSV_OR = Path("/home/mathevet/Bureau/foeto_base/arbitrage_openrouter.tsv")
MODEL_NEXT = "Qwen3.8-Flash-Next-direct"      # sans raisonnement : 8000 tokens de thinking rendaient une reponse vide
LOT = 20
AUTRES = {}          # signe -> ses lignes du TSV (une phrase peut porter deux termes)
SYSTEM = """You audit mappings from clinical sign phrases (dysmorphology / fetal pathology textbooks) to
Human Phenotype Ontology (HPO) terms. For each item you get the book phrase, a verbatim sentence from the
book, the proposed HPO term with its definition and parent terms. Decide:
  "OK"     the HPO term means the same thing as the phrase (same concept, same specificity);
  "PARENT" the HPO term is MORE specific than the phrase (the book says less) — the parent term should be used;
  "AUTRE"  a different HPO term fits better: give its OFFICIAL HPO name in "nom" (never an HP: id);
  "NON"    the phrase is not codable in HPO (behaviour, treatment, vague, a disease name, a normal finding).
"sur" is true only when you are confident; false when a specialist should look. Judge as a fetal pathologist.
Return ONLY JSON: {"items": [{"i": <index>, "verdict": "OK|PARENT|AUTRE|NON", "nom": "<HPO name or empty>", "sur": true|false}, ...]}"""


def lire(p, col):
    rows = list(csv.DictReader(open(p, encoding="utf-8"), delimiter="\t")) if p.exists() else []
    return rows, (list(rows[0].keys()) if rows else col)


def ecrire(p, rows, cols):
    w = csv.DictWriter(open(p, "w", encoding="utf-8"), fieldnames=cols, delimiter="\t", lineterminator="\n", extrasaction="ignore")
    w.writeheader(); w.writerows(rows)


def contexte(c, obo, r):
    """le dossier d'un couple : verbatim du livre, definition et parents HPO"""
    t = obo.get(r["hpo_id"], {})
    v = c.execute("""select verbatim, livre, syndrome_titre from syndrome_signes_livres_candidats
                     where lower(signe)=? and verbatim_ok=1 and verbatim <> '' limit 1""", (r["signe"].lower(),)).fetchone()
    parents = "; ".join(obo[p]["name"] for p in t.get("parents", []) if p in obo)
    autres = [x["label_hpo"] for x in AUTRES.get(r["signe"].lower(), []) if x["hpo_id"] != r["hpo_id"]]
    return (f'phrase: "{r["signe"]}"\n'
            + (f'  (this phrase is ALSO mapped to: {"; ".join(autres)} — judge only the proposed term below, a phrase holding two signs is split, not PARENT)\n' if autres else "")
            + (f'  book ({v[1]}, {v[2][:40]}): "{v[0][:300]}"\n' if v else "")
            + f'  proposed HPO: "{r["label_hpo"]}" — def: {(t.get("def") or "")[:300]}\n'
            + f'  parents: {parents}')


def parse(raw):
    m = re.search(r"\{.*\}", raw or "", re.S)
    try:
        return json.loads(m.group())["items"] if m else []
    except (json.JSONDecodeError, KeyError, TypeError):
        out = []
        for o in re.findall(r"\{[^{}]*\}", raw or ""):
            try:
                d = json.loads(o)
                if "i" in d:
                    out.append(d)
            except json.JSONDecodeError:
                pass
        return out


def appliquer(items, lot, lookup, obo, sur_seulement=True):
    """-> {index: (choix|None, sur, verdict, nom)} ; choix None = pas tranche"""
    res = {}
    par_i = {int(x.get("i", -1)): x for x in items if isinstance(x, dict)}
    for i, r in enumerate(lot):
        x = par_i.get(i)
        if not x:
            continue
        v, nom, sur = (x.get("verdict") or "").upper(), (x.get("nom") or "").strip(), bool(x.get("sur"))
        choix = None
        if v == "OK":
            choix = r["hpo_id"]
        elif v == "NON":
            choix = "NON"
        elif v == "PARENT":
            # PARENT:<id> = ce noeud pose en parapluie (est_parent=1) : on veut le PARENT
            # du terme propose — celui que nomme le modele s'il se resout, sinon le premier
            # parent declare par hp.obo
            h = lookup(nom) if nom else None
            choix = "PARENT:" + (h or (obo.get(r["hpo_id"], {}).get("parents") or [r["hpo_id"]])[0])
        elif v == "AUTRE" and nom:
            h = lookup(nom)
            if h:
                choix = h
            else:
                sur = False                     # un nom que l'index ne connait pas : on ne pose rien
        res[i] = (choix if (sur or not sur_seulement) else None, sur, v, nom)
    return res


def appel_openrouter(model, prompt):
    key = os.environ.get("OPENROUTER_API_KEY")
    if not key:
        sys.exit("OPENROUTER_API_KEY manquant")
    payload = json.dumps({"model": model, "temperature": 0.1,
                          "messages": [{"role": "system", "content": SYSTEM}, {"role": "user", "content": prompt}]}).encode()
    req = urllib.request.Request("https://openrouter.ai/api/v1/chat/completions", data=payload,
                                 headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=300) as r:
        return json.load(r)["choices"][0]["message"]["content"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--etape", choices=["next", "openrouter"], required=True)
    ap.add_argument("--modele", default="claude", help="openrouter : alias d'avis.py ou id complet")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--tous", action="store_true", help="next : toutes les lignes sans choix, pas seulement les prioritaires (tok ou n>=3)")
    a = ap.parse_args()
    c = sqlite3.connect(O.DB)
    obo = O.load_obo(O.OBO)
    ours = {r[0]: (r[1], r[2]) for r in c.execute("select hpo_id, label_en, aliases_fr from hpo_terms")}
    idx, idx_tok = R.index(obo, ours)

    def lookup(s):
        hit = idx.get(O.norm(s)) or idx_tok.get(O.toks(s))
        return hit[0] if hit and hit[1] in ("NAME", "EXACT") else None

    rows, cols = lire(TSV, ["signe", "nom_propose", "hpo_id", "label_hpo", "n", "choix"])
    for r in rows:
        AUTRES.setdefault(r["signe"].lower(), []).append(r)
    if "arbitre" not in cols:
        cols.append("arbitre")
    tok = {sg for sg, in c.execute("select distinct lower(signe) from syndrome_signes_livres_candidats where hpo_methode='llm_nom_tok'")}
    for r in rows:
        r.setdefault("arbitre", "")

    if a.etape == "next":
        from magos_client import MagosClient
        cl = MagosClient(client_id="arbitre-llm-nom")
        todo = [r for r in rows if not r["choix"] and not r["arbitre"] and (a.tous or r["signe"].lower() in tok or int(r["n"]) >= 3)]
        todo.sort(key=lambda r: (r["signe"].lower() not in tok, -int(r["n"])))
        if a.limit:
            todo = todo[:a.limit]
        or_rows, or_cols = lire(TSV_OR, cols + ["verdict_next", "nom_next"])
        deja_or = {(r["signe"].lower(), r["hpo_id"]) for r in or_rows}
        print(f"{len(todo)} couples à arbitrer par {MODEL_NEXT}", flush=True)
        k_sur = k_pas = 0
        for k in range(0, len(todo), LOT):
            lot = todo[k:k + LOT]
            prompt = "\n\n".join(f"{i}. " + contexte(c, obo, r) for i, r in enumerate(lot))
            t0 = time.time()
            try:
                rep = cl.submit_and_wait(MODEL_NEXT, prompt, system=SYSTEM, priority=6, timeout_s=1800, wait_timeout=2400,
                                         options={"temperature": 0.1, "num_predict": 3000})
                items = parse(rep.get("response") or "")
            except Exception as e:
                print(f"  lot {k//LOT + 1}: ERREUR {e}", flush=True)
                continue
            res = appliquer(items, lot, lookup, obo)
            for i, r in enumerate(lot):
                if i not in res:
                    continue
                choix, sur, v, nom = res[i]
                r["arbitre"] = f"next:{v}" + (f" {nom}" if nom else "") + ("" if sur else " ?")
                if choix:
                    r["choix"] = choix; k_sur += 1
                elif (r["signe"].lower(), r["hpo_id"]) not in deja_or:
                    or_rows.append(r | {"verdict_next": v, "nom_next": nom}); k_pas += 1
            ecrire(TSV, rows, cols)
            ecrire(TSV_OR, or_rows, cols + ["verdict_next", "nom_next"])
            print(f"  lot {k//LOT + 1}/{(len(todo) + LOT - 1)//LOT} : {len(res)}/{len(lot)} jugés, {time.time()-t0:3.0f} s — sûrs {k_sur}, pas sûrs {k_pas}", flush=True)
        print(f"fin : {k_sur} choix posés, {k_pas} pour OpenRouter -> {TSV_OR}")

    else:
        sys.path.insert(0, "/home/mathevet/Bureau")
        import avis
        key = os.environ.get("OPENROUTER_API_KEY")
        model = avis.resolve_latest(avis.FAMILIES[a.modele], avis.fetch_models(key)) if a.modele in avis.FAMILIES else a.modele
        or_rows, or_cols = lire(TSV_OR, cols + ["verdict_next", "nom_next"])
        if "arbitre_ext" not in or_cols:
            or_cols.append("arbitre_ext")
        par_cle = {(r["signe"].lower(), r["hpo_id"]): r for r in rows}
        todo = [r for r in or_rows if not r["choix"] and not r.get("arbitre_ext")]
        if a.limit:
            todo = todo[:a.limit]
        print(f"{len(todo)} couples pour {model}", flush=True)
        k_sur = 0
        for k in range(0, len(todo), LOT):
            lot = todo[k:k + LOT]
            prompt = "\n\n".join(f"{i}. " + contexte(c, obo, r) + f'\n  a first model said: {r.get("verdict_next", "")} {r.get("nom_next", "")}' for i, r in enumerate(lot))
            try:
                items = parse(appel_openrouter(model, prompt))
            except Exception as e:
                print(f"  lot {k//LOT + 1}: ERREUR {e}", flush=True)
                continue
            res = appliquer(items, lot, lookup, obo)
            for i, r in enumerate(lot):
                if i not in res:
                    continue
                choix, sur, v, nom = res[i]
                r["arbitre_ext"] = f"{a.modele}:{v}" + (f" {nom}" if nom else "") + ("" if sur else " ?")
                if choix:
                    r["choix"] = choix; k_sur += 1
                    src = par_cle.get((r["signe"].lower(), r["hpo_id"]))
                    if src is not None:
                        src["choix"] = choix; src["arbitre"] = (src.get("arbitre") or "") + f" | {r['arbitre_ext']}"
            ecrire(TSV_OR, or_rows, or_cols)
            ecrire(TSV, rows, cols)
            print(f"  lot {k//LOT + 1}/{(len(todo) + LOT - 1)//LOT} — sûrs cumulés {k_sur}", flush=True)
        reste = sum(1 for r in or_rows if not r["choix"])
        print(f"fin : {k_sur} choix posés par {model} ; {reste} restent pour Rémi dans {TSV_OR}")


if __name__ == "__main__":
    main()
