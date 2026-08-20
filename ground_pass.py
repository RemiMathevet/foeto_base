#!/usr/bin/env python3
"""Passe B : refaire le rattachement médical des 650 termes placentaires, ANCRÉ sur le corpus.

    python ground_pass.py prepare      # aperçu + coût, aucun appel API
    python ground_pass.py submit
    python ground_pass.py status
    python ground_pass.py collect

medical_pass.py a produit rattachement_medical.tsv SANS corpus : son champ `source`
(« Khong 2016, MVM ») est une citation paramétrique, invérifiable, et la même passe a
inventé deux troubles de maturation de Vogel qui n'existent dans aucun ouvrage. On refait
donc le rattachement avec les extraits sous les yeux, et le modèle doit produire un
VERBATIM copié du corpus, vérifié mécaniquement par collect().

Les 29 termes créés par la passe A ne repassent pas : ils sortent déjà du corpus avec un
verbatim vérifié. Regrounder ne ferait que payer deux fois la même preuve.

Ne touche pas la DB.
"""
import csv, json, os, sqlite3, sys
from collections import Counter
import anthropic

from gap_pass import client, fmt_evidence, norm, parse, rare_anchors, referentiels

HERE = os.path.dirname(os.path.abspath(__file__))
CANON_TSV = os.path.join(HERE, "factorisation_canon.tsv")
FOETO_DB = os.path.join(HERE, "syndromes_foetaux.db")
OUT_TSV = os.path.join(HERE, "rattachement_ancre.tsv")
EVIDENCE_JSON = os.path.join(HERE, ".ground_evidence.json")
RESULTS_JSON = os.path.join(HERE, ".ground_results.json")
BATCH_ID_FILE = os.path.join(HERE, ".ground_batch_id")
MODEL = "claude-opus-5"
TERMS_PER_REQUEST = 15
EVIDENCE_K = 6

SYSTEM = """Tu es fœtopathologiste, expert de la pathologie placentaire.

On te donne un vocabulaire de signes placentaires déjà factorisé en facettes, et surtout des
EXTRAITS RÉELS du corpus (Benirschke, Khong 2019, Vogel & Turowski 2019, consensus
d'Amsterdam). Une passe précédente a fait ce travail DE MÉMOIRE, sans corpus : elle a produit
des références invérifiables et inventé des entités inexistantes. Cette fois, tout jugement
s'appuie sur les extraits.

Le fichier de référentiels délimite le périmètre de chacun. Amsterdam est un référentiel
parmi d'autres : il ne couvre ni les tumeurs, ni les surcharges métaboliques, ni la dysplasie
mésenchymateuse, ni la pathologie gémellaire, ni les villites à étiologie identifiée, ni
l'anatomie et la maturation normales. Ne force JAMAIS un terme dans Amsterdam au prétexte
qu'il est placentaire. Un hors_referentiel motivé vaut mieux qu'un rattachement faux.

Beaucoup de termes ne sont pas des lésions : structures anatomiques normales, stades de
maturation normale. Ce n'est pas un défaut, c'est leur nature — role="structure".

Pour chaque terme de la tranche, renvoie :
- "id"            : l'identifiant FOETO fourni
- "referentiel"   : AMSTERDAM | BENIRSCHKE | VOGEL | REDLINE | GEMELLAIRE | ACCRETA | HORS_REFERENTIEL
- "entite"        : l'entité nommée de ce référentiel dont relève le terme. "" si hors_referentiel.
- "role"          : "synonyme" | "critere" | "manifestation" | "stade" | "structure" | "hors"
- "stade"         : la gradation normalisée si le libellé en porte une. Stade et grade sont
                    DEUX AXES ORTHOGONAUX chez Amsterdam : écris « MIR stade 2 grade 1 », jamais
                    un seul chiffre. Ne l'infère PAS si le libellé ne la porte pas.
- "conforme"      : "oui" | "obsolete" | "non_standard" | "erreur"
- "label_propose" : le libellé à retenir si conforme != "oui". "" sinon.
- "source"        : la référence de l'extrait qui étaye le rattachement, au format « source chN ».
                    "" si aucun extrait ne l'étaye.
- "verbatim"      : un passage COPIÉ CARACTÈRE POUR CARACTÈRE des extraits fournis, 20 à 300
                    caractères, qui étaye le rattachement. Ne le reformule pas, ne le traduis
                    pas. C'est la preuve, elle est vérifiée automatiquement.
- "ancre"         : "oui" si les extraits étayent vraiment ce terme, "non" si tu as dû juger
                    de mémoire faute d'extrait pertinent. Réponds "non" honnêtement : un
                    rattachement non ancré signalé vaut mieux qu'une citation inventée.
                    Si "ancre" vaut "non", verbatim et source valent "".
- "probleme"      : phrase courte SI le terme pose un problème de fond — libellé composite
                    mêlant plusieurs axes, gradation aplatie dans le nom, macroscopie mélangée
                    à la microscopie, énoncé négatif, fourre-tout, granularité incohérente.
                    "" sinon.

N'INVENTE JAMAIS un verbatim. Un verbatim qui n'est pas dans les extraits sera détecté.

Le vocabulaire COMPLET t'est donné pour que tes rattachements soient cohérents d'un bout à
l'autre : deux termes de même contenu doivent recevoir la même entité et le même référentiel.
On ne te demande de statuer que sur la TRANCHE indiquée.

Réponds UNIQUEMENT en JSON :
{"termes": [{"id": "...", "referentiel": "...", "entite": "...", "role": "...", "stade": "...",
"conforme": "...", "label_propose": "...", "source": "...", "verbatim": "...", "ancre": "...",
"probleme": "..."}]}"""


