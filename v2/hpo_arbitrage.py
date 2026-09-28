#!/usr/bin/env python3
"""Arbitrage des codes HPO de FOETO v2 (2026-09-28).

Règle : un code n'est retenu que s'il nomme LE MÊME constat que le signe (ou, pour un
diagnostic, la même entité) — jamais un phénotype associé, une conséquence clinique ou
une maladie voisine. foeto_hpo (table sans provenance, en partie attribuée par LLM) et
les synonymes fr de hpo_terms ne font que proposer.

Chaque décision est écrite par le LIBELLÉ ANGLAIS OFFICIEL du terme HPO, résolu dans
hpo_terms à l'exécution : un libellé introuvable est signalé, jamais deviné.
RETIRER : codes « nets » de la passe automatique jugés faux (libellé fr de la base trompeur).
"""
import json, sqlite3, sys
from pathlib import Path

ICI = Path(__file__).parent
c = sqlite3.connect("file:%s?mode=ro" % (ICI.parent / "syndromes_foetaux.db"), uri=True)

# (organe, clé) : libellé anglais officiel HPO
RETENUS = {
    # cerveau / moelle
    ("cerveau_moelle", "gliose"): "Gliosis",
    ("cerveau_moelle", "myelomeningocele"): "Myelomeningocele",
    ("cerveau_moelle", "microcephalie"): "Microcephaly",
    ("cerveau_moelle", "hypoplasie_cerebelleuse"): "Cerebellar hypoplasia",
    ("cerveau_moelle", "lissencephalie_type1"): "Lissencephaly",
    ("cerveau_moelle", "dysplasie_corticale_focale"): "Focal cortical dysplasia",
    ("cerveau_moelle", "rhombencephalosynapsis"): "Rhombencephalosynapsis",
    ("cerveau_moelle", "hydrocephalie"): "Hydrocephalus",
    ("cerveau_moelle", "chiari"): "Chiari malformation",
    # cœur
    ("coeur", "non_compaction"): "Noncompaction cardiomyopathy",
    ("coeur", "fibrose_interstitielle"): "Myocardial fibrosis",
    # digestif
    ("digestif", "duplication"): "Gastrointestinal duplication",
    ("digestif", "laparoschisis"): "Gastroschisis",
    ("digestif", "omphalocele"): "Omphalocele",
    # dysplasies osseuses
    ("dysplasies_osseuses", "thorax_etroit"): "Narrow chest",
    ("dysplasies_osseuses", "polydactylie_post_axiale"): "Postaxial polydactyly",
    # foie
    ("foie", "obliteration_vbeh"): "Biliary atresia",
    ("foie", "fibrose_hepatique_congenitale"): "Congenital hepatic fibrosis",
    ("foie", "anasarque"): "Hydrops fetalis",
    ("foie", "cytopathie_mitochondriale"): "Mitochondrial respiratory chain defects",
    ("foie", "calcifications"): "Hepatic calcification",
    # gonades
    ("gonades", "ovotestis"): "True hermaphroditism",
    # muscle
    ("muscle", "myotubes_persistants"): "Centrally nucleated skeletal muscle fibers",
    ("muscle", "noyaux_centraux"): "Centrally nucleated skeletal muscle fibers",
    ("muscle", "dispersion_calibre"): "Increased variability in muscle fiber diameter",
    ("muscle", "fibrose_endomysiale"): "Increased endomysial connective tissue",
    ("muscle", "remplacement_adipeux"): "Fatty replacement of skeletal muscle",
    ("muscle", "fascicules_incomplets"): "Fatty replacement of skeletal muscle",
    # œil
    ("oeil", "colobome_nerf_optique"): "Optic disc coloboma",
    ("oeil", "opacite_corneenne"): "Corneal opacity",
    ("oeil", "colobome"): "Coloboma",
    ("oeil", "dysgenesie_segment_anterieur"): "Anterior segment developmental abnormality",
    ("oeil", "buphtalmie"): "Buphthalmos",
    ("oeil", "cataracte_foetale"): "Developmental cataract",
    # oreille
    ("oreille", "treacher_collins"): "Mandibulofacial dysostosis",
    # pancréas
    ("pancreas", "hyperplasie_insulaire"): "Pancreatic islet-cell hyperplasia",
    ("pancreas", "agenesie"): "Pancreatic aplasia",
    # peau
    ("peau", "acanthose"): "Epidermal acanthosis",
    ("peau", "pustules"): "Pustule",
    # poumon
    ("poumon", "hernie_diaphragmatique"): "Congenital diaphragmatic hernia",
    ("poumon", "hypoplasie"): "Pulmonary hypoplasia",
    ("poumon", "pneumopathie"): "Pneumonia",
    ("poumon", "lymphangiectasie"): "Pulmonary lymphangiectasia",
    # rate
    # rein
    ("rein", "rein_multikystique"): "Multicystic kidney dysplasia",
    ("rein", "voute_ossification"): "Decreased skull ossification",
    ("rein", "dtr"): "Renotubular dysgenesis",
    ("rein", "nta"): "Renal tubular epithelial necrosis",
    # rétention
    ("retention", "anasarque_foetale"): "Hydrops fetalis",
    # squelette
    ("squelette", "mesomelie"): "Mesomelia",
    ("squelette", "fractures_os_longs"): "Fractures of the long bones",
    # surrénales
    ("surrenales", "calcifications"): "Adrenal calcification",
    ("surrenales", "hcs"): "Congenital adrenal hyperplasia",
    ("surrenales", "hypoplasie_dax1"): "Adrenal hypoplasia",
    ("surrenales", "tumeur_corticosurrenalienne"): "Neoplasm of the adrenal cortex",
    ("surrenales", "cytomegalie_cf"): "Adrenocortical cytomegaly",
    # thymus
    ("thymus", "hypoplasie_aplasie_thymique"): "Aplasia/Hypoplasia of the thymus",
    ("thymus", "cardiopathie_conotroncale"): "Conotruncal defect",
    ("thymus", "deficit_immunitaire"): "Immunodeficiency",
    # thyroïde
    ("thyroide", "thymus_hypoplasique"): "Aplasia/Hypoplasia of the thymus",
    ("thyroide", "hemiagenesie"): "Thyroid hemiagenesis",
    ("thyroide", "kyste_thyreoglosse"): "Thyroglossal cyst",
    # vessie
    ("vessie", "imperforation_anale"): "Anal atresia",
    ("vessie", "vup"): "Urethral valve",
    ("vessie", "exstrophie_vesicale"): "Bladder exstrophy",
}

