#!/usr/bin/env python3
"""Découpe les chapitres d'infections congénitales en une entrée par pathogène,
au format que lit extract_signes_livres.py (numéro, ligne vide, titre, ligne
vide, corps) :

  Keeling ch. 9 « Infection of Mother and Baby »   -> chapitres/keeling_infections/
      sections « Background » par pathogène ; clinique mère + enfant, court
  Developmental Neuropathology ch. 41              -> chapitres/devneuro_infections/
      « Intrauterine infections » : un titre par pathogène, sections
      Clinical features / Macroscopy / Histopathology — la matière neuropath

    python3 split_keeling_infections.py

On ne garde que les infections qui ont une entité fœtale dans la base (ORPHA),
et le titre de l'entrée EST le name_en de l'ORPHA : le rattachement se fait
tout seul par nom dans build_syndrome_hpo_livres. Listériose, paludisme,
chlamydia, gonocoque, SGB, HIV, entérovirus, Zika n'ont pas d'entité fœtale
Orphanet : pas extraits (rien où poser l'attestation).
"""
import re
from pathlib import Path

CHAP = Path("/home/mathevet/Bureau/Embedding_RAG_V2/chapitres")
SRC = CHAP / "keeling/ch09_infections.txt"
OUT = CHAP / "keeling_infections"
SRC2 = CHAP / "devneuro/ch41_intrauterine_infections.txt"
OUT2 = CHAP / "devneuro_infections"
# devneuro : titre de section dans le texte -> (numéro, name_en ORPHA)
SECTIONS_DEVNEURO = {
    "Cytomegalovirus": (1, "Fetal cytomegalovirus syndrome"),
    "Herpes simplex virus": (2, "Congenital herpes simplex virus infection"),
    "Toxoplasmosis": (3, "Congenital toxoplasmosis"),
    "Rubella": (4, "Congenital rubella syndrome"),
    "Varicella": (5, "Congenital varicella syndrome"),
    "Parvovirus B19": (6, "Fetal parvovirus syndrome"),
    "Syphilis": (7, "Congenital syphilis"),
}
FIN_DEVNEURO = ["Enteroviruses", "Zika virus", "Listeriosis", "Tuberculosis", "Other infections", "References"]

# section (0-based dans l'ordre des « Background ») -> (numéro, titre = name_en ORPHA)
SECTIONS = {
    17: (1, "Congenital syphilis"),                        # ORPHA:499009
    19: (2, "Congenital toxoplasmosis"),                   # ORPHA:858
    22: (3, "Congenital herpes simplex virus infection"),  # ORPHA:293
    23: (4, "Congenital varicella syndrome"),              # ORPHA:291
    24: (5, "Fetal cytomegalovirus syndrome"),             # ORPHA:294
    25: (6, "Fetal parvovirus syndrome"),                  # ORPHA:295
    26: (7, "Congenital rubella syndrome"),                # ORPHA:290
}


def main():
    t = SRC.read_text(encoding="utf-8")
    idx = [m.start() for m in re.finditer(r"^Background$", t, re.M)] + [len(t)]
    OUT.mkdir(exist_ok=True)
    for i, (num, titre) in SECTIONS.items():
        bloc = t[idx[i]:idx[i + 1]]
        # la section suivante commence par son en-tête numéroté : on coupe avant
        bloc = re.split(r"\n9\.\d\.\d\.\d\s", bloc)[0].strip()
        slug = re.sub(r"[^a-z0-9]+", "_", titre.lower()).strip("_")
        f = OUT / f"ch{num:02d}_{slug}.txt"
        f.write_text(f"{num}\n\n{titre}\n\n{bloc}\n", encoding="utf-8")
        print(f"  {f.name:48} {len(bloc):6d} car.")

    # devneuro : les titres sont des lignes seules ; une section va jusqu'au titre suivant
    t2 = SRC2.read_text(encoding="utf-8")
    titres = list(SECTIONS_DEVNEURO) + FIN_DEVNEURO
    pos = {}
    for k in titres:
        m = re.search(r"^" + re.escape(k) + r"\s*$", t2, re.M)
        if m:
            pos[k] = m.start()
    ordre = sorted(pos.items(), key=lambda x: x[1])
    OUT2.mkdir(exist_ok=True)
    for i, (k, debut) in enumerate(ordre):
        if k not in SECTIONS_DEVNEURO:
            continue
        fin = ordre[i + 1][1] if i + 1 < len(ordre) else len(t2)
        num, titre = SECTIONS_DEVNEURO[k]
        bloc = t2[debut:fin].strip()
        slug = re.sub(r"[^a-z0-9]+", "_", titre.lower()).strip("_")
        f = OUT2 / f"ch{num:02d}_{slug}.txt"
        f.write_text(f"{num}\n\n{titre}\n\n{bloc}\n", encoding="utf-8")
        print(f"  {f.name:48} {len(bloc):6d} car.")


if __name__ == "__main__":
    main()
