-- Rend annotables les 13 lésions marquées viewer_quick=1 mais sans viewer_id,
-- et retire le drapeau quick des 17 qui ne doivent pas être des labels d'annotation.
--
-- Contexte : 32 termes placenta portaient viewer_quick=1 avec viewer_id/viewer_level à NULL.
-- Lumi/app.py:1037 filtre sur `viewer_level IS NOT NULL AND viewer_id IS NOT NULL` : ils
-- n'ont jamais existé dans l'interface. C'est ce trou qui a fait annoter l'abcès décidual
-- via le terme-grade mir_g2 (« MIR Grade 1 — Abcès décidual »), seul label annotable
-- portant ces mots.
--
-- viewer_level = échelle d'annotation (viewer.js:669), PAS une magnification :
--   0 Label lame · 1 Région (faible G) · 2 Histo (moyen G)
-- Vérifié : il ne corrèle pas avec foeto_term_segments.mag. Les 13 ont tous leurs segments
-- à x10 et x20 → niveau 2.
--
-- Rattachement des organes de granularité structure vers le tissu, justifié par les paires
-- de libellés strictement identiques (aucune n'est un terme déplacé ici) :
--   plaque_basale   → parenchyme  (PBA-VAS-002=PAR-VAS-017, PBA-INF-001=PAR-INF-005)
--   plaque_choriale → parenchyme  (PCH-VAS-001=PAR-VAS-020, PCH-VAS-003=PAR-VAS-019)
--   arteres_uteroplacentaires → parenchyme (AUP-VAS-003≈PAR-MET-003, -004≈PAR-VAS-013,
--                                           -005≈PAR-VAS-017)
--   vaisseaux_allantochoriaux → parenchyme  ⚠ le plus faible des quatre : appuyé sur le
--     seul VAC-VAS-001 ≈ PAR-VAS-005 (FVM High grade — thrombose gros vaisseaux) et sur la
--     cohérence avec la plaque choriale. À revoir si un témoin contraire apparaît.

BEGIN;

-- ── 1. Les 13 lésions à activer ────────────────────────────────────────────
UPDATE foeto_terms SET viewer_id='abces_decidual',                viewer_level=2, organe='parenchyme' WHERE id='FOETO:PP.PBA-INF-002';
UPDATE foeto_terms SET viewer_id='fibrinoide_plaque_basale',      viewer_level=2, organe='parenchyme' WHERE id='FOETO:PP.PBA-MET-001';
UPDATE foeto_terms SET viewer_id='exces_trophoblaste_evt',        viewer_level=2, organe='parenchyme' WHERE id='FOETO:PP.PBA-MET-003';
UPDATE foeto_terms SET viewer_id='fibrinoide_sous_chorial',       viewer_level=2, organe='parenchyme' WHERE id='FOETO:PP.PCH-MET-001';
UPDATE foeto_terms SET viewer_id='vaisseau_chorial_paroi_epaisse',viewer_level=2, organe='parenchyme' WHERE id='FOETO:PP.PCH-VAS-002';
UPDATE foeto_terms SET viewer_id='asymetrie_paroi_vx_choriaux',   viewer_level=2, organe='parenchyme' WHERE id='FOETO:PP.PCH-VAS-004';
UPDATE foeto_terms SET viewer_id='thrombose_vx_allantochoriaux',  viewer_level=2, organe='parenchyme' WHERE id='FOETO:PP.VAC-VAS-001';
UPDATE foeto_terms SET viewer_id='endovasculite_allantochoriale', viewer_level=2, organe='parenchyme' WHERE id='FOETO:PP.VAC-VAS-002';
UPDATE foeto_terms SET viewer_id='arterite_deciduale',            viewer_level=2, organe='parenchyme' WHERE id='FOETO:PP.AUP-INF-001';
UPDATE foeto_terms SET viewer_id='defaut_remodelage_spiralees',   viewer_level=2, organe='parenchyme' WHERE id='FOETO:PP.AUP-VAS-001';
UPDATE foeto_terms SET viewer_id='thrombose_aup',                 viewer_level=2, organe='parenchyme' WHERE id='FOETO:PP.AUP-VAS-006';

-- Déjà en granularité tissu, il ne leur manquait que viewer_id/viewer_level.
UPDATE foeto_terms SET viewer_id='hemorragie_intravillositaire',  viewer_level=2 WHERE id='FOETO:PP.PAR-VAS-011';
UPDATE foeto_terms SET viewer_id='endovasculite_hemorragique',    viewer_level=2 WHERE id='FOETO:PP.PAR-VAS-004';

-- « stade précoce » est de l'étendue, pas le nom de la lésion.
UPDATE foeto_terms SET label_fr='Endovasculite hémorragique' WHERE id='FOETO:PP.PAR-VAS-004';

-- ── 2. Les 17 à sortir des quick picks ─────────────────────────────────────
-- Anatomie normale : on n'annote pas un normal en raccourci.
UPDATE foeto_terms SET viewer_quick=0 WHERE id IN (
  'FOETO:PP.PBA-NOR-001',   -- Villosités d'ancrage dans la plaque basale
  'FOETO:PP.PCH-NOR-001',   -- Coussinets myxoïdes intimaux des vaisseaux choriaux
  'FOETO:PP.PAR-NOR-007');  -- « Excès de trophoblaste multinucléé » : mal codé NOR, et double PBA-MET-003

-- Doublons de libellé EXACT d'un terme déjà annotable : les activer recréerait
-- la confusion MIR (deux labels identiques dans le menu).
UPDATE foeto_terms SET viewer_quick=0 WHERE id IN (
  'FOETO:PP.PBA-INF-001',   -- = PAR-INF-005 villite_basale
  'FOETO:PP.PBA-VAS-002',   -- = PAR-VAS-017 necrose_fibrinoide_art
  'FOETO:PP.PCH-VAS-001',   -- = PAR-VAS-020 thrombus_plaque_choriale
  'FOETO:PP.PCH-VAS-003');  -- = PAR-VAS-019 thrombose_sous_choriale

-- Reformulations d'un terme déjà annotable.
UPDATE foeto_terms SET viewer_quick=0 WHERE id IN (
  'FOETO:PP.PBA-VAS-001',   -- ≈ PAR-VAS-001 arteriopathie_deciduale
  'FOETO:PP.PBA-MET-002',   -- ≈ PAR-MET-008 vacuolisation_decidues
  'FOETO:PP.PBA-VAS-003',   -- ≈ PAR-VAS-009 hrp
  'FOETO:PP.AUP-VAS-003',   -- ≈ PAR-MET-003 atherose_aigue
  'FOETO:PP.AUP-VAS-004',   -- ≈ PAR-VAS-013 mvm_arteriopathie
  'FOETO:PP.AUP-VAS-005',   -- ≈ PAR-VAS-017 necrose_fibrinoide_art
  'FOETO:PP.AUP-VAS-002',   -- ≈ AUP-VAS-001, deux formulations du même défaut
  'FOETO:PP.VAC-VAS-003',   -- ≈ PCH-VAS-002 ectasie vasculaire choriale
  'FOETO:PP.PCH-INF-001',   -- ≈ PAR-INF-011 mir_s1_par, écrit sans le nom du stade
  'FOETO:PP.PCH-INF-002');  -- ≈ PAR-INF-012 mir_s2_par

-- L'étendue du NIDF est un axe à quantifier, pas deux labels d'annotation.
UPDATE foeto_terms SET viewer_quick=0 WHERE id IN (
  'FOETO:PP.PAR-VAS-022',   -- NIDF — Travées (stade étendu)
  'FOETO:PP.PAR-VAS-027');  -- NIDF — Îlots (stade focal)

COMMIT;