def load_terms():
    """La DB fait foi sur QUELS termes existent (12 supprimés, 29 créés le 2026-08-06) ;
    factorisation_canon.tsv fournit les facettes. L'intersection est exactement les 650
    termes préexistants — les 29 nouveaux sortent déjà du corpus et ne repassent pas."""
    canon = {r["id"]: r for r in csv.DictReader(open(CANON_TSV), delimiter="\t")}
    rows = sqlite3.connect(FOETO_DB).execute(
        "SELECT id, label_fr, label_en FROM foeto_terms WHERE id LIKE 'FOETO:PP.%' ORDER BY id")
    return [{**canon[i], "label_fr": fr, "label_en": en}
            for i, fr, en in rows if i in canon]


def all_labels():
    return [fr for (fr,) in sqlite3.connect(FOETO_DB).execute(
        "SELECT label_fr FROM foeto_terms WHERE id LIKE 'FOETO:PP.%' ORDER BY label_fr")]


def retrieve_all(terms):
    """Une requête par terme, en ANGLAIS (label_en) : le corpus et BioLORD le sont.
    Mis en cache sur disque, charger le modèle coûte plus cher que les 650 requêtes."""
    if os.path.exists(EVIDENCE_JSON):
        return json.load(open(EVIDENCE_JSON))
    sys.path.insert(0, HERE)
    from retrieve_placenta import db, search
    from sentence_transformers import SentenceTransformer
    conn, model = db(), SentenceTransformer("FremyCompany/BioLORD-2023")
    cols = "rowid, source_short, chapter_num, chapter_title, chunk_text"
    ev = {}
    for n, t in enumerate(terms, 1):
        q = t["label_en"] or t["label_fr"]
        rows = [dict(r) for r in search(conn, model, q, EVIDENCE_K)]
        seen = {r["rowid"] for r in rows}
        for rid in rare_anchors(conn, q):
            if rid not in seen:
                seen.add(rid)
                rows.append(dict(conn.execute(
                    f"SELECT {cols} FROM chunk_meta WHERE rowid = ?", (rid,)).fetchone()))
        ev[t["id"]] = rows
        if n % 50 == 0:
            print(f"  {n}/{len(terms)} termes interrogés", flush=True)
    json.dump(ev, open(EVIDENCE_JSON, "w"))
    return ev


