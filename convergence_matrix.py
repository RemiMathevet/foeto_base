#!/usr/bin/env python3
"""Étape 4 — Matrice de convergence multi-canal (RRF 4 voies).

Retrieval multi-canal pour diagnostic différentiel fœtopathologique :
  Canal 1 : BioLORD cosine (vec_chunks — 25K vecteurs)
  Canal 2 : HPO structuré (extraction termes HPO → syndrome_hpo probabiliste)
  Canal 3 : Akinator (scoring IC-pondéré bayésien avec pénalité d'absence)
  Canal 4 : FTS5 keyword (case_reports + chunk_meta)

PubMedBERT retiré : CCA montre r > 0.85 sur 50 composantes — redondant avec BioLORD.
Fusion par Reciprocal Rank Fusion (RRF) au niveau syndrome.

Usage:
    python convergence_matrix.py "RCIU, agénésie corps calleux, polydactylie"
    python convergence_matrix.py --bench              # évaluer sur le benchmark
    python convergence_matrix.py --bench --top 10
    python convergence_matrix.py --bench --sweep       # sweep RRF k
"""
import argparse
import json
import re
import sqlite3
import struct
import time
from collections import defaultdict
from pathlib import Path

import numpy as np

DB_PATH = str(Path(__file__).resolve().parent / "syndromes_foetaux.db")
RRF_K = 30
TOP_K_PER_CHANNEL = 50
TOP_K_FINAL = 10


def serialize_vec(vec):
    return struct.pack(f"{len(vec)}f", *vec)


