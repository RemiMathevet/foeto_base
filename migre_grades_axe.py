#!/usr/bin/env python3
"""Ajoute l'axe a foeto_grades : un terme peut porter un stade ET un grade.

Le MIR et le FIR d'Amsterdam croisent deux echelles independantes — le stade
(1 chorionite, 2 chorioamnionite, 3 necrosante) et le grade (1 non severe,
2 severe). La PK (term_id, grade) n'en portait qu'une. Elle devient
(term_id, axe, grade). Les 18 lignes existantes sont toutes des grades.

Aucune ligne d'axe 'stade' n'est ecrite ici : tant qu'il n'y en a pas, le
SELECT term_id, grade, desc_fr des viewers rend exactement le meme resultat.
Avant de remplir les stades il faudra que ce SELECT filtre sur l'axe.

--dry-run pour voir le plan. --selftest pour la verification.
"""
import shutil, sqlite3, sys, time

DB = "/home/mathevet/Bureau/foeto_base/syndromes_foetaux.db"
NEUF = """CREATE TABLE foeto_grades (
    term_id TEXT NOT NULL,
    axe     TEXT NOT NULL DEFAULT 'grade',
    grade   INTEGER NOT NULL,
    desc_fr TEXT NOT NULL,
    FOREIGN KEY (term_id) REFERENCES foeto_terms(id),
    PRIMARY KEY (term_id, axe, grade)
)"""


def a_laxe(db):
    return any(r[1] == "axe" for r in db.execute("PRAGMA table_info(foeto_grades)"))


def migre(db):
    """Recree la table avec l'axe et y reverse les lignes, toutes en 'grade'."""
    avant = db.execute("SELECT term_id, grade, desc_fr FROM foeto_grades "
                       "ORDER BY term_id, grade").fetchall()
    db.execute("ALTER TABLE foeto_grades RENAME TO foeto_grades_old")
    db.execute(NEUF)
    db.execute("INSERT INTO foeto_grades (term_id, axe, grade, desc_fr) "
               "SELECT term_id, 'grade', grade, desc_fr FROM foeto_grades_old")
    db.execute("DROP TABLE foeto_grades_old")
    apres = db.execute("SELECT term_id, grade, desc_fr FROM foeto_grades "
                       "ORDER BY term_id, grade").fetchall()
    assert avant == apres, "la vue des viewers a change"
    return len(apres)


def main():
    db = sqlite3.connect(DB)
    if a_laxe(db):
        print("colonne axe deja presente, rien a faire")
        return
    n = db.execute("SELECT count(*) FROM foeto_grades").fetchone()[0]
    print(f"{n} lignes a reverser en axe='grade'")
    if "--dry-run" in sys.argv:
        print("--dry-run : rien ecrit")
        return

    bak = f"{DB}.bak_{time.strftime('%Y%m%d_%H%M%S')}"
    shutil.copy2(DB, bak)
    print(f"backup {bak}")
    n = migre(db)
    db.commit()
    assert a_laxe(db)
    print(f"{n} lignes migrees, vue des viewers inchangee")


def selftest():
    db = sqlite3.connect(":memory:")
    db.execute("CREATE TABLE foeto_grades (term_id TEXT NOT NULL, grade INTEGER NOT NULL,"
               " desc_fr TEXT NOT NULL, PRIMARY KEY (term_id, grade))")
    db.executemany("INSERT INTO foeto_grades VALUES (?,?,?)",
                   [("T:1", 1, "non severe"), ("T:1", 2, "severe")])
    assert not a_laxe(db)
    assert migre(db) == 2
    assert a_laxe(db)
    # ce que la PK d'avant interdisait : meme terme, meme numero, deux axes
    db.execute("INSERT INTO foeto_grades VALUES ('T:1','stade',1,'chorionite')")
    assert db.execute("SELECT count(*) FROM foeto_grades WHERE term_id='T:1'"
                      ).fetchone()[0] == 3
    try:
        db.execute("INSERT INTO foeto_grades VALUES ('T:1','stade',1,'doublon')")
        raise AssertionError("la PK doit refuser le doublon (term_id, axe, grade)")
    except sqlite3.IntegrityError:
        pass
    print("selftest ok")


if __name__ == "__main__":
    (selftest if "--selftest" in sys.argv else main)()
