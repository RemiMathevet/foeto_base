#!/usr/bin/env python3
"""Passe A : instruire les 54 lacunes CONTRE le corpus, et traduire les termes sans label_en.

    python gap_pass.py prepare      # aperçu + preuves récupérées, aucun appel API
    python gap_pass.py submit
    python gap_pass.py status
    python gap_pass.py collect

Une lacune est une AFFIRMATION D'ABSENCE produite sans corpus par medical_pass.py. Elle est
donc invérifiée dans les deux sens : l'entité peut ne pas exister (Vogel — « maturation
dissociée » et « maturation dysharmonieuse » ont été inventées de mémoire paramétrique), ou
elle peut déjà être couverte par un terme du vocabulaire sous un autre libellé.

Chaque lacune part donc avec ses preuves tirées de placenta_rag.db, et le modèle doit rendre
un VERBATIM copié de ces preuves. collect() vérifie que ce verbatim est bien un extrait des
chunks fournis : c'est ce qui distingue une citation d'une invention.

Ne touche pas la DB.
"""
import csv, json, os, re, sys
from collections import Counter
import anthropic

HERE = os.path.dirname(os.path.abspath(__file__))
GAPS_TSV = os.path.join(HERE, "lacunes.tsv")
TERMS_TSV = os.path.join(HERE, "factorisation_canon.tsv")
REFS_MD = os.path.join(HERE, "referentiels_placenta.md")
FOETO_DB = os.path.join(HERE, "syndromes_foetaux.db")
OUT_GAPS = os.path.join(HERE, "lacunes_instruites.tsv")
OUT_EN = os.path.join(HERE, "labels_en.tsv")
EVIDENCE_JSON = os.path.join(HERE, ".gap_evidence.json")
RESULTS_JSON = os.path.join(HERE, ".gap_results.json")
QUERIES_EN = os.path.join(HERE, "lacunes_queries_en.tsv")
BATCH_ID_FILE = os.path.join(HERE, ".gap_batch_id")
ENV_FILE = "/home/mathevet/Bureau/benchmark_foeto/.env_opus"
MODEL = "claude-opus-5"
EVIDENCE_K = 6
TRAD_PER_REQUEST = 45

API_KEY = None
if os.path.exists(ENV_FILE):
    for line in open(ENV_FILE):
        if line.strip().startswith("ANTHROPIC_API_KEY="):
            API_KEY = line.split("=", 1)[1].strip().strip('"')


SYSTEM_GAP = """Tu es fœtopathologiste, expert de la pathologie placentaire.

Une passe précédente, menée SANS accès aux ouvrages, a signalé qu'une entité manquait au
vocabulaire. Cette affirmation n'est pas fiable : elle a déjà produit des entités qui
n'existent dans aucun ouvrage. Tu reçois maintenant des EXTRAITS RÉELS du corpus placentaire
(Benirschke, Khong 2019, Vogel & Turowski 2019, consensus d'Amsterdam) et le vocabulaire
complet. Tranche.

Trois verdicts possibles :
- "confirmee"      : l'entité est réelle, documentée dans les extraits, et aucun terme du
                     vocabulaire ne la désigne. Il faut la créer.
- "deja_couverte"  : un terme du vocabulaire la désigne déjà, sous un autre libellé. Donne
                     ce terme dans "terme_existant". Ne rien créer.
- "rejetee"        : l'entité n'est pas étayée par les extraits, ou n'est pas une entité
                     nosologique légitime. Donne la raison.

Règles de citation, les plus importantes :
- "verbatim" doit être un passage COPIÉ CARACTÈRE POUR CARACTÈRE des extraits fournis, entre
  20 et 300 caractères. Ne le reformule pas, ne le traduis pas, ne le raccourcis pas au
  milieu. C'est la preuve, elle est vérifiée automatiquement.
- "citation" est la référence de l'extrait d'où vient le verbatim, au format « source chN ».
- Si aucun extrait n'étaye l'entité, le verdict est "rejetee" et verbatim vaut "".
  N'invente JAMAIS un verbatim pour justifier un "confirmee".

Si le verdict est "confirmee", remplis aussi les facettes, dans le même schéma que le reste
du vocabulaire : lesion (le processus), site (la structure atteinte), qualifieurs (liste),
pattern (la distribution), niveau parmi element|entite|pattern|structure|maturation.

Réponds UNIQUEMENT en JSON :
{"verdict": "confirmee|deja_couverte|rejetee",
 "terme_existant": "", "raison": "<1-2 phrases>",
 "label_fr": "", "label_en": "",
 "lesion": "", "site": "", "qualifieurs": [], "pattern": "", "niveau": "",
 "criteres": "<critères diagnostiques, d'après les extraits>",
 "citation": "", "verbatim": ""}"""


