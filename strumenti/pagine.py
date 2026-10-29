#!/usr/bin/env python3
"""Le pagine per Google e per la condivisione, fatte da notizie.json e dall'archivio (le esegue GitHub a ogni pubblicazione).

- notizia/<id>/index.html e approfondimento/<id>/index.html: una pagina vera per ogni notizia, anche archiviata.
  È index.html con titolo, descrizione, anteprima (og:), dati strutturati (NewsArticle) e l'articolo già scritto
  nella pagina: Google lo legge subito e WhatsApp/Facebook mostrano titolo e immagine. Poi il sito funziona come sempre.
- sezione/<nome>/ e zona/<nome>/: la prima pagina già filtrata, con titolo e descrizione propri.
- chi-siamo/index.html: come lavora il sito (testo in html_chi_siamo).
- evento/<id>/index.html ed evento/<id>/evento.ics: la pagina di ogni evento del calendario (eventi.json e
  archivio/eventi-*.json), con i dati strutturati Event, e il file per aggiungerlo al calendario del telefono.
- img/n/<id>.png: l'immagine di anteprima di ogni notizia (titolo grande, sezione, luogo, fonti), sempre con lo
  stesso nome anche quando si ridisegna.
- sitemap.xml (tutto), sitemap-notizie.xml (Google News, ultimi 2 giorni), feed.xml (RSS, ultime 50).

Uso:  python3 strumenti/pagine.py [--sito .] [--sitemap-prima vecchia.xml --indexnow cambiati.json]
      python3 strumenti/pagine.py --immagine-generica condivisione.png
      python3 strumenti/pagine.py --invia-indexnow cambiati.json     (dopo la pubblicazione)
I file generati non vanno nel repository (.gitignore): li rifà GitHub ogni volta.
"""
import argparse
import datetime as dt
import email.utils
import glob
import hashlib
import html
import json
import os
import re
import shutil
import sys
import unicodedata
import urllib.parse

from chiusure import slug       # gli stessi nomi di img/stemmi (strumenti/stemmi.py)
from meteo import COMUNI_BN

SITO = "https://notiziebenevento.it"
INDEXNOW_CHIAVE = "dbcf36df6ea73bedfd5f2e121caca034"   # pubblica per costruzione: il file <chiave>.txt sta sul sito
HUB = "https://pubsubhubbub.appspot.com/"   # WebSub (il hub di Google): avvisato dopo ogni pubblicazione con notizie nuove
NOME = "Notizie Benevento"
QUI = os.path.dirname(os.path.abspath(__file__))
FONT_BOLD = os.path.join(QUI, "font", "SourceSerif4-Bold.ttf")
FONT_BLACK = os.path.join(QUI, "font", "SourceSerif4-Black.ttf")
MESI = ["gen", "feb", "mar", "apr", "mag", "giu", "lug", "ago", "set", "ott", "nov", "dic"]
MESI_LUNGHI = ["gennaio", "febbraio", "marzo", "aprile", "maggio", "giugno", "luglio", "agosto", "settembre",
               "ottobre", "novembre", "dicembre"]
NOMI_CAT = {"avvisi": "Avvisi", "cultura": "Cultura", "strade": "Strade", "cronaca": "Cronaca", "politica": "Politica", "sport": "Sport", "eventi": "Eventi",
            "meteo": "Allerte", "altro": "Altro"}
NOMI_SPORT = {"calcio": "Calcio", "calcio_a_5": "Calcio a 5", "basket": "Basket", "pallavolo": "Pallavolo", "rugby": "Rugby",
              "scherma": "Scherma", "atletica": "Atletica", "tennis": "Tennis", "ciclismo": "Ciclismo", "nuoto": "Nuoto",
              "altro": "Altri sport"}
# percorso, categoria o zona, <title>, h1, descrizione
SEZIONI = [
    ("sezione/avvisi", {"cat": "avvisi"}, "Avvisi Benevento e Sannio: strade chiuse, orari, uffici e scadenze dei Comuni",
     "Avvisi a Benevento e nel Sannio", "Strade chiuse, orari dei cimiteri e degli uffici, servizi, bandi e scadenze dei "
     "Comuni del Sannio: quello che serve sapere oggi e nei prossimi giorni, paese per paese, con le fonti ufficiali."),
    ("sezione/strade", {"cat": "strade"}, "Strade Benevento oggi: chiusure, cantieri e traffico nel Sannio",
     "Strade a Benevento e nel Sannio", "Strade chiuse, cantieri, incidenti e lavori a Benevento e nel Sannio, "
     "con le fonti ufficiali (ANAS, Provincia, Comuni) e i giornali locali messi a confronto."),
    ("sezione/cronaca", {"cat": "cronaca"}, "Cronaca Benevento: ultime notizie di cronaca dal Sannio",
     "Cronaca a Benevento e nel Sannio", "Le notizie di cronaca di oggi da Benevento e dai paesi del Sannio, "
     "confrontate tra i giornali locali, con i link agli articoli originali."),
    ("sezione/politica", {"cat": "politica"}, "Politica Benevento: Comune, Provincia e paesi del Sannio",
     "Politica a Benevento e nel Sannio", "Consiglio comunale, Provincia, Regione e paesi del Sannio: "
     "le notizie di politica di Benevento confrontate tra i giornali locali."),
    ("sezione/sport", {"cat": "sport"}, "Sport Benevento e Sannio: calcio, basket, pallavolo, rugby, scherma",
     "Sport a Benevento e nel Sannio", "Il Benevento e tutte le squadre e gli atleti del Sannio: calcio, calcio a 5, "
     "basket, pallavolo, rugby, scherma, atletica e gli altri sport, con risultati e notizie confrontate tra i giornali locali."),
    ("sezione/eventi", {"cat": "eventi"}, "Eventi a Benevento e provincia: calendario di teatro, concerti, mostre e sagre",
     "Eventi a Benevento e nel Sannio", "Il calendario degli eventi nel Sannio: teatro, concerti, mostre, cinema, sagre e "
     "feste a Benevento e provincia, con date, orari, luoghi e fonti."),
    ("sezione/allerte", {"cat": "meteo"}, "Allerte Benevento: allerta meteo, scuole chiuse e terremoti nel Sannio",
     "Allerte a Benevento e nel Sannio", "Allerte meteo della Protezione civile per le zone del Sannio, chiusure di "
     "scuole e parchi decise dai Comuni, terremoti e danni del maltempo a Benevento e provincia."),
    ("sezione/cultura", {"cat": "cultura"}, "Cultura Benevento: libri, teatro, musica e mostre nel Sannio",
     "Cultura a Benevento e nel Sannio", "Libri e autori, presentazioni, teatro, musica, cinema, mostre, musei e premi: "
     "le notizie di cultura di Benevento e del Sannio e gli appuntamenti dei prossimi giorni."),
    ("sezione/altro", {"cat": "altro"}, "Altre notizie da Benevento e provincia",
     "Altre notizie da Benevento e dal Sannio", "Lavoro, salute, scuola, ambiente e servizi: le altre notizie di Benevento "
     "e provincia confrontate tra i giornali locali."),
    ("zona/benevento", {"zona": "benevento"}, "Notizie Benevento città: cronaca, strade e politica in città",
     "Notizie da Benevento città", "Le notizie di oggi dalla città di Benevento: cronaca, strade, politica, eventi."),
    ("zona/valle-telesina", {"zona": "telesina"}, "Notizie Valle Telesina: Telese Terme, Solopaca, Cerreto e dintorni",
     "Notizie dalla Valle Telesina", "Le notizie di Telese Terme, San Salvatore Telesino, Solopaca, Cerreto Sannita, "
     "Guardia Sanframondi, Faicchio, Amorosi e degli altri paesi della Valle Telesina."),
    ("zona/valle-caudina", {"zona": "caudina"}, "Notizie Valle Caudina: Montesarchio, Airola, Sant'Agata de' Goti",
     "Notizie dalla Valle Caudina", "Le notizie di Montesarchio, Airola, Sant'Agata de' Goti, Moiano, Bonea e degli "
     "altri paesi della Valle Caudina sannita."),
    ("zona/fortore", {"zona": "fortore"}, "Notizie Fortore e Tammaro: San Bartolomeo, San Marco dei Cavoti, Morcone",
     "Notizie dal Fortore e dal Tammaro", "Le notizie di San Bartolomeo in Galdo, San Marco dei Cavoti, Morcone, "
     "Colle Sannita, Baselice e degli altri paesi del Fortore e del Tammaro."),
    ("zona/altri-comuni", {"zona": "provincia"}, "Notizie dai comuni della provincia di Benevento",
     "Notizie dagli altri comuni del Sannio", "Le notizie di San Giorgio del Sannio, Apice, Pietrelcina, Ceppaloni, "
     "Paduli, Ponte e degli altri comuni della provincia di Benevento."),
]
CAT_PERCORSO = {s[1]["cat"]: s[0] for s in SEZIONI if "cat" in s[1]}
DESCR_HOME = ("Le ultime notizie di oggi da Benevento e dal Sannio: cronaca, strade, politica, sport, eventi e allerte, "
              "confrontate tra i giornali locali, con i link agli articoli originali.")


def e(s):
    return html.escape("" if s is None else str(s), quote=True)


def leggi(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def scrivi(path, testo):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(testo)


def breve(s, n=158):
    s = re.sub(r"\s+", " ", str(s or "")).strip()
    if len(s) <= n:
        return s
    return s[:n].rsplit(" ", 1)[0].rstrip(",;:.") + "…"


def data_it(iso, lunga=False):
    """«20 ott 2026, 11:29» o, per le notizie con solo il giorno, «19 ott 2026»."""
    s = str(iso or "")
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})(?:T(\d{2}):(\d{2}))?", s)
    if not m:
        return ""
    a, me, g, h, mi = m.groups()
    t = f"{int(g)} {(MESI_LUNGHI if lunga else MESI)[int(me) - 1]} {a}"
    return t + (f", {h}:{mi}" if h and not lunga else "")


def quando_dt(iso):
    s = str(iso or "")
    if re.match(r"^\d{4}-\d{2}-\d{2}$", s):
        s += "T12:00:00+02:00"
    try:
        return dt.datetime.fromisoformat(s)
    except ValueError:
        return None


def percorso(tipo, id_):
    return f"/{tipo if tipo in ('notizia', 'evento') else 'approfondimento'}/{id_}/"


# ---------- dati: prima pagina + archivio ----------
def tutte(sito):
    prima = leggi(os.path.join(sito, "notizie.json"))
    notizie, appro, visti = [], [], set()
    for n in prima.get("notizie", []):
        if n.get("articolo") and n.get("id"):
            notizie.append(dict(n, _arch=False)); visti.add(("n", n["id"]))
    for a in prima.get("approfondimenti", []):
        if a.get("id"):
            appro.append(dict(a, _arch=False)); visti.add(("a", a["id"]))
    for f in sorted(glob.glob(os.path.join(sito, "archivio", "[0-9][0-9][0-9][0-9]-[0-9][0-9].json")), reverse=True):
        m = leggi(f)
        for n in m.get("notizie", []):
            if n.get("articolo") and n.get("id") and ("n", n["id"]) not in visti:
                notizie.append(dict(n, _arch=True)); visti.add(("n", n["id"]))
        for a in m.get("approfondimenti", []):
            if a.get("id") and ("a", a["id"]) not in visti:
                appro.append(dict(a, _arch=True)); visti.add(("a", a["id"]))
    chiave = lambda x: str(x.get("pubblicato") or x.get("aggiornato") or "")
    notizie.sort(key=chiave, reverse=True)
    appro.sort(key=chiave, reverse=True)
    return prima, notizie, appro


# ---------- immagini di anteprima (1200×630) ----------
def _font(path, size):
    from PIL import ImageFont
    return ImageFont.truetype(path, size)


def _a_capo(testo, font, larghezza):
    righe, riga = [], ""
    for parola in testo.split():
        prova = (riga + " " + parola).strip()
        if font.getlength(prova) <= larghezza or not riga:
            riga = prova
        else:
            righe.append(riga); riga = parola
    if riga:
        righe.append(riga)
    return righe


def _testata(d, W):
    """Il quadrato rosso «NB», il nome del sito e l'indirizzo: come in cima al sito."""
    d.rounded_rectangle([60, 48, 132, 120], radius=15, fill="#c4161c")
    f = _font(FONT_BLACK, 44)
    w = f.getlength("NB")
    d.text((96 - w / 2 + 1, 85), "NB", font=f, fill="#ffffff", anchor="lm")
    d.text((154, 86), NOME, font=_font(FONT_BLACK, 46), fill="#111111", anchor="lm")
    d.text((W - 60, 86), "notiziebenevento.it", font=_font(FONT_BOLD, 26), fill="#5b5249", anchor="rm")
    d.line([60, 152, W - 60, 152], fill="#e3c9ad", width=3)


