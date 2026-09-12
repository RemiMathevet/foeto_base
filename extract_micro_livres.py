#!/usr/bin/env python3
"""§micro des fiches syndromes : signes HISTOLOGIQUES attribues a un syndrome
par les livres de pathologie -> table syndrome_micro_livres_candidats, A RELIRE.

Deux temps :
  1. passages (deterministe) : pour chaque syndrome des fiches, les fenetres
     des chapitres de patho (Keeling, Ernst, Soffoet, Ashworth, Verdijk,
     Benirschke, devneuro, perineuro, + entites Spranger) qui NOMMENT le
     syndrome ET portent un mot de microscopie -> syndrome_micro_passages
  2. extraction (Qwen3.6-35B-direct via MAGOS, T=0.2) : le LLM isole et copie
     verbatim les constatations microscopiques que le passage attribue AU
     syndrome nomme, avec l'organe. verbatim introuvable -> verbatim_ok=0.
     Il ne mappe pas vers FOETO (fait ensuite, deterministe).

Meme doctrine que extract_signes_livres.py : pre-tri, jamais preuve.

Deux gisements de plus (2026-09-12, soir) :
  --passages-gr        GeneReviews : les SECTIONS nommees d'un chapitre qui portent
                       un mot d'histologie, hors references (livre='genereviews',
                       chapitre=slug). Postnatal le plus souvent : la source et
                       l'age restent visibles, on ne melange pas.
  --passages-familles  histologie de GROUPE, a propager aux membres avec
                       niveau='famille' (jamais confondue avec une attestation
                       directe) : chapitres de famille de Spranger (syndrome_id
                       'SPRFAM:N' <-> entites N.x) et fenetres des livres de patho
                       sur les noms de familles (syndrome_id = FAM:xxxx de
                       syndrome_families).

Usage : python3 extract_micro_livres.py --passages      # temps 1, compte et sort
        python3 extract_micro_livres.py --passages-gr --passages-familles   # ajoute
        python3 extract_micro_livres.py [--limit N]     # temps 2
"""
import argparse
import json
import re
import sqlite3
import sys
import time
import unicodedata
from pathlib import Path

sys.path.insert(0, "/home/mathevet/Bureau/tmux_supervisor/magos")

DB = "/home/mathevet/Bureau/foeto_base/syndromes_foetaux.db"
CHAP = Path("/home/mathevet/Bureau/Embedding_RAG_V2/chapitres")
LIVRES = ["keeling", "ernst", "soffoet", "ashworth", "verdijk", "benirschke", "devneuro", "perineuro", "spranger_entites"]
MODEL = "Qwen3.6-35B-direct"
RAYON, MAX_FEN, MAX_PASSAGE = 1200, 3, 12000
RX_MICRO = re.compile(r"histolog|microscop|cellul|cells?\b|nucle|fibros|necros|inflammat|infiltrat|chondrocyt|"
                      r"cartilag|growth plate|glomerul|tubul|villi|villous|neuron|myocard|hepatocyt|calcif|"
                      r"cyst|vacuol|storage|dysplas|hypoplas|apoptos|gliosis|heterotop|lamin|epitheli|stroma|"
                      r"histologique|microscopique|cellulaire|noyau|fibrose|nécrose|inflammatoire|infiltrat|"
                      r"chondrocyte|cartilage|glomérul|tubule|villosit|neurone|myocarde|hépatocyte|calcification|"
                      r"kyste|vacuole|surcharge|dysplasie|hypoplasie|épithéli|gliose|hétérotopie", re.I)
STOP = {"syndrome", "sequence", "association", "disease", "dysplasia", "malformation", "anomaly", "deficiency"}
RX_HISTO_FORT = re.compile(r"histolog|histopatholog|light microscop|electron microscop|biops|chondro-osseous|"
                           r"growth plate|pathologic(al)? (examination|findings|features)|autops|microscopique", re.I)
