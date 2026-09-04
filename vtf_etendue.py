#!/usr/bin/env python3
"""Pose l'axe d'etendue d'Amsterdam sur les villosites avasculaires.

PP.PLA-VAS-055 et PP.PLA-VAS-029 viennent d'etre fusionnes dans
PP.PAR-VAS-026 : le premier disait la meme lesion en vocabulaire soffoet
2008 ("hyalinisees en clusters, stade tardif"), le second portait le critere
de petits foyers. Amsterdam ne nomme qu'un terme, qualifie par l'etendue :

  Avascular villi should be qualified in distribution and extent. Small foci
  are 3 or more foci of 2 to 4 terminal villi [...] Intermediate foci are 5
  to 10 villi, and large foci are more than 10 villi.
  -- Khong 2019, consensus d'Amsterdam

L'ectasie vasculaire n'est pas un stade de la VTF mais un marqueur a part
entiere de la meme liste : elle garde son terme, sans le suffixe.

--dry-run pour voir le plan. --selftest pour la verification.
"""
import shutil, sqlite3, sys, time

DB = "/home/mathevet/Bureau/foeto_base/syndromes_foetaux.db"
P = "FOETO:"

CIBLE = P + "PP.PAR-VAS-026"
ETENDUE = [
    (1, "Petits foyers : trois foyers ou plus de 2 à 4 villosités terminales présentant "
        "une perte totale des capillaires villositaires et une fibrose hyaline bénigne du stroma."),
    (2, "Foyers intermédiaires : 5 à 10 villosités."),
    (3, "Grands foyers : plus de 10 villosités."),
]
RENOMME = (P + "PP.PLA-VAS-007", "Ectasie vasculaire des troncs villositaires")


def applique(db):
    assert db.execute("SELECT 1 FROM foeto_terms WHERE id=?", (CIBLE,)).fetchone(), CIBLE
    db.executemany("INSERT OR REPLACE INTO foeto_grades (term_id, axe, grade, desc_fr) "
                   "VALUES (?,'etendue',?,?)", [(CIBLE, g, d) for g, d in ETENDUE])
    i, lab = RENOMME
    n = db.execute("UPDATE foeto_terms SET label_fr=? WHERE id=?", (lab, i)).rowcount
    assert n == 1, f"terme a renommer absent : {i}"
    return len(ETENDUE)


def main():
    print(f"  {CIBLE[6:]:16s} + {len(ETENDUE)} lignes d'etendue")
    print(f"  {RENOMME[0][6:]:16s} -> {RENOMME[1]}")
    if "--dry-run" in sys.argv:
        print("--dry-run : rien ecrit")
        return

    bak = f"{DB}.bak_{time.strftime('%Y%m%d_%H%M%S')}"
    shutil.copy2(DB, bak)
    db = sqlite3.connect(DB)
    applique(db)
    db.commit()
    print(f"\nbackup {bak}")
    for r in db.execute("SELECT axe, grade, substr(desc_fr,1,60) FROM foeto_grades "
                        "WHERE term_id=? ORDER BY axe, grade", (CIBLE,)):
        print(f"  {r[0]:8s} {r[1]}  {r[2]}")
    print(db.execute("SELECT label_fr FROM foeto_terms WHERE id=?", (RENOMME[0],)).fetchone()[0])


def selftest():
    assert [g for g, _ in ETENDUE] == [1, 2, 3], "etendue non contigue"
    assert "stade" not in RENOMME[1].lower(), "le suffixe de stade doit disparaitre"
    db = sqlite3.connect(":memory:")
    db.execute("CREATE TABLE foeto_terms (id TEXT PRIMARY KEY, label_fr TEXT)")
    db.execute("CREATE TABLE foeto_grades (term_id TEXT, axe TEXT, grade INTEGER,"
               " desc_fr TEXT, PRIMARY KEY (term_id, axe, grade))")
    db.executemany("INSERT INTO foeto_terms VALUES (?,?)", [(CIBLE, "x"), (RENOMME[0], "x")])
    assert applique(db) == 3
    applique(db)  # rejouable : INSERT OR REPLACE, pas de doublon
    assert db.execute("SELECT count(*) FROM foeto_grades").fetchone()[0] == 3
    print("selftest ok")


if __name__ == "__main__":
    (selftest if "--selftest" in sys.argv else main)()
