#!/usr/bin/env python3
"""Rattache aux familles EXISTANTES les syndromes ajoutes apres leur construction.

phase2_families (build_hpo_families_spectrum.py) DROPPE et renumerote les
familles, et ne lit que relevance='haute' : on ne la relance pas — les FAM:xxxx
sont references par syndrome_foeto_livres et extract_micro_livres.FAMILLES.
Ici : memes FAMILY_PATTERNS (methode 1, name_fr + name_en, confiance 0,9),
memes voies geniques (methode 2, 0,8) si syndrome_genes les connait, sur les
syndromes qui ne sont dans aucune famille. Insere, met n_members a jour.

Usage : python3 add_family_members.py [--tous]   (defaut : aliases like 'livre:%')
"""
import argparse
import re
import sqlite3
from collections import defaultdict

from build_hpo_families_spectrum import FAMILY_PATTERNS, GENE_PATHWAYS

DB = "/home/mathevet/Bureau/foeto_base/syndromes_foetaux.db"
PATHWAY_TO_FAMILY = {
    "RAS/MAPK": "RASopathies", "FGFR": "Craniosynostoses syndromiques", "Collagène_I": "Collagénopathies",
    "Collagène_II": "Collagénopathies", "Collagène_XI": "Collagénopathies", "Collagène_IX": "Collagénopathies",
    "Cohésine": "Cohesinopathies", "Rett": "Syndromes de Rett et apparentés", "Peroxysome": "Troubles du spectre Zellweger",
    "Dystroglycanopathie": "Dystroglycanopathies", "Tubuline": "Tubulinopathies", "BBS/Ciliopathie": "Ciliopathies",
    "Ciliopathie": "Ciliopathies", "Laminopathie": "Laminopathies", "Craniosynostose": "Craniosynostoses syndromiques",
}


# familles absentes de phase2, creees ici si besoin (Remi, 2026-09-12) : patterns sur
# name_fr + name_en, genes causaux ; on balaie TOUS les syndromes pour celles-la
EXTRA_FAMILIES = {
    "Troubles du spectre Zellweger (peroxysomes)": {
        "patterns": [r"zellweger", r"adr[ée]noleu[ck]odystroph.*(n[ée]onatal|neonatal)", r"refsum.*infant", r"peroxisom",
                     r"peroxysom", r"rhizomelic chondrodysplasia punctata", r"chondrodysplasi.*punctata.*rhizom",
                     r"bifunctional", r"acyl.coa oxidase", r"heimler"],
        "genes": ["PEX1", "PEX2", "PEX3", "PEX5", "PEX6", "PEX7", "PEX10", "PEX11B", "PEX12", "PEX13", "PEX14", "PEX16",
                  "PEX19", "PEX26", "GNPAT", "AGPS", "HSD17B4", "ACOX1", "SCP2", "FAR1"]},
    "Fibrillinopathies et syndromes marfanoïdes": {
        "patterns": [r"marfan", r"arachnodactyl", r"loeys.dietz", r"shprintzen.goldberg", r"weill.marchesani"],
        "genes": ["FBN1", "FBN2", "TGFBR1", "TGFBR2", "SMAD3", "TGFB2", "TGFB3", "SKI"]},
    "Ostéochondromatoses et enchondromatoses": {
        "patterns": [r"exostos", r"ost[ée]ochondrom", r"enchondromat", r"ollier", r"maffucci", r"m[ée]tachondromat"],
        "genes": ["EXT1", "EXT2"]},
    "Alagille et cholangiopathies syndromiques": {
        "patterns": [r"alagille", r"art[ée]rioh[ée]pati", r"paucit.*bili", r"pauvret.*bili"],
        "genes": ["JAG1", "NOTCH2"]},
    "Ossifications hétérotopiques (FOP, POH)": {
        "patterns": [r"fibrodysplasi.*ossificans", r"ossificans progressiva", r"h[ée]t[ée]roplasi.*osseuse", r"osseous heteroplasia", r"ossification h[ée]t[ée]rotopique"],
        "genes": ["ACVR1"]},
}


# un gene partage n'est pas une appartenance : JAG1 met la tetralogie de Fallot chez
# Alagille, SKI met la deletion 1p36 chez les marfanoides (Remi, 2026-09-12)
FAMILLES_PAR_SIGNE = {"Hydrops fetalis non immun": "HP:0001789"}

