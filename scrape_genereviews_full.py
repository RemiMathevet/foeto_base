#!/usr/bin/env python3
"""GeneReviews en ENTIER, chapitre par chapitre, dans genereviews_full.

Pourquoi un second scrape (2026-09-11) : scrape_genereviews.py ne gardait que
trois sections tronquees a 8 000 car. (Suggestive Findings, l'intro de Clinical
Characteristics, Establishing the Diagnosis) — et `find_section` prenait la
premiere cle « clinical characteristics » (l'intro H2) avant « clinical
description » (le H3 qui porte les tables de frequence). Mesure sur les 20 golds
du banc : 7 fiches, 7 pourcentages en tout, 0 pour Cornelia de Lange. Ce n'est
pas GeneReviews qui ne chiffre pas, c'est le scrape qui s'arretait avant.

Ici : toutes les sections (H2 > H3 > H4), texte integral, cellules de table
separees par « | » pour que « Cleft palate | 30 % » reste lisible. La table
genereviews (juin) n'est pas touchee — d'autres scripts la lisent.

Index : genereviews_index.tsv (899 chapitres, page « titles » de NBK1116).
Usage : nohup python3 -u scrape_genereviews_full.py > scrape_gr_full.log 2>&1 &
"""
import json
import os
import re
import sqlite3
import time

import requests

from scrape_genereviews import SectionExtractor, HEADERS

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "syndromes_foetaux.db")
INDEX = os.path.join(os.path.dirname(os.path.abspath(__file__)), "genereviews_index.tsv")
RATE = 0.4
PCT = re.compile(r"\d{1,3}\s?%")


class FullExtractor(SectionExtractor):
    """Comme SectionExtractor, plus : cellules de table separees, chemin de titres."""

    def __init__(self):
        super().__init__()
        self.path = {}            # niveau -> titre, pour nommer « H2 > H3 »
        self.ordered = []         # (chemin, texte) dans l'ordre du document

    def handle_endtag(self, tag):
        if tag in ("td", "th") and not self.skip_depth:
            self.current_text.append(" | ")
        super().handle_endtag(tag)

    def _save_section(self):
        if not self.current_heading:
            return
        lvl = self.heading_level
        self.path = {k: v for k, v in self.path.items() if k < lvl}
        self.path[lvl] = self.current_heading.strip()
        key = " > ".join(self.path[k] for k in sorted(self.path))
        text = re.sub(r"[ \t]*\|[ \t]*\n", "\n", "".join(self.current_text))
        text = re.sub(r"\n{3,}", "\n\n", text).strip()
        if text:
            self.ordered.append((key, text))


def fetch(slug):
    r = requests.get(f"https://www.ncbi.nlm.nih.gov/books/n/gene/{slug}/", headers=HEADERS, timeout=60)
    if r.status_code != 200:
        return None
    ext = FullExtractor()
    ext.feed(r.text)
    ext.finish()
    sections = [{"path": k, "text": t} for k, t in ext.ordered]
    full = "\n\n".join(f"## {k}\n{t}" for k, t in ext.ordered)
    return {"title": ext.title, "sections": sections, "full_text": full,
            "n_pct": len(PCT.findall(full)),
            "omim": sorted(set(ext.omim_ids + re.findall(r"OMIM[:\s#]*(\d{6})", r.text)))[:20],
            "genes": sorted(set(ext.gene_symbols))[:30]}


def main():
    entries = [l.rstrip("\n").split("\t", 1) for l in open(INDEX, encoding="utf-8") if "\t" in l]
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""CREATE TABLE IF NOT EXISTS genereviews_full (
        slug TEXT PRIMARY KEY, title TEXT, omim_ids TEXT, genes TEXT,
        sections_json TEXT, full_text TEXT, n_chars INTEGER, n_pct INTEGER,
        scraped_at TEXT DEFAULT (datetime('now')))""")
    done = {r[0] for r in conn.execute("SELECT slug FROM genereviews_full")}
    todo = [(s, t) for s, t in entries if s not in done]
    print(f"{len(entries)} chapitres, {len(done)} faits, {len(todo)} a faire", flush=True)
    ok = err = 0
    for i, (slug, title) in enumerate(todo, 1):
        try:
            d = fetch(slug)
            if not d:
                print(f"  [{i}/{len(todo)}] {slug:40s} HTTP != 200", flush=True); err += 1
            else:
                conn.execute("INSERT OR REPLACE INTO genereviews_full VALUES (?,?,?,?,?,?,?,?,datetime('now'))",
                             (slug, d["title"] or title, json.dumps(d["omim"]), json.dumps(d["genes"]),
                              json.dumps(d["sections"], ensure_ascii=False), d["full_text"],
                              len(d["full_text"]), d["n_pct"]))
                print(f"  [{i}/{len(todo)}] {slug:40s} {len(d['sections']):3d} sections {len(d['full_text']):7d} car {d['n_pct']:3d} %", flush=True)
                ok += 1
        except Exception as e:
            print(f"  [{i}/{len(todo)}] {slug:40s} ERREUR {e}", flush=True); err += 1
        if i % 20 == 0:
            conn.commit()
        time.sleep(RATE)
    conn.commit()
    n, pct = conn.execute("SELECT count(*), sum(n_pct) FROM genereviews_full").fetchone()
    print(f"\nFini : {ok} ok, {err} erreurs. genereviews_full : {n} chapitres, {pct} pourcentages.", flush=True)


if __name__ == "__main__":
    main()
