#!/usr/bin/env python3
"""Fusionne les doublons purs de foeto_terms (sac de mots de label_fr identique).

Ne traite QUE la famille mecanique, definie par trois garde-fous cumulatifs :
  - tous les membres du groupe portent une source ET une description (sinon c'est
    la famille « compartiment » : un jumeau vide cree pour le viewer, arbitrage) ;
  - aucun libelle ne contient « grade » ou « stade » (sinon c'est un axe de
    foeto_grades, pas un doublon) ;
  - aucun membre n'est reference dans lames.db (annotations.ann_class,
    diagnoses.diagnosis).

Survivant = description la plus longue, egalite tranchee par id. Le perdant est
supprime, son id ajoute a merged_from du survivant (convention deja en place sur
633 termes) et ses chapitres sources unis a ceux du survivant.

--dry-run pour voir le plan. --selftest pour la verification.
"""
import re, sqlite3, sys, unicodedata
from collections import defaultdict

DB = "/home/mathevet/Bureau/foeto_base/syndromes_foetaux.db"
LAMES = "/media/SSDsamsung/db/lames.db"
STOP = set("de la le les des du un une et en a au aux dans par pour avec sur sans".split())


def bag(s):
    s = unicodedata.normalize("NFKD", (s or "").lower())
    s = "".join(c for c in s if not unicodedata.combining(c))
    return frozenset(w for w in re.sub(r"[^a-z0-9]+", " ", s).split()
                     if len(w) >= 4 and w not in STOP)


def references():
    db = sqlite3.connect(f"file:{LAMES}?mode=ro", uri=True)
    r = defaultdict(int)
    for t, c in (("annotations", "ann_class"), ("diagnoses", "diagnosis")):
        for i, n in db.execute(
            f"SELECT {c}, count(*) FROM {t} WHERE {c} LIKE 'FOETO:%' GROUP BY 1"
        ):
            r[i] += n
    return r


def plan(db, refs):
    groupes = defaultdict(list)
    for row in db.execute(
        "SELECT id, organe, label_fr, COALESCE(description_fr,''), COALESCE(sources,''), "
        "COALESCE(merged_from,'') FROM foeto_terms WHERE axis='pathologie'"
    ):
        b = bag(row[2])
        if b:
            groupes[b].append(row)

    out = []
    for v in groupes.values():
        if len(v) < 2:
            continue
        if any(not r[3] or not r[4] for r in v):
            continue                                   # jumeau vide -> compartiment
        if any(re.search(r"grade|stade", r[2], re.I) for r in v):
            continue                                   # axe de gradation
        if any(refs.get(r[0]) for r in v):
            continue                                   # porte des annotations
        if len({r[1] for r in v}) > 1:
            continue                                   # organes differents -> arbitrage
        v.sort(key=lambda r: (-len(r[3]), r[0]))
        out.append((v[0], v[1:]))
    return out


def libelle(keep, perdus):
    """Meme libelle aux diacritiques pres : garder l'orthographe accentuee."""
    def nu(s):
        return "".join(c for c in unicodedata.normalize("NFKD", s)
                       if not unicodedata.combining(c))
    def acc(s):
        return sum(c != d for c, d in zip(s, nu(s))) + len(s) - len(nu(s))
    cands = [keep] + list(perdus)
    if len({nu(r[2]) for r in cands}) == 1:
        return max(cands, key=lambda r: acc(r[2]))[2]
    return keep[2]


def main():
    dry = "--dry-run" in sys.argv
    # --sans-refs : les annotations lames.db seront refaites sur le vocabulaire
    # propre, elles ne protegent plus un terme de la fusion.
    refs = {} if "--sans-refs" in sys.argv else references()
    db = sqlite3.connect(DB)
    groupes = plan(db, refs)

    print(f"{len(groupes)} groupes mecaniques, "
          f"{sum(1 + len(p) for _, p in groupes)} termes -> {len(groupes)}\n")
    for keep, perdus in groupes:
        lab = libelle(keep, perdus)
        star = "  <- libelle repris" if lab != keep[2] else ""
        print(f"GARDE  {keep[0]:22s} {keep[1]:14s} {lab}{star}")
        for p in perdus:
            print(f"  fond {p[0]:22s} {p[1]:14s} {p[2]}")

    if dry:
        print("\n--dry-run : rien ecrit")
        return

    for keep, perdus in groupes:
        srcs = [c for c in keep[4].split("|") if c]
        for p in perdus:
            srcs += [c for c in p[4].split("|") if c not in srcs]
        mf = [x for x in keep[5].split(",") if x]
        mf += [p[0] for p in perdus if p[0] not in mf]
        db.execute("UPDATE foeto_terms SET sources=?, merged_from=?, label_fr=? WHERE id=?",
                   ("|".join(srcs), ",".join(mf), libelle(keep, perdus), keep[0]))
        db.executemany("DELETE FROM foeto_terms WHERE id=?",
                       [(p[0],) for p in perdus])
    db.commit()

    restant = plan(db, refs)
    assert not restant, f"{len(restant)} groupes subsistent apres fusion"
    print(f"\nfusion faite, {sum(len(p) for _, p in groupes)} termes retires, "
          f"repasse a vide")


def selftest():
    assert bag("Nécrose corticale laminaire") == bag("Nécrose laminaire corticale")
    assert bag("Perte des oligodendrocytes") == bag("Perte d'oligodendrocytes")
    assert bag("Polydactylie post-axiale") != bag("Polydactylie pré-axiale")
    assert bag("Involution thymique de stress") != bag("Involution thymique de stress — grade 1")
    r = lambda i, o, l, d: (i, o, l, d, "src", "")
    assert libelle(r("a", "cerveau", "Ulegyrie", "xx"),
                   [r("b", "cerveau", "Ulégyrie", "x")]) == "Ulégyrie"
    assert libelle(r("a", "cerveau", "Nécrose corticale laminaire", "xx"),
                   [r("b", "cerveau", "Nécrose laminaire corticale", "x")]) \
        == "Nécrose corticale laminaire"
    print("selftest ok")


if __name__ == "__main__":
    (selftest if "--selftest" in sys.argv else main)()
