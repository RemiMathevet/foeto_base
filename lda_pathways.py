#!/usr/bin/env python3
"""LDA sur voies de signalisation — regroupement des gènes par pathway.

Assigne chaque syndrome à une voie moléculaire basée sur ses gènes,
puis projette l'espace BioLORD via LDA pour voir si les embeddings
capturent la structure moléculaire.

Usage:
    python lda_pathways.py
    python lda_pathways.py --export
"""
import argparse
import json
import sqlite3
import time
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np
from sklearn.discriminant_analysis import LinearDiscriminantAnalysis
from sklearn.metrics import (
    adjusted_rand_score,
    normalized_mutual_info_score,
    classification_report,
)
from sklearn.model_selection import cross_val_score
import umap

DB_PATH = str(Path(__file__).resolve().parent / "syndromes_foetaux.db")
EMBED_DIM = 768

PATHWAY_RULES = {
    "collagène": [
        "COL1A1", "COL1A2", "COL2A1", "COL3A1", "COL4A1", "COL4A2", "COL4A3",
        "COL4A4", "COL4A5", "COL5A1", "COL5A2", "COL6A1", "COL6A2", "COL6A3",
        "COL7A1", "COL9A1", "COL9A2", "COL9A3", "COL10A1", "COL11A1", "COL11A2",
        "COL17A1", "COL18A1",
    ],
    "RAS-MAPK": [
        "BRAF", "KRAS", "NRAS", "HRAS", "MAP2K1", "MAP2K2", "RAF1",
        "PTPN11", "SOS1", "SOS2", "SHOC2", "CBL", "RIT1", "RRAS2",
        "LZTR1", "NF1", "SPRED1", "A2ML1",
    ],
    "Hedgehog": [
        "SHH", "IHH", "DHH", "PTCH1", "PTCH2", "GLI1", "GLI2", "GLI3",
        "SMO", "SUFU", "GAS1", "CDON", "BOC", "DISP1", "HHIP",
        "SCUBE2", "SHF",
    ],
    "FGF": [
        "FGFR1", "FGFR2", "FGFR3", "FGFR4",
        "FGF1", "FGF2", "FGF3", "FGF4", "FGF8", "FGF9", "FGF10",
        "FGF17", "FGF18", "FGF20", "FGF23",
        "FLRT3",
    ],
    "TGFβ-BMP": [
        "TGFB1", "TGFB2", "TGFB3", "TGFBR1", "TGFBR2",
        "BMP1", "BMP2", "BMP4", "BMP7", "BMP15",
        "BMPR1A", "BMPR1B", "BMPR2",
        "GDF1", "GDF3", "GDF5", "GDF6", "GDF11",
        "NODAL", "LEFTY1", "LEFTY2", "ACVR1", "ACVR2A", "ACVR2B",
        "SMAD1", "SMAD2", "SMAD3", "SMAD4", "SMAD5", "SMAD6",
        "TGIF1", "FOXH1", "CFC1", "CRIPTO",
    ],
    "cils_primaires": [
        "CC2D2A", "TMEM216", "TMEM67", "TMEM107", "TMEM138", "TMEM231",
        "CEP290", "CEP120", "CEP164", "CEP41", "CEP83", "CEP104",
        "MKS1", "B9D1", "B9D2", "RPGRIP1L", "TCTN1", "TCTN2", "TCTN3",
        "NPHP1", "NPHP3", "NPHP4", "IQCB1", "SDCCAG8",
        "IFT122", "IFT140", "IFT172", "IFT80", "IFT43",
        "DYNC2H1", "DYNC2LI1", "WDR19", "WDR34", "WDR35", "WDR60",
        "KIF7", "KIF3A", "KIF3B", "KIF11",
        "INPP5E", "AHI1", "ARMC9", "KIAA0586", "KIAA0753",
        "C5orf42", "CSPP1", "TMEM17", "TMEM237",
        "OFD1", "WDPCP", "TTC21B", "EVC", "EVC2",
    ],
    "Notch": [
        "NOTCH1", "NOTCH2", "NOTCH3", "NOTCH4",
        "DLL1", "DLL3", "DLL4",
        "JAG1", "JAG2",
        "HES1", "HES5", "HES7", "HEY1", "HEY2",
        "RBPJ", "MAML1", "LFNG", "MESP2",
    ],
    "Wnt": [
        "WNT1", "WNT2", "WNT2B", "WNT3", "WNT3A", "WNT4", "WNT5A",
        "WNT5B", "WNT7A", "WNT7B", "WNT10A", "WNT10B", "WNT11",
        "FZD1", "FZD2", "FZD4", "FZD6",
        "LRP5", "LRP6", "ROR2",
        "CTNNB1", "APC", "AXIN1", "AXIN2", "GSK3B",
        "RSPO1", "RSPO2", "RSPO3", "RSPO4",
        "PORCN", "WLS",
    ],
    "canal_ionique": [
        "KCNJ11", "KCNQ1", "KCNQ2", "KCNQ3", "KCNH2", "KCNK9",
        "KCNA1", "KCNA2", "KCNB1", "KCNC1", "KCND3", "KCNJ2",
        "SCN1A", "SCN2A", "SCN3A", "SCN4A", "SCN5A", "SCN8A", "SCN9A",
        "CACNA1A", "CACNA1C", "CACNA1D", "CACNA1E", "CACNA1S",
        "CLCN1", "CLCN2", "CLCN5", "CLCN7",
        "CFTR", "ABCC8",
    ],
    "sarcomère_NMJ": [
        "ACTA1", "ACTC1", "ACTN2",
        "MYH2", "MYH3", "MYH7", "MYH8", "MYH11",
        "MYBPC3", "MYL2", "MYL3",
        "TTN", "TNNT2", "TNNI3", "TPM1", "TPM2", "TPM3",
        "NEB", "LMOD3",
        "RYR1", "RYR2",
        "DOK7", "RAPSN", "CHRNA1", "CHRNB1", "CHRND", "CHRNE", "CHRNG",
        "MUSK", "CHAT", "AGRN", "COLQ",
        "MTM1", "DNM2", "BIN1",
    ],
    "kératine_épiderme": [
        "KRT1", "KRT2", "KRT5", "KRT9", "KRT10", "KRT14", "KRT16", "KRT17",
        "DSP", "DSG1", "DSG2", "DSG4", "DSC2", "DSC3",
        "JUP", "PKP1", "PKP2",
        "ITGA3", "ITGA6", "ITGB4",
        "LAMA3", "LAMB3", "LAMC2",
        "FERMT1", "KIND1", "PLEC",
        "TP63", "IRF6",
    ],
    "PI3K-AKT-mTOR": [
        "PIK3CA", "PIK3R2", "AKT1", "AKT2", "AKT3",
        "MTOR", "TSC1", "TSC2", "PTEN",
        "DEPDC5", "NPRL2", "NPRL3",
        "STRADA", "FLCN",
    ],
    "dystroglycanopathie": [
        "POMT1", "POMT2", "POMGNT1", "POMGNT2",
        "FKTN", "FKRP",
        "LARGE1", "ISPD", "GMPPB", "B3GALNT2", "B3GNT1",
        "DAG1", "POMK", "TMEM5", "CRPPA",
    ],
    "lysosomal": [
        "GBA", "GBA1", "SMPD1", "NPC1", "NPC2",
        "HEXA", "HEXB",
        "GALC", "ARSA", "ARSB",
        "IDUA", "IDS", "SGSH", "NAGLU", "HGSNAT", "GNS",
        "GUSB", "GALNS", "GLB1",
        "CLN1", "CLN2", "CLN3", "CLN5", "CLN6", "CLN8",
        "TPP1", "PPT1", "CTSD", "GRN",
        "LAMP2", "SUMF1", "GNPTAB", "GNPTG",
        "GAA", "AGA", "MANBA", "MAN2B1", "FUCA1",
        "ASAH1", "PSAP", "LIPA",
    ],
    "empreinte_14q32": [
        "DLK1", "MEG3", "RTL1", "DIO3", "MAGEL2",
    ],
    "lamine_enveloppe": [
        "LMNA", "LMNB1", "LMNB2",
        "EMD", "ZMPSTE24", "BANF1",
        "LBR", "TOR1A",
    ],
    "filamine_actine": [
        "FLNA", "FLNB", "FLNC",
        "ACTA2", "ACTB", "ACTG1",
        "MYH9", "MYH10",
    ],
    "connexine": [
        "GJA1", "GJA8", "GJB1", "GJB2", "GJB3", "GJB4", "GJB6",
    ],
    "holoprosencéphalie": [
        "SIX3", "TGIF1", "ZIC2", "TDGF1",
        "FGF8", "FGFR1",
    ],
    "cristalline_œil": [
        "CRYAA", "CRYAB", "CRYBA1", "CRYBA4",
        "CRYBB1", "CRYBB2", "CRYBB3",
        "CRYGC", "CRYGD", "CRYGS",
        "OTX2", "PAX6", "SOX2", "VSX2", "RAX",
        "FOXC1", "FOXE3", "PITX2", "PITX3",
        "MAF", "FOXC2",
    ],
    "homeobox_membre": [
        "HOXD13", "HOXD12", "HOXD11", "HOXD10",
        "HOXA13", "HOXA11",
        "TBX3", "TBX4", "TBX5",
        "LMBR1", "ZRS",
        "SALL1", "SALL4",
        "WNT7A", "EN1",
    ],
    "cardiaque_NKX_TBX": [
        "NKX2-5", "NKX2-6",
        "TBX1", "TBX5", "TBX20",
        "GATA4", "GATA5", "GATA6",
        "HAND1", "HAND2",
        "MYH6",
    ],
}

