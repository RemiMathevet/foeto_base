#!/usr/bin/env python3
"""Passe 3 : rattacher les termes placenta à un référentiel médical, et lister les lacunes.

    python medical_pass.py prepare       # aperçu, aucun appel API
    python medical_pass.py submit
    python medical_pass.py status
    python medical_pass.py collect

Amsterdam n'est PAS le cadre universel : tumeurs, surcharges, dysplasie mésenchymateuse,
gémellaire, villites à étiologie identifiée et anatomie normale en sont hors périmètre.
Le modèle choisit donc parmi plusieurs référentiels et peut répondre hors_referentiel.
Les référentiels vivent dans referentiels_placenta.md, jamais dans ce fichier.
Ne touche pas la DB.
"""
import csv, json, os, re, sys
from collections import Counter
import anthropic

HERE = os.path.dirname(os.path.abspath(__file__))
IN_TSV = os.path.join(HERE, "factorisation_canon.tsv")
REFS_MD = os.path.join(HERE, "referentiels_placenta.md")
OUT_TSV = os.path.join(HERE, "rattachement_medical.tsv")
OUT_GAPS = os.path.join(HERE, "lacunes.tsv")
BATCH_ID_FILE = os.path.join(HERE, ".medical_batch_id")
ENV_FILE = "/home/mathevet/Bureau/benchmark_foeto/.env_opus"
MODEL = "claude-opus-5"
TERMS_PER_REQUEST = 15

API_KEY = None
if os.path.exists(ENV_FILE):
    for line in open(ENV_FILE):
        if line.strip().startswith("ANTHROPIC_API_KEY="):
            API_KEY = line.split("=", 1)[1].strip().strip('"')

SYSTEM = """Tu es fœtopathologiste, expert de la pathologie placentaire.

On te donne un vocabulaire de signes placentaires déjà factorisé en facettes (lésion, siège,
qualifieurs, pattern) et canonicalisé sur la forme. Il reste à le confronter à la LITTÉRATURE.

Le fichier de référentiels ci-dessous délimite le périmètre de chacun. Amsterdam est un
référentiel parmi d'autres : il ne couvre ni les tumeurs, ni les surcharges métaboliques,
ni la dysplasie mésenchymateuse, ni la pathologie gémellaire, ni les villites à étiologie
identifiée, ni l'anatomie et la maturation normales. Ne force JAMAIS un terme dans Amsterdam
au prétexte qu'il est placentaire : choisis le référentiel dont le périmètre le couvre
réellement, et réponds hors_referentiel quand aucun ne le fait. Un hors_referentiel motivé
vaut mieux qu'un rattachement faux.

Beaucoup de termes ne sont pas des lésions : structures anatomiques normales, stades de
maturation normale. Ce n'est pas un défaut, c'est leur nature — role="structure".

Pour chaque terme, renvoie :
- "id"            : l'identifiant FOETO fourni
- "referentiel"   : AMSTERDAM | BENIRSCHKE | REDLINE | GEMELLAIRE | ACCRETA | HORS_REFERENTIEL
- "entite"        : l'entité nommée de ce référentiel dont relève le terme (ex. "MVM —
                    artériopathie déciduale", "FIR stade 3"). "" si hors_referentiel.
- "role"          : le rapport du terme à cette entité, un seul parmi
                    "synonyme"      — le terme EST l'entité
                    "critere"       — le terme est un critère diagnostique de l'entité
                    "manifestation" — le terme s'observe dans l'entité sans en être critère
                    "stade"         — le terme est un stade ou un grade de l'entité
                    "structure"     — structure anatomique ou maturation normale, pas une lésion
                    "hors"          — aucun rapport
- "stade"         : la gradation normalisée si le libellé en porte une (ex. "MIR stade 2 grade 1",
                    "FVM haut grade", "VUE bas grade"). "" sinon. Ne l'infère PAS.
- "conforme"      : "oui" | "obsolete" (terminologie remplacée) | "non_standard" (compréhensible
                    mais absent de la littérature) | "erreur" (médicalement faux ou confondant)
- "label_propose" : le libellé à retenir si conforme != "oui". "" sinon.
- "source"        : la référence précise (ex. "Khong 2016, MVM"). "" si hors_referentiel.
- "probleme"      : phrase courte SI le terme pose un problème de fond — libellé composite
                    mêlant plusieurs axes, macroscopie mélangée à la microscopie, énoncé
                    négatif, fourre-tout, granularité incohérente avec le reste du vocabulaire.
                    "" sinon.

Le vocabulaire COMPLET t'est donné pour que tes rattachements soient cohérents d'un bout à
l'autre : deux termes de même contenu doivent recevoir la même entité et le même référentiel.
On ne te demande de statuer que sur la TRANCHE indiquée.

Réponds UNIQUEMENT en JSON :
{"termes": [{"id": "...", "referentiel": "...", "entite": "...", "role": "...", "stade": "...", "conforme": "...", "label_propose": "...", "source": "...", "probleme": "..."}]}"""

