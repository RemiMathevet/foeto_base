#!/usr/bin/env python3
"""Routeur deterministe : les signes d'abstract que HPO n'aura jamais — constatations
HISTOLOGIQUES (« thickening of the alveolar walls », « absent olivary nuclei »,
« iron deposits in the liver ») — quittent le circuit HPO pour le circuit micro
(syndrome_micro_livres_candidats -> map_micro_foeto -> arbitrage FOETO).

Critere : un mot d'histologie dans le LIBELLE du signe (pas le verbatim : un signe
macro peut avoir un contexte micro). hpo_methode='micro' sur le candidat HPO pour
que nommage / ReAct / arbitrage ne le reprennent pas. Rejouable.

Usage : python3 route_micro_pubmed.py [--apply]
"""
import argparse
import re
import sqlite3

DB = "/home/mathevet/Bureau/foeto_base/syndromes_foetaux.db"
HISTO = re.compile(r"""\b(alveol\w*|pneumocyt\w*|fibro(?:sis|tic|blast\w*)|villo\w*|villi|trophoblast\w*|syncyt\w*|infarct\w*|necro\w*|
    inflammat\w*|infiltrat\w*|glomerul\w*|tubul(?:e|es|ar)|myofib\w*|fibers?|fibres?|nemaline|rods?\b|vacuol\w*|glycogen|lipid\w*|
    deposits?|hemosiderin|haemosiderin|siderosis|calcificat\w*|gliosis|neurons?|neuronal|olivary|heterotopi\w*|ultrastructur\w*|
    mitochondri\w*|microscop\w*|histolog\w*|biops\w*|cells?|cellular|nuclei|nucleus|nuclear|stain\w*|immunoreactiv\w*|apopto\w*|
    hepatocyt\w*|cholestasis|bile ducts?|ductal plate|islets?|acinar|chondrocyt\w*|growth plate|resting zone|columnar|
    marrow|megakaryocyt\w*|erythro\w*|lymphocyt\w*|storage|foam(?:y)? cells?|elastic|collagen|myelin\w*|demyelinat\w*|axon\w*|
    spongi\w*|sialidosis|inclusions?|granul\w*|vessel walls?|intima\w*|media\b|hyperplasi\w*|atrophy of muscle|
    muscle fib\w*|type [12] (?:fiber|fibre)|myopathic|dystrophic|degenerat\w*|edema of the villi|chorangi\w*|
    intervillous|decidua\w*|amnion\w*|cytotropho\w*|dysplastic (?:glomeruli|tubules)|ductal|lobul\w*)\b""", re.I | re.X)
# clinique, pas histologie, malgre le mot : « motor neuron disease », « T cell », « alveolar cleft »
NON_HISTO = re.compile(r"\b(disease|neuropathy|dysfunction|clefts?|frenul\w*|activity|immunolog\w*|deficiency|T cells?|B cells?|blood cells?|sickle|"
                       r"alveolar (?:ridge|cleft|bone|process)|dental|tooth|teeth|red cells?|white cells?|cell count|hyperplasia of the (?:gums|gingiva))\b", re.I)
ORGANE = {"neuro": "brain", "abdomen": "liver", "heart": "heart", "genitourinary": "kidney", "limbs": "muscle",
          "skeletal": "bone", "thorax": "lung", "skin": "skin", "eyes": "eye", "craniofacial": "head", "lungs": "lung",
          "renal": "kidney", "chest": "lung", "respiratory": "lung"}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()
    c = sqlite3.connect(DB)
    rows = c.execute("""select id, fichier, syndrome_titre, signe, verbatim, region from syndrome_signes_livres_candidats
                        where livre='pubmed' and verbatim_ok=1 and hpo_id is null and (hpo_methode is null or hpo_methode in ('', 'micro'))""").fetchall()
    micro = [r for r in rows if HISTO.search(r[3]) and not NON_HISTO.search(r[3])]
    print(f"{len(rows)} signes pubmed non mappés -> {len(micro)} histologiques routés vers le circuit micro")
    if not a.apply:
        for r in micro[:40]:
            print(f"  {r[3][:70]:70s} [{r[5]}]")
        return
    c.execute("delete from syndrome_micro_livres_candidats where livre='pubmed' and modele='routeur:histo'")
    c.execute("update syndrome_signes_livres_candidats set hpo_methode=null where hpo_methode='micro'")
    for rid, fichier, titre, signe, verbatim, region in micro:
        c.execute("""insert into syndrome_micro_livres_candidats (passage_id, syndrome_titre, syndrome_id, livre, chapitre, signe,
                     verbatim, verbatim_ok, organe, attribution, modele) values (?,?,?,?,?,?,?,?,?,?,?)""",
                  (None, titre, fichier.split("@")[1], "pubmed", fichier, signe, verbatim, 1, ORGANE.get(region, region or ""), "direct", "routeur:histo"))
        c.execute("update syndrome_signes_livres_candidats set hpo_methode='micro' where id=?", (rid,))
    c.commit()
    print(f"{len(micro)} candidats micro (livre='pubmed', modele='routeur:histo') ; hpo_methode='micro' posé")


if __name__ == "__main__":
    main()
