#!/usr/bin/env python3
"""Propose le terme parent de chaque famille de gradation de foeto_terms.

Une gradation n'est pas un terme : c'est UN id plus N lignes foeto_grades.
Le vocabulaire porte aujourd'hui le grade dans le libelle, parfois en triple
(le MIR existe en membranes deux fois et en parenchyme une fois).

Ce script porte la partition proposee des 37 libelles portant un mot de
gradation, et VERIFIE qu'elle couvre exactement ce que la base contient :
toute famille inventee ou tout terme oublie fait echouer la passe.

Lecture seule. Sortie stdout + parents_grades.tsv.
"""
import sqlite3, sys

DB = "/home/mathevet/Bureau/foeto_base/syndromes_foetaux.db"
LIKE = ("stage", "grade", "stade", "degré", "sévère", "modéré", "léger", "minime")

P = "FOETO:"
# famille -> (parent propose, id du parent s'il existe deja, {grade: [ids]})
FAMILLES = [
    ("Reponse inflammatoire maternelle (MIR)", "Chorioamniotite aiguë",
     P + "PP.PLA-INF-007", {
         "1": ["PP.MEM-INF-010", "PP.PAR-INF-011", "PP.MEM-INF-002"],
         "2": ["PP.MEM-INF-011", "PP.PAR-INF-012", "PP.MEM-INF-001"],
         "3": ["PP.MEM-INF-012", "PP.PAR-INF-013", "PP.MEM-INF-004"]}),
    ("Reponse inflammatoire foetale (FIR)", "Réponse inflammatoire fœtale (FIR)",
     None, {
         "1": ["PP.COR-INF-003"], "2": ["PP.COR-INF-004"], "3": ["PP.COR-INF-005"]}),
    ("Involution thymique de stress", "Involution thymique de stress",
     P + "PF.HEM-CLA-005", {
         "1": ["PF.HEM-CLA-007"], "2": ["PF.HEM-CLA-008"], "3": ["PF.HEM-CLA-009"]}),
    ("Villite chronique d'etiologie inconnue", "Villite chronique d'étiologie inconnue (VCEI)",
     P + "PP.PAR-INF-007", {
         "1": ["PP.PAR-VAS-024"], "2": ["PP.PAR-VAS-023"]}),
    ("Abruptio placentae", "Abruptio placentae", None, {
        "1": ["PP.MEM-VAS-001", "PP.PAR-VAS-028"],
        "2": ["PP.MEM-VAS-002", "PP.PAR-VAS-029"]}),
    ("Depots fibrinoides perivillositaires (NIDF)",
     "Dépôts fibrinoïdes périvillositaires massifs (NIDF / maternal floor infarction)",
     P + "PP.PAR-VAS-003", {
         "1": ["PP.PAR-VAS-027"], "2": ["PP.PAR-VAS-022"]}),
    ("Spectre placenta accreta (PAS)", "Placenta accreta spectrum",
     P + "PP.PAR-MAL-003", {
         "1": ["PP.PAR-MAL-004"], "2": ["PP.PAR-MAL-005"], "3": ["PP.PAR-MAL-006"]}),
]

# PAS une gradation : deux signes distincts, qui existent DEJA ailleurs.
# Remi 2026-09-04 : le high/low de la FVM ne s'appuie sur rien dans le corpus
# (sources vides, seule la description invoque Amsterdam 2014) -> fusionner
# chaque terme dans le signe existant plutot que le renommer.
SIGNES_SEPARES = {
    "PP.PAR-VAS-006": "-> PP.PAR-VAS-026 Villosites avasculaires (ou PLA-VAS-029 petits foyers)",
    "PP.PAR-VAS-005": "-> PP.PLA-VAS-039 Thrombose des vaisseaux foetaux",
}

# deux lesions distinctes decrivant une sequence temporelle, pas deux grades
ARBITRAGE = {"PP.PLA-VAS-007": "VTF precoce = ectasie ; tardif = hyalinisation",
             "PP.PLA-VAS-055": "lesions differentes, pas deux grades du meme terme"}