SYSTEM_GAPS = """Tu es fœtopathologiste, expert de la pathologie placentaire.

On te donne le vocabulaire COMPLET des signes placentaires d'une base de données, et un
fichier de référentiels. Ta tâche : trouver ce qui MANQUE.

On te demande de statuer sur le seul référentiel « {ref} ». Parcours les entités nommées de
ce référentiel et signale celles qu'AUCUN terme du vocabulaire ne recouvre, ou que le
vocabulaire ne recouvre que partiellement (l'entité chapeau existe mais pas ses variantes,
ou l'inverse).

Exemple du type de lacune attendu : la base contient « artériopathie déciduale » et
« athérose aiguë » mais pas « artériopathie déciduale à cellules spumeuses ».

Sois exigeant sur la réalité de la lacune : un terme formulé autrement n'est pas une lacune.
Ne signale que ce qui est vraiment absent.

Réponds UNIQUEMENT en JSON :
{{"lacunes": [{{"entite": "<entité absente>", "referentiel": "{ref}", "raison": "<ce que le vocabulaire a ou n'a pas>", "importance": "haute|moyenne|basse"}}]}}"""


def load_rows():
    if not os.path.exists(IN_TSV):
        sys.exit("factorisation_canon.tsv absent — lance canonicalize_facets.py collect")
    return list(csv.DictReader(open(IN_TSV), delimiter="\t"))


def referentiels():
    if not os.path.exists(REFS_MD):
        sys.exit("referentiels_placenta.md absent")
    return open(REFS_MD).read()


def ref_codes(md):
    """Les codes sont les titres de niveau 2 du fichier de référentiels : une seule source."""
    return [m for m in re.findall(r"^## ([A-Z_]+)$", md, re.M) if m != "HORS_REFERENTIEL"]


def fmt(r):
    facets = " | ".join(f"{k}={r[k]}" for k in ("lesion", "site", "qualifieurs", "pattern") if r[k])
    s = f"{r['id']} — \"{r['label_fr']}\"\n    niveau: {r['niveau']} | compartiment: {r['compartiment']}"
    if facets:
        s += f"\n    facettes: {facets}"
    if r["doute"]:
        s += f"\n    doute passe 1: {r['doute']}"
    return s


def prefix(rows, md):
    """Préfixe fixe mis en cache : référentiels + vocabulaire entier, partagé par
    toutes les requêtes du batch, celles de rattachement comme celles de lacunes."""
    listing = "\n".join(f"- {r['label_fr']} [{r['niveau']}]" for r in rows)
    return {"type": "text",
            "text": f"=== RÉFÉRENTIELS ===\n\n{md}\n\n\n"
                    f"=== VOCABULAIRE COMPLET ({len(rows)} termes) ===\n\n{listing}",
            "cache_control": {"type": "ephemeral"}}


def build_requests(rows, md):
    pre = prefix(rows, md)
    reqs = []
    for i in range(0, len(rows), TERMS_PER_REQUEST):
        chunk = rows[i:i + TERMS_PER_REQUEST]
        reqs.append({
            "custom_id": f"term_{i:04d}",
            "params": {
                "model": MODEL, "max_tokens": 16000,
                "system": [{"type": "text", "text": SYSTEM}, pre],
                "messages": [{"role": "user",
                              "content": "TRANCHE à rattacher :\n\n"
                                         + "\n\n".join(fmt(r) for r in chunk)}],
            },
        })
    for code in ref_codes(md):
        reqs.append({
            "custom_id": f"gap_{code}",
            "params": {
                "model": MODEL, "max_tokens": 16000,
                "system": [{"type": "text", "text": SYSTEM_GAPS.format(ref=code)}, pre],
                "messages": [{"role": "user",
                              "content": f"Quelles entités du référentiel {code} manquent "
                                         f"au vocabulaire ?"}],
            },
        })
    return reqs


def client():
    if not API_KEY:
        sys.exit("ANTHROPIC_API_KEY introuvable dans .env_opus")
    return anthropic.Anthropic(api_key=API_KEY)


def parse(res):
    """Opus renvoie un ThinkingBlock en content[0] : sélectionner sur le type."""
    txt = next((b.text for b in res.result.message.content if b.type == "text"), "")
    return json.loads(txt[txt.find("{"):txt.rfind("}") + 1])