# Codes posés par la passe automatique et jugés faux ou trompeurs
RETIRER = {
    ("peau", "peau_tendue"),          # HP:0100679 = Lack of skin elasticity, pas « tight skin »
    ("oeil", "opacite_corneenne"),    # remplacé ci-dessus (centrale OU périphérique)
    ("oeil", "nevrite_optique"),      # à vérifier contre le libellé anglais (rétrobulbaire ?)
    ("peau", "bebe_collodion"),
    ("peau", "ichtyose_congenitale"),        # HP:0007431 = Congenital ichthyosiform erythroderma : une forme seulement
    ("gonades", "gonade_bandelette"),     # HP:0010464 = Streak ovary : la bandelette n'est pas forcément ovarienne
    ("coeur", "hematopoiese_extramedullaire"),  # NOR : 13 % des mort-nés — un normal ne se code pas en phénotype
    ("rate", "rate_accessoire"),                # NOR : variante normale, une autopsie sur dix
}
# Absents du sous-ensemble HPO local (hpo_terms) — à reprendre si la base HPO est complétée :
# lissencéphalie type II (cobblestone), hémopéricarde, rhabdomyome cardiaque, pneumatose
# intestinale, paucité ductulaire, PHPV, névrite optique (seul « retrobulbar » existe),
# membrane collodion, emphysème interstitiel, kystes glomérulaires, kystes médullaires.


def hpo_de(libelle):
    r = c.execute("select hpo_id from hpo_terms where lower(label_en) = lower(?) and is_excluded = 0",
                  (libelle,)).fetchall()
    return r[0][0] if len(r) == 1 else None


if __name__ == "__main__":
    introuvables, ecrits, retires = [], 0, 0
    sources = {p.stem: json.loads(p.read_text(encoding="utf-8")) for p in (ICI / "sources").glob("*.json")}
    for (org, k) in RETIRER:
        for x in sources[org]["signes"]:
            if x["k"] == k and x.pop("hpo", None):
                retires += 1
    for (org, k), lib in sorted(RETENUS.items()):
        h = hpo_de(lib)
        x = next((s for s in sources[org]["signes"] if s["k"] == k), None)
        if not h or not x:
            introuvables.append("%s.%s → %s (%s)" % (org, k, lib, "libellé HPO introuvable" if not h else "clé absente"))
            continue
        if x.get("hpo") != h:
            x["hpo"] = h
            ecrits += 1
    for o, d in sources.items():
        (ICI / "sources" / (o + ".json")).write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")
    print("écrits %d · retirés %d · introuvables %d" % (ecrits, retires, len(introuvables)))
    print("\n".join(introuvables))
    sys.exit(0)
