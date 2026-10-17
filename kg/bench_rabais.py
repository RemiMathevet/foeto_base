#!/usr/bin/env python3
"""Banc du rabais par séquence de Foekinator (plan 349d336f5197, kg.db 2379aee4d0e5).

Réplique fidèle du moteur bayésien de foetodata_hub/templates/akinator.html (prior, pénétrance par défaut 0,01,
hiérarchie HPO jusqu'à 3 pas avec décroissance [1 ; 0,75 ; 0,5 ; 0,3], absents en correspondance directe), sur
l'export servi par le hub (/api/akinator/export), et les vignettes du banc (foeto_bench.db, gold_orpha).
Signes présents/absents = HPOExtractor (comme la matrice de convergence).

Rabais : un signe présent est SECONDAIRE si un autre signe présent est sa cause par une chaîne « entraine » de
kg.db (nœuds seq -> HPO ; un signe vaut le nœud HPO s'il l'est ou en descend de ≤ 2 pas). Variantes :
  base      aucun rabais
  paire_w   log-vraisemblance d'un signe secondaire multipliée par w (0,5 ; 0)
  groupe    une composante (cause + ses effets présents) compte une fois : max des log-pénétrances du groupe
Mesures : rang du gold ; top-1/5/10, MRR ; écart à base en pairé, IC 95 % par bootstrap (2000 tirages),
sur tous les cas et sur les cas où le rabais s'applique.

    python kg/bench_rabais.py [--mode orphanet|livres]
"""
import argparse
import collections
import json
import os
import sqlite3
import sys
import urllib.request
from pathlib import Path

import numpy as np

ICI = Path(__file__).resolve().parent
sys.path.insert(0, str(ICI.parent))
from hpo_extractor import HPOExtractor  # noqa: E402

HUB = os.environ.get("FOEKINATOR_HUB", "http://127.0.0.1:5010")
BENCH = Path(os.environ.get("BENCH_DB", Path.home() / "Bureau/benchmark_foeto/foeto_bench.db"))
KG = ICI / "kg.db"
DEFAULT_PEN, MAX_D, DECAY = 0.01, 3, [1.0, 0.75, 0.5, 0.3]


def charger(mode):
    with urllib.request.urlopen(f"{HUB}/api/akinator/export?prob_mode={mode}", timeout=300) as r:
        return json.load(r)


def paires_sequences():
    """{effet HPO: {causes HPO}} par fermeture transitive des arêtes entraine de kg.db."""
    c = sqlite3.connect(f"file:{KG}?mode=ro", uri=True)
    hpo = dict(c.execute("SELECT src, dst FROM arete WHERE rel='same_as' AND src LIKE 'SEQ:%'"))
    succ = collections.defaultdict(set)
    for a, b in c.execute("SELECT src, dst FROM arete WHERE rel='entraine'"):
        succ[a].add(b)
    causes = collections.defaultdict(set)
    for a in list(succ):
        pile, vus = [a], set()
        while pile:
            for b in succ[pile.pop()]:
                if b not in vus:
                    vus.add(b); pile.append(b)
        for b in vus:
            if a in hpo and b in hpo and hpo[a] != hpo[b]:
                causes[hpo[b]].add(hpo[a])
    return causes