GENE_TO_PATHWAY = {}
for pathway, genes in PATHWAY_RULES.items():
    for g in genes:
        if g not in GENE_TO_PATHWAY:
            GENE_TO_PATHWAY[g] = pathway


def assign_pathway(gene_symbols):
    """Assign a syndrome to its primary pathway based on its genes."""
    pathways = []
    for g in gene_symbols:
        if g in GENE_TO_PATHWAY:
            pathways.append(GENE_TO_PATHWAY[g])
    if not pathways:
        return None
    counts = Counter(pathways)
    return counts.most_common(1)[0][0]


def load_chunk_centroids(conn):
    """Weighted centroid from vec_chunks."""
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
    print(f"  {len(centroids)} chunk centroids")
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
    print("LDA par voies de signalisation — gènes → pathways → BioLORD")
    print("=" * 80)

    # 1. Load syndrome → genes mapping
    sg_rows = conn.execute("SELECT syndrome_id, gene_symbol FROM syndrome_genes").fetchall()
    syn_genes = defaultdict(list)
    for sid, gsym in sg_rows:
        syn_genes[sid].append(gsym)

    # 2. Assign pathways
    syn_pathway = {}
    for sid, genes in syn_genes.items():
        pw = assign_pathway(genes)
        if pw:
            syn_pathway[sid] = pw

    print(f"\n{len(syn_pathway)} syndromes assignés à une voie (sur {len(syn_genes)} avec gènes)")

    pw_counts = Counter(syn_pathway.values())
    print(f"{len(pw_counts)} voies distinctes :\n")
    for pw, n in pw_counts.most_common():
        print(f"  {pw:<25s} {n:>4d}")

    # 3. Load embeddings
    chunk_centroids = load_chunk_centroids(conn)

    syndromes = conn.execute(
        "SELECT id, name_fr, name_en, category, prenatal_signs_summary, key_discriminators "
        "FROM syndromes"
    ).fetchall()
    syn_map = {r[0]: r for r in syndromes}

    # 4. Build matrices — only syndromes with pathway AND embedding
    syndrome_ids = []
    names = []
    categories = []
    pathways = []
    hdbscan_labels = []
    embeddings = []

    # Get HDBSCAN labels
    hdb_rows = conn.execute("SELECT syndrome_id, cluster_id FROM syndrome_clusters").fetchall()
    hdb_map = {r[0]: r[1] for r in hdb_rows}

    missing_texts = []
    missing_meta = []

    for sid, pw in syn_pathway.items():
        if sid not in syn_map:
            continue
        r = syn_map[sid]

        if sid in chunk_centroids:
            embeddings.append(chunk_centroids[sid])
            syndrome_ids.append(sid)
            names.append(r[1] or r[2] or sid)
            categories.append(r[3] or "autre")
            pathways.append(pw)
            hdbscan_labels.append(hdb_map.get(sid, -1))
        else:
            parts = list(filter(None, [r[1], r[2], (r[4] or "")[:500], (r[5] or "")[:500]]))
            text = ". ".join(parts)
            if text:
                missing_texts.append(text)
                missing_meta.append((sid, r[1] or r[2] or sid, r[3] or "autre", pw, hdb_map.get(sid, -1)))

    if missing_texts:
        print(f"\nEncoding {len(missing_texts)} syndromes sans chunks...")
        from sentence_transformers import SentenceTransformer
        model = SentenceTransformer("FremyCompany/BioLORD-2023")
        embs = model.encode(missing_texts, batch_size=64, show_progress_bar=True, normalize_embeddings=True)
        for i, (sid, name, cat, pw, hdb) in enumerate(missing_meta):
            syndrome_ids.append(sid)
            names.append(name)
            categories.append(cat)
            pathways.append(pw)
            hdbscan_labels.append(hdb)
            embeddings.append(embs[i])

    X = np.stack(embeddings)
    n = len(syndrome_ids)
    print(f"\n{n} syndromes avec voie + embedding")

    # 5. Filter small pathways
    MIN_PW = 8
    pw_final_counts = Counter(pathways)
    pw_map = {}
    for pw, cnt in pw_final_counts.items():
        pw_map[pw] = pw if cnt >= MIN_PW else None

    mask = [pw_map[pw] is not None for pw in pathways]
    X_filt = X[mask]
    pathways_filt = [pw for pw, m in zip(pathways, mask) if m]
    names_filt = [n for n, m in zip(names, mask) if m]
    cats_filt = [c for c, m in zip(categories, mask) if m]
    hdb_filt = [h for h, m in zip(hdbscan_labels, mask) if m]
    sids_filt = [s for s, m in zip(syndrome_ids, mask) if m]

    unique_pw = sorted(set(pathways_filt))
    print(f"\nAprès filtrage (<{MIN_PW}) : {len(unique_pw)} voies, {len(pathways_filt)} syndromes")
    for pw in unique_pw:
        print(f"  {pw:<25s} {pathways_filt.count(pw):>4d}")

    # 6. UMAP pre-reduction
    print(f"\nUMAP 768D → 50D...")
    t0 = time.time()
    reducer = umap.UMAP(n_components=50, n_neighbors=15, min_dist=0.0, metric="cosine", random_state=42)
    X_50d = reducer.fit_transform(X_filt)
    print(f"  {time.time()-t0:.1f}s")

    # 7. LDA
    y = np.array([unique_pw.index(pw) for pw in pathways_filt])
    n_classes = len(unique_pw)
    n_comp = min(n_classes - 1, 50)

    print(f"\nLDA : {n_classes} voies → {n_comp} axes discriminants")
    lda = LinearDiscriminantAnalysis(n_components=n_comp)
    X_lda = lda.fit_transform(X_50d, y)

    # CV
    print("Validation croisée 5-fold...")
    cv = cross_val_score(LinearDiscriminantAnalysis(), X_50d, y, cv=5, scoring="accuracy")
    print(f"  Accuracy: {cv.mean():.3f} ± {cv.std():.3f}")

    y_pred = lda.predict(X_50d)
    print(f"\nClassification report :")
    print(classification_report(y, y_pred, target_names=unique_pw, zero_division=0))

    # 8. Concordance pathways vs HDBSCAN
    hdb_arr = np.array(hdb_filt)
    non_noise = hdb_arr != -1
    if non_noise.sum() > 0:
        ari = adjusted_rand_score(np.array(y)[non_noise], hdb_arr[non_noise])
        nmi = normalized_mutual_info_score(np.array(y)[non_noise], hdb_arr[non_noise])
        print(f"\nConcordance voies vs HDBSCAN ({non_noise.sum()} non-bruit) :")
        print(f"  ARI : {ari:.4f}")
        print(f"  NMI : {nmi:.4f}")
    else:
        ari = 0.0
        nmi = 0.0

    # 9. LDA variance
    print(f"\nLDA — variance expliquée :")
    ev = lda.explained_variance_ratio_
    cumsum = np.cumsum(ev)
    for i in range(min(15, len(ev))):
        bar = "█" * int(ev[i] * 80)
        print(f"  LD{i+1:>2d}: {ev[i]:>6.3f} (cum: {cumsum[i]:>6.3f}) {bar}")

    # 10. Pureté HDBSCAN par pathway
    print(f"\nPureté des clusters HDBSCAN par voie :")
    print(f"{'Cluster':>8s} {'Size':>5s} | {'Dominant Pathway':<25s} {'Pur':>6s} | {'Pathways'}")
    print("-" * 100)

    cluster_pw = defaultdict(list)
    for i, hdb in enumerate(hdb_filt):
        if hdb != -1:
            cluster_pw[hdb].append(pathways_filt[i])

    for cid in sorted(cluster_pw.keys(), key=lambda c: -len(cluster_pw[c])):
        pws = cluster_pw[cid]
        if len(pws) < 3:
            continue
        counts = Counter(pws)
        dom = counts.most_common(1)[0][0]
        purity = counts[dom] / len(pws)
        pw_str = ", ".join(f"{p}:{n}" for p, n in counts.most_common(4))
        print(f"  {cid:>6d} {len(pws):>5d} | {dom:<25s} {purity:>5.1%} | {pw_str}")

    # 11. UMAP 2D
    print("\nUMAP 2D...")
    reducer_2d = umap.UMAP(n_neighbors=15, min_dist=0.1, metric="cosine", random_state=42)
    X_2d = reducer_2d.fit_transform(X_filt)

    reducer_lda_2d = umap.UMAP(n_neighbors=15, min_dist=0.1, metric="euclidean", random_state=42)
    X_lda_2d = reducer_lda_2d.fit_transform(X_lda)

    # Save
    import colorsys
    viz = {
        "syndrome_ids": sids_filt,
        "names": names_filt,
        "pathways": pathways_filt,
        "categories": cats_filt,
        "hdbscan_labels": [int(h) for h in hdb_filt],
        "lda_predictions": [unique_pw[int(p)] for p in y_pred],
        "umap_x": X_2d[:, 0].tolist(),
        "umap_y": X_2d[:, 1].tolist(),
        "lda_umap_x": X_lda_2d[:, 0].tolist(),
        "lda_umap_y": X_lda_2d[:, 1].tolist(),
        "unique_pathways": unique_pw,
        "lda_cv_accuracy": float(cv.mean()),
        "ari": float(ari),
        "nmi": float(nmi),
    }

    out_json = Path(__file__).resolve().parent / "lda_pathways_data.json"
    with open(out_json, "w") as f:
        json.dump(viz, f, ensure_ascii=False)

    html_path = Path(__file__).resolve().parent / "lda_pathways.html"
    _generate_html(viz, html_path)
    print(f"\nVisualization: {html_path}")

    # 12. Compare with category LDA
    print(f"\n{'='*80}")
    print("COMPARAISON FINALE")
    print(f"{'='*80}")
    print(f"  LDA catégories DB (9 classes)  : accuracy CV = ?  (voir lda_vs_hdbscan.py)")
    print(f"  LDA voies moléculaires ({n_classes} cl.) : accuracy CV = {cv.mean():.3f}")
    print(f"  HDBSCAN vs catégories          : ARI = ?  (voir lda_vs_hdbscan.py)")
    print(f"  HDBSCAN vs voies               : ARI = {ari:.4f}, NMI = {nmi:.4f}")
    print(f"\n  → Les voies sont {'mieux' if ari > 0.05 else 'moins bien'} capturées par HDBSCAN que les catégories DB")

    conn.close()
    print("\nDone.")


