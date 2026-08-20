#!/usr/bin/env python3
"""Passe 2 : canonicaliser les valeurs de facettes produites par factorize_terms.py.

    python canonicalize_facets.py submit
    python canonicalize_facets.py status
    python canonicalize_facets.py collect

Batch API + contexte fixe : le vocabulaire ENTIER de la facette est mis en cache comme
préfixe partagé, et chaque requête ne traite qu'une tranche de valeurs. Le modèle voit
donc toujours tout le vocabulaire (cohérence des regroupements) sans qu'on paie le
préfixe à chaque requête, et aucune réponse n'a à porter 300 mappings d'un coup.
Ne touche pas la DB.
"""
import csv, json, os, sys
from collections import Counter, defaultdict
import anthropic

HERE = os.path.dirname(os.path.abspath(__file__))
IN_TSV = os.path.join(HERE, "factorisation.tsv")
OUT_TSV = os.path.join(HERE, "factorisation_canon.tsv")
BATCH_ID_FILE = os.path.join(HERE, ".canon_batch_id")
ENV_FILE = "/home/mathevet/Bureau/benchmark_foeto/.env_opus"
MODEL = "claude-opus-5"
SLICE = 60
FACETS = ("lesion", "site", "qualifieurs", "pattern")

API_KEY = None
if os.path.exists(ENV_FILE):
    for line in open(ENV_FILE):
        if line.strip().startswith("ANTHROPIC_API_KEY="):
            API_KEY = line.split("=", 1)[1].strip().strip('"')

CONSIGNES = {
    "lesion": """Ce sont des noms de lésions histologiques élémentaires du placenta.
Regroupe UNIQUEMENT les vraies synonymies : variantes orthographiques (chorioamnionite/chorioamniotite),
latin vs français (funisitis/funiculite), substantif vs processus (thrombus/thrombose),
singulier/pluriel, ordre des mots.
Ne regroupe PAS deux lésions cliniquement distinctes même si elles sont proches
(athérose ≠ nécrose fibrinoïde ; infarctus ≠ hématome).""",
    "site": """Ce sont des sièges anatomiques placentaires.
Regroupe UNIQUEMENT les désignations équivalentes du MÊME niveau de granularité.
Ne regroupe JAMAIS deux granularités différentes : « villosité » et « villosité terminale »
restent distincts, « vaisseau fœtal placentaire » et « capillaire villositaire » aussi.
En cas d'hésitation sur la granularité, ne regroupe pas.""",
    "qualifieurs": """Ce sont des modificateurs (temporalité, sévérité, étendue, stade, grade).
Regroupe les formes équivalentes (pluriels, casse, synonymes stricts).
Garde distincts les niveaux d'une même échelle : stade 1 ≠ stade 2, grade 1 ≠ stade 1.""",
    "pattern": """Ce sont des patterns clinico-pathologiques nommés.
Regroupe l'acronyme et sa forme développée (FIR = réponse inflammatoire fœtale),
et les variantes orthographiques. Forme canonique attendue : « Forme développée (ACRONYME) ».""",
}

SYSTEM = """Tu es fœtopathologiste, expert de la pathologie placentaire (Amsterdam, Benirschke & Baergen).

On te donne le vocabulaire brut d'une facette, extrait automatiquement de libellés de signes. Les mêmes notions y apparaissent sous plusieurs formulations. Ta tâche : proposer une FORME CANONIQUE et regrouper les variantes.

{consignes}

Le nombre entre parenthèses est le nombre d'occurrences — à contenu identique, préfère la formulation la plus correcte médicalement, pas simplement la plus fréquente.

Le vocabulaire COMPLET t'est donné pour que tes regroupements soient cohérents d'un bout à l'autre. On ne te demande de statuer que sur la TRANCHE indiquée : un groupe ne doit être renvoyé que si au moins une de ses variantes appartient à la tranche — mais il peut légitimement inclure des variantes situées hors de la tranche.

Ne renvoie QUE les groupes de 2 valeurs ou plus, et les valeurs isolées de la tranche dont tu changes la forme. Une valeur déjà canonique et sans variante ne doit pas apparaître.

Réponds UNIQUEMENT en JSON :
{{"groupes": [{{"canonique": "<forme retenue>", "variantes": ["<valeur brute>", ...]}}]}}"""


def load_rows():
    if not os.path.exists(IN_TSV):
        sys.exit("factorisation.tsv absent — lance factorize_terms.py collect")
    return list(csv.DictReader(open(IN_TSV), delimiter="\t"))


def values(rows, facet):
    if facet == "qualifieurs":
        return Counter(q for r in rows for q in r["qualifieurs"].split("|") if q)
    return Counter(r[facet] for r in rows if r[facet])