RX_GR_HORS = re.compile(r"Literature Cited|References|Chapter Notes|Revision History|Resources|Suggested Reading", re.I)
# familles de syndrome_families cherchees par leur nom dans les livres de patho (en/fr)
FAMILLES = {
    "FAM:0002": ["mucopolysaccharidoses", "mucopolysaccharidosis"],
    "FAM:0005": ["syndromic craniosynostosis", "craniosynostoses syndromiques", "craniosynostosis syndromes"],
    "FAM:0006": ["non-immune hydrops", "nonimmune hydrops", "anasarque non immune"],
    "FAM:0007": ["rasopathies", "rasopathy"],
    "FAM:0008": ["ciliopathies", "ciliopathy", "ciliopathie"],
    "FAM:0009": ["overgrowth syndromes", "syndromes de surcroissance"],
    "FAM:0010": ["cohesinopathies", "cohesinopathy"],
    "FAM:0011": ["holoprosencephaly", "holoprosencephalie"],
    "FAM:0012": ["collagenopathies", "type ii collagenopathy", "type 2 collagen", "type ii collagen"],
    "FAM:0013": ["arthrogryposis", "arthrogrypose"],
    "FAM:0015": ["tubulinopathies", "tubulinopathy"],
    "FAM:0016": ["ectodermal dysplasias", "ectodermal dysplasia", "dysplasies ectodermiques"],
    "FAM:0017": ["laminopathies", "laminopathy"],
    "FAM:0018": ["congenital ichthyoses", "congenital ichthyosis", "ichtyoses congenitales"],
    "FAM:0021": ["dystroglycanopathies", "dystroglycanopathy", "cobblestone"],
    "FAM:0022": ["epidermolysis bullosa", "epidermolyse bulleuse"],
    "FAM:0023": ["congenital disorders of glycosylation", "congenital disorder of glycosylation"],
    "FAM:0041": ["fibrillinopathies", "fibrillinopathy", "marfanoid"],
    "FAM:0042": ["enchondromatosis", "osteochondromatosis", "multiple osteochondromas", "multiple exostoses"],
    "FAM:0043": ["cholangiopathies", "cholangiopathy", "paucity of bile ducts", "bile duct paucity"],
    "FAM:0044": ["heterotopic ossification", "fibrodysplasia ossificans"],
}

SYSTEM = """You extract MICROSCOPIC (histological) findings from a pathology textbook passage.
The passage mentions a target syndrome. Keep ONLY findings the text attributes to that syndrome
(not to other conditions discussed nearby). Skip gross/macroscopic, clinical, radiological,
genetic and epidemiological statements.
Return ONLY a JSON object, no prose:
{"signes": [{"signe": "<short histological finding, English, as the book words it>",
             "verbatim": "<the exact phrase from the passage, 5-25 words, copied verbatim, same language as the passage>",
             "organe": "<organ or tissue the finding is seen in, English, lowercase>",
             "attribution": "<'direct' if the sentence names the syndrome or clearly describes it, 'contexte' if the link is only by proximity>"}]}
Rules: copy, never paraphrase, the verbatim. Empty list if the passage carries no microscopic finding for the syndrome."""


def norm(s):
    return "".join(ch for ch in unicodedata.normalize("NFD", s.lower()) if unicodedata.category(ch) != "Mn")


def cles(titre, name_en):
    """noms sous lesquels chercher le syndrome : titre epure + alternatives entre parentheses + nom Orphanet"""
    t = re.sub(r"^[\dA-Z]+[\.\d]*\s+", "", titre)
    alts = re.findall(r"\(([^)]+)\)", t)
    base = re.sub(r"\(.*?\)", "", t)
    out = []
    for cand in [base] + [a for al in alts for a in al.split(",")] + ([name_en] if name_en else []):
        cand = re.sub(r"\bMIM\b.*$", "", cand)
        cand = re.sub(r"\b(types?\s+[ivxa-d\d]+.*|,.*)$", "", cand, flags=re.I)
        k = norm(re.sub(r"\s+", " ", cand)).strip(" -")
        mots = k.split()
        # phrase entiere, puis sans son mot generique FINAL (« beckwith-wiedemann syndrome »
        # -> « beckwith-wiedemann ») ; jamais un mot isole sans trait d'union : « metaphyseal »
        # ou « larsen » attrapent des adjectifs et des auteurs (2026-09-12, 1 713 faux passages)
        while len(mots) > 1 and mots[-1] in STOP:
            mots = mots[:-1]
        court = " ".join(mots)
        for cand_k in (k, court):
            if len(cand_k) >= 6 and (len(cand_k.split()) >= 2 or "-" in cand_k) and cand_k not in out:
                out.append(cand_k)
    return out


