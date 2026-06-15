#!/usr/bin/env python3
"""Serveur Flask de gestion de syndromes_foetaux.db."""

import json
import math
import os
import pathlib
import re
import sqlite3
from datetime import datetime

from markupsafe import Markup
from flask import (Flask, render_template, request, redirect,
                   url_for, flash, g, Response, abort)

APP_DIR = pathlib.Path(__file__).parent
DB_PATH = APP_DIR / "syndromes_foetaux.db"

app = Flask(__name__)
app.secret_key = "foeto-base-2026-key"

FEEDBACK_DIR = os.path.join(os.path.dirname(__file__), "feedback")
_WIDGET_SCRIPT = '<script src="/static/widget-feedback.js"></script>'


@app.template_filter("md")
def md_filter(text):
    if not text:
        return ""
    import html as _html
    text = _html.escape(text)
    text = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", text)
    lines = text.split("\n")
    out = []
    in_ul = False
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("- "):
            if not in_ul:
                out.append("<ul>")
                in_ul = True
            out.append(f"<li>{stripped[2:]}</li>")
        else:
            if in_ul:
                out.append("</ul>")
                in_ul = False
            if stripped:
                out.append(f"<p>{stripped}</p>")
    if in_ul:
        out.append("</ul>")
    return Markup("\n".join(out))

AUTH_USER = "Rémi"
AUTH_PASS = "R1m2E3a4"
PER_PAGE = 50

CATEGORIES = [
    "malformatif", "metabolique", "neuromusculaire", "chromosomique",
    "squelettique", "vasculaire_placentaire", "tumoral", "infectieux", "autre",
]
RELEVANCES = ["haute", "moyenne", "faible"]


def check_auth(username: str, password: str) -> bool:
    return username == AUTH_USER and password == AUTH_PASS


@app.before_request
def require_auth():
    if request.path.startswith("/api/foekinator/"):
        return
    auth = request.authorization
    if not auth or not check_auth(auth.username, auth.password):
        return Response(
            "Authentification requise.",
            401,
            {"WWW-Authenticate": 'Basic realm="FOETO-BASE"'},
        )


def get_db() -> sqlite3.Connection:
    if "db" not in g:
        g.db = sqlite3.connect(str(DB_PATH))
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys=ON")
    return g.db


@app.teardown_appcontext
def close_db(_exc):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def paginate(query, args, page, per_page=PER_PAGE):
    db = get_db()
    count_q = f"SELECT COUNT(*) FROM ({query})"
    total = db.execute(count_q, args).fetchone()[0]
    total_pages = max(1, math.ceil(total / per_page))
    page = max(1, min(page, total_pages))
    rows = db.execute(f"{query} LIMIT ? OFFSET ?",
                      args + (per_page, (page - 1) * per_page)).fetchall()
    return rows, total, total_pages, page


class DotDict(dict):
    __getattr__ = dict.__getitem__


