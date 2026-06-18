#!/usr/bin/env python3
"""LDA supervisée sur les catégories nosographiques vs HDBSCAN aveugle.

Compare deux vues des 3215 syndromes :
1. LDA : projection supervisée sur les catégories existantes (12 classes)
2. HDBSCAN : clustering aveugle (105 clusters du run précédent)

Métriques de concordance : Adjusted Rand Index, NMI, matrice de confusion.
Visualisation : UMAP coloré par catégorie vs par cluster HDBSCAN.

Usage:
    python lda_vs_hdbscan.py              # analyse complète
    python lda_vs_hdbscan.py --export     # exporter LDA dans la DB
"""
import argparse
import json
import sqlite3
import time
from collections import defaultdict
from pathlib import Path

import numpy as np
from sklearn.discriminant_analysis import LinearDiscriminantAnalysis
from sklearn.metrics import (
    adjusted_rand_score,
    normalized_mutual_info_score,
    classification_report,
    confusion_matrix,
)
from sklearn.model_selection import cross_val_score
import umap

DB_PATH = str(Path(__file__).resolve().parent / "syndromes_foetaux.db")
EMBED_DIM = 768


def load_embeddings_and_labels(conn):
    """Load syndrome embeddings from syndrome_clusters + category labels."""
    rows = conn.execute("""
        SELECT s.id, s.name_fr, s.name_en, s.category,
               sc.cluster_id, sc.embedding_source, sc.umap_x, sc.umap_y
        FROM syndromes s
        JOIN syndrome_clusters sc ON s.id = sc.syndrome_id
        ORDER BY s.id
    """).fetchall()

    chunk_centroids = load_chunk_centroids(conn)
    model = None

    syndrome_ids = []
    names = []
    categories = []
    hdbscan_labels = []
    embeddings = []
    embed_sources = []

    missing_ids = []
    missing_texts = []

    for row in rows:
        sid = row[0]
        name_fr = row[1] or ""
        name_en = row[2] or ""
        cat = row[3] or "autre"
        cluster_id = row[4]
        source = row[5]

        if sid in chunk_centroids:
            embeddings.append(chunk_centroids[sid])
            syndrome_ids.append(sid)
            names.append(name_fr or name_en or sid)
            categories.append(cat)
            hdbscan_labels.append(cluster_id)
            embed_sources.append(source)
        else:
            text = ". ".join(filter(None, [name_fr, name_en]))
            if text:
                missing_ids.append(sid)
                missing_texts.append(text)
                names.append(name_fr or name_en or sid)
                categories.append(cat)
                hdbscan_labels.append(cluster_id)
                embed_sources.append(source)

    if missing_texts:
        print(f"Encoding {len(missing_texts)} syndromes without chunk centroids...")
        from sentence_transformers import SentenceTransformer
        model = SentenceTransformer("FremyCompany/BioLORD-2023")

        syn_rows = conn.execute(
            "SELECT id, name_fr, name_en, prenatal_signs_summary, key_discriminators "
            "FROM syndromes WHERE id IN ({})".format(",".join("?" * len(missing_ids))),
            missing_ids
        ).fetchall()
        syn_map = {r[0]: r for r in syn_rows}

        texts = []
        for sid in missing_ids:
            r = syn_map.get(sid)
            if r:
                parts = list(filter(None, [r[1], r[2], (r[3] or "")[:500], (r[4] or "")[:500]]))
                texts.append(". ".join(parts))
            else:
                texts.append(sid)

        embs = model.encode(texts, batch_size=64, show_progress_bar=True, normalize_embeddings=True)
        for i, sid in enumerate(missing_ids):
            syndrome_ids.append(sid)
            embeddings.append(embs[i])

    X = np.stack(embeddings)
    return syndrome_ids, names, categories, hdbscan_labels, X, embed_sources


