#!/usr/bin/env python3
"""Étape 1 — Clustering des syndromes par centroïdes BioLORD.

Pour chaque syndrome de la DB :
1. Si des chunks existent dans vec_chunks → centroïde BioLORD (moyenne pondérée)
2. Sinon → encode (name_fr + HPO labels + discriminateurs) avec BioLORD
3. Clustering HDBSCAN sur les centroïdes
4. Visualisation UMAP colorée par cluster
5. Export : table syndrome_clusters dans la DB

Usage:
    python cluster_syndromes.py                    # cluster + UMAP
    python cluster_syndromes.py --min-cluster 10   # taille min de cluster
    python cluster_syndromes.py --export           # exporter dans la DB
"""
import argparse
import json
import os
import sqlite3
import struct
import sys
import time
from collections import defaultdict
from pathlib import Path

import hdbscan
import numpy as np
import umap
from sentence_transformers import SentenceTransformer

DB_PATH = str(Path(__file__).resolve().parent / "syndromes_foetaux.db")
BIOLORD_MODEL = "FremyCompany/BioLORD-2023"
EMBED_DIM = 768


def load_chunk_centroids(conn):
    """Compute BioLORD centroids from vec_chunks for each source_id (syndrome).

    Returns dict: source_id → np.array(768,)
    GeneReviews chunks weighted 2x vs PubMed 1x.
    """
    print("Loading chunk embeddings from vec_chunks...")
    t0 = time.time()

    meta = conn.execute(
        "SELECT rowid, source_type, source_id FROM chunk_meta"
    ).fetchall()

    # Group by source_id
    source_chunks = defaultdict(list)
    source_weights = defaultdict(list)
    rowid_to_source = {}
    for rowid, stype, sid in meta:
        rowid_to_source[rowid] = (sid, stype)

    # Read all embeddings in one pass
    all_rows = conn.execute("SELECT rowid, embedding FROM vec_chunks").fetchall()
    print(f"  Read {len(all_rows)} embeddings in {time.time()-t0:.1f}s")

    for rowid, emb_blob in all_rows:
        if rowid not in rowid_to_source:
            continue
        sid, stype = rowid_to_source[rowid]
        vec = np.frombuffer(emb_blob, dtype=np.float32)
        if len(vec) != EMBED_DIM:
            continue
        weight = 2.0 if stype == "genereviews" else 1.0
        source_chunks[sid].append(vec)
        source_weights[sid].append(weight)

    # Compute weighted centroids
    centroids = {}
    for sid, vecs in source_chunks.items():
        weights = np.array(source_weights[sid])
        stacked = np.stack(vecs)
        centroid = np.average(stacked, axis=0, weights=weights)
        centroid = centroid / (np.linalg.norm(centroid) + 1e-10)
        centroids[sid] = centroid

    print(f"  Computed {len(centroids)} chunk-based centroids")
    return centroids


def build_syndrome_text(row):
    """Build rich text representation of a syndrome for embedding."""
    parts = []
    if row["name_fr"]:
        parts.append(row["name_fr"])
    if row["name_en"]:
        parts.append(row["name_en"])
    if row["prenatal_signs_summary"]:
        parts.append(row["prenatal_signs_summary"][:500])
    if row["key_discriminators"]:
        parts.append(row["key_discriminators"][:500])
    return ". ".join(parts)


def encode_missing_syndromes(conn, model, chunk_centroids, syndromes):
    """Encode syndromes that don't have chunk centroids."""
    missing = []
    missing_ids = []
    for s in syndromes:
        sid = s["id"]
        if sid not in chunk_centroids:
            text = build_syndrome_text(s)
            if text:
                missing.append(text)
                missing_ids.append(sid)

    if not missing:
        return {}

    print(f"Encoding {len(missing)} syndromes without chunks via BioLORD...")
    embeddings = model.encode(missing, batch_size=64, show_progress_bar=True,
                              normalize_embeddings=True)

    result = {}
    for sid, emb in zip(missing_ids, embeddings):
        result[sid] = emb
    return result


