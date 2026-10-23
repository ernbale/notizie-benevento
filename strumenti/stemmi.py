#!/usr/bin/env python3
"""Gli stemmi dei Comuni del Sannio per le pagine /comune/<nome>/ → img/stemmi/<nome>.png e img/stemmi/stemmi.json.

Si prendono solo i disegni con licenza libera su Wikimedia Commons (CC BY, CC BY-SA, CC0, pubblico dominio), con
autore e licenza da citare sotto l'immagine. La maggior parte degli stemmi su Wikipedia in italiano sono disegni di
Araldica Civica protetti da copyright, che Wikipedia usa solo per eccezione: quelli NO. Un Comune senza disegno
libero ha la pagina senza stemma. Si lancia a mano ogni tanto (i disegni liberi aumentano); le immagini stanno nel
repository.

Uso:  python3 strumenti/stemmi.py [--sito .]
"""
import argparse
import io
import json
import os
import re
import sys
import urllib.parse
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from meteo import COMUNI_BN          # noqa: E402
from chiusure import slug            # noqa: E402

UA = {"User-Agent": "NotizieBenevento/1.0 (https://notiziebenevento.it)"}
LIBERE = re.compile(r"^(CC BY(-SA)? [0-9.]+|CC0|Public domain|PD.*)$", re.I)
ALTEZZA = 200   # px: sulla pagina lo stemma è alto 100, così è nitido anche sui telefoni


def chiedi(url, **p):
    with urllib.request.urlopen(urllib.request.Request(url + "?" + urllib.parse.urlencode(p), headers=UA), timeout=60) as r:
        return json.load(r)


def titoli_wikipedia():
    """{titolo della voce su it.wikipedia: nome del Comune}, da Wikidata (codice ISTAT 062…: provincia di Benevento)."""
    q = ('SELECT ?nome ?titolo WHERE { ?c wdt:P635 ?istat . FILTER(STRSTARTS(?istat, "062")) ?c wdt:P31 wd:Q747074 . '
         '?c rdfs:label ?nome . FILTER(LANG(?nome) = "it") ?a schema:about ?c ; '
         'schema:isPartOf <https://it.wikipedia.org/> ; schema:name ?titolo . }')
    r = chiedi("https://query.wikidata.org/sparql", query=q, format="json")["results"]["bindings"]
    return {x["titolo"]["value"]: x["nome"]["value"] for x in r}


def file_stemmi(titoli):
    """{Comune: nome del file} dal campo «Stemma» del riquadro della voce (o col nome solito «<Comune>-Stemma.svg»)."""
    out, tl = {}, list(titoli)
    for i in range(0, len(tl), 40):
        d = chiedi("https://it.wikipedia.org/w/api.php", action="query", prop="revisions", rvprop="content",
                   rvslots="main", titles="|".join(tl[i:i + 40]), format="json", formatversion=2)
        for p in d["query"]["pages"]:
            m = re.search(r"\|\s*Stemma\s*=\s*([^\n|}]*)", p["revisions"][0]["slots"]["main"]["content"])
            out[titoli[p["title"]]] = [m.group(1).strip()] if m and m.group(1).strip() else []
    for c, f in out.items():
        f += [f"{c}-Stemma.svg", f"{c}-Stemma.png"]
    return out


def informazioni(nomi):
    """{file: imageinfo} dalle API di it.wikipedia (che vede anche i file di Commons)."""
    out = {}
    for i in range(0, len(nomi), 40):
        d = chiedi("https://it.wikipedia.org/w/api.php", action="query", prop="imageinfo",
                   iiprop="url|extmetadata", iiurlheight=ALTEZZA, titles="|".join("File:" + f for f in nomi[i:i + 40]),
                   format="json", formatversion=2)
        norm = {x["to"]: x["from"] for x in d["query"].get("normalized", [])}
        for p in d["query"]["pages"]:
            if "imageinfo" in p:
                out[norm.get(p["title"], p["title"])[5:]] = dict(p["imageinfo"][0], repo=p.get("imagerepository"))
    return out


def testo(m, k):
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", str((m.get(k) or {}).get("value") or ""))).strip()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sito", default=os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    a = ap.parse_args()
    from PIL import Image
    cartella = os.path.join(a.sito, "img", "stemmi")
    os.makedirs(cartella, exist_ok=True)
    candidati = file_stemmi(titoli_wikipedia())
    info = informazioni(sorted({f for v in candidati.values() for f in v}))
    dati, saltati = {}, []
    for comune in COMUNI_BN:
        scelto = None
        for f in candidati.get(comune, []):
            ii = info.get(f)
            if ii and ii["repo"] == "shared" and LIBERE.match(testo(ii.get("extmetadata") or {}, "LicenseShortName")):
                scelto = (f, ii)
                break
        if not scelto:
            saltati.append(comune)
            continue
        f, ii = scelto
        m = ii.get("extmetadata") or {}
        with urllib.request.urlopen(urllib.request.Request(ii["thumburl"], headers=UA), timeout=60) as r:
            im = Image.open(io.BytesIO(r.read()))
            im.load()
        im = im.convert("RGBA")   # ridisegnata da capo: dal file scaricato resta solo l'immagine
        if im.height != ALTEZZA:
            im = im.resize((round(im.width * ALTEZZA / im.height), ALTEZZA), Image.LANCZOS)
        nome = slug(comune) + ".png"
        im.save(os.path.join(cartella, nome), optimize=True)
        dati[comune] = {"file": "/img/stemmi/" + nome, "larghezza": im.width, "altezza": im.height,
                        "pagina": ii.get("descriptionurl"), "licenza": testo(m, "LicenseShortName"),
                        "url_licenza": testo(m, "LicenseUrl"), "autore": testo(m, "Artist")[:80]}
    with open(os.path.join(cartella, "stemmi.json"), "w", encoding="utf-8") as fh:
        json.dump(dati, fh, ensure_ascii=False, indent=1)
        fh.write("\n")
    print(f"stemmi liberi: {len(dati)}; senza disegno libero: {len(saltati)} ({', '.join(saltati)})")


if __name__ == "__main__":
    main()