def load_chunk_centroids(conn):
    """Same as cluster_syndromes.py — weighted centroid from vec_chunks."""
    print("Loading chunk centroids...")
    t0 = time.time()

    meta = conn.execute("SELECT rowid, source_type, source_id FROM chunk_meta").fetchall()
    rowid_to_source = {r[0]: (r[2], r[1]) for r in meta}

    all_rows = conn.execute("SELECT rowid, embedding FROM vec_chunks").fetchall()
    print(f"  Read {len(all_rows)} embeddings in {time.time()-t0:.1f}s")

    source_chunks = defaultdict(list)
    source_weights = defaultdict(list)

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

    centroids = {}
    for sid, vecs in source_chunks.items():
        weights = np.array(source_weights[sid])
        stacked = np.stack(vecs)
        centroid = np.average(stacked, axis=0, weights=weights)
        centroid = centroid / (np.linalg.norm(centroid) + 1e-10)
        centroids[sid] = centroid

    print(f"  {len(centroids)} chunk centroids loaded")
    return centroids


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--export", action="store_true")
    parser.add_argument("--db", default=DB_PATH)
    args = parser.parse_args()

    import sqlite_vec
    conn = sqlite3.connect(args.db)
    conn.enable_load_extension(True)
    sqlite_vec.load(conn)

    print("=" * 80)
    print("LDA supervisée vs HDBSCAN aveugle — analyse de concordance")
    print("=" * 80)

    # 1. Load data
    syndrome_ids, names, categories, hdbscan_labels, X, sources = load_embeddings_and_labels(conn)
    n = len(syndrome_ids)
    print(f"\n{n} syndromes chargés, {X.shape[1]}D embeddings")

    unique_cats = sorted(set(categories))
    print(f"{len(unique_cats)} catégories : {', '.join(f'{c} ({categories.count(c)})' for c in unique_cats)}")

    # 2. Merge small categories
    cat_counts = defaultdict(int)
    for c in categories:
        cat_counts[c] += 1

    MIN_CAT = 10
    cat_map = {}
    for c, n_c in cat_counts.items():
        if n_c < MIN_CAT:
            cat_map[c] = "autre"
        else:
            cat_map[c] = c

    categories_merged = [cat_map[c] for c in categories]
    unique_merged = sorted(set(categories_merged))
    print(f"\nAprès fusion (<{MIN_CAT}) : {len(unique_merged)} catégories")
    for c in unique_merged:
        print(f"  {c:<30s} {categories_merged.count(c):>5d}")

    # 3. UMAP reduction for LDA (768D too high for LDA with small classes)
    print(f"\nUMAP 768D → 50D pour LDA...")
    t0 = time.time()
    reducer_lda = umap.UMAP(
        n_components=50, n_neighbors=15, min_dist=0.0,
        metric="cosine", random_state=42
    )
    X_50d = reducer_lda.fit_transform(X)
    print(f"  UMAP took {time.time()-t0:.1f}s")

    # 4. LDA
    y = np.array([unique_merged.index(c) for c in categories_merged])
    n_classes = len(unique_merged)
    n_components_lda = min(n_classes - 1, 50)

    print(f"\nLDA : {n_classes} classes → {n_components_lda} axes discriminants")
    t0 = time.time()
    lda = LinearDiscriminantAnalysis(n_components=n_components_lda)
    X_lda = lda.fit_transform(X_50d, y)
    print(f"  LDA took {time.time()-t0:.1f}s")

    # Cross-validation accuracy
    print("\nValidation croisée LDA (5-fold)...")
    cv_scores = cross_val_score(
        LinearDiscriminantAnalysis(), X_50d, y, cv=5, scoring="accuracy"
    )
    print(f"  Accuracy: {cv_scores.mean():.3f} ± {cv_scores.std():.3f}")

    # LDA predictions
    y_pred_lda = lda.predict(X_50d)

    print(f"\nClassification report (LDA sur catégories) :")
    print(classification_report(y, y_pred_lda, target_names=unique_merged, zero_division=0))

    # 5. Concordance LDA catégories vs HDBSCAN clusters
    hdb = np.array(hdbscan_labels)
    non_noise = hdb != -1
    print(f"\nConcordance HDBSCAN vs catégories ({non_noise.sum()} non-bruit sur {n}) :")

    cats_non_noise = np.array(y)[non_noise]
    hdb_non_noise = hdb[non_noise]

    ari = adjusted_rand_score(cats_non_noise, hdb_non_noise)
    nmi = normalized_mutual_info_score(cats_non_noise, hdb_non_noise)
    print(f"  Adjusted Rand Index : {ari:.4f}")
    print(f"  Normalized Mutual Information : {nmi:.4f}")

    # 6. Analyse par cluster : pureté catégorielle
    print(f"\n{'Cluster':>8s} {'Size':>5s} | {'Dominant Category':<25s} {'Purity':>7s} | {'Categories'}")
    print("-" * 100)

    cluster_ids_unique = sorted(set(hdb[hdb != -1]))
    purities = []
    cluster_analysis = []

    for cid in cluster_ids_unique:
        mask = hdb == cid
        cl_cats = np.array(categories_merged)[mask]
        cl_names_list = np.array(names)[mask]
        size = len(cl_cats)

        cat_dist = defaultdict(int)
        for c in cl_cats:
            cat_dist[c] += 1

        dom_cat = max(cat_dist, key=cat_dist.get)
        purity = cat_dist[dom_cat] / size
        purities.append(purity)

        cats_str = ", ".join(f"{c}:{n}" for c, n in sorted(cat_dist.items(), key=lambda x: -x[1])[:4])
        if size >= 15:
            print(f"  {cid:>6d} {size:>5d} | {dom_cat:<25s} {purity:>6.1%} | {cats_str}")

        cluster_analysis.append({
            "cluster_id": int(cid), "size": int(size), "dominant_category": dom_cat,
            "purity": float(purity),
            "cat_distribution": {k: int(v) for k, v in cat_dist.items()},
            "sample_names": [str(s) for s in cl_names_list[:5]],
        })

    mean_purity = np.mean(purities)
    weighted_purity = sum(p * cluster_analysis[i]["size"] for i, p in enumerate(purities)) / non_noise.sum()
    print(f"\nPureté moyenne : {mean_purity:.3f}")
    print(f"Pureté pondérée (par taille) : {weighted_purity:.3f}")

    # 7. Clusters purs (>80%) vs mixtes
    pure = [ca for ca in cluster_analysis if ca["purity"] >= 0.80]
    mixed = [ca for ca in cluster_analysis if ca["purity"] < 0.50]
    print(f"\nClusters purs (≥80%) : {len(pure)}/{len(cluster_analysis)}")
    print(f"Clusters mixtes (<50%) : {len(mixed)}/{len(cluster_analysis)}")

    # 8. LDA explained variance ratio
    print(f"\nLDA — variance expliquée par axe discriminant :")
    ev = lda.explained_variance_ratio_
    cumsum = np.cumsum(ev)
    for i in range(min(10, len(ev))):
        bar = "█" * int(ev[i] * 50)
        print(f"  LD{i+1:>2d}: {ev[i]:>6.3f} (cum: {cumsum[i]:>6.3f}) {bar}")

    # 9. UMAP 2D visualization (both views)
    print("\nUMAP 2D projection...")
    reducer_2d = umap.UMAP(n_neighbors=15, min_dist=0.1, metric="cosine", random_state=42)
    X_2d = reducer_2d.fit_transform(X)

    # Also project LDA space to 2D
    reducer_lda_2d = umap.UMAP(n_neighbors=15, min_dist=0.1, metric="euclidean", random_state=42)
    X_lda_2d = reducer_lda_2d.fit_transform(X_lda)

    # Save visualization data
    viz_data = {
        "syndrome_ids": syndrome_ids,
        "names": names,
        "categories": categories_merged,
        "hdbscan_labels": [int(h) for h in hdbscan_labels],
        "lda_predictions": [unique_merged[int(p)] for p in y_pred_lda],
        "umap_x": X_2d[:, 0].tolist(),
        "umap_y": X_2d[:, 1].tolist(),
        "lda_umap_x": X_lda_2d[:, 0].tolist(),
        "lda_umap_y": X_lda_2d[:, 1].tolist(),
        "unique_categories": unique_merged,
        "n_clusters_hdbscan": len(cluster_ids_unique),
        "ari": float(ari),
        "nmi": float(nmi),
        "mean_purity": float(mean_purity),
        "weighted_purity": float(weighted_purity),
        "lda_cv_accuracy": float(cv_scores.mean()),
        "cluster_analysis": cluster_analysis,
    }

    out_json = Path(__file__).resolve().parent / "lda_vs_hdbscan_data.json"
    with open(out_json, "w") as f:
        json.dump(viz_data, f, ensure_ascii=False)
    print(f"Data saved to {out_json}")

    # Generate HTML
    html_path = Path(__file__).resolve().parent / "lda_vs_hdbscan.html"
    _generate_dual_html(viz_data, html_path)
    print(f"Visualization saved to {html_path}")

    # 10. Export LDA predictions to DB
    if args.export:
        print("\nExporting LDA predictions to DB...")
        try:
            conn.execute("ALTER TABLE syndrome_clusters ADD COLUMN lda_category TEXT")
        except sqlite3.OperationalError:
            pass
        try:
            conn.execute("ALTER TABLE syndrome_clusters ADD COLUMN lda_confidence REAL")
        except sqlite3.OperationalError:
            pass

        proba = lda.predict_proba(X_50d)
        for i, sid in enumerate(syndrome_ids):
            pred_cat = unique_merged[int(y_pred_lda[i])]
            conf = float(proba[i].max())
            conn.execute(
                "UPDATE syndrome_clusters SET lda_category = ?, lda_confidence = ? WHERE syndrome_id = ?",
                (pred_cat, round(conf, 4), sid)
            )
        conn.commit()
        print(f"  Updated {len(syndrome_ids)} records with LDA predictions")

    conn.close()
    print("\nDone.")


