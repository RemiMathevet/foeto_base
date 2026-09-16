"""Relecture Claude des 172 pas sûrs ReAct (pubmed) -> choix dans arbitrage_llm_nom.tsv.
Choix : OK | NON | HP:x | PARENT:HP:x | 'N:nom|N:nom2|...' (noms résolus par l'index NAME/EXACT, premier qui résout ;
'P:nom' = PARENT ; 'nom + nom' = composite ; dernier maillon peut être OK/NON/PARENT:HP:x)."""
import csv, sys, sqlite3
sys.path.insert(0,'/home/mathevet/Bureau/foeto_base')
import map_signes_hpo_obo as O, map_signes_hpo_regles as R
obo=O.load_obo(O.OBO); c=sqlite3.connect(O.DB)
ours={r[0]:(r[1],r[2]) for r in c.execute("select hpo_id,label_en,aliases_fr from hpo_terms")}
idx,idx_tok=R.index(obo,ours)
def lk(s):
    h=idx.get(O.norm(s)) or idx_tok.get(O.toks(s)); return h[0] if h and h[1] in("NAME","EXACT") and h[0] in obo else None
D={
1:"N:Prenatal movement abnormality|OK",2:"NON",3:"P:Abnormality of limbs",4:"N:Aprosencephaly|OK",5:"HP:0001989",6:"OK",
7:"N:Absent fifth fingernail + N:Absent fifth toenail|OK",8:"N:Dysphagia|NON",9:"NON",10:"OK",11:"N:Arhinencephaly|OK",
12:"N:Bowing of the long bones|OK",13:"PARENT:HP:0003028",14:"N:Anorectal anomaly + N:Abnormality of the genital system|OK",
15:"N:Absent hallux|N:Aplasia of the hallux|OK",16:"N:Supraventricular tachycardia|OK",17:"PARENT:HP:0008776",
18:"N:Ureteral agenesis|N:Absent ureter|PARENT:HP:0025633",
19:"N:Elbow flexion contracture + N:Wrist flexion contracture + N:Knee flexion contracture|OK",20:"N:Finger syndactyly|OK",
21:"NON",22:"P:Abnormal lung lobation",23:"PARENT:HP:0005561",24:"N:Aprosencephaly|PARENT:HP:0012443",25:"NON",
26:"N:Intracardiac calcification|N:Myocardial calcification|N:Cardiac calcification|PARENT:HP:0001627",27:"P:Abnormality of the nervous system",
28:"PARENT:HP:0001317",29:"PARENT:HP:0001317",30:"P:Abnormality of the neck",31:"HP:0005294",32:"NON",33:"N:Pes cavus|OK",
34:"N:Colonic ulceration|P:Abnormality of the large intestine",35:"NON",36:"NON",
37:"N:Decreased activity of cytochrome-c oxidase in muscle tissue|N:Decreased activity of mitochondrial complex IV|OK",
38:"PARENT:HP:0001999",39:"PARENT:HP:0001999",40:"PARENT:HP:0001999",41:"PARENT:HP:0001999",42:"PARENT:HP:0001999",43:"NON",44:"OK",
45:"N:Sternal cleft|OK",46:"N:Abnormality of the hand + N:Abnormality of the foot|OK",47:"NON",48:"NON",
49:"N:Right atrial enlargement + N:Right ventricular dilatation|OK",50:"N:Decreased activity of cytochrome-c oxidase in muscle tissue|N:Decreased activity of mitochondrial complex IV|OK",
51:"OK",52:"P:Abnormality of limbs",53:"OK",54:"NON",55:"OK",56:"NON",57:"N:Split foot|OK",58:"N:Split hand|OK",
59:"N:Edema of the dorsum of hands + N:Edema of the dorsum of feet|N:Peripheral edema|OK",60:"N:Encephalopathy + N:Myopathy|OK",
61:"N:Right atrial enlargement + N:Right ventricular dilatation|OK",62:"NON",63:"NON",64:"N:Ectopia cordis|OK",65:"OK",66:"OK",
67:"HP:0001789",68:"OK",69:"NON",70:"N:Horseshoe kidney|OK",71:"N:Gastric dilatation|N:Dilatation of the stomach|PARENT:HP:0002577",
72:"N:Cardiac hemosiderosis|N:Myocardial hemosiderosis|NON",73:"N:Pancreatic iron deposition|NON",74:"NON",75:"PARENT:HP:0001384",76:"NON",
77:"OK",78:"P:Abnormal thalamic morphology|NON",79:"N:Hypoplasia of the aorta|N:Aortic hypoplasia|OK",80:"NON",81:"N:Postural instability|OK",
82:"NON",83:"NON",84:"N:Elevated urinary polyol level|N:Polyoluria|NON",85:"PARENT:HP:0001627",86:"N:Intracranial arterial dissection|OK",
87:"N:Tracheal deviation|NON",88:"PARENT:HP:0000525",89:"OK",90:"N:Knee dislocation|PARENT:HP:0034669",91:"N:Acardia|NON",
92:"N:Lymphorrhea|NON",93:"OK",94:"N:Elevated circulating hepatic transaminase concentration|N:Elevated hepatic transaminase|NON",
95:"N:Sternal cleft|OK",96:"OK",97:"OK",98:"OK",99:"NON",100:"NON",101:"NON",102:"NON",103:"NON",104:"NON",105:"NON",106:"NON",
107:"NON",108:"NON",109:"PARENT:HP:0001999",110:"NON",111:"OK",112:"N:Pancreatic iron deposition|PARENT:HP:0012090",113:"NON",114:"NON",115:"NON",
116:"N:Placental edema|P:Abnormality of the placenta|NON",117:"N:Placental edema|P:Abnormality of the placenta|NON",118:"NON",119:"HP:0005294",
120:"OK",121:"OK",122:"OK",123:"PARENT:HP:0025015",124:"N:Edema of the dorsum of hands + N:Edema of the dorsum of feet|N:Peripheral edema|NON",
125:"P:Abnormal skeletal morphology",126:"N:Decreased activity of cytochrome-c oxidase in muscle tissue|N:Decreased activity of mitochondrial complex IV|OK",
127:"NON",128:"NON",129:"OK",130:"N:Radial club hand|OK",131:"N:Stiff skin|PARENT:HP:0011121",132:"N:Stiff skin|PARENT:HP:0011121",
133:"N:Hypoplasia of the olivary nucleus|N:Olivary nucleus hypoplasia|P:Abnormal medulla oblongata morphology",
134:"N:Hypoplasia of the olivary nucleus|N:Olivary nucleus hypoplasia|P:Abnormal medulla oblongata morphology",
135:"N:Hypoplasia of the olivary nucleus|N:Olivary nucleus hypoplasia|P:Abnormal medulla oblongata morphology",
136:"P:Abnormality of the scrotum|OK",137:"P:Abnormality of the scrotum|OK",138:"P:Abnormality of the scrotum|OK",
139:"P:Abnormal cerebral vascular morphology",140:"N:Drug-resistant epilepsy|N:Refractory seizures|HP:0001250",
141:"N:Hypoplasia of the frontal lobes + N:Hypoplasia of the occipital lobes|OK",142:"N:Joint contracture|OK",143:"OK",144:"N:Cirrhosis|OK",
145:"NON",146:"N:Perirenal hemorrhage|OK",147:"NON",148:"N:Sternal cleft|OK",149:"NON",150:"N:Subpleural cysts|PARENT:HP:0031630",
151:"N:Taut skin|N:Stiff skin|PARENT:HP:0011121",152:"N:Drug-resistant epilepsy|N:Refractory seizures|HP:0001250",
153:"N:Drug-resistant epilepsy|N:Refractory seizures|OK",154:"N:Drug-resistant epilepsy|N:Refractory seizures|OK",
155:"N:Taut skin|N:Stiff skin|PARENT:HP:0011121",156:"N:Tracheal stenosis|OK",157:"P:Abnormality of the upper respiratory tract|NON",
158:"N:Oculogyric crisis|NON",159:"NON",160:"NON",161:"N:Esophageal varix|OK",162:"N:Joint contracture of the hand + N:Joint contracture of the foot|OK",
163:"NON",164:"N:Arterial occlusion|PARENT:HP:0002597",165:"N:Vertebral artery dissection|HP:0005294",166:"NON",
167:"N:Gastric antral vascular ectasia|OK",168:"N:Popliteal pterygium|OK",169:"OK",170:"OK",171:"N:Yellow-brown discoloration of the teeth|N:Abnormality of dental color|OK",172:"NON"}
rows=c.execute("""select s.id, s.signe, f.hpo_id from signes_fragments f join syndrome_signes_livres_candidats s on s.id=f.candidat_id
 where f.modele='react_hpo?' and s.livre='pubmed' and s.hpo_id is null order by lower(s.signe)""").fetchall()
