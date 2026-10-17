#!/usr/bin/env python3
"""kg.db — graphe de connaissances fœtopathologique, reconstruit de zéro à chaque passage (plan 2d27053f987e,
349d336f5197, 41cf0f8da02c). Jamais édité à la main : on corrige les sources ou les arbitrages, puis on relance.

Nœuds (noeud.type) : foeto2 (signes FOETO v2, sous-type CON/DIA/NOR/QUA/MES/AXE), foeto1 (terme v1 figé, gardé
seulement s'il porte un lien de livre sans équivalent v2 exact ; correspond_partiellement -> foeto2), hpo, syndrome (entité ORPHA/OMIM/NOM
des livres), famille, seq (nœuds des séquences canoniques).
Arêtes (arete.rel) et leur origine :
  est_un            hpo -> hpo parent direct                              hp.obo (hpo_ancestors, distance 1)
  same_as / plus_fin_que / plus_large_que   foeto2 -> hpo                 arbitrage FOETO v2 ↔ HPO (kg/sorties)
  same_as           seq -> hpo                                            terme HPO du nœud (ancrer_sequences_fr.HPO)
  critere, constant, exclut, mime, oriente, associe…  foeto2 -> foeto2    liens des fiches (foeto_v2.liens)
  signe_de          hpo -> syndrome (fréquence, niveau, modalité)         syndrome_hpo_livres (verbatim de livre)
  signe_de          foeto2 -> syndrome                                    syndrome_foeto_livres, terme v1 -> v2 EXACT
  diagnostic_de     foeto2 (DIA) -> syndrome                              foeto_dia_orpha, terme v1 -> v2 EXACT
  membre_de         syndrome -> famille                                   syndrome_family_members
  entraine          seq -> seq (statut causale)                           séquences arbitrées, phrase OUI
  associe_seq       seq -- seq (co-occurrence seulement)                  séquences arbitrées, phrase CO
Preuves : preuve(arete_id, livre, chapitre, page, verbatim) ; preuve_noeud pour les verbatims des signes v2.
Contrôle au build : aucun cycle sur est_un ∪ entraine (nœuds seq contractés sur leur HPO) ; le build échoue sinon.
Rapport de différences avec le build précédent (comptes par relation) : kg/sorties/kg_diff.txt

    python kg/build_kg.py
"""
import collections
import csv
import json
import sqlite3
import sys
import time
from pathlib import Path

ICI = Path(__file__).resolve().parent
B = ICI.parent
sys.path.insert(0, str(ICI))
import ancrer_sequences_fr as asf  # noqa: E402
import sequences_canoniques as sc  # noqa: E402

V2, V1 = B / "foeto_v2.db", B / "syndromes_foetaux.db"
KG = ICI / "kg.db"
S = ICI / "sorties"
SCHEMA = """
CREATE TABLE noeud (id TEXT PRIMARY KEY, type TEXT NOT NULL, sous_type TEXT, label_fr TEXT, label_en TEXT, organe TEXT, source TEXT);
CREATE TABLE arete (id INTEGER PRIMARY KEY, src TEXT NOT NULL, rel TEXT NOT NULL, dst TEXT NOT NULL, statut TEXT,
                    qualifs TEXT, origine TEXT NOT NULL, UNIQUE(src, rel, dst, origine));
CREATE TABLE preuve (arete_id INTEGER NOT NULL REFERENCES arete(id), livre TEXT, chapitre TEXT, page TEXT, verbatim TEXT NOT NULL);
CREATE TABLE preuve_noeud (noeud_id TEXT NOT NULL REFERENCES noeud(id), livre TEXT, verbatim TEXT NOT NULL, fiche TEXT);
CREATE TABLE meta (cle TEXT PRIMARY KEY, valeur TEXT);
CREATE INDEX i_arete_src ON arete(src, rel); CREATE INDEX i_arete_dst ON arete(dst, rel); CREATE INDEX i_preuve ON preuve(arete_id);
"""