def _generate_html(data, path):
    import colorsys

    pws = data["unique_pathways"]
    pw_colors = {}
    for i, p in enumerate(pws):
        h = i / max(len(pws), 1)
        r, g, b = colorsys.hsv_to_rgb(h, 0.8, 0.9)
        pw_colors[p] = f"rgb({int(r*255)},{int(g*255)},{int(b*255)})"

    points_pw = []
    points_lda = []
    for i in range(len(data["syndrome_ids"])):
        name = data["names"][i].replace("'", "\\'").replace('"', '\\"')[:60]
        pw = data["pathways"][i]
        pred = data["lda_predictions"][i]
        hdb = data["hdbscan_labels"][i]
        c_pw = pw_colors.get(pw, "rgb(150,150,150)")
        c_pred = pw_colors.get(pred, "rgb(150,150,150)")

        points_pw.append(
            f'{{x:{data["umap_x"][i]:.3f},y:{data["umap_y"][i]:.3f},c:"{c_pw}",n:"{name}",pw:"{pw}",cl:{hdb}}}'
        )
        points_lda.append(
            f'{{x:{data["lda_umap_x"][i]:.3f},y:{data["lda_umap_y"][i]:.3f},c:"{c_pred}",n:"{name}",pw:"{pw}",pred:"{pred}",cl:{hdb}}}'
        )

    legend = "".join(
        f'<span class="leg" style="background:{pw_colors[p]}">{p} ({data["pathways"].count(p)})</span>'
        for p in pws
    )

    html = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>LDA Pathways — Syndromes</title>
