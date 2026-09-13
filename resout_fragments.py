#!/usr/bin/env python3
"""Seconde resolution des NOMS proposes par le 35B (signes_fragments) restes sans
hpo_id : l'egalite exacte de nomme_signes_hpo manquait le pluriel et l'ordre des
mots (« Renal cysts » -> Renal cyst, « Cleft of the palate » -> Cleft palate).
Ici : egalite de l'ENSEMBLE des mots pleins, NAME/EXACT seulement — toujours un
nom, jamais un identifiant invente ; methode 'llm_nom_tok', dans le meme TSV de
relecture que llm_nom.

Usage : python3 resout_fragments.py [--apply]
"""
import argparse
import sqlite3

import map_signes_hpo_obo as O

RANK = {"NAME": 0, "EXACT": 1}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()
    obo = O.load_obo(O.OBO)
    idx = {}
    for hid, t in obo.items():
        for form, scope in [(t["name"], "NAME")] + list(t["syn"].items()):
            if scope in RANK:
                k = O.toks(form)
                if k and (k not in idx or RANK[scope] < RANK[idx[k][1]]):
                    idx[k] = (hid, scope)
    c = sqlite3.connect(O.DB)
    rows = c.execute("""select f.candidat_id, f.fragment, s.signe from signes_fragments f
                        join syndrome_signes_livres_candidats s on s.id = f.candidat_id
                        where f.hpo_id is null and f.fragment <> '__AUCUN__' and s.hpo_id is null""").fetchall()
    par_rid = {}
    for rid, frag, signe in rows:
        h = idx.get(O.toks(frag))
        if h:
            par_rid.setdefault(rid, (signe, []))[1].append((frag, h[0]))
    print(f"{len(rows)} noms non résolus -> {len(par_rid)} signes résolus par les mots")
    for rid, (signe, L) in list(par_rid.items())[:12]:
        print(f"  {signe[:45]:45s} <- {L[0][0][:40]:40s} {L[0][1]} {obo[L[0][1]]['name'][:35]}")
    if a.apply:
        for rid, (signe, L) in par_rid.items():
            hids = list(dict.fromkeys(h for _, h in L))
            c.execute("update syndrome_signes_livres_candidats set hpo_id=?, hpo_portee='LLM_NOM', hpo_methode='llm_nom_tok' where id=?", ("+".join(hids), rid))
            for frag, h in L:
                c.execute("update signes_fragments set hpo_id=? where candidat_id=? and fragment=?", (h, rid, frag))
        c.commit()
        import nomme_signes_hpo
        nomme_signes_hpo.ecrire_tsv(c, obo)


if __name__ == "__main__":
    main()
