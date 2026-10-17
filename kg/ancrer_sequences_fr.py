#!/usr/bin/env python3
"""Ancrage des arêtes « entraine » dans les livres FRANÇAIS (soffoet, lherminecoulomb), par le pont HPO.

Motifs d'un nœud = formes françaises d'HPO (libellé officiel NAME + synonymes EXACT : rappel large, la précision
vient de l'arbitrage) du terme HPO du nœud, plus un motif français écrit à la main quand HPO n'a pas le
concept (obstacle urinaire bas, surrénales en galette, épargne cérébrale…). Recherche sans accents ni casse.
Même règle que ancrer_sequences.py : phrase cause + effet (sinon fenêtre de 2), indice causal français en tête,
verbatim copié du chunk recollé, page imprimée.

    python kg/ancrer_sequences_fr.py   -> kg/sorties/arbitrage_entraine_fr.tsv
"""
import re
import sqlite3
import sys
import unicodedata
from pathlib import Path

import pysbd

ICI = Path(__file__).resolve().parent
sys.path.insert(0, str(ICI))
import sequences_canoniques as sc  # noqa: E402

RAG = Path.home() / "Bureau/Embedding_RAG_V2/rag_v2.db"
V1 = ICI.parent / "syndromes_foetaux.db"
OUT = ICI / "sorties" / "arbitrage_entraine_fr.tsv"
PAR_ARETE = 3

# nœud -> terme HPO (résolu par libellé anglais exact dans hpo_synonymes, 2026-10-17) ; absent = HPO n'a pas le concept
HPO = {
    "agenesie_renale": "HP:0000104", "dysplasie_renale": "HP:0000110", "rpm": "HP:0001788", "oligoamnios": "HP:0001562",
    "hypoplasie_pulm": "HP:0002089", "facies_potter": "HP:0002009", "deformations_membres": "HP:0001883",
    "megavessie": "HP:0000021", "hydronephrose": "HP:0000126", "cryptorchidie": "HP:0000028", "akinesie": "HP:0001989",
    "arthrogrypose": "HP:0002804", "pterygiums": "HP:0001040", "micrognathie": "HP:0000347", "hydramnios": "HP:0001561",
    "cordon_court": "HP:0001196", "rciu": "HP:0001511", "glossoptose": "HP:0000162", "fente_palatine": "HP:0000175",
    "brides": "HP:0009775", "hpe": "HP:0001360", "face_hpe": "HP:0009914", "anencephalie": "HP:0002323",
    "hypoplasie_surren": "HP:0000835", "myelomeningocele": "HP:0002475", "hydrocephalie": "HP:0000238",
    "anemie_foetale": "HP:0001903", "ic_haut_debit": "HP:0001635", "anasarque": "HP:0001789", "hem": "HP:0001978",
    "epanchement_pleural": "HP:0002202", "hygroma": "HP:0000476", "cou_palme": "HP:0000465", "hdc": "HP:0000776",
    "atresie_oeso": "HP:0002032", "atresie_duod": "HP:0002247", "diabete_maternel": "HP:0009800",
    "hyperinsulinisme": "HP:0004510", "macrosomie": "HP:0001520", "cardiomyopathie_hyp": "HP:0001639",
    "obstacle_gauche": "HP:0001650", "sirenomelie": "HP:0010497", "craniosynostose": "HP:0001363",
    "scaphocephalie": "HP:0030799",
}
# motifs français écrits à la main (sans accents, minuscules), ajoutés aux formes HPO
MAIN = {
    "obstacle_urinaire": r"valves? de l.uretre posterieur|obstacle (sous.vesical|uretral|sur les voies urinaires basses)|atresie uretrale|obstruction uretrale",
    "surrenales_discoides": r"surrenales? (discoides?|en galette|aplaties?|couchees?)",
    "deficit_paroi_abdo": r"prune.belly|(aplasie|hypoplasie|deficit|absence) (de la )?musculature abdominale|ventre (en )?pruneau",
    "deglutition": r"(defaut|absence|trouble|diminution)s? de (la )?deglutition|deglutition",
    "rupture_amnios": r"rupture (precoce )?(de l.)?amnios|rupture amniotique",
    "amputations": r"amputations?|sillons? de constriction|constrictions? (annulaires?|amniotiques?)",
    "fentes_atypiques": r"fentes? (faciales? )?(atypiques?|obliques?)",
    "chiari2": r"chiari",
    "stt_donneur": r"(jumeau )?(transfuseur|donneur)",
    "stt_receveur": r"(jumeau )?(transfuse|receveur)",
    "insuff_placentaire": r"insuffisance placentaire|malperfusion vasculaire maternelle|hypoperfusion placentaire|insuffisance utero.placentaire",
    "epargne_cerebrale": r"epargne cerebrale|rapport (poids )?cerveau.foie|cerveau.foie",
    "hypoxie_chronique": r"hypoxie",
    "erythroblastose": r"erythroblast|normoblast|hematies nucleees|globules rouges nuclees",
    "stress_foetal": r"stress",
    "involution_thymique": r"involution (aigue )?(thymique|du thymus)|ciel etoile",
    "hypoplasie_vg": r"hypoplasie du (coeur|ventricule) gauche|ventricule gauche hypoplasique|coeur gauche hypoplasique",
    "obstacle_gauche": r"stenose aortique|atresie aortique|obstacle (du coeur gauche|aortique)",
    "vol_vasculaire": r"vol vasculaire|artere vitelline",
    "ic_haut_debit": r"insuffisance cardiaque",
    "hem": r"(hematopoiese|erythropoiese|hematopoese) extra.?medullaire|hepato.?splenomegalie",
    "anasarque": r"anasarque|hydrops",
    "hydramnios": r"hydramnios|polyhydramnios",
    "oligoamnios": r"oligoamnios|anamnios|oligohydramnios",
}
CAUSAL = re.compile(r"\b(entrain\w*|responsable|secondaire\w*|consequence\w*|due? (a|aux)|dus (a|aux)|provoqu\w*|conduit\w*|"
                    r"aboutit|a l.origine|en raison|sequence|resulte\w*|caus\w*|lie[es]* a|induit\w*|explique\w*)\b")