class ConvergenceMatrix:
    def __init__(self, db_path=DB_PATH, load_models=True, rrf_k=RRF_K):
        import sqlite_vec
        self.conn = sqlite3.connect(db_path)
        self.conn.enable_load_extension(True)
        sqlite_vec.load(self.conn)
        self.conn.row_factory = sqlite3.Row
        self.rrf_k = rrf_k

        self._build_chunk_to_syndrome_map()
        self._init_fts_chunk_meta()
        self._load_hpo_ic()
        self._load_syndrome_expected_hpo()

        if load_models:
            self._load_models()
        else:
            self.biolord = None

    def _load_models(self):
        from sentence_transformers import SentenceTransformer
        print("Loading BioLORD-2023...")
        self.biolord = SentenceTransformer("FremyCompany/BioLORD-2023")

        from hpo_extractor import HPOExtractor
        print("Loading HPO extractor...")
        self.hpo_extractor = HPOExtractor(db_path=DB_PATH)

        self._load_syndrome_hpo()

    def _load_hpo_ic(self):
        self.hpo_ic = {}
        for hpo_id, ic in self.conn.execute("SELECT hpo_id, ic FROM hpo_ic").fetchall():
            self.hpo_ic[hpo_id] = ic

    def _load_syndrome_expected_hpo(self):
        self.syndrome_expected = defaultdict(list)
        rows = self.conn.execute(
            "SELECT syndrome_id, hpo_id, prob FROM syndrome_hpo WHERE prob > 0.3"
        ).fetchall()
        for sid, hpo_id, prob in rows:
            self.syndrome_expected[sid].append((hpo_id, prob))
        self.postnatal_hpos = set()
        for (hpo_id,) in self.conn.execute(
            "SELECT hpo_id FROM hpo_terms WHERE context = 'postnatal'"
        ).fetchall():
            self.postnatal_hpos.add(hpo_id)

        self.syndrome_vf = defaultdict(list)
        rows_vf = self.conn.execute(
            "SELECT syndrome_id, hpo_id, prob FROM syndrome_hpo WHERE prob >= 0.7"
        ).fetchall()
        for sid, hpo_id, prob in rows_vf:
            self.syndrome_vf[sid].append((hpo_id, prob))

        self.hpo_ancestors_map = defaultdict(set)
        for hpo_id, ancestor_id, dist in self.conn.execute(
            "SELECT hpo_id, ancestor_id, distance FROM hpo_ancestors WHERE distance <= 2"
        ).fetchall():
            self.hpo_ancestors_map[hpo_id].add(ancestor_id)
            self.hpo_ancestors_map[ancestor_id].add(hpo_id)

    def _load_syndrome_hpo(self):
        """Pre-load syndrome_hpo for the HPO channel."""
        self.hpo_to_syndromes = defaultdict(list)
        rows = self.conn.execute(
            "SELECT syndrome_id, hpo_id, prob FROM syndrome_hpo WHERE prob > 0"
        ).fetchall()
        for sid, hpo_id, prob in rows:
            self.hpo_to_syndromes[hpo_id].append((sid, prob))
        print(f"  HPO index: {len(self.hpo_to_syndromes)} terms → {len(rows)} associations")

    def _build_chunk_to_syndrome_map(self):
        """Pre-build rowid → syndrome_id mapping for all chunks."""
        self.chunk_syndrome = {}

        for rowid, title in self.conn.execute(
            "SELECT rowid, title FROM chunk_meta WHERE source_type = 'vignette'"
        ).fetchall():
            self.chunk_syndrome[rowid] = title

        cr_map = {}
        for cid, sid in self.conn.execute(
            "SELECT id, syndrome_id FROM case_reports WHERE syndrome_id IS NOT NULL"
        ).fetchall():
            cr_map[str(cid)] = sid

        for rowid, source_id in self.conn.execute(
            "SELECT rowid, source_id FROM chunk_meta WHERE source_type = 'pubmed'"
        ).fetchall():
            if source_id in cr_map:
                self.chunk_syndrome[rowid] = cr_map[source_id]

        gr_title_map = self._build_gr_syndrome_map()
        for rowid, source_id in self.conn.execute(
            "SELECT rowid, source_id FROM chunk_meta WHERE source_type = 'genereviews'"
        ).fetchall():
            if source_id in gr_title_map:
                self.chunk_syndrome[rowid] = gr_title_map[source_id]

        n_mapped = len(self.chunk_syndrome)
        n_total = self.conn.execute("SELECT COUNT(*) FROM chunk_meta").fetchone()[0]
        self._n_mapped = n_mapped
        self._n_total = n_total

    def _build_gr_syndrome_map(self):
        syn_lookup = {}
        for row in self.conn.execute("SELECT id, name_en, name_fr FROM syndromes").fetchall():
            if row["name_en"]:
                syn_lookup[row["name_en"].lower().strip()] = row["id"]
            if row["name_fr"]:
                syn_lookup[row["name_fr"].lower().strip()] = row["id"]

        gr_map = {}
        for slug, title in self.conn.execute("SELECT slug, title FROM genereviews").fetchall():
            clean = title.split(" - GeneReviews")[0].strip().lower() if title else ""
            if clean in syn_lookup:
                gr_map[slug] = syn_lookup[clean]
        return gr_map

    def _init_fts_chunk_meta(self):
        """Create FTS5 index on chunk_meta if not exists."""
        existing = self.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='chunk_meta_fts'"
        ).fetchone()
        if not existing:
            print("Creating FTS5 index on chunk_meta...")
            self.conn.execute("""
                CREATE VIRTUAL TABLE chunk_meta_fts USING fts5(
                    chunk_text,
                    title,
                    content='chunk_meta',
                    content_rowid='rowid'
                )
            """)
            self.conn.execute(
                "INSERT INTO chunk_meta_fts(chunk_meta_fts) VALUES('rebuild')"
            )
            self.conn.commit()
            n = self.conn.execute("SELECT COUNT(*) FROM chunk_meta_fts").fetchone()[0]
            print(f"  Indexed {n} chunks in chunk_meta_fts")

    # ── Channel 1: BioLORD cosine ──

    def _load_chunk_matrix(self):
        rows = self.conn.execute("SELECT rowid, embedding FROM vec_chunks").fetchall()
        rowids = []
        vecs = []
        for rowid, emb in rows:
            rowids.append(rowid)
            vecs.append(np.frombuffer(emb, dtype=np.float32))
        self._chunk_matrix = np.stack(vecs)
        self._chunk_rowids = np.array(rowids)

    def _channel_biolord(self, query_emb, top_k=TOP_K_PER_CHANNEL):
        emb_blob = serialize_vec(query_emb)
        rows = self.conn.execute("""
            SELECT rowid, distance
            FROM vec_chunks
            WHERE embedding MATCH ?
            ORDER BY distance
            LIMIT ?
        """, (emb_blob, top_k * 5)).fetchall()

        syndrome_best = {}
        for rowid, dist in rows:
            sid = self.chunk_syndrome.get(rowid)
            if not sid:
                continue
            cosine = 1.0 - dist
            if sid not in syndrome_best or cosine > syndrome_best[sid]:
                syndrome_best[sid] = cosine

        ranked = sorted(syndrome_best.items(), key=lambda x: -x[1])[:top_k]
        return {sid: i + 1 for i, (sid, _) in enumerate(ranked)}

    def _channel_biolord_batch(self, query_embs, top_k=TOP_K_PER_CHANNEL):
        if not hasattr(self, '_chunk_matrix'):
            self._load_chunk_matrix()
        cosines = query_embs @ self._chunk_matrix.T
        n_retrieve = top_k * 5
        all_ranks = []
        for i in range(len(query_embs)):
            top_idx = np.argpartition(cosines[i], -n_retrieve)[-n_retrieve:]
            top_idx = top_idx[np.argsort(-cosines[i][top_idx])]
            syndrome_best = {}
            for idx in top_idx:
                rowid = int(self._chunk_rowids[idx])
                sid = self.chunk_syndrome.get(rowid)
                if not sid:
                    continue
                cos = float(cosines[i][idx])
                if sid not in syndrome_best or cos > syndrome_best[sid]:
                    syndrome_best[sid] = cos
            ranked = sorted(syndrome_best.items(), key=lambda x: -x[1])[:top_k]
            all_ranks.append({sid: j + 1 for j, (sid, _) in enumerate(ranked)})
        return all_ranks

    # ── Channel 2: HPO structuré ──

    def _extract_hpo(self, clinical_text):
        return self.hpo_extractor.extract(clinical_text, min_confidence=0.6)

    def _channel_hpo(self, clinical_text, top_k=TOP_K_PER_CHANNEL, hpo_matches=None):
        matches = hpo_matches if hpo_matches is not None else self._extract_hpo(clinical_text)
        if not matches:
            return {}

        syndrome_scores = defaultdict(float)
        for m in matches:
            assocs = self.hpo_to_syndromes.get(m.hpo_id, [])
            for sid, prob in assocs:
                syndrome_scores[sid] += prob * m.confidence

        ranked = sorted(syndrome_scores.items(), key=lambda x: -x[1])[:top_k]
        return {sid: i + 1 for i, (sid, _) in enumerate(ranked)}

    # ── Channel 3: Akinator (IC-weighted Bayesian with absence penalty) ──

    def _channel_akinator(self, clinical_text, top_k=TOP_K_PER_CHANNEL, hpo_matches=None):
        matches = hpo_matches if hpo_matches is not None else self._extract_hpo(clinical_text)
        if not matches:
            return {}

        present = {m.hpo_id: m.confidence for m in matches}
        alpha = 0.15

        candidate_sids = set()
        for hpo_id in present:
            for sid, _ in self.hpo_to_syndromes.get(hpo_id, []):
                candidate_sids.add(sid)

        scores = {}
        for sid in candidate_sids:
            expected = self.syndrome_expected.get(sid, [])
            if not expected:
                continue
            score = 0.0
            for hpo_id, prob in expected:
                ic = self.hpo_ic.get(hpo_id, 1.0)
                if hpo_id in present:
                    score += prob * ic * present[hpo_id]
                elif hpo_id not in self.postnatal_hpos:
                    score -= alpha * prob * ic
            scores[sid] = score

        ranked = sorted(scores.items(), key=lambda x: -x[1])[:top_k]
        return {sid: i + 1 for i, (sid, _) in enumerate(ranked)}

    # ── Channel 4: FTS5 (case_reports + chunk_meta) ──

    def _channel_fts(self, query, top_k=TOP_K_PER_CHANNEL):
        tokens = re.findall(r"[a-zA-Zéèêëàâäôöùûüïîç]{3,}", query.lower())
        if not tokens:
            return {}

        # Deduplicate and filter very short tokens
        tokens = list(dict.fromkeys(t for t in tokens if len(t) >= 4))[:30]
        fts_query = " OR ".join(tokens)

        syndrome_best_rank = {}

        # Search case_reports_fts
        try:
            rows = self.conn.execute("""
                SELECT cr.syndrome_id, rank
                FROM case_reports_fts fts
                JOIN case_reports cr ON cr.id = fts.rowid
                WHERE case_reports_fts MATCH ?
                ORDER BY rank
                LIMIT ?
            """, (fts_query, top_k * 3)).fetchall()

            for row in rows:
                sid = row["syndrome_id"]
                rank_val = abs(row["rank"])
                if sid not in syndrome_best_rank or rank_val < syndrome_best_rank[sid]:
                    syndrome_best_rank[sid] = rank_val
        except Exception:
            pass

        # Search chunk_meta_fts (vignettes + GR + PubMed chunks)
        try:
            rows = self.conn.execute("""
                SELECT cm.rowid, rank
                FROM chunk_meta_fts fts
                JOIN chunk_meta cm ON cm.rowid = fts.rowid
                WHERE chunk_meta_fts MATCH ?
                ORDER BY rank
                LIMIT ?
            """, (fts_query, top_k * 3)).fetchall()

            for row in rows:
                sid = self.chunk_syndrome.get(row["rowid"])
                if not sid:
                    continue
                rank_val = abs(row["rank"])
                if sid not in syndrome_best_rank or rank_val < syndrome_best_rank[sid]:
                    syndrome_best_rank[sid] = rank_val
        except Exception:
            pass

        ranked = sorted(syndrome_best_rank.items(), key=lambda x: x[1])[:top_k]
        return {sid: i + 1 for i, (sid, _) in enumerate(ranked)}

    # ── Absence penalty (post-filter) ──

    def _hpo_is_covered(self, expected_hpo, vignette_hpos):
        if expected_hpo in vignette_hpos:
            return True
        expected_family = self.hpo_ancestors_map.get(expected_hpo, set())
        return bool(expected_family & vignette_hpos)

    def _absence_penalty(self, merged_ranked, vignette_hpo_ids, top_k, weight=0.5):
        vignette_set = set(vignette_hpo_ids)
        rescored = []
        for sid, rrf_score in merged_ranked[:top_k * 3]:
            vf_hpos = self.syndrome_vf.get(sid, [])
            if not vf_hpos:
                rescored.append((sid, rrf_score, 0, 0, 0))
                continue
            prenatal_vf = [(h, p) for h, p in vf_hpos if h not in self.postnatal_hpos]
            if not prenatal_vf:
                rescored.append((sid, rrf_score, 0, 0, 0))
                continue
            n_covered = sum(1 for h, _ in prenatal_vf if self._hpo_is_covered(h, vignette_set))
            n_total = len(prenatal_vf)
            absence_rate = 1.0 - (n_covered / n_total)
            penalty = weight * absence_rate
            rescored.append((sid, rrf_score - penalty * rrf_score, n_covered, n_total, penalty))
        rescored.sort(key=lambda x: -x[1])
        return rescored[:top_k]

    # ── RRF Fusion ──

    def _rrf_merge(self, *channel_ranks):
        scores = defaultdict(float)
        channel_presence = defaultdict(int)
        for channel in channel_ranks:
            for sid, rank in channel.items():
                scores[sid] += 1.0 / (self.rrf_k + rank)
                channel_presence[sid] += 1

        ranked = sorted(scores.items(), key=lambda x: -x[1])
        return ranked, channel_presence

    # ── Public API ──

    def query(self, clinical_text, top_k=TOP_K_FINAL, verbose=False,
              absence_penalty_weight=0.3):
        t0 = time.time()

        bio_emb = self.biolord.encode(clinical_text, normalize_embeddings=True)
        hpo_matches = self._extract_hpo(clinical_text)
        bio_ranks = self._channel_biolord(bio_emb)
        hpo_ranks = self._channel_hpo(clinical_text, hpo_matches=hpo_matches)
        aki_ranks = self._channel_akinator(clinical_text, hpo_matches=hpo_matches)
        fts_ranks = self._channel_fts(clinical_text)

        merged, ch_presence = self._rrf_merge(bio_ranks, hpo_ranks, aki_ranks, fts_ranks)

        vignette_hpo_ids = {m.hpo_id for m in hpo_matches} if hpo_matches else set()
        rescored = self._absence_penalty(merged, vignette_hpo_ids, top_k,
                                         weight=absence_penalty_weight)
        elapsed = time.time() - t0

        results = []
        for sid, adj_score, n_covered, n_total, penalty in rescored:
            name_row = self.conn.execute(
                "SELECT name_fr, name_en, category FROM syndromes WHERE id = ?", (sid,)
            ).fetchone()
            name = (name_row["name_fr"] or name_row["name_en"]) if name_row else sid
            cat = name_row["category"] if name_row else "?"

            results.append({
                "syndrome_id": sid,
                "name": name,
                "category": cat,
                "rrf_score": adj_score,
                "biolord_rank": bio_ranks.get(sid),
                "hpo_rank": hpo_ranks.get(sid),
                "akinator_rank": aki_ranks.get(sid),
                "fts_rank": fts_ranks.get(sid),
                "n_channels": ch_presence[sid],
                "vf_covered": n_covered,
                "vf_total": n_total,
                "absence_penalty": penalty,
            })

        if verbose:
            print(f"\n  BioLORD:   {len(bio_ranks)} syndromes")
            print(f"  HPO:       {len(hpo_ranks)} syndromes")
            print(f"  Akinator:  {len(aki_ranks)} syndromes")
            print(f"  FTS5:      {len(fts_ranks)} syndromes")
            print(f"  Merged:    {len(merged)} syndromes")
            print(f"  Time:      {elapsed*1000:.0f}ms")

        return results

    def query_batch(self, texts, top_k=TOP_K_FINAL, absence_penalty_weight=0.3):
        t0 = time.time()
        print(f"Batch encoding {len(texts)} queries with BioLORD...")
        bio_embs = self.biolord.encode(texts, batch_size=64, show_progress_bar=True,
                                       normalize_embeddings=True)
        t_enc = time.time() - t0
        print(f"  Encoding: {t_enc:.1f}s")

        t1 = time.time()
        all_bio_ranks = self._channel_biolord_batch(bio_embs, top_k=TOP_K_PER_CHANNEL)
        print(f"  BioLORD batch: {time.time()-t1:.1f}s")

        results = []
        for i, text in enumerate(texts):
            hpo_matches = self._extract_hpo(text)
            bio_ranks = all_bio_ranks[i]
            hpo_ranks = self._channel_hpo(text, hpo_matches=hpo_matches)
            aki_ranks = self._channel_akinator(text, hpo_matches=hpo_matches)
            fts_ranks = self._channel_fts(text)

            merged, ch_presence = self._rrf_merge(bio_ranks, hpo_ranks, aki_ranks, fts_ranks)

            vignette_hpo_ids = {m.hpo_id for m in hpo_matches} if hpo_matches else set()
            rescored = self._absence_penalty(merged, vignette_hpo_ids, top_k,
                                             weight=absence_penalty_weight)

            top_syndromes = []
            for sid, adj_score, n_covered, n_total, penalty in rescored:
                name_row = self.conn.execute(
                    "SELECT name_fr, name_en FROM syndromes WHERE id = ?", (sid,)
                ).fetchone()
                name = (name_row["name_fr"] or name_row["name_en"]) if name_row else sid
                top_syndromes.append({
                    "syndrome_id": sid,
                    "name": name,
                    "rrf_score": adj_score,
                    "n_channels": ch_presence[sid],
                    "vf_covered": n_covered,
                    "vf_total": n_total,
                    "absence_penalty": penalty,
                })
            results.append(top_syndromes)

            if (i + 1) % 100 == 0:
                print(f"  {i+1}/{len(texts)} ({(time.time()-t0)/(i+1)*1000:.0f}ms/query)")

        elapsed = time.time() - t0
        print(f"  Total: {elapsed:.1f}s ({elapsed/len(texts)*1000:.0f}ms/query)")
        return results

    def close(self):
        self.conn.close()