class G:
    def __init__(self, con):
        self.c, self.ids = con, {}

    def noeud(self, *v):
        self.c.execute("INSERT OR IGNORE INTO noeud VALUES (?,?,?,?,?,?,?)", v)

    def arete(self, src, rel, dst, origine, statut=None, qualifs=None, preuves=()):
        k = (src, rel, dst, origine)
        if k not in self.ids:
            cur = self.c.execute("INSERT INTO arete (src, rel, dst, statut, qualifs, origine) VALUES (?,?,?,?,?,?)",
                                 (src, rel, dst, statut, json.dumps(qualifs, ensure_ascii=False) if qualifs else None, origine))
            self.ids[k] = cur.lastrowid
        for p in preuves:
            self.c.execute("INSERT INTO preuve VALUES (?,?,?,?,?)", (self.ids[k], *p))
        return self.ids[k]


def tsv(f):
    rows = list(csv.reader(f.open(), delimiter="\t"))
    return [dict(zip(rows[0], r)) for r in rows[1:]]


def acyclique(c):
    """Kahn sur est_un ∪ entraine ; un nœud seq ayant un same_as HPO est remplacé par ce HPO."""
    alias = dict(c.execute("SELECT src, dst FROM arete WHERE rel='same_as' AND src LIKE 'SEQ:%'"))
    succ, deg = collections.defaultdict(set), collections.Counter()
    for a, b in c.execute("SELECT src, dst FROM arete WHERE rel IN ('est_un','entraine')"):
        a, b = alias.get(a, a), alias.get(b, b)
        if a != b and b not in succ[a]:
            succ[a].add(b); deg[b] += 1; deg[a] += 0
    file = [n for n in deg if deg[n] == 0]
    vus = 0
    while file:
        n = file.pop(); vus += 1
        for v in succ[n]:
            deg[v] -= 1
            if deg[v] == 0:
                file.append(v)
    reste = [n for n in deg if deg[n] > 0]
    return not reste, reste[:20]


