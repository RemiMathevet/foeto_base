#!/usr/bin/env python3
"""Replie les termes gradés de foeto_terms sur un terme parent + foeto_grades.

Une gradation n'est pas un terme. Le vocabulaire portait le stade dans le
libellé — le MIR trois fois pour trois stades (MEM-INF-010/011/012,
PAR-INF-011/012/013, MEM-INF-001/002/004). Chaque membre devient une ligne
foeto_grades(parent, axe, grade, desc) et sa ligne foeto_terms est retirée
via merged_from, comme fusion_doublons_purs.py.

Deux sources pour une ligne de grade :
  ("terme", id)          -> la description (ou le libellé) du terme retiré ;
  ("grade", id, n)       -> une ligne foeto_grades deja presente, deplacee.
Les grades 1-2 du MIR et du FIR sont identiques d'un stade a l'autre : ils
dedupliquent en deux lignes sur le parent, ce qui est exactement la preuve
que le grade est independant du stade.

Ne repointe PAS les references : enchainer repointe_merged_from.py avec les
ids retires, que ce script affiche en fin de passe.

--dry-run pour voir le plan. --selftest pour la verification.
"""
import shutil, sqlite3, sys, time

DB = "/home/mathevet/Bureau/foeto_base/syndromes_foetaux.db"
P = "FOETO:"

# parent : id existant, ou (id neuf, label, organe) a creer.
# lignes : (axe, grade, source). retires : ids de foeto_terms a supprimer.
FAMILLES = [
    dict(nom="MIR — reponse inflammatoire maternelle",
         parent=P + "PP.PLA-INF-007",
         lignes=[("stade", 1, ("terme", P + "PP.MEM-INF-010")),
                 ("stade", 2, ("terme", P + "PP.MEM-INF-011")),
                 ("stade", 3, ("terme", P + "PP.MEM-INF-012")),
                 ("grade", 1, ("grade", P + "PP.MEM-INF-010", 1)),
                 ("grade", 2, ("grade", P + "PP.MEM-INF-010", 2))],
         retires=[P + "PP.MEM-INF-010", P + "PP.MEM-INF-011", P + "PP.MEM-INF-012",
                  P + "PP.PAR-INF-011", P + "PP.PAR-INF-012", P + "PP.PAR-INF-013",
                  P + "PP.MEM-INF-002", P + "PP.MEM-INF-001", P + "PP.MEM-INF-004"]),

    dict(nom="FIR — reponse inflammatoire foetale",
         parent=(P + "PP.COR-INF-008", "Réponse inflammatoire fœtale (FIR)", "cordon"),
         lignes=[("stade", 1, ("terme", P + "PP.COR-INF-003")),
                 ("stade", 2, ("terme", P + "PP.COR-INF-004")),
                 ("stade", 3, ("terme", P + "PP.COR-INF-005")),
                 ("grade", 1, ("grade", P + "PP.COR-INF-003", 1)),
                 ("grade", 2, ("grade", P + "PP.COR-INF-003", 2))],
         retires=[P + "PP.COR-INF-003", P + "PP.COR-INF-004", P + "PP.COR-INF-005"]),

    dict(nom="Involution thymique de stress",
         parent=P + "PF.HEM-CLA-005",
         lignes=[("grade", 1, ("terme", P + "PF.HEM-CLA-007")),
                 ("grade", 2, ("terme", P + "PF.HEM-CLA-008")),
                 ("grade", 3, ("terme", P + "PF.HEM-CLA-009"))],
         retires=[P + "PF.HEM-CLA-007", P + "PF.HEM-CLA-008", P + "PF.HEM-CLA-009"]),

    # les 4 niveaux d'Amsterdam sont deja ecrits, en deux moities low et high
    dict(nom="Villite chronique d'etiologie inconnue (VCEI)",
         parent=P + "PP.PAR-INF-007",
         lignes=[("grade", 1, ("grade", P + "PP.PAR-VAS-024", 1)),
                 ("grade", 2, ("grade", P + "PP.PAR-VAS-024", 2)),
                 ("grade", 3, ("grade", P + "PP.PAR-VAS-023", 1)),
                 ("grade", 4, ("grade", P + "PP.PAR-VAS-023", 2))],
         retires=[P + "PP.PAR-VAS-024", P + "PP.PAR-VAS-023"]),

    # le site n'est pas un grade : il est deja porte par la colonne organe
    dict(nom="Abruptio placentae (membranes)",
         parent=(P + "PP.MEM-VAS-003", "Abruptio placentae", "membranes"),
         lignes=[("stade", 1, ("terme", P + "PP.MEM-VAS-001")),
                 ("stade", 2, ("terme", P + "PP.MEM-VAS-002"))],
         retires=[P + "PP.MEM-VAS-001", P + "PP.MEM-VAS-002"]),

    dict(nom="Abruptio placentae (plaque basale)",
         parent=(P + "PP.PAR-VAS-030", "Abruptio placentae", "parenchyme"),
         lignes=[("stade", 1, ("terme", P + "PP.PAR-VAS-028")),
                 ("stade", 2, ("terme", P + "PP.PAR-VAS-029"))],
         retires=[P + "PP.PAR-VAS-028", P + "PP.PAR-VAS-029"]),

    dict(nom="NIDF — depots fibrinoides perivillositaires",
         parent=P + "PP.PAR-VAS-003",
         lignes=[("etendue", 1, ("terme", P + "PP.PAR-VAS-027")),
                 ("etendue", 2, ("terme", P + "PP.PAR-VAS-022"))],
         retires=[P + "PP.PAR-VAS-027", P + "PP.PAR-VAS-022"]),

    dict(nom="Spectre placenta accreta (PAS)",
         parent=P + "PP.PAR-MAL-003",
         lignes=[("grade", 1, ("terme", P + "PP.PAR-MAL-004")),
                 ("grade", 2, ("terme", P + "PP.PAR-MAL-005")),
                 ("grade", 3, ("terme", P + "PP.PAR-MAL-006"))],
         retires=[P + "PP.PAR-MAL-004", P + "PP.PAR-MAL-005", P + "PP.PAR-MAL-006"]),
]