def match_syndromes_to_chunks(conn, syndromes, chunk_centroids):
    """Try to match syndromes to chunk source_ids by name similarity."""
    # Build lookup from chunk source_ids
    chunk_titles = {}
    rows = conn.execute(
        "SELECT DISTINCT source_id, title FROM chunk_meta"
    ).fetchall()
    for sid, title in rows:
        chunk_titles[sid] = (title or "").lower()

    matched = {}
    for s in syndromes:
        oid = s["id"]
        if oid in chunk_centroids:
            matched[oid] = chunk_centroids[oid]
            continue

        name_fr = (s["name_fr"] or "").lower()
        name_en = (s["name_en"] or "").lower()

        for csid, ctitle in chunk_titles.items():
            if csid in chunk_centroids:
                if (name_en and len(name_en) > 5 and name_en in ctitle) or \
                   (name_fr and len(name_fr) > 5 and name_fr in ctitle):
                    matched[oid] = chunk_centroids[csid]
                    break

    return matched


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--min-cluster", type=int, default=8)
    parser.add_argument("--min-samples", type=int, default=5)
    parser.add_argument("--export", action="store_true")
    parser.add_argument("--db", default=DB_PATH)
    args = parser.parse_args()

    import sqlite_vec
    conn = sqlite3.connect(args.db)
    conn.enable_load_extension(True)
    sqlite_vec.load(conn)
    conn.row_factory = sqlite3.Row

    # 1. Load syndromes
    syndromes = conn.execute(
        "SELECT id, name_fr, name_en, category, orpha_code, "
        "prenatal_signs_summary, key_discriminators, aliases "
        "FROM syndromes"
    ).fetchall()
    print(f"Loaded {len(syndromes)} syndromes from DB")

    # 2. Compute chunk centroids
    chunk_centroids = load_chunk_centroids(conn)

    # 3. Match syndromes to chunk centroids
    matched = match_syndromes_to_chunks(conn, syndromes, chunk_centroids)
    print(f"Matched {len(matched)}/{len(syndromes)} syndromes to chunk centroids")

    # 4. Encode remaining syndromes with BioLORD
    print("Loading BioLORD-2023...")
    model = SentenceTransformer(BIOLORD_MODEL)
    fallback = encode_missing_syndromes(conn, model, matched, syndromes)
    print(f"Encoded {len(fallback)} additional syndromes via BioLORD")

    # 5. Merge all embeddings
    all_embeddings = {}
    all_embeddings.update(matched)
    all_embeddings.update(fallback)

    # Filter syndromes with embeddings
    valid_syndromes = [s for s in syndromes if s["id"] in all_embeddings]
    print(f"\n{len(valid_syndromes)} syndromes with embeddings (out of {len(syndromes)})")

    syndrome_ids = [s["id"] for s in valid_syndromes]
    syndrome_names = [s["name_fr"] or s["name_en"] or s["id"] for s in valid_syndromes]
    syndrome_cats = [s["category"] or "autre" for s in valid_syndromes]
    X = np.stack([all_embeddings[sid] for sid in syndrome_ids])

    # 6. UMAP dimensionality reduction then HDBSCAN
    print(f"\nUMAP reduction 768D → 30D for clustering...")
    t0 = time.time()
    reducer_cluster = umap.UMAP(
        n_components=30, n_neighbors=15, min_dist=0.0,
        metric="cosine", random_state=42
    )
    X_reduced = reducer_cluster.fit_transform(X)
    print(f"  UMAP reduction took {time.time()-t0:.1f}s")

    print(f"Running HDBSCAN (min_cluster={args.min_cluster}, min_samples={args.min_samples})...")
    t0 = time.time()
    clusterer = hdbscan.HDBSCAN(
        min_cluster_size=args.min_cluster,
        min_samples=args.min_samples,
        metric="euclidean",
        cluster_selection_method="eom",
    )
    labels = clusterer.fit_predict(X_reduced)
    n_clusters = len(set(labels)) - (1 if -1 in labels else 0)
    n_noise = (labels == -1).sum()
    print(f"  {n_clusters} clusters found, {n_noise} noise points ({n_noise/len(labels)*100:.1f}%)")
    print(f"  Clustering took {time.time()-t0:.1f}s")

    # 7. Analyze clusters
    cluster_info = defaultdict(lambda: {"names": [], "categories": defaultdict(int), "size": 0})
    for i, label in enumerate(labels):
        if label == -1:
            continue
        ci = cluster_info[label]
        ci["size"] += 1
        ci["names"].append(syndrome_names[i])
        ci["categories"][syndrome_cats[i]] += 1

    print(f"\n{'='*100}")
    print(f"{'Cluster':>8s} {'Size':>5s} | {'Dominant Category':<25s} | {'Sample Syndromes'}")
    print("-" * 100)
    for cid in sorted(cluster_info.keys(), key=lambda c: -cluster_info[c]["size"]):
        ci = cluster_info[cid]
        dom_cat = max(ci["categories"], key=ci["categories"].get)
        dom_pct = ci["categories"][dom_cat] / ci["size"] * 100
        samples = ci["names"][:5]
        sample_str = " | ".join(s[:35] for s in samples)
        print(f"  {cid:>6d} {ci['size']:>5d} | {dom_cat:<20s} ({dom_pct:>3.0f}%) | {sample_str}")

    # 8. UMAP visualization
    print("\nComputing UMAP projection...")
    reducer = umap.UMAP(n_neighbors=15, min_dist=0.1, metric="cosine", random_state=42)
    embedding_2d = reducer.fit_transform(X)

    # Save UMAP + labels for plotting
    umap_data = {
        "syndrome_ids": syndrome_ids,
        "syndrome_names": syndrome_names,
        "categories": syndrome_cats,
        "cluster_labels": labels.tolist(),
        "umap_x": embedding_2d[:, 0].tolist(),
        "umap_y": embedding_2d[:, 1].tolist(),
        "n_clusters": n_clusters,
    }

    out_path = Path(__file__).resolve().parent / "cluster_umap_data.json"
    with open(out_path, "w") as f:
        json.dump(umap_data, f)
    print(f"UMAP data saved to {out_path}")

    # Generate HTML visualization
    html_path = Path(__file__).resolve().parent / "cluster_umap.html"
    _generate_html(umap_data, html_path)
    print(f"UMAP visualization saved to {html_path}")

    # 9. Export to DB
    if args.export:
        print("\nExporting clusters to DB...")
        conn.execute("DROP TABLE IF EXISTS syndrome_clusters")
        conn.execute("""
            CREATE TABLE syndrome_clusters (
                syndrome_id TEXT PRIMARY KEY,
                cluster_id INTEGER,
                cluster_label TEXT,
                embedding_source TEXT,
                umap_x REAL,
                umap_y REAL
            )
        """)
        for i, sid in enumerate(syndrome_ids):
            source = "chunk_centroid" if sid in matched else "biolord_encode"
            conn.execute(
                "INSERT INTO syndrome_clusters VALUES (?, ?, ?, ?, ?, ?)",
                (sid, int(labels[i]), None, source, float(embedding_2d[i, 0]), float(embedding_2d[i, 1]))
            )
        conn.commit()
        print(f"  Exported {len(syndrome_ids)} records to syndrome_clusters")

    conn.close()
    print("\nDone.")