def chapitres():
    for livre in LIVRES:
        for f in sorted((CHAP / livre).glob("*.txt")):
            txt = f.read_text(encoding="utf-8", errors="ignore")
            yield livre, f.stem, txt, norm(txt)


def fenetres(txt, ntxt, ks, rx_filtre=RX_MICRO):
    """fenetres fusionnees autour des mentions des cles, filtrees sur un mot de microscopie"""
    fen = []
    for k in ks:
        for m in re.finditer(r"\b" + re.escape(k) + r"\b", ntxt):
            fen.append((max(0, m.start() - RAYON), min(len(txt), m.end() + RAYON), k))
    fen.sort()
    merged = []
    for a, b, k in fen:
        if merged and a <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], b)
        else:
            merged.append([a, b, k])
    return [m for m in merged if rx_filtre.search(txt[m[0]:m[1]])][:MAX_FEN]


def inserer(c, titre, sid, cle, livre, chap, merged, txt):
    passage = "\n[...]\n".join(txt[a:b] for a, b, _ in merged)[:MAX_PASSAGE]
    c.execute("insert into syndrome_micro_passages(syndrome_titre,syndrome_id,cle,livre,chapitre,n_fenetres,passage) values(?,?,?,?,?,?,?)",
              (titre, sid, cle, livre, chap, len(merged), passage))


def passages_gr(c):
    """GeneReviews : sections nommees portant de l'histologie, hors references"""
    c.execute("delete from syndrome_micro_passages where livre='genereviews'")
    gr = []
    for slug, title, om, sj in c.execute("select slug, title, omim_ids, sections_json from genereviews_full"):
        secs = [x for x in json.loads(sj or "[]") if not RX_GR_HORS.search(x["path"]) and RX_HISTO_FORT.search(x["text"])]
        if secs:
            gr.append((slug, set(re.findall(r"\d{6}", om or "")), norm(title.replace(" - GeneReviews® - NCBI Bookshelf", "")), secs))
    syns = c.execute("""select distinct s.syndrome_titre, s.syndrome_id, o.name_en
                        from v_syndrome_hpo_livres_foetal s left join syndromes o on o.id = s.syndrome_id""").fetchall()
    n = 0
    for titre, sid, ne in syns:
        ks, mims = cles(titre, ne), set(re.findall(r"\d{6}", titre))
        for slug, om, nt, secs in gr:
            if (mims and mims & om) or any(re.search(r"\b" + re.escape(k) + r"\b", nt) for k in ks):
                # les sections diagnostiques d'abord, puis le reste, dans la limite du passage
                secs = sorted(secs, key=lambda x: 0 if re.search(r"Histopath|Suggestive|Diagnosis|Clinical", x["path"]) else 1)
                txt = "\n[...]\n".join(f"## {x['path']}\n{x['text']}" for x in secs)
                c.execute("insert into syndrome_micro_passages(syndrome_titre,syndrome_id,cle,livre,chapitre,n_fenetres,passage) values(?,?,?,?,?,?,?)",
                          (titre, sid, ks[0] if ks else None, "genereviews", slug, len(secs), txt[:MAX_PASSAGE]))
                n += 1
    c.commit()
    ns = c.execute("select count(distinct syndrome_titre) from syndrome_micro_passages where livre='genereviews'").fetchone()[0]
    print(f"genereviews : {n} passages pour {ns} syndromes")


