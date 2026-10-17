#!/usr/bin/env python3
"""Arbitrage des arêtes « entraine » par Claude (2026-10-17, à la demande de Rémi), relisible et révocable.

Décision par phrase (numéro de ligne du TSV d'ancrage, en-tête = 1) :
  OUI  la phrase porte la causalité (results in, secondary to, leads to, « … sequence » nommée par le livre)
  CO   co-occurrence seulement : vaut pour une association, pas pour la cause
  NON  bibliographie, index, phrase hors sujet ou mal attribuée
Statut d'une arête : causale (≥ 1 OUI) / association (CO seulement) / non attestée.
Jugement de Claude, jamais une preuve : la preuve reste le verbatim du livre. Colonne arbitre = claude.

    python kg/arbitrage_entraine_claude.py      -> kg/sorties/arbitrage_entraine_decide.tsv + résumé par arête
"""
import collections
import csv
from pathlib import Path

ICI = Path(__file__).resolve().parent
SRC = ICI / "sorties" / "arbitrage_entraine.tsv"
OUT = ICI / "sorties" / "arbitrage_entraine_decide.tsv"

D = {
    2: "OUI", 3: "OUI", 4: "OUI", 5: "NON", 6: "NON", 7: "OUI", 8: "CO", 9: "NON", 10: "OUI", 11: "OUI", 12: "NON",
    13: "NON", 14: "CO", 15: "OUI", 16: "OUI", 17: "CO", 18: "CO", 19: "NON", 20: "CO", 21: "NON",
    23: "CO", 24: "OUI", 25: "OUI", 26: "CO", 27: "CO", 28: "NON", 29: "NON", 30: "OUI", 31: "NON", 32: "OUI",
    33: "NON", 34: "NON", 35: "OUI", 36: "CO", 37: "OUI", 38: "CO", 39: "CO", 40: "NON", 41: "CO", 42: "OUI",
    43: "CO", 44: "OUI", 45: "CO", 46: "CO", 47: "OUI", 48: "CO", 49: "OUI", 50: "OUI", 51: "OUI", 52: "CO",
    53: "OUI", 54: "CO", 55: "CO", 56: "OUI", 57: "OUI", 58: "OUI", 59: "CO", 60: "NON", 61: "OUI", 62: "CO",
    63: "CO", 64: "CO", 65: "NON", 66: "OUI", 68: "CO", 69: "OUI", 70: "OUI", 71: "CO", 72: "OUI", 73: "NON",
    75: "OUI", 76: "CO", 77: "CO", 78: "OUI", 79: "NON", 80: "NON", 81: "NON", 82: "NON", 83: "NON",
    84: "OUI", 85: "OUI", 86: "OUI", 87: "OUI", 88: "OUI", 89: "OUI", 90: "CO", 91: "CO", 92: "NON", 93: "OUI",
    94: "NON", 95: "CO", 96: "NON", 98: "OUI", 99: "NON", 100: "OUI", 101: "NON", 102: "NON", 103: "NON",
    104: "CO", 105: "NON", 106: "CO", 107: "OUI", 108: "OUI", 109: "CO", 110: "CO", 111: "NON", 112: "NON",
    113: "OUI", 114: "NON", 115: "CO", 116: "CO", 117: "OUI", 118: "CO", 119: "NON", 120: "NON", 121: "CO",
    122: "OUI", 123: "OUI", 124: "OUI", 125: "CO", 126: "CO", 127: "OUI", 128: "OUI", 129: "OUI", 130: "OUI",
    131: "NON", 132: "NON", 133: "NON", 134: "OUI", 135: "OUI", 136: "CO", 137: "NON", 138: "CO", 139: "NON",
    140: "OUI", 141: "CO", 142: "OUI", 143: "OUI", 144: "OUI", 145: "NON", 146: "NON", 147: "OUI", 148: "OUI",
    149: "CO",
}
NOTES = {
    13: "titre d'article en bibliographie", 3: "« renal agenesis or other causes of severe oligohydramnios »",
    40: "la phrase dit hydrops précoce -> ptérygiums (nouvelle arête), pas akinésie -> ptérygiums",
    113: "le livre dit les deux jumeaux", 116: "le livre déconseille le terme « placental insufficiency »",
    140: "« thought to be a precursor lesion » : certitude discutée", 143: "titre d'article (Stevenson 1986)",
    61: "titre d'article en bibliographie",
}
# phrases réattribuées à une autre arête (même verbatim, ligne source) ; nouvelle arête marquée
AJOUTS = [
    (58, "Pierre Robin", "glossoptose", "fente palatine (en U)", "OUI", "même phrase que la ligne 58 (« impairing the closure »)"),
    (66, "brides amniotiques", "rupture précoce de l'amnios", "brides amniotiques", "OUI", "« true bands from disruption of the amnionic sac »"),
    (63, "brides amniotiques", "brides amniotiques", "fentes faciales atypiques", "OUI", "le livre dit « amnion rupture sequence »"),
    (40, "anasarque précoce (NOUVELLE arête)", "anasarque fœto-placentaire", "ptérygiums", "OUI", "« early-onset (first-trimester) hydrops leads to the formation of pterygia »"),
]


def main():
    rows = list(csv.reader(SRC.open(), delimiter="\t"))
    tete, corps = rows[0], rows[1:]
    out = [tete + ["arbitre", "note"]]
    for i, r in enumerate(corps, start=2):
        r = r + [""] * (len(tete) - len(r))
        if r[9] == "AUCUNE PHRASE":
            out.append(r + ["", ""]); continue
        r[11] = D[i]
        out.append(r + ["claude", NOTES.get(i, "")])
    for src, seq, cause, effet, dec, note in AJOUTS:
        r = list(corps[src - 2]); r += [""] * (len(tete) - len(r))
        r[0], r[1], r[3], r[11] = seq, cause, effet, dec
        out.append(r + ["claude", note])
    csv.writer(OUT.open("w"), delimiter="\t", lineterminator="\n").writerows(out)
    statut = collections.OrderedDict()
    for r in out[1:]:
        k = (r[1], r[3])
        statut.setdefault(k, set()).add(r[11])
    n = collections.Counter()
    for (a, b), ds in statut.items():
        s = "causale" if "OUI" in ds else "association" if "CO" in ds else "non attestée"
        n[s] += 1
        if s != "causale":
            print(f"  {s:12s} {a} → {b}")
    print(f"{len(statut)} arêtes : " + ", ".join(f"{v} {k}" for k, v in n.items()) + f" -> {OUT}")


if __name__ == "__main__":
    main()