def sa(s):
    return unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().lower()


def motifs():
    v1 = sqlite3.connect(f"file:{V1}?mode=ro", uri=True)
    formes = {}
    for k in sc.NOEUDS:
        fs = set()
        if k in HPO:
            fs |= {sa(f) for (f,) in v1.execute("SELECT forme FROM hpo_synonymes WHERE hpo_id=? AND langue='fr' "
                                                 "AND portee IN ('NAME','EXACT')", (HPO[k],)) if len(f) >= 5}
        parts = [re.escape(f) for f in sorted(fs, key=len, reverse=True)]
        if k in MAIN:
            parts.append(MAIN[k])
        if parts:
            formes[k] = re.compile(r"\b(" + "|".join(parts) + r")")
    return formes


def main():
    sc._check()
    mot = motifs()
    con = sqlite3.connect(f"file:{RAG}?mode=ro", uri=True)
    rows = con.execute("SELECT c.rowid, c.source_short, c.chapter_title, c.chunk_text, p.page_label, p.page_pdf "
                       "FROM chunk_meta c LEFT JOIN chunk_pages p USING(rowid) "
                       "WHERE c.source_type='book' AND c.language='fr'").fetchall()
    seg = pysbd.Segmenter(language="fr", clean=False)
    cache, lignes, bilan = {}, [], []
    for seq, a, b, cert in sc.ARETES:
        if a not in mot or b not in mot:
            bilan.append((seq, a, b, "motif manquant")); continue
        ma, mb = mot[a], mot[b]
        cand = []
        for rid, livre, chap, txt, pl, pp in rows:
            t = " ".join(re.sub(r"-\n(?=[a-zà-ÿ])", "", txt).split())
            ts = sa(t)
            if not (ma.search(ts) and mb.search(ts)):
                continue
            ph = cache.get(rid) or cache.setdefault(rid, seg.segment(t))
            for i, s in enumerate(ph):
                ss = sa(s)
                if ma.search(ss) and mb.search(ss):
                    cand.append((s, "phrase", livre, chap, pl, pp, t))
                elif i + 1 < len(ph):
                    s2 = sa(ph[i + 1])
                    if (ma.search(ss) and mb.search(s2)) or (mb.search(ss) and ma.search(s2)):
                        cand.append((s + ph[i + 1], "fenêtre", livre, chap, pl, pp, t))
        vus, garde = set(), []
        for s, gr, livre, chap, pl, pp, t in sorted(cand, key=lambda c: (c[1] != "phrase", not CAUSAL.search(sa(c[0])), len(c[0]))):
            cle = re.sub(r"\W", "", sa(s))[:80]
            if cle in vus or len(s) > 900:
                continue
            vus.add(cle)
            assert s.strip() in t, "verbatim non retrouvé"
            garde.append((s, gr, livre, chap, pl, pp))
            if len(garde) == PAR_ARETE:
                break
        bilan.append((seq, a, b, len(cand)))
        for s, gr, livre, chap, pl, pp in garde:
            lignes.append((seq, sc.NOEUDS[a][0], "→", sc.NOEUDS[b][0], cert, livre, chap or "", pl or (f"pdf {pp}" if pp else ""),
                           gr, " ".join(s.split()), "oui" if CAUSAL.search(sa(s)) else "", ""))
    OUT.parent.mkdir(exist_ok=True)
    tete = ("sequence", "cause", "", "effet", "certitude", "livre", "chapitre", "page", "grain", "verbatim", "indice_causal", "decision")
    OUT.write_text("\n".join("\t".join(map(str, l)) for l in [tete] + lignes) + "\n")
    avec = {(l[1], l[3]) for l in lignes}
    print(f"{len(sc.ARETES)} arêtes : {len(avec)} avec phrase dans les livres français, "
          f"{len({(l[1], l[3]) for l in lignes if l[10]})} avec indice causal -> {OUT}")
    for x in bilan:
        if x[3] == "motif manquant":
            print("  motif manquant :", sc.NOEUDS[x[1]][0], "→", sc.NOEUDS[x[2]][0])


if __name__ == "__main__":
    main()