SYSTEM_TRAD = """Tu es fœtopathologiste. Traduis en anglais des libellés de signes
placentaires, pour qu'ils servent de requêtes dans un espace d'embedding biomédical
anglophone (BioLORD) interrogeant Benirschke, Khong et Vogel.

Emploie la terminologie CONSACRÉE des ouvrages anglophones, pas une traduction littérale :
« artériopathie déciduale » → "decidual vasculopathy", « nécrose fibrinoïde » →
"fibrinoid necrosis", « villosités crampons » → "anchoring villi". Garde les sigles usuels
(MVM, FVM, VUE, MIR, FIR). Pas d'article, pas de majuscule initiale sauf sigle ou nom propre.

Réponds UNIQUEMENT en JSON :
{"termes": [{"id": "<id fourni>", "label_en": "<libellé anglais>"}]}"""


def load_gaps():
    if not os.path.exists(GAPS_TSV):
        sys.exit("lacunes.tsv absent — lance medical_pass.py collect")
    return list(csv.DictReader(open(GAPS_TSV), delimiter="\t"))


def load_terms():
    return list(csv.DictReader(open(TERMS_TSV), delimiter="\t"))


def referentiels():
    return open(REFS_MD).read()


def missing_en(terms):
    """Les termes dont foeto_terms n'a pas de label_en : ils seraient interrogés en
    français dans un espace anglophone, ce qui dégrade les deux canaux de récupération."""
    import sqlite3
    have = {i for (i,) in sqlite3.connect(FOETO_DB).execute(
        "SELECT id FROM foeto_terms WHERE label_en IS NOT NULL AND TRIM(label_en) <> ''")}
    return [t for t in terms if t["id"] not in have]


def fmt_evidence(rows):
    return "\n\n".join(
        f"--- [{i}] {r['source_short']} ch{r['chapter_num']} — {r['chapter_title']}\n{r['chunk_text']}"
        for i, r in enumerate(rows, 1))


def queries_en():
    """Interroger une lacune par son libellé FRANÇAIS met les DEUX canaux à blanc : le
    vecteur est anglophone et BM25 cherche « nœud », « cordon » dans un corpus anglais.
    Au premier essai, 7 rejets sur 8 vérifiés portaient sur des entités bel et bien
    présentes dans le corpus. La requête part donc en anglais."""
    if not os.path.exists(QUERIES_EN):
        return {}
    return {r["entite"]: r["query_en"]
            for r in csv.DictReader(open(QUERIES_EN), delimiter="\t") if r["query_en"]}


RARE_DF = 40          # un terme présent dans <= 40 chunks sur 2515 est discriminant
RARE_TAKE = 2         # chunks ancrés par terme rare
RARE_MAX = 4


def rare_anchors(conn, q):
    """Verdict "rejetee" = affirmation d'ABSENCE : elle n'est valable que si le terme rare
    qui la porte est absent du corpus ENTIER, pas des 6 chunks tirés. « Quintero »,
    « Slaghekke », « increta » étaient en base et ont été noyés par la fusion RRF, qui
    dilue un terme rare parmi les mots communs de la requête.
    On force donc en preuve les meilleurs chunks de chaque terme peu fréquent."""
    out = []
    for w in {w for w in re.split(r"[^A-Za-z0-9-]+", q) if len(w) > 3}:
        try:
            hits = conn.execute(
                "SELECT rowid FROM chunk_fts WHERE chunk_fts MATCH ? "
                "ORDER BY bm25(chunk_fts) LIMIT ?", (f'"{w}"', RARE_DF + 1)).fetchall()
        except Exception:
            continue
        if 0 < len(hits) <= RARE_DF:
            out += [h[0] for h in hits[:RARE_TAKE]]
    return out[:RARE_MAX]


def retrieve_all(gaps):
    """Récupéré une fois puis mis en cache sur disque : charger BioLORD coûte plus cher
    que les 54 requêtes elles-mêmes, et prepare() est appelé par submit()."""
    if os.path.exists(EVIDENCE_JSON):
        return json.load(open(EVIDENCE_JSON))
    sys.path.insert(0, HERE)
    from retrieve_placenta import db, search
    from sentence_transformers import SentenceTransformer
    en = queries_en()
    conn, model = db(), SentenceTransformer("FremyCompany/BioLORD-2023")
    cols = "rowid, source_short, chapter_num, chapter_title, chunk_text"
    ev = {}
    for g in gaps:
        q = en.get(g["entite"]) or g["entite"]
        rows = [dict(r) for r in search(conn, model, q, EVIDENCE_K)]
        seen = {r["rowid"] for r in rows}
        for rid in rare_anchors(conn, q):
            if rid not in seen:
                seen.add(rid)
                rows.append(dict(conn.execute(
                    f"SELECT {cols} FROM chunk_meta WHERE rowid = ?", (rid,)).fetchone()))
        ev[g["entite"]] = rows
    json.dump(ev, open(EVIDENCE_JSON, "w"))
    return ev


