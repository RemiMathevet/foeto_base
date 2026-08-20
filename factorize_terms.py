#!/usr/bin/env python3
"""Passe 1 de factorisation : décomposer les libellés FOETO en facettes (texte libre).

    python factorize_terms.py prepare        # aperçu, aucun appel API
    python factorize_terms.py submit
    python factorize_terms.py status
    python factorize_terms.py collect        # -> factorisation.tsv + vocabulaire_facettes.txt

Objectif : observer le vocabulaire de facettes qui émerge AVANT de figer une liste
contrôlée. N'écrit rien dans syndromes_foetaux.db.
"""
import json, os, re, sqlite3, sys
from collections import Counter
import anthropic

HERE = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(HERE, "syndromes_foetaux.db")
OUT_TSV = os.path.join(HERE, "factorisation.tsv")
OUT_VOCAB = os.path.join(HERE, "vocabulaire_facettes.txt")
BATCH_ID_FILE = os.path.join(HERE, ".factorize_batch_id")
ENV_FILE = "/home/mathevet/Bureau/benchmark_foeto/.env_opus"

MODEL = "claude-opus-5"
TERMS_PER_REQUEST = 15
SCOPE = "FOETO:PP.%"

API_KEY = None
if os.path.exists(ENV_FILE):
    for line in open(ENV_FILE):
        if line.strip().startswith("ANTHROPIC_API_KEY="):
            API_KEY = line.split("=", 1)[1].strip().strip('"')

SYSTEM_PROMPT = """Tu es fœtopathologiste, expert de la pathologie placentaire (critères d'Amsterdam, Benirschke & Baergen, Khong).

On te donne des termes d'un vocabulaire de signes placentaires. Ce vocabulaire a grossi par accrétion : ses libellés sont des PHRASES qui mélangent plusieurs axes d'information (la lésion, son siège, son stade, le pattern clinico-pathologique auquel elle appartient). Résultat : la même entité y apparaît sous plusieurs formulations, à des niveaux d'abstraction différents.

Ta tâche : DÉCOMPOSER chaque libellé en facettes. Tu ne juges pas, tu ne compares pas les termes entre eux, tu ne proposes aucune fusion. Tu factorises.

Facettes à extraire :
- "lesion"  : l'altération histologique élémentaire, en syntagme nominal court et nu, débarrassé du siège et des qualifieurs (ex. "cellules spumeuses pariétales", "nécrose fibrinoïde pariétale", "dépôt de fibrinoïde"). null si le terme ne décrit pas une lésion.
- "site"    : la structure anatomique concernée, la plus précise que le libellé permette (ex. "artère spiralée déciduale", "villosité terminale", "plaque basale"). null si absent du libellé.
- "qualifieurs" : liste des modificateurs — temporalité (aigu/chronique/en organisation), sévérité, étendue (focal/diffus/massif), stade, grade, coloration. Liste vide si aucun.
- "pattern" : le pattern clinico-pathologique nommé auquel le terme se réfère EXPLICITEMENT dans son libellé (MVM, FVM, NIDF, VUE, chorioamnionite, abruptio...). null sinon. Ne l'infère PAS : uniquement s'il est dans le libellé.
- "niveau"  : un seul parmi
    "element"    — une lésion élémentaire observable au microscope
    "entite"     — une entité diagnostique nommée, qui regroupe/définit des lésions élémentaires
    "pattern"    — un pattern clinico-pathologique global (ensemble d'entités)
    "structure"  — une structure anatomique normale ou un repère architectural, pas une lésion
    "maturation" — un stade de développement ou de maturation normale
- "doute"   : une phrase courte SI le libellé est trop vague, ambigu, ou si tu ne peux pas factoriser proprement. "" sinon.

Règles :
- N'invente rien qui ne soit pas dans le libellé (ou dans la description microscopique quand elle est fournie).
- Un même contenu clinique doit produire les mêmes chaînes de facettes d'un terme à l'autre : sois régulier dans ta formulation, c'est ce qui permettra de repérer les redondances ensuite.
- Français, minuscules, pas d'article initial.

Réponds UNIQUEMENT en JSON :
{"termes": [{"id": "<FOETO:id>", "lesion": "...|null", "site": "...|null", "qualifieurs": [...], "pattern": "...|null", "niveau": "...", "doute": "..."}]}"""


