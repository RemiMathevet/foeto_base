#!/usr/bin/env python3
"""Scrape GeneReviews from NCBI Bookshelf — extract clinical sections."""
import requests, re, json, sqlite3, time, sys, os
from html.parser import HTMLParser

DB_PATH = os.path.join(os.path.dirname(__file__), "syndromes_foetaux.db")
INDEX_PATH = "/tmp/genereviews_index.tsv"
OUTPUT_DIR = "/tmp/genereviews_raw"
RATE_LIMIT = 0.35  # ~3 req/sec
HEADERS = {"User-Agent": "FoetoLookup/1.0 (medical-research; fetopathology-benchmark)"}

SECTIONS_OF_INTEREST = [
    "clinical characteristics",
    "clinical description",
    "clinical features",
    "suggestive findings",
    "establishing the diagnosis",
    "differential diagnosis",
    "genotype-phenotype correlations",
    "genotype-phenotype correlation",
    "prevalence",
    "nomenclature",
]


class SectionExtractor(HTMLParser):
    """Extract text grouped by heading from GeneReviews HTML."""

    def __init__(self):
        super().__init__()
        self.sections = {}
        self.current_heading = None
        self.current_text = []
        self.in_heading = False
        self.heading_level = 0
        self.skip_tags = {"script", "style", "nav", "footer", "header"}
        self.skip_depth = 0
        self.title = None
        self.in_title = False
        self.omim_ids = []
        self.gene_symbols = []
        self._tag_stack = []

    def handle_starttag(self, tag, attrs):
        attrs_d = dict(attrs)
        if tag in self.skip_tags:
            self.skip_depth += 1
            return
        if self.skip_depth:
            return

        if tag == "title" and not self.title:
            self.in_title = True

        if tag in ("h1", "h2", "h3", "h4"):
            if self.current_heading and self.current_text:
                self._save_section()
            self.in_heading = True
            self.heading_level = int(tag[1])
            self.current_text = []

        if tag == "em":
            self._tag_stack.append("em")

        if tag == "a":
            href = attrs_d.get("href", "")
            m = re.search(r"omim\.org/entry/(\d{6})", href)
            if m:
                self.omim_ids.append(m.group(1))

    def handle_endtag(self, tag):
        if tag in self.skip_tags and self.skip_depth > 0:
            self.skip_depth -= 1
            return
        if self.skip_depth:
            return

        if tag == "title":
            self.in_title = False

        if tag in ("h1", "h2", "h3", "h4") and self.in_heading:
            heading_text = "".join(self.current_text).strip()
            self.current_heading = heading_text
            self.current_text = []
            self.in_heading = False

        if tag == "em" and self._tag_stack and self._tag_stack[-1] == "em":
            self._tag_stack.pop()

        if tag in ("p", "li", "tr", "br", "div"):
            self.current_text.append("\n")

    def handle_data(self, data):
        if self.skip_depth:
            return
        if self.in_title and not self.title:
            self.title = data.strip()

        if self._tag_stack and self._tag_stack[-1] == "em":
            sym = data.strip()
            if re.match(r"^[A-Z][A-Z0-9]{1,15}$", sym):
                self.gene_symbols.append(sym)

        self.current_text.append(data)

    def _save_section(self):
        if self.current_heading:
            key = self.current_heading.strip()
            text = "".join(self.current_text).strip()
            text = re.sub(r"\n{3,}", "\n\n", text)
            if key not in self.sections:
                self.sections[key] = text
            else:
                self.sections[key] += "\n\n" + text

    def finish(self):
        if self.current_heading and self.current_text:
            self._save_section()


def fetch_entry(slug):
    url = f"https://www.ncbi.nlm.nih.gov/books/n/gene/{slug}/"
    r = requests.get(url, headers=HEADERS, timeout=30)
    if r.status_code != 200:
        return None

    ext = SectionExtractor()
    ext.feed(r.text)
    ext.finish()

    omim_extra = re.findall(r"OMIM[:\s#]*(\d{6})", r.text)
    all_omim = list(set(ext.omim_ids + omim_extra))

    all_genes = list(set(ext.gene_symbols))

    clinical = {}
    for sec_name, sec_text in ext.sections.items():
        sec_lower = sec_name.lower().strip()
        for target in SECTIONS_OF_INTEREST:
            if target in sec_lower:
                if len(sec_text) > 50:
                    clinical[sec_name] = sec_text[:8000]
                break

    return {
        "title": ext.title,
        "slug": slug,
        "omim": all_omim[:10],
        "genes": all_genes[:20],
        "sections": clinical,
        "all_section_names": list(ext.sections.keys()),
        "n_sections_total": len(ext.sections),
    }


