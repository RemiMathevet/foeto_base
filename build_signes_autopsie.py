#!/usr/bin/env python3
"""Bloc SIGNES embarque dans autopsie.html (V2) — structure MINIMALE.

Meme patron que build_signes_examen.py, au grain du CHAMP « chips » de la
trame d'autopsie (situs, diaphragme, gros vaisseaux, reins…) :
  ancres   sous-arbre HPO du champ (vide si le champ n'a pas d'organe HPO :
           docimasie, meconium, prelevements)
  normal   les valeurs qui veulent dire « vu normal » — a l'export elles
           donnent vu_normal = ancres
  chips    les valeurs V1 codees HPO quand une forme correspond ou par table
           manuelle, PLUS les signes attestes les plus nommes (jamais a la place)
  signes   liste PLATE des signes attestes du sous-arbre (id, libelle, n)
  formes   formes francaises + nom anglais officiel, pour la recherche

Usage : python3 build_signes_autopsie.py > /home/mathevet/Bureau/Hub_HTML/signes_autopsie.js
"""
import json
import re
import sqlite3
import sys
import unicodedata
from collections import defaultdict

DB = "/home/mathevet/Bureau/foeto_base/syndromes_foetaux.db"
N_TOP = 4

# champ chips -> ancre(s) HPO ; [] = pas de sous-arbre, on ne code que les valeurs
ANCRES = {
    "situs": [], "diaphragme": ["HP:0000775"],
    "veine_omb": [], "art_omb": ["HP:0011403"], "vessie": ["HP:0000014"], "ogi": ["HP:0000812"],
    "appendice": [], "vb": ["HP:0005264"],
    "voies_aer": ["HP:0002778", "HP:0002031"], "thymus_aspect": ["HP:0000777"], "tvi": [],
    "pericarde": ["HP:0001697"],
    "pointe": [], "gros_vx": ["HP:0030962"], "tsa": [], "rvp_d": ["HP:0010772"], "rvp_g": ["HP:0010772"],
    "crosse": ["HP:0012303"], "quatre_cav": ["HP:0001713"], "foramen_ovale": [],
    "septum_iv": ["HP:0001671"], "valves": ["HP:0001654"],
    "poumon_d_aspect": ["HP:0002088"], "poumon_g_aspect": ["HP:0002088"], "docimasie": [],
    "foie_aspect": ["HP:0001392"], "estomac": ["HP:0002577"], "tube_dig": ["HP:0002242"], "meconium": [],
    "pancreas_aspect": ["HP:0001732"], "rate_aspect": ["HP:0025408"],
    "surrenales_aspect": ["HP:0000834"], "reins_aspect": ["HP:0000077"],
    "voies_urin": ["HP:0004742", "HP:0000069", "HP:0000014", "HP:0000795"],   # bassinet, uretère, vessie, urètre — le rein a son champ
    "cerveau_ext": ["HP:0012443"], "gyration": ["HP:0002536"], "fosse_post": ["HP:0001317"],
    "moelle": ["HP:0002143"],
    "annexes": [], "speciaux": [],
}
# les valeurs V1 de chaque champ, telles qu'elles sont dans autopsie.html (a garder synchrone)
CHIPS_V1 = {
    "situs": ["Solitus", "Inversus", "Ambiguus"],
    "diaphragme": ["Normal", "Hernie D", "Hernie G", "Éventration", "Agénésie"],
    "veine_omb": ["Perméable", "Thrombosée", "Cathétérisée", "Non vue"],
    "art_omb": ["Deux", "Artère ombilicale unique", "Non identifiables"],
    "vessie": ["Normale", "Vide", "Distendue", "Mégavessie", "Non vue"],
    "ogi": ["Testicules en place", "Testicules inguinaux", "Cryptorchidie", "Ovaires en place", "Utérus présent", "Ambiguïté", "Non identifiés"],
    "appendice": ["Présent", "Absent", "Position anormale"],
    "vb": ["Présente", "Absente", "Atrésique", "Distendue"],
    "voies_aer": ["Perméables", "Atrésie œsophagienne", "Fistule œso-trachéale", "Sténose trachéale", "Cathétérisme non réalisé"],
    "thymus_aspect": ["Normal", "Hypoplasique", "Absent", "Involution de stress", "Ectopique", "Hémorragique"],
    "tvi": ["Présent", "Absent", "Trajet rétro-aortique"],
    "pericarde": ["Normal", "Épaissi", "Adhérent", "Hémorragique", "Fibrineux"],
    "pointe": ["À gauche", "À droite", "Médiane"],
    "gros_vx": ["Concordants", "Transposition", "Malposition", "Tronc artériel commun", "Ventricule droit à double issue"],
    "tsa": ["Normaux", "Variante d'origine", "Arc aortique droit", "Sous-clavière rétro-œsophagienne"],
    "rvp_d": ["Normal", "Anormal partiel", "Anormal total", "Non exploré"],
    "rvp_g": ["Normal", "Anormal partiel", "Anormal total", "Non exploré"],
    "crosse": ["Normaux", "Hypoplasie de l'arc", "Coarctation", "Interruption de l'arc"],
    "quatre_cav": ["Équilibrées", "VG hypoplasique", "VD hypoplasique", "Ventricule unique"],
    "foramen_ovale": ["Perméable", "Restrictif", "Fermé", "Absent"],
    "septum_iv": ["Intact", "CIV périmembraneuse", "CIV musculaire", "CIV d'admission", "Canal atrio-ventriculaire"],
    "valves": ["Normales", "Sténose pulmonaire", "Atrésie pulmonaire", "Sténose aortique", "Atrésie aortique", "Dysplasie tricuspide", "Maladie d'Ebstein", "Dysplasie mitrale"],
    "poumon_d_aspect": ["Normal", "Hypoplasique", "Congestif", "Lobation anormale", "Malformation kystique", "Séquestration"],
    "poumon_g_aspect": ["Normal", "Hypoplasique", "Congestif", "Lobation anormale", "Malformation kystique", "Séquestration"],
    "docimasie": ["Négative", "Positive partielle", "Positive"],
    "foie_aspect": ["Normal", "Congestif", "Stéatosique", "Fibreux", "Nodulaire", "Pâle", "Hémorragique"],
    "estomac": ["Normal", "Vide", "Distendu", "Atrésie", "Contenu méconial", "Contenu hémorragique"],
    "tube_dig": ["Normal", "Malrotation", "Atrésie", "Sténose", "Volvulus", "Perforation", "Diverticule de Meckel", "Mésentère commun"],
    "meconium": ["Présent en place", "Absent", "Retard d'évacuation"],
    "pancreas_aspect": ["Normal", "Annulaire", "Hypoplasique", "Ectopie"],
    "rate_aspect": ["Normale", "Asplénie", "Polysplénie", "Rate accessoire", "Congestive"],
    "surrenales_aspect": ["Normales", "Hypoplasiques", "Hémorragiques", "Kystiques", "En galette"],
    "reins_aspect": ["Normaux", "Agénésie", "Hypoplasie", "Dysplasie multikystique", "Polykystose", "Fer à cheval", "Ectopie", "Lobulation persistante"],
    "voies_urin": ["Normales", "Dilatation pyélique", "Urétérohydronéphrose", "Méga-uretère", "Valves de l'urètre postérieur", "Duplicité"],
    "cerveau_ext": ["Normal", "Autolysé", "Œdémateux", "Hémorragique", "Malformatif", "Non prélevable"],
    "gyration": ["Adaptée au terme", "Retard", "Avance", "Lissencéphalie", "Polymicrogyrie"],
    "fosse_post": ["Normale", "Kystique", "Dandy-Walker", "Méga grande citerne", "Hypoplasie vermienne", "Chiari II"],
    "moelle": ["Normale", "Non explorée", "Malformative", "Autolysée"],
    "annexes": ["Placenta", "Cordon", "Membranes", "Aucune"],
    "speciaux": ["Caryotype", "ACPA", "Bactériologie", "Virologie", "Métabolique", "Muscle", "Peau (fibroblastes)"],
}
# valeurs qui signifient « vu, normal » : a l'export, vu_normal = ancres du champ
NORMAL = {"Solitus", "Normal", "Normale", "Normales", "Normaux", "Perméable", "Perméables", "Deux",
          "Présent", "Présente", "Concordants", "Intact", "Équilibrées", "Adaptée au terme",
          "Présent en place", "Négative", "Testicules en place", "Ovaires en place", "Utérus présent", "À gauche"}
