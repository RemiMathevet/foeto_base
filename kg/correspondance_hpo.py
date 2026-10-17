#!/usr/bin/env python3
"""Correspondance FOETO v2 ↔ HPO : propositions déterministes à arbitrer (plan 349d336f5197, étape 2).

Sans le pont FOETO v2 ↔ HPO, le graphe reste en îlots : les liens syndrome -> HPO des livres ne croisent pas
les liens FOETO (critère, exclut…). Ici on PROPOSE, Rémi arbitre ; rien n'est écrit dans foeto_v2.db.

Signes visés : constats (CON) et diagnostics (DIA). Canaux, du plus sûr au moins sûr :
  fr_exact   libellé fr du signe v2 (sans parenthèses ni ponctuation) = un libellé fr officiel d'HPO (NAME)
  en_exact   libellé en du terme v1 correspondant EXACTEMENT = une forme en d'HPO (NAME/EXACT)
  fr_contenu tous les mots pleins d'une forme fr d'HPO sont dans le libellé du signe : HPO égal ou plus large
             (FOETO plus fin) ; on garde la forme HPO la plus longue
  en_semantique  à défaut des précédents : libellé en du terme v1 (correspondance exacte/partielle) contre les
             libellés en officiels d'HPO, BioLORD (anglais seul), cosinus ≥ 0,80 ET un mot plein en commun ;
             suggestion seulement
Le lien v1 foeto_hpo n'est PAS utilisé : mesuré inutilisable (sténose de l'aqueduc -> insuffisance pancréatique
exocrine, acétylcholinestérase -> atélectasie, 2026-10-17).
Parmi plusieurs candidats d'un même signe, un ancêtre d'un autre candidat est écarté (on garde le plus fin).
Relation proposée : same_as si fr_exact ou en_exact, sinon « à trancher » (same_as / plus_fin / plus_large).
L'HPO déjà posé dans foeto_v2.signes.hpo (arbitrage fiches) est rappelé et confronté.

Sortie hors dépôt : kg/sorties/arbitrage_foeto2_hpo.tsv (colonne decision : SAME / FIN (FOETO plus fin que
HPO) / LARGE / NON).

    python kg/correspondance_hpo.py
"""
import collections
import re
import sqlite3
import unicodedata
from pathlib import Path

ICI = Path(__file__).resolve().parent
B = ICI.parent
V2 = B / "foeto_v2.db"
V1 = B / "syndromes_foetaux.db"
OUT = ICI / "sorties" / "arbitrage_foeto2_hpo.tsv"


def norm(s):
    s = re.sub(r"\([^)]*\)|«[^»]*»", " ", s or "")
    s = re.split(r" — | – ", s)[0]                      # « Gliose — astrocytose réactionnelle » : la tête
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().lower()
    return " ".join(re.sub(r"[^a-z0-9]+", " ", s).split())


VIDES = set("de du des la le les l d et en a au aux un une par avec sans dans sur sous ou the of and with".split())


def pleins(s):
    """Mots pleins normalisés, pluriel simple retiré."""
    return [re.sub(r"(?<=...)[sx]$", "", w) for w in norm(s).split() if w not in VIDES]


