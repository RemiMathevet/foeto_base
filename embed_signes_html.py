#!/usr/bin/env python3
"""Re-embarque signes_examen_clinique.js / signes_autopsie.js entre les marqueurs
/* SIGNES:debut */ ... /* SIGNES:fin */ des deux HTML V2 et incremente le patch
de VERSION. Ne touche a rien d'autre. Usage : python3 embed_signes_html.py"""
import re
from pathlib import Path

H = Path("/home/mathevet/Bureau/Hub_HTML")
for html, js in (("autopsie.html", "signes_autopsie.js"), ("examen_clinique.html", "signes_examen_clinique.js")):
    p = H / html
    s = p.read_text(encoding="utf-8")
    a = s.index("/* SIGNES:debut */\n") + len("/* SIGNES:debut */\n")
    b = s.index("/* SIGNES:fin */")
    s = s[:a] + (H / js).read_text(encoding="utf-8") + s[b:]
    s = re.sub(r'var VERSION = "(\d+)\.(\d+)\.(\d+)";', lambda m: f'var VERSION = "{m[1]}.{m[2]}.{int(m[3]) + 1}";', s, count=1)
    p.write_text(s, encoding="utf-8")
    print(html, re.search(r'var VERSION = "[^"]+"', s)[0])