assert len(rows)==172==len(D)
def resoudre(spec, prop):
    for alt in spec.split("|"):
        alt=alt.strip()
        if alt=="OK": return prop
        if alt=="NON" or alt.startswith(("HP:","PARENT:HP:")): return alt
        if alt.startswith("P:"):
            h=lk(alt[2:]); 
            if h: return "PARENT:"+h
            continue
        parts=[lk(p.strip()[2:]) for p in alt.split(" + ")]
        if all(parts): return "+".join(parts)
    raise SystemExit(f"non résolu : {spec}")
choix={}
for i,(rid,sg,h) in enumerate(rows,1):
    ch=resoudre(D[i],h); choix[(sg.lower(),h)]=ch
    if ch!=h: print(f"{i:3d} {sg[:45]:45s} {h} -> {ch} {' / '.join(obo[x]['name'] for x in ch.replace('PARENT:','').split('+') if x in obo)}")
p='/home/mathevet/Bureau/foeto_base/arbitrage_llm_nom.tsv'
rs=list(csv.DictReader(open(p,encoding='utf-8'),delimiter='\t')); n=0
for r in rs:
    k=(r['signe'].lower(), r['hpo_id'])
    if k in choix and not r['choix']: r['choix']=choix[k]; n+=1
w=csv.DictWriter(open(p,'w',encoding='utf-8'),fieldnames=rs[0].keys(),delimiter='\t',lineterminator='\n'); w.writeheader(); w.writerows(rs)
from collections import Counter
print(f"\n{n} choix écrits ; ", Counter('NON' if v=='NON' else 'PARENT' if v.startswith('PARENT') else 'composite' if '+' in v else 'OK' if v==k[1] else 'autre' for k,v in choix.items()))