EXCLUS = {("Alagille et cholangiopathies syndromiques", "ORPHA:3303"),
          ("Fibrillinopathies et syndromes marfanoïdes", "ORPHA:1606"),
          # 2026-09-13 : membres attestes sans AUCUN voisin de parente dans leur famille, relus
          ("Collagénopathies", "ORPHA:899"),                # Walker-Warburg = dystroglycanopathie
          ("Collagénopathies", "ORPHA:90636"),              # surdite DFNB : cluster de genes, pas une entite
          ("Dysplasies ectodermiques", "ORPHA:90636"),
          ("Ichtyoses congénitales", "ORPHA:90636"),
          ("Craniosynostoses syndromiques", "ORPHA:2363"),  # LADD : FGFR2 sans craniosynostose
          ("Craniosynostoses syndromiques", "ORPHA:2396"),  # lipomatose encephalo-cranio-cutanee (FGFR1)
          ("Craniosynostoses syndromiques", "ORPHA:2645"),  # dysplasie osteoglophonique (FGFR1)
          ("Holoprosencéphalies", "ORPHA:2396"),
          ("Holoprosencéphalies", "ORPHA:2645"),
          ("Holoprosencéphalies", "ORPHA:988"),             # hemimelie tibiale : cluster SHH/LMBR1
          ("Glycosylation (CDG)", "ORPHA:2059"),            # Fryns
          ("Glycosylation (CDG)", "ORPHA:293181"),          # epilepsie a crises migrantes
          ("Mucopolysaccharidoses", "ORPHA:349"),           # fucosidose = oligosaccharidose
          ("Mucopolysaccharidoses", "ORPHA:93"),            # aspartylglucosaminurie, idem
          ("RASopathies", "ORPHA:93270"),                   # Saldino-NOONAN : le motif « noonan »
          ("Syndromes de surcroissance", "ORPHA:85173"),    # IMAGe = RCIU, l'inverse
          ("Tubulinopathies", "ORPHA:2995"),                # Baraitser-Winter = actinopathie
          ("Tubulinopathies", "ORPHA:60040"),               # MCAP = PIK3CA, reste en surcroissance
          ("Épidermolyses bulleuses", "ORPHA:314381")}      # HSAN 6


# familles EXISTANTES dont phase2 ne connaissait qu'une partie des membres : patterns
# et genes ajoutes, appliques a toute la base (Remi, 2026-09-13 : « Ciliopathies, 3 membres »)
# Spranger : quel groupe du livre correspond a quelle famille de la base — les entites
# Spranger « N.x » de ces groupes entrent dans la famille (0,85). Les autres groupes
# (FGFR3, metaphysaires, SEMD, diastrophique, filamines, ponctuees, rhizomeliques,
# acromesomeliques, mineralisation, os denses, osteolyses, dysostoses…) restent des
# groupes Spranger : ce sont des familles squelettiques sans equivalent dans la base.
SPRANGER_EQUIV = {4: "Collagénopathies", 14: "Collagénopathies", 11: "Ciliopathies", 5: "Mucopolysaccharidoses",
                  23: "Craniosynostoses syndromiques", 22: "Syndromes de surcroissance"}

