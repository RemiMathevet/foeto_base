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


def entries(livre):
    for f in sorted((CHAP / livre).glob("ch*.txt")):
        lines = f.read_text(encoding="utf-8").split("\n", 4)
        num, title, body = lines[0].strip(), lines[2].strip(), lines[4] if len(lines) > 4 else ""
        if livre == "smith" and not re.match(r"^[A-W] ", title):
            continue                              # intro, ch. 2-5, appendice : pas des syndromes
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
    ap.add_argument("--livre", choices=["smith", "spranger", "all"], default="all")
    ap.add_argument("--limit", type=int, default=0)
    a = ap.parse_args()
    c = sqlite3.connect(DB)
    c.execute("""CREATE TABLE IF NOT EXISTS syndrome_signes_livres_candidats (
        id INTEGER PRIMARY KEY, livre TEXT, fichier TEXT, entree_num INTEGER, syndrome_titre TEXT,
        syndrome_llm TEXT, signe TEXT, verbatim TEXT, verbatim_ok INTEGER, frequence TEXT,
        niveau TEXT, region TEXT, modele TEXT, extrait_le TEXT DEFAULT (datetime('now')))""")
    done = {(r[0], r[1]) for r in c.execute("select livre, fichier from syndrome_signes_livres_candidats")}
    cl = MagosClient(client_id="extract-signes-livres")
    livres = ["smith", "spranger"] if a.livre == "all" else [a.livre]
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
                             v, vok, s.get("frequence"), s.get("niveau"), s.get("region"), MODEL))
            if not rows:
                rows = [(livre, fname, num, title, d.get("syndrome"), "__VIDE__", "", 0, None, None, None, MODEL)]
            c.executemany("insert into syndrome_signes_livres_candidats(livre,fichier,entree_num,syndrome_titre,syndrome_llm,signe,verbatim,verbatim_ok,frequence,niveau,region,modele) values(?,?,?,?,?,?,?,?,?,?,?,?)", rows)
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
