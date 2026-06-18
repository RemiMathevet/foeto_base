#!/usr/bin/env python3
"""Parse les abstracts PubMed scrapés en champs structurés via Gemini Flash.

Extrait : gènes, HPO, sémiologie, histologie, imagerie, âge gestationnel, contexte.
Coût estimé : ~$3 pour 8700 abstracts.
"""

import importlib.util
import sqlite3
import json
import time
import os
import threading
from openai import OpenAI

DB_PATH = "/home/mathevet/Bureau/foeto_base/syndromes_foetaux.db"

MODEL = "google/gemini-2.5-flash"
N_THREADS = 4
NOTIFY_EVERY = 500

spec = importlib.util.spec_from_file_location(
    "notify", "/home/mathevet/Bureau/tmux_supervisor/embeddings/pipeline_v2/08_notify.py"
)
_mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(_mod)
send_email = _mod.send_email
NOTIFY_TO = "remimathevet@gmail.com"

SYSTEM_PROMPT = """Tu es un expert en génétique médicale et fœtopathologie.
On te donne un abstract PubMed d'un case report.
Extrais les informations structurées suivantes en JSON.

Règles :
- Ne remplis QUE ce qui est explicitement mentionné dans l'abstract
- Pour les champs absents, utilise null
- Les termes HPO doivent être en anglais standardisé (ex: "Polydactyly", "Renal cysts", "Encephalocele")
- Les gènes en notation officielle HGNC (ex: "FGFR3", "COL2A1")
- Sois factuel, pas d'inférence

Réponds UNIQUEMENT avec le JSON suivant, sans commentaire :
{
  "genes": ["GENE1", "GENE2"],
  "hpo_phenotypes": ["Phenotype 1", "Phenotype 2"],
  "histology": ["finding histo 1", "finding histo 2"],
  "imaging": ["finding imagerie 1", "finding imagerie 2"],
  "gestational_age": "22 SA",
  "outcome": "TOP|stillbirth|neonatal_death|alive|null",
  "inheritance": "AR|AD|XL|sporadic|null",
  "sample_type": "fetus|neonate|infant|child|adult",
  "key_clinical_features": ["feature 1", "feature 2"]
}"""

lock = threading.Lock()
progress = {"done": 0, "errors": 0, "total": 0}


def ensure_table():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""CREATE TABLE IF NOT EXISTS case_reports_parsed (
        case_report_id INTEGER PRIMARY KEY REFERENCES case_reports(id),
        genes TEXT,
        hpo_phenotypes TEXT,
        histology TEXT,
        imaging TEXT,
        gestational_age TEXT,
        outcome TEXT,
        inheritance TEXT,
        sample_type TEXT,
        key_clinical_features TEXT,
        raw_json TEXT,
        parsed_at TEXT DEFAULT (datetime('now'))
    )""")
    conn.commit()
    conn.close()


def get_todo():
    conn = sqlite3.connect(DB_PATH)
    done = set(r[0] for r in conn.execute(
        "SELECT case_report_id FROM case_reports_parsed"
    ).fetchall())
    rows = conn.execute(
        "SELECT id, syndrome_id, gold_diagnosis, clinical_text FROM case_reports WHERE clinical_text IS NOT NULL AND clinical_text != '[]' AND length(clinical_text) > 50"
    ).fetchall()
    conn.close()
    todo = [(r[0], r[1], r[2], r[3]) for r in rows if r[0] not in done]
    return todo


def parse_abstract(client, abstract_text, syndrome_name):
    response = client.chat.completions.create(
        model=MODEL,
        temperature=0,
        max_tokens=1000,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": f"Syndrome connu : {syndrome_name}\n\nAbstract :\n{abstract_text[:3000]}"},
        ],
    )
    text = response.choices[0].message.content
    tokens_in = response.usage.prompt_tokens if response.usage else 0
    tokens_out = response.usage.completion_tokens if response.usage else 0
    return text, tokens_in, tokens_out


def extract_json(text):
    if not text:
        return None
    text = text.strip()
    if "```json" in text:
        text = text.split("```json", 1)[1]
        if "```" in text:
            text = text.split("```")[0]
        text = text.strip()
    elif "```" in text:
        parts = text.split("```")
        for p in parts:
            p = p.strip()
            if p.startswith("{"):
                text = p
                break
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        idx = text.find("{")
        if idx >= 0:
            try:
                return json.loads(text[idx:])
            except json.JSONDecodeError:
                pass
    return None


def insert_parsed(case_report_id, data, raw_json):
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        """INSERT OR REPLACE INTO case_reports_parsed
        (case_report_id, genes, hpo_phenotypes, histology, imaging,
         gestational_age, outcome, inheritance, sample_type,
         key_clinical_features, raw_json)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            case_report_id,
            json.dumps(data.get("genes"), ensure_ascii=False) if data.get("genes") else None,
            json.dumps(data.get("hpo_phenotypes"), ensure_ascii=False) if data.get("hpo_phenotypes") else None,
            json.dumps(data.get("histology"), ensure_ascii=False) if data.get("histology") else None,
            json.dumps(data.get("imaging"), ensure_ascii=False) if data.get("imaging") else None,
            data.get("gestational_age"),
            data.get("outcome"),
            data.get("inheritance"),
            data.get("sample_type"),
            json.dumps(data.get("key_clinical_features"), ensure_ascii=False) if data.get("key_clinical_features") else None,
            raw_json,
        ),
    )
    conn.commit()
    conn.close()


