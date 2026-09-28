#!/usr/bin/env python3
"""HPO complète FOETO v2 : propose un code HPO par signe, n'écrit que les nets.

Candidats : (1) HPO des termes v1 rattachés en « exacte » au signe (foeto_hpo — table
sans provenance, en partie attribuée par LLM : jamais reprise sans contrôle) ;
(2) libellé du signe = libellé ou synonyme HPO (hpo_terms, fr). Net = égalité avec
le libellé OFFICIEL HPO (fr ou en), jamais un synonyme ; libellés normalisés (accents, casse, ponctuation, « du/de la » neutres). Le reste
part dans hpo_a_arbitrer.tsv. Écrit le champ "hpo" dans v2/sources/*.json, sans
jamais écraser un hpo déjà posé.
"""
import json, re, sqlite3, unicodedata
from pathlib import Path

ICI = Path(__file__).parent
V1 = ICI.parent / "syndromes_foetaux.db"
V2 = ICI.parent / "foeto_v2.db"


def cle(s):
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower()
    s = re.split(r" — | \(", s)[0]   # précision entre parenthèses ou après un tiret : ignorée ;
    # une virgule énumère plusieurs constats : jamais coupée (sinon le 1er emporte le code)
    s = re.sub(r"\b(du|de la|des|de|d|la|le|les|l)\b", " ", re.sub(r"[^a-z0-9 ]", " ", s))
    return " ".join(s.split())


v1 = sqlite3.connect("file:%s?mode=ro" % V1, uri=True)
v2 = sqlite3.connect("file:%s?mode=ro" % V2, uri=True)
hpo = {}
for i, fr, en, al in v1.execute("select hpo_id, label_fr, label_en, aliases_fr from hpo_terms where is_excluded = 0"):
    # (libellé affiché, libellés OFFICIELS fr/en, synonymes) — les synonymes fr de la base
    # sont trop larges (« bébé collodion » sous Hyperkeratosis) : ils proposent, ne tranchent pas
    hpo[i] = (fr or en, {cle(x) for x in (fr, en) if x}, {cle(x) for x in (al or "").split("|") if x.strip()})
par_libelle = {}
for i, (_, off, syn) in hpo.items():
    for c in off | syn:
        par_libelle.setdefault(c, set()).add(i)

nets, arbitrer = {}, []
for sid, org, k, l, deja in v2.execute("select id, organe, k, label_fr, hpo from signes where type != 'AXE'"):
    if deja:
        continue
    cands = {}
    for (vid,) in v2.execute("select v1_id from correspondance_v1 where v2_id = ? and qualite = 'exacte'", (sid,)):
        for (h,) in v1.execute("select hpo_id from foeto_hpo where foeto_id = ?", (vid,)):
            cands.setdefault(h, set()).add("foeto_hpo via " + vid)
    for h in par_libelle.get(cle(l), ()):
        cands.setdefault(h, set()).add("libellé")
    exacts = [h for h in cands if h in hpo and cle(l) in hpo[h][1]]   # libellé officiel seulement
    if len(exacts) == 1:
        nets[(org, k)] = exacts[0]
    for h, orig in sorted(cands.items()):
        if (org, k) in nets and nets[(org, k)] == h:
            continue
        arbitrer.append([org, k, l, h, hpo.get(h, ("?",))[0], " ; ".join(sorted(orig))])

for p in sorted((ICI / "sources").glob("*.json")):
    d = json.loads(p.read_text(encoding="utf-8"))
    n = 0
    for x in d["signes"]:
        h = nets.get((d["organe"], x["k"]))
        if h and not x.get("hpo"):
            x["hpo"] = h
            n += 1
    if n:
        p.write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")
        print("%-20s %d HPO nets écrits" % (d["organe"], n))
(ICI / "hpo_a_arbitrer.tsv").write_text(
    "organe\tclé\tlibellé v2\tHPO proposé\tlibellé HPO\torigine\n" + "".join("\t".join(r) + "\n" for r in arbitrer),
    encoding="utf-8")
print("nets : %d · à arbitrer : %d lignes" % (len(nets), len(arbitrer)))