class Moteur:
    def __init__(self, data):
        self.parents = data["hpo_parents"]
        self.enfants = collections.defaultdict(list)
        for c, ps in self.parents.items():
            for p in ps:
                self.enfants[p].append(c)
        dis = data["diseases"]
        self.ids = [d["disease_id"] for d in dis]
        self.n = len(dis)
        prev = np.array([d.get("prevalence") or 0.001 for d in dis])
        self.prior = np.log(prev / prev.sum())
        self.inv = collections.defaultdict(list)          # hpo -> [(indice maladie, pénétrance)]
        for i, d in enumerate(dis):
            for p in d["phenotypes"]:
                self.inv[p["hpo_id"]].append((i, p["penetrance"]))
        self._pen = {}
        # matrice creuse maladies × HPO (pénétrances) : la meilleure pénétrance hiérarchique se lit par colonnes
        from scipy import sparse
        self.col = {h: j for j, h in enumerate(self.inv)}
        r, c, v = zip(*[(i, self.col[h], p) for h, lst in self.inv.items() for i, p in lst])
        self.P = sparse.csc_matrix((v, (r, c)), shape=(self.n, len(self.col)))

    def ancetres(self, h, k=2):
        out, front = {h}, [h]
        for _ in range(k):
            front = [p for x in front for p in self.parents.get(x, [])]
            out.update(front)
        return out

    def atteignables(self, h):
        """Même parcours que _getReachable : montée ≤ 3, puis descente dans chaque sous-arbre (total ≤ 3)."""
        r, anc, front, vu = {h: 0}, [(h, 0)], [h], {h}
        for d in range(1, MAX_D + 1):
            nxt = []
            for x in front:
                for p in self.parents.get(x, []):
                    if p not in vu:
                        vu.add(p); nxt.append(p); anc.append((p, d))
                        if r.get(p, 99) > d:
                            r[p] = d
            front = nxt
            if not nxt:
                break
        for a, du in anc:
            front, vd = [a], {a}
            for dd in range(1, MAX_D - du + 1):
                nxt = []
                for x in front:
                    for ch in self.enfants.get(x, []):
                        if ch not in vd:
                            vd.add(ch); nxt.append(ch)
                            if r.get(ch, 99) > du + dd:
                                r[ch] = du + dd
                front = nxt
                if not nxt:
                    break
        return r

    def logpen_present(self, h):
        """log de la pénétrance effective (directe, sinon meilleure hiérarchique décrue), vecteur par maladie."""
        if h in self._pen:
            return self._pen[h]
        best = np.zeros(self.n)
        par_d = collections.defaultdict(list)
        for x, d in self.atteignables(h).items():
            if d and x in self.col:
                par_d[d].append(self.col[x])
        for d, cols in par_d.items():
            best = np.maximum(best, self.P[:, cols].max(axis=1).toarray().ravel() * DECAY[d])
        best = np.where(best > DEFAULT_PEN, best, DEFAULT_PEN)
        for i, p in self.inv.get(h, ()):
            best[i] = p                                    # direct prioritaire, comme _effectivePen
        self._pen[h] = np.log(np.maximum(best, 1e-6))
        return self._pen[h]

    def log1pen_absent(self, h):
        v = np.full(self.n, np.log(1 - DEFAULT_PEN))
        for i, p in self.inv.get(h, ()):
            v[i] = np.log(1 - min(p, 1 - 1e-6))
        return v

    def secondaires(self, present, causes):
        """{signe secondaire: cause présente} selon les chaînes entraine."""
        vaut = {h: self.ancetres(h) for h in present}
        out = {}
        for s in present:
            for t in present:
                if t != s and any(c in vaut[t] for e in vaut[s] for c in causes.get(e, ())):
                    out[s] = t
                    break
        return out

    def rang(self, present, absent, gold, variante, causes):
        ll = self.prior.copy()
        sec = self.secondaires(present, causes) if variante != "base" else {}
        if variante == "groupe" and sec:
            # composantes : chaque secondaire rattaché à sa cause, récursivement jusqu'à une racine
            def racine(h):
                vus = set()
                while h in sec and h not in vus:
                    vus.add(h); h = sec[h]
                return h
            groupes = collections.defaultdict(list)
            for h in present:
                groupes[racine(h)].append(h)
            for g in groupes.values():
                ll += np.max(np.stack([self.logpen_present(h) for h in g]), axis=0)
        else:
            w = {"base": 1.0, "paire_0.5": 0.5, "paire_0": 0.0, "groupe": 1.0}[variante]
            for h in present:
                ll += (w if h in sec else 1.0) * self.logpen_present(h)
        for h in absent:
            ll += self.log1pen_absent(h)
        if gold not in self.idx:
            return None, bool(sec)
        g = ll[self.idx[gold]]
        return int((ll > g).sum()) + 1, bool(sec)


