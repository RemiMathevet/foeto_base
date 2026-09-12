#!/usr/bin/env python3
"""Discriminateurs de Smith -> syndrome_diff_livres (livre='smith').

Spranger structure son differentiel (un paragraphe par syndrome, decoupage
sans LLM : build_diff_livres.py). Smith le met dans COMMENT, en prose :
« ...should be distinguished from X, which has... ». Il faut un modele pour
isoler chaque paire (syndrome a distinguer, critere), avec la meme discipline
que pour les signes : le verbatim est copie, pas paraphrase, et une ligne dont
le verbatim ne se retrouve pas dans le texte est rejetee.

167 entrees Smith ont un COMMENT. Qwen3.6-35B-direct via MAGOS, T=0,2.

Usage : python3 extract_diff_smith.py [--limit N]
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
SMITH = Path("/home/mathevet/Bureau/Embedding_RAG_V2/chapitres/smith")
MODEL = "Qwen3.6-35B-direct"
SEC = re.compile(r"^(ABNORMALITIES|OCCASIONAL ABNORMALITIES|NATURAL HISTORY|ETIOLOGY|COMMENT|References)\s*$", re.M)

SYSTEM = """You extract DIFFERENTIAL DIAGNOSES from the COMMENT section of a dysmorphology textbook entry about ONE syndrome.
Return ONLY a JSON object, no prose:
{"differentiels": [{"syndrome": "<the OTHER syndrome the text distinguishes from, as named in the text>",
                    "verbatim": "<the exact sentence(s) stating how they differ, copied verbatim, 8-60 words>"}]}
Rules: one entry per syndrome mentioned as a differential or look-alike. Copy, never paraphrase.
If the comment names no other syndrome, return {"differentiels": []}."""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0)
    a = ap.parse_args()
    c = sqlite3.connect(DB)
    c.execute("""CREATE TABLE IF NOT EXISTS syndrome_diff_livres (
        id INTEGER PRIMARY KEY, livre TEXT NOT NULL, entree TEXT NOT NULL, syndrome_titre TEXT NOT NULL,
        diff_nom TEXT, diff_syndrome_id TEXT REFERENCES syndromes(id), verbatim TEXT NOT NULL,
        cree_le TEXT NOT NULL DEFAULT (datetime('now')))""")
    done = {r[0] for r in c.execute("select distinct entree from syndrome_diff_livres where livre='smith'")}
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from build_syndrome_hpo_livres import index_syndromes, norm, variantes
    idx = index_syndromes(c)
    cl = MagosClient(client_id="extract-diff-smith")
    n = tot = ok_tot = 0
    for f in sorted(SMITH.glob("ch*.txt")):
        lignes = f.read_text(encoding="utf-8").split("\n", 4)
        titre = lignes[2].strip()
        if not re.match(r"^[A-W] ", titre) or f.name in done:
            continue
        parts = SEC.split(lignes[4] if len(lignes) > 4 else "")
        secs = {parts[i]: parts[i + 1].strip() for i in range(1, len(parts) - 1, 2)}
        comment = secs.get("COMMENT", "")
        if len(comment) < 60:
            continue
        if a.limit and n >= a.limit:
            break
        n += 1
        t0 = time.time()
        try:
            r = cl.submit_and_wait(MODEL, f"ENTRY: {titre}\n\nCOMMENT:\n{comment[:12000]}",
                                   system=SYSTEM, priority=6, timeout_s=600, wait_timeout=900,
                                   options={"temperature": 0.2, "num_predict": 4000})
            m = re.search(r"\{.*\}", r.get("response") or "", re.S)
            d = json.loads(m.group()) if m else {}
        except Exception as e:
            print(f"  {f.name[:50]}: ERREUR {e}", flush=True)
            continue
        norm_c = re.sub(r"\s+", " ", comment.lower())
        rows, ok = [], 0
        for x in d.get("differentiels", []) or []:
            v = (x.get("verbatim") or "").strip()
            if v and re.sub(r"\s+", " ", v.lower())[:50] in norm_c:
                nom = (x.get("syndrome") or "").strip()
                sid = None
                for var in variantes(nom):
                    sid = idx.get(norm(var))
                    if sid:
                        break
                rows.append(("smith", f.name, titre, nom, sid, v))
                ok += 1
        c.executemany("insert into syndrome_diff_livres (livre, entree, syndrome_titre, diff_nom, diff_syndrome_id, verbatim) values (?,?,?,?,?,?)", rows)
        c.commit()
        tot += len(d.get("differentiels", []) or []); ok_tot += ok
        print(f"  {titre[:48]:48s} {ok:2d}/{len(d.get('differentiels', []) or []):2d} verbatim ok  {time.time()-t0:3.0f} s", flush=True)
    print(f"\n{n} entrées, {ok_tot}/{tot} différentiels retenus (verbatim vérifié).", flush=True)


if __name__ == "__main__":
    main()
