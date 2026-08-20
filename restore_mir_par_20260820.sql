-- Restauration des 4 termes MIR/RIF « versant parenchyme » supprimés le 2026-08-06.
--
-- Ils avaient été emportés par l'arbitrage « stade et grade = axes orthogonaux »
-- (décision PREFECT 9a403d380374, 12 termes supprimés) alors qu'ils ne sont PAS
-- des termes-grades : ce sont les stades lus sur la coupe de parenchyme, jumeaux
-- documentés des termes membranes/cordon. Leur label_fr est identique à celui du
-- jumeau, mais leur description_fr porte un critère histologique propre.
--
-- 48 annotations (55 lames) pointaient ces ids et étaient silencieusement
-- absentes des CR générés (services/lumi.py:406 fait `continue` sur id non résolu).
--
-- Source : syndromes_foetaux.db.bak_amsterdam_20260806 (schéma identique, vérifié).

ATTACH 'file:syndromes_foetaux.db.bak_amsterdam_20260806?mode=ro' AS b;

BEGIN;

-- 1. Les 4 termes, copiés à l'identique depuis le backup.
INSERT INTO foeto_terms
SELECT * FROM b.foeto_terms
WHERE id IN ('FOETO:PP.PAR-INF-011','FOETO:PP.PAR-INF-012',
             'FOETO:PP.PAR-INF-013','FOETO:PP.PAR-INF-016');

-- 2. Leurs segments d'annotation (plaque_choriale). fir_s1_par n'en avait aucun.
INSERT OR IGNORE INTO foeto_term_segments
SELECT * FROM b.foeto_term_segments
WHERE foeto_id IN ('FOETO:PP.PAR-INF-011','FOETO:PP.PAR-INF-012',
                   'FOETO:PP.PAR-INF-013','FOETO:PP.PAR-INF-016');

-- 3. cr_description des 3 MIR : le texte hérité du jumeau membranes parlait de la
--    décidue, qui n'est pas ce que l'on lit sur la coupe de parenchyme. Réécrit sur
--    le versant plaque choriale, conformément à leur propre description_fr et à leur
--    cr_section (cr_plaque_choriale). fir_s1_par est laissé tel quel : déjà correct.
UPDATE foeto_terms SET cr_description =
  'On note un afflux de polynucléaires neutrophiles maternels au toit de la chambre '
  || 'intervilleuse, englués dans la fibrine sous-choriale, sans franchissement du tissu '
  || 'conjonctif de la plaque choriale (MIR stade 1, versant plaque choriale).'
WHERE id = 'FOETO:PP.PAR-INF-011';

UPDATE foeto_terms SET cr_description =
  'On note un afflux de polynucléaires neutrophiles maternels franchissant la fibrine '
  || 'sous-choriale et infiltrant le tissu conjonctif de la plaque choriale, voire l''amnios '
  || 'sus-jacent, sans nécrose amniotique (MIR stade 2, versant plaque choriale).'
WHERE id = 'FOETO:PP.PAR-INF-012';

UPDATE foeto_terms SET cr_description =
  'On note un infiltrat à polynucléaires neutrophiles de la plaque choriale avec nécrose '
  || 'de l''épithélium amniotique, karyorrhexis et débris amniotiques (MIR stade 3, versant '
  || 'plaque choriale).'
WHERE id = 'FOETO:PP.PAR-INF-013';

COMMIT;