def _extraire(a):
    cid, txt = a
    m = _EX.extract(txt, min_confidence=0.6)
    pres = sorted({x.hpo_id for x in m if not x.negated})
    return cid, (pres, sorted({x.hpo_id for x in m if x.negated} - set(pres)))


def _init():
    global _EX
    _EX = HPOExtractor()


def extractions(cas):
    """Signes présents/absents par vignette : HPOExtractor (~1 à 10 s par vignette), en parallèle, mis en cache.
    Le cache est invalidé si la liste des vignettes change."""
    f = ICI / "sorties" / "extractions_bench.json"
    cle = sorted(c[0] for c in cas)
    if f.exists():
        d = json.loads(f.read_text())
        if d.get("cle") == cle:
            return {k: tuple(v) for k, v in d["ext"].items()}
    from multiprocessing import Pool
    with Pool(12, initializer=_init) as p:
        ext = dict(p.imap_unordered(_extraire, [(c[0], c[1]) for c in cas], chunksize=4))
    f.write_text(json.dumps({"cle": cle, "ext": ext}))
    return ext


def boot(diff, n=2000, rng=np.random.default_rng(0)):
    if not len(diff):
        return (float("nan"),) * 3
    m = rng.choice(diff, (n, len(diff))).mean(1)
    return float(np.mean(diff)), float(np.percentile(m, 2.5)), float(np.percentile(m, 97.5))


def main():
    a = argparse.ArgumentParser()
    a.add_argument("--mode", default="orphanet")
    a = a.parse_args()
    data = charger(a.mode)
    mo = Moteur(data)
    mo.idx = {d: i for i, d in enumerate(mo.ids)}
    causes = paires_sequences()
    con = sqlite3.connect(f"file:{BENCH}?mode=ro", uri=True)
    cas = con.execute("SELECT id, clinical_text, gold_orpha FROM cases WHERE is_truncated=0 AND gold_orpha LIKE 'ORPHA:%'").fetchall()
    ext = extractions(cas)
    VAR = ["base", "paire_0.5", "paire_0", "groupe"]
    res = {v: [] for v in VAR}
    touche = []
    for cid, txt, gold in cas:
        pres, abs_ = ext[cid]
        if not pres or gold not in mo.idx:
            continue
        for v in VAR:
            r, s = mo.rang(pres, abs_, gold, v, causes)
            res[v].append(r)
        touche.append(s)
    touche = np.array(touche)
    R = {v: np.array(res[v], float) for v in VAR}
    lignes = [f"Foekinator mode {a.mode} : {len(R['base'])} vignettes évaluables (gold dans l'export, ≥ 1 signe), "
              f"rabais actif sur {int(touche.sum())}"]
    for v in VAR:
        r = R[v]
        lignes.append(f"  {v:10s} top1 {np.mean(r <= 1):.3f}  top5 {np.mean(r <= 5):.3f}  top10 {np.mean(r <= 10):.3f}  MRR {np.mean(1 / r):.4f}")
    for v in VAR[1:]:
        for nom, msk in (("tous", np.ones(len(touche), bool)), ("touchés", touche)):
            d_mrr = boot(1 / R[v][msk] - 1 / R["base"][msk])
            d_t10 = boot((R[v][msk] <= 10).astype(float) - (R["base"][msk] <= 10))
            lignes.append(f"  {v:10s} vs base ({nom:7s}, n={int(msk.sum())}) : ΔMRR {d_mrr[0]:+.4f} [{d_mrr[1]:+.4f} ; {d_mrr[2]:+.4f}]"
                          f"   Δtop10 {d_t10[0]:+.3f} [{d_t10[1]:+.3f} ; {d_t10[2]:+.3f}]")
    out = ICI / "sorties" / f"bench_rabais_{a.mode}.txt"
    out.write_text("\n".join(lignes) + "\n")
    print("\n".join(lignes))


if __name__ == "__main__":
    main()