def pid(f):
    return f["parent"] if isinstance(f["parent"], str) else f["parent"][0]


def desc(db, src):
    """Texte de la ligne de grade, pris au terme retire ou a un grade existant."""
    if src[0] == "terme":
        r = db.execute("SELECT COALESCE(NULLIF(description_fr,''), label_fr) "
                       "FROM foeto_terms WHERE id=?", (src[1],)).fetchone()
        assert r, f"terme absent : {src[1]}"
        return r[0]
    r = db.execute("SELECT desc_fr FROM foeto_grades WHERE term_id=? AND grade=?",
                   src[1:]).fetchone()
    assert r, f"grade absent : {src[1]} {src[2]}"
    return r[0]


def applique(db):
    retires = []
    for f in FAMILLES:
        if not isinstance(f["parent"], str):
            i, lab, org = f["parent"]
            assert not db.execute("SELECT 1 FROM foeto_terms WHERE id=?", (i,)).fetchone(), \
                f"id neuf deja pris : {i}"
            db.execute("INSERT INTO foeto_terms (id, organe, label_fr, axis, domain) "
                       "VALUES (?,?,?,'pathologie','placenta')", (i, org, lab))
        p = pid(f)
        for axe, g, src in f["lignes"]:
            db.execute("INSERT OR REPLACE INTO foeto_grades (term_id, axe, grade, desc_fr) "
                       "VALUES (?,?,?,?)", (p, axe, g, desc(db, src)))
        mf = db.execute("SELECT COALESCE(merged_from,'') FROM foeto_terms WHERE id=?",
                        (p,)).fetchone()[0]
        garde = [x for x in mf.split(",") if x]
        garde += [i for i in f["retires"] if i not in garde]
        db.execute("UPDATE foeto_terms SET merged_from=? WHERE id=?", (",".join(garde), p))
        # les grades des termes retires ne doivent pas survivre a leur terme
        db.executemany("DELETE FROM foeto_grades WHERE term_id=?", [(i,) for i in f["retires"]])
        db.executemany("DELETE FROM foeto_terms WHERE id=?", [(i,) for i in f["retires"]])
        retires += f["retires"]
    return retires


def main():
    db = sqlite3.connect(DB)
    n = sum(len(f["retires"]) for f in FAMILLES)
    neufs = [f["parent"][1] for f in FAMILLES if not isinstance(f["parent"], str)]
    for f in FAMILLES:
        axes = {a for a, _, _ in f["lignes"]}
        print(f"  {f['nom'][:44]:46s} {len(f['retires'])} termes -> "
              f"{pid(f)[6:]:16s} {'+'.join(sorted(axes))}")
    print(f"\n{n} termes replies sur {len(FAMILLES)} parents "
          f"({len(neufs)} crees : {', '.join(neufs)})")
    if "--dry-run" in sys.argv:
        print("--dry-run : rien ecrit")
        return

    bak = f"{DB}.bak_{time.strftime('%Y%m%d_%H%M%S')}"
    shutil.copy2(DB, bak)
    print(f"\nbackup {bak}")
    retires = applique(db)
    db.commit()

    for i in retires:
        assert not db.execute("SELECT 1 FROM foeto_terms WHERE id=?", (i,)).fetchone(), i
    orphelins = db.execute(
        "SELECT count(*) FROM foeto_grades WHERE term_id NOT IN "
        "(SELECT id FROM foeto_terms)").fetchone()[0]
    assert orphelins == 0, f"{orphelins} grades sans terme"
    print(f"{len(retires)} termes retires, "
          f"{db.execute('SELECT count(*) FROM foeto_grades').fetchone()[0]} lignes de grade")
    print("\nrepointer les references :\n  python3 repointe_merged_from.py "
          + " ".join(retires))


def selftest():
    ids = [i for f in FAMILLES for i in f["retires"]]
    assert len(ids) == len(set(ids)), "un terme retire dans deux familles"
    assert not (set(ids) & {pid(f) for f in FAMILLES}), "un parent est aussi retire"
    for f in FAMILLES:
        cles = [(a, g) for a, g, _ in f["lignes"]]
        assert len(cles) == len(set(cles)), f"(axe, grade) en double dans {f['nom']}"
        for a, g, _ in f["lignes"]:
            assert isinstance(g, int) and g > 0, f"grade non entier dans {f['nom']}"
        # toute ligne issue d'un terme doit retirer ce terme
        for _, _, s in f["lignes"]:
            if s[0] == "terme":
                assert s[1] in f["retires"], f"{s[1]} sert de grade sans etre retire"
    print("selftest ok")


if __name__ == "__main__":
    (selftest if "--selftest" in sys.argv else main)()