ENRICHIR = {
    "RASopathies": {
        "patterns": [r"noonan", r"costello", r"cardio.?facio.?cutan", r"\bcfc\b", r"legius", r"leopard", r"lentigines",
                     r"neurofibromatos.*1", r"rasopath", r"capillary malformation.arteriovenous", r"mazzanti"],
        "genes": ["PTPN11", "SOS1", "SOS2", "RAF1", "KRAS", "HRAS", "NRAS", "BRAF", "MAP2K1", "MAP2K2", "RIT1", "SHOC2",
                  "CBL", "NF1", "SPRED1", "LZTR1", "RRAS", "MRAS", "RASA1", "RASA2", "PPP1CB", "A2ML1"]},
    "Collagénopathies": {
        "patterns": [r"ost[ée]ogen[eè]s[ei]s? imperf", r"ehlers.danlos", r"stickler", r"marshall\b", r"kniest",
                     r"spondylo.?[ée]piphys.*cong", r"hypochondrogen", r"achondrogen.*(2|ii|type 2)", r"collag[eé]n",
                     r"spondyloperipheral", r"caffey", r"bruck", r"cole.carpenter", r"osteoporosis.pseudoglioma",
                     r"torrance", r"czech dysplasia", r"fibrochondrogen", r"weissenbacher", r"otospondylomegaepiphys"],
        "genes": ["COL1A1", "COL1A2", "COL2A1", "COL3A1", "COL5A1", "COL5A2", "COL9A1", "COL9A2", "COL9A3", "COL11A1",
                  "COL11A2", "COL27A1", "COL12A1", "PLOD1", "PLOD2", "CRTAP", "P3H1", "PPIB", "SERPINF1", "SERPINH1",
                  "FKBP10", "BMP1", "IFITM5", "SP7", "WNT1", "TMEM38B", "CREB3L1", "ADAMTS2", "TNXB", "FKBP14", "CHST14",
                  "DSE", "B4GALT7", "B3GALT6", "SLC39A13", "ZNF469", "PRDM5"]},
    "Dystroglycanopathies": {
        "patterns": [r"walker.warburg", r"muscle.eye.brain", r"fukuyama", r"dystroglycan", r"\bmeb\b",
                     r"cobblestone", r"muscular dystrophy.dystroglycanopathy", r"dystrophie musculaire.*(congénitale|dystroglycan)"],
        "genes": ["POMT1", "POMT2", "POMGNT1", "POMGNT2", "FKTN", "FKRP", "LARGE1", "CRPPA", "ISPD", "B3GALNT2", "POMK",
                  "GMPPB", "DAG1", "RXYLT1", "TMEM5", "B4GAT1", "DPM1", "DPM2", "DPM3", "DOLK"]},
    "Cohesinopathies": {
        "patterns": [r"cornelia.de.lange", r"brachmann", r"de lange", r"roberts\b", r"\bsc phocomelia", r"coh[ée]sinopath",
                     r"warsaw breakage", r"chops"],
        "genes": ["NIPBL", "SMC1A", "SMC3", "RAD21", "HDAC8", "BRD4", "ANKRD11", "ESCO2", "DDX11", "AFF4"]},
    "Craniosynostoses syndromiques": {
        "patterns": [r"apert", r"crouzon", r"pfeiffer", r"muenke", r"saethre.chotzen", r"craniosynostos", r"cranios[ty][ée]nose",
                     r"carpenter", r"antley.bixler", r"jackson.weiss", r"beare.stevenson", r"baller.gerold",
                     r"craniofrontonasal", r"shprintzen.goldberg", r"kleeblattsch", r"cloverleaf"],
        "genes": ["FGFR1", "FGFR2", "FGFR3", "TWIST1", "EFNB1", "MSX2", "ERF", "TCF12", "ZIC1", "IL11RA", "RAB23",
                  "POR", "RECQL4", "ALX4", "SKI", "MEGF8"]},
    "Tubulinopathies": {
        "patterns": [r"tubulinopath", r"lissenc[ée]phal", r"polymicrogyri", r"pachygyri", r"double.cortex",
                     r"miller.dieker", r"subcortical band heterotopia", r"h[ée]t[ée]rotopie.*(bande|laminaire)"],
        "genes": ["TUBA1A", "TUBB2A", "TUBB2B", "TUBB3", "TUBB", "TUBG1", "TUBA8", "PAFAH1B1", "DCX", "ARX", "RELN",
                  "VLDLR", "KIF2A", "KIF5C", "DYNC1H1", "CDK5", "ACTB", "ACTG1", "WDR62", "GPR56", "ADGRG1"]},
    "Laminopathies": {
        "patterns": [r"laminopath", r"progeri", r"hutchinson.gilford", r"emery.dreifuss", r"mandibuloacral",
                     r"restrictive dermopathy", r"dermopathie restrictive", r"wiedemann.rautenstrauch"],
        "genes": ["LMNA", "ZMPSTE24", "LMNB1", "LMNB2", "EMD", "BANF1", "POLR3A"]},
    "Dysplasies ectodermiques": {
        "patterns": [r"ectoderm", r"hypohidrotic", r"anhidrotic", r"clouston", r"rapp.hodgkin", r"hay.wells",
                     r"ankyloblepharon", r"\beec\b", r"ectrodactyly.ectodermal", r"tricho.dento.oss", r"witkop",
                     r"incontinentia pigmenti", r"goltz", r"focal dermal hypoplasia", r"pachyonychia"],
        "genes": ["EDA", "EDAR", "EDARADD", "WNT10A", "TP63", "GJB6", "GJB2", "IKBKG", "PORCN", "NECTIN1", "PVRL1",
                  "DLX3", "MSX1", "KRT6A", "KRT16", "KRT17", "TRAF6", "NFKBIA"]},
    "Holoprosencéphalies": {
        "patterns": [r"holoprosenc", r"cyclop", r"ethmocephal", r"cebocephal", r"holoprosencéphal", r"septo.?optic"],
        "genes": ["SHH", "ZIC2", "SIX3", "TGIF1", "GLI2", "FGF8", "PTCH1", "CDON", "DISP1", "FOXH1", "DLL1", "NODAL",
                  "GAS1", "TDGF1", "STIL", "PLCH1", "FGFR1"]},
    "Syndromes de surcroissance": {
        "patterns": [r"beckwith.wiedemann", r"sotos", r"weaver\b", r"simpson.golabi", r"perlman", r"surcroissance",
                     r"overgrowth", r"malan", r"tatton.brown", r"marshall.smith", r"macrocephaly.capillary",
                     r"megalencephaly", r"m[ée]gal.?enc[ée]phal", r"proteus", r"pten hamartoma", r"bannayan",
                     r"cowden", r"nevo", r"costello", r"luscan.lumish", r"tenorio", r"kagami.ogata"],
        "genes": ["NSD1", "EZH2", "GPC3", "GPC4", "DIS3L2",
                  "NFIX", "DNMT3A", "PIK3CA", "AKT1", "AKT3", "PTEN", "CDKN1C", "H19", "KCNQ1OT1", "IGF2", "CHD8",
                  "SETD2", "PPP2R5D", "RNF125", "MTOR", "PIK3R2", "CCND2", "SUZ12", "EED", "HIST1H1E"]},
    "Trisomies et aneuploïdies": {
        "patterns": [r"trisom", r"monosom", r"triploid", r"tetrasom", r"pentasom", r"klinefelter", r"turner",
                     r"\bxyy\b", r"\bxxy\b", r"\bxxx\b", r"mosa[iï]", r"aneuploid", r"down\b", r"edwards\b", r"patau",
                     r"cat.eye", r"pallister.killian", r"isochromosom", r"\b4[57],x"],
        "genes": []},
    "Syndromes microdélétionnels": {
        "patterns": [r"micro.?d[ée]l[ée]tion", r"micro.?dupli", r"d[ée]l[ée]tion\s*\d+[pq]", r"dupli[ck]ation\s*\d+[pq]",
                     r"\b\d{1,2}[pq]\d+(\.\d+)?\b", r"monosom.*\d+[pq]", r"williams", r"digeorge", r"velo.?cardio",
                     r"smith.magenis", r"wolf.hirschhorn", r"cri.du.chat", r"angelman", r"prader.willi", r"miller.dieker",
                     r"langer.giedion", r"potocki", r"phelan.mcdermid", r"jacobsen", r"koolen", r"kleefstra", r"wagr\b",
                     r"rubinstein.taybi", r"subtelomer", r"contiguous gene", r"recurrent deletion", r"recurrent duplication"],
        "genes": []},
    "Hydrops fetalis non immun": {
        "patterns": [r"hydrops", r"anasarque", r"non.?immune hydrops"],
        "genes": []},
    "Arthrogryposes": {
        "patterns": [r"arthrogrypos", r"akin[ée]si", r"contractures?\b.*(cong[ée]nital|multiple)", r"pterygium",
                     r"pena.shokeir", r"amyoplasi", r"freeman.sheldon", r"sheldon.hall", r"escobar", r"gordon\b",
                     r"marden.walker", r"beals\b", r"contractural arachnodactyly", r"neu.laxova", r"lethal congenital contracture"],
        "genes": ["MYH3", "MYH8", "TNNI2", "TNNT3", "TPM2", "MYBPC1", "ECEL1", "RAPSN", "CHRNG", "CHRNA1", "CHRND",
                  "CHRNB1", "DOK7", "MUSK", "NEB", "PIEZO2", "FBN2", "GLE1", "ERBB3", "CNTNAP1", "ADCY6", "LGI4",
                  "MYMK", "KLHL40", "KLHL41", "RYR1", "NALCN", "SCN4A", "ZC4H2", "TOR1A"]},
    "Fanconi et instabilité chromosomique": {
        "patterns": [r"fanconi an", r"bloom\b", r"instabilit[ée].*chromosom", r"ataxi.*t[ée]langiectas", r"nijmegen",
                     r"chromosome breakage", r"cassure", r"rothmund", r"werner\b", r"dyskeratosis", r"seckel", r"ligase iv"],
        "genes": ["FANCA", "FANCB", "FANCC", "FANCD2", "FANCE", "FANCF", "FANCG", "FANCI", "FANCL", "FANCM", "BRCA2",
                  "BRIP1", "PALB2", "RAD51C", "SLX4", "ERCC4", "XRCC2", "UBE2T", "BLM", "ATM", "NBN", "RECQL4",
                  "WRN", "LIG4", "ATR", "DKC1"]},
    "Ichtyoses congénitales": {
        "patterns": [r"ichthyos", r"ichtyos", r"harlequin", r"arlequin", r"collodion", r"[ée]rythrodermi.*(cong|ichtyo)",
                     r"netherton", r"sj[oö]gren.larsson", r"conradi.h[uü]nermann", r"\bkid\b", r"keratitis.ichthyosis"],
        "genes": ["ABCA12", "TGM1", "ALOX12B", "ALOXE3", "NIPAL4", "CYP4F22", "KRT1", "KRT10", "KRT2", "SPINK5", "ALDH3A2",
                  "EBP", "GJB2", "ST14", "CERS3", "PNPLA1", "SDR9C7", "SULT2B1", "LIPN", "CASP14", "SLC27A4", "ABHD5"]},
    "Épidermolyses bulleuses": {
        "patterns": [r"epidermolysis bullosa", r"[ée]pidermolyse bulleuse", r"kindler", r"herlitz", r"dowling.meara",
                     r"bart\b", r"pyloric atresia.*epidermolysis", r"aplasia cutis"],
        "genes": ["COL7A1", "LAMA3", "LAMB3", "LAMC2", "KRT5", "KRT14", "ITGB4", "ITGA6", "PLEC", "COL17A1", "DST",
                  "EXPH5", "FERMT1", "KLHL24", "TGM5", "ITGA3", "CD151", "DSP", "JUP", "PKP1"]},
    "Glycosylation (CDG)": {
        "patterns": [r"\bcdg\b", r"glycosylation", r"pmm2", r"cdg[- ]?[i1]", r"congenital disorder of glycosylation"],
        "genes": ["PMM2", "MPI", "ALG1", "ALG2", "ALG3", "ALG6", "ALG8", "ALG9", "ALG11", "ALG12", "ALG13", "DPAGT1",
                  "SRD5A3", "DOLK", "DPM1", "DPM2", "DPM3", "MGAT2", "SLC35A2", "SLC35C1", "COG1", "COG4", "COG5", "COG6",
                  "COG7", "COG8", "TMEM165", "ATP6V0A2", "PGM1", "B4GALT1", "NANS", "GFPT1", "SLC35A1", "RFT1", "PIGA",
                  "PIGN", "PIGV", "PIGO", "PGAP2", "PGAP3"]},
    "Syndromes de Rett et apparentés": {
        "patterns": [r"\brett\b", r"mecp2", r"cdkl5", r"foxg1", r"pitt.hopkins", r"angelman"],
        "genes": ["MECP2", "CDKL5", "FOXG1", "TCF4", "UBE3A", "STXBP1", "MEF2C", "IQSEC2", "WDR45", "SLC9A6"]},
    "Troubles du spectre Zellweger": {
        "patterns": [r"zellweger", r"adr[ée]noleu[ck]odystroph.*(n[ée]onatal|neonatal)", r"refsum.*infant", r"peroxisom",
                     r"peroxysom", r"rhizomelic chondrodysplasia punctata", r"chondrodysplasi.*punctata.*rhizom",
                     r"bifunctional", r"acyl.coa oxidase", r"heimler"],
        "genes": ["PEX1", "PEX2", "PEX3", "PEX5", "PEX6", "PEX7", "PEX10", "PEX11B", "PEX12", "PEX13", "PEX14", "PEX16",
                  "PEX19", "PEX26", "GNPAT", "AGPS", "HSD17B4", "ACOX1", "SCP2", "ABCD1", "FAR1", "PEX14"]},
    "Mucopolysaccharidoses": {
        "patterns": [r"mucopolysacchar", r"hurler", r"hunter\b", r"sanfilippo", r"morquio", r"maroteaux.lamy", r"\bsly\b",
                     r"scheie", r"natowicz", r"\bmps\b", r"oligosacchar", r"mucolipidos", r"i.cell", r"sialidos",
                     r"fucosidos", r"mannosidos", r"aspartylglucosamin", r"galactosialidos", r"dysostosis multiplex"],
        "genes": ["IDUA", "IDS", "SGSH", "NAGLU", "HGSNAT", "GNS", "GALNS", "GLB1", "ARSB", "GUSB", "HYAL1", "GNPTAB",
                  "GNPTG", "MCOLN1", "NEU1", "FUCA1", "MAN2B1", "MANBA", "AGA", "CTSA"]},
    "Ciliopathies": {
        "patterns": [r"jeune", r"asphyxiating thoracic", r"thoracique asphyxiante", r"short.rib", r"côtes courtes",
                     r"ellis.van.creveld", r"chondroectodermal", r"or[ao].?faci[ao].?digital", r"senior.l[oø]ken",
                     r"nephronophthisis", r"n[ée]phronophtise", r"sensenbrenner", r"cranioectodermal",
                     r"mainzer.saldino", r"hydrolethalus", r"alstr[oö]m", r"acrocallosal", r"joubert", r"meckel",
                     r"bardet.biedl", r"mckusick.kaufman", r"ciliopath"],
        "genes": ["IFT80", "IFT172", "IFT140", "DYNC2H1", "WDR34", "WDR60", "NEK1", "TTC21B", "EVC", "EVC2",
                  "OFD1", "NPHP1", "NPHP3", "NPHP4", "CEP290", "TMEM67", "RPGRIP1L", "CC2D2A", "MKS1", "TMEM216",
                  "B9D1", "B9D2", "TCTN1", "TCTN2", "TCTN3", "KIF7", "INPP5E", "ARL13B", "AHI1", "BBS1", "BBS2",
                  "BBS4", "BBS10", "BBS12", "WDR19", "WDR35", "IFT122", "IFT43", "TTC8", "HYLS1", "ALMS1"]},
}