def prefix(terms, md):
    """Préfixe fixe mis en cache, partagé par les 54 requêtes de lacunes : le vocabulaire
    entier est nécessaire pour trancher « deja_couverte »."""
    listing = "\n".join(f"- {t['label_fr']} [{t['niveau']}]" for t in terms)
    return {"type": "text",
            "text": f"=== RÉFÉRENTIELS ===\n\n{md}\n\n\n"
                    f"=== VOCABULAIRE COMPLET ({len(terms)} termes) ===\n\n{listing}",
            "cache_control": {"type": "ephemeral"}}


def build_requests(gaps, terms, md, ev, only=None):
    pre = prefix(terms, md)
    reqs = []
    for i, g in enumerate(gaps):
        if only is not None and i not in only:
            continue
        reqs.append({
            "custom_id": f"gap_{i:03d}",
            "params": {
                "model": MODEL, "max_tokens": 16000,
                "system": [{"type": "text", "text": SYSTEM_GAP}, pre],
                "messages": [
                    {"role": "user", "content":
                        f"ENTITÉ SIGNALÉE ABSENTE : {g['entite']}\n"
                        f"référentiel visé : {g['referentiel']} | importance annoncée : {g['importance']}\n"
                        f"motif de la passe précédente : {g['raison']}\n\n"
                        f"=== EXTRAITS DU CORPUS ===\n\n{fmt_evidence(ev[g['entite']])}\n\n"
                        f"=== FIN DES EXTRAITS ===\n\n"
                        f"Ci-dessus se termine le document. Ne le prolonge pas, n'ajoute aucun\n"
                        f"titre de section : rends ton verdict sur « {g['entite']} ».\n"
                        f"Ta réponse doit commencer par le caractère {{ et finir par le caractère }}.\n"
                        f"(Opus 5 n'accepte pas l'amorce assistant, cette consigne la remplace :\n"
                        f"5 réponses sur 54 avaient continué le document au premier essai.)"},
                ],
            },
        })
    if only is not None:
        return reqs
    todo = missing_en(terms)
    for i in range(0, len(todo), TRAD_PER_REQUEST):
        sl = todo[i:i + TRAD_PER_REQUEST]
        reqs.append({
            "custom_id": f"trad_{i:03d}",
            "params": {
                "model": MODEL, "max_tokens": 8000,
                "system": [{"type": "text", "text": SYSTEM_TRAD}],
                "messages": [{"role": "user", "content": "\n".join(
                    f"{t['id']} — {t['label_fr']}  [{t['niveau']} | {t['compartiment']}]"
                    for t in sl)}],
            },
        })
    return reqs


def client():
    if not API_KEY:
        sys.exit("ANTHROPIC_API_KEY introuvable dans .env_opus")
    return anthropic.Anthropic(api_key=API_KEY)


def parse(res):
    txt = next((b.text for b in res.result.message.content if b.type == "text"), "")
    if "{" not in txt:                       # réponse amorcée par « { », qui n'est pas renvoyé
        txt = "{" + txt
    return json.loads(txt[txt.find("{"):txt.rfind("}") + 1])


def norm(s):
    """Comparaison de verbatim : les chunks sont extraits de PDF, les espaces et les
    coupures de ligne n'y sont pas fiables. Seuls les caractères pleins comptent."""
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def _selfcheck():
    assert norm("Fibrinoid  necrosis,\nwith foam cells") == "fibrinoidnecrosiswithfoamcells"
    ev = [{"source_short": "vogel", "chapter_num": 8, "chapter_title": "t", "chunk_text": "AVM is graded 1 to 3."}]
    assert "vogel ch8" in fmt_evidence(ev)
    # un verbatim reformulé ne doit PAS passer pour une citation
    assert norm("AVM is graded 1 to 3") in norm(fmt_evidence(ev))
    assert norm("AVM has three grades") not in norm(fmt_evidence(ev))
    sys.path.insert(0, HERE)
    from retrieve_placenta import db
    conn = db()
    # les termes rares que la fusion RRF avait noyés doivent être ancrés ; un mot banal, non
    assert rare_anchors(conn, "Quintero staging twin transfusion"), "ancre lexicale muette"
    assert not rare_anchors(conn, "placenta villous maternal fetal"), "ancre trop bavarde"


