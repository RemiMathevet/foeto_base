#!/usr/bin/env python3
"""Seconde chance pour les manques du temoin de Smith (temoin_appendice_smith) :
l'appendice dit qu'une anomalie est un trait du syndrome, la matrice ne la
retrouve pas. Pour chaque entree Smith concernee, le 35B recoit le texte de
l'entree et la liste des anomalies attendues, et doit COPIER la phrase du texte
qui porte chaque anomalie — ou dire qu'elle n'y est pas. Un verbatim introuvable
dans l'entree est rejete. Les trouvailles entrent dans
syndrome_signes_livres_candidats avec niveau='appendice', hpo_id = l'HPO de
l'anomalie (deja resolu par le temoin), hpo_methode='appendice_smith'.

C'est une extraction dirigee : le livre dit ou chercher, le modele copie.

Usage : python3 temoin_reextraction.py [--limit N] [--apply]
"""
import argparse
import json
import re
import sqlite3
import sys
import time
from collections import defaultdict

sys.path.insert(0, "/home/mathevet/Bureau/tmux_supervisor/magos")
import extract_signes_livres as X

MODEL = "Qwen3.6-35B-direct"
SYSTEM = """You are given ONE textbook entry about a syndrome and a list of anomalies that the same textbook's
index says are features of this syndrome. For each anomaly, find the passage of the entry that states it and
COPY it verbatim (5-25 words, exact characters). If the entry does not mention it, return null.
Return ONLY JSON: {"items": [{"anomalie": "<as given>", "verbatim": "<copied text or null>"}, ...]}"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()
    from magos_client import MagosClient
    c = sqlite3.connect(X.DB)
    manques = defaultdict(dict)
    for an, h, t in c.execute("select anomalie, hpo_id, syndrome_titre from temoin_appendice_smith where retrouve=0"):
        manques[t][an] = h
    deja = {(r[0], r[1]) for r in c.execute("select syndrome_titre, signe from syndrome_signes_livres_candidats where niveau='appendice'")}
    corps = {title: (fname, num, body) for fname, num, title, body in X.entries("smith")}
    cl = MagosClient(client_id="temoin-reextraction")
    n = trouve = 0
    for titre, ans in manques.items():
        ans = {an: h for an, h in ans.items() if (titre, an) not in deja}
        if not ans or titre not in corps:
            continue
        if a.limit and n >= a.limit:
            break
        fname, num, body = corps[titre]
        t0 = time.time()
        try:
            r = cl.submit_and_wait(MODEL, f"ENTRY ({titre}):\n\n{body[:20000]}\n\nANOMALIES:\n" + "\n".join(f"- {an}" for an in ans),
                                   system=SYSTEM, priority=6, timeout_s=600, wait_timeout=900,
                                   options={"temperature": 0.1, "num_predict": 4000})
            m = re.search(r"\{.*\}", r.get("response") or "", re.S)
            items = json.loads(m.group())["items"] if m else []
        except Exception as e:
            print(f"  {titre[:50]}: ERREUR {e}", flush=True); continue
        nb = re.sub(r"\s+", " ", body.lower())
        ok = 0
        for it in items:
            an, v = it.get("anomalie"), (it.get("verbatim") or "").strip()
            if an not in ans:
                continue
            vok = 1 if v and re.sub(r"\s+", " ", v.lower())[:60] in nb else 0
            if vok:
                ok += 1
                if a.apply:
                    c.execute("""insert into syndrome_signes_livres_candidats(livre,fichier,entree_num,syndrome_titre,signe,verbatim,verbatim_ok,
                                 niveau,region,modele,hpo_id,hpo_portee,hpo_methode) values(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                              ("smith", fname, num, titre, an, v, 1, "appendice", None, MODEL, ans[an], "APPENDICE", "appendice_smith"))
            elif a.apply:
                c.execute("""insert into syndrome_signes_livres_candidats(livre,fichier,entree_num,syndrome_titre,signe,verbatim,verbatim_ok,niveau,modele)
                             values(?,?,?,?,?,?,?,?,?)""", ("smith", fname, num, titre, an, v, 0, "appendice", MODEL))
        c.commit(); n += 1; trouve += ok
        print(f"  {titre[:52]:52s} {ok:2d}/{len(ans):2d} verbatims, {time.time()-t0:3.0f} s", flush=True)
    print(f"\n{n} entrées relues, {trouve} attestations retrouvées")


if __name__ == "__main__":
    main()