def slice_evidence(chunk, ev):
    """Les 15 termes d'une tranche tirent des chunks très redondants (même chapitre, même
    lésion voisine). Dédupliquer par rowid divise la facture d'entrée par ~2."""
    seen, rows = set(), []
    for t in chunk:
        for r in ev[t["id"]]:
            if r["rowid"] not in seen:
                seen.add(r["rowid"])
                rows.append(r)
    return rows


def fmt(r):
    facets = " | ".join(f"{k}={r[k]}" for k in ("lesion", "site", "qualifieurs", "pattern") if r[k])
    s = f"{r['id']} — \"{r['label_fr']}\" / \"{r['label_en']}\"\n" \
        f"    niveau: {r['niveau']} | compartiment: {r['compartiment']}"
    if facets:
        s += f"\n    facettes: {facets}"
    if r.get("doute"):
        s += f"\n    doute passe 1: {r['doute']}"
    return s


def prefix(md):
    """Préfixe fixe mis en cache, partagé par les 44 requêtes : référentiels + vocabulaire
    entier (679 libellés, les 29 créés compris — sans quoi le modèle re-signalerait comme
    manquant ce que la passe A vient d'insérer)."""
    labels = all_labels()
    listing = "\n".join(f"- {l}" for l in labels)
    return {"type": "text",
            "text": f"=== RÉFÉRENTIELS ===\n\n{md}\n\n\n"
                    f"=== VOCABULAIRE COMPLET ({len(labels)} termes) ===\n\n{listing}",
            "cache_control": {"type": "ephemeral"}}


def build_requests(terms, md, ev, only=None):
    pre = prefix(md)
    reqs = []
    for i in range(0, len(terms), TERMS_PER_REQUEST):
        if only is not None and i not in only:
            continue
        chunk = terms[i:i + TERMS_PER_REQUEST]
        reqs.append({
            "custom_id": f"slice_{i:04d}",
            "params": {
                "model": MODEL, "max_tokens": 16000,
                "system": [{"type": "text", "text": SYSTEM}, pre],
                "messages": [{"role": "user", "content":
                    "TRANCHE à rattacher :\n\n" + "\n\n".join(fmt(t) for t in chunk)
                    + f"\n\n=== EXTRAITS DU CORPUS ===\n\n"
                    + fmt_evidence(slice_evidence(chunk, ev))
                    + f"\n\n=== FIN DES EXTRAITS ===\n\n"
                    f"Ci-dessus se termine le document. Ne le prolonge pas, n'ajoute aucun\n"
                    f"titre de section : rattache les {len(chunk)} termes de la tranche.\n"
                    f"Ta réponse doit commencer par le caractère {{ et finir par le caractère }}."}],
            },
        })
    return reqs


def _selfcheck():
    # la tranche déduplique : un chunk vu par deux termes ne part qu'une fois
    ev = {"a": [{"rowid": 1, "chunk_text": "x"}, {"rowid": 2, "chunk_text": "y"}],
          "b": [{"rowid": 2, "chunk_text": "y"}, {"rowid": 3, "chunk_text": "z"}]}
    assert [r["rowid"] for r in slice_evidence([{"id": "a"}, {"id": "b"}], ev)] == [1, 2, 3]
    assert referentiels().count("## "), "référentiels illisibles"


def prepare():
    _selfcheck()
    terms, md = load_terms(), referentiels()
    ev = retrieve_all(terms)
    reqs = build_requests(terms, md, ev)
    pre_tok = len(prefix(md)["text"]) // 4
    var = sum(len(r["params"]["messages"][0]["content"]) for r in reqs) // 4
    brut = sum(len(c["chunk_text"]) for v in ev.values() for c in v) // 4
    print(f"{len(terms)} termes -> {len(reqs)} requêtes de {TERMS_PER_REQUEST}")
    print(f"préfixe caché ~{pre_tok/1000:.1f}k tokens x {len(reqs)} requêtes")
    print(f"preuves : {brut/1000:.0f}k tokens bruts -> {var/1000:.0f}k après dédup de tranche")
    print(f"entrée totale ≈ {(pre_tok * len(reqs) + var)/1e6:.2f}M tokens "
          f"(dont {pre_tok * (len(reqs)-1)/1e6:.2f}M lus en cache)")
    print("\n--- aperçu tranche 1 ---")
    print(reqs[0]["params"]["messages"][0]["content"][:1200])
    return reqs