def _generate_html(data, path):
    """Generate interactive UMAP scatter plot."""
    import colorsys

    n_clusters = data["n_clusters"]
    colors = {}
    for i in range(n_clusters):
        h = i / max(n_clusters, 1)
        r, g, b = colorsys.hsv_to_rgb(h, 0.7, 0.9)
        colors[i] = f"rgb({int(r*255)},{int(g*255)},{int(b*255)})"
    colors[-1] = "rgb(180,180,180)"

    points_js = []
    for i in range(len(data["syndrome_ids"])):
        cl = data["cluster_labels"][i]
        color = colors.get(cl, "rgb(180,180,180)")
        name = data["syndrome_names"][i].replace("'", "\\'").replace('"', '\\"')[:60]
        cat = data["categories"][i]
        points_js.append(
            f'{{x:{data["umap_x"][i]:.4f},y:{data["umap_y"][i]:.4f},'
            f'c:"{color}",n:"{name}",cat:"{cat}",cl:{cl}}}'
        )

    html = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>Syndrome Clusters — BioLORD UMAP</title>
<style>
body {{ font-family: system-ui; margin: 20px; background: #1a1a2e; color: #eee; }}
h1 {{ color: #e94560; }}
canvas {{ border: 1px solid #333; cursor: crosshair; }}
#tooltip {{ position: absolute; background: rgba(0,0,0,0.85); color: #fff; padding: 8px 12px;
  border-radius: 6px; font-size: 13px; pointer-events: none; display: none; max-width: 400px; }}
#stats {{ margin: 10px 0; font-size: 14px; color: #aaa; }}
#legend {{ margin: 10px 0; display: flex; flex-wrap: wrap; gap: 8px; }}
.leg {{ padding: 3px 8px; border-radius: 4px; font-size: 12px; cursor: pointer; }}
</style>
</head><body>
<h1>Clustering BioLORD — {n_clusters} clusters, {len(data["syndrome_ids"])} syndromes</h1>
<div id="stats"></div>
<div id="legend"></div>
<canvas id="c" width="1200" height="800"></canvas>
<div id="tooltip"></div>
<script>
const pts = [{','.join(points_js)}];
const canvas = document.getElementById('c');
const ctx = canvas.getContext('2d');
const tooltip = document.getElementById('tooltip');

// Compute bounds
let minX=Infinity,maxX=-Infinity,minY=Infinity,maxY=-Infinity;
pts.forEach(p => {{ minX=Math.min(minX,p.x); maxX=Math.max(maxX,p.x); minY=Math.min(minY,p.y); maxY=Math.max(maxY,p.y); }});
const pad = 40;
const sx = (canvas.width - 2*pad) / (maxX - minX);
const sy = (canvas.height - 2*pad) / (maxY - minY);

function draw() {{
  ctx.fillStyle = '#1a1a2e';
  ctx.fillRect(0, 0, canvas.width, canvas.height);
  pts.forEach(p => {{
    const x = pad + (p.x - minX) * sx;
    const y = pad + (p.y - minY) * sy;
    ctx.beginPath();
    ctx.arc(x, y, 3, 0, Math.PI * 2);
    ctx.fillStyle = p.c;
    ctx.fill();
  }});
}}
draw();

canvas.addEventListener('mousemove', e => {{
  const rect = canvas.getBoundingClientRect();
  const mx = e.clientX - rect.left;
  const my = e.clientY - rect.top;
  let closest = null, minD = 100;
  pts.forEach(p => {{
    const x = pad + (p.x - minX) * sx;
    const y = pad + (p.y - minY) * sy;
    const d = Math.sqrt((mx-x)**2 + (my-y)**2);
    if (d < minD) {{ minD = d; closest = p; }}
  }});
  if (closest && minD < 15) {{
    tooltip.style.display = 'block';
    tooltip.style.left = (e.clientX + 15) + 'px';
    tooltip.style.top = (e.clientY + 15) + 'px';
    tooltip.innerHTML = '<b>' + closest.n + '</b><br>Catégorie: ' + closest.cat + '<br>Cluster: ' + closest.cl;
  }} else {{
    tooltip.style.display = 'none';
  }}
}});

// Stats
const clCounts = {{}};
pts.forEach(p => {{ clCounts[p.cl] = (clCounts[p.cl]||0) + 1; }});
document.getElementById('stats').innerText =
  `${{pts.length}} syndromes, ${{Object.keys(clCounts).filter(k=>k!='-1').length}} clusters, ${{clCounts[-1]||0}} noise`;
</script>
</body></html>"""

    with open(path, "w") as f:
        f.write(html)


if __name__ == "__main__":
    main()