# ── Scoring ──

def _score_level(cos_direct, gold_cluster, cand_cluster):
    if cos_direct >= 0.90:
        return "EXACT"
    if gold_cluster is not None and gold_cluster >= 0 and cand_cluster >= 0 and gold_cluster == cand_cluster:
        return "FAMILLE"
    if cos_direct >= 0.50:
        return "CADRE"
    return "HORS"


LEVEL_RANK = {"EXACT": 3, "FAMILLE": 2, "CADRE": 1, "HORS": 0}


def eval_benchmark(cm, top_k=10):
    bench_conn = sqlite3.connect("/home/mathevet/Bureau/benchmark_foeto/foeto_bench.db")
    bench_conn.row_factory = sqlite3.Row

    cases = bench_conn.execute("""
        SELECT id, clinical_text, gold_diagnosis
        FROM cases
        WHERE is_truncated = 0 AND length(clinical_text) > 50
        ORDER BY id
    """).fetchall()
    bench_conn.close()

    if not cases:
        print("No benchmark cases found.")
        return

    print(f"\nEvaluating on {len(cases)} benchmark cases (top-{top_k}, RRF k={cm.rrf_k})...")

    texts = [c["clinical_text"] for c in cases]
    golds = [c["gold_diagnosis"] for c in cases]

    batch_results = cm.query_batch(texts, top_k=top_k)

    # Pre-build syndrome name→embedding matrix + cluster lookup
    syn_rows = cm.conn.execute(
        "SELECT s.id, s.name_fr, s.name_en, sc.cluster_id "
        "FROM syndromes s LEFT JOIN syndrome_clusters sc ON s.id = sc.syndrome_id"
    ).fetchall()

    syn_names = []
    syn_ids = []
    syn_clusters = {}
    for row in syn_rows:
        name = row["name_fr"] or row["name_en"] or row["id"]
        syn_names.append(name)
        syn_ids.append(row["id"])
        syn_clusters[row["id"]] = row["cluster_id"] if row["cluster_id"] is not None else -1

    all_names = set(golds)
    all_names.update(syn_names)
    for res_list in batch_results:
        for r in res_list:
            all_names.add(r["name"])
    all_names = list(all_names)

    print(f"\nEncoding {len(all_names)} unique names for scoring...")
    name_embs = cm.biolord.encode(all_names, batch_size=64, normalize_embeddings=True,
                                   show_progress_bar=True)
    emb_map = {name: emb for name, emb in zip(all_names, name_embs)}

    syn_emb_matrix = np.stack([emb_map[n] for n in syn_names])

    def find_gold_cluster(gold_emb):
        cosines = gold_emb @ syn_emb_matrix.T
        best_idx = np.argmax(cosines)
        if cosines[best_idx] >= 0.85:
            return syn_clusters.get(syn_ids[best_idx], -1)
        return None

    levels = {"EXACT": 0, "FAMILLE": 0, "CADRE": 0, "HORS": 0}
    levels_tk = {"EXACT": 0, "FAMILLE": 0, "CADRE": 0, "HORS": 0}
    details = []

    for i, case in enumerate(cases):
        gold = golds[i]
        gold_emb = emb_map.get(gold)
        candidates = batch_results[i]

        if not candidates or gold_emb is None:
            levels["HORS"] += 1
            levels_tk["HORS"] += 1
            details.append({"case": case["id"], "gold": gold[:40], "level": "HORS",
                           "best": "HORS", "top1": "?", "n_ch": 0})
            continue

        gold_cluster = find_gold_cluster(gold_emb)

        best_level = "HORS"
        t1_level = "HORS"
        for j, cand in enumerate(candidates):
            c_emb = emb_map.get(cand["name"])
            if c_emb is None:
                continue
            cos = float(gold_emb @ c_emb)
            c_cluster = syn_clusters.get(cand["syndrome_id"], -1)
            lvl = _score_level(cos, gold_cluster, c_cluster)

            if j == 0:
                t1_level = lvl
                levels[lvl] += 1

            if LEVEL_RANK[lvl] > LEVEL_RANK[best_level]:
                best_level = lvl

        levels_tk[best_level] += 1
        details.append({
            "case": case["id"], "gold": gold[:40],
            "level": t1_level, "best": best_level,
            "top1": candidates[0]["name"][:40] if candidates else "?",
            "n_ch": candidates[0]["n_channels"] if candidates else 0,
        })

    n = len(cases)
    print(f"\n{'='*80}")
    print(f"CONVERGENCE MATRIX v2 — {n} cases, top-{top_k}, RRF k={cm.rrf_k}")
    print(f"Canaux: BioLORD + HPO + Akinator + FTS5")
    print(f"{'='*80}")

    print(f"\n  Top-1:")
    for lbl in ["EXACT", "FAMILLE", "CADRE", "HORS"]:
        print(f"    {lbl:<10s}: {levels[lbl]:>4d}/{n} ({levels[lbl]/n*100:.1f}%)")
    useful = levels["EXACT"] + levels["FAMILLE"]
    print(f"    Utile     : {useful:>4d}/{n} ({useful/n*100:.1f}%)")

    print(f"\n  Best-of-{top_k}:")
    for lbl in ["EXACT", "FAMILLE", "CADRE", "HORS"]:
        print(f"    {lbl:<10s}: {levels_tk[lbl]:>4d}/{n} ({levels_tk[lbl]/n*100:.1f}%)")
    useful_tk = levels_tk["EXACT"] + levels_tk["FAMILLE"]
    print(f"    Utile     : {useful_tk:>4d}/{n} ({useful_tk/n*100:.1f}%)")

    # Channel contribution analysis
    ch_counts = defaultdict(int)
    for d in details:
        if d["level"] in ("EXACT", "FAMILLE"):
            ch_counts["t1_useful"] += 1
        if d["best"] in ("EXACT", "FAMILLE"):
            ch_counts["tk_useful"] += 1

    print(f"\n{'Case':<22s} {'T1':>5s} {'B-K':>5s} {'Ch':>3s} | {'Gold':<40s} | {'Top-1':<40s}")
    print("-" * 130)
    for d in details[:30]:
        print(f"  {d['case']:<20s} {d['level']:>5s} {d['best']:>5s} {d['n_ch']:>3d} | "
              f"{d['gold']:<40s} | {d['top1']:<40s}")
    if len(details) > 30:
        print(f"  ... ({len(details) - 30} more)")

    return {"levels": levels, "levels_top_k": levels_tk, "n": n,
            "useful_t1": useful, "useful_tk": useful_tk}


