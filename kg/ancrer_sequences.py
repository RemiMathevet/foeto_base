#!/usr/bin/env python3
"""Ancre chaque arête « entraine » de sequences_canoniques.py sur des phrases de livres (rag_v2.db), sans LLM.

Pour une arête cause -> effet : phrases des chunks de livres anglophones où le motif de la cause ET celui de
l'effet apparaissent ; à défaut, deux phrases consécutives (marquées « fenêtre »). Classement : indice causal
présent (results in, leads to, secondary to, due to, causes…), puis phrase courte. Le verbatim est une copie
exacte du chunk (contrôlé), avec livre, chapitre, page imprimée (chunk_pages).

Sortie : TSV d'arbitrage (3 meilleures phrases par arête, colonne decision vide pour Rémi : OUI / NON / INVERSE),
hors dépôt (verbatims de livres) : kg/sorties/arbitrage_entraine.tsv

    python kg/ancrer_sequences.py
"""
import re
import sqlite3
import sys
from pathlib import Path

import pysbd

ICI = Path(__file__).resolve().parent
sys.path.insert(0, str(ICI))
import sequences_canoniques as sc  # noqa: E402

RAG = Path.home() / "Bureau/Embedding_RAG_V2/rag_v2.db"
OUT = ICI / "sorties" / "arbitrage_entraine.tsv"
CAUSAL = re.compile(r"\b(result(s|ed|ing)? in|lead(s|ing)? to|led to|caus(e|es|ed|ing)|secondary to|due to|"
                    r"consequen\w*|because of|owing to|attribut\w* to|produc(es|ed|ing)|responsible for|"
                    r"sequence|accounts? for|giv(es|ing) rise to|follow(s|ing) from)\b", re.I)
PAR_ARETE = 3


def main():
    sc._check()
    con = sqlite3.connect(f"file:{RAG}?mode=ro", uri=True)
    rows = con.execute("SELECT c.rowid, c.source_short, c.chapter_title, c.chunk_text, p.page_label, p.page_pdf "
                       "FROM chunk_meta c LEFT JOIN chunk_pages p USING(rowid) "
                       "WHERE c.source_type='book' AND c.language='en'").fetchall()
    seg = pysbd.Segmenter(language="en", clean=False)
    motif = {k: re.compile(m, re.I) for k, (_, m) in sc.NOEUDS.items()}
    phrases_cache = {}
    lignes, resume = [], []
    for seq, a, b, cert in sc.ARETES:
        ma, mb = motif[a], motif[b]
        cand = []
        for rid, livre, chap, txt, pl, pp in rows:
            if not (ma.search(txt) and mb.search(txt)):
                continue
            # texte recollé (césures de fin de ligne, retours à la ligne du PDF) : la phrase n'est plus coupée ;
            # le verbatim est contrôlé contre ce texte recollé, pas contre le chunk brut
            txt = " ".join(re.sub(r"-\n(?=[a-z])", "", txt).split())
            ph = phrases_cache.get(rid) or phrases_cache.setdefault(rid, seg.segment(txt))
            for i, s in enumerate(ph):
                if ma.search(s) and mb.search(s):
                    cand.append((s, "phrase", livre, chap, pl, pp, txt))
                elif i + 1 < len(ph) and ((ma.search(s) and mb.search(ph[i + 1])) or (mb.search(s) and ma.search(ph[i + 1]))):
                    cand.append((s + ph[i + 1], "fenêtre", livre, chap, pl, pp, txt))
        vus, garde = set(), []
        for s, gr, livre, chap, pl, pp, txt in sorted(cand, key=lambda c: (c[1] != "phrase", not CAUSAL.search(c[0]), len(c[0]))):
            cle = re.sub(r"\W", "", s.lower())[:80]
            if cle in vus or len(s) > 900:
                continue
            vus.add(cle)
            assert s.strip() in " ".join(re.sub(r"-\n(?=[a-z])", "", txt).split()), "verbatim non retrouvé"
            garde.append((s, gr, livre, chap, pl, pp))
            if len(garde) == PAR_ARETE:
                break
        resume.append((seq, a, b, len(cand), sum(1 for g in garde if CAUSAL.search(g[0]))))
        if not garde:
            lignes.append((seq, sc.NOEUDS[a][0], "→", sc.NOEUDS[b][0], cert, "", "", "", "", "AUCUNE PHRASE", "", ""))
        for s, gr, livre, chap, pl, pp in garde:
            v = " ".join(s.split())
            lignes.append((seq, sc.NOEUDS[a][0], "→", sc.NOEUDS[b][0], cert, livre, chap or "",
                           pl or f"pdf {pp}" if pp else "", gr, v, "oui" if CAUSAL.search(s) else "", ""))
    OUT.parent.mkdir(exist_ok=True)
    tete = ("sequence", "cause", "", "effet", "certitude", "livre", "chapitre", "page", "grain", "verbatim",
            "indice_causal", "decision")
    OUT.write_text("\n".join("\t".join(map(str, l)) for l in [tete] + lignes) + "\n")
    sans = [r for r in resume if r[3] == 0]
    causal = sum(1 for r in resume if r[4] > 0)
    print(f"{len(sc.ARETES)} arêtes : {len(sc.ARETES) - len(sans)} avec au moins une phrase de livre, "
          f"{causal} avec indice causal, {len(sans)} sans aucune -> {OUT}")
    for r in sans:
        print("  sans phrase :", r[0], "|", sc.NOEUDS[r[1]][0], "→", sc.NOEUDS[r[2]][0])


if __name__ == "__main__":
    main()
