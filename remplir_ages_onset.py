#!/usr/bin/env python3
"""ages_of_onset (JSON, libelles francais comme l'existant) pour les syndromes qui
n'en ont pas — les ORPHA crees depuis les livres et GeneReviews — depuis Orphanet
product9_ages (akinator/orphadata_cache/ages_en.xml). Usage : python3 remplir_ages_onset.py"""
import json
import sqlite3
import xml.etree.ElementTree as ET

DB = "/home/mathevet/Bureau/foeto_base/syndromes_foetaux.db"
FR = {"Antenatal": "Prénatal", "Neonatal": "Néonatal", "Infancy": "Petite enfance", "Childhood": "Enfance",
      "Adolescent": "Adolescence", "Adult": "Adulte", "Elderly": "Personne âgée", "All ages": "Tous âges", "No data available": None}
c = sqlite3.connect(DB)
ages = {}
for d in ET.parse("/home/mathevet/Bureau/akinator/orphadata_cache/ages_en.xml").getroot().iter("Disorder"):
    sid = "ORPHA:" + d.findtext("OrphaCode")
    l = [FR.get(x.findtext("Name"), x.findtext("Name")) for x in d.iter("AverageAgeOfOnset")]
    ages[sid] = [x for x in l if x]
n = 0
for sid, in c.execute("select id from syndromes where ages_of_onset is null or ages_of_onset in ('', '[]')").fetchall():
    if ages.get(sid):
        c.execute("update syndromes set ages_of_onset=? where id=?", (json.dumps(ages[sid], ensure_ascii=False), sid)); n += 1
c.commit()
reste = c.execute("select count(*) from syndromes where ages_of_onset is null or ages_of_onset in ('', '[]')").fetchone()[0]
print(f"{n} syndromes complétés ; sans âge Orphanet : {reste}")