# le mot de gradation y est descriptif : stade de maturation, critere, qualifieur
FAUX_POSITIFS = {
    "PF.HEM-RET-001": "stade de maturation myeloide, pas un grade lesionnel",
    "PF.PEA-MAL-008": "stades de maturation du melanosome",
    "PF.PEA-MAL-063": "stade evolutif de l'incontinentia pigmenti",
    "PP.PCH-INF-003": "CRITERE du grade 2 du MIR, pas un terme grade",
    "PF.CER-MET-011": "qualifieur libre", "PF.CER-CLA-098": "qualifieur libre",
    "PF.MUL-MET-207": "qualifieur libre",
}


def recense(db):
    ou = " OR ".join(f"label_fr LIKE '%{m}%'" for m in LIKE)
    return {r[0][len(P):]: r[1:] for r in db.execute(
        f"SELECT id, organe, label_fr FROM foeto_terms WHERE axis='pathologie' AND ({ou})")}


def main():
    db = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    base = recense(db)
    vus = ({i for _, _, _, g in FAMILLES for v in g.values() for i in v}
           | set(SIGNES_SEPARES) | set(ARBITRAGE) | set(FAUX_POSITIFS))

    manque, migres = set(base) - vus, vus - set(base)
    assert not manque, f"termes grades non classes : {manque}"
    if migres:
        # migre_gradations.py est passe : ces termes n'ont plus de ligne.
        print(f"{len(migres)} termes deja replies sur leur parent, "
              f"il reste {len(base)} libelles portant un mot de gradation")

    lignes = []
    for nom, label, pid, grades in FAMILLES:
        grades = {g: [i for i in v if i in base] for g, v in grades.items()}
        grades = {g: v for g, v in grades.items() if v}
        if not grades:
            continue
        n = sum(len(v) for v in grades.values())
        etat = f"EXISTE {pid}" if pid else "A CREER"
        print(f"\n## {nom} — {n} termes -> 1 + {len(grades)} grades   [{etat}]")
        print(f"   parent : {label}")
        for g, ids in grades.items():
            for i in ids:
                print(f"     grade {g:5s} {i:18s} {base[i][1]}")
                lignes.append((nom, label, pid or "", g, i, base[i][0], base[i][1]))

    def section(titre, d, large=60):
        vivants = [(i, w) for i, w in d.items() if i in base]
        if not vivants:
            return
        print(f"\n## {titre} — {len(vivants)} termes")
        for i, w in vivants:
            print(f"     {i:18s} {base[i][1][:large]:{large + 2}s} {w}")

    section("Deux signes separes, deja presents — a fusionner", SIGNES_SEPARES, 44)
    section("Pas des gradations, a laisser tels quels", FAUX_POSITIFS)
    section("Arbitrage", ARBITRAGE)

    with open("parents_grades.tsv", "w", encoding="utf-8") as f:
        f.write("famille\tparent_label\tparent_id\tgrade\tid\torgane\tlabel_fr\n")
        for l in lignes:
            f.write("\t".join(l) + "\n")

    reste = lambda d: sum(1 for i in d if i in base)
    print(f"\n{len(base)} libelles portant un mot de gradation : {len(lignes)} en gradation "
          f"a migrer, {reste(SIGNES_SEPARES)} a fusionner comme signes, "
          f"{reste(ARBITRAGE)} en arbitrage, {reste(FAUX_POSITIFS)} faux positifs")
    print(f"-> parents_grades.tsv ({len(lignes)} lignes)")


def selftest():
    ids = [i for _, _, _, g in FAMILLES for v in g.values() for i in v]
    assert len(ids) == len(set(ids)), "un terme grade dans deux familles"
    autres = set(FAUX_POSITIFS) | set(ARBITRAGE) | set(SIGNES_SEPARES)
    assert not (set(ids) & autres), "terme a la fois grade et classe ailleurs"
    # foeto_grades.grade est INTEGER : pas de clef "low" ni "3-4"
    assert all(g.isdigit() for _, _, _, gr in FAMILLES for g in gr), "grade non entier"
    print("selftest ok")


if __name__ == "__main__":
    (selftest if "--selftest" in sys.argv else main)()
