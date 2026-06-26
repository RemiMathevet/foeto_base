#!/usr/bin/env python3
"""Extract FOETO terms from French clinical text via fuzzy matching.

Same pattern as hpo_extractor.py — builds an in-memory index of FOETO
labels (FR + EN + merged_from aliases) from syndromes_foetaux.db, then
matches clinical text segments using normalized substring matching +
optional token-level fuzzy fallback.

Usage as module:
    from foeto_extractor import FOETOExtractor
    ext = FOETOExtractor()
    matches = ext.extract("polymicrogyrie périsylvienne avec hétérotopies neuronales")

Usage as CLI:
    python foeto_extractor.py "cortex désorganisé, polymicrogyrie, dilatation ventriculaire"
    python foeto_extractor.py --file /path/to/vignette.txt
"""
import os
import re
import sqlite3
import unicodedata
from dataclasses import dataclass
from pathlib import Path

DB_PATH = os.environ.get(
    "ORACULUM_SYNDROME_DB",
    str(Path(__file__).resolve().parent / "syndromes_foetaux.db"),
)

MIN_TERM_LEN = 4
MAX_NGRAM_WORDS = 6

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

_NORMALITY_PATTERNS = re.compile(
    r"(?:"
    r"dans\s+l(?:a|es)\s+normes?"
    r"|de\s+(?:taille|volume|poids)\s+normal(?:e|aux)?"
    r"|sans\s+(?:particularite|anomalie)"
    r"|\bras\b"
    r"|parai(?:t|ssent)\s+normal(?:e|aux)?"
    r"|semble(?:nt)?\s+normal(?:e|aux)?"
    r"|d'aspect\s+normal(?:e|aux)?"
    r"|normes?\s+pour\s+(?:le\s+terme|l'age)"
    r"|proportionn(?:e|ee|es)?"
    r"|bien\s+(?:forme|developpe|visualise)(?:e?s?)?"
    r"|en\s+place"
    r"|(?:a|aux)\s+limites?\s+(?:de\s+la\s+)?normal(?:e|es)?"
    r")",
    re.IGNORECASE,
)

_NEGATION_WINDOW = 40
_NORMALITY_WINDOW = 60
_CONTEXT_WINDOW = 150
_CONTEXT_COVERAGE_THRESHOLD = 0.75

_DETERMINERS = {
    "de", "du", "des", "le", "la", "les", "l", "d", "un", "une",
    "et", "a", "au", "aux", "en", "par", "pour", "avec", "dans",
    "sur", "ou", "qui", "que", "ce", "se", "son", "sa", "ses",
}

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


def _norm(text: str) -> str:
    t = text.lower().replace("œ", "oe").replace("æ", "ae").replace("ß", "ss")
    t = unicodedata.normalize("NFD", t)
    t = "".join(c for c in t if unicodedata.category(c) != "Mn")
    t = re.sub(r"[''`]", "'", t)
    t = re.sub(r"[–—]", "-", t)
    return t.strip()


def _tokenize_clinical(text: str) -> list[str]:
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


@dataclass
class FOETOMatch:
    foeto_id: str
    label_fr: str
    label_en: str
    organe: str
    matched_span: str
    confidence: float  # 1.0=exact FR, 0.95=exact EN, 0.85=alias, 0.65=fuzzy
    negated: bool = False