def sweep_rrf_k(top_k=10):
    """Test different RRF k values."""
    results = []
    for k in [10, 15, 20, 25, 30, 40, 50, 60, 80]:
        print(f"\n{'#'*60}")
        print(f"# RRF k = {k}")
        print(f"{'#'*60}")
        cm = ConvergenceMatrix(rrf_k=k)
        r = eval_benchmark(cm, top_k=top_k)
        if r:
            results.append({"k": k, **r})
        cm.close()

    print(f"\n{'='*80}")
    print(f"RRF k SWEEP RESULTS — top-{top_k}")
    print(f"{'='*80}")
    print(f"{'k':>4s} | {'T1 utile':>9s} | {'T-K utile':>10s} | {'T1 exact':>9s} | {'T-K exact':>10s}")
    print("-" * 55)
    for r in results:
        n = r["n"]
        print(f"  {r['k']:>2d} | {r['useful_t1']:>4d} ({r['useful_t1']/n*100:>4.1f}%) | "
              f"{r['useful_tk']:>4d} ({r['useful_tk']/n*100:>5.1f}%) | "
              f"{r['levels']['EXACT']:>4d} ({r['levels']['EXACT']/n*100:>4.1f}%) | "
              f"{r['levels_top_k']['EXACT']:>4d} ({r['levels_top_k']['EXACT']/n*100:>5.1f}%)")

    best = max(results, key=lambda r: r["useful_tk"])
    print(f"\n  Best k for top-{top_k} utile: k={best['k']} ({best['useful_tk']}/{best['n']})")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("query", nargs="?", help="Clinical text to query")
    parser.add_argument("--bench", action="store_true")
    parser.add_argument("--sweep", action="store_true", help="Sweep RRF k values")
    parser.add_argument("--top", type=int, default=10)
    parser.add_argument("--rrf-k", type=int, default=RRF_K)
    parser.add_argument("--verbose", "-v", action="store_true")
    args = parser.parse_args()

    if args.sweep:
        sweep_rrf_k(top_k=args.top)
        return

    cm = ConvergenceMatrix(rrf_k=args.rrf_k)
    print(f"Chunk→syndrome mapping: {cm._n_mapped}/{cm._n_total}")

    if args.bench:
        eval_benchmark(cm, top_k=args.top)
    elif args.query:
        results = cm.query(args.query, top_k=args.top, verbose=True)
        print(f"\n{'Rang':>4s} {'Ch':>3s} {'RRF':>7s} {'VF':>7s} {'Pen':>5s} {'BioL':>5s} {'HPO':>5s} {'Aki':>5s} {'FTS':>5s} | {'Syndrome'}")
        print("-" * 120)
        for i, r in enumerate(results, 1):
            bio = str(r["biolord_rank"]) if r["biolord_rank"] else "-"
            hpo = str(r["hpo_rank"]) if r["hpo_rank"] else "-"
            aki = str(r["akinator_rank"]) if r["akinator_rank"] else "-"
            fts = str(r["fts_rank"]) if r["fts_rank"] else "-"
            vf = f"{r['vf_covered']}/{r['vf_total']}" if r.get("vf_total") else "-"
            pen = f"{r['absence_penalty']:.0%}" if r.get("absence_penalty") else "-"
            print(f"  {i:>2d}  {r['n_channels']:>4d} {r['rrf_score']:.5f} {vf:>7s} {pen:>5s} {bio:>5s} {hpo:>5s} {aki:>5s} {fts:>5s} | "
                  f"{r['name'][:55]} [{r['category']}]")
    else:
        parser.print_help()

    cm.close()


if __name__ == "__main__":
    main()
