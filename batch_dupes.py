#!/usr/bin/env python3
"""Arbitrage des paires de termes FOETO redondants via batch API Opus.

    python batch_dupes.py prepare    # trie auto / LLM, écrit dupe_auto.tsv
    python batch_dupes.py submit
    python batch_dupes.py status
    python batch_dupes.py collect    # -> dupe_verdicts.tsv (n'écrit RIEN en DB)

L'application des fusions est un script séparé : rien ici ne touche syndrome_foeto.
"""
import json, os, sqlite3, sys
import anthropic

HERE = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(HERE, "syndromes_foetaux.db")
CANDIDATES = os.path.join(HERE, "dupe_candidates.json")
AUTO_TSV = os.path.join(HERE, "dupe_auto.tsv")
VERDICTS_TSV = os.path.join(HERE, "dupe_verdicts.tsv")
BATCH_ID_FILE = os.path.join(HERE, ".dupes_batch_id")
ENV_FILE = "/home/mathevet/Bureau/benchmark_foeto/.env_opus"

MODEL = "claude-opus-5"
PAIRS_PER_REQUEST = 12

API_KEY = None
if os.path.exists(ENV_FILE):
    for line in open(ENV_FILE):
        if line.strip().startswith("ANTHROPIC_API_KEY="):
            API_KEY = line.split("=", 1)[1].strip().strip('"')

SYSTEM_PROMPT = """Tu es fœtopathologiste, expert de la terminologie lésionnelle placentaire et fœtale (Amsterdam criteria, ISSHP, terminologie de Benirschke/Baergen, HPO).

On te donne des PAIRES de termes issus d'un vocabulaire de signes fœtopathologiques qui a grossi par accrétion et contient des redondances. Pour chaque paire, tranche.

VERDICTS possibles :
- "fusion"   : les deux termes désignent EXACTEMENT la même entité lésionnelle. Un seul doit survivre.
- "parent"   : l'un est l'entité générique (phénotype, syndrome lésionnel) et l'autre un de ses signes constitutifs ou une de ses variantes. Ne pas fusionner : hiérarchiser.
- "distinct" : entités différentes, même si la formulation est proche. C'est le verdict par défaut en cas de nuance clinique réelle.
- "incertain": tu ne peux pas trancher sans le contexte d'usage. N'hésite pas à l'utiliser.

PIÈGES à ne pas rater :
- Des ANTONYMES peuvent avoir un cosinus élevé ("défaut de remodelage" vs "remodelage physiologique") : c'est "distinct".
- Un même libellé sous deux organes/compartiments différents peut être une duplication délibérée décrivant deux localisations distinctes (ex. paroi artérielle déciduale du parenchyme vs de la plaque basale). Regarde l'axe et le compartiment avant de conclure à "fusion".
- Des signes distincts d'un même phénotype (ex. athérose aiguë, défaut de remodelage, nécrose fibrinoïde pariétale relèvent tous de l'artériopathie déciduale) NE se fusionnent PAS : verdict "parent" si l'un des deux est l'entité chapeau, "distinct" si aucun des deux ne l'est.
- Une différence de gradation, de stade ou de sévérité = "distinct".

SURVIVANT (pour "fusion") ou GÉNÉRIQUE (pour "parent") : donne l'id à conserver. À contenu clinique égal, préfère le libellé le plus correct en français et le mieux ancré dans la nomenclature de référence — pas simplement le plus utilisé.

Réponds UNIQUEMENT en JSON :
{"verdicts": [{"pair": "<pair_id>", "verdict": "fusion|parent|distinct|incertain", "keep": "<FOETO:id ou null>", "raison": "<une ligne, en français>"}]}"""


def load_pairs():
    if not os.path.exists(CANDIDATES):
        sys.exit("dupe_candidates.json absent — lance d'abord prefilter_dupes.py --cross-organ")
    pairs = json.load(open(CANDIDATES))
    for n, p in enumerate(pairs):
        p["pair_id"] = f"P{n:04d}"
    return pairs


def split_auto(pairs):
    """Auto = variante orthographique dans le MÊME compartiment et le MÊME axe.
    Tout ce qui traverse un organe ou un axe part à l'arbitrage : un libellé identique
    sous deux compartiments peut être une duplication voulue."""
    auto, llm = [], []
    for p in pairs:
        a, b = p["a"], p["b"]
        if (p["verdict"] == "orthographe" and a["organe"] == b["organe"]
                and a["axis"] == b["axis"]):
            auto.append(p)
        else:
            llm.append(p)
    return auto, llm