def build_requests(rows):
    reqs = []
    for facet in FACETS:
        counts = values(rows, facet)
        ordered = [v for v, _ in counts.most_common()]
        listing = "\n".join(f"- {v} ({counts[v]})" for v in ordered)
        # Préfixe fixe mis en cache : identique pour toutes les tranches de la facette.
        system = [
            {"type": "text", "text": SYSTEM.format(consignes=CONSIGNES[facet])},
            {"type": "text",
             "text": f"VOCABULAIRE COMPLET de la facette « {facet} » ({len(ordered)} valeurs) :\n\n{listing}",
             "cache_control": {"type": "ephemeral"}},
        ]
        for i in range(0, len(ordered), SLICE):
            chunk = ordered[i:i + SLICE]
            reqs.append({
                "custom_id": f"canon_{facet}_{i:04d}",
                "params": {
                    "model": MODEL, "max_tokens": 16000, "system": system,
                    "messages": [{"role": "user",
                                  "content": "TRANCHE à traiter :\n\n"
                                             + "\n".join(f"- {v}" for v in chunk)}],
                },
            })
    return reqs


def client():
    if not API_KEY:
        sys.exit("ANTHROPIC_API_KEY introuvable dans .env_opus")
    return anthropic.Anthropic(api_key=API_KEY)


def submit():
    rows = load_rows()
    reqs = build_requests(rows)
    for facet in FACETS:
        n = len(values(rows, facet))
        print(f"{facet:12s} {n:4d} valeurs -> {sum(1 for r in reqs if r['custom_id'].startswith(f'canon_{facet}_'))} tranches")
    batch = client().messages.batches.create(requests=reqs)
    open(BATCH_ID_FILE, "w").write(batch.id)
    print(f"\n{len(reqs)} requêtes | batch soumis : {batch.id} ({batch.processing_status})")


def status():
    b = client().messages.batches.retrieve(open(BATCH_ID_FILE).read().strip())
    c = b.request_counts
    print(f"{b.id} : {b.processing_status} | ok={c.succeeded} err={c.errored} "
          f"en cours={c.processing} expiré={c.expired}")


def apply_map(v, mapping):
    return mapping.get(v, v)


def _selfcheck():
    m = {"thrombose": "thrombus", "chorioamniotite": "chorioamnionite"}
    assert apply_map("thrombose", m) == "thrombus"
    assert apply_map("infarctus", m) == "infarctus"


def collect():
    _selfcheck()
    bid = open(BATCH_ID_FILE).read().strip()
    cl = client()
    if cl.messages.batches.retrieve(bid).processing_status != "ended":
        sys.exit("batch pas terminé")

    rows = load_rows()
    counts = {f: values(rows, f) for f in FACETS}
    maps, bad, cached = {f: {} for f in FACETS}, 0, 0
    for res in cl.messages.batches.results(bid):
        facet = res.custom_id.split("_")[1]
        if res.result.type != "succeeded":
            bad += 1
            continue
        u = res.result.message.usage
        cached += getattr(u, "cache_read_input_tokens", 0) or 0
        txt = next((b.text for b in res.result.message.content if b.type == "text"), "")
        try:
            groups = json.loads(txt[txt.find("{"):txt.rfind("}") + 1])["groupes"]
        except (json.JSONDecodeError, KeyError):
            bad += 1
            continue
        for g in groups:
            for v in g["variantes"]:
                # Une valeur vue dans deux tranches : on garde le premier verdict.
                if v in counts[facet] and v not in maps[facet]:
                    maps[facet][v] = g["canonique"]

    for facet in FACETS:
        m = {v: c for v, c in maps[facet].items() if v != c}
        maps[facet] = m
        with open(os.path.join(HERE, f"canon_{facet}.tsv"), "w") as f:
            f.write("brut\tcanonique\toccurrences\n")
            for v, c in sorted(m.items(), key=lambda x: -counts[facet][x[0]]):
                f.write(f"{v}\t{c}\t{counts[facet][v]}\n")
        reduced = len({apply_map(v, m) for v in counts[facet]})
        print(f"{facet:12s} {len(counts[facet]):4d} valeurs -> {reduced:4d} canoniques "
              f"({len(m)} variantes remappées)")

    with open(OUT_TSV, "w") as f:
        w = csv.DictWriter(f, delimiter="\t", fieldnames=list(rows[0].keys()))
        w.writeheader()
        for r in rows:
            r = dict(r)
            for facet in ("lesion", "site", "pattern"):
                r[facet] = apply_map(r[facet], maps[facet])
            r["qualifieurs"] = "|".join(sorted(
                apply_map(q, maps["qualifieurs"]) for q in r["qualifieurs"].split("|") if q))
            w.writerow(r)

    rows2 = list(csv.DictReader(open(OUT_TSV), delimiter="\t"))
    print(f"\n({bad} requêtes en échec, {cached} tokens lus depuis le cache)")
    for name, keyf in (("lésion+site+qualifieurs", lambda r: (r["lesion"], r["site"], r["qualifieurs"])),
                       ("lésion+site", lambda r: (r["lesion"], r["site"]))):
        groups = defaultdict(list)
        for r in rows2:
            if r["lesion"]:
                groups[keyf(r)].append(r)
        d = {k: v for k, v in groups.items() if len(v) > 1}
        print(f"doublons sur {name:24s}: {len(d):3d} tuples / {sum(len(v) for v in d.values()):3d} termes")
    print(f"-> {OUT_TSV}")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "submit"
    {"submit": submit, "status": status, "collect": collect}[cmd]()