# =====================================================================
# INDEX — Syndromes list
# =====================================================================
@app.route("/")
def index():
    db = get_db()
    q = request.args.get("q", "").strip()
    cat = request.args.get("cat", "")
    rel = request.args.get("rel", "")
    sort = request.args.get("sort", "name_fr")
    dir_ = request.args.get("dir", "asc")
    page = int(request.args.get("page", 1))

    allowed_sorts = {"name_fr": "s.name_fr", "n_hpo": "n_hpo", "n_genes": "n_genes"}
    order_col = allowed_sorts.get(sort, "s.name_fr")
    order_dir = "DESC" if dir_ == "desc" else "ASC"

    base = """
        SELECT s.id, s.name_fr, s.name_en, s.aliases, s.category, s.relevance, s.inheritance,
               (SELECT COUNT(*) FROM syndrome_hpo sh WHERE sh.syndrome_id = s.id) AS n_hpo,
               (SELECT COUNT(*) FROM syndrome_genes sg WHERE sg.syndrome_id = s.id) AS n_genes
        FROM syndromes s
        WHERE 1=1
    """
    args = []
    if q:
        base += """ AND (s.name_fr LIKE ? OR s.name_en LIKE ? OR s.aliases LIKE ?
                    OR s.id LIKE ? OR s.omim LIKE ?
                    OR s.id IN (SELECT syndrome_id FROM syndrome_genes WHERE gene_symbol LIKE ?)
                    OR s.id IN (SELECT syndrome_id FROM syndrome_hpo WHERE hpo_id LIKE ?))"""
        w = f"%{q}%"
        args.extend([w, w, w, w, w, w, w])
    if cat:
        base += " AND s.category = ?"
        args.append(cat)
    if rel:
        base += " AND s.relevance = ?"
        args.append(rel)

    query = f"{base} ORDER BY {order_col} {order_dir}"
    syndromes, total, total_pages, page = paginate(query, tuple(args), page)

    result = []
    for s in syndromes:
        inh = ""
        try:
            inh = ", ".join(json.loads(s["inheritance"] or "[]"))
        except (json.JSONDecodeError, TypeError):
            pass
        result.append({**dict(s), "inheritance_display": inh})

    categories = [r[0] for r in db.execute(
        "SELECT DISTINCT category FROM syndromes ORDER BY category").fetchall()]
    relevances_db = [r[0] for r in db.execute(
        "SELECT DISTINCT relevance FROM syndromes WHERE relevance IS NOT NULL ORDER BY relevance").fetchall()]

    stats = [
        ("Syndromes", db.execute("SELECT COUNT(*) FROM syndromes").fetchone()[0]),
        ("Termes HPO", db.execute("SELECT COUNT(*) FROM hpo_terms").fetchone()[0]),
        ("Genes", db.execute("SELECT COUNT(*) FROM genes").fetchone()[0]),
        ("Associations HPO", db.execute("SELECT COUNT(*) FROM syndrome_hpo").fetchone()[0]),
    ]

    return render_template("index.html", syndromes=result, total=total,
                           page=page, total_pages=total_pages,
                           q=q, cat=cat, rel=rel, sort=sort, dir=dir_,
                           categories=categories, relevances=relevances_db,
                           stats=stats)


# =====================================================================
# SYNDROME — detail view
# =====================================================================
@app.route("/syndrome/<path:sid>")
def syndrome_view(sid):
    db = get_db()
    s = db.execute("SELECT * FROM syndromes WHERE id = ?", (sid,)).fetchone()
    if not s:
        abort(404)
    s = dict(s)

    try:
        s["inheritance_display"] = ", ".join(json.loads(s["inheritance"] or "[]"))
    except (json.JSONDecodeError, TypeError):
        s["inheritance_display"] = ""
    try:
        s["onset_display"] = ", ".join(json.loads(s["ages_of_onset"] or "[]"))
    except (json.JSONDecodeError, TypeError):
        s["onset_display"] = ""

    s["aliases_list"] = [a.strip() for a in (s.get("aliases") or "").split(",") if a.strip()]

    genes = db.execute("""
        SELECT g.symbol, g.name, g.omim AS gene_omim, g.locus, sg.role
        FROM syndrome_genes sg
        JOIN genes g ON sg.gene_symbol = g.symbol
        WHERE sg.syndrome_id = ?
        ORDER BY sg.role, g.symbol
    """, (sid,)).fetchall()

    hpo_terms = db.execute("""
        SELECT h.hpo_id, h.label_en, h.label_fr, h.context,
               sh.frequency, sh.prob, sh.source
        FROM syndrome_hpo sh
        JOIN hpo_terms h ON sh.hpo_id = h.hpo_id
        WHERE sh.syndrome_id = ?
        ORDER BY sh.prob DESC NULLS LAST, h.label_en
    """, (sid,)).fetchall()

    families = db.execute("""
        SELECT f.family_id, f.family_name, f.mechanism, f.n_members, fm.confidence
        FROM syndrome_family_members fm
        JOIN syndrome_families f ON fm.family_id = f.family_id
        WHERE fm.syndrome_id = ?
    """, (sid,)).fetchall()

    family_siblings = []
    for fam in families:
        sibs = db.execute("""
            SELECT s2.id, s2.name_fr, s2.category, fm2.confidence
            FROM syndrome_family_members fm2
            JOIN syndromes s2 ON fm2.syndrome_id = s2.id
            WHERE fm2.family_id = ? AND fm2.syndrome_id != ?
            ORDER BY s2.name_fr
        """, (fam["family_id"], sid)).fetchall()
        family_siblings.append({
            "family": dict(fam),
            "siblings": [dict(s2) for s2 in sibs],
        })

    spectrum = db.execute("""
        SELECT s2.id, s2.name_fr, s2.category, sp.similarity,
               sp.shared_hpo, sp.shared_genes, sp.jaccard, sp.same_family
        FROM syndrome_spectrum sp
        JOIN syndromes s2 ON (
            CASE WHEN sp.syndrome_id_1 = ? THEN sp.syndrome_id_2
                 ELSE sp.syndrome_id_1 END
        ) = s2.id
        WHERE sp.syndrome_id_1 = ? OR sp.syndrome_id_2 = ?
        ORDER BY sp.similarity DESC
        LIMIT 15
    """, (sid, sid, sid)).fetchall()

    return render_template("syndrome.html",
                           s=DotDict(s), genes=genes, hpo_terms=hpo_terms,
                           families=family_siblings, spectrum=spectrum)


