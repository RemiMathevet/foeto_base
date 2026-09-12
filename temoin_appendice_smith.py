#!/usr/bin/env python3
"""Temoin de la matrice attestee : l'appendice de Smith « Pattern of Malformation
Differential Diagnosis by Anomalies » (26 listes, ch317-ch342), ecrit par le livre
lui-meme depuis ses propres entrees. Si la matrice syndrome_hpo_livres ne retrouve
pas ces listes, une attestation manque quelque part (5346afe04b4f).

Pour chaque (anomalie, syndrome, frequent|occasionnel) de l'appendice :
  anomalie -> HPO par hpo_synonymes (NAME/EXACT/NARROW anglais), sinon non testable
  syndrome -> entree Smith par le titre (« Acrocallosal S. » = « Acrocallosal Syndrome »)
  retrouve = un signe atteste du syndrome (foetal, est_parent=0) est l'HPO ou un
             descendant (hpo_ancestors) ; sinon « manque »
Table temoin_appendice_smith + rappel par liste. Un manque n'est pas forcement une
erreur d'extraction : le filtre foetal ecarte les signes postnataux, et l'appendice
inclut des traits (surdite, retard) que la vue exclut.

Usage : python3 temoin_appendice_smith.py
"""
import re
import sqlite3
import unicodedata
from collections import defaultdict
from pathlib import Path

DB = "/home/mathevet/Bureau/foeto_base/syndromes_foetaux.db"
APP = sorted(Path("/home/mathevet/Bureau/Embedding_RAG_V2/chapitres/smith").glob("ch3[1-4][0-9]_appendix*.txt"))
FIN = re.compile(r"(\bS\.|Syndrome|Sequence|Association|Dysplasia|Spectrum|Complex|Disease|Anomaly|Syndromes|Deficiency|Embryopathy|Dystrophy|Dysostosis|Type [IVX\d]+|\d+p\d*|\d+q\d*|Trisomy \d+|Mosaicism|\))\s*$")


def norm(s):
    s = "".join(ch for ch in unicodedata.normalize("NFD", (s or "").lower()) if unicodedata.category(ch) != "Mn")
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9\s]", " ", s)).strip()


def parse():
    """(liste, anomalie, niveau, nom) depuis les 26 fichiers"""
    out = []
    for f in APP:
        liste = re.sub(r"^ch\d+_appendix_\d+_", "", f.stem).replace("_", " ")
        lines = [l.strip() for l in f.read_text(encoding="utf-8").split("\n")]
        anomalie, niveau, buf = None, None, ""
        prev = []
        for l in lines:
            if not l or re.fullmatch(r"\d+", l) or l.startswith("APPENDIX") or l.startswith("Appendix") or "Pattern of Malformation" in l:
                continue
            if l in ("Frequent in", "Occasional in"):
                if l == "Frequent in" or (anomalie is None and prev):
                    # l'anomalie = la ligne juste avant, debarrassee de ce que la mise en
                    # page y colle : queue de la liste precedente (« Zellweger S. (Brushfield
                    # spots) 290 Glaucoma »), en-tete de section (« 20. Abdominal »), filigrane
                    anomalie = prev[-1] if prev else None
                    if anomalie:
                        anomalie = re.sub(r"VRG Release\s*:\s*\S+\s*", "", anomalie)
                        anomalie = re.sub(r"^\d+\.\s+", "", anomalie)
                        if re.search(r"\bS\.", anomalie):
                            anomalie = anomalie[anomalie.rfind("S.") + 2:]
                        anomalie = re.sub(r"^[\s,;]*(and [A-Z][a-z]+/|\([^)]*\)|\d+|/)\s*", "", anomalie).strip(" ,;/")
                niveau = "frequent" if l == "Frequent in" else "occasionnel"
                buf = ""; prev = []
                continue
            if niveau and anomalie:
                buf = (buf + " " + l).strip()
                if FIN.search(buf) or (buf.endswith("S.") or len(buf) > 60):
                    out.append((liste, anomalie, niveau, buf)); buf = ""
                    continue
            prev.append(l)
            if len(prev) > 6:
                prev = prev[-6:]
            # une ligne sans terminateur qui suit une liste : c'est un nouveau titre d'anomalie
            if niveau and anomalie and not buf and not FIN.search(l):
                pass
    return out


