#!/usr/bin/env python3
"""Combien de termes foeto_terms remontent a la MEME phrase de livre ?

Deux lectures complementaires, aucune ecriture en base :
  - lexicale  : le terme est apparie a la phrase du chapitre qui couvre le mieux son label_en.
                Precise, mais aveugle aux reformulations (« Glomerulomegaly » ne matche pas
                « glomerular enlargement »). C'est un PLANCHER.
  - BioLORD   : paires de termes proches en cosinus DANS LE MEME CHAPITRE source.
                Rattrape les reformulations, au prix de faux positifs.
"""
import re, sqlite3, sys, unicodedata
from collections import defaultdict
from pathlib import Path

import numpy as np

DB = Path.home() / "Bureau/foeto_base/syndromes_foetaux.db"
NPZ = Path.home() / "Bureau/foeto_base/foeto_terms_biolord.npz"
STOP = {"of", "the", "in", "and", "with", "a", "to", "or", "on", "at", "by", "for"}
COS_MIN = 0.90


def mots(s):
    """Mots de contenu, tronques a 6 car. pour absorber pluriels et formes adjectivales."""
    s = unicodedata.normalize("NFKD", s.lower())
    s = "".join(c for c in s if not unicodedata.combining(c))
    return {w[:6] for w in re.findall(r"[a-z]+", s) if w not in STOP and len(w) > 2}


def phrases(txt):
    """Decoupe grossiere. Le texte PDF est en colonnes : on ne cherche qu'une cle de localite."""
    out = []
    for p in re.split(r"(?<=[.;])\s+", txt):
        if out and len(p) < 40:
            out[-1] += " " + p
        else:
            out.append(p)
    return [p for p in out if len(p) > 40]


def main():
    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    termes = con.execute(
        "SELECT id, organe, label_fr, COALESCE(NULLIF(label_en,''),label_fr), sources "
        "FROM foeto_terms WHERE axis='pathologie' AND sources IS NOT NULL AND sources<>''"
    ).fetchall()
    print(f"{len(termes)} termes pathologie sources", file=sys.stderr)

    # un terme peut declarer plusieurs chapitres : on l'essaie dans chacun
    par_chap = defaultdict(list)
    for t in termes:
        for src in t[4].split("|"):
            par_chap[src.strip()].append(t)

    cluster = defaultdict(list)   # (chapitre, i_phrase) -> [termes]
    apparie = {}
    chap_vus = 0
    for chap, ts in sorted(par_chap.items()):
        rows = con.execute(
            "SELECT chunk_text FROM chunk_meta WHERE source_id=? ORDER BY chunk_index", (chap,)
        ).fetchall()
        if not rows:
            continue
        chap_vus += 1
        ph = phrases(" ".join(r[0] for r in rows))
        sacs = [mots(p) for p in ph]
        for t in ts:
            # chapitres FR (soffoet) et EN melanges : on essaie les deux libelles
            best, bi, seuil = 0.0, -1, 1.0
            for lab in (t[3], t[2]):
                m = mots(lab)
                if not m:
                    continue
                for i, s in enumerate(sacs):
                    cov = len(m & s) / len(m)
                    if cov > best:
                        best, bi, seuil = cov, i, (1.0 if len(m) == 1 else 0.75)
            if best >= seuil:
                cluster[(chap, bi)].append(t)
                apparie[t[0]] = (chap, bi, ph[bi])

    multi = {k: v for k, v in cluster.items() if len(v) > 1}
    dans_multi = sum(len(v) for v in multi.values())
    print(f"\n=== APPARIEMENT LEXICAL (plancher) ===")
    print(f"chapitres avec chunks en base : {chap_vus}/{len(par_chap)}")
    print(f"termes apparies a une phrase  : {len(apparie)}/{len(termes)}")
    print(f"phrases portant >1 terme      : {len(multi)}")
    print(f"termes concernes              : {dans_multi}")
    print(f"reduction si on factorise     : {dans_multi} -> {len(multi)} "
          f"(soit -{dans_multi - len(multi)} termes)")

    # les tableaux et listes d'abreviations attirent les libelles : on les compte a part
    est_table = lambda p: bool(re.search(
        r"\bTable \d|Abbreviations|Synonyms|Inheritance pattern|\bGene\b.*\bChromosome\b", p))
    tsv = Path("/tmp/doublons_phrase.tsv")
    n_tab = n_prose = t_tab = t_prose = 0
    with tsv.open("w") as f:
        f.write("chapitre\tn_termes\tnature\tphrase\ttermes\n")
        for (chap, i), ts in sorted(multi.items(), key=lambda x: -len(x[1])):
            p = apparie[ts[0][0]][2]
            nat = "table" if est_table(p) else "prose"
            if nat == "table":
                n_tab += 1; t_tab += len(ts)
            else:
                n_prose += 1; t_prose += len(ts)
            f.write(f"{chap}\t{len(ts)}\t{nat}\t{p[:400].replace(chr(9),' ')}\t"
                    + " || ".join(t[2] for t in ts) + "\n")
    print(f"\n  dont tableaux/listes : {n_tab} paquets, {t_tab} termes  (bruit)")
    print(f"  dont prose           : {n_prose} paquets, {t_prose} termes")
    print(f"  detail : {tsv}")

    print(f"\n--- 12 plus gros paquets ---")
    for (chap, i), ts in sorted(multi.items(), key=lambda x: -len(x[1]))[:12]:
        print(f"\n[{len(ts)} termes] {chap}")
        print(f"  phrase : {apparie[ts[0][0]][2][:300]}")
        for t in ts:
            print(f"    - {t[2][:70]}")

    # complement BioLORD : reformulations que le lexical rate
    if NPZ.exists():
        d = np.load(NPZ, allow_pickle=True)
        idx = {str(i): k for k, i in enumerate(d["ids"])}
        paires = 0
        exemples = []
        for chap, ts in par_chap.items():
            ts = [t for t in ts if str(t[0]) in idx]
            if len(ts) < 2:
                continue
            v = np.stack([d["en"][idx[str(t[0])]] for t in ts])
            v = v / np.clip(np.linalg.norm(v, axis=1, keepdims=True), 1e-9, None)
            sim = v @ v.T
            for i in range(len(ts)):
                for j in range(i + 1, len(ts)):
                    if sim[i, j] >= COS_MIN:
                        paires += 1
                        meme = apparie.get(ts[i][0], (0, -1))[:2] == apparie.get(ts[j][0], (1, -2))[:2]
                        if not meme and len(exemples) < 15:
                            exemples.append((sim[i, j], chap, ts[i][2], ts[j][2]))
        print(f"\n=== COMPLEMENT BioLORD (cos >= {COS_MIN}, meme chapitre) ===")
        print(f"paires proches : {paires}")
        print(f"--- 15 paires que le lexical n'a PAS mises ensemble ---")
        for s, chap, a, b in sorted(exemples, reverse=True):
            print(f"  {s:.3f}  {a[:52]:54s} || {b[:52]}")


if __name__ == "__main__":
    main()
