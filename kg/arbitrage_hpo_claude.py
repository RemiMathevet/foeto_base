#!/usr/bin/env python3
"""Arbitrage FOETO v2 ↔ HPO par Claude (2026-10-17, à la demande de Rémi), relisible et révocable.

Décision par ligne du TSV de correspondance (en-tête = 1) :
  SAME  même concept          FIN  le signe FOETO est plus fin que le terme HPO (HPO plus large)
  LARGE le signe FOETO est plus large (composite, « A ou B »)          NON  pas de correspondance
Un diagnostic (syndrome) n'est jamais SAME d'un signe HPO qui n'en est qu'un trait : NON.
Colonne arbitre = claude ; rien n'est écrit dans foeto_v2.db ici.

    python kg/arbitrage_hpo_claude.py  -> kg/sorties/arbitrage_foeto2_hpo_decide.tsv
"""
import collections
import csv
from pathlib import Path

ICI = Path(__file__).resolve().parent
SRC = ICI / "sorties" / "arbitrage_foeto2_hpo.tsv"
OUT = ICI / "sorties" / "arbitrage_foeto2_hpo_decide.tsv"

S, F, L, N = "SAME", "FIN", "LARGE", "NON"
D = {
    4: S, 5: S, 9: F, 11: F, 13: N, 14: N, 15: F, 17: N, 20: N, 35: S, 36: S, 37: S, 38: S, 39: S, 40: S, 41: S,
    42: S, 43: F, 44: S, 45: S, 46: S, 47: S, 49: S, 50: F, 51: S, 52: S, 53: N, 59: L, 61: S, 64: S,
    65: N, 70: N, 71: S, 74: S, 77: N, 85: N, 90: F, 92: F, 95: F, 105: N, 107: F, 109: F, 112: N, 117: F, 119: N,
    120: F, 121: F, 122: N, 123: N, 130: S, 131: S, 132: N, 133: S, 135: S, 136: S, 138: S, 148: N, 150: S, 151: F,
    152: S, 153: F, 154: N, 162: S, 174: F, 183: L, 184: L, 188: F, 191: F, 192: S, 193: S, 194: S, 205: N, 206: N,
    217: S, 218: S, 221: F, 224: F, 245: F, 251: F, 252: F, 261: S, 262: S, 263: F, 267: F, 268: L, 269: L, 270: S,
    271: L, 272: F, 289: N, 290: N, 291: N, 303: F, 306: S, 310: S, 316: F, 317: N, 322: S, 334: S, 341: N, 343: S,
    344: S, 349: N, 350: F, 351: S, 354: S, 360: S, 373: F, 375: S, 376: S, 379: F, 381: F, 382: S, 383: N, 384: N,
    385: S, 390: S, 396: S, 397: S, 400: F, 402: S, 404: N, 406: L, 407: L, 409: N, 418: S, 422: N, 428: S, 434: N,
    435: S, 437: S, 439: F, 442: S, 444: F, 446: F, 463: F, 469: F, 475: S, 481: S, 482: N, 494: N, 495: S, 496: S,
    498: S, 499: S, 500: L, 501: L, 502: S, 503: S, 505: S,
    506: S, 507: S, 508: S, 509: S, 515: S, 516: N, 517: F, 518: S, 520: S, 528: N, 529: L, 530: L, 533: S, 544: L,
    546: S, 552: F, 553: S, 555: S, 562: S, 565: F, 570: L, 573: S, 579: N, 581: S, 593: S, 594: S, 596: S, 606: S,
    607: F, 608: S, 609: S, 618: S, 628: L, 632: N, 633: S, 637: F, 638: F, 640: S, 641: S, 648: S, 649: S, 671: S,
    673: N, 686: N, 689: S, 697: S, 698: S, 702: S, 711: S, 724: L, 725: L, 727: S, 728: S, 730: N, 734: F, 738: N,
    744: F, 749: S, 750: F, 753: F, 755: F, 756: F, 757: N, 760: S, 762: N, 764: S, 772: N, 773: S, 782: S, 783: F,
    784: F, 785: S, 791: S, 795: S, 798: S, 800: F, 801: S, 812: S, 813: N, 821: S, 823: S, 824: L, 825: S, 831: S,
    832: S, 846: N, 853: S, 857: S, 862: F, 867: F, 868: N, 871: N, 878: L, 879: S, 886: N, 892: S, 893: F, 895: F,
    896: F, 897: F, 902: S, 922: S, 925: S, 931: F, 936: S, 949: S, 951: L, 965: S, 970: S, 973: F, 977: S, 978: F,
    981: S, 982: S, 990: F, 993: S, 994: N, 996: S, 1001: S, 1008: S, 1013: N, 1014: N, 1015: N, 1017: S, 1018: S,
    1019: S, 1020: F,
}
NOTES = {
    13: "« Tall stature » : inclusion sur « grande taille »", 383: "« Short stature » : même piège", 42: "type I = lissencéphalie classique à 4 couches : HP:0006818 plus juste que HP:0001339 posé",
    43: "HP:0001339 (Lissencephaly) plus large que le type I", 188: "HP:0002595 Necrotizing enterocolitis serait SAME (absent des candidats)",
    349: "HP:0008799 Paucity of interlobular bile ducts serait SAME", 434: "HP:0000610 Chorioretinal coloboma plus juste",
    753: "HP:0100611 Multiple glomerular cysts serait plus juste", 762: "négation perdue par le canal sémantique",
    886: "surrénale en galette de poids NORMAL ≠ hypoplasie", 868: "maturation, pas hyperplasie", 686: "emphysème interstitiel ≠ emphysème destructif",
    148: "rhabdomyome ≠ myxome", 375: "true hermaphroditism = DSD ovotesticulaire : les deux HPO conviennent",
    9: "gray matter heterotopia ; HPO a des sous-types (nodulaire périventriculaire)", 205: "hétérotopie digestive ≠ hétérotopie de substance grise",
    206: "idem", 579: "idem", 730: "idem", 772: "rénine tissulaire (IHC) ≠ rénine circulante",
}


def main():
    rows = list(csv.reader(SRC.open(), delimiter="\t"))
    out = [rows[0] + ["arbitre", "note"]]
    manq = []
    for i, r in enumerate(rows[1:], start=2):
        r = r + [""] * (len(rows[0]) - len(r))
        if not r[5]:
            out.append(r + ["", ""]); continue
        if i not in D:
            manq.append(i); out.append(r + ["", ""]); continue
        r[11] = D[i]
        out.append(r + ["claude", NOTES.get(i, "")])
    assert not manq, f"lignes non arbitrées : {manq}"
    csv.writer(OUT.open("w"), delimiter="\t", lineterminator="\n").writerows(out)
    c = collections.Counter(r[11] for r in out[1:] if r[12] == "claude")
    par_canal = collections.defaultdict(collections.Counter)
    for r in out[1:]:
        if r[12] == "claude":
            par_canal[r[8]][r[11]] += 1
    signes = {r[0] for r in out[1:] if r[11] in (S, F, L)}
    print(f"{sum(c.values())} propositions arbitrées : {dict(c)} ; {len(signes)} signes reliés à HPO -> {OUT}")
    for k, v in sorted(par_canal.items(), key=lambda x: -sum(x[1].values())):
        print(f"  {k:28s} {dict(v)}")


if __name__ == "__main__":
    main()