def submit(only=None):
    terms, md = load_terms(), referentiels()
    reqs = build_requests(terms, md, retrieve_all(terms), only)
    batch = client().messages.batches.create(requests=reqs)
    open(BATCH_ID_FILE, "w").write(batch.id)
    print(f"{len(reqs)} requêtes | batch soumis : {batch.id} ({batch.processing_status})")


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

    terms = load_terms()
    ev = retrieve_all(terms)
    src = {t["id"]: t for t in terms}
    # Cumul sur disque : un batch de rattrapage ne doit pas effacer les tranches déjà rendues.
    prev = json.load(open(RESULTS_JSON)) if os.path.exists(RESULTS_JSON) else {}
    out, bad, cached = dict(prev), 0, 0
    for res in cl.messages.batches.results(bid):
        if res.result.type != "succeeded":
            bad += 1
            print(f"  échec {res.custom_id}: {res.result.type}")
            continue
        cached += getattr(res.result.message.usage, "cache_read_input_tokens", 0) or 0
        try:
            d = parse(res)
        except (json.JSONDecodeError, ValueError):
            bad += 1
            print(f"  JSON illisible {res.custom_id}")
            continue
        for r in d.get("termes") or []:
            if r.get("id") in src:
                out[r["id"]] = r
    json.dump(out, open(RESULTS_JSON, "w"))

    # Le verbatim est vérifié contre les preuves DE LA TRANCHE, pas du seul terme : le
    # modèle voit la tranche entière et peut légitimement citer le chunk d'un voisin.
    corpus = {}
    for i in range(0, len(terms), TERMS_PER_REQUEST):
        chunk = terms[i:i + TERMS_PER_REQUEST]
        c = norm(fmt_evidence(slice_evidence(chunk, ev)))
        for t in chunk:
            corpus[t["id"]] = c

    cols = ["id", "label_fr", "referentiel", "entite", "role", "stade", "conforme",
            "label_propose", "ancre", "verbatim_verifie", "source", "verbatim", "probleme"]
    ok_v = 0
    with open(OUT_TSV, "w") as f:
        f.write("\t".join(cols) + "\n")
        for tid, r in sorted(out.items()):
            v = norm(r.get("verbatim"))
            good = "oui" if v and len(v) >= 15 and v in corpus.get(tid, "") else "non"
            ok_v += good == "oui"
            r = {**r, "label_fr": src[tid]["label_fr"], "verbatim_verifie": good}
            f.write("\t".join(str(r.get(c) or "").replace("\t", " ").replace("\n", " ")
                              for c in cols) + "\n")

    print(f"\n{len(out)}/{len(terms)} termes rattachés, {bad} échecs, "
          f"{cached} tokens lus en cache")
    for col in ("referentiel", "role", "conforme", "ancre"):
        print(f"{col:14s} {Counter(r.get(col) or '?' for r in out.values()).most_common()}")
    print(f"verbatim vérifié    : {ok_v}/{len(out)}")
    print(f"termes à renommer   : {sum(1 for r in out.values() if r.get('conforme') not in ('oui', None))}")
    print(f"termes à problème   : {sum(1 for r in out.values() if r.get('probleme'))}")
    print(f"-> {OUT_TSV}")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "prepare"
    if cmd == "submit" and len(sys.argv) > 2:      # rattrapage : ground_pass.py submit 0 150
        submit({int(a) for a in sys.argv[2:]})
    else:
        {"prepare": prepare, "submit": submit, "status": status, "collect": collect}[cmd]()
