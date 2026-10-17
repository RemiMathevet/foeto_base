"""Séquences canoniques de dysmorphologie fœtale : PROPOSITIONS d'arêtes « entraine » (plan 2d27053f987e, 349d336f5197).

Liste de départ écrite de mémoire : elle ne prouve rien. Chaque arête n'entre dans le graphe que si un livre la
porte (ancrer_sequences.py cherche la phrase, verbatim contrôlé) ET que Rémi l'a validée (TSV d'arbitrage).
certitude = ce que la littérature courante en dit : « établi » ou « discuté » (mécanisme débattu).

NOEUDS : id -> (libellé fr, motif anglais pour retrouver le nœud dans les livres, insensible à la casse).
ARETES : (séquence, cause, effet, certitude).
Règles (349d336f5197) : séquence = chaîne d'arêtes entraine ; syndrome = nœud cause portant des arêtes entraine
vers ses signes ; association = co-occurrence non orientée, jamais ici.
"""

NOEUDS = {
    # séquence oligoamnios (Potter)
    "agenesie_renale":    ("agénésie rénale", r"renal agenesis|absent kidneys|agenesis of (both|the) kidneys"),
    "dysplasie_renale":   ("dysplasie rénale (kystique)", r"renal dysplasia|dysplastic kidneys?|multicystic dysplastic"),
    "obstacle_urinaire":  ("obstacle urinaire bas (VUP, atrésie urétrale)", r"urethral obstruction|posterior urethral valves?|urethral atresia|lower urinary tract obstruction|bladder outlet obstruction"),
    "rpm":                ("rupture prématurée prolongée des membranes", r"(premature|prolonged|preterm) (premature )?rupture of (the )?membranes|PPROM|chronic (amniotic fluid )?leak"),
    "oligoamnios":        ("oligoamnios / anamnios", r"oligohydramnios|anhydramnios"),
    "hypoplasie_pulm":    ("hypoplasie pulmonaire", r"pulmonary hypoplasia|hypoplastic lungs?|lung hypoplasia|hypoplasia of the lungs?"),
    "facies_potter":      ("faciès de Potter (compression)", r"Potter(.s)? (facies|face|phenotype)|facial compression|flattened nose|compressed face"),
    "deformations_membres": ("déformations des membres (pieds bots, contractures de position)", r"club ?feet|talipes|clubfoot|positional deformit|limb deformit|joint contractures?"),
    "surrenales_discoides": ("surrénales discoïdes (en galette)", r"(discoid|flattened|ovoid|lying.down|pancake).{0,15}adrenals?|adrenals?.{0,40}(discoid|flattened|ovoid)"),
    # obstacle urinaire bas / prune belly
    "megavessie":         ("mégavessie", r"megacystis|distended (urinary )?bladder|bladder distension|dilated bladder|enlarged bladder"),
    "hydronephrose":      ("hydronéphrose / urétérohydronéphrose", r"hydronephrosis|hydroureter|ureterohydronephrosis"),
    "deficit_paroi_abdo": ("déficit de la musculature abdominale (prune belly)", r"prune.belly|(deficien|absen|hypoplas|lack)\w* .{0,25}abdominal (wall )?muscul|abdominal muscle deficiency"),
    "cryptorchidie":      ("cryptorchidie", r"cryptorchidism|undescended test"),
    # akinésie fœtale (FADS, Pena-Shokeir)
    "akinesie":           ("akinésie / hypokinésie fœtale", r"akinesia|hypokinesia|decreased fetal movements?|reduced fetal movements?|lack of fetal movement|fetal immobility"),
    "arthrogrypose":      ("arthrogrypose (contractures multiples)", r"arthrogryposis|multiple (joint )?contractures|multiple congenital contractures"),
    "pterygiums":         ("ptérygiums", r"pterygi(a|um)|webbing (of|across) (the )?joints?"),
    "micrognathie":       ("micrognathie / rétrognathie", r"micrognathia|retrognathia|mandibular hypoplasia|small mandible"),
    "deglutition":        ("défaut de déglutition fœtale", r"(impaired|defective|lack of|absent|reduced|decreased|failure of) (fetal )?swallowing|swallowing (defect|impairment)"),
    "hydramnios":         ("hydramnios / polyhydramnios", r"polyhydramnios|hydramnios"),
    "cordon_court":       ("cordon court", r"short (umbilical )?cord"),
    "rciu":               ("retard de croissance intra-utérin", r"(intrauterine|intra-uterine|fetal) growth (restriction|retardation)|IUGR|growth.restricted"),
    # Pierre Robin
    "glossoptose":        ("glossoptose", r"glossoptosis|posterior(ly)? (displaced|displacement of the) tongue|tongue.{0,25}(posterior|displaced)"),
    "fente_palatine":     ("fente palatine (en U)", r"cleft palate|palatal cleft|cleft of the (soft |hard )?palate"),
    # brides amniotiques
    "rupture_amnios":     ("rupture précoce de l'amnios", r"amnion(ic)? rupture|rupture of the amnion|early amnion rupture"),
    "brides":             ("brides amniotiques", r"amniotic bands?|amniotic band"),
    "amputations":        ("amputations / sillons de constriction", r"amputations?|constriction (rings?|bands?|grooves?)"),
    "fentes_atypiques":   ("fentes faciales atypiques", r"(atypical|oblique|bizarre) (facial )?clefts?"),
    # holoprosencéphalie
    "hpe":                ("holoprosencéphalie", r"holoprosenceph"),
    "face_hpe":           ("anomalies faciales médianes (cyclopie, proboscis, hypotélorisme)", r"cyclopia|proboscis|hypotelorism|median (cleft|facial cleft)|single (central )?(maxillary )?incisor|cebocephaly|ethmocephaly"),
    # défauts de fermeture du tube neural
    "anencephalie":       ("anencéphalie", r"anencephal"),
    "hypoplasie_surren":  ("hypoplasie surrénalienne", r"adrenal hypoplasia|hypoplastic adrenals?|small adrenals?|adrenal glands? (are|were) (small|hypoplastic)"),
    "myelomeningocele":   ("myéloméningocèle / spina bifida", r"myelomeningocele|meningomyelocele|spina bifida"),
    "chiari2":            ("malformation de Chiari II", r"Chiari (II|2|type II|type 2)|Arnold.Chiari|hindbrain herniation"),
    "hydrocephalie":      ("hydrocéphalie", r"hydrocephal"),
    # anasarque
    "anemie_foetale":     ("anémie fœtale (allo-immunisation, parvovirus B19, α-thalassémie)", r"fetal an(a)?emia|alloimmuni[sz]ation|red cell (allo)?immuni[sz]ation|parvovirus|alpha.thalass|hemolytic disease"),
    "ic_haut_debit":      ("insuffisance cardiaque (à haut débit)", r"high.output (cardiac )?failure|(congestive )?(cardiac|heart) failure"),
    "anasarque":          ("anasarque fœto-placentaire", r"hydrops|anasarca"),
    "hem":                ("hématopoïèse extramédullaire / hépatosplénomégalie", r"extramedullary (h(a)?ematopoiesis|erythropoiesis)|hepatosplenomegaly"),
    "epanchement_pleural": ("épanchement pleural / chylothorax", r"pleural effusions?|hydrothorax|chylothorax"),
    "hygroma":            ("hygroma kystique / obstruction lymphatique jugulaire", r"cystic hygroma|nuchal (cystic )?hygroma|jugular lymphatic (obstruction|sacs?)|lymphatic obstruction"),
    "cou_palme":          ("cou palmé / excès de peau nucale", r"webbed neck|webbing of the neck|pterygium colli|redundant (nuchal )?skin|excess (nuchal )?skin"),
    # obstacle digestif, hernie diaphragmatique
    "hdc":                ("hernie diaphragmatique congénitale", r"diaphragmatic hernia"),
    "atresie_oeso":       ("atrésie de l'œsophage", r"(o)?esophageal atresia|tracheo.?(o)?esophageal fistula"),
    "atresie_duod":       ("atrésie / obstruction duodénale", r"duodenal (atresia|obstruction|stenosis)"),
    # jumeaux
    "stt_donneur":        ("transfuseur (syndrome transfuseur-transfusé)", r"donor twin"),
    "stt_receveur":       ("transfusé (syndrome transfuseur-transfusé)", r"recipient twin"),
    # placenta, stress
    "insuff_placentaire": ("insuffisance placentaire / malperfusion vasculaire maternelle", r"(utero)?placental insufficiency|maternal vascular malperfusion|placental malperfusion|uteroplacental (insufficiency|ischemia)"),
    "epargne_cerebrale":  ("épargne cérébrale (rapport cerveau/foie élevé)", r"brain.sparing|brain.(to.)?liver (weight )?ratio|brain:liver"),
    "hypoxie_chronique":  ("hypoxie fœtale chronique", r"chronic (fetal )?hypoxi|chronic intrauterine hypoxi|fetal hypoxi"),
    "erythroblastose":    ("érythroblastose (NRBC circulants)", r"nucleated red (blood )?cells|normoblast(a)?emia|erythroblastosis|NRBC"),
    "stress_foetal":      ("stress fœtal", r"fetal stress|intrauterine stress|stress"),
    "involution_thymique": ("involution thymique (ciel étoilé)", r"thymic involution|involution of the thymus|starry.sky|thymic atrophy|accidental involution"),
    # diabète maternel
    "diabete_maternel":   ("diabète maternel", r"maternal diabetes|diabetic mothers?|infants? of diabetic|diabetes mellitus"),
    "hyperinsulinisme":   ("hyperinsulinisme fœtal / hyperplasie des îlots", r"hyperinsulin|islet (cell )?hyperplasia|hyperplasia of (the )?islets|nesidioblastosis|hypertrophy of (the )?islets"),
    "macrosomie":         ("macrosomie / organomégalie", r"macrosomi|organomegaly|large for gestational age|visceromegaly"),
    "cardiomyopathie_hyp": ("cardiomyopathie hypertrophique (septale)", r"hypertrophic cardiomyopathy|septal hypertrophy|asymmetric septal|cardiomegaly"),
    # cœur
    "obstacle_gauche":    ("obstacle du cœur gauche (sténose / atrésie aortique)", r"aortic (valve )?stenosis|aortic atresia|left (ventricular )?outflow (tract )?obstruction"),
    "hypoplasie_vg":      ("hypoplasie du ventricule gauche", r"hypoplastic left heart|left ventricular hypoplasia|hypoplastic left ventricle"),
    # sirénomélie, crâne
    "vol_vasculaire":     ("vol vasculaire (artère vitelline unique)", r"(persistent )?vitelline artery|vascular steal|single (umbilical|vitelline) artery.{0,40}(aorta|steal)"),
    "sirenomelie":        ("sirénomélie", r"sirenomel"),
    "craniosynostose":    ("craniosynostose (sagittale)", r"craniosynostosis|(sagittal|premature) synostosis"),
    "scaphocephalie":     ("scaphocéphalie / dolichocéphalie", r"scaphoceph|dolichoceph"),
}