def prepare():
    _selfcheck()
    gaps, terms, md = load_gaps(), load_terms(), referentiels()
    ev = retrieve_all(gaps)
    reqs = build_requests(gaps, terms, md, ev)
    n_trad = sum(1 for r in reqs if r["custom_id"].startswith("trad_"))
    chars = sum(len(c["chunk_text"]) for v in ev.values() for c in v)
    print(f"{len(gaps)} lacunes -> {len(reqs) - n_trad} requêtes ancrées "
          f"+ {n_trad} requêtes de traduction ({len(missing_en(terms))} termes sans label_en)")
    print(f"preuves : {chars/1000:.0f}k car ≈ {chars//4000}k tokens | "
          f"préfixe caché ~{len(prefix(terms, md)['text'])//4} tokens")
    print(f"importances : {Counter(g['importance'] for g in gaps).most_common()}")
    print("\n--- aperçu lacune 1 ---")
    print(reqs[0]["params"]["messages"][0]["content"][:900])
    return reqs


def submit(only=None):
    gaps = load_gaps()
    reqs = build_requests(gaps, load_terms(), referentiels(), retrieve_all(gaps), only)
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

    gaps, terms = load_gaps(), load_terms()
    ev = retrieve_all(gaps)
    todo_en = missing_en(terms)
    # Cumul sur disque : un batch de rattrapage ne doit pas effacer les lacunes déjà rendues.
    prev = json.load(open(RESULTS_JSON)) if os.path.exists(RESULTS_JSON) else {"gaps": {}, "trads": []}
    out = {int(k): v for k, v in prev["gaps"].items()}
    trads, bad, cached = list(prev["trads"]), 0, 0
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
        if res.custom_id.startswith("trad_"):
            trads.extend(d.get("termes") or [])
        else:
            out[int(res.custom_id.split("_")[1])] = d

    json.dump({"gaps": {str(k): v for k, v in out.items()}, "trads": trads},
              open(RESULTS_JSON, "w"))

    cols = ["referentiel", "importance", "entite", "verdict", "verbatim_verifie",
            "terme_existant", "label_fr", "label_en", "lesion", "site", "qualifieurs",
            "pattern", "niveau", "criteres", "citation", "verbatim", "raison"]
    ok_v = 0
    with open(OUT_GAPS, "w") as f:
        f.write("\t".join(cols) + "\n")
        for i, g in enumerate(gaps):
            d = out.get(i)
            if not d:
                continue
            corpus = norm(fmt_evidence(ev[g["entite"]]))
            v = norm(d.get("verbatim"))
            good = "oui" if v and len(v) >= 15 and v in corpus else "non"
            ok_v += good == "oui"
            d = {**d, "referentiel": g["referentiel"], "importance": g["importance"],
                 "entite": g["entite"], "verbatim_verifie": good}
            d["qualifieurs"] = ", ".join(d.get("qualifieurs") or []) \
                if isinstance(d.get("qualifieurs"), list) else (d.get("qualifieurs") or "")
            f.write("\t".join(str(d.get(c) or "").replace("\t", " ").replace("\n", " ")
                              for c in cols) + "\n")

    src = {t["id"]: t["label_fr"] for t in todo_en}
    with open(OUT_EN, "w") as f:
        f.write("id\tlabel_fr\tlabel_en\n")
        for t in trads:
            if t.get("id") in src:
                f.write(f"{t['id']}\t{src[t['id']]}\t{t.get('label_en','')}\n")

    verdicts = Counter(d.get("verdict") for d in out.values())
    conf = [i for i, d in out.items() if d.get("verdict") == "confirmee"]
    print(f"{len(out)}/{len(gaps)} lacunes instruites, {bad} échecs, {cached} tokens en cache")
    print(f"verdicts : {verdicts.most_common()}")
    print(f"verbatim vérifié dans le corpus : {ok_v}/{len(out)}")
    print(f"{len(trads)}/{len(todo_en)} traductions -> {OUT_EN}")
    print(f"-> {OUT_GAPS}")
    if conf:
        print(f"\n{len(conf)} entités à créer :")
        for i in sorted(conf):
            d = out[i]
            print(f"  [{gaps[i]['referentiel']:14s}] {d.get('label_fr','')}"
                  f"  ({d.get('citation','')}, preuve={('oui' if norm(d.get('verbatim')) in norm(fmt_evidence(ev[gaps[i]['entite']])) else 'NON')})")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "prepare"
    if cmd == "submit" and len(sys.argv) > 2:      # rattrapage : gap_pass.py submit 9 15 26
        submit({int(a) for a in sys.argv[2:]})
    else:
        {"prepare": prepare, "submit": submit, "status": status, "collect": collect}[cmd]()