def worker(items, thread_name):
    client = OpenAI(
        base_url="https://openrouter.ai/api/v1",
        api_key=os.environ["OPENROUTER_API_KEY"],
    )

    for i, (cr_id, syndrome_id, gold, text) in enumerate(items):
        try:
            raw, tok_in, tok_out = parse_abstract(client, text, gold or syndrome_id)
            data = extract_json(raw)

            if data:
                insert_parsed(cr_id, data, raw)
                with lock:
                    progress["done"] += 1
            else:
                print(f"  [{thread_name}] {cr_id} PARSE_ERROR", flush=True)
                with lock:
                    progress["errors"] += 1
                    progress["done"] += 1

        except Exception as e:
            print(f"  [{thread_name}] {cr_id} API_ERROR: {e}", flush=True)
            with lock:
                progress["errors"] += 1
                progress["done"] += 1
            time.sleep(2)

        with lock:
            total_done = progress["done"]
            if total_done % NOTIFY_EVERY == 0 and total_done > 0:
                subject = f"[FoetoBase] parse_abstracts — {total_done}/{progress['total']} ({progress['errors']} err)"
                print(f"  [{thread_name}] {subject}", flush=True)
                try:
                    send_email(subject=subject, body=subject, to=NOTIFY_TO)
                except Exception:
                    pass

            if total_done % 100 == 0 and total_done > 0:
                print(f"  === {total_done}/{progress['total']} done ({progress['errors']} err) ===", flush=True)


def main():
    ensure_table()
    todo = get_todo()

    print(f"\n{'=' * 60}", flush=True)
    print(f"Parse abstracts PubMed → champs structurés", flush=True)
    print(f"  {len(todo)} abstracts à traiter (Gemini Flash)", flush=True)
    print(f"{'=' * 60}\n", flush=True)

    if not todo:
        print("Rien à faire !", flush=True)
        return

    progress["total"] = len(todo)

    chunks = [[] for _ in range(N_THREADS)]
    for i, item in enumerate(todo):
        chunks[i % N_THREADS].append(item)

    threads = []
    for t_idx in range(N_THREADS):
        if not chunks[t_idx]:
            continue
        name = f"T{t_idx+1}"
        t = threading.Thread(target=worker, args=(chunks[t_idx], name), daemon=True)
        threads.append(t)

    print(f"Lancement de {len(threads)} threads...\n", flush=True)
    t0 = time.time()
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    elapsed = time.time() - t0
    print(f"\n{'=' * 60}", flush=True)
    print(f"TERMINE — {progress['done']}/{progress['total']} en {elapsed/60:.0f}min ({progress['errors']} err)", flush=True)
    print(f"{'=' * 60}", flush=True)

    subject = f"[FoetoBase] parse_abstracts TERMINE — {progress['done']}/{progress['total']} ({progress['errors']} err)"
    try:
        send_email(subject=subject, body=subject, to=NOTIFY_TO)
    except Exception:
        pass


if __name__ == "__main__":
    main()