def creer_familles(c):
    """cree les EXTRA_FAMILIES manquantes et y rattache tous les syndromes de la base ;
    enrichit les familles ENRICHIR sur toute la base"""
    fam_id = {n: f for f, n in c.execute("select family_id, family_name from syndrome_families")}
    genes = defaultdict(set)
    for sid, g in c.execute("select syndrome_id, gene_symbol from syndrome_genes where role='causal'"):
        genes[sid].add(g)
    tous = c.execute("select id, name_fr, name_en from syndromes").fetchall()
    for fname, spec in ENRICHIR.items():
        if fname not in fam_id:
            continue
        n = 0
        for sid, fr, en in tous:
            nom = f"{fr or ''} {en or ''}".lower()
            conf = 0.9 if any(re.search(p, nom, re.I) for p in spec["patterns"]) else \
                   0.8 if genes.get(sid, set()) & set(spec["genes"]) else None
            if conf:
                n += c.execute("insert or ignore into syndrome_family_members values(?,?,?)", (fam_id[fname], sid, conf)).rowcount
        print(f"  {fam_id[fname]} {fname} : +{n} membres")
    # groupes Spranger equivalents : les entites « N.x » avec ORPHA entrent dans la famille
    for grp, fname in SPRANGER_EQUIV.items():
        if fname not in fam_id:
            continue
        n = 0
        for (sid,) in c.execute("""select distinct syndrome_id from syndrome_hpo_livres where livre='spranger_entites'
                                   and syndrome_id is not null and syndrome_titre like ?""", (f"{grp}.%",)):
            n += c.execute("insert or ignore into syndrome_family_members values(?,?,?)", (fam_id[fname], sid, 0.85)).rowcount
        if n:
            print(f"  {fam_id[fname]} {fname} : +{n} membres du groupe Spranger {grp}")
    c.execute("update syndrome_families set n_members = (select count(*) from syndrome_family_members m where m.family_id = syndrome_families.family_id)")
    creer_familles_extra(c, fam_id, genes, tous)


