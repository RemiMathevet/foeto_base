#!/usr/bin/env python3
"""Scrape PubMed case reports pour peupler case_reports dans syndromes_foetaux.db.

Utilise NCBI E-utilities (gratuit, 3 req/s sans clé).
Pour chaque syndrome : cherche "{name_en} case report fetal/prenatal/neonatal",
récupère les abstracts, insère dans case_reports.
"""

import sqlite3
import requests
import time
import xml.etree.ElementTree as ET
import re
import importlib.util
from pathlib import Path

DB_PATH = Path("/home/mathevet/Bureau/foeto_base/syndromes_foetaux.db")

ESEARCH_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
EFETCH_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"

MAX_RESULTS_PER_SYNDROME = 15
MIN_ABSTRACT_LEN = 150
RATE_LIMIT = 0.35  # ~3 req/s

NOTIFY_EVERY = 50

spec = importlib.util.spec_from_file_location(
    "notify", "/home/mathevet/Bureau/tmux_supervisor/embeddings/pipeline_v2/08_notify.py"
)
_mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(_mod)
send_email = _mod.send_email
NOTIFY_TO = "remimathevet@gmail.com"


def get_syndromes():
    """Syndromes avec assez de HPO et des discriminateurs."""
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    rows = conn.execute("""
        SELECT s.id, s.name_en, s.name_fr, s.category,
               COUNT(sh.hpo_id) as hpo_count
        FROM syndromes s
        JOIN syndrome_hpo sh ON sh.syndrome_id = s.id
        WHERE s.name_en IS NOT NULL AND s.name_en != ''
        GROUP BY s.id
        HAVING hpo_count >= 3
        ORDER BY hpo_count DESC
    """).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def search_pubmed(syndrome_name, max_results=MAX_RESULTS_PER_SYNDROME):
    """Search PubMed for case reports related to a syndrome."""
    clean_name = syndrome_name.replace("(", "").replace(")", "").strip()
    query = f'"{clean_name}" case report (fetal OR prenatal OR neonatal OR autopsy OR fetus OR newborn)'

    params = {
        "db": "pubmed",
        "term": query,
        "retmax": max_results,
        "retmode": "json",
        "sort": "relevance",
    }

    try:
        resp = requests.get(ESEARCH_URL, params=params, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        return data.get("esearchresult", {}).get("idlist", [])
    except Exception as e:
        print(f"    SEARCH ERROR: {e}", flush=True)
        return []


def fetch_abstracts(pmids):
    """Fetch abstracts for a list of PMIDs."""
    if not pmids:
        return []

    params = {
        "db": "pubmed",
        "id": ",".join(pmids),
        "retmode": "xml",
        "rettype": "abstract",
    }

    try:
        resp = requests.get(EFETCH_URL, params=params, timeout=30)
        resp.raise_for_status()
    except Exception as e:
        print(f"    FETCH ERROR: {e}", flush=True)
        return []

    articles = []
    try:
        root = ET.fromstring(resp.content)
        for article in root.findall(".//PubmedArticle"):
            pmid_el = article.find(".//PMID")
            pmid = pmid_el.text if pmid_el is not None else ""

            title_el = article.find(".//ArticleTitle")
            title = title_el.text if title_el is not None else ""

            abstract_parts = []
            for ab_text in article.findall(".//AbstractText"):
                label = ab_text.get("Label", "")
                text = "".join(ab_text.itertext()).strip()
                if label:
                    abstract_parts.append(f"{label}: {text}")
                else:
                    abstract_parts.append(text)
            abstract = "\n".join(abstract_parts)

            year_el = article.find(".//PubDate/Year")
            year = year_el.text if year_el is not None else ""

            journal_el = article.find(".//Journal/Title")
            journal = journal_el.text if journal_el is not None else ""

            articles.append({
                "pmid": pmid,
                "title": title or "",
                "abstract": abstract,
                "year": year,
                "journal": journal,
            })
    except ET.ParseError as e:
        print(f"    XML PARSE ERROR: {e}", flush=True)

    return articles


def extract_hpo_tags(abstract):
    """Extract rough HPO-like tags from abstract text."""
    keywords = []
    patterns = [
        r'hydrops', r'polydactyly', r'microcephaly', r'macrocephaly',
        r'encephalocele', r'holoprosencephaly', r'renal cyst',
        r'hepatomegaly', r'splenomegaly', r'cardiac', r'skeletal',
        r'short limb', r'narrow thorax', r'cleft', r'omphalocele',
        r'hypotonia', r'seizure', r'calcification', r'ichthyosis',
        r'pterygium', r'contracture', r'arthrogryposis', r'agenesis',
        r'dysplasia', r'hypoplasia', r'atresia', r'stenosis',
    ]
    text_lower = abstract.lower()
    for p in patterns:
        if re.search(p, text_lower):
            keywords.append(p)
    return ", ".join(keywords) if keywords else None


def main():
    syndromes = get_syndromes()
    print(f"Syndromes avec ≥3 HPO : {len(syndromes)}", flush=True)

    conn = sqlite3.connect(str(DB_PATH))

    existing_pmids = set()
    try:
        rows = conn.execute(
            "SELECT source FROM case_reports WHERE source LIKE 'pubmed:%'"
        ).fetchall()
        existing_pmids = {r[0] for r in rows}
    except Exception:
        pass

    total_inserted = 0
    total_skipped = 0
    total_errors = 0
    syndromes_with_results = 0

    for idx, syn in enumerate(syndromes):
        name = syn["name_en"]
        print(f"[{idx+1}/{len(syndromes)}] {name[:60]}...", end="", flush=True)

        pmids = search_pubmed(name)
        time.sleep(RATE_LIMIT)

        if not pmids:
            print(f" 0 results", flush=True)
            continue

        articles = fetch_abstracts(pmids)
        time.sleep(RATE_LIMIT)

        inserted = 0
        for art in articles:
            if not art["abstract"] or len(art["abstract"]) < MIN_ABSTRACT_LEN:
                continue

            source_key = f"pubmed:{art['pmid']}"
            if source_key in existing_pmids:
                total_skipped += 1
                continue

            hpo_tags = extract_hpo_tags(art["abstract"])

            clinical_text = f"[{art['title']}]\n\n{art['abstract']}"
            if art["year"]:
                clinical_text += f"\n\n(Published: {art['year']}"
                if art["journal"]:
                    clinical_text += f", {art['journal']}"
                clinical_text += ")"

            try:
                conn.execute(
                    """INSERT INTO case_reports
                       (syndrome_id, gold_diagnosis, clinical_text, hpo_tags,
                        format, source, source_model, difficulty)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        syn["id"],
                        syn["name_en"],
                        clinical_text,
                        hpo_tags,
                        "pubmed_abstract",
                        source_key,
                        None,
                        "real_case",
                    ),
                )
                existing_pmids.add(source_key)
                inserted += 1
                total_inserted += 1
            except Exception as e:
                total_errors += 1
                if "UNIQUE" not in str(e):
                    print(f" DB ERROR: {e}", flush=True)

        if inserted > 0:
            conn.commit()
            syndromes_with_results += 1

        print(f" {len(pmids)} found, {inserted} inserted", flush=True)

        if (idx + 1) % NOTIFY_EVERY == 0:
            subject = (
                f"[PubMed Scrape] {idx+1}/{len(syndromes)} — "
                f"{total_inserted} cases, {syndromes_with_results} syndromes"
            )
            body = (
                f"Progression: {idx+1}/{len(syndromes)} syndromes\n"
                f"Cases insérés: {total_inserted}\n"
                f"Syndromes avec résultats: {syndromes_with_results}\n"
                f"Skipped (duplicates): {total_skipped}\n"
                f"Errors: {total_errors}"
            )
            try:
                send_email(subject=subject, body=body, to=NOTIFY_TO)
                print(f"  [MAIL] {subject}", flush=True)
            except Exception:
                pass

    conn.close()

    print(f"\n{'=' * 60}", flush=True)
    print(f"TERMINE", flush=True)
    print(f"  Syndromes traités : {len(syndromes)}", flush=True)
    print(f"  Syndromes avec résultats : {syndromes_with_results}", flush=True)
    print(f"  Cases insérés : {total_inserted}", flush=True)
    print(f"  Skipped (duplicates) : {total_skipped}", flush=True)
    print(f"  Errors : {total_errors}", flush=True)

    subject = f"[PubMed Scrape] TERMINE — {total_inserted} cases de {syndromes_with_results} syndromes"
    body = (
        f"Scraping PubMed terminé\n"
        f"{'=' * 40}\n\n"
        f"Syndromes traités : {len(syndromes)}\n"
        f"Syndromes avec résultats : {syndromes_with_results}\n"
        f"Cases insérés : {total_inserted}\n"
        f"Skipped : {total_skipped}\n"
        f"Errors : {total_errors}"
    )
    try:
        send_email(subject=subject, body=body, to=NOTIFY_TO)
    except Exception:
        pass


if __name__ == "__main__":
    main()