def main():
    ancien = {}
    if KG.exists():
        o = sqlite3.connect(KG)
        ancien = dict(o.execute("SELECT rel || ' / ' || origine, count(*) FROM arete GROUP BY 1"))
        o.close()
    tmp = KG.with_suffix(".tmp.db")
    tmp.unlink(missing_ok=True)
    c = sqlite3.connect(tmp)
    c.executescript(SCHEMA)
    g = G(c)
    v2 = sqlite3.connect(f"file:{V2}?mode=ro", uri=True)
    v1 = sqlite3.connect(f"file:{V1}?mode=ro", uri=True)
    v1v2 = dict(v2.execute("SELECT v1_id, v2_id FROM correspondance_v1 WHERE qualite='exacte'"))

    # HPO : nœuds + est_un (parent direct)
    for h, en, fr in v1.execute("SELECT hpo_id, label_en, label_fr FROM hpo_terms"):
        g.noeud(h, "hpo", None, fr, en, None, "hp.obo")
    for h, p in v1.execute("SELECT hpo_id, ancestor_id FROM hpo_ancestors WHERE distance = 1"):
        g.noeud(p, "hpo", None, None, None, None, "hp.obo")
        g.arete(h, "est_un", p, "hp.obo")

    # FOETO v2 : nœuds, verbatims, liens de fiche
    for sid, org, typ, lab, fiche in v2.execute("SELECT id, organe, type, label_fr, fiche FROM signes"):
        g.noeud(sid, "foeto2", typ, lab, None, org, fiche)
    for oid, src, txt, fiche in v2.execute("SELECT objet_id, source, texte, fiche FROM verbatims"):
        c.execute("INSERT INTO preuve_noeud SELECT ?,?,?,? WHERE EXISTS (SELECT 1 FROM noeud WHERE id=?)", (oid, src, txt, fiche, oid))
    for de, rel, vers in v2.execute("SELECT de, relation, vers FROM liens"):
        g.arete(de, rel, vers, "fiche")

    # FOETO v2 ↔ HPO (arbitrage)
    REL = {"SAME": "same_as", "FIN": "plus_fin_que", "LARGE": "plus_large_que"}
    for r in tsv(S / "arbitrage_foeto2_hpo_decide.tsv"):
        if r["decision"] in REL:
            g.noeud(r["hpo_candidat"], "hpo", None, r["hpo_fr"] or None, r["hpo_en"] or None, None, "hp.obo")
            g.arete(r["foeto2_id"], REL[r["decision"]], r["hpo_candidat"], f"arbitrage_{r['arbitre'] or 'remi'}",
                    qualifs={"canaux": r["canaux"], "note": r.get("note", "")})

    # syndromes (entités des livres), familles
    noms = {e: (n, o) for e, n, o in v1.execute("SELECT entite_id, nom, orpha FROM entites_livres")}
    for sid, titre in v1.execute("SELECT DISTINCT syndrome_id, syndrome_titre FROM syndrome_hpo_livres WHERE syndrome_id IS NOT NULL AND syndrome_id != ''"):
        g.noeud(sid, "syndrome", None, noms.get(sid, (None,))[0], titre, None, "livres")
    for fid, nom in v1.execute("SELECT family_id, family_name FROM syndrome_families"):
        g.noeud(fid, "famille", None, nom, None, None, "syndrome_families")
    for fid, sid, conf in v1.execute("SELECT family_id, syndrome_id, confidence FROM syndrome_family_members"):
        g.noeud(sid, "syndrome", None, noms.get(sid, (None,))[0], None, None, "familles")
        g.arete(sid, "membre_de", fid, "syndrome_family_members", qualifs={"confiance": conf})

    perdus = collections.Counter()
    # termes v1 (figés) gardés en nœuds foeto1 quand ils portent un lien de livre sans équivalent v2 exact
    lab_v1 = dict(v1.execute("SELECT id, label_fr FROM foeto_terms"))
    partiel = collections.defaultdict(list)
    for a, b in v2.execute("SELECT v1_id, v2_id FROM correspondance_v1 WHERE qualite='partielle'"):
        partiel[a].append(b)

    def terme(fid):
        if fid in v1v2:
            return v1v2[fid]
        g.noeud(fid, "foeto1", "v1 figée", lab_v1.get(fid), None, None, "syndromes_foetaux.foeto_terms")
        for b in partiel.get(fid, ()):
            g.arete(fid, "correspond_partiellement", b, "correspondance_v1")
        return fid
    # HPO -> syndrome (matrice des livres, verbatim)
    titre_ent = {(t, l): e for e, l, t in v1.execute("SELECT entite_id, livre, syndrome_titre FROM entites_livres_titres")}
    for sid, titre, h, livre, entree, verb, freq, niv, mod, parent, meth in v1.execute(
            "SELECT syndrome_id, syndrome_titre, hpo_id, livre, entree, verbatim, frequence, niveau, modalite, est_parent, methode "
            "FROM syndrome_hpo_livres WHERE hpo_id IS NOT NULL AND hpo_id != ''"):
        sid = sid or titre_ent.get((titre, livre))      # entrée sans syndrome_id : entité par (titre, livre)
        if not sid:
            perdus["signe_de hpo (ligne de livre sans entité)"] += 1; continue
        g.noeud(sid, "syndrome", None, noms.get(sid, (None,))[0], titre, None, "livres")
        g.noeud(h, "hpo", None, None, None, None, "hp.obo")
        q = {k: v for k, v in (("frequence", freq), ("niveau", niv), ("modalite", mod), ("est_parent", parent), ("methode", meth)) if v}
        g.arete(h, "signe_de", sid, "syndrome_hpo_livres", qualifs=q, preuves=[(livre, entree, None, verb)] if verb else ())

    # FOETO -> syndrome (micro des livres), DIA -> syndrome ; seulement par un terme v1 en correspondance EXACTE
    for sid, fid, verb, livre, chap, niv, age in v1.execute(
            "SELECT syndrome_id, foeto_id, verbatim, livre, chapitre, niveau, age FROM syndrome_foeto_livres "
            "WHERE foeto_id IS NOT NULL AND syndrome_id IS NOT NULL AND syndrome_id != ''"):
        g.noeud(sid, "syndrome", None, noms.get(sid, (None,))[0], None, None, "livres")
        g.arete(terme(fid), "signe_de", sid, "syndrome_foeto_livres", qualifs={k: v for k, v in (("niveau", niv), ("age", age)) if v},
                preuves=[(livre, chap, None, verb)] if verb else ())
    for tid, sid, meth in v1.execute("SELECT term_id, syndrome_id, methode FROM foeto_dia_orpha"):
        g.noeud(sid, "syndrome", None, noms.get(sid, (None,))[0], None, None, "foeto_dia_orpha")
        g.arete(terme(tid), "diagnostic_de", sid, "foeto_dia_orpha", qualifs={"methode": meth})

    # séquences : nœuds seq, same_as HPO, entraine (causale) / associe_seq (co-occurrence), preuves
    for k, (lab, _) in sc.NOEUDS.items():
        g.noeud(f"SEQ:{k}", "seq", None, lab, None, None, "sequences_canoniques")
        if k in asf.HPO:
            g.arete(f"SEQ:{k}", "same_as", asf.HPO[k], "sequences_canoniques")
    lab2id = {lab: f"SEQ:{k}" for k, (lab, _) in sc.NOEUDS.items()}
    statut = {(r["cause"], r["effet"]): r["statut"] for r in tsv(S / "entraine_statut.tsv")}
    for f in ("arbitrage_entraine_decide.tsv", "arbitrage_entraine_fr_decide.tsv"):
        for r in tsv(S / f):
            st = statut.get((r["cause"], r["effet"]))
            a, b = lab2id[r["cause"]], lab2id[r["effet"]]
            if st == "causale" and r["decision"] == "OUI":
                g.arete(a, "entraine", b, "sequences_arbitrees", statut="causale",
                        qualifs={"sequence": r["sequence"].replace(" (NOUVELLE arête)", "")},
                        preuves=[(r["livre"], r["chapitre"], r["page"], r["verbatim"])])
            elif st == "association" and r["decision"] == "CO":
                g.arete(a, "associe_seq", b, "sequences_arbitrees", statut="association",
                        preuves=[(r["livre"], r["chapitre"], r["page"], r["verbatim"])])

    ok, reste = acyclique(c)
    if not ok:
        c.close(); tmp.unlink()
        sys.exit(f"CYCLE sur est_un ∪ entraine, build refusé ; nœuds en cause : {reste}")
    c.execute("INSERT INTO meta VALUES ('construit_le', ?)", (time.strftime("%Y-%m-%d %H:%M:%S"),))
    c.execute("INSERT INTO meta VALUES ('acyclique_est_un_entraine', 'oui')")
    c.commit()
    n_noeud = dict(c.execute("SELECT type, count(*) FROM noeud GROUP BY 1"))
    n_arete = dict(c.execute("SELECT rel || ' / ' || origine, count(*) FROM arete GROUP BY 1"))
    sans_preuve = c.execute("SELECT count(*) FROM arete a WHERE rel IN ('entraine','signe_de') AND NOT EXISTS "
                            "(SELECT 1 FROM preuve p WHERE p.arete_id = a.id)").fetchone()[0]
    c.close()
    tmp.replace(KG)
    lignes = [f"kg.db construit {time.strftime('%Y-%m-%d %H:%M')}", "nœuds : " + json.dumps(n_noeud, ensure_ascii=False)]
    for k in sorted(set(ancien) | set(n_arete)):
        a, b = ancien.get(k, 0), n_arete.get(k, 0)
        lignes.append(f"  {k:55s} {b:7d}" + (f"   (avant {a}, {b - a:+d})" if ancien and a != b else ""))
    lignes.append(f"arêtes entraine/signe_de sans preuve de livre : {sans_preuve}")
    lignes += [f"perdus : {k} = {v}" for k, v in perdus.items()]
    lignes.append("acyclicité est_un ∪ entraine : OK")
    (S / "kg_diff.txt").write_text("\n".join(lignes) + "\n")
    print("\n".join(lignes))


if __name__ == "__main__":
    main()