class FOETOExtractor:
    def __init__(self, db_path: str = DB_PATH):
        # index: norm_key → [(foeto_id, label_fr, label_en, organe, base_conf)]
        self._index: dict[str, list[tuple[str, str, str, str, float]]] = {}
        self._term_data: dict[str, dict] = {}
        self._load_index(db_path)

    def _load_index(self, db_path: str):
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT id, label_fr, label_en, organe, merged_from, cr_description "
            "FROM foeto_terms"
        ).fetchall()
        conn.close()

        for row in rows:
            fid = row["id"]
            self._term_data[fid] = {
                "label_fr": row["label_fr"] or "",
                "label_en": row["label_en"] or "",
                "organe": row["organe"] or "",
            }

            if row["label_fr"]:
                key = _norm(row["label_fr"])
                if len(key) >= MIN_TERM_LEN:
                    self._index.setdefault(key, []).append(
                        (fid, row["label_fr"], row["label_en"] or "", row["organe"] or "", 1.0)
                    )

            if row["label_en"]:
                key = _norm(row["label_en"])
                if len(key) >= MIN_TERM_LEN:
                    self._index.setdefault(key, []).append(
                        (fid, row["label_fr"] or row["label_en"], row["label_en"], row["organe"] or "", 0.95)
                    )

            # merged_from IDs → chercher les labels de ces termes comme aliases
            if row["merged_from"]:
                for alias_id in re.split(r"[,|]+", row["merged_from"]):
                    alias_id = alias_id.strip()
                    if not alias_id:
                        continue
                    # L'alias_id est un FOETO ID — on l'indexe par son propre label
                    # (sera résolu si le terme existe, sinon ignoré)
                    self._index.setdefault(_norm(alias_id), [])  # placeholder

            if row["cr_description"]:
                key = _norm(row["cr_description"])
                if len(key) >= MIN_TERM_LEN:
                    self._index.setdefault(key, []).append(
                        (fid, row["label_fr"] or "", row["label_en"] or "", row["organe"] or "", 0.85)
                    )

        # Résoudre les merged_from : indexer les labels des termes fusionnés
        conn2 = sqlite3.connect(db_path)
        conn2.row_factory = sqlite3.Row
        for row in rows:
            if not row["merged_from"]:
                continue
            fid = row["id"]
            for alias_id in re.split(r"[,|]+", row["merged_from"]):
                alias_id = alias_id.strip()
                if not alias_id:
                    continue
                alias_row = conn2.execute(
                    "SELECT label_fr, label_en FROM foeto_terms WHERE id = ?", (alias_id,)
                ).fetchone()
                if alias_row:
                    for label in (alias_row["label_fr"], alias_row["label_en"]):
                        if label:
                            key = _norm(label)
                            if len(key) >= MIN_TERM_LEN:
                                self._index.setdefault(key, []).append(
                                    (fid, row["label_fr"] or "", row["label_en"] or "", row["organe"] or "", 0.85)
                                )
        conn2.close()

        self._sorted_keys = sorted(self._index.keys(), key=len, reverse=True)

        self._reverse_index: dict[str, set[str]] = {}
        for key, entries in self._index.items():
            for fid, *_ in entries:
                self._reverse_index.setdefault(fid, set()).add(key)

    @staticmethod
    def _sentence_window(text: str, pos: int, window: int, direction: str) -> str:
        """Return text within window but clipped at sentence boundaries."""
        _SENT_BOUNDARY = re.compile(r"[.;:\n]")
        if direction == "before":
            start = max(0, pos - window)
            chunk = text[start:pos]
            m = _SENT_BOUNDARY.search(chunk[::-1])  # ponytail: reverse search for last boundary
            if m:
                chunk = chunk[len(chunk) - m.start():]
            return chunk
        else:
            end = min(len(text), pos + window)
            chunk = text[pos:end]
            m = _SENT_BOUNDARY.search(chunk)
            if m:
                chunk = chunk[:m.start()]
            return chunk

    def _is_negated(self, text_norm: str, match_start: int, match_end: int | None = None) -> bool:
        prefix = self._sentence_window(text_norm, match_start, _NEGATION_WINDOW, "before")
        if _NEGATION_PATTERNS.search(prefix):
            return True
        pre_text = self._sentence_window(text_norm, match_start, _NORMALITY_WINDOW, "before")
        if _NORMALITY_PATTERNS.search(pre_text):
            return True
        if match_end is not None:
            post_text = self._sentence_window(text_norm, match_end, _NORMALITY_WINDOW, "after")
            if _NORMALITY_PATTERNS.search(post_text):
                return True
        return False

    def _match_exact(self, text_norm: str) -> list[tuple[str, str, str, str, float, str, bool]]:
        results = []
        matched_spans = set()
        for key in self._sorted_keys:
            if len(key) < MIN_TERM_LEN:
                continue
            entries = self._index[key]
            if not entries:
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
                neg = self._is_negated(text_norm, pos, end)
                matched_spans.add(span)
                for fid, label_fr, label_en, organe, base_conf in entries:
                    results.append((fid, label_fr, label_en, organe, base_conf, key, neg))
                break
        return results

    def _context_coverage(self, text_norm: str, foeto_id: str, span: str) -> float:
        pos = text_norm.find(span)
        if pos == -1:
            return 0.0
        win_start = max(0, pos - _CONTEXT_WINDOW)
        win_end = min(len(text_norm), pos + len(span) + _CONTEXT_WINDOW)
        context = text_norm[win_start:win_end]

        best_ratio = 0.0
        for key in self._reverse_index.get(foeto_id, ()):
            content_words = [w for w in key.split() if w not in _DETERMINERS]
            if not content_words:
                continue
            total = sum(len(w) for w in content_words)
            matched = sum(len(w) for w in content_words if w in context)
            ratio = matched / total
            if ratio > best_ratio:
                best_ratio = ratio
        return best_ratio

    def _match_fuzzy(self, segment: str) -> list[tuple[str, str, str, str, float, str, bool]]:
        seg_norm = _norm(segment)
        if _NORMALITY_PATTERNS.search(seg_norm):
            return []
        tokens = [t for t in seg_norm.split() if len(t) >= 5 and t not in _STOP_WORDS_CLINICAL]
        if len(tokens) < 2:
            return []

        bigrams = [f"{tokens[i]} {tokens[i+1]}" for i in range(len(tokens) - 1)]

        results = []
        seen = set()
        for bigram in bigrams:
            for key in self._sorted_keys:
                if len(key) < 10:
                    continue
                entries = self._index[key]
                if not entries and key not in seen:
                    continue
                if bigram in key:
                    for fid, label_fr, label_en, organe, _ in entries:
                        if fid not in seen:
                            seen.add(fid)
                            results.append((fid, label_fr, label_en, organe, 0.65, bigram, False))
        return results

    def extract(self, text: str, min_confidence: float = 0.5) -> list[FOETOMatch]:
        text_norm = _norm(text)
        raw = self._match_exact(text_norm)

        segments = _tokenize_clinical(text)
        exact_ids = {m[0] for m in raw}
        for seg in segments:
            for m in self._match_exact(_norm(seg)):
                if m[0] not in exact_ids:
                    raw.append(m)
                    exact_ids.add(m[0])

        matched_ids = {m[0] for m in raw}
        for seg in segments:
            for m in self._match_fuzzy(seg):
                if m[0] not in matched_ids:
                    cov = self._context_coverage(text_norm, m[0], m[5])
                    if cov >= _CONTEXT_COVERAGE_THRESHOLD:
                        raw.append(m)
                        matched_ids.add(m[0])

        best: dict[str, tuple] = {}
        for fid, label_fr, label_en, organe, conf, span, neg in raw:
            if fid not in best or conf > best[fid][4]:
                best[fid] = (fid, label_fr, label_en, organe, conf, span, neg)

        results = []
        for fid, label_fr, label_en, organe, conf, span, neg in best.values():
            if conf < min_confidence:
                continue
            results.append(FOETOMatch(
                foeto_id=fid,
                label_fr=label_fr,
                label_en=label_en,
                organe=organe,
                matched_span=span,
                confidence=conf,
                negated=neg,
            ))

        results.sort(key=lambda m: (-m.confidence, m.organe, m.label_fr))
        return results

    def structure_clinical_text(self, clinical_text: str) -> dict:
        matches = self.extract(clinical_text, min_confidence=0.6)

        by_organ: dict[str, list[dict]] = {}
        terms = []
        for m in matches:
            entry = {
                "foeto_id": m.foeto_id,
                "label_fr": m.label_fr,
                "label_en": m.label_en,
                "organe": m.organe,
                "confidence": m.confidence,
                "negated": m.negated,
            }
            terms.append(entry)
            by_organ.setdefault(m.organe or "autre", []).append(entry)

        high_conf = [t for t in terms if t["confidence"] >= 0.85 and not t["negated"]]
        summary = ", ".join(f"{t['foeto_id']} {t['label_fr']}" for t in high_conf[:20])

        return {
            "foeto_terms": terms,
            "by_organ": dict(sorted(by_organ.items())),
            "summary_line": summary,
            "n_matched": len(terms),
            "n_negated": sum(1 for t in terms if t["negated"]),
        }

    def format_for_prompt(self, clinical_text: str, min_confidence: float = 0.85) -> str:
        matches = self.extract(clinical_text, min_confidence=min_confidence)
        if not matches:
            return ""

        by_organ: dict[str, list[FOETOMatch]] = {}
        for m in matches:
            by_organ.setdefault(m.organe or "autre", []).append(m)

        pos = [m for m in matches if not m.negated]
        neg = [m for m in matches if m.negated]

        lines = [f"[FOETO EXTRACTION — {len(pos)} signes, {len(neg)} absents]"]
        for organ in sorted(by_organ.keys()):
            terms = by_organ[organ]
            parts = []
            for t in terms:
                tag = " [absent]" if t.negated else ""
                conf = "" if t.confidence >= 0.95 else " ~"
                parts.append(f"{t.foeto_id} {t.label_fr}{conf}{tag}")
            lines.append(f"  {organ}: {' | '.join(parts)}")

        return "\n".join(lines)


_extractor: FOETOExtractor | None = None


def get_extractor() -> FOETOExtractor:
    global _extractor
    if _extractor is None:
        _extractor = FOETOExtractor()
    return _extractor


if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("Usage: python foeto_extractor.py <text> | --file <path>")
        sys.exit(1)

    if sys.argv[1] == "--file":
        with open(sys.argv[2]) as f:
            text = f.read()
    else:
        text = " ".join(sys.argv[1:])

    ext = FOETOExtractor()
    print(ext.format_for_prompt(text, min_confidence=0.6))
    print()
    data = ext.structure_clinical_text(text)
    print(f"Total: {data['n_matched']} FOETO terms ({data['n_negated']} negated)")
    print(f"Summary: {data['summary_line']}")
