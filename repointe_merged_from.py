#!/usr/bin/env python3
"""Repointe les dependants des termes retires par une fusion vers leur survivant.

fusion_doublons_purs.py supprime la ligne du perdant et note son id dans
merged_from du survivant, mais ne touchait pas les tables qui le referencent.
Ce script relit merged_from, construit la carte retire -> survivant, et
repointe : foeto_terms.parent_id, foeto_hpo, syndrome_foeto, foeto_genes,
foeto_term_segments, foeto_edges (source_id et target_id).

Les doublons crees par le repointage sont ecrases (INSERT OR IGNORE puis DELETE)
et les boucles sur soi supprimees dans foeto_edges.

--dry-run pour compter sans ecrire. --selftest pour la verification.
"""
import sqlite3, sys

DB = "/home/mathevet/Bureau/foeto_base/syndromes_foetaux.db"
# (table, colonne) portant un id de foeto_terms
CIBLES = [("foeto_terms", "parent_id"), ("foeto_hpo", "foeto_id"),
          ("syndrome_foeto", "foeto_id"), ("foeto_genes", "foeto_id"),
          ("foeto_term_segments", "foeto_id"),
          ("foeto_edges", "source_id"), ("foeto_edges", "target_id")]


def carte(db, seulement=None):
    """retire -> survivant, lue depuis merged_from des termes vivants.

    `seulement` restreint aux ids donnes : on repare une fusion precise sans
    reecrire les references pendantes laissees par les passes anterieures.
    """
    m = {}
    vivants = {r[0] for r in db.execute("SELECT id FROM foeto_terms")}
    for tid, mf in db.execute(
        "SELECT id, merged_from FROM foeto_terms WHERE COALESCE(merged_from,'')<>''"
    ):
        for old in (x.strip() for x in mf.split(",")):
            if old and old.startswith("FOETO:") and old not in vivants \
                    and (seulement is None or old in seulement):
                m[old] = tid
    return m


def main():
    dry = "--dry-run" in sys.argv
    ids = {a for a in sys.argv[1:] if not a.startswith("--")}
    db = sqlite3.connect(DB)
    m = carte(db, ids or None)
    print(f"{len(m)} ids retires connus de merged_from\n")

    total = 0
    for t, c in CIBLES:
        n = sum(db.execute(f"SELECT count(*) FROM {t} WHERE {c}=?", (o,)).fetchone()[0]
                for o in m)
        if not n:
            continue
        total += n
        print(f"  {t}.{c:11s} {n} lignes a repointer")
        if dry:
            continue
        for old, new in m.items():
            db.execute(f"UPDATE OR IGNORE {t} SET {c}=? WHERE {c}=?", (new, old))
            db.execute(f"DELETE FROM {t} WHERE {c}=?", (old,))   # restes du OR IGNORE
    if dry:
        print(f"\n--dry-run : {total} lignes, rien ecrit")
        return

    db.execute("DELETE FROM foeto_edges WHERE source_id=target_id")
    db.commit()

    reste = sum(db.execute(f"SELECT count(*) FROM {t} WHERE {c}=?", (o,)).fetchone()[0]
                for t, c in CIBLES for o in m)
    assert reste == 0, f"{reste} references pendantes subsistent"
    print(f"\n{total} lignes repointees, zero reference pendante")

    # hors perimetre : parents jamais crees, absents de tout merged_from, donc
    # pas reparables ici. Signale sans faire echouer la passe.
    autres = db.execute(
        "SELECT count(*) FROM foeto_terms WHERE COALESCE(parent_id,'')<>'' "
        "AND parent_id NOT IN (SELECT id FROM foeto_terms)").fetchone()[0]
    if autres:
        print(f"note : {autres} parent_id pendants hors perimetre (parents inexistants)")


def selftest():
    db = sqlite3.connect(":memory:")
    db.execute("CREATE TABLE foeto_terms (id TEXT PRIMARY KEY, merged_from TEXT)")
    db.executemany("INSERT INTO foeto_terms VALUES (?,?)",
                   [("FOETO:A", "FOETO:B,FOETO:C"), ("FOETO:D", "")])
    m = carte(db)
    assert m == {"FOETO:B": "FOETO:A", "FOETO:C": "FOETO:A"}, m
    assert carte(db, {"FOETO:B"}) == {"FOETO:B": "FOETO:A"}, "seulement doit restreindre"
    db.execute("INSERT INTO foeto_terms VALUES ('FOETO:E','FOETO:D')")
    assert "FOETO:D" not in carte(db), "un id VIVANT ne doit jamais etre repointe"
    print("selftest ok")


if __name__ == "__main__":
    (selftest if "--selftest" in sys.argv else main)()