def passages_familles(c):
    """histologie de groupe : chapitres de famille de Spranger + noms de familles dans les livres de patho"""
    c.execute("delete from syndrome_micro_passages where syndrome_id like 'SPRFAM:%' or syndrome_id like 'FAM:%'")
    n = 0
    for f in sorted((CHAP / "spranger").glob("ch*.txt")):
        txt = f.read_text(encoding="utf-8", errors="ignore")
        num = int(re.match(r"ch(\d+)", f.stem)[1])
        fen = []
        for m in RX_HISTO_FORT.finditer(txt):
            fen.append((max(0, m.start() - RAYON), min(len(txt), m.end() + RAYON), "histo"))
        merged = []
        for a, b, k in sorted(fen):
            if merged and a <= merged[-1][1]:
                merged[-1][1] = max(merged[-1][1], b)
            else:
                merged.append([a, b, k])
        if merged:
            inserer(c, f"FAMILLE Spranger {num} — {f.stem[5:].replace('_', ' ')}", f"SPRFAM:{num}", "histo", "spranger", f.stem, merged[:MAX_FEN], txt)
            n += 1
    noms = dict(c.execute("select family_id, family_name from syndrome_families"))
    chaps = [x for x in chapitres() if x[0] != "spranger_entites"]
    for fid, ks in FAMILLES.items():
        for livre, chap, txt, ntxt in chaps:
            merged = fenetres(txt, ntxt, ks)
            if merged:
                inserer(c, f"FAMILLE {noms.get(fid, fid)}", fid, merged[0][2], livre, chap, merged, txt)
                n += 1
    c.commit()
    print(f"familles : {n} passages")
    for l, k in c.execute("select livre, count(*) from syndrome_micro_passages where syndrome_id like 'SPRFAM:%' or syndrome_id like 'FAM:%' group by 1 order by 2 desc"):
        print(f"  {l:18s} {k}")


