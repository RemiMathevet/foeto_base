#!/usr/bin/env python3
"""syndrome_diff_livres : les differentiels ECRITS PAR LE LIVRE, avec ce qui tranche.

Spranger, section MAJOR DIFFERENTIAL DIAGNOSES (225 entites) : un paragraphe par
syndrome a distinguer, le nom en tete, puis les criteres — « Spondyloepiphyseal
dysplasia congenita: There are no cranial changes and the pubic bones are not
ossified at birth. » C'est le differentiel sourcé que le §5 de la fiche
n'avait pas : jusqu'ici il etait calcule par chevauchement Jaccard sur
syndrome_hpo (Orphanet), et proposait « deficience intellectuelle profonde »
comme discriminateur foetal.

Aucun LLM. Le decoupage est structurel (paragraphes), le nom est ce qui precede
le premier « : » ou le premier verbe de comparaison ; le reste est le verbatim.
Le nom est ensuite apparie aux syndromes de la base par le meme index que
build_syndrome_hpo_livres ; non apparie -> diff_syndrome_id NULL, le nom reste.

Usage : python3 build_diff_livres.py [--apply]
"""
import argparse
import re
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_syndrome_hpo_livres import index_syndromes, norm, variantes

DB = "/home/mathevet/Bureau/foeto_base/syndromes_foetaux.db"
SRC = Path("/home/mathevet/Bureau/Embedding_RAG_V2/chapitres/spranger_entites")


def tol(p):
    return r"\s*".join(r"\s*".join(m) for m in p.split())


FIN = "|".join(tol(k) for k in ["COURSE AND PROGNOSIS", "MODE OF INHERITANCE", "GENETICS",
                                "REMARKS", "TREATMENT", "BIBLIOGRAPHY"])
RX = re.compile(r"^[ \t]*" + tol("MAJOR DIFFERENTIAL DIAGNOSES") + r"[ \t]*$(.*?)^[ \t]*(?:" + FIN + r")[ \t]*$",
                re.M | re.S)
# un paragraphe de differentiel commence en debut de ligne par une majuscule,
# apres une ligne qui finissait par un point (ou en tete de section)
VERBE = re.compile(r"^(.{3,90}?)(?::|\s+(?:differs?|is|are|may|can|resembles?|shows?|has|have|lacks?|"
                   r"presents?|should|must|need)\b)", re.S)


def paragraphes(texte):
    texte = texte.replace("​", "")
    lignes = [l.rstrip() for l in texte.strip().split("\n")]
    paras, cur = [], []
    for l in lignes:
        if not l.strip():
            continue
        if re.match(r"^\d{1,3}$", l.strip()):        # numero de page tombe dans le texte
            continue
        debut = re.match(r"^[A-Z]", l) and (not cur or cur[-1].rstrip().endswith((".", ")")))
        if debut and cur:
            paras.append(" ".join(cur))
            cur = []
        cur.append(l.strip())
    if cur:
        paras.append(" ".join(cur))
    return [re.sub(r"\s+", " ", p) for p in paras if len(p) > 25]


def nom_et_critere(para):
    m = VERBE.match(para)
    if not m:
        return None, para
    nom = m.group(1).strip().rstrip(":").strip()
    return nom, para


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()
    c = sqlite3.connect(DB)
    idx = index_syndromes(c)
    # titre propre de chaque entree, tel qu'il est deja dans la matrice
    titres = dict(c.execute("""select distinct substr(entree, 1, instr(entree, '#') - 1), syndrome_titre
                               from syndrome_hpo_livres where livre='spranger_entites'"""))
    rows, n_ent, n_app = [], 0, 0
    for f in sorted(SRC.glob("e*.txt")):
        m = RX.search(f.read_text(encoding="utf-8"))
        if not m:
            continue
        n_ent += 1
        titre = titres.get(f.name) or f.read_text(encoding="utf-8").split("\n")[2].strip()
        for para in paragraphes(m.group(1)):
            nom, verbatim = nom_et_critere(para)
            sid = None
            if nom:
                for v in variantes(nom):
                    sid = idx.get(norm(v))
                    if sid:
                        break
            n_app += bool(sid)
            rows.append(("spranger", f.name, titre, nom, sid, verbatim))
    print(f"{n_ent} entités avec une section différentiel, {len(rows)} différentiels, "
          f"{n_app} appariés à un ORPHA ({n_app*100//max(len(rows),1)} %)")
    for r in rows[:5]:
        print(f"  [{r[2][:38]}] {str(r[3])[:40]:40s} -> {r[4] or '-':12s} « {r[5][:70]} »")

    if a.apply:
        # ne JAMAIS dropper : extract_diff_smith.py ecrit dans la meme table
        # (le 2026-09-12 un DROP ici a efface les lignes Smith en cours d'ecriture)
        c.execute("""CREATE TABLE IF NOT EXISTS syndrome_diff_livres (
            id INTEGER PRIMARY KEY,
            livre TEXT NOT NULL, entree TEXT NOT NULL,
            syndrome_titre TEXT NOT NULL,                 -- l'entree dont on part
            diff_nom TEXT,                                -- le syndrome a distinguer, tel que le livre l'ecrit
            diff_syndrome_id TEXT REFERENCES syndromes(id),
            verbatim TEXT NOT NULL,                       -- le paragraphe entier : ce qui tranche
            cree_le TEXT NOT NULL DEFAULT (datetime('now')))""")
        c.execute("DELETE FROM syndrome_diff_livres WHERE livre='spranger'")
        c.executemany("INSERT INTO syndrome_diff_livres (livre, entree, syndrome_titre, diff_nom, diff_syndrome_id, verbatim) VALUES (?,?,?,?,?,?)", rows)
        c.execute("CREATE INDEX IF NOT EXISTS idx_diff_titre ON syndrome_diff_livres(syndrome_titre)")
        c.commit()
        print(f"\nsyndrome_diff_livres : {len(rows)} lignes.")


if __name__ == "__main__":
    main()