def fmt_term(t):
    en = f" | EN: {t['label_en']}" if t.get("label_en") else ""
    typ = f" | type: {t['annotation_type']}" if t.get("annotation_type") else ""
    return (f"{t['id']} — \"{t['label_fr']}\"{en}\n"
            f"      compartiment: {t['organe']} | axe: {t['axis']}{typ}"
            f" | usages: {t['n_synd']} syndromes, {t['n_hpo']} HPO")


def build_requests(pairs):
    reqs = []
    for i in range(0, len(pairs), PAIRS_PER_REQUEST):
        chunk = pairs[i:i + PAIRS_PER_REQUEST]
        blocks = [f"[{p['pair_id']}] cosinus={p['cos']}\n  A) {fmt_term(p['a'])}\n  B) {fmt_term(p['b'])}"
                  for p in chunk]
        reqs.append({
            "custom_id": f"dupes_{i:04d}",
            "params": {
                "model": MODEL,
                "max_tokens": 8192,
                "system": SYSTEM_PROMPT,
                "messages": [{"role": "user",
                              "content": "Tranche ces paires :\n\n" + "\n\n".join(blocks)}],
            },
        })
    return reqs


def client():
    if not API_KEY:
        sys.exit("ANTHROPIC_API_KEY introuvable dans .env_opus")
    return anthropic.Anthropic(api_key=API_KEY)


def prepare():
    pairs = load_pairs()
    auto, llm = split_auto(pairs)
    with open(AUTO_TSV, "w") as f:
        f.write("pair\tcos\torgane\tkeep_id\tkeep_label\tdrop_id\tdrop_label\tkeep_usages\tdrop_usages\n")
        for p in auto:
            a, b = p["a"], p["b"]
            k, d = (a, b) if (a["n_synd"] + a["n_hpo"]) >= (b["n_synd"] + b["n_hpo"]) else (b, a)
            f.write(f"{p['pair_id']}\t{p['cos']}\t{k['organe']}\t{k['id']}\t{k['label_fr']}\t"
                    f"{d['id']}\t{d['label_fr']}\t{k['n_synd']}s/{k['n_hpo']}h\t{d['n_synd']}s/{d['n_hpo']}h\n")
    print(f"{len(pairs)} paires | auto (survivant = plus d'usages) : {len(auto)} -> {AUTO_TSV}")
    print(f"arbitrage LLM : {len(llm)} paires -> {len(build_requests(llm))} requêtes batch")
    return auto, llm


def submit():
    _, llm = prepare()
    reqs = build_requests(llm)
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

    pairs = {p["pair_id"]: p for p in load_pairs()}
    rows, bad = [], 0
    for res in cl.messages.batches.results(bid):
        if res.result.type != "succeeded":
            bad += 1
            continue
        txt = res.result.message.content[0].text
        txt = txt[txt.find("{"):txt.rfind("}") + 1]
        try:
            for v in json.loads(txt)["verdicts"]:
                rows.append(v)
        except (json.JSONDecodeError, KeyError):
            bad += 1

    with open(VERDICTS_TSV, "w") as f:
        f.write("pair\tverdict\tcos\tkeep_id\tkeep_label\tautre_id\tautre_label\torganes\traison\n")
        for v in sorted(rows, key=lambda x: x.get("verdict", "")):
            p = pairs.get(v.get("pair"))
            if not p:
                continue
            a, b = p["a"], p["b"]
            keep = v.get("keep")
            other = b if keep == a["id"] else a
            klab = a["label_fr"] if keep == a["id"] else (b["label_fr"] if keep == b["id"] else "")
            f.write(f"{v['pair']}\t{v.get('verdict')}\t{p['cos']}\t{keep or ''}\t{klab}\t"
                    f"{other['id']}\t{other['label_fr']}\t{a['organe']}/{b['organe']}\t"
                    f"{v.get('raison', '').replace(chr(9), ' ')}\n")

    from collections import Counter
    print(f"{len(rows)} verdicts ({bad} requêtes en échec) -> {VERDICTS_TSV}")
    print(Counter(v.get("verdict") for v in rows).most_common())


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "prepare"
    {"prepare": prepare, "submit": submit, "status": status, "collect": collect}[cmd]()
