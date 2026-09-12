#!/usr/bin/env python3
"""Le DAG cote syndromes, calcule depuis la matrice attestee (syndrome_hpo_livres).

Deux tables, deterministes, recalculables :
  syndrome_parente_livres  pour chaque entite de livre, ses 15 plus proches :
      score = Jaccard pondere par l'IC HPO sur les FERMETURES (signe + ancetres,
      hpo_ancestors), pour que « hypertelorisme » et « orbite anormale » se
      rencontrent a mi-chemin ; n_partages = signes directs communs ;
      partages = les 3 signes communs les plus informatifs ; disc_a / disc_b =
      les 3 signes les plus informatifs que l'un atteste et l'autre pas
      (ni lui ni ses descendants) ; meme_orpha = deux livres, une entite.
  famille_signes_livres    par famille (FAM via ORPHA, SPRFAM via prefixe) :
      chaque signe atteste chez ses membres, n_membres_attestant / n_membres ;
      un signe present chez >= 60 % des membres est « coeur », un signe present
      chez un seul membre est son « discriminant » dans la famille.
Filtre foetal (vue v_syndrome_hpo_livres_foetal), est_parent=0, clinique + radio.
Rien n'est pondere par la frequence : l'attestation est binaire ici (5346afe04b4f).

Usage : python3 build_parente_livres.py
"""
import re
import sqlite3
from collections import defaultdict

DB = "/home/mathevet/Bureau/foeto_base/syndromes_foetaux.db"
TOP = 15


def main():
    c = sqlite3.connect(DB)
    ic = dict(c.execute("select hpo_id, ic from hpo_ic"))
    lab = {h: (fr or en) for h, fr, en in c.execute("select hpo_id, label_fr, label_en from hpo_terms")}
    anc = defaultdict(set)
    for h, a in c.execute("select hpo_id, ancestor_id from hpo_ancestors"):
        anc[h].add(a)
    ic_def = sum(ic.values()) / len(ic)
    w = lambda h: ic.get(h, ic_def)

    direct, orpha, livre = defaultdict(set), {}, {}
    for t, sid, lv, h in c.execute("""select syndrome_titre, syndrome_id, livre, hpo_id from v_syndrome_hpo_livres_foetal
                                      where est_parent=0 and niveau_entree='syndrome'"""):
        direct[t].add(h); orpha[t] = sid; livre[t] = lv
    ferm = {t: set().union(*(anc[h] | {h} for h in hs)) for t, hs in direct.items()}
    poids = {t: sum(w(h) for h in f) for t, f in ferm.items()}
    ents = sorted(direct)
    print(f"{len(ents)} entités, {sum(len(v) for v in direct.values())} signes directs")

    c.execute("drop table if exists syndrome_parente_livres")
    c.execute("""create table syndrome_parente_livres (
        a text, b text, orpha_a text, orpha_b text, livre_a text, livre_b text,
        score real, n_partages integer, partages text, disc_a text, disc_b text, meme_orpha integer,
        primary key (a, b))""")
    def top3(hs, exclu):
        """3 signes les plus informatifs de hs qui ne sont pas dans la fermeture exclu"""
        return " ; ".join(f"{lab.get(h, h)} {h}" for h in sorted((h for h in hs if h not in exclu), key=lambda h: -w(h))[:3])
    rows = []
    for i, a in enumerate(ents):
        fa, pa = ferm[a], poids[a]
        cands = []
        for b in ents:
            if b == a:
                continue
            inter = fa & ferm[b]
            if not inter:
                continue
            s = sum(w(h) for h in inter) / (pa + poids[b] - sum(w(h) for h in inter))
            cands.append((s, b, inter))
        for s, b, inter in sorted(cands, key=lambda x: -x[0])[:TOP]:
            partages = direct[a] & direct[b]
            rows.append((a, b, orpha[a], orpha[b], livre[a], livre[b], round(s, 4), len(partages),
                         top3(partages or inter, set()), top3(direct[a], ferm[b]), top3(direct[b], fa),
                         int(bool(orpha[a]) and orpha[a] == orpha[b])))
    c.executemany("insert into syndrome_parente_livres values(?,?,?,?,?,?,?,?,?,?,?,?)", rows)

    # --- familles -------------------------------------------------------------
    c.execute("drop table if exists famille_signes_livres")
    c.execute("""create table famille_signes_livres (
        famille text, famille_nom text, hpo_id text, label text, n_membres_attestant integer, n_membres integer,
        part real, niveau text, membres text, primary key (famille, hpo_id))""")
    membres = defaultdict(set)
    noms = dict(c.execute("select family_id, family_name from syndrome_families"))
    o2t = defaultdict(set)
    for t, sid in orpha.items():
        if sid:
            o2t[sid].add(t)
    for fid, sid in c.execute("select family_id, syndrome_id from syndrome_family_members"):
        for t in o2t.get(sid, ()):
            membres[fid].add(t)
    for t in ents:
        m = re.match(r"^(\d+)\.\d+\s", t)
        if m and livre[t] == "spranger_entites":
            membres[f"SPRFAM:{m[1]}"].add(t)
    frows = 0
    for fid, ts in membres.items():
        if len(ts) < 2:
            continue
        cnt = defaultdict(set)
        for t in ts:
            for h in direct[t]:
                cnt[h].add(t)
        for h, who in cnt.items():
            part = len(who) / len(ts)
            niveau = "coeur" if part >= 0.6 else ("discriminant" if len(who) == 1 else "partiel")
            c.execute("insert into famille_signes_livres values(?,?,?,?,?,?,?,?,?)",
                      (fid, noms.get(fid, fid if not fid.startswith("SPRFAM") else f"Groupe Spranger {fid.split(':')[1]}"),
                       h, lab.get(h, h), len(who), len(ts), round(part, 3), niveau, " | ".join(sorted(who))))
            frows += 1
    c.commit()
    nf = c.execute("select count(distinct famille) from famille_signes_livres").fetchone()[0]
    print(f"parenté : {len(rows)} arêtes (top {TOP} par entité) ; familles : {nf} avec ≥ 2 membres attestés, {frows} lignes de signes")
    for fid, k, coeur in c.execute("""select famille_nom, n_membres, sum(niveau='coeur') from famille_signes_livres
                                      group by famille order by n_membres desc limit 8"""):
        print(f"  {fid[:45]:45s} {k:3d} membres, {coeur} signes cœur")


if __name__ == "__main__":
    main()