def _generate_dual_html(data, path):
    """Generate side-by-side UMAP: categories vs HDBSCAN clusters."""
    import colorsys

    cats = data["unique_categories"]
    cat_colors = {}
    for i, c in enumerate(cats):
        h = i / max(len(cats), 1)
        r, g, b = colorsys.hsv_to_rgb(h, 0.75, 0.9)
        cat_colors[c] = f"rgb({int(r*255)},{int(g*255)},{int(b*255)})"

    n_cl = data["n_clusters_hdbscan"]
    cl_colors = {}
    for i in range(n_cl):
        h = i / max(n_cl, 1)
        r, g, b = colorsys.hsv_to_rgb(h, 0.7, 0.85)
        cl_colors[i] = f"rgb({int(r*255)},{int(g*255)},{int(b*255)})"
    cl_colors[-1] = "rgb(100,100,100)"

    points_cat = []
    points_hdb = []
    points_lda = []

    for i in range(len(data["syndrome_ids"])):
        name = data["names"][i].replace("'", "\\'").replace('"', '\\"')[:60]
        cat = data["categories"][i]
        hdb = data["hdbscan_labels"][i]
        lda_pred = data["lda_predictions"][i]

        cc = cat_colors.get(cat, "rgb(150,150,150)")
        hc = cl_colors.get(hdb, "rgb(100,100,100)")
        lc = cat_colors.get(lda_pred, "rgb(150,150,150)")

        points_cat.append(
            f'{{x:{data["umap_x"][i]:.3f},y:{data["umap_y"][i]:.3f},c:"{cc}",n:"{name}",cat:"{cat}",cl:{hdb}}}'
        )
        points_hdb.append(
            f'{{x:{data["umap_x"][i]:.3f},y:{data["umap_y"][i]:.3f},c:"{hc}",n:"{name}",cat:"{cat}",cl:{hdb}}}'
        )
        points_lda.append(
            f'{{x:{data["lda_umap_x"][i]:.3f},y:{data["lda_umap_y"][i]:.3f},c:"{lc}",n:"{name}",cat:"{cat}",pred:"{lda_pred}",cl:{hdb}}}'
        )

    legend_cats = "".join(
        f'<span class="leg" style="background:{cat_colors[c]}">{c} ({data["categories"].count(c)})</span>'
        for c in cats
    )

    html = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>LDA vs HDBSCAN — Syndromes</title>
