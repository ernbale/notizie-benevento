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

SITO = "https://notiziebenevento.it"
INDEXNOW_CHIAVE = "dbcf36df6ea73bedfd5f2e121caca034"   # pubblica per costruzione: il file <chiave>.txt sta sul sito
NOME = "Notizie Benevento"
QUI = os.path.dirname(os.path.abspath(__file__))
FONT_BOLD = os.path.join(QUI, "font", "SourceSerif4-Bold.ttf")
FONT_BLACK = os.path.join(QUI, "font", "SourceSerif4-Black.ttf")
MESI = ["gen", "feb", "mar", "apr", "mag", "giu", "lug", "ago", "set", "ott", "nov", "dic"]
MESI_LUNGHI = ["gennaio", "febbraio", "marzo", "aprile", "maggio", "giugno", "luglio", "agosto", "settembre",
               "ottobre", "novembre", "dicembre"]
NOMI_CAT = {"strade": "Strade", "cronaca": "Cronaca", "politica": "Politica", "sport": "Sport", "eventi": "Eventi",
            "meteo": "Allerte", "altro": "Altro"}
NOMI_SPORT = {"calcio": "Calcio", "calcio_a_5": "Calcio a 5", "basket": "Basket", "pallavolo": "Pallavolo", "rugby": "Rugby",
              "scherma": "Scherma", "atletica": "Atletica", "tennis": "Tennis", "ciclismo": "Ciclismo", "nuoto": "Nuoto",
              "altro": "Altri sport"}