# codage explicite (champ, valeur) — les valeurs de paillasse n'ont pas de forme HPO
MANUEL = {
    ("situs", "Inversus"): "HP:0001696", ("situs", "Ambiguus"): "HP:0030853",
    ("diaphragme", "Hernie D"): "HP:0000776", ("diaphragme", "Hernie G"): "HP:0000776",
    ("diaphragme", "Agénésie"): "HP:0010315",
    ("art_omb", "Artère ombilicale unique"): "HP:0001195",
    ("vessie", "Mégavessie"): "HP:0000021",
    ("ogi", "Cryptorchidie"): "HP:0000028", ("ogi", "Testicules inguinaux"): "HP:0000028", ("ogi", "Ambiguïté"): "HP:0000062",
    ("vb", "Absente"): "HP:0011467", ("vb", "Atrésique"): "HP:0005912",
    ("voies_aer", "Atrésie œsophagienne"): "HP:0002032", ("voies_aer", "Fistule œso-trachéale"): "HP:0002575",
    ("voies_aer", "Sténose trachéale"): "HP:0002777",
    ("thymus_aspect", "Hypoplasique"): "HP:0000778", ("thymus_aspect", "Absent"): "HP:0005359",
    ("pointe", "À droite"): "HP:0001651", ("pointe", "Médiane"): "HP:0011599",
    ("gros_vx", "Transposition"): "HP:0001669", ("gros_vx", "Tronc artériel commun"): "HP:0001660",
    ("gros_vx", "Ventricule droit à double issue"): "HP:0001719",
    ("tsa", "Arc aortique droit"): "HP:0012020", ("tsa", "Sous-clavière rétro-œsophagienne"): "HP:0031251",
    ("rvp_d", "Anormal partiel"): "HP:0010773", ("rvp_d", "Anormal total"): "HP:0005160",
    ("rvp_g", "Anormal partiel"): "HP:0010773", ("rvp_g", "Anormal total"): "HP:0005160",
    ("crosse", "Hypoplasie de l'arc"): "HP:0012304", ("crosse", "Coarctation"): "HP:0001680",
    ("crosse", "Interruption de l'arc"): "HP:0011611",
    ("quatre_cav", "VG hypoplasique"): "HP:0004383", ("quatre_cav", "VD hypoplasique"): "HP:0004762",
    ("quatre_cav", "Ventricule unique"): "HP:0001750",
    ("septum_iv", "CIV périmembraneuse"): "HP:0011682", ("septum_iv", "CIV musculaire"): "HP:0011623",
    ("septum_iv", "CIV d'admission"): "HP:0001629", ("septum_iv", "Canal atrio-ventriculaire"): "HP:0006695",
    ("valves", "Sténose pulmonaire"): "HP:0001642", ("valves", "Atrésie pulmonaire"): "HP:0010882",
    ("valves", "Sténose aortique"): "HP:0001650", ("valves", "Atrésie aortique"): "HP:0010883",
    ("valves", "Dysplasie tricuspide"): "HP:0030732", ("valves", "Maladie d'Ebstein"): "HP:0010316",
    ("valves", "Dysplasie mitrale"): "HP:0001633",
    ("poumon_d_aspect", "Hypoplasique"): "HP:0002089", ("poumon_g_aspect", "Hypoplasique"): "HP:0002089",
    ("poumon_d_aspect", "Lobation anormale"): "HP:0002101", ("poumon_g_aspect", "Lobation anormale"): "HP:0002101",
    ("poumon_d_aspect", "Séquestration"): "HP:0100632", ("poumon_g_aspect", "Séquestration"): "HP:0100632",
    ("foie_aspect", "Stéatosique"): "HP:0001397", ("foie_aspect", "Fibreux"): "HP:0001395",
    ("estomac", "Atrésie"): "HP:0004399",
    ("tube_dig", "Malrotation"): "HP:0002566", ("tube_dig", "Mésentère commun"): "HP:0002566",
    ("tube_dig", "Atrésie"): "HP:0011100", ("tube_dig", "Volvulus"): "HP:0002580",
    ("tube_dig", "Perforation"): "HP:0031368", ("tube_dig", "Diverticule de Meckel"): "HP:0002245",
    ("pancreas_aspect", "Annulaire"): "HP:0001734", ("pancreas_aspect", "Hypoplasique"): "HP:0002594",
    ("rate_aspect", "Asplénie"): "HP:0001746", ("rate_aspect", "Polysplénie"): "HP:0001748",
    ("rate_aspect", "Rate accessoire"): "HP:0001747",
    ("surrenales_aspect", "Hypoplasiques"): "HP:0000835",
    ("reins_aspect", "Agénésie"): "HP:0000104", ("reins_aspect", "Hypoplasie"): "HP:0000089",
    ("reins_aspect", "Dysplasie multikystique"): "HP:0000003", ("reins_aspect", "Polykystose"): "HP:0000113",
    ("reins_aspect", "Fer à cheval"): "HP:0000085", ("reins_aspect", "Ectopie"): "HP:0000086",
    ("voies_urin", "Dilatation pyélique"): "HP:0010945", ("voies_urin", "Urétérohydronéphrose"): "HP:0000126+HP:0000072",
    ("voies_urin", "Méga-uretère"): "HP:0008676", ("voies_urin", "Valves de l'urètre postérieur"): "HP:0010957",
    ("voies_urin", "Duplicité"): "HP:0000081",
    ("cerveau_ext", "Œdémateux"): "HP:0002181", ("cerveau_ext", "Hémorragique"): "HP:0002170",
    ("gyration", "Lissencéphalie"): "HP:0001339", ("gyration", "Polymicrogyrie"): "HP:0002126",
    ("fosse_post", "Kystique"): "HP:0007291", ("fosse_post", "Dandy-Walker"): "HP:0001305",
    ("fosse_post", "Méga grande citerne"): "HP:0002280", ("fosse_post", "Hypoplasie vermienne"): "HP:0001320",
    ("fosse_post", "Chiari II"): "HP:0002308",
}


