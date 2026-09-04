#!/usr/bin/env python3
"""Mesure le volume de doublons « meme phrase d'origine » dans foeto_terms.

Entree : syndromes_foetaux.db (foeto_terms.axis='pathologie' + chunk_meta source_type='book').
Chaque terme porte dans `sources` un ou plusieurs ids de chapitre separes par `|`.
On reancre chaque terme sur la PHRASE du livre qui le porte (recouvrement de mots
de label_en contre les phrases des chunks du chapitre), puis on groupe les termes
par phrase : deux termes sur la meme phrase sont un doublon ou deux facettes.

Sortie : stdout (distribution + groupes) et doublons_source.tsv.
Lecture seule sur la base.
"""
import re, sqlite3, sys, unicodedata
from collections import defaultdict

DB = "/home/mathevet/Bureau/foeto_base/syndromes_foetaux.db"
SEUIL = 0.5  # fraction des mots du terme presents dans la phrase pour l'ancrer

STOP = set("""the and for with from that this than then they them their there these those
into onto over under between within without during after before while about above below
which where when what whom whose have has had been being were was are is be of in on at
to by as it its or nor not but also such some most many more less least both each other
another same different due can may might must should would could shall will not non
associated observed described reported seen show shows shown found present presence
absence case cases patient patients infant infants fetus fetal foetal type types form
forms feature features finding findings change changes lesion lesions""".split())


def norm(s):
    s = unicodedata.normalize("NFKD", s.lower())
    s = "".join(c for c in s if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]+", " ", s)


def mots(s):
    return {w for w in norm(s).split() if len(w) >= 4 and w not in STOP}


def phrases(txt):
    """Decoupage naif en phrases : suffisant, les chunks sont deja segmentes."""
    return [p.strip() for p in re.split(r"(?<=[.;:!?])\s+", txt) if len(p.strip()) >= 30]


def main():
    db = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)

    chapitres = defaultdict(list)  # source_id -> [(rowid, [phrases])]
    for rid, sid, txt in db.execute(
        "SELECT rowid, source_id, chunk_text FROM chunk_meta WHERE source_type='book'"
    ):
        ph = phrases(txt)
        if ph:
            chapitres[sid].append((rid, ph))

    termes = db.execute(
        "SELECT id, organe, label_fr, COALESCE(label_en,''), COALESCE(sources,'') "
        "FROM foeto_terms WHERE axis='pathologie' AND COALESCE(sources,'')<>''"
    ).fetchall()

    ancres, sans_chapitre, sans_ancre = {}, [], []
    for tid, org, fr, en, src in termes:
        chaps = [c.strip() for c in src.split("|") if c.strip() in chapitres]
        if not chaps:
            sans_chapitre.append((tid, org, fr, src))
            continue
        mt = mots(en or fr)
        if not mt:
            sans_ancre.append((tid, org, fr, 0.0))
            continue
        best = (0.0, None, None)
        for c in chaps:
            for rid, ph in chapitres[c]:
                for i, p in enumerate(ph):
                    s = len(mt & mots(p)) / len(mt)
                    if s > best[0]:
                        best = (s, (rid, i), p)
        if best[0] >= SEUIL:
            ancres[tid] = (best[1], best[0], best[2], org, fr)
        else:
            sans_ancre.append((tid, org, fr, best[0]))

    groupes = defaultdict(list)
    for tid, (cle, sc, phr, org, fr) in ancres.items():
        groupes[cle].append((tid, org, fr, sc, phr))

    multi = {k: v for k, v in groupes.items() if len(v) > 1}
    n_dans_multi = sum(len(v) for v in multi.values())

    assert len(ancres) + len(sans_ancre) + len(sans_chapitre) == len(termes)

    print(f"termes pathologie sources        : {len(termes)}")
    print(f"  chapitre absent de chunk_meta  : {len(sans_chapitre)}")
    print(f"  chapitre trouve, phrase < {SEUIL} : {len(sans_ancre)}")
    print(f"  ancres sur une phrase          : {len(ancres)}")
    print()
    print(f"phrases distinctes portant >=1 terme : {len(groupes)}")
    print(f"phrases portant >=2 termes           : {len(multi)}")
    print(f"TERMES EN DOUBLON POTENTIEL          : {n_dans_multi}"
          f"  ({100*n_dans_multi/max(len(ancres),1):.0f} % des ancres,"
          f" {100*n_dans_multi/len(termes):.0f} % des sources)")
    print()
    print("taille de groupe : nb de phrases")
    tailles = defaultdict(int)
    for v in multi.values():
        tailles[len(v)] += 1
    for t in sorted(tailles, reverse=True):
        print(f"  {t:3d} termes : {tailles[t]:4d} phrases")

    with open("doublons_source.tsv", "w", encoding="utf-8") as f:
        f.write("groupe\tn\tid\torgane\tlabel_fr\tscore\tphrase\n")
        for g, (cle, v) in enumerate(
            sorted(multi.items(), key=lambda kv: -len(kv[1])), 1
        ):
            for tid, org, fr, sc, phr in sorted(v):
                f.write(f"{g}\t{len(v)}\t{tid}\t{org}\t{fr}\t{sc:.2f}\t"
                        f"{' '.join(phr.split())[:400]}\n")

    print("\n--- 8 plus gros groupes ---")
    for cle, v in sorted(multi.items(), key=lambda kv: -len(kv[1]))[:8]:
        print(f"\n[{len(v)} termes] {' '.join(v[0][4].split())[:200]}")
        for tid, org, fr, sc, _ in sorted(v):
            print(f"    {org:12s} {fr}")

    print(f"\n-> doublons_source.tsv ({n_dans_multi} lignes)")


def selftest():
    assert mots("Renal dysplasia with cysts") == {"renal", "dysplasia", "cysts"}
    assert len(phrases("A. B. " + "x" * 40 + ". short")) == 1
    t = mots("mesangial hypercellularity")
    p = mots("There is mesangial hypercellularity and glomerulomegaly in these infants.")
    assert len(t & p) / len(t) == 1.0
    print("selftest ok")


if __name__ == "__main__":
    (selftest if "--selftest" in sys.argv else main)()