def creer_familles_extra(c, fam_id, genes, tous):
    """cree les EXTRA_FAMILIES manquantes et y rattache tous les syndromes de la base"""
    nxt = 1 + max(int(f.split(":")[1]) for f in fam_id.values())
    for fname, spec in EXTRA_FAMILIES.items():
        if fname not in fam_id:
            fid = f"FAM:{nxt:04d}"; nxt += 1
            c.execute("insert into syndrome_families values(?,?,?,?,?)", (fid, fname, None, "name_pattern", 0))
            fam_id[fname] = fid
        fid = fam_id[fname]
        n = 0
        for sid, fr, en in tous:
            nom = f"{fr or ''} {en or ''}".lower()
            conf = 0.9 if any(re.search(p, nom, re.I) for p in spec["patterns"]) else \
                   0.8 if genes.get(sid, set()) & set(spec["genes"]) else None
            if conf and (fname, sid) not in EXCLUS:
                c.execute("insert or ignore into syndrome_family_members values(?,?,?)", (fid, sid, conf)); n += 1
        print(f"  {fid} {fname} : {n} membres")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tous", action="store_true", help="tous les syndromes sans famille, pas seulement ceux des livres")
    ap.add_argument("--livres", action="store_true", help="tout syndrome rattache a une entree de livre (syndrome_hpo_livres)")
    ap.add_argument("--creer", action="store_true", help="cree les EXTRA_FAMILIES manquantes et les peuple sur toute la base")
    a = ap.parse_args()
    c = sqlite3.connect(DB)
    if a.creer:
        creer_familles(c)
    fam_id = {n: f for f, n in c.execute("select family_id, family_name from syndrome_families")}
    for fname, sid in EXCLUS:                       # une exclusion vaut aussi pour l'existant
        if fname in fam_id:
            c.execute("delete from syndrome_family_members where family_id=? and syndrome_id=?", (fam_id[fname], sid))
    c.commit()
    deja = {r[0] for r in c.execute("select distinct syndrome_id from syndrome_family_members")}
    where = "" if a.tous else ("where id in (select syndrome_id from syndrome_hpo_livres)" if a.livres else "where aliases like 'livre:%'")
    cibles = [r for r in c.execute(f"select id, name_fr, name_en from syndromes {where}") if r[0] not in deja]
    genes = defaultdict(set)
    for sid, g in c.execute("select syndrome_id, gene_symbol from syndrome_genes where role='causal'"):
        genes[sid].add(g)
    n = 0
    for sid, fr, en in cibles:
        nom = f"{fr or ''} {en or ''}".lower()
        for fname, pats in FAMILY_PATTERNS.items():
            if fname in fam_id and any(re.search(p, nom, re.I) for p in pats):
                c.execute("insert or ignore into syndrome_family_members values(?,?,?)", (fam_id[fname], sid, 0.9)); n += 1
                print(f"  {sid} {en or fr} -> {fname}")
        for g in genes.get(sid, ()):
            fname = PATHWAY_TO_FAMILY.get(GENE_PATHWAYS.get(g, ""))
            if fname in fam_id:
                c.execute("insert or ignore into syndrome_family_members values(?,?,?)", (fam_id[fname], sid, 0.8)); n += 1
                print(f"  {sid} {en or fr} -> {fname} (gène {g})")
    # familles de PRESENTATION : « Hydrops fetalis non immun » n'avait que les entites
    # hydrops elles-memes, aucun membre atteste. Ses membres sont les syndromes ou un
    # livre atteste l'anasarque (HP:0001789 et descendants, est_parent=0) — le
    # differentiel de l'anasarque au foetopathologiste, confiance 0.7
    for fname, hpo in FAMILLES_PAR_SIGNE.items():
        if fname in fam_id:
            k = 0
            for sid, in c.execute("""select distinct syndrome_id from syndrome_hpo_livres where syndrome_id is not null and est_parent=0
                                     and (hpo_id=? or hpo_id in (select hpo_id from hpo_ancestors where ancestor_id=?))""", (hpo, hpo)):
                k += c.execute("insert or ignore into syndrome_family_members values(?,?,?)", (fam_id[fname], sid, 0.7)).rowcount
            print(f"  {fname} : {k} membres attestés par le signe {hpo}")
    c.execute("update syndrome_families set n_members = (select count(*) from syndrome_family_members m where m.family_id = syndrome_families.family_id)")
    c.commit()
    print(f"{len(cibles)} syndromes examinés, {n} rattachements")


if __name__ == "__main__":
    main()