def main():
    c = sqlite3.connect(DB)
    syn = defaultdict(set)
    for h, f in c.execute("select hpo_id, forme from hpo_synonymes where langue='en' and portee in ('NAME','EXACT','NARROW')"):
        syn[norm(f)].add(h)
    anc = defaultdict(set)
    for h, a in c.execute("select hpo_id, ancestor_id from hpo_ancestors"):
        anc[h].add(a)
    direct = defaultdict(set)
    for t, h in c.execute("select syndrome_titre, hpo_id from v_syndrome_hpo_livres_foetal where est_parent=0 and livre='smith'"):
        direct[t].add(h)
    ferm = {t: set().union(*(anc[h] | {h} for h in hs)) for t, hs in direct.items()}
    idx = {}
    for t in direct:
        base = re.sub(r"^[A-W] ", "", t)
        for v in [base, re.sub(r"\(.*?\)", "", base)] + re.findall(r"\(([^)]+)\)", base):
            for x in re.split(r"[,;/]", v):
                k = norm(x)
                if len(k) >= 5:
                    idx.setdefault(k, t)
    def resoudre(nom):
        n = norm(re.sub(r"\bS\.", "Syndrome", nom).replace("(variable)", ""))
        n = re.sub(r"\s+syndrome$", " syndrome", n)
        for cand in (n, n.replace(" syndrome", ""), n + " syndrome", n.replace(" syndrome", "") + " sequence"):
            if cand in idx:
                return idx[cand]
        return None
    def hpo_de(anomalie):
        """forme exacte, puis suffixes de plus en plus courts (>= 2 mots) : « Microcephalic
        Primordial Dandy-Walker Malformation » -> « Dandy-Walker Malformation »"""
        mots = norm(anomalie).split()
        for i in range(len(mots)):
            cand = " ".join(mots[i:])
            if (len(mots) - i >= 2 or len(mots) == 1) and cand in syn:
                return sorted(syn[cand])[0]
        a = norm(anomalie)
        for k, v in syn.items():          # « Hypotonicity » ~ « hypotonia » : radical
            if len(a) > 6 and (k.startswith(a[:-3]) and len(k) - len(a) <= 3):
                return sorted(v)[0]
        return None

    entries = parse()
    c.execute("drop table if exists temoin_appendice_smith")
    c.execute("""create table temoin_appendice_smith (liste text, anomalie text, hpo_id text, niveau text,
                 syndrome_appendice text, syndrome_titre text, retrouve integer)""")
    stats = defaultdict(lambda: [0, 0, 0, 0])   # liste -> [testables, retrouves, sans_hpo, sans_syndrome]
    for liste, anomalie, niveau, nom in entries:
        h, t = hpo_de(anomalie), resoudre(nom)
        ok = None
        if h and t:
            ok = int(any(h in anc[x] or h == x for x in direct[t]))
            stats[liste][0] += 1; stats[liste][1] += ok
        else:
            stats[liste][2 if not h else 3] += 1
        c.execute("insert into temoin_appendice_smith values(?,?,?,?,?,?,?)", (liste, anomalie, h, niveau, nom, t, ok))
    c.commit()
    tot = [sum(s[i] for s in stats.values()) for i in range(4)]
    print(f"{len(entries)} paires (anomalie, syndrome) lues ; testables {tot[0]} — retrouvées {tot[1]} "
          f"({100*tot[1]/max(tot[0],1):.0f} %) ; anomalie sans HPO {tot[2]} ; syndrome non résolu {tot[3]}")
    for liste, s in sorted(stats.items(), key=lambda x: -x[1][0]):
        if s[0]:
            print(f"  {liste[:38]:38s} {s[1]:4d}/{s[0]:<4d} {100*s[1]/s[0]:3.0f} %   (sans HPO {s[2]}, non résolus {s[3]})")
    for niv, k, r in c.execute("select niveau, count(*), sum(retrouve) from temoin_appendice_smith where retrouve is not null group by 1"):
        print(f"  {niv}: {r}/{k} ({100*r/k:.0f} %)")


if __name__ == "__main__":
    main()