def _selfcheck():
    md = "## AMSTERDAM\nblah\n## BENIRSCHKE\nblah\n## HORS_REFERENTIEL\nblah\n"
    assert ref_codes(md) == ["AMSTERDAM", "BENIRSCHKE"], ref_codes(md)
    assert ref_codes(referentiels()), "aucun référentiel lu dans le .md"


def prepare():
    _selfcheck()
    rows, md = load_rows(), referentiels()
    reqs = build_requests(rows, md)
    n_gap = sum(1 for r in reqs if r["custom_id"].startswith("gap_"))
    print(f"{len(rows)} termes -> {len(reqs) - n_gap} requêtes de rattachement "
          f"+ {n_gap} requêtes de lacunes ({', '.join(ref_codes(md))})")
    print(f"préfixe caché : ~{len(prefix(rows, md)['text']) // 4} tokens")
    print(f"niveaux: {Counter(r['niveau'] for r in rows).most_common()}")
    print("\n--- aperçu tranche 1 ---")
    print(reqs[0]["params"]["messages"][0]["content"][:700])
    return rows, reqs


def submit():
    _, reqs = prepare()
    batch = client().messages.batches.create(requests=reqs)
    open(BATCH_ID_FILE, "w").write(batch.id)
    print(f"\n{len(reqs)} requêtes | batch soumis : {batch.id} ({batch.processing_status})")


def status():
    b = client().messages.batches.retrieve(open(BATCH_ID_FILE).read().strip())
    c = b.request_counts
    print(f"{b.id} : {b.processing_status} | ok={c.succeeded} err={c.errored} "
          f"en cours={c.processing} expiré={c.expired}")


def collect():
    _selfcheck()
    bid = open(BATCH_ID_FILE).read().strip()
    cl = client()
    if cl.messages.batches.retrieve(bid).processing_status != "ended":
        sys.exit("batch pas terminé")

    src = {r["id"]: r for r in load_rows()}
    out, gaps, bad, cached = [], [], 0, 0
    for res in cl.messages.batches.results(bid):
        if res.result.type != "succeeded":
            bad += 1
            print(f"  échec {res.custom_id}: {res.result.type}")
            continue
        u = res.result.message.usage
        cached += getattr(u, "cache_read_input_tokens", 0) or 0
        try:
            d = parse(res)
        except (json.JSONDecodeError, KeyError, ValueError):
            bad += 1
            print(f"  JSON illisible {res.custom_id} "
                  f"(stop={res.result.message.stop_reason}, out={u.output_tokens})")
            continue
        (gaps if res.custom_id.startswith("gap_") else out).extend(
            d.get("lacunes" if res.custom_id.startswith("gap_") else "termes") or [])

    cols = ["id", "referentiel", "entite", "role", "stade", "conforme",
            "label_propose", "source", "probleme"]
    with open(OUT_TSV, "w") as f:
        f.write("\t".join(cols + ["label_fr"]) + "\n")
        for r in out:
            t = src.get(r.get("id"))
            if not t:
                continue
            cells = [str(r.get(c) or "").replace("\t", " ") for c in cols] + [t["label_fr"]]
            f.write("\t".join(cells) + "\n")

    with open(OUT_GAPS, "w") as f:
        f.write("referentiel\timportance\tentite\traison\n")
        rank = {"haute": 0, "moyenne": 1, "basse": 2}
        for g in sorted(gaps, key=lambda x: (x.get("referentiel", ""),
                                             rank.get(x.get("importance"), 3))):
            f.write("\t".join(str(g.get(c) or "").replace("\t", " ")
                              for c in ("referentiel", "importance", "entite", "raison")) + "\n")

    print(f"\n{len(out)}/{len(src)} termes rattachés ({bad} requêtes en échec, "
          f"{cached} tokens lus depuis le cache)")
    for col in ("referentiel", "role", "conforme"):
        print(f"{col:14s} {Counter(r.get(col) or '?' for r in out).most_common()}")
    print(f"termes à renommer   : {sum(1 for r in out if r.get('conforme') not in ('oui', None))}")
    print(f"termes à problème   : {sum(1 for r in out if r.get('probleme'))}")
    print(f"lacunes             : {len(gaps)} "
          f"({sum(1 for g in gaps if g.get('importance') == 'haute')} de haute importance)")
    print(f"-> {OUT_TSV}, {OUT_GAPS}")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "prepare"
    {"prepare": prepare, "submit": submit, "status": status, "collect": collect}[cmd]()