def norm(s):
    s = "".join(ch for ch in unicodedata.normalize("NFD", (s or "").lower()) if unicodedata.category(ch) != "Mn")
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9\s-]", " ", s)).strip()


def main():
    c = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    lab = {h: (fr or en) for h, fr, en in c.execute("select hpo_id, label_fr, label_en from hpo_terms")}
    foet = {r[0] for r in c.execute("select hpo_id from hpo_terms where context in ('prenatal','both') and is_excluded=0")}
    att = {r[0]: r[1] for r in c.execute(
        "select hpo_id, count(distinct syndrome_titre) from v_syndrome_hpo_livres_foetal where est_parent=0 group by 1")}
    desc = defaultdict(set)
    for h, a in c.execute("select hpo_id, ancestor_id from hpo_ancestors"):
        desc[a].add(h)
    formes = defaultdict(list)
    for h, f, lg, portee in c.execute("select hpo_id, forme, langue, portee from hpo_synonymes where portee in ('NAME','EXACT','NARROW')"):
        if lg == "fr" or portee == "NAME":
            formes[h].append(f)

    for k, v in MANUEL.items():
        for h in v.split("+"):
            assert h in foet, (k, h)
    out, n_code, n_chips = {}, 0, 0
    for champ, ancres in ANCRES.items():
        sub = set()
        for a in ancres:
            sub |= desc[a] | {a}
        sub &= foet
        chips = []
        for v in CHIPS_V1[champ]:
            h = MANUEL.get((champ, v))
            chips.append({"l": v, "id": h})
            n_chips += 1; n_code += bool(h)
        deja = {x for ch in chips if ch["id"] for x in ch["id"].split("+")}
        for _, h in sorted(((att[h], h) for h in sub if att.get(h) and h not in deja), reverse=True)[:N_TOP]:
            chips.append({"l": lab[h], "id": h, "att": 1})
        signes = sorted(({"id": h, "l": lab[h], "n": att[h]} for h in sub if att.get(h)), key=lambda x: -x["n"])
        fm = {h: sorted(set(formes.get(h, [])), key=str.lower) for h in sub if att.get(h)}
        out[champ] = {"ancres": ancres, "normal": [v for v in CHIPS_V1[champ] if v in NORMAL],
                      "chips": chips, "signes": signes, "formes": fm}

    js = "/* genere par foeto_base/build_signes_autopsie.py — ne pas editer a la main */\nvar SIGNES = " + \
         json.dumps(out, ensure_ascii=False, separators=(",", ":")) + ";\n"
    sys.stdout.write(js)
    tot_s = sum(len(v["signes"]) for v in out.values()); tot_f = sum(len(x) for v in out.values() for x in v["formes"].values())
    sys.stderr.write(f"{len(out)} champs | valeurs V1 codees {n_code}/{n_chips} | {tot_s} signes attestes | {tot_f} formes | {len(js)//1024} Ko\n")


if __name__ == "__main__":
    main()