def passages(c):
    c.execute("drop table if exists syndrome_micro_passages")
    c.execute("""create table syndrome_micro_passages (
        id integer primary key, syndrome_titre text, syndrome_id text, cle text, livre text, chapitre text,
        n_fenetres integer, passage text)""")
    syns = c.execute("""select distinct s.syndrome_titre, s.syndrome_id, o.name_en
                        from v_syndrome_hpo_livres_foetal s left join syndromes o on o.id = s.syndrome_id""").fetchall()
    cible = [(t, sid, cles(t, ne)) for t, sid, ne in syns]
    chaps = list(chapitres())
    n = 0
    for titre, sid, ks in cible:
        # Spranger : les entites se citent entre elles (differentiel) — on ne lit que
        # le texte de l'entite elle-meme (prefixe « 1.1 » -> fichier e1_1_*)
        num = re.match(r"^(\d+)\.(\d+)\s", titre)
        for livre, chap, txt, ntxt in chaps:
            if livre == "spranger_entites" and not (num and chap.startswith(f"e{num[1]}_{num[2]}_")):
                continue
            fen = []
            for k in ks:
                for m in re.finditer(r"\b" + re.escape(k) + r"\b", ntxt):
                    fen.append((max(0, m.start() - RAYON), min(len(txt), m.end() + RAYON), k))
            if not fen:
                continue
            fen.sort()
            merged = []
            for a, b, k in fen:
                if merged and a <= merged[-1][1]:
                    merged[-1][1] = max(merged[-1][1], b)
                else:
                    merged.append([a, b, k])
            # ne garder que les fenetres qui parlent de microscopie
            merged = [m for m in merged if RX_MICRO.search(txt[m[0]:m[1]])][:MAX_FEN]
            if not merged:
                continue
            passage = "\n[...]\n".join(txt[a:b] for a, b, _ in merged)[:MAX_PASSAGE]
            c.execute("insert into syndrome_micro_passages(syndrome_titre,syndrome_id,cle,livre,chapitre,n_fenetres,passage) values(?,?,?,?,?,?,?)",
                      (titre, sid, merged[0][2], livre, chap, len(merged), passage))
            n += 1
    c.commit()
    ns = c.execute("select count(distinct syndrome_titre) from syndrome_micro_passages").fetchone()[0]
    print(f"{n} passages pour {ns} syndromes ; par livre :")
    for l, k in c.execute("select livre, count(*) from syndrome_micro_passages group by 1 order by 2 desc"):
        print(f"  {l:18s} {k}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--passages", action="store_true")
    ap.add_argument("--passages-gr", action="store_true")
    ap.add_argument("--passages-familles", action="store_true")
    ap.add_argument("--limit", type=int, default=0)
    a = ap.parse_args()
    c = sqlite3.connect(DB)
    if a.passages:
        return passages(c)
    if a.passages_gr or a.passages_familles:
        if a.passages_gr:
            passages_gr(c)
        if a.passages_familles:
            passages_familles(c)
        return
    from magos_client import MagosClient
    c.execute("""create table if not exists syndrome_micro_livres_candidats (
        id integer primary key, passage_id integer, syndrome_titre text, syndrome_id text, livre text, chapitre text,
        signe text, verbatim text, verbatim_ok integer, organe text, attribution text, modele text,
        extrait_le text default (datetime('now')))""")
    # cle = (syndrome, livre, chapitre), pas passage_id : --passages-familles / --passages-gr
    # recreent les passages avec de nouveaux ids, les candidats deja extraits restent valables
    done = {tuple(r) for r in c.execute("select distinct syndrome_titre, livre, chapitre from syndrome_micro_livres_candidats")}
    cl = MagosClient(client_id="extract-micro-livres")
    n = 0
    for pid, titre, sid, livre, chap, passage in c.execute(
            "select id, syndrome_titre, syndrome_id, livre, chapitre, passage from syndrome_micro_passages order by id").fetchall():
        if (titre, livre, chap) in done:
            continue
        if a.limit and n >= a.limit:
            break
        t0 = time.time()
        try:
            cible = "TARGET GROUP OF SYNDROMES" if titre.startswith("FAMILLE") else "TARGET SYNDROME"
            r = cl.submit_and_wait(MODEL, f"{cible}: {titre}\nPASSAGE ({livre}, {chap}):\n\n{passage}",
                                   system=SYSTEM, priority=6, timeout_s=600, wait_timeout=900,
                                   options={"temperature": 0.2, "num_predict": 4000})
            raw = r.get("response") or ""
            m = re.search(r"\{.*\}", raw, re.S)
            try:
                d = json.loads(m.group()) if m else {}
            except json.JSONDecodeError:
                sig = []
                for o in re.findall(r"\{[^{}]*\}", m.group() if m else raw):
                    try:
                        sig.append(json.loads(o))
                    except json.JSONDecodeError:
                        pass
                d = {"signes": sig}
        except Exception as e:
            print(f"  {livre}/{chap} {titre[:40]}: ERREUR {e}", flush=True)
            c.execute("insert into syndrome_micro_livres_candidats(passage_id,syndrome_titre,syndrome_id,livre,chapitre,signe,verbatim_ok,modele) values(?,?,?,?,?,?,?,?)",
                      (pid, titre, sid, livre, chap, f"__ERREUR__ {e}"[:200], 0, MODEL))
            c.commit(); continue
        np = re.sub(r"\s+", " ", passage.lower())
        rows, ok = [], 0
        for s in d.get("signes", []) or []:
            v = (s.get("verbatim") or "").strip()
            vok = 1 if v and re.sub(r"\s+", " ", v.lower())[:60] in np else 0
            ok += vok
            rows.append((pid, titre, sid, livre, chap, (s.get("signe") or "").strip(), v, vok,
                         (s.get("organe") or "").strip().lower() or None, s.get("attribution"), MODEL))
        if not rows:
            rows = [(pid, titre, sid, livre, chap, "__VIDE__", "", 0, None, None, MODEL)]
        c.executemany("insert into syndrome_micro_livres_candidats(passage_id,syndrome_titre,syndrome_id,livre,chapitre,signe,verbatim,verbatim_ok,organe,attribution,modele) values(?,?,?,?,?,?,?,?,?,?,?)", rows)
        c.commit(); n += 1
        print(f"  {livre[:10]:10s} {chap[:28]:28s} {titre[:36]:36s} {len(rows):2d} signes, {ok:2d} verbatim ok, {time.time()-t0:3.0f} s", flush=True)
    tot = c.execute("select count(*), sum(verbatim_ok), count(distinct syndrome_titre) from syndrome_micro_livres_candidats "
                    "where signe not like '\\_\\_%' escape '\\'").fetchone()
    print(f"\nTable : {tot[0]} signes, {tot[1]} verbatim ok, {tot[2]} syndromes", flush=True)


if __name__ == "__main__":
    main()
