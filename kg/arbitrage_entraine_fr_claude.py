#!/usr/bin/env python3
"""Arbitrage par Claude des phrases des livres FRANÇAIS (ancrer_sequences_fr.py), puis statut final des arêtes
en réunissant anglais (arbitrage_entraine_decide.tsv) et français. Mêmes codes : OUI / CO / NON.

    python kg/arbitrage_entraine_fr_claude.py -> kg/sorties/arbitrage_entraine_fr_decide.tsv + kg/sorties/entraine_statut.tsv
"""
import collections
import csv
from pathlib import Path

ICI = Path(__file__).resolve().parent
SRC = ICI / "sorties" / "arbitrage_entraine_fr.tsv"
OUT = ICI / "sorties" / "arbitrage_entraine_fr_decide.tsv"
EN = ICI / "sorties" / "arbitrage_entraine_decide.tsv"
STATUT = ICI / "sorties" / "entraine_statut.tsv"

D = {2: "OUI", 3: "OUI", 4: "NON", 5: "CO", 6: "CO", 7: "NON", 8: "CO", 9: "CO", 10: "OUI", 11: "OUI", 12: "OUI",
     13: "OUI", 14: "OUI", 15: "OUI", 16: "OUI", 17: "OUI", 18: "CO", 19: "NON", 20: "CO", 21: "NON", 22: "CO",
     23: "OUI", 24: "NON", 25: "CO", 26: "OUI", 27: "CO"}
NOTES = {4: "« mégavessie SANS obstacle urétral anatomique »", 7: "porte obstacle -> hydronéphrose/dysplasie, pas hydronéphrose -> dysplasie",
         10: "« immobilité fœtale se manifestant … par un tableau de ptérygia multiples »", 26: "« érythroblastose témoignant d'une hypoxie fœtale »",
         20: "description du tableau (« l'autre hypotrophique, anémique et en anamnios »)"}
# même phrase, autre arête (ligne source)
AJOUTS = [
    (2, "oligoamnios (Potter)", "dysplasie rénale (kystique)", "oligoamnios / anamnios", "OUI", "« reins kystiques ou hypoplasiques non fonctionnels »"),
    (2, "oligoamnios (Potter)", "obstacle urinaire bas (VUP, atrésie urétrale)", "oligoamnios / anamnios", "OUI", "« rétention d'urine (valve urétrale, mégavessie) »"),
    (2, "oligoamnios (Potter)", "rupture prématurée prolongée des membranes", "oligoamnios / anamnios", "OUI", "« fissure chronique de la poche des eaux »"),
    (14, "obstacle digestif haut", "atrésie de l'œsophage", "hydramnios / polyhydramnios", "OUI", "liste des causes d'hydramnios qui « gênent la déglutition »"),
    (7, "obstacle urinaire bas (NOUVELLE arête)", "obstacle urinaire bas (VUP, atrésie urétrale)", "hydronéphrose / urétérohydronéphrose", "OUI", "« à l'origine d'un retentissement constant … (hydronéphrose et/ou dysplasie rénale) »"),
    (7, "obstacle urinaire bas (prune belly)", "obstacle urinaire bas (VUP, atrésie urétrale)", "dysplasie rénale (kystique)", "OUI", "même phrase"),
    (9, "obstacle urinaire bas (NOUVELLE arête)", "obstacle urinaire bas (VUP, atrésie urétrale)", "déficit de la musculature abdominale (prune belly)", "OUI", "« une séquence prune belly peut s'observer dans les différents types d'obstruction urétrale »"),
]


def main():
    rows = list(csv.reader(SRC.open(), delimiter="\t"))
    tete, corps = rows[0], rows[1:]
    out = [tete + ["arbitre", "note"]]
    for i, r in enumerate(corps, start=2):
        r = r + [""] * (len(tete) - len(r)); r[11] = D[i]
        out.append(r + ["claude", NOTES.get(i, "")])
    for src, seq, cause, effet, dec, note in AJOUTS:
        r = list(corps[src - 2]) + [""] * 0; r[0], r[1], r[3], r[11] = seq, cause, effet, dec
        out.append(r + ["claude", note])
    csv.writer(OUT.open("w"), delimiter="\t", lineterminator="\n").writerows(out)
    # statut final, anglais + français
    tout = collections.OrderedDict()
    for f in (EN, OUT):
        for r in list(csv.reader(f.open(), delimiter="\t"))[1:]:
            k = (r[0].replace(" (NOUVELLE arête)", ""), r[1], r[3])
            e = tout.setdefault(k, {"dec": set(), "preuves": []})
            if r[11]:
                e["dec"].add(r[11])
            if r[11] == "OUI":
                e["preuves"].append(f"{r[5]} p.{r[7]}")
    lignes, n = [], collections.Counter()
    for (seq, a, b), e in tout.items():
        s = "causale" if "OUI" in e["dec"] else "association" if "CO" in e["dec"] else "non attestée"
        n[s] += 1
        lignes.append((seq, a, b, s, " ; ".join(dict.fromkeys(e["preuves"]))))
    csv.writer(STATUT.open("w"), delimiter="\t", lineterminator="\n").writerows([("sequence", "cause", "effet", "statut", "preuves_OUI")] + lignes)
    print(f"{len(tout)} arêtes (anglais + français) : " + ", ".join(f"{v} {k}" for k, v in n.items()) + f" -> {STATUT}")
    for l in lignes:
        if l[3] != "causale":
            print(f"  {l[3]:12s} {l[1]} → {l[2]}")


if __name__ == "__main__":
    main()