ARETES = [
    ("oligoamnios (Potter)", "agenesie_renale", "oligoamnios", "établi"),
    ("oligoamnios (Potter)", "dysplasie_renale", "oligoamnios", "établi"),
    ("oligoamnios (Potter)", "obstacle_urinaire", "oligoamnios", "établi"),
    ("oligoamnios (Potter)", "rpm", "oligoamnios", "établi"),
    ("oligoamnios (Potter)", "oligoamnios", "hypoplasie_pulm", "établi"),
    ("oligoamnios (Potter)", "oligoamnios", "facies_potter", "établi"),
    ("oligoamnios (Potter)", "oligoamnios", "deformations_membres", "établi"),
    ("oligoamnios (Potter)", "agenesie_renale", "surrenales_discoides", "établi"),
    ("obstacle urinaire bas (prune belly)", "obstacle_urinaire", "megavessie", "établi"),
    ("obstacle urinaire bas (prune belly)", "megavessie", "hydronephrose", "établi"),
    ("obstacle urinaire bas (prune belly)", "hydronephrose", "dysplasie_renale", "discuté"),
    ("obstacle urinaire bas (prune belly)", "obstacle_urinaire", "dysplasie_renale", "établi"),
    ("obstacle urinaire bas (prune belly)", "megavessie", "deficit_paroi_abdo", "discuté"),
    ("obstacle urinaire bas (prune belly)", "megavessie", "cryptorchidie", "discuté"),
    ("akinésie fœtale (FADS)", "akinesie", "arthrogrypose", "établi"),
    ("akinésie fœtale (FADS)", "akinesie", "pterygiums", "établi"),
    ("akinésie fœtale (FADS)", "akinesie", "hypoplasie_pulm", "établi"),
    ("akinésie fœtale (FADS)", "akinesie", "micrognathie", "établi"),
    ("akinésie fœtale (FADS)", "akinesie", "deglutition", "établi"),
    ("akinésie fœtale (FADS)", "deglutition", "hydramnios", "établi"),
    ("akinésie fœtale (FADS)", "akinesie", "cordon_court", "établi"),
    ("akinésie fœtale (FADS)", "akinesie", "rciu", "discuté"),
    ("Pierre Robin", "micrognathie", "glossoptose", "établi"),
    ("Pierre Robin", "glossoptose", "fente_palatine", "établi"),
    ("brides amniotiques", "rupture_amnios", "brides", "discuté"),
    ("brides amniotiques", "brides", "amputations", "établi"),
    ("brides amniotiques", "brides", "fentes_atypiques", "établi"),
    ("holoprosencéphalie", "hpe", "face_hpe", "établi"),
    ("anencéphalie", "anencephalie", "hypoplasie_surren", "établi"),
    ("anencéphalie", "anencephalie", "deglutition", "établi"),
    ("myéloméningocèle", "myelomeningocele", "chiari2", "établi"),
    ("myéloméningocèle", "chiari2", "hydrocephalie", "établi"),
    ("myéloméningocèle", "myelomeningocele", "deformations_membres", "établi"),
    ("anasarque", "anemie_foetale", "ic_haut_debit", "établi"),
    ("anasarque", "ic_haut_debit", "anasarque", "établi"),
    ("anasarque", "anemie_foetale", "hem", "établi"),
    ("anasarque", "epanchement_pleural", "hypoplasie_pulm", "établi"),
    ("obstruction lymphatique jugulaire", "hygroma", "anasarque", "établi"),
    ("obstruction lymphatique jugulaire", "hygroma", "cou_palme", "établi"),
    ("hernie diaphragmatique", "hdc", "hypoplasie_pulm", "établi"),
    ("hernie diaphragmatique", "hdc", "hydramnios", "discuté"),
    ("obstacle digestif haut", "atresie_oeso", "hydramnios", "établi"),
    ("obstacle digestif haut", "atresie_duod", "hydramnios", "établi"),
    ("transfuseur-transfusé", "stt_donneur", "oligoamnios", "établi"),
    ("transfuseur-transfusé", "stt_receveur", "hydramnios", "établi"),
    ("transfuseur-transfusé", "stt_receveur", "anasarque", "établi"),
    ("transfuseur-transfusé", "stt_donneur", "rciu", "établi"),
    ("insuffisance placentaire", "insuff_placentaire", "rciu", "établi"),
    ("insuffisance placentaire", "insuff_placentaire", "oligoamnios", "établi"),
    ("insuffisance placentaire", "rciu", "epargne_cerebrale", "établi"),
    ("insuffisance placentaire", "insuff_placentaire", "hypoxie_chronique", "établi"),
    ("insuffisance placentaire", "hypoxie_chronique", "erythroblastose", "établi"),
    ("stress fœtal", "stress_foetal", "involution_thymique", "établi"),
    ("diabète maternel", "diabete_maternel", "hyperinsulinisme", "établi"),
    ("diabète maternel", "hyperinsulinisme", "macrosomie", "établi"),
    ("diabète maternel", "diabete_maternel", "cardiomyopathie_hyp", "établi"),
    ("cœur gauche (« no flow, no grow »)", "obstacle_gauche", "hypoplasie_vg", "discuté"),
    ("sirénomélie", "vol_vasculaire", "sirenomelie", "discuté"),
    ("sirénomélie", "sirenomelie", "agenesie_renale", "établi"),
    ("craniosynostose", "craniosynostose", "scaphocephalie", "établi"),
]


def _check():
    import re
    ids = set(NOEUDS)
    for s, a, b, c in ARETES:
        assert a in ids and b in ids and c in ("établi", "discuté"), (s, a, b, c)
    for k, (_, m) in NOEUDS.items():
        re.compile(m, re.I)
    # acyclicité (Kahn) : la liste de départ doit déjà être un DAG
    succ = {k: set() for k in ids}
    deg = {k: 0 for k in ids}
    for _, a, b, _ in ARETES:
        if b not in succ[a]:
            succ[a].add(b); deg[b] += 1
    file = [k for k in ids if deg[k] == 0]
    vus = 0
    while file:
        k = file.pop(); vus += 1
        for v in succ[k]:
            deg[v] -= 1
            if deg[v] == 0:
                file.append(v)
    assert vus == len(ids), "cycle dans les séquences"
    return len(NOEUDS), len(ARETES)


if __name__ == "__main__":
    print("%d nœuds, %d arêtes, DAG OK" % _check())
