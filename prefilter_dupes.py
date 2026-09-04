#!/usr/bin/env python3
"""Pré-filtrage cosinus des termes FOETO redondants (candidats pour arbitrage LLM).

    python prefilter_dupes.py --thr 0.90

Sort dupe_candidates.json + un aperçu console. N'écrit rien dans la DB.
"""
import argparse, json, os, re, sqlite3, unicodedata
import numpy as np


def norm(s):
    """Clé de comparaison : sans accents/casse/ponctuation, pluriels et ordre des mots ignorés."""
    s = unicodedata.normalize("NFKD", (s or "").lower())
    s = "".join(c for c in s if not unicodedata.combining(c))
    toks = re.findall(r"[a-z0-9]+", s)
    toks = [t[:-1] if len(t) > 3 and t.endswith("s") else t for t in toks]
    return " ".join(sorted(t for t in toks if t not in {"de", "du", "des", "la", "le", "l", "d", "a", "en"}))

DB = os.path.join(os.path.dirname(__file__), "syndromes_foetaux.db")
MODEL = "FremyCompany/BioLORD-2023"
CACHE = os.path.join(os.path.dirname(__file__), "foeto_terms_biolord.npz")


def load_terms(conn):
    rows = conn.execute("""
        SELECT t.id, t.organe, t.label_fr, t.label_en, t.axis, t.annotation_type,
               (SELECT COUNT(*) FROM syndrome_foeto s WHERE s.foeto_id = t.id) AS n_synd,
               (SELECT COUNT(*) FROM foeto_hpo h WHERE h.foeto_id = t.id)     AS n_hpo
        FROM foeto_terms t ORDER BY t.id
    """).fetchall()
    return [dict(r) for r in rows]


def embed(terms):
    """Deux espaces séparés : FR et EN. BioLORD est anglophone, comparer un label FR
    à un label EN effondre le cosinus même quand les termes sont identiques."""
    if os.path.exists(CACHE):
        z = np.load(CACHE, allow_pickle=True)
        if list(z["ids"]) == [t["id"] for t in terms]:
            return z["fr"], z["en"], z["has_en"]
    from sentence_transformers import SentenceTransformer
    m = SentenceTransformer(MODEL)
    enc = lambda xs: m.encode(xs, batch_size=64, show_progress_bar=True, normalize_embeddings=True)
    fr = enc([(t["label_fr"] or "").strip() for t in terms])
    has_en = np.array([bool((t["label_en"] or "").strip()) for t in terms])
    en = enc([(t["label_en"] or t["label_fr"] or "").strip() for t in terms])
    np.savez(CACHE, ids=np.array([t["id"] for t in terms]), fr=fr, en=en, has_en=has_en)
    return fr, en, has_en


def _selfcheck():
    assert norm("Agénésie du corps calleux") == norm("Agenesie corps calleux")
    assert norm("Hétérotopie nodulaire périventriculaire") == norm("Hétérotopie périventriculaire nodulaire")
    assert norm("Lymphangiectasie pulmonaire") == norm("Lymphangiectasies pulmonaires")
    assert norm("Microcéphalie") != norm("Microencéphalie")
    print("selfcheck ok")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--thr", type=float, default=0.90)
    ap.add_argument("--cross-organ", action="store_true", help="garder aussi les paires inter-organes")
    ap.add_argument("--top", type=int, default=40)
    args = ap.parse_args()
    _selfcheck()

    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    terms = load_terms(conn)
    fr, en, has_en = embed(terms)
    organ = np.array([t["organe"] for t in terms])

    sim = np.maximum(fr.astype(np.float32) @ fr.astype(np.float32).T,
                     np.where(np.outer(has_en, has_en),
                              en.astype(np.float32) @ en.astype(np.float32).T, -1.0))
    iu = np.triu_indices(len(terms), k=1)
    keep = sim[iu] >= args.thr

    # Canal de rappel indépendant du cosinus : labels identiques après normalisation.
    keys = [norm(t["label_fr"]) for t in terms]
    same = np.array([keys[a] == keys[b] and keys[a] != "" for a, b in zip(*iu)])
    keep |= same

    i, j, s = iu[0][keep], iu[1][keep], sim[iu][keep]
    if not args.cross_organ:
        m = organ[i] == organ[j]
        i, j, s = i[m], j[m], s[m]

    order = np.argsort(-s)
    pairs = []
    for k in order:
        a, b = terms[i[k]], terms[j[k]]
        orth = (norm(a["label_fr"]) == norm(b["label_fr"])
                or (a["label_en"] and b["label_en"] and norm(a["label_en"]) == norm(b["label_en"])))
        pairs.append({
            "cos": round(float(s[k]), 4),
            "same_organ": bool(organ[i[k]] == organ[j[k]]),
            "verdict": "orthographe" if orth else "arbitrage",
            "a": a, "b": b,
        })

    out = os.path.join(os.path.dirname(__file__), "dupe_candidates.json")
    with open(out, "w") as f:
        json.dump(pairs, f, ensure_ascii=False, indent=1)

    # ponytail: on ne clusterise pas, l'arbitrage se fait paire par paire
    hist = {f">={b}": int((s >= b).sum()) for b in (0.99, 0.97, 0.95, 0.93, 0.90)}
    n_orth = sum(p["verdict"] == "orthographe" for p in pairs)
    print(f"{len(terms)} termes | {len(pairs)} paires >= {args.thr} -> {out}")
    print("distribution:", hist)
    print(f"orthographe (fusion sans LLM): {n_orth} | arbitrage LLM: {len(pairs) - n_orth}")
    for v in ("orthographe", "arbitrage"):
        sel = [p for p in pairs if p["verdict"] == v]
        print(f"\n--- {v} ({len(sel)}) — {args.top} premiers ---")
        for p in sel[:args.top]:
            a, b = p["a"], p["b"]
            print(f"{p['cos']:.3f} [{a['organe']}] {a['label_fr']}  ({a['n_synd']}s/{a['n_hpo']}h)"
                  f"\n      ~~  {b['label_fr']}  ({b['n_synd']}s/{b['n_hpo']}h)")


if __name__ == "__main__":
    main()