def immagine(path, titolo, occhiello, luogo, piede, impronta=None):
    from PIL import Image, ImageDraw, PngImagePlugin
    W, H = 1200, 630
    im = Image.new("RGB", (W, H), "#fdeedd")
    d = ImageDraw.Draw(im)
    _testata(d, W)
    x = 60
    if occhiello:
        fo = _font(FONT_BOLD, 28)
        oc = occhiello.upper()
        d.text((x, 196), oc, font=fo, fill="#c4161c", anchor="lm")
        if luogo:
            d.text((x + fo.getlength(oc) + 18, 196), breve(luogo, 60), font=fo, fill="#5b5249", anchor="lm")
    # il titolo più grande possibile tra la sezione e il piede
    alto, basso = 236, 548
    for size in range(76, 38, -2):
        f = _font(FONT_BOLD, size)
        righe = _a_capo(titolo, f, W - 120)
        if len(righe) * size * 1.14 <= basso - alto:
            break
    else:
        f = _font(FONT_BOLD, 40)
        righe = _a_capo(titolo, f, W - 120)
        max_r = int((basso - alto) // (40 * 1.14))
        if len(righe) > max_r:
            righe = righe[:max_r]
            while f.getlength(righe[-1] + "…") > W - 120 and " " in righe[-1]:
                righe[-1] = righe[-1].rsplit(" ", 1)[0]
            righe[-1] += "…"
        size = 40
    y = alto
    for r in righe:
        d.text((x, y), r, font=f, fill="#111111")
        y += size * 1.14
    if piede:
        d.rectangle([0, H - 14, W, H], fill="#c4161c")
        d.text((x, 585), piede, font=_font(FONT_BOLD, 26), fill="#5b5249", anchor="lm")
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    info = PngImagePlugin.PngInfo()
    if impronta:
        info.add_text("impronta", impronta)
    im.save(path, optimize=True, pnginfo=info)


def _impronta_png(path):
    """L'impronta scritta dentro un'immagine già fatta (None se non c'è)."""
    from PIL import Image
    try:
        with Image.open(path) as im:
            return im.info.get("impronta")
    except (OSError, ValueError):
        return None


def immagine_generica(path):
    from PIL import Image, ImageDraw
    W, H = 1200, 630
    im = Image.new("RGB", (W, H), "#fdeedd")
    d = ImageDraw.Draw(im)
    _testata(d, W)
    f = _font(FONT_BOLD, 64)
    y = 262
    for r in _a_capo("Le notizie di Benevento e provincia, confrontate tra i giornali locali", f, W - 120):
        d.text((60, y), r, font=f, fill="#111111"); y += 74
    d.text((60, y + 30), "Con le fonti e i link agli articoli originali.",
           font=_font(FONT_BOLD, 28), fill="#5b5249")
    d.rectangle([0, H - 14, W, H], fill="#c4161c")
    im.save(path, optimize=True)


def immagine_ig(sito, n):
    """L'immagine per Instagram (img/ig/<id>.jpg, 1080×1350, il formato verticale del feed): testata, la foto
    illustrativa se la notizia ce l'ha (con la scritta che è fatta con l'IA), sezione, titolo grande e, senza foto,
    anche il riassunto. Si rifà solo se cambia qualcosa (impronta nel commento del JPEG)."""
    from PIL import Image, ImageDraw
    W, H = 1080, 1350
    occ, foto, loc = _categoria(n), foto_tema(n), foto_in_alto(n)
    impronta = hashlib.sha1(json.dumps([n["titolo"], occ, n.get("luogo"), n.get("sintesi"), foto or loc, 1],
                                       ensure_ascii=False).encode()).hexdigest()[:10]
    rel = f"img/ig/{n['id']}.jpg"
    full = os.path.join(sito, rel)
    try:
        with Image.open(full) as vecchia:
            if (vecchia.info.get("comment") or b"").decode(errors="ignore") == impronta:
                return rel
    except (OSError, ValueError):
        pass
    im = Image.new("RGB", (W, H), "#fdeedd")
    d = ImageDraw.Draw(im)
    _testata(d, W)
    x, larg = 60, W - 120
    y = 190
    if foto and os.path.exists(os.path.join(sito, foto.lstrip("/"))):
        with Image.open(os.path.join(sito, foto.lstrip("/"))) as f:
            f = f.convert("RGB")
            alto_foto = 600
            r = max(W / f.width, alto_foto / f.height)
            f = f.resize((round(f.width * r), round(f.height * r)))
            sx, sy = (f.width - W) // 2, (f.height - alto_foto) // 2
            im.paste(f.crop((sx, sy, sx + W, sy + alto_foto)), (0, y))
        nota = "Immagine illustrativa creata con l'intelligenza artificiale"
        fn = _font(FONT_BOLD, 22)
        d.rectangle([0, y + alto_foto - 40, fn.getlength(nota) + 40, y + alto_foto], fill="#111111")
        d.text((20, y + alto_foto - 20), nota, font=fn, fill="#ffffff", anchor="lm")
        y += alto_foto + 50
    elif loc and os.path.exists(os.path.join(sito, loc.lstrip("/"))):
        # la locandina o la foto inviata, intera (niente ritagli): al centro di una fascia scura alta quanto la foto
        alto_foto = 600
        d.rectangle([0, y, W, y + alto_foto], fill="#2b2622")
        with Image.open(os.path.join(sito, loc.lstrip("/"))) as f:
            f = f.convert("RGB")
            r = min((W - 40) / f.width, (alto_foto - 20) / f.height)
            f = f.resize((round(f.width * r), round(f.height * r)))
            im.paste(f, ((W - f.width) // 2, y + (alto_foto - f.height) // 2))
        foto = loc
        y += alto_foto + 50
    else:
        y += 50
    fo = _font(FONT_BOLD, 30)
    d.text((x, y), occ.upper(), font=fo, fill="#c4161c", anchor="lm")
    if n.get("luogo"):
        d.text((x + fo.getlength(occ.upper()) + 18, y), breve(n["luogo"], 40).upper(), font=fo, fill="#5b5249", anchor="lm")
    y += 44
    basso = H - 110
    spazio = (basso - y) if foto else (basso - y) * 0.62   # senza foto: sotto il titolo c'è il riassunto
    for size in range(92 if not foto else 70, 40, -2):
        ft = _font(FONT_BOLD, size)
        righe = _a_capo(n["titolo"], ft, larg)
        if len(righe) * size * 1.14 <= spazio:
            break
    else:
        righe = righe[:max(1, int(spazio // (42 * 1.14)))]
        righe[-1] += "…"
    for rg in righe:
        d.text((x, y), rg, font=ft, fill="#111111")
        y += size * 1.14
    if not foto and n.get("sintesi"):
        y += 24
        fs = _font(FONT_BOLD, 34)
        rr = _a_capo(n["sintesi"], fs, larg)
        massimo = max(0, int((basso - y) // (34 * 1.3)))
        if len(rr) > massimo:
            rr = rr[:massimo]
            if rr:
                rr[-1] = rr[-1].rstrip(",;:.") + "…"
        for rg in rr:
            d.text((x, y), rg, font=fs, fill="#5b5249")
            y += 34 * 1.3
    d.rectangle([0, H - 14, W, H], fill="#c4161c")
    d.text((x, H - 56), "Leggi tutto su notiziebenevento.it", font=_font(FONT_BOLD, 30), fill="#111111", anchor="lm")
    os.makedirs(os.path.dirname(full), exist_ok=True)
    im.save(full, "JPEG", quality=88, optimize=True, comment=impronta.encode())
    return rel


def immagini_ig_foto(sito, n):
    """Le foto inviate col comunicato per il carosello di Instagram e per Facebook (img/ig/<id>-foto-<k>.jpg,
    1080×1350 come la prima): ognuna intera su fondo scuro, con chi l'ha mandata. Si rifanno solo se cambiano."""
    from PIL import Image, ImageDraw
    W, H = 1080, 1350
    out = []
    for k, foto in enumerate(foto_inviate(n), 1):
        src = os.path.join(sito, foto.lstrip("/"))
        if not os.path.exists(src):
            continue
        with open(src, "rb") as f:
            impronta = hashlib.sha1(f.read() + didascalia_foto(n).encode() + b"1").hexdigest()[:10]
        rel = f"img/ig/{n['id']}-foto-{k}.jpg"
        full = os.path.join(sito, rel)
        out.append(rel)
        try:
            with Image.open(full) as vecchia:
                if (vecchia.info.get("comment") or b"").decode(errors="ignore") == impronta:
                    continue
        except (OSError, ValueError):
            pass
        im = Image.new("RGB", (W, H), "#2b2622")
        d = ImageDraw.Draw(im)
        basso = 110
        with Image.open(src) as f:
            f = f.convert("RGB")
            r = min((W - 40) / f.width, (H - basso - 40) / f.height)
            f = f.resize((round(f.width * r), round(f.height * r)))
            im.paste(f, ((W - f.width) // 2, 20 + (H - basso - 40 - f.height) // 2))
        d.text((40, H - basso / 2 - 8), breve(didascalia_foto(n), 60), font=_font(FONT_BOLD, 30), fill="#ffffff", anchor="lm")
        d.text((W - 40, H - basso / 2 - 8), "notiziebenevento.it", font=_font(FONT_BOLD, 26), fill="#d9cfc4", anchor="rm")
        d.rectangle([0, H - 14, W, H], fill="#c4161c")
        os.makedirs(os.path.dirname(full), exist_ok=True)
        im.save(full, "JPEG", quality=88, optimize=True, comment=impronta.encode())
    return out


def credito_breve(c):
    return ((c.get("immagine") or {}).get("credito") or "").strip()


def immagine_curiosita(sito, c):
    """L'immagine della curiosità per Instagram, Facebook e Telegram (img/ig/curiosita-<slug>.jpg, 1080×1350), come
    quelle delle notizie (immagine_ig): testata, la foto libera con l'autore, «Curiosità del Sannio», titolo e inizio
    del racconto. Si rifà solo se cambia qualcosa (impronta nel commento del JPEG)."""
    from PIL import Image, ImageDraw
    W, H = 1080, 1350
    foto = (c.get("immagine") or {}).get("file")
    fuoco = float((c.get("immagine") or {}).get("fuoco_y", 0.5))   # dove sta il soggetto, dall'alto (0) al basso (1)
    impronta = hashlib.sha1(json.dumps([c["titolo"], c["testo"], c["categoria"], c["luogo"], foto, credito_breve(c), fuoco, 1],
                                       ensure_ascii=False).encode()).hexdigest()[:10]
    rel = f"img/ig/curiosita-{c['slug']}.jpg"
    full = os.path.join(sito, rel)
    try:
        with Image.open(full) as vecchia:
            if (vecchia.info.get("comment") or b"").decode(errors="ignore") == impronta:
                return rel
    except (OSError, ValueError):
        pass
    im = Image.new("RGB", (W, H), "#fdeedd")
    d = ImageDraw.Draw(im)
    _testata(d, W)
    x, larg, y = 60, W - 120, 190
    if foto and os.path.exists(os.path.join(sito, foto.lstrip("/"))):
        with Image.open(os.path.join(sito, foto.lstrip("/"))) as f:
            f = f.convert("RGB")
            alto = 600
            r = max(W / f.width, alto / f.height)
            f = f.resize((round(f.width * r), round(f.height * r)))
            sx = (f.width - W) // 2
            sy = min(max(0, round(f.height * fuoco - alto / 2)), f.height - alto)
            im.paste(f.crop((sx, sy, sx + W, sy + alto)), (0, y))
        # la foto fatta con l'IA quando su Commons non c'è quella del protagonista (CURIOSITA.md, dal 28 ott 2026)
        nota = ("Immagine illustrativa creata con l'intelligenza artificiale" if (c.get("immagine") or {}).get("ia")
                else credito_breve(c) + " · Wikimedia Commons")
        fn = _font(FONT_BOLD, 22)
        d.rectangle([0, y + alto - 40, fn.getlength(nota) + 40, y + alto], fill="#111111")
        d.text((20, y + alto - 20), nota, font=fn, fill="#ffffff", anchor="lm")
        y += alto + 50
    else:
        foto = None
        y += 60
    fo = _font(FONT_BOLD, 30)
    occ = "CURIOSITÀ DEL SANNIO"
    d.text((x, y), occ, font=fo, fill="#c4161c", anchor="lm")
    d.text((x + fo.getlength(occ) + 18, y), f"{CAT_CURIOSITA.get(c['categoria'], '')} · {c['luogo']}".upper(),
           font=fo, fill="#5b5249", anchor="lm")
    y += 44
    basso = H - 110
    spazio = (basso - y) * (0.55 if foto else 0.45)
    for size in range(66 if foto else 84, 40, -2):
        ft = _font(FONT_BOLD, size)
        righe = _a_capo(c["titolo"], ft, larg)
        if len(righe) * size * 1.14 <= spazio:
            break
    for rg in righe:
        d.text((x, y), rg, font=ft, fill="#111111")
        y += size * 1.14
    y += 22
    fs = _font(FONT_BOLD, 33)
    par = _paragrafi_curiosita(c["testo"])
    rr = _a_capo(par[0] if foto else " ".join(par[:2]), fs, larg)
    massimo = max(0, int((basso - y) // (33 * 1.32)))
    if len(rr) > massimo:
        rr = rr[:massimo]
        if rr:
            rr[-1] = rr[-1].rstrip(",;:.") + "…"
    for rg in rr:
        d.text((x, y), rg, font=fs, fill="#5b5249")
        y += 33 * 1.32
    d.rectangle([0, H - 14, W, H], fill="#c4161c")
    d.text((x, H - 56), "La storia intera su notiziebenevento.it", font=_font(FONT_BOLD, 30), fill="#111111", anchor="lm")
    os.makedirs(os.path.dirname(full), exist_ok=True)
    im.save(full, "JPEG", quality=88, optimize=True, comment=impronta.encode())
    return rel


def immagine_notizia(sito, n, tipo):
    """Percorso dell'immagine (sul sito) della notizia: si rifà solo se cambiano titolo, sezione, luogo o fonti.
    Il nome resta sempre lo stesso: Facebook si tiene l'indirizzo dell'immagine letto quando esce il post, e se
    cambiasse a ogni fonte nuova il post resterebbe col riquadro vuoto (21 ott 2026)."""
    v = vista_ufficiale(n)
    fonti = (v.get("articolo") or {}).get("fonti") or v.get("fonti") or []
    occ = "Approfondimento" if tipo == "approfondimento" else _categoria(n)
    quante = conta_fonti(v, fonti)
    piede = f"{quante[:1].upper() + quante[1:]} · {data_it(n.get('pubblicato') or n.get('aggiornato'), lunga=True)}"
    impronta = hashlib.sha1(json.dumps([n["titolo"], occ, n.get("luogo"), piede, 2], ensure_ascii=False)
                            .encode()).hexdigest()[:10]
    rel = f"img/n/{'approfondimento-' if tipo == 'approfondimento' else ''}{n['id']}.png"
    full = os.path.join(sito, rel)
    if _impronta_png(full) != impronta:
        immagine(full, n["titolo"], occ, n.get("luogo"), piede, impronta)
    return "/" + rel


# ---------- con una fonte ufficiale si mostra quella ----------
def vista_ufficiale(n):
    """La notizia come si mostra. Con una fonte ufficiale (stato «ufficiale» e la fonte segnata "ufficiale": true) il
    sito mostra quella; i giornali solo dove aggiungono un fatto che lei non dice (citati in una frase senza la fonte
    ufficiale) o dove dicono una cosa diversa («divergono»). Voluto dal proprietario il 26 ott 2026 («quando abbiamo la
    fonte ufficiale non è necessario mettere anche le altre fonti», «vale per tutte»). I giornali restano nei dati:
    servono a riconoscere i doppioni (giornali.citati, comunicati.link_di). Senza una fonte segnata la notizia si mostra
    com'è. Copia, non tocca n. Uguale a vistaUfficiale() di index.html."""
    a = n.get("articolo") if isinstance(n.get("articolo"), dict) else {}
    tutte = [f for l in (n.get("fonti"), a.get("fonti")) if isinstance(l, list) for f in l if isinstance(f, dict)]
    uff = {f["nome"] for f in tutte if f.get("ufficiale") is True and isinstance(f.get("nome"), str)}
    if n.get("stato") != "ufficiale" or not uff:
        return n

    def e_uff(nm):
        return isinstance(nm, str) and nm in uff

    def togli(x):   # in una frase con la fonte ufficiale, i giornali che la ripetono non si citano
        if not isinstance(x, dict) or not isinstance(x.get("fonti"), list) or not any(e_uff(nm) for nm in x["fonti"]):
            return x
        return dict(x, fonti=[nm for nm in x["fonti"] if e_uff(nm)])

    def segnata(f):   # la stessa fonte (per nome) è ufficiale in tutti e due gli elenchi
        return f if f.get("ufficiale") is True else dict(f, ufficiale=True)

    v = dict(n)
    elenco = lambda l: l if isinstance(l, list) else []
    v["fonti"] = ([segnata(f) for f in elenco(n.get("fonti")) if isinstance(f, dict) and e_uff(f.get("nome"))]
                  or [segnata(f) for f in elenco(a.get("fonti")) if isinstance(f, dict) and e_uff(f.get("nome"))])
    if a:
        b = dict(a)
        for sez in ("racconto", "cronologia"):
            if isinstance(a.get(sez), list):
                b[sez] = [togli(x) for x in a[sez]]
        if isinstance(a.get("concordano"), list):   # «concordano» rimasto con la sola fonte ufficiale non dice niente
            b["concordano"] = [y for x in a["concordano"] for y in [togli(x)]
                               if y is x or len(y.get("fonti") or []) > 1]
        if isinstance(a.get("aggiornamento"), dict):
            b["aggiornamento"] = togli(a["aggiornamento"])
        citate = set(uff)
        for sez in ("racconto", "cronologia", "concordano", "divergono", "non_si_sa"):
            for x in b.get(sez) or []:
                if isinstance(x, dict) and isinstance(x.get("fonti"), list):
                    citate |= {nm for nm in x["fonti"] if isinstance(nm, str)}
        if isinstance(b.get("aggiornamento"), dict) and isinstance(b["aggiornamento"].get("fonti"), list):
            citate |= {nm for nm in b["aggiornamento"]["fonti"] if isinstance(nm, str)}
        if isinstance(a.get("fonti"), list):   # prima le fonti ufficiali, poi i giornali (ognuno nel suo ordine)
            resta = [f for f in a["fonti"] if isinstance(f, dict) and isinstance(f.get("nome"), str) and f["nome"] in citate]
            b["fonti"] = [segnata(f) for f in resta if e_uff(f["nome"])] + [f for f in resta if not e_uff(f["nome"])]
        v["articolo"] = b
    return v


def conta_fonti(n, fonti):
    """«5 fonti confrontate», «1 fonte»; con una fonte ufficiale «fonte ufficiale» (e quanti giornali si citano)."""
    if n.get("stato") == "ufficiale" and any(isinstance(f, dict) and f.get("ufficiale") is True for f in fonti):
        u = sum(1 for f in fonti if isinstance(f, dict) and f.get("ufficiale") is True)
        g = len(fonti) - u
        return ("fonte ufficiale" if u == 1 else f"{u} fonti ufficiali") + \
            (f" e {g} {'giornale' if g == 1 else 'giornali'}" if g else "")
    return f"{len(fonti)} {'fonte' if len(fonti) == 1 else 'fonti confrontate'}"


# ---------- l'articolo già scritto nella pagina (stesso HTML che disegna index.html) ----------
def _link_fonte(f, testo):
    if re.match(r"^https?://", str(f.get("url") or ""), re.I):
        return f'<a href="{e(f["url"])}" target="_blank" rel="noopener nofollow">{e(testo)}</a>'
    return e(testo)


def _cita(nomi, fonti):
    if not isinstance(nomi, list) or not nomi:
        return ""
    pezzi = []
    for nome in nomi:
        f = next((x for x in fonti if x.get("nome") == nome), None)
        pezzi.append(_link_fonte(f, nome) if f else e(nome))
    return '<span class="cita"> (' + ", ".join(pezzi) + ")</span>"


def _frase(tag, r, fonti):
    t = r if isinstance(r, str) else (r or {}).get("testo", "")
    c = "" if isinstance(r, str) else _cita((r or {}).get("fonti"), fonti)
    return f"<{tag}>{e(t)}{c}</{tag}>"


def _giorno_racconto(g):
    try:
        d = dt.date.fromisoformat(str(g))
    except ValueError:
        return str(g)
    anno = f" {d.year}" if d.year != dt.date.today().year else ""
    return f"{GIORNI[d.weekday()]} {d.day} {MESI_LUNGHI[d.month - 1]}{anno}"


def riepilogo_ig(sito, notizie, adesso):
    """Il riepilogo serale di Instagram (strumenti/instagram.py): la copertina img/ig/oggi-<data>-<impronta>.jpg
    con le notizie più importanti di oggi e img/ig/oggi.json con la scelta. Con poche notizie niente (e via il json).
    Restituisce i file da tenere."""
    from PIL import Image, ImageDraw
    from facebook import fuso
    from instagram import ALMENO, del_giorno
    oggi = adesso.astimezone(fuso())
    scelte = del_giorno(notizie, oggi)
    pj = os.path.join(sito, "img", "ig", "oggi.json")
    if len(scelte) < ALMENO:
        if os.path.exists(pj):
            os.remove(pj)
        return set()
    giorno = f"{GIORNI[oggi.weekday()]} {oggi.day} {MESI_LUNGHI[oggi.month - 1]}"
    impronta = hashlib.sha1(json.dumps([giorno, 1] + [[n["id"], n["titolo"], _categoria(n), n.get("luogo")]
                                                      for n in scelte], ensure_ascii=False).encode()).hexdigest()[:8]
    rel = f"img/ig/oggi-{oggi.date().isoformat()}-{impronta}.jpg"
    full = os.path.join(sito, rel)
    if not os.path.exists(full):
        W, H = 1080, 1350
        im = Image.new("RGB", (W, H), "#fdeedd")
        d = ImageDraw.Draw(im)
        _testata(d, W)
        x = 60
        fo = _font(FONT_BOLD, 30)
        d.text((x, 205), "IL SANNIO OGGI", font=fo, fill="#c4161c", anchor="lm")
        d.text((x + fo.getlength("IL SANNIO OGGI") + 18, 205), giorno.upper(), font=fo, fill="#5b5249", anchor="lm")
        d.text((x, 285), "Le notizie della giornata", font=_font(FONT_BLACK, 66), fill="#111111", anchor="lm")
        xt = x + 84
        lt, alto, basso = W - 60 - xt, 370, H - 110
        for size in range(46, 28, -2):   # i titoli più grandi possibile, al massimo 3 righe l'uno
            ft = _font(FONT_BOLD, size)
            blocchi = [_a_capo(n["titolo"], ft, lt) for n in scelte]
            if sum(34 + min(len(b), 3) * size * 1.18 + 30 for b in blocchi) <= basso - alto:
                break
        fc, fn = _font(FONT_BOLD, 22), _font(FONT_BLACK, 34)
        y = alto
        for i, (n, b) in enumerate(zip(scelte, blocchi), 1):
            d.rounded_rectangle([x, y, x + 58, y + 58], radius=12, fill="#c4161c")
            d.text((x + 29, y + 30), str(i), font=fn, fill="#ffffff", anchor="mm")
            cat = " · ".join(([_categoria(n)] if n.get("categoria") in NOMI_CAT and n["categoria"] != "altro" else [])
                             + ([breve(n["luogo"], 30)] if n.get("luogo") else [])).upper()
            d.text((xt, y + 12), cat, font=fc, fill="#5b5249", anchor="lm")
            y += 34
            if len(b) > 3:
                b = b[:3]
                while ft.getlength(b[-1] + "…") > lt and " " in b[-1]:
                    b[-1] = b[-1].rsplit(" ", 1)[0]
                b[-1] = b[-1].rstrip(",;:.") + "…"
            for rg in b:
                d.text((xt, y), rg, font=ft, fill="#111111")
                y += size * 1.18
            y += 30
        d.rectangle([0, H - 14, W, H], fill="#c4161c")
        d.text((x, H - 56), "Scorri per leggerle · tutto su notiziebenevento.it", font=_font(FONT_BOLD, 30),
               fill="#111111", anchor="lm")
        os.makedirs(os.path.dirname(full), exist_ok=True)
        im.save(full, "JPEG", quality=88, optimize=True)
    with open(pj, "w", encoding="utf-8") as f:
        json.dump({"data": oggi.date().isoformat(), "giorno": giorno, "ids": [n["id"] for n in scelte],
                   "copertina": rel}, f, ensure_ascii=False)
    return {rel}


# ---------- chiusure dei Comuni (strumenti/chiusure.py) ----------
def chiusure_per_giorno(chiusure, oggi):
    """{giorno: [chiusure]} da oggi in poi, in ordine (una chiusura di più giorni sta sotto ognuno)."""
    per = {}
    for c in chiusure:
        if c.get("revocata"):
            continue
        for g in c.get("giorni") or []:
            if g >= oggi.isoformat():
                per.setdefault(g, []).append(c)
    return {g: sorted(per[g], key=lambda c: c["comune"]) for g in sorted(per)}


def _giorno_chiusura(g, oggi):
    d = dt.date.fromisoformat(g)
    nome = f"{GIORNI[d.weekday()]} {d.day} {MESI_LUNGHI[d.month - 1]}"
    if d == oggi:
        return f"Oggi, {nome}"
    if d == oggi + dt.timedelta(days=1):
        return f"Domani, {nome}"
    return nome[0].upper() + nome[1:]


def html_scuole_chiuse(dati, oggi):
    """La pagina «Scuole chiuse»: le chiusure di oggi e dei prossimi giorni, con l'ordinanza. index.html la ridisegna
    da chiusure.json appena si apre (NB_PAGINA.chiusure), così è sempre quella di adesso."""
    h = _testata_pagina("Chiusure dei Comuni", "", "Scuole chiuse nel Sannio", [("Servizi", "/servizi/"), ("Scuole chiuse", None)])
    h += ('<p class="sommario">Le scuole e gli altri luoghi che i Comuni della provincia di Benevento chiudono oggi e '
          'nei prossimi giorni, ognuno con la sua ordinanza. La pagina si aggiorna da sola, anche di notte.</p>')
    agg = dati.get("aggiornato")
    if agg:
        t = dt.datetime.fromisoformat(agg)
        h += (f'<p class="agg-chiusure" id="agg-chiusure">Aggiornato alle {t:%H:%M} di {GIORNI[t.weekday()]} '
              f'{t.day} {MESI_LUNGHI[t.month - 1]}.</p>')
    per = chiusure_per_giorno(dati.get("chiusure") or [], oggi)
    el_, con_id = "", set()   # l'id (…/scuole-chiuse/#id, i link dei messaggi di Telegram) sulla prima riga di ognuna
    for g, cs in per.items():
        el_ += f"<h3>{e(_giorno_chiusura(g, oggi))}</h3><ul class=\"chiusure\">"
        for c in cs:
            f = c.get("fonte") or {}
            ide = f' id="{e(c["id"])}"' if c.get("id") and c["id"] not in con_id else ""
            con_id.add(c.get("id"))
            el_ += (f"<li{ide}><b>{e(c['comune'])}</b>: {e(c['cosa'])}." + (f" {e(c['motivo'])}." if c.get("motivo") else "")
                    + (f' <a href="{e(f["url"])}" target="_blank" rel="noopener nofollow">{e(f.get("nome") or "Ordinanza")}</a>'
                       if str(f.get("url") or "").startswith("http") else "") + "</li>")
        el_ += "</ul>"
    if not per:
        el_ = "<p>Nessuna chiusura annunciata dai Comuni per oggi e per i prossimi giorni.</p>"
    h += f'<div id="elenco-chiusure">{el_}</div>'
    h += ('<p class="agg-chiusure">I siti dei Comuni li controlliamo ogni 5 minuti nei giorni di allerta e ogni 10 '
          'negli altri, giorno e notte: una chiusura nuova esce qui e sui nostri canali a qualsiasi ora.</p>')
    h += SEGUI
    return f'<article class="appro">{h}</article>'


def immagine_chiusure(sito, dati, adesso):
    """L'immagine delle chiusure per Instagram e Facebook (img/ig/chiusure-<impronta>.jpg, 1080×1350) e
    img/ig/chiusure.json col suo nome, per strumenti/chiusure_social.py. Restituisce i file da tenere."""
    from PIL import Image, ImageDraw
    from facebook import fuso
    oggi = adesso.astimezone(fuso()).date()
    per = chiusure_per_giorno(dati.get("chiusure") or [], oggi)
    pj = os.path.join(sito, "img", "ig", "chiusure.json")
    if not per:
        if os.path.exists(pj):
            os.remove(pj)
        return set()
    impronta = hashlib.sha1(json.dumps([dati.get("aggiornato"), 1] + [[g, [(c["comune"], c["cosa"]) for c in cs]]
                                                                       for g, cs in per.items()],
                                       ensure_ascii=False).encode()).hexdigest()[:8]
    rel = f"img/ig/chiusure-{impronta}.jpg"
    full = os.path.join(sito, rel)
    if not os.path.exists(full):
        W, H = 1080, 1350
        im = Image.new("RGB", (W, H), "#fdeedd")
        d = ImageDraw.Draw(im)
        _testata(d, W)
        x, larg = 60, W - 120
        fo = _font(FONT_BOLD, 30)
        d.text((x, 205), "CHIUSURE DEI COMUNI", font=fo, fill="#c4161c", anchor="lm")
        if dati.get("aggiornato"):
            ora = f"AGGIORNATO ALLE {dt.datetime.fromisoformat(dati['aggiornato']):%H:%M}"
            d.text((x + fo.getlength("CHIUSURE DEI COMUNI") + 18, 205), ora, font=fo, fill="#5b5249", anchor="lm")
        scuole = any("scuol" in c["cosa"].lower() for cs in per.values() for c in cs)
        d.text((x, 285), "Scuole chiuse" if scuole else "Chiusure dei Comuni", font=_font(FONT_BLACK, 70),
               fill="#111111", anchor="lm")
        alto, basso = 360, H - 110
        voci = [(g, c) for g, cs in per.items() for c in cs]

        def blocchi(size, quante):
            fc, fd = _font(FONT_BLACK, size), _font(FONT_BOLD, round(size * 0.8))
            out, g_prec = [], None
            for g, c in voci[:quante]:
                if g != g_prec:
                    out.append(("giorno", _giorno_chiusura(g, oggi).upper(), 30 + 18))
                    g_prec = g
                righe = _a_capo(c["cosa"], fd, larg)[:2]
                out.append(("voce", (c["comune"], righe, fc, fd), size * 1.15 + len(righe) * size * 0.8 * 1.2 + 16))
            return out

        quante, size = len(voci), 40
        while True:
            for size in range(40, 23, -2):
                bl = blocchi(size, quante)
                if sum(b[2] for b in bl) + (50 if quante < len(voci) else 0) <= basso - alto:
                    break
            else:
                quante -= 1
                continue
            break
        y = alto
        for tipo, val, alt in bl:
            if tipo == "giorno":
                d.text((x, y + 18), val, font=_font(FONT_BOLD, 30), fill="#c4161c", anchor="lm")
            else:
                comune, righe, fc, fd = val
                d.text((x, y), comune, font=fc, fill="#111111")
                yy = y + size * 1.15
                for r in righe:
                    d.text((x, yy), r, font=fd, fill="#5b5249")
                    yy += size * 0.8 * 1.2
            y += alt
        if quante < len(voci):
            d.text((x, y + 10), f"e altre {len(voci) - quante} chiusure: l'elenco completo è sul sito",
                   font=_font(FONT_BOLD, 30), fill="#c4161c")
        d.rectangle([0, H - 14, W, H], fill="#c4161c")
        d.text((x, H - 56), "Elenco con le ordinanze: notiziebenevento.it/scuole-chiuse", font=_font(FONT_BOLD, 30),
               fill="#111111", anchor="lm")
        os.makedirs(os.path.dirname(full), exist_ok=True)
        im.save(full, "JPEG", quality=88, optimize=True)
    with open(pj, "w", encoding="utf-8") as f:
        json.dump({"immagine": rel, "aggiornato": dati.get("aggiornato")}, f, ensure_ascii=False)
    return {rel}


# ---------- strade chiuse: le notizie con «traffico» (AGENTE.md) ----------
TRAFFICO = {"chiusa": "Strada chiusa", "blocchi": "Blocchi", "senso_unico": "Senso unico",
            "ristretta": "Carreggiata ristretta", "bus": "Bus deviati"}   # dal disagio più forte
GIORNI_SENZA_FINE = 3   # senza data di fine resta 3 giorni dall'ultima novità, come in prima pagina


def strade_chiuse(notizie, oggi):
    """(in vigore oggi, dei prossimi giorni): le notizie della prima pagina con «traffico» non ancora finite."""
    o, soglia = oggi.isoformat(), (oggi - dt.timedelta(days=GIORNI_SENZA_FINE - 1)).isoformat()
    ora, poi = [], []
    for n in sorted(notizie, key=lambda n: str(n.get("pubblicato") or ""), reverse=True):
        if n.get("traffico") not in TRAFFICO or n.get("_arch"):
            continue
        fino, dal = str(n.get("in_vigore_fino") or ""), str(n.get("in_vigore_dal") or "")
        ag = str(((n.get("articolo") or {}).get("aggiornamento") or {}).get("quando") or "")
        if fino and fino < o:
            continue
        if not fino and max(str(n.get("pubblicato") or "")[:10], ag[:10], dal) < soglia:
            continue
        (poi if dal > o else ora).append(n)
    peso = list(TRAFFICO)
    ora.sort(key=lambda n: (not n.get("rilevante"), peso.index(n["traffico"])))
    poi.sort(key=lambda n: (n["in_vigore_dal"], peso.index(n["traffico"])))
    return ora, poi


def _quando_strada(n, oggi):
    """«fino a venerdì 30 ottobre», «da sabato 31 ottobre a lunedì 2 novembre», «solo domani», «fine non annunciata»."""
    def g(x):
        d = dt.date.fromisoformat(x)
        return "oggi" if d == oggi else "domani" if d == oggi + dt.timedelta(days=1) else \
            f"{GIORNI[d.weekday()]} {d.day} {MESI_LUNGHI[d.month - 1]}"
    o, dal, fino = oggi.isoformat(), n.get("in_vigore_dal"), n.get("in_vigore_fino")
    if dal and dal > o:
        if fino == dal:
            return f"solo {g(dal)}"
        return f"da {g(dal)} " + (f"a {g(fino)}" if fino else "(fine non annunciata)")
    if fino == o:
        return "solo oggi" if dal == o else "fino a oggi"
    return f"fino a {g(fino)}" if fino else "fine non annunciata"


def _voci_strade(voci, oggi):
    h = '<ul class="notizie-comune">'
    for n in voci:
        f = next((x for x in vista_ufficiale(n).get("fonti") or [] if str(x.get("url") or "").startswith("http")), None)
        h += (f'<li><div class="occhiello">{e(TRAFFICO[n["traffico"]])}</div>'
              f'<a href="{percorso("notizia", n["id"])}">{e(n["titolo"])}</a><span class="dove">'
              + (f"{_luogo_link(n['luogo'])} · " if n.get("luogo") else "") + e(_quando_strada(n, oggi))
              + (f' · <a href="{e(f["url"])}" target="_blank" rel="noopener nofollow">{e(f.get("nome") or "Fonte")}</a>'
                 if f else "") + "</span></li>")
    return h + "</ul>"


def segnaposti_strade(ora, poi, oggi, luoghi=None):
    """I tondi della mappa in cima a «Strade chiuse» (punto 3 del piano, «dati che gli altri citano», 29 ott 2026): uno
    per strada, dove OpenStreetMap la mette (strumenti/strade_luoghi.py → strade-luoghi.json, `luoghi`); le strade che
    non trova, e le voci senza strada, al centro del paese (strumenti/comuni_coordinate.json), con «centro» se la strada
    c'era ma non è sulla mappa. Rosso se qualcosa vale oggi, arancione se solo nei prossimi giorni. Le voci senza un
    Comune nel «luogo» (una statale) restano solo nell'elenco."""
    from strade_luoghi import a_mano, chiave, strade_nel_testo
    with open(os.path.join(QUI, "comuni_coordinate.json"), encoding="utf-8") as f:
        coord = json.load(f)
    luoghi = {**(luoghi or {}), **a_mano()}   # quelle a mano valgono anche se la ricerca non è girata
    per = {}
    for n in ora + poi:
        comuni = comuni_di(n.get("luogo"))
        for i, c in enumerate(comuni):
            # le strade valgono per il primo Comune del luogo, come in strade_luoghi.py
            strade = strade_nel_testo(f"{n.get('luogo') or ''}\n{n.get('titolo') or ''}", comuni) if i == 0 else []
            punti = [(s, luoghi[chiave(c, s)]["lat"], luoghi[chiave(c, s)]["lon"]) for s in strade
                     if "lat" in (luoghi.get(chiave(c, s)) or {})]
            for s, lat, lon in punti or [("", coord[slug(c)]["lat"], coord[slug(c)]["lon"])]:
                p = per.setdefault((c, s), {"c": c, "s": s, "lat": lat, "lon": lon, "u": url_comune(c),
                                            "oggi": False, "voci": []})
                if not punti and strade:
                    p["centro"] = True
                p["oggi"] = p["oggi"] or n in ora
                p["voci"].append({"k": TRAFFICO[n["traffico"]], "t": n["titolo"], "u": percorso("notizia", n["id"]),
                                  "q": _quando_strada(n, oggi), **({"o": 1} if n in ora else {})})
    return sorted(per.values(), key=lambda p: (-len(p["voci"]), p["c"], p["s"]))


def html_strade_chiuse(ora, poi, oggi, aggiornato, segnaposti=()):
    h = _testata_pagina("Strade", "", "Strade chiuse a Benevento e nel Sannio", [("Servizi", "/servizi/"), ("Strade chiuse", None)])
    h += ('<p class="sommario">Le strade chiuse, i sensi unici, i lavori che restringono la strada, i blocchi e i bus '
          "deviati a Benevento e in provincia, oggi e nei prossimi giorni. Ogni voce porta alla notizia con le fonti: "
          "ordinanze dei Comuni, comunicati dell'ANAS e della Provincia, giornali locali.</p>")
    if segnaposti:   # la disegna index.html (NB_PAGINA.strade); senza JavaScript resta l'elenco qui sotto
        h += ('<figure class="mappa-strade"><div id="mappa-strade" role="region" aria-label="Mappa delle strade chiuse '
              'nel Sannio"></div><figcaption><span class="pin-leg oggi"></span>Oggi <span class="pin-leg poi"></span>'
              "Nei prossimi giorni · tocca un paese per vedere le strade</figcaption></figure>")
    t = quando_dt(aggiornato)
    if t:
        from facebook import fuso
        t = t.astimezone(fuso())
        h += (f'<p class="agg-chiusure">Aggiornato alle {t:%H:%M} di {GIORNI[t.weekday()]} {t.day} '
              f'{MESI_LUNGHI[t.month - 1]}.</p>')
    h += f"<h3>{e(_giorno_chiusura(oggi.isoformat(), oggi))}</h3>"
    h += _voci_strade(ora, oggi) if ora else "<p>Nessuna strada chiusa o con lavori annunciata per oggi.</p>"
    if poi:
        h += "<h3>Nei prossimi giorni</h3>" + _voci_strade(poi, oggi)
    h += ('<p class="agg-chiusure">Ogni ora leggiamo le ordinanze dei Comuni, i comunicati dell\'ANAS e della '
          "Provincia e i giornali locali. Le date sono quelle annunciate: un cantiere può finire prima o durare di più.</p>")
    h += '<p class="collegate"><a href="/sezione/strade/">Tutte le notizie sulle strade ›</a></p>'
    h += SEGUI
    return f'<article class="appro">{h}</article>'


# ---------- la pagina Avvisi (sezione/avvisi): anche per Google, con lo speciale di stagione ----------
# Lui, 28 ott 2026: «per me è difficile trovare info su quando le strade saranno chiuse, il cimitero quando è aperto»;
# poi, su una pagina a parte per Ognissanti, «anche se quella pagina tra qualche giorno non serve più, pensa una
# alternativa» → «fai 1»: la pagina Avvisi resta la stessa tutto l'anno e in cima cambia lo speciale del periodo, con il
# titolo per Google. È la stessa pagina che disegna paginaAvvisi() in index.html (SPECIALI, tipoAvviso, gruppi):
# scritta qui perché Google la legga anche senza JavaScript.
RX_DEFUNTI = re.compile(r"cimiter|defunt|ognissanti|lampade votive", re.I)
CAT_AVVISI = ("avvisi", "strade", "altro")   # le notizie che possono stare in uno speciale
SPECIALI = [
    {"da": "10-22", "a": "11-02", "rx": RX_DEFUNTI, "via": re.compile(r"loculi|bando", re.I),
     "occhiello": "Speciale · 1° e 2 novembre", "titolo": "Ognissanti e Defunti: cimiteri, strade e sosta paese per paese",
     "nota": "Gli orari dei cimiteri, le strade chiuse e i divieti annunciati dai Comuni.",
     "manca": "Il tuo paese non c'è? Il Comune non ha ancora pubblicato gli orari: li aggiungiamo appena escono. ",
     "title": "Avvisi Benevento: orari dei cimiteri per Ognissanti, strade chiuse e scadenze",
     "descr": "Gli orari dei cimiteri per Ognissanti e i Defunti, le strade chiuse e i divieti a Benevento e nei paesi "
              "del Sannio, Comune per Comune, e gli altri avvisi dei Comuni: uffici, acqua, rifiuti, scadenze."},
]


def speciale_di(oggi):
    """Lo speciale del periodo (anche a cavallo dell'anno, «12-15»…«01-06»), o None."""
    md = oggi.strftime("%m-%d")
    return next((x for x in SPECIALI if (x["da"] <= md <= x["a"] if x["da"] <= x["a"] else md >= x["da"] or md <= x["a"])), None)


def tipo_avviso(n):
    """L'etichetta rossa sopra il titolo, come tipoAvviso() di index.html."""
    t = str(n.get("titolo") or "")
    if n.get("traffico") in TRAFFICO:
        return TRAFFICO[n["traffico"]]
    regole = ((r"sciopero", "Sciopero"), (r"\btren[io]\b|ferrovi", "Treni"), (r"\bbus\b|autobus|capolinea|fermat", "Bus"),
              (r"parchegg", "Parcheggio"), (r"sosta", "Divieto di sosta"), (r"", "Strade")) if n.get("categoria") == "strade" else \
        ((r"domande|bando|bonus|elenc|iscrizion", "Domande e bandi"), (r"\bentro\b|scadenz", "Scadenza"),
         (r"cimiter|defunt|votive|loculi", "Cimitero"), (r"acqua|contatori|idric|alto calore", "Acqua"),
         (r"senza luce|\bluce\b|elettric", "Luce"), (r"rifiut|ingombrant|raccolta|ecocentro", "Rifiuti"),
         (r"vaccin|\basl\b|medic|ambulator", "Salute"), (r"sportell|uffic|passaporto|tributi", "Uffici"), (r"", "Avviso"))
    return next(nome for rx, nome in regole if re.search(rx, t, re.I))


def _quando_avviso(n, oggi):
    """Come quandoStrada() di index.html: le date dell'avviso, «scade…» per domande e scadenze, sennò quando è uscito."""
    if tipo_avviso(n) in ("Domande e bandi", "Scadenza"):
        return f"scade {_quando_strada(n, oggi)[len('fino a '):]}" if n.get("in_vigore_fino") else f"uscito il {data_it(n.get('pubblicato'), True)}"
    return _quando_strada(n, oggi) if n.get("in_vigore_fino") else f"uscito il {data_it(n.get('pubblicato'), True)}"


def _paese_avviso(n):
    cc = comuni_di(n.get("luogo"))
    return cc[0] if len(cc) == 1 else "Più Comuni" if cc else "Tutto il Sannio"


def _voce_avviso(n, oggi, paese=None):
    f = next((x for x in vista_ufficiale(n).get("fonti") or [] if str(x.get("url") or "").startswith("http")), None)
    titolo = n["titolo"][len(paese) + 2:] if paese and n["titolo"].startswith(paese + ", ") else n["titolo"]
    quanti = len(re.split(r",| e ", str(n.get("luogo") or "")))
    dove = "" if paese or not n.get("luogo") else (f"{quanti} Comuni · " if quanti > 3 else f"{_luogo_link(n['luogo'])} · ")
    return (f'<li><div class="occhiello">{e(tipo_avviso(n))}</div>'
            f'<a href="{percorso("notizia", n["id"])}">{e(titolo[:1].upper() + titolo[1:])}</a><span class="dove">{dove}'
            + e(_quando_avviso(n, oggi))
            + (f' · <a href="{e(f["url"])}" target="_blank" rel="noopener nofollow">{e(f.get("nome") or "Fonte")}</a>' if f else "")
            + "</span></li>")


def html_avvisi(notizie, oggi, h1):
    """La pagina Avvisi come la disegna paginaAvvisi() in index.html, con le notizie della prima pagina."""
    o = oggi.isoformat()
    vive = [n for n in notizie if not n.get("_arch") and str(n.get("in_vigore_fino") or "9") >= o]
    ultime = sorted((n for n in vive if n.get("categoria") in ("avvisi", "strade")), key=lambda n: str(n.get("pubblicato")), reverse=True)[:5]
    testa = f'<h1 class="titolo-sezione">{e(h1)}</h1><section class="ultimora">'
    for n in ultime:
        p = str(n.get("pubblicato"))
        ora = p[11:16] if p[:10] == o and len(p) > 10 else f"{int(p[8:10])} {MESI[int(p[5:7]) - 1]}"
        testa += f'<a href="{percorso("notizia", n["id"])}"><div class="ora">{e(ora)}</div><div class="tit">{e(n["titolo"])}</div></a>'
    testa += "</section>"
    h = ('<p class="sommario">Strade chiuse, scioperi, orari di cimiteri e uffici, acqua, luce, rifiuti, bandi e scadenze dei '
          "Comuni del Sannio: quello che serve sapere oggi e nei prossimi giorni, con il link alla fonte.</p>")
    h += ('<p class="avv-vai"><a href="/strade-chiuse/">Strade chiuse oggi ›</a><a href="/scuole-chiuse/">Scuole chiuse ›</a>'
          '<a href="/meteo.html">Meteo e allerte ›</a></p>')
    visti = set()
    sp = speciale_di(oggi)
    if sp:
        voci = [n for n in vive if n.get("categoria") in CAT_AVVISI and sp["rx"].search(n["titolo"]) and not sp["via"].search(n["titolo"])]
        if voci:
            per = {}
            for n in voci:
                per.setdefault(_paese_avviso(n), []).append(n)
                visti.add(n["id"])
            h += (f'<section class="avv-speciale"><div class="occhiello">{e(sp["occhiello"])}</div><h2>{e(sp["titolo"])}</h2>'
                  f'<p class="avv-nota">{e(sp["nota"])}</p><div class="avv-paesi">')
            for c in sorted(per, key=lambda c: (c != "Benevento", c)):
                tit = f'<a href="{url_comune(c)}">{e(c)}</a>' if _comune(c) else e(c)
                h += f'<div class="avv-paese"><h4>{tit}</h4><ul class="notizie-comune">'
                h += "".join(_voce_avviso(n, oggi, c) for n in per[c]) + "</ul></div>"
            h += (f'</div><p class="avv-nota">{e(sp["manca"])}Intanto guarda la pagina del tuo <a href="/comuni/">Comune</a>.</p>'
                  "</section>")
    def recente(n, giorni):
        try:
            return (oggi - dt.date.fromisoformat(str(n.get("pubblicato"))[:10])).days < giorni
        except ValueError:
            return False
    avv = [n for n in vive if n.get("categoria") in ("avvisi", "strade") and n["id"] not in visti
           and (n.get("in_vigore_fino") or recente(n, 2 if n["categoria"] == "strade" else 7))]
    domande = [n for n in avv if tipo_avviso(n) in ("Domande e bandi", "Scadenza")]
    avv = [n for n in avv if n not in domande]
    in_corso = sorted((n for n in avv if n.get("in_vigore_fino") and str(n.get("in_vigore_dal") or "") <= o),
                      key=lambda n: n["in_vigore_fino"])
    poi = sorted((n for n in avv if str(n.get("in_vigore_dal") or "") > o), key=lambda n: n["in_vigore_dal"])
    resto = [n for n in avv if n not in in_corso and n not in poi]
    for titolo, gruppo in ((f"Oggi, {GIORNI[oggi.weekday()]} {oggi.day} {MESI_LUNGHI[oggi.month - 1]}", in_corso),
                           ("Nei prossimi giorni", poi), ("Domande e scadenze", domande), ("Da sapere", resto)):
        if gruppo:
            h += f'<h3>{e(titolo)}</h3><ul class="notizie-comune">' + "".join(_voce_avviso(n, oggi) for n in gruppo) + "</ul>"
    h += ('<p class="agg-chiusure">Ogni ora leggiamo gli albi e i siti dei 78 Comuni, i comunicati ufficiali e i giornali '
          "locali. Le date sono quelle annunciate: un orario o un cantiere possono cambiare.</p>")
    return testa + f'<article class="appro avvisi-pag">{h}</article>'


# ---------- i contributi (strumenti/contributi.py → contributi.json): la pagina e una per contributo ----------
# Come paginaContributi() in index.html, che ridisegna /agevolazioni/ con i filtri che funzionano; qui per Google e per
# chi non ha JavaScript. Ogni contributo del catalogo e dei locali ha la sua pagina con il testo ufficiale.
from contributi import CHI as CHI_CONTR, DA as DA_CONTR, TEMI as TEMI_CONTR, AIUTO as AIUTO_CONTR   # noqa: E402
DOVE_CONTR = {"sannio": "Solo Sannio", "campania": "Campania", "sud": "Sud Italia", "italia": "Italia", "europa": "Europa"}
TITOLO_CONTR = "Agevolazioni a Benevento e nel Sannio"
# la pagina si chiamava «Contributi» (/contributi/) fino al 28 ott 2026 sera: lui «ho deciso di cambiare nome… la pagina
# deve uscire come /agevolazioni/». I vecchi indirizzi portano ai nuovi (vedi sotto, «i vecchi indirizzi /contributi/»).
CART_AGEV = "agevolazioni"


def _giorno_contr(g):
    d = dt.date.fromisoformat(g)
    return f"{GIORNI[d.weekday()]} {d.day} {MESI_LUNGHI[d.month - 1]}"


def _scadenza_contr(v, oggi):
    """(testo, urgente) come scadenzaContr() in index.html."""
    o = oggi.isoformat()
    cd = str(v.get("click_day") or "")
    if cd[:10] >= o and cd:
        return f"Click day {'oggi' if cd[:10] == o else _giorno_contr(cd[:10])} alle {cd[11:16]}", (dt.date.fromisoformat(cd[:10]) - oggi).days <= 7
    if v.get("apertura") and v["apertura"] > o:
        return f"Apre {_giorno_contr(v['apertura'])}" + (f", scade {_giorno_contr(v['scadenza'])}" if v.get("scadenza") else ""), False
    if v.get("scadenza"):
        n = (dt.date.fromisoformat(v["scadenza"]) - oggi).days
        if n < 0:
            return f"Scaduto {_giorno_contr(v['scadenza'])}", False
        return f"Scade {_giorno_contr(v['scadenza'])} · {'oggi' if n == 0 else 'domani' if n == 1 else f'fra {n} giorni'}", n <= 7
    t = v.get("scadenza_testo") or "Senza scadenza indicata"
    return t[:1].upper() + t[1:], False


def _link_contr(v):
    return v.get("pagina") or f"/{CART_AGEV}/{v['id']}/"


def _scheda_contr(v, oggi):
    h = (f'<article class="contr"><div class="occhiello">{e(v["ente"])} · {e(DOVE_CONTR.get(v.get("dove"), ""))}</div>'
         f'<h3><a href="{e(_link_contr(v))}">{e(v["titolo"])}</a></h3>')
    if v.get("cose"):
        c = v["cose"] if len(v["cose"]) <= 190 else re.sub(r"\s+\S*$", "", v["cose"][:190]) + "…"
        h += f'<p class="contr-cose">{e(c)}</p>'
    fatti = []
    per = [CHI_CONTR[k] for k in v.get("chi") or [] if k in CHI_CONTR]
    if per:
        fatti.append(f"<li><b>Per: </b>{e(', '.join(per))}</li>")
    if v.get("forma"):
        fatti.append(f"<li><b>Cosa: </b>{e(v['forma'])}</li>")
    if v.get("quanto"):
        fatti.append(f"<li><b>Quanto: </b>{e(v['quanto'])}</li>")
    if fatti:
        h += '<ul class="contr-fatti">' + "".join(fatti) + "</ul>"
    t, urg = _scadenza_contr(v, oggi)
    h += f'<div class="contr-scad{" urgente" if urg else ""}">{e(t)}</div>'
    if v.get("link"):
        h += f'<div class="contr-link"><a href="{e(v["link"])}" target="_blank" rel="noopener nofollow">Sito ufficiale ›</a></div>'
    return h + "</article>"


def contributi_dei_comuni(notizie, oggi):
    """Gli aiuti dei Comuni dalle notizie segnate "contributo" dall'agente, come contributiDeiComuni() in index.html."""
    o, out = oggi.isoformat(), []
    for n in notizie:
        cn = n.get("contributo") if isinstance(n.get("contributo"), dict) else {}
        chi = [k for k in cn.get("chi") or [] if k in CHI_CONTR]
        if n.get("_arch") or not chi or str(n.get("in_vigore_fino") or "9") < o:
            continue
        f = next((x for x in vista_ufficiale(n).get("fonti") or [] if str(x.get("url") or "").startswith("http")), None)
        c = _paese_avviso(n)
        out.append({"id": "notizia-" + n["id"], "titolo": n["titolo"], "ente": c if c in ("Più Comuni", "Tutto il Sannio") else f"Comune di {c}",
                    "dove": "sannio", "chi": chi, "da": ["comune"], "temi": [k for k in cn.get("temi") or [] if k in TEMI_CONTR],
                    "aiuto": [k for k in cn.get("aiuto") or [] if k in AIUTO_CONTR], "forma": "", "quanto": "",
                    "scadenza": n.get("in_vigore_fino"), "scadenza_testo": cn.get("quando") or None,
                    "link": f["url"] if f else "", "cose": n.get("sintesi") or "",
                    "pagina": percorso("notizia", n["id"]), "aggiunto": str(n.get("pubblicato") or "")[:10]})
    return out


def html_contributi(voci, oggi, aggiornato):
    o = oggi.isoformat()
    nuovi = sorted(voci, key=lambda v: str(v.get("aggiunto") or ""), reverse=True)[:5]
    h = f'<h1 class="titolo-sezione">{e(TITOLO_CONTR)}</h1>'
    if nuovi:
        h += '<section class="ultimora">' + "".join(
            f'<a href="{e(_link_contr(v))}"><div class="ora">{"oggi" if v.get("aggiunto") == o else e(data_it(v.get("aggiunto"))[:-5])}</div>'
            f'<div class="tit">{e(v["titolo"])}</div></a>' for v in nuovi) + "</section>"
    click = [v for v in voci if str(v.get("click_day") or "")[:10] >= o and v.get("click_day")]
    h += (f'<p class="contr-riepilogo">{"1 agevolazione aperta" if len(voci) == 1 else f"{len(voci)} agevolazioni aperte"}' + (f" · {len(click)} click day in arrivo" if click else "") + "</p>")
    righe = ""
    for etichetta, chiave, valori in (("Chi sei?", "chi", CHI_CONTR), ("Da chi?", "da", DA_CONTR), ("Per cosa?", "temi", TEMI_CONTR),
                                      ("Che aiuto?", "aiuto", AIUTO_CONTR)):
        b = "".join(f'<button type="button" aria-pressed="false">{e(nome)}<span class="n"> {n}</span></button>'
                    for k, nome in valori.items()
                    for n in [sum(1 for v in voci if k in (v.get(chiave) or []))] if n)
        righe += (f'<div class="contr-riga"><span class="contr-etichetta">{etichetta}</span><div class="contr-bottoni">'
                  f'<button type="button" aria-pressed="true">Tutti</button>{b}</div></div>')
    h += (f'<section class="contr-filtri"><div>{righe}</div><div class="contr-cerca"><input type="search" '
          'placeholder="Cerca: fotovoltaico, bar, affitto, assunzioni…" aria-label="Cerca tra le agevolazioni"></div></section>')
    h += f'<section class="contr-elenco"><h3 class="titolo-col">{len(voci)} agevolazioni, in ordine di scadenza</h3><div class="contr-lista">'
    h += "".join(_scheda_contr(v, oggi) for v in voci) + "</div></section>"
    h += ('<p class="contr-nota">Fonti: Catalogo degli incentivi del Ministero delle Imprese e del Made in Italy (incentivi.gov.it, '
          "dati aperti IODL 2.0) e, controllati ogni giorno sui siti ufficiali, INPS, Agenzia delle Entrate, Invitalia, Regione "
          "Campania, Camera di Commercio Irpinia Sannio, Unione europea, fondazioni e Comuni del Sannio. Prima di fare "
          "domanda leggi sempre il bando ufficiale: date e importi possono cambiare. Manca un contributo? Scrivi a "
          '<a href="mailto:redazione@notiziebenevento.it">redazione@notiziebenevento.it</a>.</p>')
    return h


def html_contributo(v, oggi):
    """La pagina di un contributo: i fatti in breve e il testo ufficiale della scheda (regola 3 delle pagine)."""
    h = (_percorso([("Agevolazioni", f"/{CART_AGEV}/")]) + f'<div class="occhiello">Agevolazioni · '
         f'{e(DOVE_CONTR.get(v.get("dove"), ""))}</div><h1>{e(v["titolo"])}</h1>')
    h += f'<div class="meta">{e(v["ente"])}</div>'
    t, urg = _scadenza_contr(v, oggi)
    if v.get("scaduto"):
        h += f'<div class="nota">È scaduto ({e(_giorno_contr(v["scadenza"]))}). Guarda le agevolazioni <a href="/{CART_AGEV}/">ancora aperte</a>.</div>'
    righe = [("Chi può chiederlo", ", ".join(CHI_CONTR[k] for k in v.get("chi") or [] if k in CHI_CONTR)),
             ("Chi lo dà", ", ".join(DA_CONTR[k] for k in v.get("da") or [] if k in DA_CONTR)),
             ("Che cosa è", v.get("forma") or ""), ("Quanto", v.get("quanto") or ""), ("Scadenza", t),
             ("Per cosa", ", ".join(TEMI_CONTR[k] for k in v.get("temi") or [] if k in TEMI_CONTR))]
    h += '<dl class="contr-dati">' + "".join(f"<dt>{e(a)}</dt><dd>{e(b)}</dd>" for a, b in righe if b) + "</dl>"
    h += (f'<p class="contr-vai"><a href="{e(v["link"])}" target="_blank" rel="noopener nofollow">Vai al bando ufficiale per fare '
          "domanda ›</a></p>")
    for titolo, k in (("Cos'è", "cose"), ("A chi si rivolge", "a_chi"), ("Cosa prevede", "cosa_prevede"), ("Come si chiede", "come")):
        if v.get(k):
            h += f"<h3>{titolo}</h3><p>{e(v[k])}</p>"
    if v.get("fonte") == "catalogo":
        h += (f'<p class="agg-chiusure">Testo della scheda del <a href="{e(v.get("scheda") or "https://www.incentivi.gov.it")}" '
              'target="_blank" rel="noopener nofollow">Catalogo degli incentivi</a> del Ministero delle Imprese e del Made in Italy '
              f'(dati aperti IODL 2.0){", aggiornata il " + e(data_it(v["aggiornato_fonte"], True)) if v.get("aggiornato_fonte") else ""}. '
              "Prima di fare domanda leggi sempre il bando ufficiale.</p>")
    else:
        h += (f'<p class="agg-chiusure">Controllato il {e(data_it(v.get("controllato"), True))} sul sito ufficiale. Prima di fare '
              "domanda leggi sempre il bando ufficiale.</p>")
    h += f'<p class="collegate"><a href="/{CART_AGEV}/">Tutte le agevolazioni per Benevento e il Sannio ›</a></p>'
    return f'<article class="appro">{h}</article>'


# ---------- prezzi dei carburanti (strumenti/carburanti.py → carburanti.json) ----------
NOMI_CARBURANTI = {"benzina": "Benzina", "gasolio": "Diesel", "gpl": "GPL", "metano": "Metano"}


def _euro(x):
    return f"{x:.3f}".replace(".", ",")


def _nome_distributore(i):
    """Il marchio; per le pompe bianche il nome dell'impianto, se non è solo il paese (come in index.html)."""
    if i["bandiera"] == "Pompa bianca" and i["nome"] and i["nome"] != i["comune"]:
        return i["nome"]
    return i["bandiera"]


def _classifica(dati, tipo, quanti):
    """I distributori meno cari della provincia (prezzo self recente), per chi legge senza JavaScript e per Google: gli
    altri vedono la lista con paese e carburante (index.html)."""
    per = {i["id"]: i for i in dati.get("impianti") or []}
    righe = ""
    for n, k in enumerate((dati.get("classifiche") or {}).get(tipo, [])[:quanti], 1):
        i = per[k]
        # i link interi: con <base href="/"> un «#d…» da solo porta alla prima pagina (lo ha visto il proprietario)
        righe += (f'<tr><td>{n}</td><td class="pr">{_euro(i["prezzi"][tipo]["self"]["prezzo"])}</td>'
                  f'<td><a href="/carburanti/#d{e(k)}">{e(_nome_distributore(i))}</a> <span>{e(i["comune"])}'
                  + (f", {e(i['indirizzo'])}" if i["indirizzo"] else "") + "</span></td></tr>")
    return f'<table class="prezzi"><thead><tr><th></th><th>€/litro</th><th>Distributore</th></tr></thead><tbody>{righe}</tbody></table>'


def _per_lista(i, tipo):
    """Il prezzo con cui un distributore va in ordine nella lista di un carburante («1.989 self»): il self comunicato
    di recente; per GPL e metano, che quasi ovunque si fanno col servito, anche il servito."""
    p = i["prezzi"].get(tipo) or {}
    for m in ("self", "servito") if tipo in ("gpl", "metano") else ("self",):
        if (p.get(m) or {}).get("valido"):
            return f'{p[m]["prezzo"]:.3f} {m}'
    return ""


def html_carburanti(dati, oggi):
    h = _testata_pagina("Carburanti", "", "Prezzi di benzina e diesel a Benevento e provincia", [("Servizi", "/servizi/"), ("Carburanti", None)])
    h += ('<p class="sommario">I prezzi di benzina, diesel, GPL e metano di tutti i distributori della provincia di '
          "Benevento, self e servito, dal meno caro. Sono i prezzi che i gestori comunicano al Ministero delle Imprese "
          "e del Made in Italy: li aggiorniamo ogni mattina.</p>")
    impianti = dati.get("impianti") or []
    if not impianti:
        h += "<p>I prezzi del Ministero ora non sono disponibili: riprova più tardi.</p>" + SEGUI
        return f'<article class="appro">{h}</article>'
    d = dt.date.fromisoformat(dati["estrazione"])
    medie = dati.get("medie_self") or {}
    h += (f'<p class="agg-chiusure">Prezzi in vigore {GIORNI[d.weekday()]} {d.day} {MESI_LUNGHI[d.month - 1]} alle 8, '
          f"per {len(impianti)} distributori." + (f" Media in provincia, self: benzina {_euro(medie['benzina'])} €, "
                                                   f"diesel {_euro(medie['gasolio'])} €." if medie.get("benzina") and medie.get("gasolio") else "")
          + "</p>")
    per_comune = {}
    for i in impianti:
        per_comune.setdefault(i["comune"], []).append(i)
    # La pagina che si usa, voluta dal proprietario il 25 ott 2026 («un filtro a tendina per comune, di default
    # Benevento», «anche tutti», «mostrali tutti, non solo i primi 10», «ripensa la pagina»): paese e carburante, poi
    # tutti i distributori dal meno caro. La accende index.html spostando lì le schede scritte più sotto; senza
    # JavaScript, e per Google, restano le classifiche dei 10 meno cari e i distributori paese per paese.
    h += ('<div class="cb-vivo" hidden><div class="cb-comandi"><label>Paese <select id="cb-paese">'
          f'<option value="">Tutti i paesi ({len(impianti)})</option>'
          + "".join(f'<option value="{e(c)}">{e(c)} ({len(v)})</option>' for c, v in sorted(per_comune.items()))
          + '</select></label><div class="cb-scelta">'
          + "".join(f'<button type="button" data-tipo="{t}">{n}</button>' for t, n in NOMI_CARBURANTI.items())
          + '</div></div><p class="cb-riepilogo"></p><ul class="notizie-comune distributori cb-lista"></ul></div>')
    h += '<div class="cb-statico">'
    h += "<h3>Benzina self, i 10 meno cari</h3>" + _classifica(dati, "benzina", 10)
    h += "<h3>Diesel self, i 10 meno cari</h3>" + _classifica(dati, "gasolio", 10)
    h += "<h3>Tutti i distributori, paese per paese</h3>"
    h += '<ul class="elenco-comuni">' + "".join(
        f'<li><a href="/carburanti/#c-{slug(c)}">{e(c)}</a> <span>{len(v)}</span></li>'
        for c, v in sorted(per_comune.items())) + "</ul>"
    for c, v in sorted(per_comune.items()):
        h += (f'<h4 class="cb-comune" id="c-{slug(c)}" data-comune="{e(c)}">{e(c)}</h4>'
              '<ul class="notizie-comune distributori">')
        for i in v:
            try:   # i numeri si controllano: il file arriva da fuori (il Pi, attraverso la pubblicazione)
                mappa = (f' · <a href="https://www.google.com/maps/search/?api=1&amp;query={float(i["lat"])},'
                         f'{float(i["lon"])}" target="_blank" rel="noopener nofollow">mappa</a>')
            except (KeyError, TypeError, ValueError):
                mappa = ""
            righe, quando = "", []
            for tipo, nome in NOMI_CARBURANTI.items():
                p = i["prezzi"].get(tipo) or {}
                parti = [f"{_euro(p[m]['prezzo'])} {m}" for m in ("self", "servito") if m in p]
                if parti:
                    righe += f"<span><b>{nome}</b> {' · '.join(parti)}</span>"
                    quando += [p[m]["dt"][:10] for m in ("self", "servito") if m in p]
            ultimo = dt.date.fromisoformat(max(quando))
            vecchio = not any((i["prezzi"].get(t) or {}).get(m, {}).get("valido") for t in NOMI_CARBURANTI for m in ("self", "servito"))
            # il nome dell'impianto dei marchi è spesso un codice interno («8336 Telese Terme»): si mostra l'indirizzo
            nome = i["nome"] if i["bandiera"] == "Pompa bianca" else ""
            in_lista = "".join(f' data-{t}="{x}"' for t in NOMI_CARBURANTI for x in [_per_lista(i, t)] if x)
            h += (f'<li id="d{e(i["id"])}" data-comune="{e(c)}"{in_lista}><div class="cb-grande" hidden></div>'
                  f'<div class="cb-testo"><div class="occhiello">{e(i["bandiera"])}</div>'
                  f'<b class="cb-nome">{e(i["indirizzo"] or i["nome"] or c)}</b>'
                  f'<span class="dove">{e(nome + " · " if nome else "")}{e(c)}{mappa}</span><p class="cb-prezzi">{righe}</p>'
                  f'<span class="dove">{"⚠️ prezzi vecchi: " if vecchio else ""}comunicati il {ultimo.day} '
                  f'{MESI_LUNGHI[ultimo.month - 1]}</span></div></li>')
        h += "</ul>"
    h += "</div>"
    h += (f'<p class="agg-chiusure">In ordine di prezzo ci sono solo i prezzi comunicati negli ultimi '
          f'{dati.get("giorni_validi", 8)} giorni: self per benzina e diesel, anche servito per GPL e metano. Il prezzo '
          "giusto è sempre quello sul cartello alla pompa.</p>")
    h += ('<p class="agg-chiusure">Fonte: <a href="https://www.mimit.gov.it/it/open-data/elenco-dataset/carburanti-prezzi-'
          'praticati-e-anagrafica-degli-impianti" target="_blank" rel="noopener nofollow">Ministero delle Imprese e del '
          "Made in Italy, Osservatorio prezzi carburanti</a> (dati aperti, licenza IODL 2.0). I prezzi li comunicano i "
          "gestori: un distributore può averli cambiati dopo.</p>")
    h += '<p class="collegate"><a href="/strade-chiuse/">Strade chiuse oggi ›</a></p>'
    h += SEGUI
    return f'<article class="appro">{h}</article>'


# ---------- Servizi: la pagina che li raccoglie e le farmacie di turno (strumenti/farmacie.py → farmacie.json) ----------
# Lui, 29 ott 2026: «facciamo pagina servizi la metti nel menu dopo avvisi», «stesso stile del sito per tutto», «ok
# sottolinea servizi» (nel menu «Servizi» è sottolineata qui e nelle pagine dei servizi: regola 1 delle pagine,
# CLAUDE.md). Le farmacie sono la prima pagina nuova: Benevento città (Federfarma Benevento) e i paesi, zona per zona
# (Ordine dei Farmacisti: strumenti/farmacie_paesi.py), scelti con «Il tuo paese» (lui: «ok va bene fai così»).
# Gli orari si calcolano qui, una volta sola (fasce_citta, fasce_zona), e vanno in farmacie-fasce.json: da lì index.html
# rifà «adesso» nella pagina, nelle pagine dei Comuni e nel riquadro della prima pagina, così alle 13, alle 16:30, alle
# 20 e alle 8:45 cambia da solo anche senza una pubblicazione nuova. Negli orari normali della città: «Sono aperte tutte
# le farmacie» (lui: «si scrivi aperte tutte le farmacie»); il turno «diurno» del PDF di Federfarma è il «servizio
# pomeridiano e festivo» dell'Ordine: la pausa del pomeriggio, il sabato pomeriggio, la domenica e i festivi.
# Prima il turno in corso con l'ora di fine, poi il prossimo con inizio e fine (lui: «prima il turno in atto e poi il
# successivo»); il nome di quello in corso un po' più grande.

# i giorni di festa (le farmacie fanno il turno festivo): le feste nazionali, Pasqua e Pasquetta, e il 24 agosto, San
# Bartolomeo, patrono di Benevento
FESTE = {(1, 1), (1, 6), (4, 25), (5, 1), (6, 2), (8, 15), (8, 24), (11, 1), (12, 8), (12, 25), (12, 26)}
SERVIZI_FARMACIA = {"pomeridiano": "servizio pomeridiano", "festivo": "servizio festivo", "notturno": "servizio notturno",
                    "turno": "farmacia di turno"}


def pasqua(a):
    """La domenica di Pasqua (calendario gregoriano, algoritmo di Meeus)."""
    aa, (b, c) = a % 19, divmod(a, 100)
    d, e_ = divmod(b, 4)
    g = (b - (b + 8) // 25 + 1) // 3
    h = (19 * aa + b - d - g + 15) % 30
    i, k = divmod(c, 4)
    l_ = (32 + 2 * e_ + 2 * i - h - k) % 7
    m = (aa + 11 * h + 22 * l_) // 451
    mese, giorno = divmod(h + l_ - 7 * m + 114, 31)
    return dt.date(a, mese, giorno + 1)


def festivo(d):
    return d.weekday() == 6 or (d.month, d.day) in FESTE or d in (pasqua(d.year), pasqua(d.year) + dt.timedelta(days=1))


def _ora_breve(s):
    return s[1:] if s.startswith("0") else s


def _giorno_lungo(iso):
    d = dt.date.fromisoformat(iso[:10])
    return f"{GIORNI[d.weekday()]} {'1°' if d.day == 1 else d.day} {MESI_LUNGHI[d.month - 1]}"


def _giorni_turno(x):
    a, b = dt.date.fromisoformat(x["dal"]), dt.date.fromisoformat(x["al"])
    g = lambda d: "1°" if d.day == 1 else str(d.day)   # noqa: E731
    if a == b:
        return f"{GIORNI[a.weekday()]} {g(a)} {MESI_LUNGHI[a.month - 1]}"
    if a.month == b.month:
        return f"dal {g(a)} al {g(b)} {MESI_LUNGHI[b.month - 1]}"
    return f"dal {g(a)} {MESI_LUNGHI[a.month - 1]} al {g(b)} {MESI_LUNGHI[b.month - 1]}"


def _farm(x, comune=""):
    return {"nome": x["nome"], "indirizzo": x.get("indirizzo") or "", "telefono": x.get("telefono") or "",
            "via_mappa": x.get("via_mappa") or "", "comune": comune or x.get("comune") or ""}


def _fascia(da_d, da_o, a_d, a_o, tipo, servizio=None, f=None, anche=""):
    return {"da": f"{da_d.isoformat()}T{da_o}", "a": f"{a_d.isoformat()}T{a_o}", "tipo": tipo, "servizio": servizio,
            "farmacia": _farm(f, "Benevento") if f else None, "anche": anche}


def fasce_citta(dati, oggi, giorni=10):
    """Le fasce di Benevento città da ieri a `giorni` giorni: «tutte» negli orari normali, il turno pomeridiano nella
    pausa e il sabato pomeriggio, il festivo la domenica e nelle feste, il notturno dalle 20 alle 8:45."""
    note, orari = dati.get("note") or {}, dati.get("orari") or {}
    notte = note.get("notte") or {"dalle": "20:00", "alle": "08:45"}
    fer = orari.get("feriali") if len(orari.get("feriali") or []) == 2 else [["08:45", "13:00"], ["16:30", "20:00"]]
    sab = orari.get("sabato") or [["08:45", "13:00"]]
    trova = lambda k, d: next((x for x in dati.get(k) or [] if x["dal"] <= d.isoformat() <= x["al"]), None)   # noqa: E731
    c = note.get("continuato") or {}
    anche_fer = f"Aperte anche, con l'orario continuato: {c['farmacie']}." if c.get("farmacie") else ""
    anche_sab = f"Aperte anche il sabato pomeriggio: {note['sabato_pomeriggio']}." if note.get("sabato_pomeriggio") else ""
    out = []
    for k in range(-1, giorni):
        d = oggi + dt.timedelta(days=k)
        di = trova("diurno", d)
        if festivo(d):
            out.append(_fascia(d, notte["alle"], d, notte["dalle"], "turno", "festivo", di))
        elif d.weekday() == 5:
            out.append(_fascia(d, notte["alle"], d, sab[0][1], "tutte"))
            out.append(_fascia(d, sab[0][1], d, notte["dalle"], "turno", "pomeridiano", di, anche_sab))
        else:
            out.append(_fascia(d, notte["alle"], d, fer[0][1], "tutte"))
            out.append(_fascia(d, fer[0][1], d, fer[1][0], "turno", "pomeridiano", di, anche_fer))
            out.append(_fascia(d, fer[1][0], d, notte["dalle"], "tutte"))
        out.append(_fascia(d, notte["dalle"], d + dt.timedelta(days=1), notte["alle"], "turno", "notturno", trova("notturno", d)))
    return out


def fasce_zona(z, oggi, settimane=9):
    """Le fasce di una zona dei paesi: un turno dopo l'altro, dal giorno e all'ora del cambio (le ore del PDF)."""
    ora = (z.get("cambio") or {}).get("ora") or "09:00"
    turni = z.get("turni") or []
    da, a = (oggi - dt.timedelta(days=21)).isoformat(), (oggi + dt.timedelta(days=7 * settimane)).isoformat()
    out = []
    for i, t in enumerate(turni):
        if t["al"] < da or t["dal"] > a:
            continue
        f = z["farmacie"][t["farmacia"]]
        fine = turni[i + 1]["dal"] if i + 1 < len(turni) else t["al"]   # «fino al 09/01» e poi «dal 10/01»: il cambio è il 10
        out.append({"da": f"{t['dal']}T{ora}", "a": f"{fine}T{ora}", "tipo": "turno", "servizio": "turno",
                    "farmacia": _farm(f), "anche": ""})
    return out


def adesso_e_poi(fasce, adesso):
    """(la fascia di adesso o None, la prossima o None)."""
    ora = adesso.strftime("%Y-%m-%dT%H:%M")
    for i, f in enumerate(fasce):
        if f["da"] <= ora < f["a"]:
            return f, fasce[i + 1] if i + 1 < len(fasce) else None
    return None, next((f for f in fasce if f["da"] > ora), None)


def etichetta_adesso(f, adesso, cambio=""):
    oggi, domani = adesso.date().isoformat(), (adesso.date() + dt.timedelta(days=1)).isoformat()
    a_d, a_o = f["a"][:10], _ora_breve(f["a"][11:])
    if a_d == oggi:
        return f"Adesso, fino alle {a_o}"
    if a_d == domani and not cambio:
        return f"Adesso, fino alle {a_o} di domani"
    return f"Adesso, fino a {_giorno_lungo(a_d)}" + (f" ({cambio})" if cambio else "")


def etichetta_poi(f, adesso, cambio=""):
    oggi, domani = adesso.date().isoformat(), (adesso.date() + dt.timedelta(days=1)).isoformat()
    da_d, da_o, a_d, a_o = f["da"][:10], _ora_breve(f["da"][11:]), f["a"][:10], _ora_breve(f["a"][11:])
    if cambio or da_d not in (oggi, domani):
        return f"Da {_giorno_lungo(da_d)}" + (f" ({cambio})" if cambio else "")
    base = f"Dalle {da_o}" if da_d == oggi else f"Domani dalle {da_o}"
    if a_d == da_d:
        return f"{base} alle {a_o}"
    return f"{base} alle {a_o} " + ("di domani" if da_d == oggi else "del giorno dopo")


def _mappa_farmacia(x):
    q = urllib.parse.quote(f"Farmacia {x['nome']}, {x.get('via_mappa') or x.get('indirizzo') or ''}, {x.get('comune') or 'Benevento'}")
    return f'<a href="https://www.google.com/maps/search/?api=1&amp;query={q}" target="_blank" rel="noopener nofollow">mappa</a>'


def _telefono(x):
    """Il numero della farmacia (dall'elenco di Federfarma, strumenti/farmacie.py), da chiamare con un tocco."""
    t = re.sub(r"\D", "", str(x.get("telefono") or ""))
    if not re.match(r"^(0\d{5,10}|3\d{8,9})$", t):
        return ""
    return f'<a href="tel:+39{t}">{t[:3] + " " + t[3:] if t.startswith("3") else t[:4] + " " + t[4:]}</a> · '


def _dove_farmacia(x, con_comune=False):
    pezzi = [e(x["comune"])] if con_comune and x.get("comune") else []
    via = x.get("indirizzo") or bello_via(x.get("via_mappa") or "")
    if via:
        pezzi.append(e(via))
    return f'<span class="dove">{" · ".join(pezzi)}{" · " if pezzi else ""}{_telefono(x)}{_mappa_farmacia(x)}</span>'


def bello_via(s):
    """«VIA ROMA 24» → «Via Roma 24» (l'indirizzo dell'elenco di Federfarma)."""
    s = re.sub(r"\b([A-ZÀ-Ý])([A-ZÀ-Ý']+)\b", lambda m: m.group(1) + m.group(2).lower(), s)
    s = re.sub(r"\b(Di|Del|Della|Delle|Dei|Degli|De|Da|E)\b", lambda m: m.group(0).lower(), s)
    return s[:1].upper() + s[1:]


def html_adesso(fasce, adesso, cambio="", con_comune=False, manca=""):
    """Il riquadro «adesso»: prima la fascia in corso (il nome un po' più grande), poi la prossima."""
    cur, poi = adesso_e_poi(fasce, adesso)
    h = f'<div class="occhiello">{e(_giorno_chiusura(adesso.date().isoformat(), adesso.date()))}</div><ul class="notizie-comune">'
    for i, (f, quando) in enumerate(((cur, etichetta_adesso(cur, adesso, cambio) if cur else "Adesso"),
                                     (poi, etichetta_poi(poi, adesso, cambio) if poi else ""))):
        cls = ' class="in-corso"' if i == 0 else ""
        if f is None:
            if i == 0:
                h += (f'<li{cls}><div class="occhiello">Adesso</div><p>{e(manca or "Il turno non è ancora pubblicato: lo mettiamo appena esce.")}</p></li>')
            continue
        if f["tipo"] == "tutte":
            h += f'<li{cls}><div class="occhiello">{e(quando)}</div><b class="farm-nome">Sono aperte tutte le farmacie</b></li>'
        elif not f.get("farmacia"):
            h += (f'<li{cls}><div class="occhiello">{e(quando)} · {e(SERVIZI_FARMACIA[f["servizio"]])}</div><p>Il turno '
                  "non è ancora pubblicato: lo mettiamo appena esce.</p></li>")
        else:
            x = f["farmacia"]
            h += (f'<li{cls}><div class="occhiello">{e(quando)} · {e(SERVIZI_FARMACIA[f["servizio"]])}</div>'
                  f'<b class="farm-nome">{e(x["nome"])}</b>{_dove_farmacia(x, con_comune)}'
                  + (f'<p class="farm-anche">{e(f["anche"])}</p>' if f.get("anche") else "") + "</li>")
    return h + "</ul>"


_PAROLE_VUOTE = {"san", "santa", "sant", "in", "di", "de", "del", "dei", "della", "fraz", "beltiglio", "val"}


def _parole_paese(n):
    t = unicodedata.normalize("NFKD", n.lower()).encode("ascii", "ignore").decode()
    return {w for w in re.findall(r"[a-z]{3,}", t) if w not in _PAROLE_VUOTE}


def comune_ufficiale(n):
    """Il nome del Comune come in COMUNI_BN («S Bartolomeo In Galdo» → «San Bartolomeo in Galdo», «Ceppaloni
    Fraz.Beltiglio» → «Ceppaloni»); il nome com'è se non si riconosce."""
    if not n:
        return n
    per_slug = {slug(c): c for c in COMUNI_BN}
    if slug(n) in per_slug:
        return per_slug[slug(n)]
    p = _parole_paese(n)
    cand = [c for c in COMUNI_BN if _parole_paese(c) and _parole_paese(c) <= p]
    return max(cand, key=lambda c: len(_parole_paese(c))) if cand else n


def _e_lista(nomi):
    return nomi[0] if len(nomi) == 1 else ", ".join(nomi[:-1]) + " e " + nomi[-1]


def aree_farmacie(farm, adesso):
    """Le aree della pagina: Benevento città e una per zona dei paesi, con le fasce, e per ogni paese la sua area.
    Restituisce (aree {id: {...}}, paesi {slug: (nome, id)})."""
    oggi = adesso.date()
    aree = {"benevento": {"nome": "Benevento", "paesi": ["Benevento"], "fasce": fasce_citta(farm, oggi), "cambio": "",
                          "manca": "", "zona": None}}
    paesi = {"benevento": ("Benevento", "benevento")}
    for z in (farm.get("paesi") or {}).get("zone") or []:
        for f in z.get("farmacie") or []:
            f["comune"] = comune_ufficiale(f.get("comune") or "")
        nomi = list(dict.fromkeys(f["comune"] for f in z.get("farmacie") or [] if f.get("comune")))
        if not nomi:
            continue
        zid = "z" + re.sub(r"\D", "", z["pdf"].split("id=")[-1])
        manca = ""
        if not z.get("turni"):
            manca = "In questa zona l'Ordine dei Farmacisti non pubblica turni: chiama la farmacia."
        elif z.get("fino_al"):
            manca = (f"Il calendario dell'Ordine per questa zona dal {_giorno_lungo(z['fino_al'])} non è chiaro: "
                     "chiama la farmacia.")
        aree[zid] = {"nome": _e_lista(nomi), "paesi": nomi, "fasce": fasce_zona(z, oggi),
                     "cambio": (z.get("cambio") or {}).get("parole") or "", "manca": manca, "zona": z}
        for n in nomi:
            paesi.setdefault(slug(n), (n, zid))
    return aree, paesi


def html_area_citta(farm, area, adesso):
    oggi = adesso.date()
    h = (f'<section class="farm-area" data-area="benevento"><h2 class="farm-titolo">Benevento</h2>'
         f'<div class="avv-speciale farm-adesso" data-area="benevento">{html_adesso(area["fasce"], adesso)}</div>')
    if not farm.get("diurno") or not farm.get("notturno"):
        return h + "<p>I turni delle farmacie di Benevento ora non sono disponibili: riprova più tardi.</p></section>"
    ieri = (oggi - dt.timedelta(days=1)).isoformat()
    notte = (farm.get("note") or {}).get("notte") or {"dalle": "20:00", "alle": "08:45"}
    dalle, alle = _ora_breve(notte["dalle"]), _ora_breve(notte["alle"])
    # negli elenchi l'ordine resta pomeridiano e festivo e poi notturno, con le ore (lui, 29 ott 2026)
    for k, titolo in (("diurno", "Servizio pomeridiano e festivo, nella pausa del pomeriggio, il sabato pomeriggio, la "
                                 "domenica e i festivi"),
                      ("notturno", f"Servizio notturno, dalle {dalle} alle {alle} del giorno dopo")):
        h += f'<h3>{titolo}</h3><ul class="notizie-comune farm-turni">'
        for x in farm[k]:
            if x["al"] < (ieri if k == "notturno" else oggi.isoformat()):
                continue
            h += (f'<li data-servizio="{k}" data-dal="{e(x["dal"])}" data-al="{e(x["al"])}"><div class="occhiello">'
                  f'{e(_giorni_turno(x)[0].upper() + _giorni_turno(x)[1:])}</div><b class="farm-nome">{e(x["nome"])}</b>'
                  f'{_dove_farmacia(_farm(x, "Benevento"))}</li>')
        h += "</ul>"
    orari, note = farm.get("orari") or {}, farm.get("note") or {}
    fasce_ = lambda v: " e ".join(f"{_ora_breve(a)}-{_ora_breve(b)}" for a, b in v)   # noqa: E731
    righe = []
    if orari.get("feriali"):
        righe.append(f"Dal lunedì al venerdì: {fasce_(orari['feriali'])}.")
    if orari.get("sabato"):
        righe.append(f"Il sabato: {fasce_(orari['sabato'])}.")
    c = note.get("continuato")
    if c:
        righe.append(f"Orario continuato nei giorni feriali, dalle {_ora_breve(c['dalle'])} alle {_ora_breve(c['alle'])}: "
                     f"{c['farmacie']}.")
    if note.get("sabato_pomeriggio"):
        righe.append(f"Aperte anche il sabato pomeriggio: {note['sabato_pomeriggio']}.")
    if note.get("notte"):
        righe.append(f"Il turno notturno va dalla chiusura del pomeriggio ({_ora_breve(note['notte']['dalle'])}) "
                     f"all'apertura del mattino dopo ({_ora_breve(note['notte']['alle'])}).")
    if note.get("chiamata"):
        righe.append("Di notte si chiama solo per farmaci davvero urgenti, con la ricetta del medico che porta scritto "
                     f"«urgente», l'ora e la firma: la chiamata notturna costa {note['chiamata']} €.")
    if righe:
        h += "<h3>Orari delle farmacie di Benevento</h3>" + "".join(f"<p>{e(r)}</p>" for r in righe)
    tutte = sorted(farmacie_dei_paesi(farm).get("Benevento") or [], key=lambda x: x["nome"])
    if tutte:
        h += '<h3>Tutte le farmacie di Benevento</h3><ul class="notizie-comune">' + "".join(
            f'<li><b class="farm-nome">{e(x["nome"])}</b>{_dove_farmacia(x)}</li>' for x in tutte) + "</ul>"
    f = farm.get("fonte") or {}
    t = quando_dt(f.get("modificato"))
    from facebook import fuso
    agg = f" (aggiornati il {t.astimezone(fuso()).day} {MESI_LUNGHI[t.astimezone(fuso()).month - 1]})" if t else ""
    elenco = (f' e <a href="{e(f["elenco"])}" target="_blank" rel="noopener nofollow">elenco delle farmacie</a> (i '
              "telefoni)") if f.get("elenco") else ""
    h += (f'<p class="agg-chiusure">Fonte: {e(f.get("nome") or "Federfarma Benevento")}, <a href="{e(f.get("pagina") or "")}" '
          f'target="_blank" rel="noopener nofollow">turni delle farmacie</a>{agg}{elenco}. Un turno può cambiare '
          "all'ultimo momento: il cartello sulla porta delle farmacie è sempre quello giusto.</p>")
    return h + "</section>"


def html_area_zona(zid, area, adesso, elenco_paesi):
    """Una zona dei paesi: adesso, le farmacie con telefono, i prossimi turni, le regole della zona, la fonte."""
    z, ora = area["zona"], adesso.strftime("%Y-%m-%dT%H:%M")
    slug_paesi = " ".join(slug(n) for n in area["paesi"])
    h = (f'<section class="farm-area" data-area="{zid}" data-paesi="{e(slug_paesi)}"><h2 class="farm-titolo">'
         f'{e(area["nome"])}</h2><div class="avv-speciale farm-adesso" data-area="{zid}">'
         f'{html_adesso(area["fasce"], adesso, area["cambio"], True, area["manca"])}</div>')
    h += '<h3>Le farmacie</h3><ul class="notizie-comune">'
    for x in elenco_paesi:
        h += f'<li><b class="farm-nome">{e(x["nome"])}</b>{_dove_farmacia(x, True)}</li>'
    h += "</ul>"
    prossimi = [f for f in area["fasce"] if f["da"] > ora][:6]   # quelli che devono ancora cominciare
    if prossimi:
        h += '<h3>I prossimi turni</h3><ul class="notizie-comune farm-turni">'
        for f in prossimi:
            x = f["farmacia"]
            cambio = f' ({area["cambio"]})' if area["cambio"] else ""
            h += (f'<li data-da="{e(f["da"])}"><div class="occhiello">Da {e(_giorno_lungo(f["da"]))}{e(cambio)}</div>'
                  f'<b class="farm-nome">{e(x["nome"])}</b>{_dove_farmacia(x, True)}</li>')
        h += "</ul>"
    if area["manca"] and z.get("turni"):
        h += f'<p>{e(area["manca"])}</p>'
    if z.get("regole"):
        h += "<h3>Come funzionano i turni qui</h3>" + "".join(
            f'<p><b>{e(r["titolo"])}:</b> {e(r["testo"])}</p>' for r in z["regole"])
    h += (f'<p class="agg-chiusure">Fonte: Ordine dei Farmacisti della Provincia di Benevento, <a href="{e(z["pdf"])}" '
          f'target="_blank" rel="noopener nofollow">calendario della zona</a> ({e(z["titolo"])}); i telefoni dall\'elenco '
          "delle farmacie di Federfarma Benevento. Un turno può cambiare all'ultimo momento: il cartello sulla porta "
          "della farmacia è sempre quello giusto.</p>")
    return h + "</section>"


def farmacie_dei_paesi(farm):
    """Le farmacie di ogni paese dall'elenco di Federfarma (strumenti/farmacie.py, farm["paesi"]["elenco"]); l'ultima
    letta resta in farmacie_dei_paesi.cache (per le pagine dei Comuni)."""
    out = farmacie_dei_paesi.cache = {}
    # il nome: quello dei calendari (zone dei paesi, turni della città) per lo stesso telefono, se no la ragione
    # sociale, se no «Farmacia di <paese>»: mai il titolare (l'elenco pubblico non lo porta)
    noti = {x.get("telefono"): x["nome"] for z in (farm.get("paesi") or {}).get("zone") or [] for x in z.get("farmacie") or []
            if x.get("telefono") and x.get("nome") and not x["nome"].startswith("Farmacia di ")}
    noti.update({x.get("telefono"): x["nome"] for k in ("diurno", "notturno") for x in farm.get(k) or [] if x.get("telefono")})
    for f in (farm.get("paesi") or {}).get("elenco") or []:
        c = comune_ufficiale(f["comune"])
        nome = (bello_via(f["nome"]) if f["nome"].isupper() else f["nome"]) if f.get("nome") else ""
        if not nome or nome == ".":
            nome = noti.get(f.get("telefono")) or f"Farmacia di {c}"
        out.setdefault(c, []).append({"nome": nome,
                                      "comune": c, "telefono": f.get("telefono") or "",
                                                "via_mappa": f.get("via") or "", "indirizzo": ""})
    return out


farmacie_dei_paesi.cache = {}


def html_farmacie(farm, aree, paesi, adesso):
    h = _testata_pagina("Servizi", "", "Farmacie di turno a Benevento e nel Sannio", [("Servizi", "/servizi/"), ("Farmacie di turno", None)])
    h += ('<p class="sommario">Le farmacie di turno di Benevento e dei paesi del Sannio, adesso e nei prossimi giorni, '
          "con il telefono, la mappa e gli orari. I turni sono quelli di Federfarma Benevento per la città e dell'Ordine "
          "dei Farmacisti per i paesi: li controlliamo ogni giorno.</p>")
    # «Il tuo paese» (lui, 29 ott 2026), come la scelta del paese nella pagina dei carburanti
    h += ('<div class="cb-comandi farm-scelta"><label>Il tuo paese <select id="farm-paese">'
          + "".join(f'<option value="{e(s)}" data-area="{e(a)}">{e(n)}</option>'
                    for s, (n, a) in sorted(paesi.items(), key=lambda kv: (kv[0] != "benevento", kv[1][0])))
          + "</select></label></div>")
    h += html_area_citta(farm, aree["benevento"], adesso)
    per_paese = farmacie_dei_paesi(farm)
    for zid, area in aree.items():
        if zid == "benevento":
            continue
        lista = [x for n in area["paesi"] for x in per_paese.get(n, [])] or area["zona"]["farmacie"]
        h += html_area_zona(zid, area, adesso, lista)
    h += '<p class="collegate"><a href="/servizi/">Tutti i servizi ›</a></p>'
    h += SEGUI
    return f'<article class="appro farmacie">{h}</article>'


def html_farmacia_comune(c, aree, paesi, adesso):
    """Il riquadrino «Farmacia di turno» nella pagina di un Comune (lui, 29 ott 2026), con il link alla pagina delle
    farmacie già sul paese; '' se il paese non ha farmacie."""
    s = slug(c)
    if s not in paesi:
        return ""
    area = aree[paesi[s][1]]
    # sempre, anche negli orari normali, le farmacie del paese col telefono (lui: «nei comuni non far sparire il
    # riquadro quando sono aperte normalmente, indicare la farmacia aperta»)
    qui = farmacie_dei_paesi.cache.get(c) or []
    lista = ("" if not qui else f'<p class="farm-qui">Le farmacie di {e(c)}</p><ul class="notizie-comune">' + "".join(
        f'<li><b class="farm-nome">{e(x["nome"])}</b>{_dove_farmacia(x)}</li>' for x in qui) + "</ul>")
    return (f'<section class="farm-comune"><h3 class="titolo-col">Farmacia di turno</h3><div class="avv-speciale farm-adesso" '
            f'data-area="{e(paesi[s][1])}">{html_adesso(area["fasce"], adesso, area["cambio"], paesi[s][1] != "benevento", area["manca"])}'
            f'</div>{lista}<p class="collegate"><a href="/farmacie-di-turno/?paese={e(s)}">Tutti i turni e i telefoni ›</a></p></section>')


def farmacie_fasce(aree, paesi, adesso):
    """farmacie-fasce.json: quello che serve a index.html per rifare «adesso» (pagina, Comuni, prima pagina)."""
    ora, fino = adesso.strftime("%Y-%m-%dT%H:%M"), (adesso + dt.timedelta(days=21)).strftime("%Y-%m-%dT%H:%M")
    return {"aggiornato": adesso.isoformat(timespec="minutes"),
            "aree": {k: {"nome": a["nome"], "fasce": [f for f in a["fasce"] if f["a"] > ora and f["da"] <= fino],
                         "cambio": a["cambio"], "manca": a["manca"], "con_comune": k != "benevento"} for k, a in aree.items()},
            "paesi": {s: a for s, (_, a) in paesi.items()}}


def html_servizi(righe):
    """La pagina Servizi: un riquadro per servizio (titolo, la riga di adesso, a cosa serve), nello stile di «Strade
    chiuse». righe = [(link, occhiello, titolo, adesso, cosa)]."""
    h = _testata_pagina("Servizi", "", "Servizi utili a Benevento e nel Sannio", [("Servizi", None)])
    h += ('<p class="sommario">Le cose che servono ogni giorno a Benevento e nei paesi del Sannio: la farmacia di '
          "turno, le strade e le scuole chiuse, i prezzi dei carburanti, il meteo e gli avvisi dei Comuni, aggiornati "
          "di continuo.</p>")
    h += '<ul class="notizie-comune servizi">'
    for link, occh, titolo, ora, cosa in righe:
        h += (f'<li><div class="occhiello">{e(occh)}</div><a href="{e(link)}">{e(titolo)}</a>'
              + (f'<span class="dove{" farm-riga" if link == "/farmacie-di-turno/" else ""}">{e(ora)}</span>' if ora else "")
              + f"<p>{e(cosa)}</p></li>")
    h += "</ul>" + SEGUI
    return f'<article class="appro">{h}</article>'


# ---------- Benevento Calcio (strumenti/calcio.py → calcio.json) ----------
# La pagina scritta qui è quella che legge Google e che si vede subito; poi calcio.js la ridisegna uguale e, durante
# le partite, la tiene in diretta (tabellone, cronaca, statistiche, formazioni, gli altri campi, classifica).
def _cal_logo(d, i, px):
    lg = (d["squadre"].get(i) or {}).get("logo")
    return f'<img src="{e(lg)}" width="{px}" height="{px}" alt="" loading="lazy">' if lg else '<span class="logo-vuoto"></span>'


def _cal_nome(d, i):
    return e((d["squadre"].get(i) or {}).get("nome", "?"))


def _cal_quando(p, ora=True):
    t = dt.datetime.fromisoformat(p["quando"])
    g = f"{GIORNI[t.weekday()]} {t.day} {MESI_LUNGHI[t.month - 1]}"
    return g + (f", {t:%H:%M}" if ora and p.get("ora_certa") else (", orario da definire" if ora else ""))


def _cal_clou(d, adesso):
    """La partita da mostrare in alto, come calcio.js: in corso, se no l'ultima finita da meno di 36 ore, se no la prossima."""
    ps = d["partite"]
    for p in ps:
        if p["stato"] == "in":
            return p
    finite = [p for p in ps if p["stato"] == "post"]
    if finite and adesso - dt.datetime.fromisoformat(finite[-1]["quando"]) < dt.timedelta(hours=36):
        return finite[-1]
    return next((p for p in ps if p["stato"] == "pre"), finite[-1] if finite else None)


def _cal_lista(d, ps, finite):
    h = '<ul class="calcio-cal">'
    for p in ps:
        t = dt.datetime.fromisoformat(p["quando"])
        sx = (f'<span class="cc-g">{t.day} {MESI[t.month - 1]}<small>{p["giornata"]}ª</small></span>'
              f'<span class="cc-sq">{_cal_logo(d, p["casa"], 20)}{_cal_nome(d, p["casa"])} – '
              f'{_cal_logo(d, p["fuori"], 20)}{_cal_nome(d, p["fuori"])}</span>')
        if finite:
            noi = (p["gol_casa"], p["gol_fuori"]) if p["casa"] == d["benevento"] else (p["gol_fuori"], p["gol_casa"])
            esito = "V" if noi[0] > noi[1] else "N" if noi[0] == noi[1] else "P"
            h += f'<li>{sx}<span class="cc-r {esito}">{p["gol_casa"]}–{p["gol_fuori"]}</span></li>'
        else:
            dx = "rinviata" if p["stato"] == "rinviata" else (f"{t:%H:%M}" if p.get("ora_certa") else "da def.")
            h += f'<li>{sx}<span class="cc-r">{dx}</span></li>'
    return h + "</ul>"


# sotto la classifica, la spiegazione delle sigle (voluta dal proprietario il 26 ott 2026); uguale in calcio.js
LEGENDA_CLASSIFICA = ("<b>Pt</b> punti · <b>G</b> partite giocate · <b>V</b> vinte · <b>N</b> pareggiate · "
                      "<b>P</b> perse · <b>DR</b> differenza reti (gol fatti meno gol subiti)")


def html_calcio(d, adesso):
    h = _testata_pagina("Calcio · Serie B", "", "Benevento Calcio: risultati, classifica e partite in diretta", [("Benevento Calcio", None)])
    h += ('<p class="sommario">Il Benevento in Serie B: la partita in diretta con la cronaca minuto per minuto, i '
          "risultati degli altri campi, la classifica che si aggiorna mentre si gioca, il calendario e i risultati.</p>")
    if not (d or {}).get("partite"):
        return f'<article class="calcio">{h}<p>I dati del campionato ora non sono disponibili: riprova più tardi.</p></article>'
    ben, p = d["benevento"], _cal_clou(d, adesso)
    vivo = ""
    if p:
        info = (f'{e(d["campionato"])} · {p["giornata"]}ª giornata · {_cal_quando(p)}'
                + (f' · {e(p["stadio"])}' if p.get("stadio") else ""))
        if p["stato"] in ("in", "post"):
            centro = f'<div class="tb-ris">{p["gol_casa"]} – {p["gol_fuori"]}</div>'
            stato = '<span class="stato-live">In diretta</span>' if p["stato"] == "in" else '<span class="stato-fine">Finita</span>'
        else:
            centro = f'<div class="tb-ris vs">{dt.datetime.fromisoformat(p["quando"]):%H:%M}</div>' if p.get("ora_certa") else '<div class="tb-ris vs">–</div>'
            stato = f'<span class="stato-pre">{e(_cal_quando(p))}</span>'
        lati = [f'<div class="tb-sq">{_cal_logo(d, i, 72)}<div class="tb-nome">{_cal_nome(d, i)}</div></div>'
                for i in (p["casa"], p["fuori"])]
        vivo += (f'<section class="tabellone"><div class="tb-info">{info}</div><div class="tb-campo">{lati[0]}'
                 f'<div class="tb-centro">{centro}<div class="tb-stato">{stato}</div></div>{lati[1]}</div></section>')
    prossime = [x for x in d["partite"] if x["stato"] in ("pre", "rinviata")][:5]
    finite = [x for x in d["partite"] if x["stato"] == "post"][-5:][::-1]
    sx = (f'<section class="cal-sez"><h3 class="titolo-col">Prossime partite</h3>{_cal_lista(d, prossime, False)}</section>'
          f'<section class="cal-sez"><h3 class="titolo-col">Ultimi risultati</h3>{_cal_lista(d, finite, True)}</section>')
    g = d.get("giornata") or {}
    righe = ""
    for x in g.get("partite", []):
        if x["stato"] in ("in", "post"):
            r = f'{x["gol_casa"]}–{x["gol_fuori"]}'
        else:
            t = dt.datetime.fromisoformat(x["quando"])
            r = "rinv." if x["stato"] == "rinviata" else f'{GIORNI[t.weekday()][:3]} {t:%H:%M}'
        noi = " noi" if ben in (x["casa"], x["fuori"]) else ""
        righe += (f'<li class="{"live" if x["stato"] == "in" else x["stato"]}{noi}"><span class="c">{_cal_nome(d, x["casa"])}'
                  f'{_cal_logo(d, x["casa"], 18)}</span><span class="r">{r}</span><span class="f">'
                  f'{_cal_logo(d, x["fuori"], 18)}{_cal_nome(d, x["fuori"])}</span></li>')
    dx = f'<section class="cal-sez"><h3 class="titolo-col">{g.get("numero", "")}ª giornata, gli altri campi</h3><ul class="giornata">{righe}</ul></section>'
    n = len(d["classifica"])
    tab = ('<table class="classifica"><thead><tr><th></th><th class="sq">Squadra</th><th>Pt</th><th>G</th><th>V</th>'
           "<th>N</th><th>P</th><th>DR</th></tr></thead><tbody>")
    for r in d["classifica"]:
        pos = r["pos"]
        zona = "zona-a" if pos <= 2 else "zona-po" if pos <= 8 else "zona-r" if pos >= n - 2 else "zona-pl" if pos >= n - 4 else ""
        dr = r["gf"] - r["gs"]
        pen = f' <span class="pen">(−{r["penalita"]})</span>' if r.get("penalita") else ""
        tab += (f'<tr class="{"noi " if r["id"] == ben else ""}{zona}"><td class="pos">{pos}</td><td class="sq">'
                f'{_cal_logo(d, r["id"], 18)}{_cal_nome(d, r["id"])}{pen}</td><td class="pt">{r["pt"]}</td><td>{r["pg"]}</td>'
                f'<td>{r["v"]}</td><td>{r["n"]}</td><td>{r["p"]}</td><td>{"+" if dr > 0 else ""}{dr}</td></tr>')
    note = ["1ª e 2ª in Serie A, dalla 3ª all'8ª playoff, 16ª e 17ª playout, ultime tre in Serie C."]
    note += [f'{_cal_nome(d, r["id"])}: {r["penalita"]} punti di penalizzazione.' for r in d["classifica"] if r.get("penalita")]
    dx += (f'<section class="cal-sez"><h3 class="titolo-col">Classifica {e(d["campionato"])}</h3>{tab}</tbody></table>'
           f'<p class="nota-cl">{LEGENDA_CLASSIFICA}</p><p class="nota-cl">{" ".join(note)}</p></section>')
    t = dt.datetime.fromisoformat(d["aggiornato"])
    vivo += (f'<div class="calcio-griglia"><div>{sx}</div><div>{dx}</div></div><p class="cal-fonte">Dati: ESPN, '
             f"aggiornati in diretta ogni 15 secondi durante le partite; calendario e classifica controllati alle "
             f"{t:%H:%M}. La cronaca è scritta in automatico dai fatti della partita (gol, cartellini, cambi). I loghi "
             "sono delle società.</p>")
    return f'<article class="calcio">{h}<div id="calcio-vivo">{vivo}</div>{SEGUI}</article>'


def _racconto(righe, fonti):
    """Storia di più giorni: sopra i paragrafi di ogni giorno la sua data (come disegna index.html)."""
    piu_giorni = len({r.get("giorno") for r in righe if isinstance(r, dict) and r.get("giorno")}) > 1
    h, prec = "", None
    for r in righe:
        g = r.get("giorno") if isinstance(r, dict) else None
        if piu_giorni and g and g != prec:
            h += f'<div class="giorno">{e(_giorno_racconto(g))}</div>'
            prec = g
        h += _frase("p", r, fonti)
    return h


def _elenco(titolo, righe, fonti):
    if not isinstance(righe, list) or not righe:
        return ""
    return f"<h3>{e(titolo)}</h3><ul>" + "".join(_frase("li", r, fonti) for r in righe) + "</ul>"


def _cronologia(righe, fonti, titolo):
    if not isinstance(righe, list) or not righe:
        return ""
    li = "".join(f'<li><span class="giorno">{e(c.get("data"))}</span><span>{e(c.get("fatto"))}'
                 f'{_cita(c.get("fonti"), fonti)}</span></li>' for c in righe)
    return f'<h3>{e(titolo)}</h3><ol class="cronologia">{li}</ol>'


# ---------- Curiosità del Sannio (curiosita.json: una al giorno, alle 12; sui social strumenti/curiosita_social.py) ----------
# Voluta dal proprietario il 24 ott 2026: «un post al giorno alle 12: una curiosità, una storia, un fatto del passato,
# un detto, una superstizione, una leggenda… di Benevento», «andare avanti all'infinito», «nessuna storia scritta male».
# Sul sito esce col primo giro dopo le 12 del suo giorno (prima non c'è: né pagina, né riquadro, né sitemap).
ORA_CURIOSITA = 12
CAT_CURIOSITA = {"leggenda": "Leggenda", "storia": "Storia", "detto": "Detto", "superstizione": "Superstizione",
                 "tradizione": "Tradizione", "cibo": "Sapori", "paese": "Paesi del Sannio", "accadde oggi": "Accadde oggi"}


def curiosita_uscite(curiosita, adesso):
    """Le curiosità già uscite (dalle 12 del loro giorno), dalla più nuova."""
    from facebook import fuso
    t = adesso.astimezone(fuso())
    oggi = t.date().isoformat()
    return sorted((c for c in curiosita if c["data"] < oggi or (c["data"] == oggi and t.hour >= ORA_CURIOSITA)),
                  key=lambda c: c["data"], reverse=True)


def _data_curiosita(iso):
    d = dt.date.fromisoformat(iso)
    return f"{GIORNI[d.weekday()]} {d.day} {MESI_LUNGHI[d.month - 1]} {d.year}"


def _paragrafi_curiosita(testo):
    """I paragrafi del racconto; l'ultima riga, la domanda per i commenti dei social, sul sito non c'è."""
    par = [x.strip() for x in testo.split("\n\n") if x.strip()]
    if len(par) > 1 and par[-1].endswith("?") and len(par[-1]) < 140:
        par = par[:-1]
    return par


def html_curiosita(c, altre):
    h = _testata_pagina("Curiosità del Sannio", c["luogo"], c["titolo"], [("Curiosità del Sannio", "/curiosita/")])
    h += (f'<p class="agg-chiusure">{e(CAT_CURIOSITA.get(c["categoria"], "Curiosità"))} · '
          f'{e(_data_curiosita(c["data"]))}</p>')
    im = c.get("immagine")
    if im:
        pos = f' style="object-position: 50% {float(im.get("fuoco_y", 0.5)) * 100:.0f}%"' if "fuoco_y" in im else ""
        alt = im.get("mostra") or c["titolo"]   # «mostra»: cosa si vede nella foto (CURIOSITA.md)
        h += (f'<figure class="foto-tema"><img src="{e(im["file"])}" alt="{e(alt)}" loading="lazy"{pos}>'
              + ("<figcaption>Immagine illustrativa creata con l'intelligenza artificiale: non è una foto vera.</figcaption>"
                 if im.get("ia") else
                 f'<figcaption><a href="{e(im["pagina"])}" target="_blank" rel="noopener nofollow">{e(im["credito"])}'
                 "</a>, da Wikimedia Commons</figcaption>") + "</figure>")
    h += "".join(f"<p>{e(x)}</p>" for x in _paragrafi_curiosita(c["testo"]))
    h += '<h3>Fonti</h3><ul class="elenco-fonti">' + "".join(
        f"<li>{_link_fonte(f, f['titolo'])}</li>" for f in c.get("fonti") or []) + "</ul>"
    if altre:
        h += '<h3>Altre curiosità</h3><ul class="notizie-comune">' + "".join(
            f'<li><a href="/curiosita/{e(x["slug"])}/">{e(x["titolo"])}</a><span class="dove">'
            f'{e(CAT_CURIOSITA.get(x["categoria"], ""))} · {e(x["luogo"])}</span></li>' for x in altre) + "</ul>"
    h += '<p class="collegate"><a href="/curiosita/">Tutte le curiosità del Sannio ›</a></p>'
    h += SEGUI
    return f'<article class="appro">{h}</article>'


def html_curiosita_elenco(uscite):
    h = _testata_pagina("Curiosità del Sannio", "", "Curiosità del Sannio: leggende, storia e tradizioni", [("Curiosità del Sannio", None)])
    h += ('<p class="sommario">Ogni giorno alle 12 una storia di Benevento e dei paesi della provincia: leggende, fatti '
          "del passato, detti, superstizioni, tradizioni e sapori. Ogni fatto è controllato sulle fonti, che trovi in "
          "fondo a ogni racconto; le leggende sono raccontate come leggende.</p>")
    if uscite:
        h += '<ul class="notizie-comune">' + "".join(
            f'<li><a href="/curiosita/{e(x["slug"])}/">{e(x["titolo"])}</a><span class="dove">'
            f'{e(CAT_CURIOSITA.get(x["categoria"], ""))} · {e(x["luogo"])} · {e(_data_curiosita(x["data"]))}</span></li>'
            for x in uscite) + "</ul>"
    else:
        h += "<p>La prima esce oggi alle 12.</p>"
    h += SEGUI
    return f'<article class="appro">{h}</article>'


def _fonti(fonti):
    if not fonti:
        return ""
    li = "".join("<li>" + _link_fonte(f, f.get("nome", "") + (": " + f["titolo"] if f.get("titolo") else "")) +
                 (f" · {e(f['data'])}" if f.get("data") else "") + "</li>" for f in fonti)
    return f'<h3>Fonti</h3><ul class="elenco-fonti">{li}</ul>'


def _categoria(n):
    """«Cronaca», «Strade»… e per lo sport anche la disciplina: «Sport · Calcio»."""
    c = NOMI_CAT.get(n.get("categoria"), "Altro")
    return f"{c} · {NOMI_SPORT[n['sport']]}" if n.get("categoria") == "sport" and n.get("sport") in NOMI_SPORT else c


def _percorso(passi):
    """Il percorso in cima alla pagina, al posto di «← Tutte le notizie» (lui, 29 ott 2026: «da rivedere questa sorta di
    tasto indietro, non mi convince il funzionamento, ripensalo e dagli anche un aspetto più adatto al sito» → «sì fallo
    in tutte le pagine»): «Notizie Benevento › Cronaca › Telese Terme», ogni passo un link, l'ultimo (la pagina stessa,
    se c'è) senza. Il bottone «‹ Indietro» lo mostra index.html solo a chi arriva da un'altra pagina del sito e lo
    riporta lì, allo stesso punto (attivaIndietro). Come percorsoPagina() in index.html."""
    voci = [(NOME, "/")] + list(passi)
    li = "".join(f'<li><a href="{e(h)}">{e(n)}</a></li>' if h else f'<li aria-current="page">{e(n)}</li>' for n, h in voci)
    return (f'<nav class="percorso" aria-label="Dove sei"><button type="button" class="indietro" hidden>‹ Indietro</button>'
            f"<ol>{li}</ol></nav>")


def sezione_di(cat):
    """(nome, indirizzo) della sezione di una categoria, come nel menu (le strade stanno negli Avvisi)."""
    if cat == "strade":
        cat = "avvisi"
    return NOMI_CAT.get(cat, "Altro"), "/" + CAT_PERCORSO.get(cat, "sezione/altro") + "/"


def passi_notizia(n):
    """Il percorso di una notizia: la sezione e, se il luogo è un Comune solo, il suo «piccolo sito»."""
    passi = [sezione_di(n.get("categoria"))]
    cc = comuni_di(n.get("luogo"))
    if len(cc) == 1:
        passi.append((cc[0], url_comune(cc[0])))
    return passi


def _testata_pagina(occhiello, luogo, titolo, passi=()):
    lu = f'<span class="luogo">{_luogo_link(luogo)}</span>' if luogo else ""
    return f'{_percorso(passi)}<div class="occhiello">{e(occhiello)}{lu}</div><h1>{e(titolo)}</h1>'


# dove seguire le notizie (come riquadroSegui in index.html; loghi Simple Icons, CC0)
INSTAGRAM = "https://www.instagram.com/notiziebenevento.it/"
_LOGO = {"telegram": "M11.944 0A12 12 0 0 0 0 12a12 12 0 0 0 12 12 12 12 0 0 0 12-12A12 12 0 0 0 12 0a12 12 0 0 0-.056 0zm4.962 7.224c.1-.002.321.023.465.14a.506.506 0 0 1 .171.325c.016.093.036.306.02.472-.18 1.898-.962 6.502-1.36 8.627-.168.9-.499 1.201-.82 1.23-.696.065-1.225-.46-1.9-.902-1.056-.693-1.653-1.124-2.678-1.8-1.185-.78-.417-1.21.258-1.91.177-.184 3.247-2.977 3.307-3.23.007-.032.014-.15-.056-.212s-.174-.041-.249-.024c-.106.024-1.793 1.14-5.061 3.345-.48.33-.913.49-1.302.48-.428-.008-1.252-.241-1.865-.44-.752-.245-1.349-.374-1.297-.789.027-.216.325-.437.893-.663 3.498-1.524 5.83-2.529 6.998-3.014 3.332-1.386 4.025-1.627 4.476-1.635z",
         "facebook": "M9.101 23.691v-7.98H6.627v-3.667h2.474v-1.58c0-4.085 1.848-5.978 5.858-5.978.401 0 .955.042 1.468.103a8.68 8.68 0 0 1 1.141.195v3.325a8.623 8.623 0 0 0-.653-.036 26.805 26.805 0 0 0-.733-.009c-.707 0-1.259.096-1.675.309a1.686 1.686 0 0 0-.679.622c-.258.42-.374.995-.374 1.752v1.297h3.919l-.386 2.103-.287 1.564h-3.246v8.245C19.396 23.238 24 18.179 24 12.044c0-6.627-5.373-12-12-12s-12 5.373-12 12c0 5.628 3.874 10.35 9.101 11.647Z",
         "instagram": "M7.0301.084c-1.2768.0602-2.1487.264-2.911.5634-.7888.3075-1.4575.72-2.1228 1.3877-.6652.6677-1.075 1.3368-1.3802 2.127-.2954.7638-.4956 1.6365-.552 2.914-.0564 1.2775-.0689 1.6882-.0626 4.947.0062 3.2586.0206 3.6671.0825 4.9473.061 1.2765.264 2.1482.5635 2.9107.308.7889.72 1.4573 1.388 2.1228.6679.6655 1.3365 1.0743 2.1285 1.38.7632.295 1.6361.4961 2.9134.552 1.2773.056 1.6884.069 4.9462.0627 3.2578-.0062 3.668-.0207 4.9478-.0814 1.28-.0607 2.147-.2652 2.9098-.5633.7889-.3086 1.4578-.72 2.1228-1.3881.665-.6682 1.0745-1.3378 1.3795-2.1284.2957-.7632.4966-1.636.552-2.9124.056-1.2809.0692-1.6898.063-4.948-.0063-3.2583-.021-3.6668-.0817-4.9465-.0607-1.2797-.264-2.1487-.5633-2.9117-.3084-.7889-.72-1.4568-1.3876-2.1228C21.2982 1.33 20.628.9208 19.8378.6165 19.074.321 18.2017.1197 16.9244.0645 15.6471.0093 15.236-.005 11.977.0014 8.718.0076 8.31.0215 7.0301.0839m.1402 21.6932c-1.17-.0509-1.8053-.2453-2.2287-.408-.5606-.216-.96-.4771-1.3819-.895-.422-.4178-.6811-.8186-.9-1.378-.1644-.4234-.3624-1.058-.4171-2.228-.0595-1.2645-.072-1.6442-.079-4.848-.007-3.2037.0053-3.583.0607-4.848.05-1.169.2456-1.805.408-2.2282.216-.5613.4762-.96.895-1.3816.4188-.4217.8184-.6814 1.3783-.9003.423-.1651 1.0575-.3614 2.227-.4171 1.2655-.06 1.6447-.072 4.848-.079 3.2033-.007 3.5835.005 4.8495.0608 1.169.0508 1.8053.2445 2.228.408.5608.216.96.4754 1.3816.895.4217.4194.6816.8176.9005 1.3787.1653.4217.3617 1.056.4169 2.2263.0602 1.2655.0739 1.645.0796 4.848.0058 3.203-.0055 3.5834-.061 4.848-.051 1.17-.245 1.8055-.408 2.2294-.216.5604-.4763.96-.8954 1.3814-.419.4215-.8181.6811-1.3783.9-.4224.1649-1.0577.3617-2.2262.4174-1.2656.0595-1.6448.072-4.8493.079-3.2045.007-3.5825-.006-4.848-.0608M16.953 5.5864A1.44 1.44 0 1 0 18.39 4.144a1.44 1.44 0 0 0-1.437 1.4424M5.8385 12.012c.0067 3.4032 2.7706 6.1557 6.173 6.1493 3.4026-.0065 6.157-2.7701 6.1506-6.1733-.0065-3.4032-2.771-6.1565-6.174-6.1498-3.403.0067-6.156 2.771-6.1496 6.1738M8 12.0077a4 4 0 1 1 4.008 3.9921A3.9996 3.9996 0 0 1 8 12.0077"}
SEGUI = ('<section class="segui"><h3>Seguici</h3><p>Le notizie di Benevento e del Sannio appena escono, sul telefono.</p>'
         '<div class="canali">' + "".join(
    f'<a class="{k}" href="{u}" target="_blank" rel="noopener nofollow" aria-label="{t} di Notizie Benevento">'
    f'<svg viewBox="0 0 24 24" aria-hidden="true"><path d="{_LOGO[k]}"/></svg>{t}</a>'
    for k, t, u in (("instagram", "Instagram", INSTAGRAM),
                    ("facebook", "Facebook", "https://www.facebook.com/notiziebenevento"),
                    ("telegram", "Telegram", "https://t.me/notiziebenevento"))) + '</div></section>')

# il posto dei pulsanti Ascolta e Condividi, che mette index.html: così la pagina non salta quando arrivano
POSTO_ASCOLTA = '<div class="ascolta" style="min-height:38px"></div>'


def locandina(n):
    """La locandina arrivata con il comunicato (img/locandine/<nome>.jpg), se c'è: «/img/locandine/…jpg»."""
    t = str(n.get("locandina") or "")
    return "/" + t if re.match(r"^img/locandine/[a-z0-9-]+\.jpg$", t) else None


def dim_jpeg(rel):
    """Larghezza e altezza di un JPEG del sito (letti dall'intestazione, senza Pillow); (0, 0) se non si legge."""
    try:
        with open(os.path.join(os.path.dirname(QUI), rel.lstrip("/")), "rb") as f:
            b = f.read()
    except OSError:
        return 0, 0
    i = 2
    while i + 9 < len(b) and b[i] == 0xFF:
        m, lung = b[i + 1], int.from_bytes(b[i + 2:i + 4], "big")
        if m in (0xC0, 0xC1, 0xC2):
            return int.from_bytes(b[i + 7:i + 9], "big"), int.from_bytes(b[i + 5:i + 7], "big")
        i += 2 + lung
    return 0, 0


def html_locandina(rel, chi):
    w, h = dim_jpeg(rel)
    misure = f' width="{w}" height="{h}"' if w and h else ""
    return (f'<figure class="locandina"><img src="{e(rel)}"{misure} alt="La locandina" decoding="async">'
            f'<figcaption>{e("La locandina di " + chi if chi else "La locandina")}</figcaption></figure>')


def foto_inviate(n):
    """Le foto arrivate con il comunicato (img/locandine/<nome>.jpg, archivia.FOTO_MAX al massimo), in ordine."""
    f = n.get("foto_inviate")
    return ["/" + t for t in f if re.match(r"^img/locandine/[a-z0-9-]+\.jpg$", str(t))] if isinstance(f, list) else []


def foto_in_alto(n):
    """L'immagine vera in cima alla notizia: la locandina, se no la prima foto inviata (None se non ce ne sono)."""
    return locandina(n) or next(iter(foto_inviate(n)), None)


def foto_in_fondo(n):
    """Le altre foto inviate, in fondo all'articolo: tutte, se in alto c'è la locandina."""
    f = foto_inviate(n)
    return f if locandina(n) else f[1:]


def didascalia_foto(n, quante=1):
    chi = str(n.get("foto_da") or "").strip()
    return (("Le foto inviate da " if quante > 1 else "Foto inviata da ") + chi) if chi else \
        ("Le foto inviate con il comunicato" if quante > 1 else "Foto inviata con il comunicato")


def html_foto(rel, n):
    w, h = dim_jpeg(rel)
    misure = f' width="{w}" height="{h}"' if w and h else ""
    return (f'<figure class="locandina foto-vera"><img src="{e(rel)}"{misure} alt="{e(didascalia_foto(n))}" '
            f'decoding="async"><figcaption>{e(didascalia_foto(n))}</figcaption></figure>')


def html_galleria(foto, n):
    """Le altre foto inviate, in fondo all'articolo (come galleria() in index.html): ognuna si apre intera."""
    if not foto:
        return ""
    h = ""
    for rel in foto:
        w, a = dim_jpeg(rel)
        misure = f' width="{w}" height="{a}"' if w and a else ""
        h += (f'<a href="{e(rel)}"><img src="{e(rel)}"{misure} alt="{e(didascalia_foto(n))}" loading="lazy" '
              'decoding="async"></a>')
    return (f'<figure class="galleria"><div class="galleria-foto">{h}</div>'
            f'<figcaption>{e(didascalia_foto(n, len(foto)))}</figcaption></figure>')


def foto_tema(n):
    """La foto illustrativa della notizia, se c'è, mai quando c'è la locandina vera o una foto inviata (voluto dal
    proprietario il 25 ott 2026: «in questo caso niente immagini AI»): quella fatta apposta dall'IA per la scena della
    notizia o della storia (img/ia/<id>.jpg, strumenti/foto_ia.py; lui, 28 ott 2026: «regola tutte foto, se non la trovi
    ne crei una… con gpt»), anche sulla cronaca; se no quella del tema (img/temi/<tema>.jpg), mai sulla cronaca."""
    if foto_in_alto(n):
        return None
    if re.match(r"^img/ia/[a-z0-9-]+$", str(n.get("foto_ia") or "")):
        return "/" + n["foto_ia"] + ".jpg"
    t = n.get("immagine")
    if not t or n.get("categoria") == "cronaca" or not re.match(r"^[a-z0-9-]+$", str(t)):
        return None
    # «foto» è la versione scelta da archivia.py per non ripetere la stessa foto in prima pagina
    if re.match(r"^[a-z0-9-]+$", str(n.get("foto") or "")):
        t = n["foto"]
    return f"/img/temi/{t}.jpg"


def figura_illustrativa(n, cosa="del fatto"):
    """La foto illustrativa in grande nella pagina (foto_tema), con la scritta che è fatta con l'IA."""
    if not foto_tema(n):
        return ""
    b = foto_tema(n)[:-4]
    largo = 1200 if b.startswith("/img/ia/") else 1536
    return (f'<figure class="foto-tema"><img src="{b}-m.jpg" srcset="{b}-m.jpg 768w, {b}.jpg {largo}w" '
            'sizes="(max-width: 800px) 100vw, 760px" width="1536" height="1024" alt="" decoding="async">'
            f"<figcaption>Immagine illustrativa creata con l'intelligenza artificiale: non è una foto {cosa}.</figcaption></figure>")


def illustrata_ia(n):
    """True se la notizia si mostra con una foto fatta dall'IA (tema o img/ia): i social lo scrivono nel post."""
    return bool(foto_tema(n))


def _aggiornamento(ag, fonti):
    """L'ultima novità di una notizia che va avanti da giorni, in cima all'articolo con data e ora: come le dirette dei
    giornali, chi torna vede subito cosa è cambiato (l'ora la mette archivia.py)."""
    if not isinstance(ag, dict) or not str(ag.get("testo") or "").strip():
        return ""
    m = re.match(r"\d{4}-(\d{2})-(\d{2})T(\d{2}):(\d{2})", str(ag.get("quando") or ""))
    q = f" · {int(m[2])} {MESI_LUNGHI[int(m[1]) - 1]}, {m[3]}:{m[4]}" if m else ""
    return f'<div class="aggiornamento"><div class="quando">Aggiornamento{e(q)}</div>{_frase("p", ag, fonti)}</div>'


# la firma di ogni articolo (come in disegnaArticolo di index.html): chi scrive e come, per chi legge e per Google News
FIRMA = "Di Notizie Benevento, con l'intelligenza artificiale dalle fonti citate"


def html_articolo(n, appro_collegato):
    n = vista_ufficiale(n)
    a = n["articolo"]
    fonti = a.get("fonti") if isinstance(a.get("fonti"), list) else []
    h = _testata_pagina(_categoria(n), n.get("luogo"), n["titolo"], passi_notizia(n))
    meta = ("Dall'archivio · " if n["_arch"] else "") + (data_it(n.get("pubblicato")) + " · " if n.get("pubblicato") else "")
    h += (f'<div class="meta">{e(meta)}{e(conta_fonti(n, fonti))}<span class="firma">{FIRMA} · '
          '<a href="/chi-siamo/">Come lavoriamo</a></span></div>')
    if n.get("stato") == "una_fonte" and n.get("fonti"):
        h += (f'<div class="nota">Per ora questo fatto lo riporta solo {e(n["fonti"][0].get("nome", ""))}. '
              'Lo aggiorniamo se arrivano altre fonti.</div>')
    h += _aggiornamento(a.get("aggiornamento"), fonti)
    h += POSTO_ASCOLTA
    if locandina(n):
        h += html_locandina(locandina(n), (fonti[0].get("nome") if fonti else ""))
    elif foto_inviate(n):
        h += html_foto(foto_inviate(n)[0], n)
    h += figura_illustrativa(n)
    if isinstance(a.get("racconto"), list) and a["racconto"]:
        h += '<div class="racconto">' + _racconto(a["racconto"], fonti) + "</div>"
    elif a.get("cosa"):
        h += f"<h3>Cosa è successo</h3><p>{e(a['cosa'])}</p>"
    h += html_galleria(foto_in_fondo(n), n)
    # con il racconto, una cronologia di un solo momento non aggiunge niente
    if not a.get("racconto") or len(a.get("cronologia") or []) > 1:
        h += _cronologia(a.get("cronologia"), fonti, "I fatti")
    h += _elenco("Su cosa concordano i giornali", a.get("concordano"), fonti)
    h += _elenco("Su cosa non concordano", a.get("divergono"), fonti)
    h += _elenco("Cosa non si sa ancora", a.get("non_si_sa"), fonti)
    if appro_collegato:
        h += (f'<h3>Approfondimento</h3><p class="collegate"><a href="{percorso("approfondimento", appro_collegato["id"])}">'
              f'{e(appro_collegato["titolo"])} ›</a></p>')
    h += SEGUI
    h += _fonti(fonti)
    return f'<article class="appro">{h}</article>'


def html_approfondimento(ap, notizie_per_id):
    fonti = ap.get("fonti") if isinstance(ap.get("fonti"), list) else []
    h = _testata_pagina("Approfondimento", ap.get("luogo"), ap["titolo"], [sezione_di(ap["categoria"])] if ap.get("categoria") else [])
    if ap.get("sommario"):
        h += f'<p class="sommario">{e(ap["sommario"])}</p>'
    h += (f'<div class="meta">{"Dall&#39;archivio · " if ap["_arch"] else ""}Aggiornato {e(data_it(ap.get("aggiornato")))} · '
          f'{len(fonti)} fonti confrontate</div>') + POSTO_ASCOLTA + figura_illustrativa(ap)
    if isinstance(ap.get("in_breve"), list) and ap["in_breve"]:
        h += '<div class="inbreve"><strong>In breve</strong><ul>' + "".join(_frase("li", r, fonti) for r in ap["in_breve"]) + "</ul></div>"
    for s in ap.get("sezioni") or []:
        h += f"<h3>{e(s.get('titolo'))}</h3>" + "".join(_frase("p", p, fonti) for p in s.get("paragrafi") or [])
        if isinstance(s.get("punti"), list):
            h += "<ul>" + "".join(_frase("li", r, fonti) for r in s["punti"]) + "</ul>"
    if isinstance(ap.get("domande"), list) and ap["domande"]:
        h += "<h3>Domande e risposte</h3>" + "".join(
            f'<p class="domanda">{e(q.get("d"))}</p>' + _frase("p", {"testo": q.get("r"), "fonti": q.get("fonti")}, fonti)
            for q in ap["domande"])
    h += _cronologia(ap.get("cronologia"), fonti, "Giorno per giorno")
    h += _elenco("Cosa non si sa ancora", ap.get("non_si_sa"), fonti)
    coll = [notizie_per_id[i] for i in ap.get("collegate") or [] if i in notizie_per_id]
    if coll:
        h += '<h3>Le notizie collegate</h3><ul class="collegate">' + "".join(
            f'<li><a href="{percorso("notizia", x["id"])}">{e(x["titolo"])}</a></li>' for x in coll) + "</ul>"
    h += _fonti(fonti)
    return f'<article class="appro">{h}</article>'



# ---------- chi siamo (pagina fissa) ----------
def html_chi_siamo():
    fb = f'<a href="{FACEBOOK}" target="_blank" rel="noopener">Pagina Facebook Notizie Benevento</a>'
    h = _testata_pagina(NOME, "", "Chi siamo", [("Chi siamo", None)])
    h += ('<p class="sommario">Notizie Benevento raccoglie in un solo posto le notizie di Benevento e della provincia: '
          'le confronta tra i giornali locali e i siti ufficiali e le racconta in modo semplice, con i link agli articoli '
          'originali.</p>')
    h += ("<h3>Da dove vengono le notizie</h3>"
          "<p>Ogni giorno leggiamo i giornali del Sannio e i siti ufficiali: Prefettura, Provincia, Comuni, Protezione "
          "civile della Campania, ASL Benevento, ospedale San Pio, ANAS e INGV. Le notizie sono dei giornali che le hanno "
          "scritte: noi non le diamo per primi e non facciamo inchieste. In ogni articolo trovi i link per leggerle da "
          "loro.</p>")
    h += ("<h3>Come scegliamo cosa pubblicare</h3><ul>"
          "<li>Una notizia esce se la riportano almeno due testate diverse oppure una fonte ufficiale.</li>"
          "<li>La cronaca riportata da un solo giornale autorevole porta la scritta «Una sola fonte».</li>"
          "<li>Se i giornali dicono cose diverse lo scriviamo, e diciamo anche cosa non si sa ancora.</li>"
          "<li>Le accuse sono riportate con le parole usate dai giornali.</li></ul>")
    h += ("<h3>Come sono scritti gli articoli</h3>"
          "<p>I testi sono scritti con l'intelligenza artificiale partendo dagli articoli citati, con regole precise: ogni "
          "frase viene da una fonte, e date, numeri e nomi sono quelli degli originali. Le foto illustrative sono create "
          "con l'intelligenza artificiale e lo dicono sotto l'immagine. Il sito si aggiorna ogni ora, dalle 6 alle 22.</p>")
    h += ('<h3>Meteo e allerte</h3><p>Le <a href="/meteo.html">previsioni</a> mettono insieme 8 modelli dei servizi '
          "meteo nazionali ed europei. Per le allerte valgono solo gli avvisi ufficiali del Centro funzionale della "
          "Regione Campania e della Protezione civile.</p>")
    h += ('<h3>Archivio</h3><p>Nessuna notizia viene cancellata: quando esce dalla prima pagina resta '
          'nell\'<a href="/#archivio">archivio</a>, allo stesso indirizzo.</p>')
    h += ("<h3>Mandaci i comunicati</h3><p>Comuni, enti, scuole, associazioni e società sportive del Sannio possono "
          'mandare i loro comunicati a <a href="mailto:comunicati@notiziebenevento.it">comunicati@notiziebenevento.it</a> '
          'o alla PEC <a href="mailto:notiziebenevento@pec.it">notiziebenevento@pec.it</a>, '
          "meglio con il testo scritto nella mail. Li leggiamo ogni 5 minuti: se sono notizie della "
          "provincia e si possono verificare, le pubblichiamo citando chi le firma.</p>")
    h += ("<h3>Correzioni</h3><p>Se in un articolo c'è un errore lo correggiamo nell'articolo stesso e lo scriviamo in "
          "una nota, con quello che è cambiato. Quando una notizia va avanti, la novità è in cima con la data e l'ora "
          "dell'aggiornamento.</p>")
    h += ('<h3>Contatti</h3><p>Per segnalare un errore o una notizia che manca scrivi a '
          '<a href="mailto:redazione@notiziebenevento.it">redazione@notiziebenevento.it</a> '
          f"oppure un messaggio sulla {fb}.</p>")
    h += ("<h3>Privacy</h3><p>Le visite si contano in forma anonima, senza cookie. Non serve nessuna registrazione.</p>")
    return f'<article class="appro">{h}</article>'


# ---------- i Comuni: comune/<nome>/ e comuni/ ----------
COMUNE_MINIMO = 3   # notizie + eventi: sotto, la pagina c'è ma con noindex e fuori dalla sitemap (Google penalizza le pagine quasi vuote)
_COMUNI = {c.lower(): c for c in COMUNI_BN}
_COMUNI["sant'agata dei goti"] = "Sant'Agata de' Goti"
SEP_LUOGO = r"([,()]| e )"   # come in luogoConLink (index.html)


def _comune(pezzo):
    return _COMUNI.get(pezzo.replace("’", "'").strip().lower())


def comuni_di(luogo):
    """I Comuni nel «luogo» di una notizia: «Cusano Mutri, frazione Civitella» → Cusano Mutri, «Airola e Valle
    Caudina» → Airola. Solo i pezzi che sono proprio il nome di un Comune: nel titolo «Ponte» sarebbe ovunque."""
    trovati = []
    for p in re.split(SEP_LUOGO, str(luogo or "")):
        c = _comune(p)
        if c and c not in trovati:
            trovati.append(c)
    return trovati


def url_comune(c):
    return "/zona/benevento/" if c == "Benevento" else f"/comune/{slug(c)}/"


def _luogo_link(luogo):
    """Il luogo sotto il titolo, con i Comuni che portano alla loro pagina."""
    out = ""
    for p in re.split(SEP_LUOGO, str(luogo or "")):
        c = _comune(p)
        if c:
            prima, nome, dopo = re.match(r"(\s*)(.*?)(\s*)$", p, re.S).groups()
            out += f'{e(prima)}<a href="{url_comune(c)}">{e(nome)}</a>{e(dopo)}'
        else:
            out += e(p)
    return out


COND_METEO = {"sereno": "Sereno", "poco-nuvoloso": "Poco nuvoloso", "nuvoloso": "Nuvoloso", "coperto": "Coperto",
              "nebbia": "Nebbia", "possibili-piogge": "Possibili piogge", "pioggia-debole": "Pioggia debole",
              "pioggia": "Pioggia", "pioggia-forte": "Pioggia forte", "temporale": "Temporale", "neve": "Neve"}
LIVELLI_ALLERTA = {"gialla": "#f2c200", "arancione": "#ef7f1a", "rossa": "#c4161c"}
NOMI_ZONA = {"benevento": "Benevento città", "telesina": "Valle Telesina", "caudina": "Valle Caudina",
             "fortore": "Fortore e Tammaro", "provincia": "Sannio"}


def html_meteo_comune(c, m, allerte, oggi):
    """Il riquadro «Meteo» del Comune (strumenti/meteo_comuni.py), come quello di Benevento in prima pagina: adesso e
    tre giorni; le icone le mette index.html (icona()). In cima la striscia dell'allerta, se non è verde."""
    if not m:
        return ""
    gradi = lambda v: "–" if v is None else f"{round(v)}°"   # noqa: E731
    al, peggio = "", 0
    ordine = ["verde", "gialla", "arancione", "rossa"]
    for nome, d in (("oggi", oggi), ("domani", oggi + dt.timedelta(days=1))):
        for x in (((allerte.get("giorni") or {}).get(d.isoformat()) or {}).get("zone") or {}).values():
            if c in (x.get("comuni") or []) and ordine.index(x.get("livello") or "verde") > peggio:
                peggio, al = ordine.index(x.get("livello") or "verde"), nome
    h, dove = "", f"/meteo.html?paese={slug(c)}"   # il meteo completo del paese (lui, 29 ott 2026)
    if peggio:
        liv = ordine[peggio]
        dove += "#allerte"
        h += (f'<div class="mb-allerta" style="background:{LIVELLI_ALLERTA[liv]}'
              f'{";color:#3a2c00" if liv == "gialla" else ""}">Allerta {liv} {al} ›</div>')
    o = m["ora"]
    h += (f'<div class="mb-tit">Meteo {e(c)}</div><div class="mb-ora"><span class="mb-icona" data-cond="{e(o["cond"])}" '
          f'data-notte="{0 if o.get("giorno") else 1}"></span><div class="mb-t">{gradi(o["t"])}</div><div class="mb-c">'
          f'{e(COND_METEO.get(o["cond"], ""))}<small>adesso</small></div></div><div class="mb-giorni">')
    for k, g in enumerate(m["giorni"][:3]):
        d = dt.date.fromisoformat(g["data"])
        et = "Oggi" if k == 0 else "Domani" if k == 1 else GIORNI[d.weekday()][:3]
        pp = f"{g['prob']}%" if g.get("prob") else ""
        h += (f'<div class="mb-g">{e(et)}<span class="mb-icona" data-cond="{e(g["cond"])}" data-notte="0"></span><b>'
              f'{gradi(g["max"])}</b> <span class="mn">{gradi(g["min"])}</span><span class="pp">{pp}</span></div>')
    h += "</div>"
    return (f'<a class="meteo-box meteo-comune" href="{e(dove)}">{h}<p class="mb-fonte">Previsioni ora per ora e a 10 '
            f'giorni ›</p></a>')


def html_comune(c, notizie, eventi, allerte, stemma, oggi, distributori=0, farmacia="", meteo_c=None, vicine=(), zona=""):
    """La pagina di un Comune: in cima titolo e stemma; a destra (sul telefono sotto il titolo) allerta, meteo, farmacia
    di turno e carburanti (lui, 29 ott 2026: «una colonna di destra simile alla nostra home», «meteo e farmacia sempre
    nella colonna di destra», «e anche allerte»); a sinistra eventi e notizie, e se sono poche quelle della zona («cerchiamo
    di riempire un po' le pagine, spesso sono vuote»)."""
    titolo = f"Notizie da {c}"
    h = _testata_pagina("Comuni del Sannio", "Provincia di Benevento", titolo, [("Comuni", "/comuni/"), (c, None)])
    somm = (f'<p class="sommario">Le notizie di {e(c)}, in provincia di Benevento: cronaca, strade, politica, sport ed '
            f'eventi, confrontati tra i giornali locali e i siti ufficiali, con i link agli articoli originali.</p>')
    if stemma:   # accanto al titolo; disegni liberi di Wikimedia Commons: autore e licenza vanno citati
        lic = e(stemma.get("licenza"))
        if stemma.get("url_licenza", "").startswith("http"):
            lic = f'<a href="{e(stemma["url_licenza"])}" target="_blank" rel="noopener nofollow">{lic}</a>'
        fig = (f'<figure class="stemma"><img src="{e(stemma["file"])}" width="{stemma["larghezza"] // 2}" '
               f'height="{stemma["altezza"] // 2}" alt="Stemma del Comune di {e(c)}"><figcaption>Stemma: '
               f'<a href="{e(stemma["pagina"])}" target="_blank" rel="noopener nofollow">Wikimedia Commons</a>'
               + (f", {e(stemma['autore'])}" if stemma.get("autore") else "") + f", {lic}</figcaption></figure>")
        h = h.replace(f"<h1>{e(titolo)}</h1>", f'<div class="testata-comune"><div><h1>{e(titolo)}</h1>{somm}</div>{fig}</div>')
    else:
        h += somm
    # l'allerta: solo da gialla in su, come in prima pagina, con la striscia in cima al meteo (html_meteo_comune); la
    # riga «oggi verde» no (lui, 29 ott 2026: «quando è verde non mostrarla, da gialla in su e falla come la nostra home»)
    lat = html_meteo_comune(c, meteo_c, allerte, oggi) + farmacia
    if distributori:
        quali = f"dei {distributori} distributori" if distributori > 1 else "del distributore"
        lat += (f'<h3 class="titolo-col">Carburanti</h3><p class="sezioni-link"><a href="/carburanti/#c-{slug(c)}">I prezzi '
                f'di oggi {quali} di {e(c)} ›</a></p>')
    princ = ""
    if eventi:
        princ += f"<h3>Prossimi eventi a {e(c)}</h3><ul class=\"notizie-comune\">" + "".join(
            f'<li><a href="{percorso("evento", ev["id"])}">{e(ev["titolo"])}</a>'
            f'<span class="dove">{e(quando_ev(ev))}</span></li>' for ev in eventi) + "</ul>"
    princ += f"<h3>Le notizie da {e(c)}</h3>"
    if notizie:
        princ += '<ul class="notizie-comune">' + "".join(
            f'<li><a href="{percorso("notizia", n["id"])}">{e(n["titolo"])}</a>'
            f'<span class="dove">{e(_categoria(n))} · {e(data_it(n.get("pubblicato"), lunga=True))}</span>'
            + (f"<p>{e(breve(n['sintesi'], 220))}</p>" if n.get("sintesi") else "") + "</li>" for n in notizie[:100]) + "</ul>"
    else:
        princ += f"<p>Per ora non ci sono notizie da {e(c)}: le trovi qui appena escono.</p>"
    if vicine:
        princ += f"<h3>Le ultime da {e(zona or 'Sannio')}</h3>" + '<ul class="notizie-comune">' + "".join(
            f'<li><a href="{percorso("notizia", n["id"])}">{e(n["titolo"])}</a>'
            f'<span class="dove">{e(n.get("luogo") or "")}{" · " if n.get("luogo") else ""}'
            f'{e(data_it(n.get("pubblicato"), lunga=True))}</span></li>' for n in vicine) + "</ul>"
    princ += '<p class="sezioni-link">Gli altri paesi: <a href="/comuni/">tutti i Comuni del Sannio</a></p>'
    h += f'<div class="comune-griglia"><aside class="comune-lat">{lat}</aside><div class="comune-princ">{princ}</div></div>'
    h += SEGUI
    return f'<article class="appro comune-pag">{h}</article>'


def nome_mese(m):
    return f"{MESI_LUNGHI[int(m[5:7]) - 1]} {m[:4]}"


def html_archivio(mesi):
    """La pagina archivio/: i mesi, dal più recente, con quante notizie."""
    h = _testata_pagina("Archivio", "", "Tutte le notizie, mese per mese", [("Archivio", None)])
    h += ('<p class="sommario">Nessuna notizia viene cancellata: quando esce dalla prima pagina resta qui, allo stesso '
          "indirizzo. Le notizie di Benevento e del Sannio, mese per mese.</p>")
    h += '<ul class="notizie-comune">' + "".join(
        f'<li><a href="/archivio/{m}/">{e(nome_mese(m).capitalize())}</a>'
        f'<span class="dove">{len(v)} {"notizia" if len(v) == 1 else "notizie"}</span></li>'
        for m, v in sorted(mesi.items(), reverse=True)) + "</ul>"
    h += SEGUI
    return f'<article class="appro">{h}</article>'


def html_archivio_mese(m, voci, k, pagine_mese):
    """Una pagina dell'archivio di un mese: i link a tutte le sue notizie, dalla più recente."""
    h = _testata_pagina("Archivio", "", f"Le notizie di {nome_mese(m)}" + (f", pagina {k}" if k > 1 else ""), [("Archivio", "/archivio/"), (nome_mese(m).capitalize(), None)])
    h += (f'<p class="sommario">Tutte le notizie di Benevento e del Sannio pubblicate a {e(nome_mese(m))}, dalla più '
          "recente.</p>")
    h += '<ul class="notizie-comune">' + "".join(
        f'<li><a href="{percorso("notizia", n["id"])}">{e(n["titolo"])}</a><span class="dove">{e(_categoria(n))}'
        + (f" · {e(n['luogo'])}" if n.get("luogo") else "") + f' · {e(data_it(n.get("pubblicato"), lunga=True))}</span></li>'
        for n in voci) + "</ul>"
    if pagine_mese > 1:
        h += '<p class="sezioni-link">Pagine: ' + " · ".join(
            (f"<strong>{i}</strong>" if i == k else f'<a href="/archivio/{m}/' + (f"{i}/" if i > 1 else "") + f'">{i}</a>')
            for i in range(1, pagine_mese + 1)) + "</p>"
    h += '<p class="sezioni-link"><a href="/archivio/">Tutti i mesi</a></p>' + SEGUI
    return f'<article class="appro">{h}</article>'


def html_comuni(quante):
    h = _testata_pagina("Comuni del Sannio", "", "I Comuni della provincia di Benevento", [("Comuni", None)])
    h += ('<p class="sommario">Una pagina per ognuno dei 78 Comuni del Sannio, con le sue notizie, gli eventi, le '
          "scuole chiuse e l'allerta meteo della sua zona.</p>")
    h += '<ul class="elenco-comuni">' + "".join(
        f'<li><a href="{url_comune(c)}">{e(c)}</a>' + (f" <span>{quante[c]}</span>" if quante.get(c) else "") + "</li>"
        for c in COMUNI_BN) + "</ul>"
    h += '<p class="agg-chiusure">Accanto al nome, quante notizie ci sono.</p>'
    h += SEGUI
    return f'<article class="appro">{h}</article>'


# ---------- eventi del calendario ----------
NOMI_TIPO = {"teatro": "Teatro", "danza": "Danza", "concerto": "Concerto", "lirica": "Lirica", "mostra": "Mostra",
             "museo": "Museo", "cinema": "Cinema", "libro": "Libri", "sagra": "Sagra", "festa": "Festa", "mercatino": "Mercatino",
             "natale": "Natale", "carnevale": "Carnevale", "altro": "Evento"}
GIORNI = ["lunedì", "martedì", "mercoledì", "giovedì", "venerdì", "sabato", "domenica"]


def tutti_gli_eventi(sito):
    """eventi.json più quelli già in archivio (archivio/eventi-AAAA-MM.json): ognuno ha la sua pagina per sempre."""
    out, visti = [], set()
    files = [os.path.join(sito, "eventi.json")] + sorted(glob.glob(os.path.join(sito, "archivio", "eventi-*.json")), reverse=True)
    for f in files:
        if not os.path.exists(f):
            continue
        for ev in leggi(f).get("eventi", []):
            if ev.get("id") and ev.get("inizio") and ev["id"] not in visti:
                out.append(ev)
                visti.add(ev["id"])
    return out


GRUPPO = re.compile(r"orchestr|band\b|\bduo\b|trio\b|quartet|quintet|compagnia|\bcoro\b|gruppo|ensemble|^(i|gli|le) |\bper\b|^\S+$", re.I)


def a_lista(v):
    return [x for x in (v if isinstance(v, list) else [v]) if isinstance(x, str) and x.strip()]


def fine_ev(ev):
    return ev["fine"] if ev.get("fine") and ev["fine"] > ev["inizio"] else ev["inizio"]


def quando_ev(ev):
    """«Da giovedì 29 ottobre a domenica 1 novembre 2026», «Sabato 24 ottobre 2026, ore 21:00»,
    «26 e 27 dicembre 2026, 2 e 3 gennaio 2027» (come quandoEv in index.html)."""
    gg = ev.get("giorni") if isinstance(ev.get("giorni"), list) else []
    if 1 < len(gg) <= 8:
        mesi = []
        for x in gg:
            if mesi and mesi[-1][0] == x[:7]:
                mesi[-1][1].append(int(x[8:]))
            else:
                mesi.append((x[:7], [int(x[8:])]))
        pezzi = []
        for i, (m, dd) in enumerate(mesi):
            d = ", ".join(map(str, dd[:-1])) + " e " + str(dd[-1]) if len(dd) > 1 else str(dd[0])
            anno = f" {m[:4]}" if i == len(mesi) - 1 or mesi[i + 1][0][:4] != m[:4] else ""
            pezzi.append(f"{d} {MESI_LUNGHI[int(m[5:7]) - 1]}{anno}")
        t = ", ".join(pezzi) + (f", ore {ev['ora']}" if ev.get("ora") else "")
        return t[0].upper() + t[1:]
    if len(gg) > 8:
        a, b = dt.date.fromisoformat(ev["inizio"]), dt.date.fromisoformat(fine_ev(ev))
        return f"Da {a.day} {MESI_LUNGHI[a.month - 1]} a {b.day} {MESI_LUNGHI[b.month - 1]} {b.year}, in {len(gg)} giorni"

    def g(s):
        d = dt.date.fromisoformat(s)
        return f"{GIORNI[d.weekday()]} {d.day} {MESI_LUNGHI[d.month - 1]}"
    f = fine_ev(ev)
    t = f"da {g(ev['inizio'])} a {g(f)}" if f > ev["inizio"] else g(ev["inizio"])
    t += f" {f[:4]}" + (f", ore {ev['ora']}" if ev.get("ora") else "")
    return t[0].upper() + t[1:]


def inizio_dt(ev):
    """Inizio con l'ora italiana (solo se c'è l'ora)."""
    from zoneinfo import ZoneInfo
    return dt.datetime.fromisoformat(f"{ev['inizio']}T{ev['ora']}").replace(tzinfo=ZoneInfo("Europe/Rome"))


def ics_evento(ev, url):
    """Il file .ics: senza ora è un evento di tutto il giorno; con l'ora dura 2 ore (la fine non la sappiamo)."""
    def esc(t):
        return str(t or "").replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\n", "\\n")

    def piega(riga):   # righe di al massimo 75 byte, come vuole il formato
        out, b = [], riga.encode("utf-8")
        while len(b) > 75:
            taglio = 75 if not out else 74
            while taglio > 0 and (b[taglio] & 0xC0) == 0x80:
                taglio -= 1
            out.append(b[:taglio].decode("utf-8"))
            b = b[taglio:]
        out.append(b.decode("utf-8"))
        return "\r\n ".join(out)
    adesso = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    descr = ev.get("breve", "") + ("\nOrario di fine non indicato." if ev.get("ora") else "") + "\n" + url
    righe = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//Notizie Benevento//Eventi//IT", "CALSCALE:GREGORIAN",
             "METHOD:PUBLISH", "BEGIN:VEVENT", f"UID:{ev['id']}@notiziebenevento.it", f"DTSTAMP:{adesso}"]
    if ev.get("ora"):
        a = inizio_dt(ev).astimezone(dt.timezone.utc)
        righe += [f"DTSTART:{a.strftime('%Y%m%dT%H%M%SZ')}", f"DTEND:{(a + dt.timedelta(hours=2)).strftime('%Y%m%dT%H%M%SZ')}"]
    else:
        dopo = dt.date.fromisoformat(fine_ev(ev)) + dt.timedelta(days=1)
        righe += [f"DTSTART;VALUE=DATE:{ev['inizio'].replace('-', '')}", f"DTEND;VALUE=DATE:{dopo.strftime('%Y%m%d')}"]
        # solo alcuni giorni (per esempio i fine settimana): gli altri si tolgono
        gg = set(ev.get("giorni") or [])
        if gg:
            fuori, d = [], dt.date.fromisoformat(ev["inizio"])
            while d <= dt.date.fromisoformat(fine_ev(ev)):
                if d.isoformat() not in gg:
                    fuori.append(d.strftime("%Y%m%d"))
                d += dt.timedelta(days=1)
            if fuori:
                righe += [f"RRULE:FREQ=DAILY;UNTIL={fine_ev(ev).replace('-', '')}", "EXDATE;VALUE=DATE:" + ",".join(fuori)]
                righe[-3] = f"DTEND;VALUE=DATE:{(dt.date.fromisoformat(ev['inizio']) + dt.timedelta(days=1)).strftime('%Y%m%d')}"
    righe += [f"SUMMARY:{esc(ev['titolo'])}", f"LOCATION:{esc(ev.get('luogo', '') + ', ' + ev.get('comune', ''))}",
              f"DESCRIPTION:{esc(descr)}", f"URL:{url}", "STATUS:" + ("CANCELLED" if ev.get("annullato") else "CONFIRMED"),
              "END:VEVENT", "END:VCALENDAR"]
    return "\r\n".join(piega(r) for r in righe) + "\r\n"


def html_evento(ev):
    fonti = ev.get("fonti") if isinstance(ev.get("fonti"), list) else []
    cc = comuni_di(ev.get("comune"))
    h = _testata_pagina(NOMI_TIPO.get(ev.get("tipo"), "Evento"), ev.get("comune"), ev["titolo"],
                        [("Eventi", "/sezione/eventi/")] + ([(cc[0], url_comune(cc[0]))] if len(cc) == 1 else []))
    if ev.get("annullato"):
        h += '<p class="ev-annullato">Annullato</p>'
    dove = f'{e(ev.get("luogo"))}, {e(ev.get("comune"))}'
    righe = [("Quando", e(quando_ev(ev)))] + ([("Orari", e(ev["orari"][:1].upper() + ev["orari"][1:]))] if ev.get("orari") else [])
    righe.append(("Dove", dove))
    if ev.get("prezzo"):
        righe.append(("Ingresso", e(ev["prezzo"][:1].upper() + ev["prezzo"][1:])))
    if a_lista(ev.get("artisti")):
        righe.append(("Con", e(", ".join(a_lista(ev["artisti"])))))
    if a_lista(ev.get("organizzatore")):
        righe.append(("Organizza", e(" e ".join(a_lista(ev["organizzatore"])))))
    h += '<dl class="scheda-evento">' + "".join(f"<dt>{t}</dt><dd>{v}</dd>" for t, v in righe) + "</dl>"
    h += '<div class="ev-azioni" style="min-height:38px"></div>'
    if locandina(ev):
        org = " e ".join(a_lista(ev.get("organizzatore")))
        h += html_locandina(locandina(ev), org)
    if foto_tema(ev):
        b = foto_tema(ev)[:-4]
        h += (f'<figure class="foto-tema"><img src="{b}-m.jpg" srcset="{b}-m.jpg 768w, {b}.jpg 1536w" '
              'sizes="(max-width: 800px) 100vw, 760px" width="1536" height="1024" alt="" decoding="async">'
              "<figcaption>Immagine illustrativa creata con l'intelligenza artificiale: non è una foto dell'evento.</figcaption></figure>")
    par = ev.get("descrizione") if isinstance(ev.get("descrizione"), list) and ev.get("descrizione") else [ev.get("breve", "")]
    h += '<div class="racconto">' + "".join(_frase("p", r, fonti) for r in par) + "</div>"
    h += _fonti(fonti)
    return f'<article class="appro">{h}</article>'


# ---------- la testa della pagina (titolo, descrizione, anteprima, dati strutturati) ----------
FACEBOOK = "https://www.facebook.com/notiziebenevento"
ORG = {"@type": "NewsMediaOrganization", "@id": SITO + "/#org", "name": NOME, "url": SITO + "/",
       "sameAs": [FACEBOOK, INSTAGRAM, "https://t.me/notiziebenevento"], "publishingPrinciples": SITO + "/chi-siamo/",
       "logo": {"@type": "ImageObject", "url": SITO + "/icona-512.png", "width": 512, "height": 512},
       "areaServed": {"@type": "AdministrativeArea", "name": "Provincia di Benevento"}}


def titolo_google(x):
    """Il titolo per Google (<title>): quello corto scritto apposta, se c'è; Google ne mostra circa 60 caratteri."""
    return re.sub(r"\s+", " ", str(x.get("titolo_google") or x["titolo"])).strip()


def blocco_seo(title, descr, url, immagine, tipo="website", jsonld=None, extra="", dim=(1200, 630), og_title=None):
    h = [f"<title>{e(title)}</title>",
         f'<meta name="description" content="{e(descr)}">',
         f'<link rel="canonical" href="{e(url)}">',
         f'<meta property="og:type" content="{tipo}">',
         f'<meta property="og:site_name" content="{NOME}">',
         f'<meta property="og:title" content="{e(og_title or title)}">',
         f'<meta property="og:description" content="{e(descr)}">',
         f'<meta property="og:url" content="{e(url)}">',
         f'<meta property="og:image" content="{e(SITO + immagine)}">',
         f'<meta property="og:image:width" content="{dim[0]}">',
         f'<meta property="og:image:height" content="{dim[1]}">',
         '<meta property="og:locale" content="it_IT">',
         '<meta name="twitter:card" content="summary_large_image">']
    if extra:
        h.append(extra)
    if jsonld:
        h.append('<script type="application/ld+json">' +
                 json.dumps(jsonld, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/") + "</script>")
    return "<!--seo-->\n" + "\n".join(h) + "\n<!--/seo-->"


# ---------- i link alle notizie scritti nell'HTML (per Google) ----------
# Voluto dal proprietario il 25 ott 2026 («vai fai la cosa migliore per google»): le notizie le disegna index.html dopo
# aver letto notizie.json, e nell'HTML delle pagine non c'era un solo link a una notizia (prima pagina, sezioni, zone,
# articoli). Google li vede solo quando esegue il JavaScript, a volte ore dopo, e le notizie nuove le scopriva dalle
# sitemap, che legge circa una volta al giorno: la Miwa a Ragusa, uscita alle 21:09, alle 23 per Google era ancora
# «sconosciuta». Google: «ogni pagina che ti interessa deve avere un link da almeno un'altra pagina del sito», con un
# <a href> vero (developers.google.com/search/docs/crawling-indexing/links-crawlable). Il riquadro sta tra <main> e il
# piede (<!--ultime--> in index.html), fuori da quello che ridisegna index.html: la pagina non salta.
ULTIME = 15          # «Le ultime notizie» in fondo a ogni pagina
ULTIME_HOME = 30     # in prima pagina, la più visitata da Google
DELLA_SEZIONE = 40   # nelle pagine delle sezioni e delle zone
ARCHIVIO_PAGINA = 300   # notizie per pagina dell'archivio di un mese
SEGNAPOSTO_ULTIME = re.compile(r"<!--ultime-->.*?<!--/ultime-->", re.S)


def html_ultime(elenchi, archivio=True):
    """Il riquadro dei link: elenchi = [(titolo, notizie)]; una notizia compare una volta sola."""
    h, viste = "", set()
    for titolo, voci in elenchi:
        voci = [n for n in voci if n["id"] not in viste]
        viste |= {n["id"] for n in voci}
        if voci:
            h += f"<h2>{e(titolo)}</h2><ul>" + "".join(
                f'<li><a href="{percorso("notizia", n["id"])}">{e(n["titolo"])}</a> '
                f'<span>{e(data_it(n.get("pubblicato"), lunga=True))}</span></li>' for n in voci) + "</ul>"
    if h and archivio:
        h += '<p class="tutte"><a href="/archivio/">Tutte le notizie, mese per mese ›</a></p>'
    return f'<section class="ultime" aria-label="Altre notizie">{h}</section>' if h else ""


def con_ultime(s, blocco):
    if s.count("<!--ultime-->") != 1 or s.count("<!--/ultime-->") != 1 or len(SEGNAPOSTO_ULTIME.findall(s)) != 1:
        raise RuntimeError("index.html è cambiato: il posto del riquadro <!--ultime--><!--/ultime--> deve esserci una "
                           "volta sola (anche nei commenti)")
    return SEGNAPOSTO_ULTIME.sub(lambda m: f"<!--ultime-->{blocco}<!--/ultime-->", s)


def pagina(modello, seo, pagina_js, contenuto="", articolo=False, ultime=None):
    """index.html con un'altra testa e (se c'è) il contenuto già scritto; `ultime`: il riquadro dei link al posto di
    quello del modello (le ultime notizie)."""
    s = modello if ultime is None else con_ultime(modello, ultime)
    def sostituisci(vecchio, nuovo, conta=1):
        nonlocal s
        if s.count(vecchio) != conta:
            raise RuntimeError(f"index.html è cambiato: non trovo {vecchio[:60]!r}")
        s = s.replace(vecchio, nuovo)
    sostituisci('<meta charset="utf-8">', '<meta charset="utf-8">\n<base href="/">')
    s = re.sub(r"<!--seo-->.*?<!--/seo-->", lambda m: seo, s, count=1, flags=re.S)
    sostituisci("</head>", "<script>window.NB_PAGINA = " +
                json.dumps(pagina_js, ensure_ascii=False).replace("</", "<\\/") + ";</script>\n</head>")
    sostituisci('<main id="contenuto"></main>', f'<main id="contenuto">{contenuto}</main>')
    # il titolo principale (h1) è quello della notizia o della sezione, non il nome del sito
    sostituisci('<h1 class="grande">Notizie Benevento</h1>', '<span class="grande">Notizie Benevento</span>')
    # il menu c'è in tutte le pagine (regola 1 delle pagine, CLAUDE.md, 28 ott 2026): `articolo` non lo nasconde più
    return s


def avvisa_websub():
    """Dice al hub WebSub che feed.xml è cambiato (Google: «se usi RSS o Atom puoi usare WebSub per avvisare i motori di
    ricerca, Google compreso delle modifiche»; dal 25 ott 2026)."""
    import urllib.parse
    import urllib.request
    dati = urllib.parse.urlencode({"hub.mode": "publish", "hub.url": f"{SITO}/feed.xml"}).encode()
    with urllib.request.urlopen(urllib.request.Request(HUB, data=dati, method="POST"), timeout=30) as r:
        print(f"WebSub: feed annunciato al hub, risposta {r.status}")


def invia_indexnow(path):
    """Avvisa Bing (e gli altri motori di IndexNow) delle pagine nuove o cambiate. Google non usa IndexNow: per Google,
    se tra le pagine c'è una notizia, il hub WebSub del feed."""
    import urllib.request
    with open(path, encoding="utf-8") as f:
        urls = json.load(f)
    if not urls:
        print("IndexNow: niente di nuovo")
        return
    if any("/notizia/" in u for u in urls):
        try:
            avvisa_websub()
        except Exception as ex:   # non ferma IndexNow
            print(f"WebSub: il hub non ha risposto ({type(ex).__name__}: {ex})")
    corpo = json.dumps({"host": "notiziebenevento.it", "key": INDEXNOW_CHIAVE,
                        "keyLocation": f"{SITO}/{INDEXNOW_CHIAVE}.txt", "urlList": urls}).encode()
    req = urllib.request.Request("https://api.indexnow.org/indexnow", data=corpo, method="POST",
                                 headers={"Content-Type": "application/json; charset=utf-8"})
    with urllib.request.urlopen(req, timeout=30) as r:
        print(f"IndexNow: {len(urls)} pagine inviate, risposta {r.status}")


def main():
    ap_ = argparse.ArgumentParser()
    ap_.add_argument("--sito", default=os.path.dirname(QUI))
    ap_.add_argument("--sitemap-prima", help="la sitemap pubblicata prima, per sapere quali pagine sono cambiate")
    ap_.add_argument("--indexnow", help="dove scrivere l'elenco delle pagine cambiate (per IndexNow)")
    ap_.add_argument("--immagine-generica", help="crea solo l'immagine di anteprima del sito")
    ap_.add_argument("--invia-indexnow", help="manda a IndexNow l'elenco scritto con --indexnow")
    a = ap_.parse_args()
    if a.invia_indexnow:
        invia_indexnow(a.invia_indexnow)
        return
    if a.immagine_generica:
        immagine_generica(a.immagine_generica)
        print("OK", a.immagine_generica)
        return
    sito = a.sito
    with open(os.path.join(sito, "index.html"), encoding="utf-8") as f:
        modello = f.read()
    if "<!--seo-->" not in modello:
        raise SystemExit("index.html senza il blocco <!--seo-->")
    prima, notizie, appro = tutte(sito)
    # il riquadro dei link (vedi html_ultime): nel modello quello di tutte le pagine, le ultime notizie
    modello = con_ultime(modello, "")
    modello_home = con_ultime(modello, html_ultime([("Le ultime notizie", notizie[:ULTIME_HOME])]))
    modello = con_ultime(modello, html_ultime([("Le ultime notizie", notizie[:ULTIME])]))
    try:
        with open(os.path.join(sito, "chiusure.json"), encoding="utf-8") as f:
            chius = json.load(f)
    except (OSError, ValueError):
        chius = {"chiusure": []}
    try:
        import PIL  # noqa: F401
        con_immagini = True
    except ImportError:
        con_immagini = False
        print("AVVISO: Pillow non c'è, uso l'immagine del sito per tutte le notizie", file=sys.stderr)
    for d in ("notizia", "approfondimento", "sezione", "zona", "evento", "comune", "comuni", "carburanti", "curiosita", "calcio",
              "servizi", "farmacie-di-turno"):
        shutil.rmtree(os.path.join(sito, d), ignore_errors=True)
    per_id = {n["id"]: n for n in notizie}
    usate, mappa = set(), []   # mappa: (url, lastmod)
    adesso = dt.datetime.now(dt.timezone.utc).astimezone()

    def img(x, tipo):
        if not con_immagini:
            return "/condivisione.png"
        p = immagine_notizia(sito, x, tipo)
        usate.add(p.lstrip("/"))
        return p

    for n in notizie:
        url = SITO + percorso("notizia", n["id"])
        im = img(n, "notizia")
        a_ = n["articolo"]
        modificato = max((x for x in (n.get("pubblicato"), a_.get("aggiornato"), (a_.get("aggiornamento") or {}).get("quando"))
                          if quando_dt(x)), key=quando_dt, default=n.get("pubblicato"))
        sez = NOMI_CAT.get(n.get("categoria"), "Altro")
        coll = next((x for x in appro if n["id"] in (x.get("collegate") or [])), None)
        fonti = (vista_ufficiale(n).get("articolo") or {}).get("fonti")
        fonti = fonti if isinstance(fonti, list) else []
        jsonld = {"@context": "https://schema.org", "@graph": [
            {"@type": "NewsArticle", "@id": url + "#articolo", "headline": breve(titolo_google(n), 110),
             "description": n.get("sintesi"), "datePublished": n.get("pubblicato"), "dateModified": modificato,
             "image": [SITO + x for x in dict.fromkeys([foto_in_alto(n) or foto_tema(n)] + foto_inviate(n)) if x] + [SITO + im], "inLanguage": "it-IT", "articleSection": sez, "isAccessibleForFree": True,
             "mainEntityOfPage": url, "author": {"@type": "Organization", "name": NOME, "url": SITO + "/chi-siamo/"},
             "publisher": ORG, "contentLocation": {"@type": "Place", "name": n.get("luogo")},
             "isBasedOn": [f["url"] for f in fonti if re.match(r"^https?://", str(f.get("url") or ""))]},
            {"@type": "BreadcrumbList", "itemListElement": [   # lo stesso percorso della pagina (passi_notizia)
                {"@type": "ListItem", "position": i, "name": nome, **({"item": SITO + u} if u else {})}
                for i, (nome, u) in enumerate([(NOME, "/")] + passi_notizia(n) + [(n["titolo"], None)], 1)]}]}
        extra = (f'<meta property="article:published_time" content="{e(n.get("pubblicato"))}">\n'
                 f'<meta property="article:section" content="{e(sez)}">')
        seo = blocco_seo(f"{titolo_google(n)} – {NOME}", breve(n.get("sintesi")), url, im, "article", jsonld, extra,
                         og_title=f"{n['titolo']} – {NOME}")
        altre = [x for x in notizie if x["id"] != n["id"]]
        ultime = html_ultime([(f"Altre notizie: {sez}", [x for x in altre if x.get("categoria") == n.get("categoria")][:6]),
                              ("Le ultime notizie", altre[:10])])
        scrivi(os.path.join(sito, "notizia", n["id"], "index.html"),
               pagina(modello, seo, {"rotta": "#articolo/" + n["id"]}, html_articolo(n, coll), articolo=True,
                      ultime=ultime))
        mappa.append((url, modificato))

    def rimando(path, dest, tit, frase):
        scrivi(path, f'<!doctype html><meta charset="utf-8"><title>{e(tit)} – {NOME}</title>'
                     f'<link rel="canonical" href="{e(dest)}"><meta name="robots" content="noindex">'
                     f'<meta http-equiv="refresh" content="0; url={e(dest)}">'
                     f'<script>location.replace({json.dumps(dest)})</script>'
                     f'<p>{e(frase)} <a href="{e(dest)}">{e(tit)}</a>.</p>\n')

    # notizie unite in un'altra (archivio/rimandi.json): il vecchio indirizzo porta a quella rimasta
    p_rim = os.path.join(sito, "archivio", "rimandi.json")
    for vecchio, nuovo in ((leggi(p_rim).get("notizie") or {}) if os.path.exists(p_rim) else {}).items():
        if nuovo in per_id and vecchio not in per_id:
            rimando(os.path.join(sito, "notizia", vecchio, "index.html"), SITO + percorso("notizia", nuovo),
                    per_id[nuovo]["titolo"], "Questa notizia è stata unita a")

    # le cartelle che il JavaScript delle pagine nomina da sole ("/evento/" + id): Google le prova e trovava un 404
    # (Search Console, 26 ott 2026: /approfondimento/, /comune/, /img/temi/, /evento/). Portano all'elenco giusto.
    for cartella, dest, tit in (("notizia", "/archivio/", "Archivio delle notizie"),
                                ("approfondimento", "/archivio/", "Archivio delle notizie"),
                                ("evento", "/sezione/eventi/", "Eventi a Benevento e provincia"),
                                ("comune", "/comuni/", "Comuni del Sannio"),
                                ("img/temi", "/chi-siamo/", "Chi siamo")):
        rimando(os.path.join(sito, *cartella.split("/"), "index.html"), SITO + dest, tit, "Vai a")

    for x in appro:
        url = SITO + percorso("approfondimento", x["id"])
        im = img(x, "approfondimento")
        jsonld = {"@context": "https://schema.org", "@type": "NewsArticle", "@id": url + "#articolo",
                  "headline": breve(titolo_google(x), 110), "description": x.get("sommario"),
                  "datePublished": x.get("pubblicato") or x.get("aggiornato"), "dateModified": x.get("aggiornato"),
                  "image": [SITO + im], "inLanguage": "it-IT", "articleSection": "Approfondimento",
                  "mainEntityOfPage": url, "author": {"@type": "Organization", "name": NOME, "url": SITO + "/chi-siamo/"},
                  "publisher": ORG}
        seo = blocco_seo(f"{titolo_google(x)} – {NOME}", breve(x.get("sommario")), url, im, "article", jsonld,
                         og_title=f"{x['titolo']} – {NOME}")
        scrivi(os.path.join(sito, "approfondimento", x["id"], "index.html"),
               pagina(modello, seo, {"rotta": "#approfondimento/" + x["id"]}, html_approfondimento(x, per_id), articolo=True))
        mappa.append((url, x.get("aggiornato")))

    # eventi del calendario: una pagina e un .ics ciascuno
    eventi = tutti_gli_eventi(sito)
    for ev in eventi:
        url = SITO + percorso("evento", ev["id"])
        ft = locandina(ev) or foto_tema(dict(ev, immagine=ev.get("immagine") or ""))
        luogo = {"@type": "Place", "name": ev.get("luogo"), "address": {"@type": "PostalAddress",
                 "addressLocality": ev.get("comune"), "addressRegion": "BN", "addressCountry": "IT"}}
        jsonld = {"@context": "https://schema.org", "@type": "Event", "name": ev["titolo"], "url": url,
                  "startDate": inizio_dt(ev).isoformat(timespec="minutes") if ev.get("ora") else ev["inizio"],
                  "eventStatus": "https://schema.org/Event" + ("Cancelled" if ev.get("annullato") else "Scheduled"),
                  "eventAttendanceMode": "https://schema.org/OfflineEventAttendanceMode", "location": luogo,
                  "description": ev.get("breve"), "image": [SITO + (ft or "/condivisione.png")]}
        # Google la chiede anche per gli eventi di un giorno; con l'ora d'inizio e senza quella di fine, la stessa
        jsonld["endDate"] = fine_ev(ev) if fine_ev(ev) > ev["inizio"] or not ev.get("ora") else jsonld["startDate"]
        pz = str(ev.get("prezzo") or "")
        if re.match(r"(ingresso |entrata )?(libero|gratuit|gratis)", pz.strip(), re.I):   # non «navetta gratuita» tra le tariffe
            jsonld["isAccessibleForFree"] = True
            jsonld["offers"] = {"@type": "Offer", "price": "0", "priceCurrency": "EUR", "url": url}
        elif re.fullmatch(r"(?:biglietto )?(\d+(?:,\d\d)?) euro", pz.strip(), re.I):   # un prezzo solo; gli elenchi di tariffe no
            jsonld["offers"] = {"@type": "Offer", "price": re.search(r"[\d,]+", pz).group().replace(",", "."),
                                "priceCurrency": "EUR", "url": url}
        if ev.get("organizzatore"):
            jsonld["organizer"] = [{"@type": "Organization", "name": x} for x in a_lista(ev["organizzatore"])]
        if ev.get("artisti"):
            jsonld["performer"] = [{"@type": "PerformingGroup" if GRUPPO.search(x) else "Person", "name": x}
                                   for x in a_lista(ev["artisti"])]
        # anteprima su WhatsApp e Facebook: la foto del tema (1536×1024), sennò l'immagine del sito
        dim = (dim_jpeg(ft) if locandina(ev) else (1536, 1024)) if ft else (1200, 630)
        seo = blocco_seo(f"{ev['titolo']}, {ev.get('comune')} – {quando_ev(ev)} – {NOME}", breve(ev.get("breve")), url,
                         ft or "/condivisione.png", jsonld=jsonld, dim=dim if all(dim) else (1200, 630))
        cartella = os.path.join(sito, "evento", ev["id"])
        scrivi(os.path.join(cartella, "index.html"),
               pagina(modello, seo, {"rotta": "#evento/" + ev["id"], "evento": ev}, html_evento(ev), articolo=True))
        with open(os.path.join(cartella, "evento.ics"), "w", encoding="utf-8", newline="") as f:
            f.write(ics_evento(ev, url))
        mappa.append((url, None))
    # eventi uniti in un altro (archivio/rimandi.json, «eventi»): come le notizie, il vecchio indirizzo porta a quello rimasto
    ev_per_id = {x["id"]: x for x in eventi}
    for vecchio, nuovo in ((leggi(p_rim).get("eventi") or {}) if os.path.exists(p_rim) else {}).items():
        if nuovo in ev_per_id and vecchio not in ev_per_id:
            rimando(os.path.join(sito, "evento", vecchio, "index.html"), SITO + percorso("evento", nuovo),
                    ev_per_id[nuovo]["titolo"], "Questo evento è stato unito a")

    # sezioni e zone: la prima pagina filtrata
    for perc, filtro, title, h1, descr in SEZIONI:
        url = f"{SITO}/{perc}/"
        dentro = [n for n in notizie if all(n.get("categoria" if k == "cat" else "zona") == v for k, v in filtro.items())]
        jsonld = {"@context": "https://schema.org", "@type": "CollectionPage", "name": h1, "url": url,
                  "isPartOf": {"@type": "WebSite", "name": NOME, "url": SITO + "/"}}
        from facebook import fuso
        oggi_qui = adesso.astimezone(fuso()).date()
        sp = speciale_di(oggi_qui) if filtro.get("cat") == "avvisi" else None
        seo = blocco_seo(f"{sp['title'] if sp else title} – {NOME}", sp["descr"] if sp else descr, url, "/condivisione.png",
                         jsonld=jsonld)
        # solo il titolo: le notizie le mette index.html (un elenco qui farebbe saltare la pagina quando arrivano);
        # i link alle notizie della sezione stanno nel riquadro in fondo (html_ultime). La pagina Avvisi invece è scritta
        # per intero (html_avvisi): index.html la ridisegna uguale.
        corpo = html_avvisi(notizie, oggi_qui, h1) if filtro.get("cat") == "avvisi" else f'<h1 class="titolo-sezione">{e(h1)}</h1>'
        scrivi(os.path.join(sito, perc, "index.html"),
               pagina(modello, seo, dict(filtro, h1=h1), corpo,
                      ultime=html_ultime([(h1, dentro[:DELLA_SEZIONE]), ("Le ultime notizie", notizie[:10])])))
        mappa.append((url, dentro[0].get("pubblicato") if dentro else None))

    # l'archivio mese per mese (archivio/, archivio/AAAA-MM/): i link a tutte le notizie, anche a quelle uscite dalla
    # prima pagina. L'archivio di index.html («#archivio») per Google non è una pagina: senza queste, le notizie vecchie
    # le trovava solo nella sitemap. Le pagine si rifanno a ogni pubblicazione (i file .json dell'archivio non si toccano)
    mesi = {}
    for n in notizie:
        if re.match(r"^\d{4}-\d{2}", str(n.get("pubblicato") or "")):
            mesi.setdefault(n["pubblicato"][:7], []).append(n)
    for d in glob.glob(os.path.join(sito, "archivio", "[0-9][0-9][0-9][0-9]-[0-9][0-9]")):
        if os.path.isdir(d):
            shutil.rmtree(d)
    briciole = lambda *x: {"@type": "BreadcrumbList", "itemListElement": [
        {"@type": "ListItem", "position": i, "name": nome, **({"item": u} if u else {})}
        for i, (nome, u) in enumerate([(NOME, SITO + "/")] + list(x), 1)]}
    for m, voci in mesi.items():
        pezzi = [voci[i:i + ARCHIVIO_PAGINA] for i in range(0, len(voci), ARCHIVIO_PAGINA)]
        for k, pezzo in enumerate(pezzi, 1):
            rel = f"archivio/{m}/" + (f"{k}/" if k > 1 else "")
            url = f"{SITO}/{rel}"
            nome = nome_mese(m)
            jsonld = {"@context": "https://schema.org", "@graph": [
                {"@type": "CollectionPage", "name": f"Le notizie di {nome}", "url": url,
                 "isPartOf": {"@type": "WebSite", "name": NOME, "url": SITO + "/"}},
                briciole(("Archivio", SITO + "/archivio/"), (nome.capitalize(), None))]}
            seo = blocco_seo(f"Notizie di {nome}" + (f" (pagina {k})" if k > 1 else "") + f": l'archivio – {NOME}",
                             f"Tutte le notizie di Benevento e del Sannio pubblicate a {nome}: cronaca, strade, politica, "
                             "sport ed eventi, con i link agli articoli originali.", url, "/condivisione.png", jsonld=jsonld)
            scrivi(os.path.join(sito, rel, "index.html"),
                   pagina(modello, seo, {"statica": True}, html_archivio_mese(m, pezzo, k, len(pezzi)), articolo=True))
            mappa.append((url, pezzo[0].get("pubblicato")))
    url = SITO + "/archivio/"
    seo = blocco_seo(f"Archivio delle notizie, mese per mese – {NOME}", "Tutte le notizie di Benevento e del Sannio "
                     "pubblicate da Notizie Benevento, mese per mese: nessuna viene cancellata.", url, "/condivisione.png",
                     jsonld={"@context": "https://schema.org", "@graph": [
                         {"@type": "CollectionPage", "name": "Archivio delle notizie", "url": url,
                          "isPartOf": {"@type": "WebSite", "name": NOME, "url": SITO + "/"}},
                         briciole(("Archivio", None))]})
    scrivi(os.path.join(sito, "archivio", "index.html"),
           pagina(modello, seo, {"statica": True}, html_archivio(mesi), articolo=True))
    mappa.append((url, notizie[0].get("pubblicato") if notizie else None))

    # chi siamo: già scritta nella pagina, index.html la lascia com'è (NB_PAGINA.statica)
    url = SITO + "/chi-siamo/"
    seo = blocco_seo(f"Chi siamo – {NOME}", "Come lavora Notizie Benevento: le notizie di Benevento e del Sannio "
                     "confrontate tra i giornali locali e i siti ufficiali, con i link agli articoli originali.", url,
                     "/condivisione.png", jsonld={"@context": "https://schema.org", "@type": "AboutPage",
                                                  "name": "Chi siamo", "url": url, "mainEntity": ORG})
    scrivi(os.path.join(sito, "chi-siamo", "index.html"), pagina(modello, seo, {"statica": True}, html_chi_siamo(), articolo=True))
    mappa.append((url, None))

    # la pagina «non trovata» (404.html, GitHub Pages la mostra per ogni indirizzo che non c'è): con la testata e il
    # menu come tutte (regola 1 delle pagine, CLAUDE.md); la notizia non ancora scritta si apre dentro il sito, come
    # nel 404.html del repository, che resta per quando le pagine non si generano
    rimando_404 = ('<meta name="robots" content="noindex">\n<script>(function () { var m = location.pathname.match('
               '/^\\/(notizia|approfondimento)\\/([a-z0-9-]+)\\/?$/); if (m) location.replace("/#" + (m[1] === "notizia" ? '
               '"articolo" : "approfondimento") + "/" + m[2]); })();</script>')
    seo = blocco_seo(f"Pagina non trovata – {NOME}", "Questo indirizzo non esiste: le notizie di Notizie Benevento non "
                     "vengono mai cancellate, cercale nell'archivio.", SITO + "/404.html", "/condivisione.png", extra=rimando_404)
    h = _testata_pagina(NOME, "", "Pagina non trovata", [("Pagina non trovata", None)])
    h += ('<p class="sommario">Questo indirizzo non esiste. Le notizie non vengono mai cancellate: cercale '
          'nell\'<a href="/#archivio">archivio</a> o torna alla <a href="/">prima pagina</a>.</p>')
    scrivi(os.path.join(sito, "404.html"), pagina(modello, seo, {"statica": True}, f'<article class="appro">{h}</article>',
                                                  articolo=True))

    # le chiusure dei Comuni (strumenti/chiusure.py): la pagina c'è sempre, anche vuota (la cercano su Google)
    url = SITO + "/scuole-chiuse/"
    seo = blocco_seo(f"Scuole chiuse oggi e domani nel Sannio – {NOME}", "Le scuole chiuse a Benevento e in provincia, "
                     "oggi e domani: i Comuni con le ordinanze dei sindaci, aggiornati anche di notte.", url,
                     "/condivisione.png", jsonld={"@context": "https://schema.org", "@type": "WebPage",
                                                  "name": "Scuole chiuse nel Sannio", "url": url,
                                                  "isPartOf": {"@type": "WebSite", "name": NOME, "url": SITO + "/"}})
    from facebook import fuso
    scrivi(os.path.join(sito, "scuole-chiuse", "index.html"),
           pagina(modello, seo, {"statica": True, "chiusure": True},
                  html_scuole_chiuse(chius, adesso.astimezone(fuso()).date()), articolo=True))
    mappa.append((url, chius.get("aggiornato")))

    # le strade chiuse: le notizie con «traffico» (AGENTE.md); la pagina c'è sempre, anche vuota
    oggi = adesso.astimezone(fuso()).date()
    url = SITO + "/strade-chiuse/"
    seo = blocco_seo(f"Strade chiuse oggi a Benevento e nel Sannio – {NOME}", "Strade chiuse, sensi unici, lavori e "
                     "bus deviati a Benevento e in provincia, oggi e nei prossimi giorni, con le ordinanze dei Comuni e "
                     "i comunicati ANAS. Aggiornato ogni ora.", url, "/condivisione.png",
                     jsonld={"@context": "https://schema.org", "@type": "WebPage", "name": "Strade chiuse nel Sannio",
                             "url": url, "isPartOf": {"@type": "WebSite", "name": NOME, "url": SITO + "/"}})
    ora, poi = strade_chiuse(notizie, oggi)
    try:   # dove sono le strade (strumenti/strade_luoghi.py, prima di questo nella pubblicazione)
        luoghi = (leggi(os.path.join(sito, "strade-luoghi.json")) or {}).get("luoghi") or {}
    except (OSError, ValueError):
        luoghi = {}
    pin = segnaposti_strade(ora, poi, oggi, luoghi)
    scrivi(os.path.join(sito, "strade-chiuse", "index.html"),
           pagina(modello, seo, {"statica": True, "strade": pin},
                  html_strade_chiuse(ora, poi, oggi, prima.get("aggiornato"), pin), articolo=True))
    mappa.append((url, prima.get("aggiornato")))

    # i contributi (strumenti/contributi.py): la pagina (anche vuota) e una per contributo
    try:
        contr = leggi(os.path.join(sito, "contributi.json")) or {}
    except (OSError, ValueError):
        contr = {}
    tutti_contr = contr.get("contributi") or []
    aperti = sorted([v for v in tutti_contr if not v.get("scaduto")] + contributi_dei_comuni(notizie, oggi),
                    key=lambda v: v.get("scadenza") or "9999")
    url = f"{SITO}/{CART_AGEV}/"
    seo = blocco_seo(f"Agevolazioni Benevento e Sannio: contributi, bonus, bandi e click day – {NOME}",
                     "Le agevolazioni aperte per imprese, famiglie, associazioni e Comuni di Benevento e del Sannio: contributi, bonus e bandi di "
                     "Camera di Commercio, Regione Campania, Ministeri e Comuni, con scadenze e link ufficiali. Aggiornati ogni giorno.",
                     url, "/condivisione.png", jsonld={"@context": "https://schema.org", "@type": "CollectionPage",
                                                      "name": TITOLO_CONTR, "url": url,
                                                      "isPartOf": {"@type": "WebSite", "name": NOME, "url": SITO + "/"}})
    scrivi(os.path.join(sito, CART_AGEV, "index.html"),
           pagina(modello, seo, {"cat": "contributi", "h1": TITOLO_CONTR}, html_contributi(aperti, oggi, contr.get("aggiornato"))))
    mappa.append((url, contr.get("aggiornato")))
    for v in tutti_contr:
        url = f"{SITO}/{CART_AGEV}/{v['id']}/"
        seo = blocco_seo(f"{v['titolo'][:70]} – Agevolazioni Benevento e Sannio – {NOME}",
                         (v.get("cose") or v["titolo"])[:155], url, "/condivisione.png",
                         jsonld={"@context": "https://schema.org", "@type": "WebPage", "name": v["titolo"], "url": url,
                                 "isPartOf": {"@type": "WebSite", "name": NOME, "url": SITO + "/"},
                                 "breadcrumb": {"@type": "BreadcrumbList", "itemListElement": [
                                     {"@type": "ListItem", "position": 1, "name": NOME, "item": SITO + "/"},
                                     {"@type": "ListItem", "position": 2, "name": "Agevolazioni", "item": f"{SITO}/{CART_AGEV}/"},
                                     {"@type": "ListItem", "position": 3, "name": v["titolo"]}]}})
        scrivi(os.path.join(sito, CART_AGEV, v["id"], "index.html"),
               pagina(modello, seo, {"statica": True}, html_contributo(v, oggi), articolo=True))
        mappa.append((url, contr.get("aggiornato")))
    # i vecchi indirizzi /contributi/ (la pagina si chiamava così fino al 28 ott 2026): portano ai nuovi, anche con i
    # filtri (/contributi/?chi=commercio → /agevolazioni/?chi=commercio). Fuori dalla sitemap, «noindex».
    dest = f"{SITO}/{CART_AGEV}/"
    scrivi(os.path.join(sito, "contributi", "index.html"),
           f'<!doctype html><meta charset="utf-8"><title>{e(TITOLO_CONTR)} – {NOME}</title>'
           f'<link rel="canonical" href="{e(dest)}"><meta name="robots" content="noindex">'
           f'<meta http-equiv="refresh" content="0; url={e(dest)}">'
           f'<script>location.replace({json.dumps(dest)} + location.search + location.hash)</script>'
           f'<p>La pagina ora si chiama <a href="{e(dest)}">Agevolazioni</a>.</p>\n')
    for v in tutti_contr:
        rimando(os.path.join(sito, "contributi", v["id"], "index.html"), f"{SITO}/{CART_AGEV}/{v['id']}/", v["titolo"],
                "Questa pagina ora è in Agevolazioni:")

    # i prezzi dei carburanti (strumenti/carburanti.py, nello stesso giro): la pagina c'è sempre
    try:
        carb = leggi(os.path.join(sito, "carburanti.json"))
    except (OSError, ValueError):
        carb = {}
    url = SITO + "/carburanti/"
    seo = blocco_seo(f"Prezzi benzina e diesel oggi a Benevento e provincia – {NOME}", "I prezzi di benzina, diesel, GPL "
                     "e metano di tutti i distributori di Benevento e provincia, con i più economici: dati del Ministero "
                     "aggiornati ogni mattina.", url, "/condivisione.png",
                     jsonld={"@context": "https://schema.org", "@type": "WebPage", "name": "Prezzi dei carburanti nel Sannio",
                             "url": url, "isPartOf": {"@type": "WebSite", "name": NOME, "url": SITO + "/"}})
    try:
        corpo = html_carburanti(carb, oggi)
    except Exception as ex:   # un file dei prezzi rotto non deve fermare la pubblicazione: la pagina dice «non disponibili»
        print(f"AVVISO: carburanti.json non torna ({type(ex).__name__}: {ex}): pagina senza prezzi", file=sys.stderr)
        carb, corpo = {}, html_carburanti({}, oggi)
    scrivi(os.path.join(sito, "carburanti", "index.html"), pagina(modello, seo, {"statica": True, "carburanti": True}, corpo, articolo=True))
    mappa.append((url, carb.get("estrazione")))

    # le farmacie di turno (strumenti/farmacie.py: le manda il Pi, come i carburanti): la pagina c'è sempre
    try:
        farm = leggi(os.path.join(sito, "farmacie.json"))
    except (OSError, ValueError):
        farm = {}
    adesso_it = adesso.astimezone(fuso())
    url = SITO + "/farmacie-di-turno/"
    seo = blocco_seo(f"Farmacie di turno a Benevento e nei paesi del Sannio oggi – {NOME}", "Le farmacie di turno a "
                     "Benevento e in tutti i paesi della provincia, adesso e stanotte, con telefono, mappa e orari: i turni "
                     "di Federfarma Benevento e dell'Ordine dei Farmacisti, controllati ogni giorno.", url, "/condivisione.png",
                     jsonld={"@context": "https://schema.org", "@type": "WebPage", "name": "Farmacie di turno a Benevento e nel Sannio",
                             "url": url, "isPartOf": {"@type": "WebSite", "name": NOME, "url": SITO + "/"},
                             "breadcrumb": {"@type": "BreadcrumbList", "itemListElement": [
                                 {"@type": "ListItem", "position": 1, "name": NOME, "item": SITO + "/"},
                                 {"@type": "ListItem", "position": 2, "name": "Servizi", "item": SITO + "/servizi/"},
                                 {"@type": "ListItem", "position": 3, "name": "Farmacie di turno"}]}})
    try:
        aree_f, paesi_f = aree_farmacie(farm, adesso_it)
        corpo = html_farmacie(farm, aree_f, paesi_f, adesso_it)
    except Exception as ex:   # un file dei turni rotto non deve fermare la pubblicazione: la pagina dice «non disponibili»
        print(f"AVVISO: farmacie.json non torna ({type(ex).__name__}: {ex}): pagina senza turni", file=sys.stderr)
        farm = {}
        aree_f, paesi_f = aree_farmacie(farm, adesso_it)
        corpo = html_farmacie(farm, aree_f, paesi_f, adesso_it)
    scrivi(os.path.join(sito, "farmacie-di-turno", "index.html"),
           pagina(modello, seo, {"statica": True, "farmacie": True}, corpo, articolo=True))
    with open(os.path.join(sito, "farmacie-fasce.json"), "w", encoding="utf-8") as f_:
        json.dump(farmacie_fasce(aree_f, paesi_f, adesso_it), f_, ensure_ascii=False, separators=(",", ":"))
    mappa.append((url, (farm.get("fonte") or {}).get("modificato") or farm.get("aggiornato")))

    # la pagina Servizi: un riquadro per servizio, con la riga di adesso dove il sito ha il dato
    cur_f, poi_f = adesso_e_poi(aree_f["benevento"]["fasce"], adesso_it)
    r_farm = " · ".join(x for x in (
        ("Adesso: " + ("aperte tutte" if f["tipo"] == "tutte" else (f["farmacia"] or {}).get("nome", "turno non pubblicato"))
         if i == 0 else etichetta_poi(f, adesso_it).split(" alle ")[0][:1].lower() + etichetta_poi(f, adesso_it).split(" alle ")[0][1:]
         + ": " + ("aperte tutte" if f["tipo"] == "tutte" else (f["farmacia"] or {}).get("nome", "turno non pubblicato")))
        if f else "" for i, f in enumerate((cur_f, poi_f))) if x)
    n_strade = len(strade_chiuse(notizie, oggi)[0])
    scuole = {c["comune"] for c in chiusure_per_giorno(chius.get("chiusure") or [], oggi).get(oggi.isoformat(), [])}
    try:
        k = (carb.get("classifiche") or {}).get("benzina", [])[0]
        i = next(x for x in carb["impianti"] if x["id"] == k)
        r_carb = f"Benzina self da {_euro(i['prezzi']['benzina']['self']['prezzo'])} € al litro, a {i['comune']}"
    except (IndexError, KeyError, StopIteration, TypeError):
        r_carb = ""
    sp = speciale_di(oggi)
    righe = [
        ("/farmacie-di-turno/", "Salute", "Farmacie di turno", r_farm,
         "La farmacia di turno adesso e stanotte, a Benevento e in tutti i paesi, con telefono, mappa e orari."),
        ("/strade-chiuse/", "Strade", "Strade chiuse", f"Oggi: {n_strade} " + ("strada chiusa o con lavori" if n_strade == 1
                                                                                else "strade chiuse o con lavori") if n_strade else "Oggi nessuna strada chiusa annunciata",
         "Strade chiuse, sensi unici, lavori e bus deviati a Benevento e in provincia, oggi e nei prossimi giorni."),
        ("/scuole-chiuse/", "Chiusure dei Comuni", "Scuole chiuse", f"Oggi chiuse in {len(scuole)} " + ("Comune" if len(scuole) == 1 else "Comuni")
         if scuole else "Oggi nessuna chiusura annunciata",
         "Le scuole e gli altri luoghi che i Comuni del Sannio chiudono, con l'ordinanza, anche di notte."),
        ("/carburanti/", "Carburanti", "Prezzi di benzina e diesel", r_carb,
         "I prezzi di tutti i distributori di Benevento e provincia, dal meno caro, aggiornati ogni mattina."),
        ("/meteo.html", "Meteo", "Meteo e allerte", "",
         "Le previsioni per Benevento ora per ora, con le allerte della Protezione civile per il Sannio."),
        ("/sezione/avvisi/", "Avvisi", "Avvisi dei Comuni", sp["titolo"] if sp else "",
         "Uffici, acqua, rifiuti, cimiteri e scadenze: gli avvisi dei Comuni in ordine di quando servono."),
        ("/agevolazioni/", "Agevolazioni", "Agevolazioni, bonus e bandi", f"{len(aperti)} aperte adesso" if aperti else "",
         "Contributi, bonus e bandi per famiglie, imprese e associazioni del Sannio, con le scadenze."),
        ("/comuni/", "Comuni", "I Comuni del Sannio", "",
         "Le notizie paese per paese, con gli avvisi e i distributori di ogni Comune."),
    ]
    url = SITO + "/servizi/"
    seo = blocco_seo(f"Servizi a Benevento: farmacie di turno, strade chiuse, carburanti, meteo – {NOME}", "Le cose che "
                     "servono ogni giorno a Benevento e nel Sannio: farmacie di turno, strade e scuole chiuse, prezzi dei "
                     "carburanti, meteo, avvisi dei Comuni e agevolazioni.", url, "/condivisione.png",
                     jsonld={"@context": "https://schema.org", "@type": "CollectionPage", "name": "Servizi utili a Benevento e nel Sannio",
                             "url": url, "isPartOf": {"@type": "WebSite", "name": NOME, "url": SITO + "/"}})
    scrivi(os.path.join(sito, "servizi", "index.html"),
           pagina(modello, seo, {"statica": True}, html_servizi(righe), articolo=True))
    mappa.append((url, None))
    # Benevento Calcio (strumenti/calcio.py, nello stesso giro): la pagina c'è sempre, la diretta la fa calcio.js
    try:
        cal = leggi(os.path.join(sito, "calcio.json"))
    except (OSError, ValueError):
        cal = {}
    url = SITO + "/calcio/"
    seo = blocco_seo(f"Benevento Calcio: risultati, classifica Serie B e partite in diretta – {NOME}",
                     "Il Benevento in Serie B: la partita in diretta con la cronaca minuto per minuto, i risultati degli "
                     "altri campi, la classifica in diretta, il calendario e i risultati.", url, "/condivisione.png",
                     jsonld={"@context": "https://schema.org", "@type": "WebPage", "name": "Benevento Calcio",
                             "url": url, "isPartOf": {"@type": "WebSite", "name": NOME, "url": SITO + "/"}})
    try:
        corpo = html_calcio(cal, dt.datetime.now(dt.timezone.utc).astimezone())
    except Exception as ex:   # un calcio.json rotto non deve fermare la pubblicazione
        print(f"AVVISO: calcio.json non torna ({type(ex).__name__}: {ex}): pagina senza dati", file=sys.stderr)
        cal, corpo = {}, html_calcio({}, dt.datetime.now(dt.timezone.utc).astimezone())
    scrivi(os.path.join(sito, "calcio", "index.html"), pagina(modello, seo, {"statica": True, "calcio": True}, corpo, articolo=True))
    mappa.append((url, cal.get("aggiornato")))

    distributori = {}
    for i in carb.get("impianti") or []:
        distributori[i["comune"]] = distributori.get(i["comune"], 0) + 1

    # le curiosità del Sannio (curiosita.json): sul sito solo quelle già uscite, dalle 12 del loro giorno
    try:
        curiosita = leggi(os.path.join(sito, "curiosita.json")).get("curiosita") or []
    except (OSError, ValueError) as ex:
        print(f"AVVISO: curiosita.json non si legge ({type(ex).__name__}: {ex}): niente curiosità", file=sys.stderr)
        curiosita = []
    cur_uscite = curiosita_uscite(curiosita, adesso)
    os.makedirs(os.path.join(sito, "curiosita"), exist_ok=True)
    url = SITO + "/curiosita/"
    seo = blocco_seo(f"Curiosità del Sannio: leggende, storia e tradizioni di Benevento – {NOME}", "Ogni giorno una "
                     "storia di Benevento e della provincia: leggende come le janare, fatti del passato, detti, "
                     "superstizioni e tradizioni dei paesi del Sannio, con le fonti.", url, "/condivisione.png",
                     jsonld={"@context": "https://schema.org", "@type": "CollectionPage", "name": "Curiosità del Sannio",
                             "url": url, "isPartOf": {"@type": "WebSite", "name": NOME, "url": SITO + "/"}})
    scrivi(os.path.join(sito, "curiosita", "index.html"),
           pagina(modello, seo, {"statica": True}, html_curiosita_elenco(cur_uscite), articolo=True))
    mappa.append((url, cur_uscite[0]["data"] if cur_uscite else None))
    for c in cur_uscite:
        url = f"{SITO}/curiosita/{c['slug']}/"
        im = c.get("immagine") or {}
        if im and not os.path.exists(os.path.join(sito, str(im.get("file", "")).lstrip("/"))):
            im = {}   # la foto dell'IA non ancora fatta (strumenti/foto_ia.py): la pagina esce senza
        jsonld = {"@context": "https://schema.org", "@type": "Article", "headline": breve(c["titolo"], 110),
                  "datePublished": dt.datetime.combine(dt.date.fromisoformat(c["data"]), dt.time(ORA_CURIOSITA),
                                                       fuso()).isoformat(),
                  "image": [SITO + im["file"]] if im else [], "inLanguage": "it-IT", "mainEntityOfPage": url,
                  "author": {"@type": "Organization", "name": NOME, "url": SITO + "/"}, "publisher": ORG,
                  "contentLocation": {"@type": "Place", "name": c["luogo"]},
                  "isBasedOn": [f["url"] for f in c.get("fonti") or [] if re.match(r"^https?://", str(f.get("url") or ""))]}
        dim = (1200, 630)
        if im and con_immagini:
            from PIL import Image
            with Image.open(os.path.join(sito, im["file"].lstrip("/"))) as f_:
                dim = f_.size
        seo = blocco_seo(f"{breve(c['titolo'], 70)} – Curiosità del Sannio", breve(" ".join(_paragrafi_curiosita(c["testo"]))),
                         url, im.get("file") or "/condivisione.png", "article", jsonld, dim=dim)
        altre = [x for x in cur_uscite if x["slug"] != c["slug"]][:5]
        scrivi(os.path.join(sito, "curiosita", c["slug"], "index.html"),
               pagina(modello, seo, {"statica": True}, html_curiosita(c, altre), articolo=True))
        mappa.append((url, c["data"]))
    with open(os.path.join(sito, "curiosita", "ultime.json"), "w", encoding="utf-8") as f:   # il riquadro in prima pagina
        json.dump({"curiosita": [{k: c.get(k) for k in ("slug", "titolo", "categoria", "luogo", "data")}
                                 | {"immagine": (c.get("immagine") or {}).get("file"),
                                    "fuoco_y": (c.get("immagine") or {}).get("fuoco_y", 0.5),
                                    "categoria_nome": CAT_CURIOSITA.get(c["categoria"], "")}
                                 for c in cur_uscite[:3]]}, f, ensure_ascii=False)

    # i Comuni: una pagina per ognuno (Benevento ha zona/benevento) e l'elenco comuni/
    try:
        allerte = leggi(os.path.join(sito, "meteo.json")).get("allerte") or {}
    except (OSError, ValueError):   # meteo.json lo fa meteo.py nello stesso giro: senza, la pagina non ha l'allerta
        allerte = {}
    try:
        stemmi = leggi(os.path.join(sito, "img", "stemmi", "stemmi.json"))
    except (OSError, ValueError):
        stemmi = {}
    per_comune = {c: [] for c in COMUNI_BN}
    for n in notizie:
        for c in comuni_di(n.get("luogo")):
            per_comune[c].append(n)
    ev_comune = {c: [] for c in COMUNI_BN}
    for ev in sorted(eventi, key=lambda x: x["inizio"]):
        if fine_ev(ev) >= oggi.isoformat() and not ev.get("annullato"):
            for c in comuni_di(ev.get("comune"))[:1]:
                ev_comune[c].append(ev)
    indicizzate = 0
    try:
        meteo_c = (leggi(os.path.join(sito, "meteo-comuni.json")) or {}).get("comuni") or {}
    except (OSError, ValueError):
        meteo_c = {}
    from archivia import ZONA_COMUNE
    for c in COMUNI_BN:
        if c == "Benevento":
            continue
        url = SITO + url_comune(c)
        dentro, evc = per_comune[c], ev_comune[c]
        zona_c = ZONA_COMUNE.get(c.lower(), "provincia")
        vicine = [] if len(dentro) >= 6 else [n for n in notizie if n not in dentro and (
            zona_c == "provincia" or n.get("zona") == zona_c)][:8]
        visibile = len(dentro) + len(evc) >= COMUNE_MINIMO
        jsonld = {"@context": "https://schema.org", "@graph": [
            {"@type": "CollectionPage", "name": f"Notizie da {c}", "url": url,
             "about": {"@type": "AdministrativeArea", "name": c,
                       "containedInPlace": {"@type": "AdministrativeArea", "name": "Provincia di Benevento"}},
             "isPartOf": {"@type": "WebSite", "name": NOME, "url": SITO + "/"}},
            {"@type": "BreadcrumbList", "itemListElement": [
                {"@type": "ListItem", "position": 1, "name": NOME, "item": SITO + "/"},
                {"@type": "ListItem", "position": 2, "name": "Comuni del Sannio", "item": SITO + "/comuni/"},
                {"@type": "ListItem", "position": 3, "name": c}]}]}
        seo = blocco_seo(f"Notizie {c} oggi: cronaca, eventi e allerte – {NOME}",
                         breve(f"Le ultime notizie da {c} (BN): cronaca, strade, politica, eventi, scuole chiuse e allerta "
                               "meteo, confrontate tra i giornali locali e i siti ufficiali."), url, "/condivisione.png",
                         jsonld=jsonld, extra="" if visibile else '<meta name="robots" content="noindex, follow">')
        scrivi(os.path.join(sito, url_comune(c).strip("/"), "index.html"),
               pagina(modello, seo, {"statica": True},
                      html_comune(c, dentro, evc, allerte, stemmi.get(c), oggi, distributori.get(c, 0),
                                  html_farmacia_comune(c, aree_f, paesi_f, adesso_it), meteo_c.get(slug(c)),
                                  vicine, NOMI_ZONA.get(zona_c, "Sannio")), articolo=True))
        if visibile:
            indicizzate += 1
            mappa.append((url, dentro[0].get("pubblicato") if dentro else None))
    url = SITO + "/comuni/"
    quante = {c: len(v) for c, v in per_comune.items()}
    seo = blocco_seo(f"I Comuni del Sannio: notizie paese per paese – {NOME}", "Le notizie dei 78 Comuni della provincia "
                     "di Benevento, una pagina per ogni paese: cronaca, eventi, scuole chiuse e allerta meteo.", url,
                     "/condivisione.png", jsonld={"@context": "https://schema.org", "@type": "CollectionPage",
                                                  "name": "I Comuni del Sannio", "url": url,
                                                  "isPartOf": {"@type": "WebSite", "name": NOME, "url": SITO + "/"}})
    scrivi(os.path.join(sito, "comuni", "index.html"), pagina(modello, seo, {"statica": True}, html_comuni(quante), articolo=True))
    mappa.append((url, None))

    mappa.insert(0, (SITO + "/", prima.get("aggiornato")))
    mappa.insert(1, (SITO + "/meteo.html", adesso.isoformat(timespec="minutes")))

    # immagini per Instagram: solo le notizie della prima pagina uscite o aggiornate nelle ultime 48 ore
    # (strumenti/instagram.py; dal 27 ott 2026 anche le aggiornate: Instagram rifà gli «Aggiornamento» di Facebook,
    # che possono essere di notizie di qualche giorno prima)
    if con_immagini:
        usate_ig = set()
        for x in prima.get("notizie", []):
            ore = []
            for v in (x.get("pubblicato"), ((x.get("articolo") or {}).get("aggiornamento") or {}).get("quando")):
                try:
                    t = dt.datetime.fromisoformat(str(v))
                    ore.append(t if t.tzinfo else t.replace(tzinfo=adesso.tzinfo))
                except ValueError:
                    continue
            if ore and adesso - max(ore) <= dt.timedelta(hours=48):
                usate_ig.add(immagine_ig(sito, x))
                usate_ig |= set(immagini_ig_foto(sito, x))
        usate_ig |= riepilogo_ig(sito, prima.get("notizie", []), adesso)
        usate_ig |= immagine_chiusure(sito, chius, adesso)
        oggi_cur = adesso.astimezone(fuso()).date().isoformat()
        for c in curiosita:   # anche quella di oggi prima delle 12: alle 12 i social la trovano già online
            if c["data"] <= oggi_cur:
                try:
                    usate_ig.add(immagine_curiosita(sito, c))
                except Exception as ex:
                    print(f"AVVISO: immagine della curiosità {c.get('slug')} non fatta ({type(ex).__name__}: {ex})",
                          file=sys.stderr)
        for f in glob.glob(os.path.join(sito, "img", "ig", "*.jpg")):
            if os.path.relpath(f, sito).replace(os.sep, "/") not in usate_ig:
                os.remove(f)

    # immagini non più usate; quelle col nome di prima (<id>-<impronta>.png, fino al 21 ott 2026) restano finché c'è
    # la notizia, perché i post di Facebook usciti fino ad allora puntano lì (quelle dei post sono anche nel repository)
    ids = {x["id"] for x in notizie} | {x["id"] for x in appro}
    for f in glob.glob(os.path.join(sito, "img", "n", "*.png")):
        vecchia = re.match(r"(.+)-[0-9a-f]{10}\.png$", os.path.basename(f))
        if os.path.relpath(f, sito).replace(os.sep, "/") not in usate and not (vecchia and vecchia.group(1) in ids):
            os.remove(f)

    # la prima pagina (index.html) col riquadro delle ultime notizie scritto dentro: la riscrive solo la pubblicazione
    # su GitHub (questo programma non si lancia altrove; nel repository il riquadro resta vuoto)
    scrivi(os.path.join(sito, "index.html"), modello_home)

    # sitemap.xml
    righe = ['<?xml version="1.0" encoding="UTF-8"?>', '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">']
    for url, lm in mappa:
        righe.append(f"<url><loc>{e(url)}</loc>" + (f"<lastmod>{e(lm)}</lastmod>" if lm else "") + "</url>")
    righe.append("</urlset>")
    scrivi(os.path.join(sito, "sitemap.xml"), "\n".join(righe) + "\n")

    # sitemap-notizie.xml: Google News vuole solo gli articoli degli ultimi 2 giorni
    limite = adesso - dt.timedelta(days=2)
    righe = ['<?xml version="1.0" encoding="UTF-8"?>',
             '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9" '
             'xmlns:news="http://www.google.com/schemas/sitemap-news/0.9">']
    for n in notizie:
        q = quando_dt(n.get("pubblicato"))
        if q and q >= limite:
            righe.append(f'<url><loc>{SITO}{percorso("notizia", n["id"])}</loc><news:news><news:publication>'
                         f'<news:name>{NOME}</news:name><news:language>it</news:language></news:publication>'
                         f'<news:publication_date>{e(n["pubblicato"])}</news:publication_date>'
                         f'<news:title>{e(titolo_google(n))}</news:title></news:news></url>')
    righe.append("</urlset>")
    scrivi(os.path.join(sito, "sitemap-notizie.xml"), "\n".join(righe) + "\n")

    # feed.xml (RSS 2.0)
    voci = []
    for n in notizie[:50]:
        q = quando_dt(n.get("pubblicato"))
        link = SITO + percorso("notizia", n["id"])
        voci.append(f"<item><title>{e(n['titolo'])}</title><link>{link}</link><guid isPermaLink=\"true\">{link}</guid>"
                    + (f"<pubDate>{email.utils.format_datetime(q)}</pubDate>" if q else "")
                    + f"<category>{e(NOMI_CAT.get(n.get('categoria'), 'Altro'))}</category>"
                    f"<description>{e(n.get('sintesi'))}</description></item>")
    feed = ('<?xml version="1.0" encoding="UTF-8"?>\n<rss version="2.0" xmlns:atom="http://www.w3.org/2005/Atom"><channel>'
            f"<title>{NOME}</title><link>{SITO}/</link><description>{e(DESCR_HOME)}</description><language>it</language>"
            f'<atom:link href="{SITO}/feed.xml" rel="self" type="application/rss+xml"/>'
            f'<atom:link href="{HUB}" rel="hub"/>'
            f"<lastBuildDate>{email.utils.format_datetime(adesso)}</lastBuildDate>" + "".join(voci) + "</channel></rss>\n")
    scrivi(os.path.join(sito, "feed.xml"), feed)

    # IndexNow (Bing e altri): solo le pagine nuove o cambiate rispetto alla sitemap pubblicata prima
    if a.indexnow:
        vecchie = {}
        if a.sitemap_prima and os.path.exists(a.sitemap_prima):
            with open(a.sitemap_prima, encoding="utf-8", errors="ignore") as f:
                for m in re.finditer(r"<loc>([^<]+)</loc>(?:<lastmod>([^<]*)</lastmod>)?", f.read()):
                    vecchie[html.unescape(m.group(1))] = html.unescape(m.group(2) or "")
        cambiate = [u for u, lm in mappa if not u.endswith("/meteo.html") and vecchie.get(u) != (lm or "")]
        with open(a.indexnow, "w", encoding="utf-8") as f:
            json.dump(cambiate[:10000], f)
        print(f"IndexNow: {len(cambiate)} pagine cambiate")
    print(f"OK pagine: {len(notizie)} notizie, {len(appro)} approfondimenti, {len(eventi)} eventi, {len(SEZIONI)} sezioni e zone, "
          f"{len(COMUNI_BN) - 1} Comuni ({indicizzate} per Google), strade chiuse {len(ora)} oggi e {len(poi)} poi; "
          f"{len(usate)} immagini; sitemap {len(mappa)} indirizzi")


if __name__ == "__main__":
    main()