<style>
body {{ font-family: system-ui; margin: 15px; background: #1a1a2e; color: #eee; }}
h1 {{ color: #e94560; font-size: 1.3em; }}
h2 {{ color: #e94560; font-size: 1.1em; margin: 10px 0 5px; }}
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
<h1>LDA Voies Moléculaires — {len(data["syndrome_ids"])} syndromes, {len(pws)} voies</h1>
<div class="stats">
  LDA CV accuracy: {data["lda_cv_accuracy"]:.1%} |
  HDBSCAN vs voies: ARI={data["ari"]:.3f}, NMI={data["nmi"]:.3f}
</div>
<div class="legend">{legend}</div>
<div class="row">
  <div class="panel">
    <h2>UMAP BioLORD — coloré par voie (ground truth)</h2>
    <canvas id="c1" width="600" height="450"></canvas>
  </div>
  <div class="panel">
    <h2>Espace LDA — prédictions voies</h2>
    <canvas id="c2" width="600" height="450"></canvas>
  </div>
</div>
<div id="tooltip"></div>
<script>
const ptsPw = [{",".join(points_pw)}];
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
    ctx.arc(x, y, 3.5, 0, Math.PI * 2);
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
      let info = '<b>' + closest.n + '</b><br>Voie: ' + closest.pw + '<br>Cluster: ' + closest.cl;
      if (closest.pred) info += '<br>LDA prédit: ' + closest.pred;
      tooltip.innerHTML = info;
    }} else {{
      tooltip.style.display = 'none';
    }}
  }});
}}
drawCanvas('c1', ptsPw);
drawCanvas('c2', ptsLda);
</script>
</body></html>"""

    with open(path, "w") as f:
        f.write(html)


if __name__ == "__main__":
    main()
