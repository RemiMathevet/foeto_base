#!/usr/bin/env python3
"""Fusionne des termes de foeto_terms decides a la main, puis repointe.

fusion_doublons_purs.py ne traite que ce qui se decide mecaniquement. Tout le
reste — compartiment, cross-organe, paires proches — se tranche a l'oeil et
arrive ici : le survivant recupere les chapitres sources des perdants et leurs
ids dans merged_from, les lignes perdantes sont supprimees, puis
repointe_merged_from.py remet les references sur le survivant.

  python3 fusionne.py SURVIVANT PERDANT [PERDANT...]

Les ids sont acceptes avec ou sans le prefixe FOETO:.
--dry-run pour voir le plan. --selftest pour la verification.
"""
import os, shutil, sqlite3, subprocess, sys, time

DB = "/home/mathevet/Bureau/foeto_base/syndromes_foetaux.db"
ICI = "/home/mathevet/Bureau/foeto_base"
P = "FOETO:"


def plein(i):
    return i if i.startswith(P) else P + i


def fusionne(db, keep, perdus):
    """Verse sources et merged_from des perdus dans le survivant, les supprime."""
    lu = lambda i: db.execute(
        "SELECT organe, label_fr, COALESCE(sources,''), COALESCE(merged_from,'') "
        "FROM foeto_terms WHERE id=?", (i,)).fetchone()
    k = lu(keep)
    assert k, f"survivant absent : {keep}"

    srcs = [c for c in k[2].split("|") if c]
    mf = [x for x in k[3].split(",") if x]
    for p in perdus:
        r = lu(p)
        assert r, f"perdant absent : {p}"
        srcs += [c for c in r[2].split("|") if c and c not in srcs]
        # un perdant peut deja porter d'anciennes fusions : elles suivent
        mf += [x for x in r[3].split(",") if x and x not in mf]
        if p not in mf:
            mf.append(p)
    db.execute("UPDATE foeto_terms SET sources=?, merged_from=? WHERE id=?",
               ("|".join(srcs), ",".join(mf), keep))
    db.executemany("DELETE FROM foeto_grades WHERE term_id=?", [(p,) for p in perdus])
    db.executemany("DELETE FROM foeto_terms WHERE id=?", [(p,) for p in perdus])
    return len(perdus)


def main():
    ids = [plein(a) for a in sys.argv[1:] if not a.startswith("--")]
    assert len(ids) >= 2, __doc__
    keep, perdus = ids[0], ids[1:]
    assert keep not in perdus, "le survivant ne peut pas etre son propre perdant"

    db = sqlite3.connect(DB)
    for i in ids:
        r = db.execute("SELECT organe, label_fr FROM foeto_terms WHERE id=?", (i,)).fetchone()
        assert r, f"id absent de foeto_terms : {i}"
        print(f"  {'GARDE' if i == keep else ' fond'} {i[6:]:18s} {r[0]:14s} {r[1][:70]}")

    if "--dry-run" in sys.argv:
        print("\n--dry-run : rien ecrit")
        return

    # deux fusions dans la meme seconde ecraseraient le meme fichier
    bak = f"{DB}.bak_{time.strftime('%Y%m%d_%H%M%S')}"
    n = 0
    while os.path.exists(bak):
        n += 1
        bak = f"{DB}.bak_{time.strftime('%Y%m%d_%H%M%S')}_{n}"
    shutil.copy2(DB, bak)
    n = fusionne(db, keep, perdus)
    db.commit()
    for p in perdus:
        assert not db.execute("SELECT 1 FROM foeto_terms WHERE id=?", (p,)).fetchone(), p
    print(f"\nbackup {bak}\n{n} termes fusionnes dans {keep[6:]}\n", flush=True)

    subprocess.run([sys.executable, f"{ICI}/repointe_merged_from.py", *perdus],
                   check=True, cwd=ICI)


def selftest():
    db = sqlite3.connect(":memory:")
    db.execute("CREATE TABLE foeto_terms (id TEXT PRIMARY KEY, organe TEXT, label_fr TEXT,"
               " sources TEXT, merged_from TEXT)")
    db.execute("CREATE TABLE foeto_grades (term_id TEXT, axe TEXT, grade INT, desc_fr TEXT)")
    db.executemany("INSERT INTO foeto_terms VALUES (?,?,?,?,?)", [
        ("FOETO:A", "rein", "garde", "ch1|ch2", ""),
        ("FOETO:B", "rein", "perd", "ch2|ch3", "FOETO:X"),   # B avait deja fusionne X
        ("FOETO:C", "rein", "perd", "", "")])
    db.execute("INSERT INTO foeto_grades VALUES ('FOETO:B','grade',1,'a jeter')")
    assert fusionne(db, "FOETO:A", ["FOETO:B", "FOETO:C"]) == 2
    src, mf = db.execute("SELECT sources, merged_from FROM foeto_terms "
                         "WHERE id='FOETO:A'").fetchone()
    assert src == "ch1|ch2|ch3", src
    assert mf == "FOETO:X,FOETO:B,FOETO:C", "la fusion anterieure du perdant doit suivre"
    assert db.execute("SELECT count(*) FROM foeto_terms").fetchone()[0] == 1
    assert db.execute("SELECT count(*) FROM foeto_grades").fetchone()[0] == 0
    print("selftest ok")


if __name__ == "__main__":
    (selftest if "--selftest" in sys.argv else main)()
