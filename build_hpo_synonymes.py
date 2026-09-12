#!/usr/bin/env python3
"""Table hpo_synonymes : une forme par ligne, avec sa LANGUE, sa PORTEE et sa SOURCE.

Remplace l'usage de hpo_terms.aliases_fr comme fourre-tout. Mesure du
2026-09-12 : cette colonne porte 30 897 formes dont 25 % sont ANGLAISES (les
synonymes HPO officiels y ont ete verses) — le nom de la colonne ment, et rien
ne distingue « bouche en triangle » (FR, equivalent) de « Triangular shaped
oral aperture » (EN, synonyme HPO EXACT).

Trois sources, jamais fusionnees en silence :
  obo    hp.obo officiel : nom + synonymes avec leur portee EXACT/NARROW/BROAD/RELATED
  maison hpo_terms.label_fr et aliases_fr, langue detectee, portee EXACT par defaut
  La colonne `source` permet de rejouer une passe sans toucher aux autres.

Sert deux lectures opposees :
  - une vignette FRANCAISE -> hpo_id (extraction de signes)
  - un signe de LIVRE ANGLAIS -> hpo_id (mapping syndromologie)

Ne traduit rien : un alias absent reste absent et sort dans --manquants, qui est
la liste de travail pour completer le francais.

Usage :
  python3 build_hpo_synonymes.py                  mesure seule
  python3 build_hpo_synonymes.py --apply          (re)construit la table
  python3 build_hpo_synonymes.py --manquants f.tsv  termes foetaux sans forme FR
"""
import argparse
import re
import sqlite3

DB = "/home/mathevet/Bureau/foeto_base/syndromes_foetaux.db"
OBO = "/home/mathevet/Bureau/akinator/orphadata_cache/hp.obo"

# marqueurs francais : diacritiques, ou mots-outils/medicaux qui n'existent pas en anglais
FR = re.compile(r"[àâäéèêëïîôöùûüÿçœæ]|\b(de|du|des|la|le|les|une|un|aux|avec|sans|dans|"
                r"anomalie|absence|petit|petite|grand|grande|court|courte|large|"
                r"hypoplasie|aplasie|malformation|fente|retard|trouble|atteinte)\b", re.I)


def langue(s):
    return "fr" if FR.search(s) else "en"


def load_obo(path):
    terms, cur = {}, None
    for line in open(path, encoding="utf-8"):
        line = line.rstrip("\n")
        if line == "[Term]":
            if cur and cur["id"]:
                terms[cur["id"]] = cur
            cur = {"id": None, "name": "", "syn": {}, "obsolete": False}
        elif line.startswith("[") and cur:
            if cur["id"]:
                terms[cur["id"]] = cur
            cur = None
        elif cur is not None:
            if line.startswith("id: HP:"):
                cur["id"] = line[4:].strip()
            elif line.startswith("name: "):
                cur["name"] = line[6:].strip()
                cur["obsolete"] = cur["name"].startswith("obsolete ")
            elif line.startswith("synonym: "):
                m = re.match(r'synonym: "(.*?)"\s+(EXACT|NARROW|BROAD|RELATED)', line)
                if m:
                    cur["syn"][m.group(1)] = m.group(2)
            elif line.startswith("is_obsolete: true"):
                cur["obsolete"] = True
    if cur and cur["id"]:
        terms[cur["id"]] = cur
    return {k: v for k, v in terms.items() if not v["obsolete"]}


def collect(c, obo):
    """(hpo_id, forme, langue, portee, source) dedoublonne sur (hpo_id, forme normalisee)."""
    seen, rows = set(), []

    def add(hid, forme, lang, portee, source):
        forme = (forme or "").strip()
        if not forme:
            return
        k = (hid, re.sub(r"\s+", " ", forme.lower()))
        if k in seen:
            return
        seen.add(k)
        rows.append((hid, forme, lang, portee, source))

    known = {r[0] for r in c.execute("select hpo_id from hpo_terms")}
    for hid, t in obo.items():
        if hid not in known:
            continue
        add(hid, t["name"], "en", "NAME", "obo")
        for forme, portee in t["syn"].items():
            add(hid, forme, langue(forme), portee, "obo")
    for hid, fr, al in c.execute("select hpo_id, label_fr, aliases_fr from hpo_terms"):
        if fr:
            add(hid, fr, langue(fr), "NAME", "maison")
        for forme in [x.strip() for x in (al or "").split("|") if x.strip()]:
            add(hid, forme, langue(forme), "EXACT", "maison")
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--manquants")
    a = ap.parse_args()
    c = sqlite3.connect(DB)
    rows = collect(c, load_obo(OBO))

    foetal = {r[0] for r in c.execute(
        "select hpo_id from hpo_terms where context in ('prenatal','both') and is_excluded=0")}
    par = {}
    for hid, forme, lang, portee, source in rows:
        d = par.setdefault(hid, {"fr": 0, "en": 0})
        d[lang] += 1
    nf = len(foetal)
    sans_fr = [h for h in foetal if par.get(h, {}).get("fr", 0) == 0]
    print(f"{len(rows)} formes pour {len(par)} termes HPO")
    print(f"  fr {sum(1 for r in rows if r[2]=='fr'):6d}   en {sum(1 for r in rows if r[2]=='en'):6d}")
    for s in ("obo", "maison"):
        print(f"  source {s:7s} {sum(1 for r in rows if r[4]==s):6d}")
    print(f"\ntermes fœtaux ({nf}) :")
    print(f"  avec au moins une forme FR : {nf-len(sans_fr):5d}  {(nf-len(sans_fr))*100/nf:5.1f} %")
    print(f"  SANS aucune forme FR       : {len(sans_fr):5d}  {len(sans_fr)*100/nf:5.1f} %")

    if a.manquants:
        lab = dict(c.execute("select hpo_id, label_en from hpo_terms"))
        df = dict(c.execute("select hpo_id, count(*) from syndrome_hpo group by 1"))
        liste = sorted(sans_fr, key=lambda h: -df.get(h, 0))
        with open(a.manquants, "w", encoding="utf-8") as f:
            f.write("hpo_id\tlabel_en\tsyndromes_portant_le_signe\tforme_fr_a_ecrire\n")
            for h in liste:
                f.write(f"{h}\t{lab.get(h,'')}\t{df.get(h,0)}\t\n")
        print(f"\n{len(liste)} termes sans français -> {a.manquants} (triés par nb de syndromes)")

    if a.apply:
        c.execute("DROP TABLE IF EXISTS hpo_synonymes")
        c.execute("""CREATE TABLE hpo_synonymes (
            hpo_id TEXT NOT NULL REFERENCES hpo_terms(hpo_id),
            forme TEXT NOT NULL, langue TEXT NOT NULL CHECK(langue IN ('fr','en')),
            portee TEXT NOT NULL, source TEXT NOT NULL,
            PRIMARY KEY (hpo_id, forme))""")
        c.executemany("INSERT OR IGNORE INTO hpo_synonymes VALUES (?,?,?,?,?)", rows)
        c.execute("CREATE INDEX idx_syn_forme ON hpo_synonymes(forme)")
        c.execute("CREATE INDEX idx_syn_langue ON hpo_synonymes(langue, portee)")
        c.commit()
        print(f"\nhpo_synonymes : {c.execute('select count(*) from hpo_synonymes').fetchone()[0]} lignes.")


if __name__ == "__main__":
    main()