# percorso, categoria o zona, <title>, h1, descrizione
SEZIONI = [
    ("sezione/strade", {"cat": "strade"}, "Strade Benevento oggi: chiusure, cantieri e traffico nel Sannio",
     "Strade di Benevento e provincia", "Strade chiuse, cantieri, incidenti e lavori a Benevento e nel Sannio, "
     "con le fonti ufficiali (ANAS, Provincia, Comuni) e i giornali locali messi a confronto."),
    ("sezione/cronaca", {"cat": "cronaca"}, "Cronaca Benevento: ultime notizie di cronaca dal Sannio",
     "Cronaca di Benevento e provincia", "Le notizie di cronaca di oggi da Benevento e dai paesi del Sannio, "
     "confrontate tra i giornali locali, con i link agli articoli originali."),
    ("sezione/politica", {"cat": "politica"}, "Politica Benevento: Comune, Provincia e paesi del Sannio",
     "Politica a Benevento e nel Sannio", "Consiglio comunale, Provincia, Regione e paesi del Sannio: "
     "le notizie di politica di Benevento confrontate tra i giornali locali."),
    ("sezione/sport", {"cat": "sport"}, "Sport Benevento e Sannio: calcio, basket, pallavolo, rugby, scherma",
     "Sport a Benevento e nel Sannio", "Il Benevento e tutte le squadre e gli atleti del Sannio: calcio, calcio a 5, "
     "basket, pallavolo, rugby, scherma, atletica e gli altri sport, con risultati e notizie confrontate tra i giornali locali."),
    ("sezione/eventi", {"cat": "eventi"}, "Eventi a Benevento e provincia: calendario di teatro, concerti, mostre e sagre",
     "Eventi a Benevento e provincia", "Il calendario degli eventi nel Sannio: teatro, concerti, mostre, cinema, sagre e "
     "feste a Benevento e provincia, con date, orari, luoghi e fonti."),
    ("sezione/allerte", {"cat": "meteo"}, "Allerte Benevento: allerta meteo, scuole chiuse e terremoti nel Sannio",
     "Allerte a Benevento e nel Sannio", "Allerte meteo della Protezione civile per le zone del Sannio, chiusure di "
     "scuole e parchi decise dai Comuni, terremoti e danni del maltempo a Benevento e provincia."),
    ("sezione/altro", {"cat": "altro"}, "Altre notizie da Benevento e provincia",
     "Altre notizie dal Sannio", "Lavoro, salute, scuola, ambiente e servizi: le altre notizie di Benevento "
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
    occ, foto = _categoria(n), foto_tema(n)
    impronta = hashlib.sha1(json.dumps([n["titolo"], occ, n.get("luogo"), n.get("sintesi"), foto, 1],
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


def immagine_notizia(sito, n, tipo):
    """Percorso dell'immagine (sul sito) della notizia: si rifà solo se cambiano titolo, sezione, luogo o fonti.
    Il nome resta sempre lo stesso: Facebook si tiene l'indirizzo dell'immagine letto quando esce il post, e se
    cambiasse a ogni fonte nuova il post resterebbe col riquadro vuoto (21 ott 2026)."""
    fonti = (n.get("articolo") or {}).get("fonti") or n.get("fonti") or []
    occ = "Approfondimento" if tipo == "approfondimento" else _categoria(n)
    piede = (f"{len(fonti)} {'fonte' if len(fonti) == 1 else 'fonti confrontate'} · "
             f"{data_it(n.get('pubblicato') or n.get('aggiornato'), lunga=True)}")
    impronta = hashlib.sha1(json.dumps([n["titolo"], occ, n.get("luogo"), piede, 2], ensure_ascii=False)
                            .encode()).hexdigest()[:10]
    rel = f"img/n/{'approfondimento-' if tipo == 'approfondimento' else ''}{n['id']}.png"
    full = os.path.join(sito, rel)
    if _impronta_png(full) != impronta:
        immagine(full, n["titolo"], occ, n.get("luogo"), piede, impronta)
    return "/" + rel


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


def _testata_pagina(occhiello, luogo, titolo):
    lu = f'<span class="luogo">{e(luogo)}</span>' if luogo else ""
    return (f'<a class="indietro" href="/">← Tutte le notizie</a><div class="occhiello">{e(occhiello)}{lu}</div>'
            f"<h1>{e(titolo)}</h1>")


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


def foto_tema(n):
    """La foto illustrativa della notizia (img/temi/<tema>.jpg), se c'è: mai sulla cronaca."""
    t = n.get("immagine")
    if not t or n.get("categoria") == "cronaca" or not re.match(r"^[a-z0-9-]+$", str(t)):
        return None
    # «foto» è la versione scelta da archivia.py per non ripetere la stessa foto in prima pagina
    if re.match(r"^[a-z0-9-]+$", str(n.get("foto") or "")):
        t = n["foto"]
    return f"/img/temi/{t}.jpg"


def _aggiornamento(ag, fonti):
    """L'ultima novità di una notizia che va avanti da giorni, in cima all'articolo con data e ora: come le dirette dei
    giornali, chi torna vede subito cosa è cambiato (l'ora la mette archivia.py)."""
    if not isinstance(ag, dict) or not str(ag.get("testo") or "").strip():
        return ""
    m = re.match(r"\d{4}-(\d{2})-(\d{2})T(\d{2}):(\d{2})", str(ag.get("quando") or ""))
    q = f" · {int(m[2])} {MESI_LUNGHI[int(m[1]) - 1]}, {m[3]}:{m[4]}" if m else ""
    return f'<div class="aggiornamento"><div class="quando">Aggiornamento{e(q)}</div>{_frase("p", ag, fonti)}</div>'


def html_articolo(n, appro_collegato):
    a = n["articolo"]
    fonti = a.get("fonti") if isinstance(a.get("fonti"), list) else []
    h = _testata_pagina(_categoria(n), n.get("luogo"), n["titolo"])
    meta = ("Dall'archivio · " if n["_arch"] else "") + (data_it(n.get("pubblicato")) + " · " if n.get("pubblicato") else "")
    h += f'<div class="meta">{e(meta)}{len(fonti)} {"fonte" if len(fonti) == 1 else "fonti confrontate"}</div>'
    if n.get("stato") == "una_fonte" and n.get("fonti"):
        h += (f'<div class="nota">Per ora questo fatto lo riporta solo {e(n["fonti"][0].get("nome", ""))}. '
              'Lo aggiorniamo se arrivano altre fonti.</div>')
    h += _aggiornamento(a.get("aggiornamento"), fonti)
    h += POSTO_ASCOLTA
    if foto_tema(n):
        b = foto_tema(n)[:-4]
        h += (f'<figure class="foto-tema"><img src="{b}-m.jpg" srcset="{b}-m.jpg 768w, {b}.jpg 1536w" '
              'sizes="(max-width: 800px) 100vw, 760px" width="1536" height="1024" alt="" decoding="async">'
              "<figcaption>Immagine illustrativa creata con l'intelligenza artificiale: non è una foto del fatto.</figcaption></figure>")
    if isinstance(a.get("racconto"), list) and a["racconto"]:
        h += '<div class="racconto">' + _racconto(a["racconto"], fonti) + "</div>"
    elif a.get("cosa"):
        h += f"<h3>Cosa è successo</h3><p>{e(a['cosa'])}</p>"
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
    h = _testata_pagina("Approfondimento", ap.get("luogo"), ap["titolo"])
    if ap.get("sommario"):
        h += f'<p class="sommario">{e(ap["sommario"])}</p>'
    h += (f'<div class="meta">{"Dall&#39;archivio · " if ap["_arch"] else ""}Aggiornato {e(data_it(ap.get("aggiornato")))} · '
          f'{len(fonti)} fonti confrontate</div>') + POSTO_ASCOLTA
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
    h = _testata_pagina(NOME, "", "Chi siamo")
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
          'mandare i loro comunicati a <a href="mailto:comunicati@notiziebenevento.it">comunicati@notiziebenevento.it</a>, '
          "meglio con il testo scritto nella mail. Li leggiamo a ogni aggiornamento del sito: se sono notizie della "
          "provincia e si possono verificare, le pubblichiamo citando chi le firma.</p>")
    h += f"<h3>Contatti</h3><p>Per segnalare un errore o una notizia che manca, scrivici un messaggio sulla {fb}.</p>"
    h += ("<h3>Privacy</h3><p>Le visite si contano in forma anonima, senza cookie. Non serve nessuna registrazione.</p>")
    return f'<article class="appro">{h}</article>'


# ---------- eventi del calendario ----------
NOMI_TIPO = {"teatro": "Teatro", "danza": "Danza", "concerto": "Concerto", "lirica": "Lirica", "mostra": "Mostra",
             "museo": "Museo", "cinema": "Cinema", "sagra": "Sagra", "festa": "Festa", "mercatino": "Mercatino",
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
    h = _testata_pagina(NOMI_TIPO.get(ev.get("tipo"), "Evento"), ev.get("comune"), ev["titolo"]).replace(
        '<a class="indietro" href="/">← Tutte le notizie</a>', '<a class="indietro" href="/sezione/eventi/">← Calendario degli eventi</a>')
    if ev.get("annullato"):
        h += '<p class="ev-annullato">Annullato</p>'
    dove = f'{e(ev.get("luogo"))}, {e(ev.get("comune"))}'
    righe = [("Quando", e(quando_ev(ev)))] + ([("Orari", e(ev["orari"][:1].upper() + ev["orari"][1:]))] if ev.get("orari") else [])
    righe.append(("Dove", dove))
    if ev.get("prezzo"):
        righe.append(("Ingresso", e(ev["prezzo"][:1].upper() + ev["prezzo"][1:])))
    h += '<dl class="scheda-evento">' + "".join(f"<dt>{t}</dt><dd>{v}</dd>" for t, v in righe) + "</dl>"
    h += '<div class="ev-azioni" style="min-height:38px"></div>'
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


def pagina(modello, seo, pagina_js, contenuto="", articolo=False):
    """index.html con un'altra testa e (se c'è) il contenuto già scritto."""
    s = modello
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
    if articolo:
        sostituisci('<nav class="menu" id="menu"', '<nav class="menu" id="menu" style="display:none"')
    return s


def invia_indexnow(path):
    """Avvisa Bing (e gli altri motori di IndexNow) delle pagine nuove o cambiate. Google non usa IndexNow."""
    import urllib.request
    with open(path, encoding="utf-8") as f:
        urls = json.load(f)
    if not urls:
        print("IndexNow: niente di nuovo")
        return
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
    try:
        import PIL  # noqa: F401
        con_immagini = True
    except ImportError:
        con_immagini = False
        print("AVVISO: Pillow non c'è, uso l'immagine del sito per tutte le notizie", file=sys.stderr)
    for d in ("notizia", "approfondimento", "sezione", "zona", "evento"):
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
        fonti = a_.get("fonti") if isinstance(a_.get("fonti"), list) else []
        jsonld = {"@context": "https://schema.org", "@graph": [
            {"@type": "NewsArticle", "@id": url + "#articolo", "headline": breve(titolo_google(n), 110),
             "description": n.get("sintesi"), "datePublished": n.get("pubblicato"), "dateModified": modificato,
             "image": ([SITO + foto_tema(n)] if foto_tema(n) else []) + [SITO + im], "inLanguage": "it-IT", "articleSection": sez, "isAccessibleForFree": True,
             "mainEntityOfPage": url, "author": {"@type": "Organization", "name": NOME, "url": SITO + "/"},
             "publisher": ORG, "contentLocation": {"@type": "Place", "name": n.get("luogo")},
             "isBasedOn": [f["url"] for f in fonti if re.match(r"^https?://", str(f.get("url") or ""))]},
            {"@type": "BreadcrumbList", "itemListElement": [
                {"@type": "ListItem", "position": 1, "name": NOME, "item": SITO + "/"},
                {"@type": "ListItem", "position": 2, "name": sez, "item": SITO + "/" + CAT_PERCORSO.get(n.get("categoria"), "sezione/altro") + "/"},
                {"@type": "ListItem", "position": 3, "name": n["titolo"]}]}]}
        extra = (f'<meta property="article:published_time" content="{e(n.get("pubblicato"))}">\n'
                 f'<meta property="article:section" content="{e(sez)}">')
        seo = blocco_seo(f"{titolo_google(n)} – {NOME}", breve(n.get("sintesi")), url, im, "article", jsonld, extra,
                         og_title=f"{n['titolo']} – {NOME}")
        scrivi(os.path.join(sito, "notizia", n["id"], "index.html"),
               pagina(modello, seo, {"rotta": "#articolo/" + n["id"]}, html_articolo(n, coll), articolo=True))
        mappa.append((url, modificato))

    # notizie unite in un'altra (archivio/rimandi.json): il vecchio indirizzo porta a quella rimasta
    p_rim = os.path.join(sito, "archivio", "rimandi.json")
    for vecchio, nuovo in ((leggi(p_rim).get("notizie") or {}) if os.path.exists(p_rim) else {}).items():
        if nuovo in per_id and vecchio not in per_id:
            dest, tit = SITO + percorso("notizia", nuovo), per_id[nuovo]["titolo"]
            scrivi(os.path.join(sito, "notizia", vecchio, "index.html"),
                   f'<!doctype html><meta charset="utf-8"><title>{e(tit)} – {NOME}</title>'
                   f'<link rel="canonical" href="{e(dest)}"><meta name="robots" content="noindex">'
                   f'<meta http-equiv="refresh" content="0; url={e(dest)}">'
                   f'<script>location.replace({json.dumps(dest)})</script>'
                   f'<p>Questa notizia è stata unita a <a href="{e(dest)}">{e(tit)}</a>.</p>\n')

    for x in appro:
        url = SITO + percorso("approfondimento", x["id"])
        im = img(x, "approfondimento")
        jsonld = {"@context": "https://schema.org", "@type": "NewsArticle", "@id": url + "#articolo",
                  "headline": breve(titolo_google(x), 110), "description": x.get("sommario"),
                  "datePublished": x.get("pubblicato") or x.get("aggiornato"), "dateModified": x.get("aggiornato"),
                  "image": [SITO + im], "inLanguage": "it-IT", "articleSection": "Approfondimento",
                  "mainEntityOfPage": url, "author": {"@type": "Organization", "name": NOME, "url": SITO + "/"},
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
        ft = foto_tema(dict(ev, immagine=ev.get("immagine") or ""))
        luogo = {"@type": "Place", "name": ev.get("luogo"), "address": {"@type": "PostalAddress",
                 "addressLocality": ev.get("comune"), "addressRegion": "BN", "addressCountry": "IT"}}
        jsonld = {"@context": "https://schema.org", "@type": "Event", "name": ev["titolo"], "url": url,
                  "startDate": inizio_dt(ev).isoformat(timespec="minutes") if ev.get("ora") else ev["inizio"],
                  "eventStatus": "https://schema.org/Event" + ("Cancelled" if ev.get("annullato") else "Scheduled"),
                  "eventAttendanceMode": "https://schema.org/OfflineEventAttendanceMode", "location": luogo,
                  "description": ev.get("breve"), "image": [SITO + (ft or "/condivisione.png")]}
        if fine_ev(ev) > ev["inizio"]:
            jsonld["endDate"] = fine_ev(ev)
        if re.search(r"gratuit|gratis|libero", str(ev.get("prezzo") or ""), re.I):
            jsonld["isAccessibleForFree"] = True
        # anteprima su WhatsApp e Facebook: la foto del tema (1536×1024), sennò l'immagine del sito
        seo = blocco_seo(f"{ev['titolo']}, {ev.get('comune')} – {quando_ev(ev)} – {NOME}", breve(ev.get("breve")), url,
                         ft or "/condivisione.png", jsonld=jsonld, dim=(1536, 1024) if ft else (1200, 630))
        cartella = os.path.join(sito, "evento", ev["id"])
        scrivi(os.path.join(cartella, "index.html"),
               pagina(modello, seo, {"rotta": "#evento/" + ev["id"], "evento": ev}, html_evento(ev), articolo=True))
        with open(os.path.join(cartella, "evento.ics"), "w", encoding="utf-8", newline="") as f:
            f.write(ics_evento(ev, url))
        mappa.append((url, None))

    # sezioni e zone: la prima pagina filtrata
    for perc, filtro, title, h1, descr in SEZIONI:
        url = f"{SITO}/{perc}/"
        dentro = [n for n in notizie if all(n.get("categoria" if k == "cat" else "zona") == v for k, v in filtro.items())]
        jsonld = {"@context": "https://schema.org", "@type": "CollectionPage", "name": h1, "url": url,
                  "isPartOf": {"@type": "WebSite", "name": NOME, "url": SITO + "/"}}
        seo = blocco_seo(f"{title} – {NOME}", descr, url, "/condivisione.png", jsonld=jsonld)
        # solo il titolo: le notizie le mette index.html (un elenco qui farebbe saltare la pagina quando arrivano)
        scrivi(os.path.join(sito, perc, "index.html"),
               pagina(modello, seo, dict(filtro, h1=h1), f'<h1 class="titolo-sezione">{e(h1)}</h1>'))
        mappa.append((url, dentro[0].get("pubblicato") if dentro else None))

    # chi siamo: già scritta nella pagina, index.html la lascia com'è (NB_PAGINA.statica)
    url = SITO + "/chi-siamo/"
    seo = blocco_seo(f"Chi siamo – {NOME}", "Come lavora Notizie Benevento: le notizie di Benevento e del Sannio "
                     "confrontate tra i giornali locali e i siti ufficiali, con i link agli articoli originali.", url,
                     "/condivisione.png", jsonld={"@context": "https://schema.org", "@type": "AboutPage",
                                                  "name": "Chi siamo", "url": url, "mainEntity": ORG})
    scrivi(os.path.join(sito, "chi-siamo", "index.html"), pagina(modello, seo, {"statica": True}, html_chi_siamo(), articolo=True))
    mappa.append((url, None))

    mappa.insert(0, (SITO + "/", prima.get("aggiornato")))
    mappa.insert(1, (SITO + "/meteo.html", adesso.isoformat(timespec="minutes")))

    # immagini per Instagram: solo le notizie della prima pagina delle ultime 48 ore (strumenti/instagram.py)
    if con_immagini:
        usate_ig = set()
        for x in prima.get("notizie", []):
            try:
                t = dt.datetime.fromisoformat(str(x.get("pubblicato")))
                t = t if t.tzinfo else t.replace(tzinfo=adesso.tzinfo)
            except ValueError:
                continue
            if adesso - t <= dt.timedelta(hours=48):
                usate_ig.add(immagine_ig(sito, x))
        usate_ig |= riepilogo_ig(sito, prima.get("notizie", []), adesso)
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
    print(f"OK pagine: {len(notizie)} notizie, {len(appro)} approfondimenti, {len(eventi)} eventi, {len(SEZIONI)} sezioni e zone; "
          f"{len(usate)} immagini; sitemap {len(mappa)} indirizzi")


if __name__ == "__main__":
    main()
