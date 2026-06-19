# TODO — Amélioration du filtre de négation / normalité dans hpo_extractor.py

## Fichier cible
`/home/mathevet/Bureau/foeto_base/hpo_extractor.py` (361 lignes)

## Problème constaté
Testé sur une vignette de syndrome de Pai. L'extracteur retourne **microcéphalie ET macrocéphalie** alors que le texte dit "le périmètre crânien est dans la norme".

Le système de négation actuel (`_NEGATION_PATTERNS`, lignes 33-45) détecte :
- "pas de", "sans", "absence de", "aucun", "ni", "non retrouvé/observé/..."

Il **ne détecte PAS** :
- "dans la norme" / "dans les normes"
- "de taille normale" / "de volume normal"
- "sans particularité" / "sans anomalie"
- Mesures avec percentiles normaux : "> 10e", "entre 25e et 75e percentile"
- Contexte dimensionnel neutre : "PC mesuré à X (norme pour le terme)"

## Trois axes d'amélioration

### 1. Patterns de normalité (priorité haute)
Ajouter à `_NEGATION_PATTERNS` ou créer un `_NORMALITY_PATTERNS` séparé :
```
dans la norme / dans les normes
de taille normale / de volume normal / de poids normal
sans particularité / sans anomalie / RAS
paraît normal(e) / semble normal(e) / d'aspect normal
norme(s) pour le terme / pour l'âge gestationnel
```
Ces patterns doivent annuler les HPO matchés dans la même phrase/segment.

### 2. Filtre de contradictions mutuellement exclusives (priorité moyenne)
Post-filtre qui élimine les paires impossibles quand les deux sont matchés dans le même texte :
- HP:0000252 (Microcéphalie) ↔ HP:0000256 (Macrocéphalie)
- HP:0001562 (Oligohydramnios) ↔ HP:0001561 (Polyhydramnios)
- HP:0001511 (RCIU) ↔ HP:0001548 (Macrosomie)
- HP:0000347 (Micrognathie) ↔ HP:0000303 (Macrognathie)
- HP:0000568 (Microphtalmie) ↔ HP:0000520 (Macrophtalmie)

Règle : si les deux sont présents, garder celui avec la confidence la plus élevée. Si confidence égale, supprimer les deux.

### 3. Qualificatifs directionnels pour termes dimensionnels (priorité basse)
Certains HPO ne devraient matcher que si un qualificatif de déviation est présent :
- "périmètre crânien" seul ≠ microcéphalie (il faut "diminué", "petit", "< 3e percentile")
- "reins" seul ≠ anomalie rénale (il faut "dilatés", "hyperéchogènes", "kystiques")

Ceci est plus complexe et peut attendre. L'axe 1 + 2 suffit à corriger le cas Pai.

## Fenêtre de négation
Le `_NEGATION_WINDOW` actuel est de 40 caractères avant le match. C'est suffisant pour "pas de X" mais trop court pour "le périmètre crânien est dans la norme" si le match est sur "périmètre crânien" et "dans la norme" est après.

→ Étendre la détection de normalité **aussi après** le match (fenêtre bidirectionnelle de ~60 caractères).

## Structure actuelle du code (repères)
- `_NEGATION_PATTERNS` : lignes 33-45 (regex compilé)
- `_NEGATION_WINDOW` : ligne 45 (= 40)
- `_STOP_WORDS_CLINICAL` : lignes 47-63
- `HPOMatch` dataclass : lignes 67-76
- `_norm()` : lignes 78-84
- `extract()` : ligne 220+ (méthode principale)
- La vérification de négation se fait dans `extract()` en cherchant `_NEGATION_PATTERNS` dans les N chars avant le match

## Test de validation
Après modification, relancer :
```bash
cd /home/mathevet/Bureau/foeto_base
python hpo_extractor.py "Le périmètre crânien est dans la norme. Nez bifide. Fente labiale médiane."
```
Attendu : nez bifide + fente labiale, **PAS** micro/macrocéphalie.
