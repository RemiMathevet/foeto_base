#!/usr/bin/env python3
"""Extract HPO terms from French clinical text via fuzzy matching.

Builds an in-memory index of HPO labels/aliases from syndromes_foetaux.db,
then matches clinical text segments against it using normalized substring
matching + optional token-level fuzzy fallback.

Usage as module:
    from hpo_extractor import HPOExtractor
    ext = HPOExtractor()  # loads index once
    matches = ext.extract("encéphalocèle occipitale, reins polykystiques, polydactylie")
    structured = ext.structure_clinical_text(clinical_text)

Usage as CLI:
    python hpo_extractor.py "encéphalocèle, reins polykystiques, polydactylie"
    python hpo_extractor.py --file /path/to/clinical.txt
"""
import os
import re
import sqlite3
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path

DB_PATH = os.environ.get(
    "ORACULUM_SYNDROME_DB",
    str(Path(__file__).resolve().parent / "syndromes_foetaux.db"),
)

MIN_TERM_LEN = 4
MAX_NGRAM_WORDS = 5

_NEGATION_PATTERNS = re.compile(
    r"(?:"
    r"pas\s+d[e']?\s*"
    r"|sans\s+"
    r"|absence\s+(?:totale\s+)?(?:d[e']?\s*)?"
    r"|aucune?\s+"
    r"|ni\s+(?:d[e']?\s*)?"
    r"|(?:non?\s+)?(?:retrouve|observe|identifie|note|visualise|objective|constate)(?:e?s?)\s+"
    r")$",
    re.IGNORECASE,
)

_NEGATION_WINDOW = 40

_STOP_WORDS_CLINICAL = {
    "foetus", "foetal", "foetale", "fetal", "fetale", "grossesse", "examen",
    "externe", "interne", "aspect", "normal", "normale", "normaux",
    "absence", "absent", "absente", "presents", "presente", "present",
    "gauche", "droite", "droit", "bilateral", "bilaterale", "unilateral",
    "anterieur", "posterieur", "superieur", "inferieur", "median", "mediane",
    "severe", "modere", "moderee", "leger", "legere", "important", "importante",
    "diffus", "diffuse", "massif", "massive", "complet", "complete",
    "partiel", "partielle", "discret", "discrete",
    "tissu", "tissus", "cellule", "cellules", "structure", "structures",
    "niveau", "environ", "mesure", "mesurant", "taille", "poids",
    "coupe", "coupes", "coloration", "aspect", "image", "images",
    "premiere", "premier", "deuxieme", "troisieme", "quatrieme",
    "semaine", "semaines", "mois", "annee", "annees", "jours",
    "apres", "avant", "pendant", "depuis", "entre",
    "adresse", "envoye", "realise", "retrouve", "observe", "montre",
    "confirme", "revele", "suggere", "evoque", "compatible",
}


@dataclass
class HPOMatch:
    hpo_id: str
    label_en: str
    label_fr: str
    category: str
    matched_span: str
    confidence: float  # 1.0=exact, 0.85=alias, 0.7=fuzzy
    context: str = ""  # fetal/postnatal/both


def _norm(text: str) -> str:
    t = text.lower().replace("œ", "oe").replace("æ", "ae").replace("ß", "ss")
    t = unicodedata.normalize("NFD", t)
    t = "".join(c for c in t if unicodedata.category(c) != "Mn")
    t = re.sub(r"[''`]", "'", t)
    t = re.sub(r"[–—]", "-", t)
    return t.strip()


def _tokenize_clinical(text: str) -> list[str]:
    """Split clinical text into meaningful segments for matching."""
    text = re.sub(r"\b(\d+)\s*(sa|sg|semaines?)\b", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\b\d+\s*(g|kg|mm|cm|mg|ml|p\.?|percentile)\b", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\b(poids|taille|lcc|pc|pa|bip)\s*:?\s*\d+", "", text, flags=re.IGNORECASE)

    seps = re.split(r"[.;:\n]+", text)
    segments = []
    for seg in seps:
        parts = re.split(r",\s*(?:et\s+)?|(?:\bet\b)", seg)
        for p in parts:
            p = p.strip()
            if len(p) > MIN_TERM_LEN:
                segments.append(p)
    return segments