def load_terms():
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    rows = conn.execute("""
        SELECT id, organe, axis, annotation_type, label_fr, label_en, cr_description
        FROM foeto_terms WHERE id LIKE ? ORDER BY organe, id
    """, (SCOPE,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def fmt(t):
    s = f"{t['id']} — \"{t['label_fr']}\""
    if t.get("label_en"):
        s += f" | EN: {t['label_en']}"
    s += f"\n    compartiment: {t['organe']} | axe: {t['axis']}"
    if t.get("cr_description"):
        s += f"\n    description micro: {t['cr_description'][:300]}"
    return s


def build_requests(terms):
    reqs = []
    for i in range(0, len(terms), TERMS_PER_REQUEST):
        chunk = terms[i:i + TERMS_PER_REQUEST]
        reqs.append({
            "custom_id": f"fact_{i:04d}",
            "params": {
                "model": MODEL,
                "max_tokens": 8192,
                "system": SYSTEM_PROMPT,
                "messages": [{"role": "user",
                              "content": "Factorise ces termes :\n\n" + "\n\n".join(fmt(t) for t in chunk)}],
            },
        })
    return reqs


def client():
    if not API_KEY:
        sys.exit("ANTHROPIC_API_KEY introuvable dans .env_opus")
    return anthropic.Anthropic(api_key=API_KEY)


def prepare():
    terms = load_terms()
    reqs = build_requests(terms)
    print(f"{len(terms)} termes ({SCOPE}) -> {len(reqs)} requêtes de {TERMS_PER_REQUEST}")
    print(Counter(t["organe"] for t in terms).most_common())
    print("\n--- aperçu requête 1 ---")
    print(reqs[0]["params"]["messages"][0]["content"][:900])
    return terms, reqs


def submit():
    _, reqs = prepare()
    batch = client().messages.batches.create(requests=reqs)
    open(BATCH_ID_FILE, "w").write(batch.id)
    print(f"\nbatch soumis : {batch.id} ({batch.processing_status})")


def status():
    b = client().messages.batches.retrieve(open(BATCH_ID_FILE).read().strip())
    c = b.request_counts
    print(f"{b.id} : {b.processing_status} | ok={c.succeeded} err={c.errored} "
          f"en cours={c.processing} expiré={c.expired}")


def collect():
    bid = open(BATCH_ID_FILE).read().strip()
    cl = client()
    if cl.messages.batches.retrieve(bid).processing_status != "ended":
        sys.exit("batch pas terminé")

    src = {t["id"]: t for t in load_terms()}
    out, bad = [], 0
    for res in cl.messages.batches.results(bid):
        if res.result.type != "succeeded":
            bad += 1
            continue
        txt = next((b.text for b in res.result.message.content if b.type == "text"), "")
        txt = txt[txt.find("{"):txt.rfind("}") + 1]
        try:
            out.extend(json.loads(txt)["termes"])
        except (json.JSONDecodeError, KeyError):
            bad += 1

    with open(OUT_TSV, "w") as f:
        f.write("id\tniveau\tlesion\tsite\tqualifieurs\tpattern\tcompartiment\tlabel_fr\tdoute\n")
        for r in out:
            t = src.get(r.get("id"))
            if not t:
                continue
            q = "|".join(r.get("qualifieurs") or [])
            cells = [r["id"], r.get("niveau") or "", r.get("lesion") or "", r.get("site") or "",
                     q, r.get("pattern") or "", t["organe"], t["label_fr"], r.get("doute") or ""]
            f.write("\t".join(str(c).replace("\t", " ") for c in cells) + "\n")

    # Le livrable réel : le vocabulaire qui émerge, pour décider de la liste contrôlée.
    with open(OUT_VOCAB, "w") as f:
        for facet in ("niveau", "lesion", "site", "pattern"):
            vals = Counter(r.get(facet) for r in out if r.get(facet))
            f.write(f"\n=== {facet} — {len(vals)} valeurs distinctes / {sum(vals.values())} occurrences\n")
            for v, n in vals.most_common():
                f.write(f"{n:5d}  {v}\n")
        quals = Counter(q for r in out for q in (r.get("qualifieurs") or []))
        f.write(f"\n=== qualifieurs — {len(quals)} valeurs distinctes\n")
        for v, n in quals.most_common():
            f.write(f"{n:5d}  {v}\n")

    # Redondances mécaniques : même (lésion, site, qualifieurs) = même chose.
    tuples = Counter((r.get("lesion"), r.get("site"), "|".join(sorted(r.get("qualifieurs") or [])))
                     for r in out if r.get("lesion"))
    dupes = {k: n for k, n in tuples.items() if n > 1}
    print(f"{len(out)} termes factorisés ({bad} requêtes en échec) -> {OUT_TSV}, {OUT_VOCAB}")
    print(f"niveaux: {Counter(r.get('niveau') for r in out).most_common()}")
    print(f"tuples (lésion,site,qualif) identiques sur >1 terme : {len(dupes)} "
          f"({sum(dupes.values())} termes concernés)")
    print(f"termes avec doute : {sum(1 for r in out if r.get('doute'))}")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "prepare"
    {"prepare": prepare, "submit": submit, "status": status, "collect": collect}[cmd]()