def create_table(conn):
    conn.execute("""
        CREATE TABLE IF NOT EXISTS genereviews (
            slug        TEXT PRIMARY KEY,
            title       TEXT NOT NULL,
            omim_ids    TEXT,
            genes       TEXT,
            clinical_text TEXT,
            differential TEXT,
            suggestive   TEXT,
            diagnosis    TEXT,
            genotype_phenotype TEXT,
            prevalence   TEXT,
            all_sections TEXT,
            scraped_at   TEXT DEFAULT (datetime('now'))
        )
    """)
    conn.commit()


def store_entry(conn, data):
    sections = data["sections"]

    def find_section(keywords):
        for k, v in sections.items():
            kl = k.lower()
            if any(kw in kl for kw in keywords):
                return v
        return None

    clinical = find_section(["clinical characteristics", "clinical description", "clinical features"])
    differential = find_section(["differential diagnosis"])
    suggestive = find_section(["suggestive findings"])
    diagnosis = find_section(["establishing the diagnosis"])
    genopheno = find_section(["genotype-phenotype"])
    prevalence = find_section(["prevalence"])

    # Combine for clinical_text: suggestive + clinical + establishing
    parts = []
    if suggestive:
        parts.append(f"=== Suggestive Findings ===\n{suggestive}")
    if clinical:
        parts.append(f"=== Clinical Characteristics ===\n{clinical}")
    if diagnosis:
        parts.append(f"=== Establishing the Diagnosis ===\n{diagnosis}")
    clinical_text = "\n\n".join(parts) if parts else None

    conn.execute(
        """INSERT OR REPLACE INTO genereviews
           (slug, title, omim_ids, genes, clinical_text, differential,
            suggestive, diagnosis, genotype_phenotype, prevalence, all_sections)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        [
            data["slug"],
            data["title"] or data["slug"],
            json.dumps(data["omim"]),
            json.dumps(data["genes"]),
            clinical_text,
            differential,
            suggestive,
            diagnosis,
            genopheno,
            prevalence,
            json.dumps(data["all_section_names"]),
        ],
    )


def main():
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    entries = []
    with open(INDEX_PATH) as f:
        for line in f:
            parts = line.strip().split("\t", 1)
            if len(parts) == 2:
                entries.append((parts[0], parts[1]))

    conn = sqlite3.connect(DB_PATH)
    create_table(conn)

    already = {r[0] for r in conn.execute("SELECT slug FROM genereviews").fetchall()}
    todo = [(s, t) for s, t in entries if s not in already]

    print(f"GeneReviews scraper: {len(entries)} total, {len(already)} already done, {len(todo)} to fetch")

    success = 0
    errors = 0

    for i, (slug, title) in enumerate(todo):
        try:
            data = fetch_entry(slug)
            if data:
                store_entry(conn, data)
                n_clinical = len(data["sections"])
                clinical_len = sum(len(v) for v in data["sections"].values())
                print(f"  [{i+1}/{len(todo)}] {slug:40s} {n_clinical} sections, {clinical_len:5d} chars, {len(data['genes'])} genes, {len(data['omim'])} OMIM")
                success += 1

                with open(os.path.join(OUTPUT_DIR, f"{slug}.json"), "w") as f:
                    json.dump(data, f, ensure_ascii=False, indent=2)
            else:
                print(f"  [{i+1}/{len(todo)}] {slug:40s} FAILED (HTTP error)")
                errors += 1

            if (i + 1) % 20 == 0:
                conn.commit()

        except Exception as e:
            print(f"  [{i+1}/{len(todo)}] {slug:40s} ERROR: {e}")
            errors += 1

        time.sleep(RATE_LIMIT)

    conn.commit()

    stats = conn.execute("""
        SELECT COUNT(*) as total,
               SUM(CASE WHEN clinical_text IS NOT NULL THEN 1 ELSE 0 END) as with_clinical,
               SUM(CASE WHEN differential IS NOT NULL THEN 1 ELSE 0 END) as with_diff,
               SUM(CASE WHEN genes != '[]' THEN 1 ELSE 0 END) as with_genes
        FROM genereviews
    """).fetchone()

    conn.close()

    print(f"\nDone: {success} scraped, {errors} errors")
    print(f"DB: {stats[0]} entries, {stats[1]} with clinical, {stats[2]} with differential, {stats[3]} with genes")


if __name__ == "__main__":
    main()