def main():
    v2 = sqlite3.connect(f"file:{V2}?mode=ro", uri=True)
    v1 = sqlite3.connect(f"file:{V1}?mode=ro", uri=True)
    signes = v2.execute("SELECT id, organe, type, label_fr, COALESCE(hpo,'') FROM signes WHERE type IN ('CON','DIA')").fetchall()
    corr = collections.defaultdict(list)
    for v1_id, v2_id, q in v2.execute("SELECT v1_id, v2_id, qualite FROM correspondance_v1 WHERE qualite IN ('exacte','partielle')"):
        corr[v2_id].append((v1_id, q))
    lab_en_v1 = dict(v1.execute("SELECT id, label_en FROM foeto_terms"))
    formes = {"fr": collections.defaultdict(set), "en": collections.defaultdict(set)}
    # fr : libellés officiels traduits seulement (NAME) ; les synonymes fr EXACT sont des traductions bruitées
    # (« myéloméningocèle » synonyme de spina bifida occulta, « agénésie du corps calleux » de l'agénésie
    # partielle). en : NAME + EXACT (synonymes HPO d'origine, fiables)
    for h, forme, langue in v1.execute("SELECT hpo_id, forme, langue FROM hpo_synonymes WHERE portee = 'NAME' "
                                       "OR (portee = 'EXACT' AND langue = 'en')"):
        formes[langue][norm(forme)].add(h)
    nom = {h: (fr or "", en) for h, en, fr in v1.execute("SELECT hpo_id, label_en, label_fr FROM hpo_terms")}
    anc = collections.defaultdict(set)
    for h, a in v1.execute("SELECT hpo_id, ancestor_id FROM hpo_ancestors WHERE distance > 0"):
        anc[h].add(a)
    # canal sémantique : préparé une fois (BioLORD, anglais contre anglais)
    noms_en = sorted({(h, f) for h, f in v1.execute("SELECT hpo_id, forme FROM hpo_synonymes WHERE portee='NAME' AND langue='en'")})
    from sentence_transformers import SentenceTransformer
    st = SentenceTransformer("FremyCompany/BioLORD-2023")
    E_hpo = st.encode([f for _, f in noms_en], batch_size=256, normalize_embeddings=True, show_progress_bar=False)
    lignes, stats = [], collections.Counter()
    for sid, org, typ, lab, hpo_pose in signes:
        cand = collections.defaultdict(set)
        for h in formes["fr"].get(norm(lab), ()):
            cand[h].add("fr_exact")
        for v1_id, q in corr.get(sid, ()):
            for h in formes["en"].get(norm(lab_en_v1.get(v1_id)), ()) if q == "exacte" else ():
                cand[h].add("en_exact")
        if not cand:                                    # inclusion : seulement à défaut d'égalité
            mots = set(pleins(lab))
            best = [(len(m), h) for f, hs in formes["fr"].items() if (m := pleins(f)) and len(m) >= 1
                    and set(m) <= mots and (len(m) >= 2 or len(m[0]) >= 8) for h in hs]
            if best:
                n = max(b[0] for b in best)
                for _, h in (b for b in best if b[0] == n):
                    cand[h].add("fr_contenu")
        if not cand:
            ens = [lab_en_v1.get(v1_id) for v1_id, _ in corr.get(sid, ()) if lab_en_v1.get(v1_id)]
            if ens:
                q = st.encode(ens, normalize_embeddings=True, show_progress_bar=False)
                sc = q @ E_hpo.T
                for i, en in enumerate(ens):
                    j = int(sc[i].argmax())
                    h, f = noms_en[j]
                    if sc[i, j] >= 0.80 and set(pleins(en)) & set(pleins(f)):
                        cand[h].add("en_semantique")
        # on garde le plus fin : un candidat ancêtre d'un autre candidat sort
        fins = {h: c for h, c in cand.items() if not any(h in anc[o] for o in cand if o != h)}
        if hpo_pose and hpo_pose not in fins:
            fins.setdefault(hpo_pose, set()).add("déjà_posé")
        if not fins:
            stats["sans candidat"] += 1
            lignes.append((sid, org, typ, lab, hpo_pose, "", "", "", "", "aucun candidat", ""))
            continue
        stats["avec candidat"] += 1
        for h, c in sorted(fins.items(), key=lambda x: (-len(x[1] & {"fr_exact", "en_exact"}), x[0])):
            rel = "same_as" if c & {"fr_exact", "en_exact"} else "à trancher"
            if c & {"fr_exact", "en_exact"}:
                stats["same_as lexical"] += 1
            fr, en = nom.get(h, ("", ""))
            accord = "oui" if h == hpo_pose else ("CONFLIT" if hpo_pose else "")
            lignes.append((sid, org, typ, lab, hpo_pose, h, fr, en, "+".join(sorted(c)), rel, accord))
    OUT.parent.mkdir(exist_ok=True)
    tete = ("foeto2_id", "organe", "type", "label_fr", "hpo_deja_pose", "hpo_candidat", "hpo_fr", "hpo_en",
            "canaux", "relation_proposee", "accord_deja_pose", "decision")
    OUT.write_text("\n".join("\t".join(map(str, l)) for l in [tete] + [l + ("",) for l in lignes]) + "\n")
    print(f"{len(signes)} signes CON/DIA : {stats['avec candidat']} avec au moins un candidat, "
          f"{stats['sans candidat']} sans ; {stats['same_as lexical']} propositions same_as lexicales ; "
          f"conflits avec l'HPO déjà posé : {sum(1 for l in lignes if l[10] == 'CONFLIT')} -> {OUT}")
    par = collections.Counter((l[2], l[9] != "aucun candidat") for l in lignes if l[9] != "à trancher" or True)
    return stats


if __name__ == "__main__":
    main()