<style>
body {{ font-family: system-ui; margin: 15px; background: #1a1a2e; color: #eee; }}
h1 {{ color: #e94560; font-size: 1.3em; }}
h2 {{ color: #0f3460; font-size: 1.1em; margin: 10px 0 5px; }}
.row {{ display: flex; gap: 15px; flex-wrap: wrap; }}
.panel {{ flex: 1; min-width: 550px; }}
canvas {{ border: 1px solid #333; cursor: crosshair; width: 100%; }}
#tooltip {{ position: absolute; background: rgba(0,0,0,0.9); color: #fff; padding: 8px 12px;
  border-radius: 6px; font-size: 13px; pointer-events: none; display: none; max-width: 400px; z-index: 10; }}
.stats {{ font-size: 13px; color: #aaa; margin: 5px 0; }}
.legend {{ margin: 5px 0; display: flex; flex-wrap: wrap; gap: 4px; }}
.leg {{ padding: 2px 6px; border-radius: 3px; font-size: 11px; color: #fff; }}
</style>
</head><body>
<h1>LDA supervisée vs HDBSCAN aveugle — {len(data["syndrome_ids"])} syndromes</h1>
<div class="stats">
  ARI: {data["ari"]:.3f} | NMI: {data["nmi"]:.3f} |
  Pureté pondérée: {data["weighted_purity"]:.1%} |
  LDA CV accuracy: {data["lda_cv_accuracy"]:.1%} |
  HDBSCAN: {data["n_clusters_hdbscan"]} clusters
</div>
<div class="legend">{legend_cats}</div>

<div class="row">
  <div class="panel">
    <h2 style="color:#e94560">UMAP — Catégories DB (ground truth)</h2>
    <canvas id="c1" width="600" height="450"></canvas>
  </div>
  <div class="panel">
    <h2 style="color:#e94560">UMAP — HDBSCAN clusters (aveugle)</h2>
    <canvas id="c2" width="600" height="450"></canvas>
  </div>
</div>
<div class="row" style="margin-top:10px">
  <div class="panel">
    <h2 style="color:#e94560">LDA space — Prédictions LDA</h2>
    <canvas id="c3" width="600" height="450"></canvas>
  </div>
</div>

<div id="tooltip"></div>
<script>
const ptsCat = [{",".join(points_cat)}];
const ptsHdb = [{",".join(points_hdb)}];
const ptsLda = [{",".join(points_lda)}];

function drawCanvas(canvasId, pts) {{
  const canvas = document.getElementById(canvasId);
  const ctx = canvas.getContext('2d');
  let minX=Infinity,maxX=-Infinity,minY=Infinity,maxY=-Infinity;
  pts.forEach(p => {{ minX=Math.min(minX,p.x); maxX=Math.max(maxX,p.x); minY=Math.min(minY,p.y); maxY=Math.max(maxY,p.y); }});
  const pad = 30;
  const sx = (canvas.width - 2*pad) / (maxX - minX || 1);
  const sy = (canvas.height - 2*pad) / (maxY - minY || 1);

  ctx.fillStyle = '#1a1a2e';
  ctx.fillRect(0, 0, canvas.width, canvas.height);
  pts.forEach(p => {{
    const x = pad + (p.x - minX) * sx;
    const y = pad + (p.y - minY) * sy;
    ctx.beginPath();
    ctx.arc(x, y, 2.5, 0, Math.PI * 2);
    ctx.fillStyle = p.c;
    ctx.fill();
  }});

  canvas.addEventListener('mousemove', e => {{
    const rect = canvas.getBoundingClientRect();
    const scaleX = canvas.width / rect.width;
    const scaleY = canvas.height / rect.height;
    const mx = (e.clientX - rect.left) * scaleX;
    const my = (e.clientY - rect.top) * scaleY;
    let closest = null, minD = 100;
    pts.forEach(p => {{
      const x = pad + (p.x - minX) * sx;
      const y = pad + (p.y - minY) * sy;
      const d = Math.sqrt((mx-x)**2 + (my-y)**2);
      if (d < minD) {{ minD = d; closest = p; }}
    }});
    const tooltip = document.getElementById('tooltip');
    if (closest && minD < 12) {{
      tooltip.style.display = 'block';
      tooltip.style.left = (e.clientX + 15) + 'px';
      tooltip.style.top = (e.clientY + 15) + 'px';
      let info = '<b>' + closest.n + '</b><br>Cat: ' + closest.cat + '<br>Cluster HDBSCAN: ' + closest.cl;
      if (closest.pred) info += '<br>LDA prédit: ' + closest.pred;
      tooltip.innerHTML = info;
    }} else {{
      tooltip.style.display = 'none';
    }}
  }});
}}

drawCanvas('c1', ptsCat);
drawCanvas('c2', ptsHdb);
drawCanvas('c3', ptsLda);
</script>
</body></html>"""

    with open(path, "w") as f:
        f.write(html)


if __name__ == "__main__":
    main()