# =====================================================================
# SYNDROME — edit
# =====================================================================
@app.route("/syndrome/<path:sid>/edit", methods=["GET", "POST"])
def syndrome_edit(sid):
    db = get_db()
    s = db.execute("SELECT * FROM syndromes WHERE id = ?", (sid,)).fetchone()
    if not s:
        abort(404)

    if request.method == "POST":
        db.execute("""
            UPDATE syndromes SET
                name_fr = ?, name_en = ?, omim = ?, category = ?,
                relevance = NULLIF(?, ''), prevalence = NULLIF(?, ''),
                aliases = NULLIF(?, ''),
                description_md = NULLIF(?, ''),
                prenatal_signs_summary = NULLIF(?, ''),
                key_discriminators = NULLIF(?, ''),
                differential_diagnosis = NULLIF(?, ''),
                updated_at = datetime('now')
            WHERE id = ?
        """, (
            request.form["name_fr"], request.form.get("name_en", ""),
            request.form.get("omim", ""), request.form["category"],
            request.form.get("relevance", ""), request.form.get("prevalence", ""),
            request.form.get("aliases", ""),
            request.form.get("description_md", ""),
            request.form.get("prenatal_signs_summary", ""),
            request.form.get("key_discriminators", ""),
            request.form.get("differential_diagnosis", ""),
            sid,
        ))
        db.commit()
        flash("Syndrome mis a jour.", "success")
        return redirect(url_for("syndrome_view", sid=sid))

    s = dict(s)

    return render_template("syndrome_edit.html", s=DotDict(s),
                           categories=CATEGORIES, relevances=RELEVANCES)