class HPOExtractor:
    def __init__(self, db_path: str = DB_PATH):
        self._index: dict[str, list[tuple[str, str, str, str, float]]] = {}
        self._hpo_data: dict[str, dict] = {}
        self._load_index(db_path)

    def _load_index(self, db_path: str):
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT hpo_id, label_en, label_fr, category, context, aliases_fr "
            "FROM hpo_terms WHERE is_excluded = 0"
        ).fetchall()
        conn.close()

        for row in rows:
            hpo_id = row["hpo_id"]
            self._hpo_data[hpo_id] = {
                "label_en": row["label_en"] or "",
                "label_fr": row["label_fr"] or "",
                "category": row["category"] or "",
                "context": row["context"] or "both",
            }

            if row["label_fr"]:
                key = _norm(row["label_fr"])
                if len(key) >= MIN_TERM_LEN:
                    self._index.setdefault(key, []).append(
                        (hpo_id, row["label_fr"], row["label_en"] or "", row["category"] or "", 1.0)
                    )

            if row["label_en"]:
                key = _norm(row["label_en"])
                if len(key) >= MIN_TERM_LEN:
                    self._index.setdefault(key, []).append(
                        (hpo_id, row["label_fr"] or row["label_en"], row["label_en"], row["category"] or "", 0.95)
                    )

            if row["aliases_fr"]:
                for alias in re.split(r"\s*\|\s*", row["aliases_fr"]):
                    alias = alias.strip()
                    if len(alias) >= MIN_TERM_LEN:
                        key = _norm(alias)
                        self._index.setdefault(key, []).append(
                            (hpo_id, row["label_fr"] or alias, row["label_en"] or "", row["category"] or "", 0.85)
                        )

        self._sorted_keys = sorted(self._index.keys(), key=len, reverse=True)

    def _is_negated(self, text_norm: str, match_start: int) -> bool:
        window_start = max(0, match_start - _NEGATION_WINDOW)
        prefix = text_norm[window_start:match_start]
        return bool(_NEGATION_PATTERNS.search(prefix))

    def _match_exact(self, text_norm: str) -> list[tuple[str, str, str, str, float, str]]:
        """Find exact substring matches of HPO labels in normalized text.

        Uses word boundary checks to avoid partial word matches
        (e.g. 'tissu' matching inside 'tissulaire').
        Skips matches preceded by negation patterns.
        """
        results = []
        matched_spans = set()
        for key in self._sorted_keys:
            if len(key) < MIN_TERM_LEN:
                continue
            pos = 0
            while True:
                pos = text_norm.find(key, pos)
                if pos == -1:
                    break
                end = pos + len(key)
                before_ok = (pos == 0 or not text_norm[pos - 1].isalpha())
                after_ok = (end >= len(text_norm) or not text_norm[end].isalpha())
                if not (before_ok and after_ok):
                    pos += 1
                    continue
                span = (pos, end)
                overlap = any(
                    not (span[1] <= ms[0] or span[0] >= ms[1])
                    for ms in matched_spans
                )
                if overlap:
                    pos += 1
                    continue
                if self._is_negated(text_norm, pos):
                    pos += 1
                    continue
                matched_spans.add(span)
                for hpo_id, label_fr, label_en, category, base_conf in self._index[key]:
                    results.append((hpo_id, label_fr, label_en, category, base_conf, key))
                break
        return results

    def _match_fuzzy(self, segment: str) -> list[tuple[str, str, str, str, float, str]]:
        """Token-level fuzzy matching — only for multi-word medical terms."""
        seg_norm = _norm(segment)
        tokens = [t for t in seg_norm.split() if len(t) >= 6 and t not in _STOP_WORDS_CLINICAL]
        if len(tokens) < 2:
            return []

        bigrams = [f"{tokens[i]} {tokens[i+1]}" for i in range(len(tokens) - 1)]

        results = []
        seen_hpo = set()
        for bigram in bigrams:
            for key in self._sorted_keys:
                if len(key) < 10:
                    continue
                if bigram in key and key not in seen_hpo:
                    for hpo_id, label_fr, label_en, category, base_conf in self._index[key]:
                        if hpo_id not in seen_hpo:
                            seen_hpo.add(hpo_id)
                            results.append((hpo_id, label_fr, label_en, category, 0.65, bigram))
        return results

    def extract(self, text: str, min_confidence: float = 0.5) -> list[HPOMatch]:
        """Extract HPO terms from clinical text.

        Returns deduplicated matches sorted by confidence descending.
        """
        text_norm = _norm(text)
        raw_matches = self._match_exact(text_norm)

        segments = _tokenize_clinical(text)
        exact_hpo_ids = {m[0] for m in raw_matches}
        for seg in segments:
            seg_norm = _norm(seg)
            for m in self._match_exact(seg_norm):
                if m[0] not in exact_hpo_ids:
                    raw_matches.append(m)
                    exact_hpo_ids.add(m[0])

        matched_hpo_ids = {m[0] for m in raw_matches}
        for seg in segments:
            fuzzy = self._match_fuzzy(seg)
            for m in fuzzy:
                if m[0] not in matched_hpo_ids:
                    raw_matches.append(m)
                    matched_hpo_ids.add(m[0])

        best: dict[str, tuple] = {}
        for hpo_id, label_fr, label_en, category, conf, span in raw_matches:
            if hpo_id not in best or conf > best[hpo_id][4]:
                best[hpo_id] = (hpo_id, label_fr, label_en, category, conf, span)

        results = []
        for hpo_id, label_fr, label_en, category, conf, span in best.values():
            if conf < min_confidence:
                continue
            ctx = self._hpo_data.get(hpo_id, {}).get("context", "both")
            results.append(HPOMatch(
                hpo_id=hpo_id,
                label_en=label_en,
                label_fr=label_fr,
                category=category,
                matched_span=span,
                confidence=conf,
                context=ctx,
            ))

        results.sort(key=lambda m: (-m.confidence, m.category, m.label_fr))
        return results

    def structure_clinical_text(self, clinical_text: str) -> dict:
        """Parse clinical text into structured data for ReAct prompt injection.

        Returns:
            {
                "hpo_terms": [{"hpo_id", "label_fr", "label_en", "category", "confidence"}],
                "by_category": {"Tête / Cou": [...], "Squelette": [...], ...},
                "summary_line": "HP:0002084 Encéphalocèle, HP:0000113 Polykystose rénale, ...",
                "n_matched": int,
            }
        """
        matches = self.extract(clinical_text, min_confidence=0.6)

        by_cat: dict[str, list[dict]] = {}
        terms = []
        for m in matches:
            entry = {
                "hpo_id": m.hpo_id,
                "label_fr": m.label_fr,
                "label_en": m.label_en,
                "category": m.category,
                "confidence": m.confidence,
                "context": m.context,
            }
            terms.append(entry)
            by_cat.setdefault(m.category or "Autre", []).append(entry)

        high_conf = [t for t in terms if t["confidence"] >= 0.85]
        summary_parts = [f"{t['hpo_id']} {t['label_fr']}" for t in high_conf[:20]]
        summary = ", ".join(summary_parts)

        return {
            "hpo_terms": terms,
            "by_category": dict(sorted(by_cat.items())),
            "summary_line": summary,
            "n_matched": len(terms),
        }

    def format_for_prompt(self, clinical_text: str, min_confidence: float = 0.85) -> str:
        """Format structured extraction as a text block for prompt injection.

        Only includes high-confidence matches (exact label_fr + aliases)
        to avoid noise. Lower-confidence fuzzy matches are available
        via structure_clinical_text() for downstream use.
        """
        matches = self.extract(clinical_text, min_confidence=min_confidence)
        if not matches:
            return ""

        by_cat: dict[str, list[HPOMatch]] = {}
        for m in matches:
            by_cat.setdefault(m.category or "Autre", []).append(m)

        lines = [f"[HPO EXTRACTION — {len(matches)} termes identifiés]"]
        for cat in sorted(by_cat.keys()):
            terms = by_cat[cat]
            term_strs = []
            for t in terms:
                conf_tag = "" if t.confidence >= 0.95 else " ~"
                term_strs.append(f"{t.hpo_id} {t.label_fr}{conf_tag}")
            lines.append(f"  {cat}: {' | '.join(term_strs)}")

        return "\n".join(lines)


_extractor: HPOExtractor | None = None


def get_extractor() -> HPOExtractor:
    global _extractor
    if _extractor is None:
        _extractor = HPOExtractor()
    return _extractor


if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("Usage: python hpo_extractor.py <text> | --file <path>")
        sys.exit(1)

    if sys.argv[1] == "--file":
        with open(sys.argv[2]) as f:
            text = f.read()
    else:
        text = " ".join(sys.argv[1:])

    ext = HPOExtractor()
    print(ext.format_for_prompt(text))
    print()
    data = ext.structure_clinical_text(text)
    print(f"Total: {data['n_matched']} HPO terms")
    print(f"Summary: {data['summary_line']}")