# =====================================================================
# SYNDROME — new (manual add)
# =====================================================================
@app.route("/syndrome/new", methods=["GET", "POST"])
def syndrome_new():
    db = get_db()

    if request.method == "POST":
        sid = request.form.get("id", "").strip()
        name_fr = request.form.get("name_fr", "").strip()
        if not sid or not name_fr:
            flash("ID et Nom FR sont obligatoires.", "error")
            return render_template("syndrome_new.html",
                                   categories=CATEGORIES, relevances=RELEVANCES,
                                   form=request.form)

        existing = db.execute("SELECT id FROM syndromes WHERE id = ?", (sid,)).fetchone()
        if existing:
            flash(f"Un syndrome avec l'ID {sid} existe deja.", "error")
            return render_template("syndrome_new.html",
                                   categories=CATEGORIES, relevances=RELEVANCES,
                                   form=request.form)

        db.execute("""
            INSERT INTO syndromes
            (id, name_fr, name_en, omim, orpha_code, type, category, relevance,
             prevalence, inheritance, ages_of_onset, aliases,
             description_md, prenatal_signs_summary, key_discriminators,
             differential_diagnosis)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            sid,
            name_fr,
            request.form.get("name_en", ""),
            request.form.get("omim", "") or None,
            request.form.get("orpha_code", "") or None,
            request.form.get("type", "") or None,
            request.form.get("category", "autre"),
            request.form.get("relevance", "") or None,
            request.form.get("prevalence", "") or None,
            json.dumps([x.strip() for x in request.form.get("inheritance", "").split(",") if x.strip()],
                       ensure_ascii=False) if request.form.get("inheritance") else "[]",
            json.dumps([x.strip() for x in request.form.get("ages_of_onset", "").split(",") if x.strip()],
                       ensure_ascii=False) if request.form.get("ages_of_onset") else "[]",
            request.form.get("aliases", "") or None,
            request.form.get("description_md", "") or None,
            request.form.get("prenatal_signs_summary", "") or None,
            request.form.get("key_discriminators", "") or None,
            request.form.get("differential_diagnosis", "") or None,
        ))
        db.commit()
        flash(f"Syndrome {sid} cree.", "success")
        return redirect(url_for("syndrome_view", sid=sid))

    return render_template("syndrome_new.html",
                           categories=CATEGORIES, relevances=RELEVANCES,
                           form={})


# =====================================================================
# GENES
# =====================================================================
@app.route("/genes")
def genes_list():
    q = request.args.get("q", "").strip()
    page = int(request.args.get("page", 1))

    base = """
        SELECT g.symbol, g.name, g.omim, g.locus,
               (SELECT COUNT(*) FROM syndrome_genes sg WHERE sg.gene_symbol = g.symbol) AS n_syndromes
        FROM genes g
        WHERE 1=1
    """
    args = []
    if q:
        base += " AND (g.symbol LIKE ? OR g.name LIKE ? OR g.omim LIKE ? OR g.locus LIKE ?)"
        w = f"%{q}%"
        args.extend([w, w, w, w])
    query = f"{base} ORDER BY n_syndromes DESC, g.symbol"
    genes, total, total_pages, page = paginate(query, tuple(args), page)

    return render_template("genes.html", genes=genes, total=total,
                           page=page, total_pages=total_pages, q=q)


@app.route("/gene/<symbol>")
def gene_view(symbol):
    db = get_db()
    gene = db.execute("SELECT * FROM genes WHERE symbol = ?", (symbol,)).fetchone()
    if not gene:
        abort(404)

    syndromes = db.execute("""
        SELECT s.id, s.name_fr, s.category, sg.role
        FROM syndrome_genes sg
        JOIN syndromes s ON sg.syndrome_id = s.id
        WHERE sg.gene_symbol = ?
        ORDER BY s.name_fr
    """, (symbol,)).fetchall()

    return render_template("gene.html", gene=gene, syndromes=syndromes)


# =====================================================================
# HPO
# =====================================================================
@app.route("/hpo")
def hpo_list():
    q = request.args.get("q", "").strip()
    ctx = request.args.get("ctx", "")
    page = int(request.args.get("page", 1))

    base = """
        SELECT h.hpo_id, h.label_en, h.label_fr, h.context,
               (SELECT COUNT(*) FROM syndrome_hpo sh WHERE sh.hpo_id = h.hpo_id) AS n_syndromes
        FROM hpo_terms h
        WHERE 1=1
    """
    args = []
    if q:
        base += " AND (h.hpo_id LIKE ? OR h.label_en LIKE ? OR h.label_fr LIKE ?)"
        w = f"%{q}%"
        args.extend([w, w, w])
    if ctx:
        base += " AND h.context = ?"
        args.append(ctx)
    query = f"{base} ORDER BY n_syndromes DESC, h.hpo_id"
    terms, total, total_pages, page = paginate(query, tuple(args), page)

    return render_template("hpo.html", terms=terms, total=total,
                           page=page, total_pages=total_pages, q=q, ctx=ctx)


@app.route("/hpo/<hpo_id>")
def hpo_view(hpo_id):
    db = get_db()
    term = db.execute("SELECT * FROM hpo_terms WHERE hpo_id = ?", (hpo_id,)).fetchone()
    if not term:
        abort(404)

    syndromes = db.execute("""
        SELECT s.id, s.name_fr, s.category, sh.frequency, sh.prob
        FROM syndrome_hpo sh
        JOIN syndromes s ON sh.syndrome_id = s.id
        WHERE sh.hpo_id = ?
        ORDER BY sh.prob DESC NULLS LAST, s.name_fr
    """, (hpo_id,)).fetchall()

    return render_template("hpo_view.html", term=term, syndromes=syndromes)


@app.route("/hpo/<hpo_id>/context", methods=["POST"])
def hpo_update_context(hpo_id):
    db = get_db()
    ctx = request.form.get("context", "both")
    if ctx not in ("prenatal", "postnatal", "both"):
        ctx = "both"
    db.execute("UPDATE hpo_terms SET context = ? WHERE hpo_id = ?", (ctx, hpo_id))
    db.commit()
    flash(f"Contexte de {hpo_id} mis a jour: {ctx}", "success")
    return redirect(url_for("hpo_view", hpo_id=hpo_id))


# =====================================================================
# STATS
# =====================================================================
@app.route("/stats")
def stats():
    db = get_db()

    global_stats = [
        ("Syndromes", db.execute("SELECT COUNT(*) FROM syndromes").fetchone()[0]),
        ("Termes HPO", db.execute("SELECT COUNT(*) FROM hpo_terms").fetchone()[0]),
        ("Genes", db.execute("SELECT COUNT(*) FROM genes").fetchone()[0]),
        ("Assoc. HPO", db.execute("SELECT COUNT(*) FROM syndrome_hpo").fetchone()[0]),
        ("Assoc. genes", db.execute("SELECT COUNT(*) FROM syndrome_genes").fetchone()[0]),
        ("Avec genes", db.execute("SELECT COUNT(DISTINCT syndrome_id) FROM syndrome_genes").fetchone()[0]),
    ]

    by_category = db.execute("""
        SELECT s.category,
               COUNT(*) AS n,
               SUM(CASE WHEN EXISTS(SELECT 1 FROM syndrome_genes sg WHERE sg.syndrome_id=s.id) THEN 1 ELSE 0 END) AS n_with_genes
        FROM syndromes s
        GROUP BY s.category ORDER BY n DESC
    """).fetchall()

    hpo_context = db.execute("""
        SELECT context, COUNT(*) AS n FROM hpo_terms GROUP BY context ORDER BY n DESC
    """).fetchall()

    top_genes = db.execute("""
        SELECT g.symbol, g.locus, COUNT(*) AS n
        FROM syndrome_genes sg JOIN genes g ON sg.gene_symbol = g.symbol
        GROUP BY g.symbol ORDER BY n DESC LIMIT 15
    """).fetchall()

    top_hpo = db.execute("""
        SELECT h.hpo_id, h.label_en, COUNT(*) AS n
        FROM syndrome_hpo sh JOIN hpo_terms h ON sh.hpo_id = h.hpo_id
        GROUP BY h.hpo_id ORDER BY n DESC LIMIT 15
    """).fetchall()

    return render_template("stats.html", global_stats=global_stats,
                           by_category=by_category, hpo_context=hpo_context,
                           top_genes=top_genes, top_hpo=top_hpo)


# =====================================================================
# SQL CONSOLE
# =====================================================================
@app.route("/sql", methods=["GET", "POST"])
def sql_query():
    db = get_db()
    query = ""
    columns = []
    rows = []
    error = None

    tables_raw = db.execute("""
        SELECT name FROM sqlite_master
        WHERE type='table' AND name NOT LIKE 'sqlite_%'
        ORDER BY name
    """).fetchall()
    tables = []
    for t in tables_raw:
        cols = db.execute(f"PRAGMA table_info({t['name']})").fetchall()
        tables.append({"name": t["name"], "columns": [c["name"] for c in cols]})

    if request.method == "POST":
        query = request.form.get("query", "").strip()
        if not query:
            error = "Requete vide."
        elif not query.upper().lstrip().startswith("SELECT"):
            error = "Seules les requetes SELECT sont autorisees."
        else:
            try:
                cur = db.execute(query)
                if cur.description:
                    columns = [d[0] for d in cur.description]
                    rows = cur.fetchmany(500)
            except Exception as e:
                error = str(e)

    return render_template("sql.html", query=query, columns=columns,
                           rows=rows, error=error, tables=tables)


# =====================================================================
# FOEKINATOR API (sans auth, avec CORS)
# =====================================================================
FREQ_TO_PROB = {
    "Obligate (100%)": 0.99,
    "Very frequent (99-80%)": 0.85,
    "Frequent (79-30%)": 0.50,
    "Occasional (29-5%)": 0.15,
    "Very rare (<4-1%)": 0.02,
    "Excluded (0%)": 0.0,
}

CATEGORY_LABELS = {
    "malformatif": "Syndromes malformatifs",
    "squelettique": "Dysplasies squelettiques",
    "chromosomique": "Anomalies chromosomiques",
    "metabolique": "Maladies metaboliques",
    "neuromusculaire": "Syndromes neuromusculaires",
    "vasculaire_placentaire": "Pathologies vasculaires/placentaires",
    "tumoral": "Tumeurs",
    "infectieux": "Infections",
    "autre": "Autres",
}


def _cors(response):
    response.headers["Access-Control-Allow-Origin"] = "*"
    return response


@app.route("/api/foekinator/databases")
def foekinator_databases():
    db = get_db()
    cats = db.execute(
        "SELECT category, COUNT(*) as n FROM syndromes GROUP BY category ORDER BY n DESC"
    ).fetchall()
    total = db.execute("SELECT COUNT(*) FROM syndromes").fetchone()[0]
    haute = db.execute(
        "SELECT COUNT(*) FROM syndromes WHERE relevance = 'haute'"
    ).fetchone()[0]

    databases = [
        {"id": "all", "name": f"Tous les syndromes ({total})", "params": {}},
        {"id": "haute", "name": f"Pertinence haute ({haute})", "params": {"relevance": "haute"}},
    ]
    for cat in cats:
        label = CATEGORY_LABELS.get(cat["category"], cat["category"])
        databases.append({
            "id": f"cat_{cat['category']}",
            "name": f"{label} ({cat['n']})",
            "params": {"category": cat["category"]},
        })

    resp = Response(
        json.dumps({"databases": databases}, ensure_ascii=False),
        mimetype="application/json",
    )
    return _cors(resp)


@app.route("/api/foekinator/export")
def foekinator_export():
    """Export au format Foekinator JSON.

    ?category=malformatif,squelettique
    ?relevance=haute,moyenne
    ?context=prenatal|postnatal
    ?min_hpo=1
    """
    db = get_db()

    cats = [c.strip() for c in request.args.get("category", "").split(",") if c.strip()]
    rels = [r.strip() for r in request.args.get("relevance", "").split(",") if r.strip()]
    ctx = request.args.get("context", "").strip()
    min_hpo = int(request.args.get("min_hpo", 1))

    where_syn = []
    args_syn = []
    if cats:
        where_syn.append(f"s.category IN ({','.join('?' * len(cats))})")
        args_syn.extend(cats)
    if rels:
        where_syn.append(f"s.relevance IN ({','.join('?' * len(rels))})")
        args_syn.extend(rels)

    syn_filter = (" AND " + " AND ".join(where_syn)) if where_syn else ""

    syndromes = db.execute(f"""
        SELECT s.id, s.name_fr, s.prevalence, s.category
        FROM syndromes s
        WHERE (SELECT COUNT(*) FROM syndrome_hpo sh2 WHERE sh2.syndrome_id = s.id) >= ?
        {syn_filter}
        ORDER BY s.name_fr
    """, [min_hpo] + args_syn).fetchall()

    syn_ids = [s["id"] for s in syndromes]
    if not syn_ids:
        resp = Response(
            json.dumps({"_meta": {}, "hpo_terms": {}, "diseases": []}, ensure_ascii=False),
            mimetype="application/json",
        )
        return _cors(resp)

    placeholders = ",".join("?" * len(syn_ids))
    assocs = db.execute(f"""
        SELECT syndrome_id, hpo_id, prob, frequency
        FROM syndrome_hpo
        WHERE syndrome_id IN ({placeholders})
    """, syn_ids).fetchall()

    hpo_ids_used = set()
    assoc_map = {}
    for a in assocs:
        sid = a["syndrome_id"]
        pen = a["prob"]
        if pen is None or pen <= 0:
            pen = FREQ_TO_PROB.get(a["frequency"], 0.01)
        assoc_map.setdefault(sid, []).append({"hpo_id": a["hpo_id"], "penetrance": pen})
        hpo_ids_used.add(a["hpo_id"])

    hpo_filter = ""
    args_hpo = []
    if ctx in ("prenatal", "postnatal"):
        hpo_filter = " AND (h.context = ? OR h.context = 'both')"
        args_hpo.append(ctx)

    hpo_placeholders = ",".join("?" * len(hpo_ids_used))
    hpo_rows = db.execute(f"""
        SELECT h.hpo_id, h.label_en, h.label_fr, h.context
        FROM hpo_terms h
        WHERE h.hpo_id IN ({hpo_placeholders})
        {hpo_filter}
    """, list(hpo_ids_used) + args_hpo).fetchall()

    hpo_allowed = set()
    hpo_terms = {}
    for h in hpo_rows:
        hpo_terms[h["hpo_id"]] = {
            "name_fr": h["label_fr"] or h["label_en"],
            "context": h["context"] or "both",
        }
        hpo_allowed.add(h["hpo_id"])

    if ctx in ("prenatal", "postnatal"):
        for sid in assoc_map:
            assoc_map[sid] = [a for a in assoc_map[sid] if a["hpo_id"] in hpo_allowed]

    diseases = []
    for s in syndromes:
        phenos = assoc_map.get(s["id"], [])
        if not phenos:
            continue
        diseases.append({
            "disease_id": s["id"],
            "disease_name": s["name_fr"],
            "prevalence": s["prevalence"] if s["prevalence"] else 0.001,
            "phenotypes": phenos,
        })

    meta = {
        "name": "Syndromes foetaux",
        "version": "sql-live",
        "source": "syndromes_foetaux.db",
        "generated": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "diseases_count": len(diseases),
        "hpo_terms_count": len(hpo_terms),
        "associations_count": sum(len(d["phenotypes"]) for d in diseases),
        "filters": {
            "category": cats or "all",
            "relevance": rels or "all",
            "context": ctx or "all",
            "min_hpo": min_hpo,
        },
    }

    payload = json.dumps(
        {"_meta": meta, "hpo_terms": hpo_terms, "diseases": diseases},
        ensure_ascii=False,
    )
    return _cors(Response(payload, mimetype="application/json"))


# =====================================================================
# FEEDBACK
# =====================================================================
@app.route("/api/feedback", methods=["GET", "POST"])
def feedback():
    if request.method == "GET":
        items = []
        if os.path.isdir(FEEDBACK_DIR):
            for fname in sorted(os.listdir(FEEDBACK_DIR), reverse=True):
                if not fname.endswith(".txt"):
                    continue
                filepath = os.path.join(FEEDBACK_DIR, fname)
                with open(filepath, "r") as f:
                    lines = f.read().split("\n")
                item = {"file": fname, "author": "", "type": "", "page": "", "date": "", "text": ""}
                in_body = False
                body_lines = []
                for line in lines:
                    if line.startswith("---"):
                        in_body = True
                        continue
                    if in_body:
                        body_lines.append(line)
                    elif line.startswith("Date : "):
                        item["date"] = line[7:]
                    elif line.startswith("Auteur : "):
                        item["author"] = line[9:]
                    elif line.startswith("Type : "):
                        item["type"] = line[7:]
                    elif line.startswith("Page : "):
                        item["page"] = line[7:]
                item["text"] = "\n".join(body_lines).strip()
                items.append(item)
        return Response(json.dumps({"items": items}, ensure_ascii=False),
                        mimetype="application/json")

    data = request.get_json(silent=True)
    if not data or not data.get("text"):
        return Response(json.dumps({"ok": False, "error": "texte requis"}),
                        status=400, mimetype="application/json")
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    name = data.get("name", "Anonyme").replace("/", "-")[:30]
    typ = data.get("type", "idee")[:20]
    page = data.get("page", "inconnue").replace("/", "").replace(".html", "")[:40]
    user = request.authorization.username if request.authorization else "?"
    filename = f"{ts}_{page}_{typ}_{name}.txt"
    content = (
        f"Date : {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
        f"Auteur : {name}\n"
        f"Type : {typ}\n"
        f"Page : {page}\n"
        f"Utilisateur connecté : {user}\n"
        f"---\n"
        f"{data['text']}\n"
    )
    os.makedirs(FEEDBACK_DIR, exist_ok=True)
    with open(os.path.join(FEEDBACK_DIR, filename), "w") as f:
        f.write(content)
    return Response(json.dumps({"ok": True}), mimetype="application/json")


@app.after_request
def _inject_feedback_widget(response):
    if response.content_type and "text/html" in response.content_type:
        data = response.get_data(as_text=True)
        if "</body>" in data:
            data = data.replace("</body>", _WIDGET_SCRIPT + "\n</body>")
            response.set_data(data)
    return response


# =====================================================================
if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5070, debug=True)
