#!/usr/bin/env python3
"""Scarica da casa (Raspberry Pi del nodo Ingresso, 192.168.50.6) le fonti di Notizie Benevento che dal cloud dell'agente non si aprono e le mette
nell'archivio privato ernbale/notizie-benevento-fonti, che l'agente trova accanto al suo.

- ANAS: i comunicati della Campania (escono più o meno una volta a settimana) più quelli della Campania nel feed
  nazionale, che ne tiene solo gli ultimi 10 di tutta Italia ma li ha appena escono.
- ASL Benevento: notizie e avvisi. Il sito ha il certificato incompleto (manca il pezzo intermedio di Actalis,
  che Chrome si procura da solo e i programmi no): lo si scarica una volta e si aggiunge.
- TV7 Benevento: il feed senza le notizie nazionali dell'agenzia AdnKronos, con il testo intero degli articoli.
- Albo pretorio del Comune di Benevento (le ordinanze appena pubblicate) e comunicati stampa della Regione Campania:
  dal cloud dell'agente non si aprono (22 ott 2026), da casa sì.
- I 78 Comuni della provincia: gli avvisi e le notizie nuovi sui loro siti, col testo (dal 22 ott 2026). Ogni Comune
  ha il suo sistema (Halley, WordPress, Designers Italia…): si leggono le pagine con l'elenco e si aprono solo i link
  mai visti prima, ricordati in comuni-visti.json (fuori dall'archivio). La prima volta che si legge un Comune si
  prende solo nota di quello che c'è, senza segnalarlo: le notizie vecchie non diventano «nuove».

ANAS e TV7 rifiutano le connessioni dall'estero (il cloud dell'agente, GitHub), da casa si aprono.

Gira ogni 30 minuti dal cron del Pi (fino al 21 ott 2026 era sul K12, che cade con la corrente dello stanzino);
libreria standard di Python, più curl e git. Per ogni fonte tiene le voci degli ultimi
giorni, aggiunge le nuove e scrive l'esito della lettura; se una fonte non risponde lascia le voci vecchie e lo
scrive. Pubblica sempre un commit solo (riscritto ogni volta), così l'archivio resta piccolo.
La chiave per scrivere è una chiave di deploy valida solo per quell'archivio (~/.ssh/nb_fonti sul Pi).

La casella dei comunicati si legge anche da sola ogni 5 minuti (--solo comunicati, dal 24 ott 2026: «dobbiamo
essere rapidi»): l'archivio si pubblica solo se è arrivato qualcosa di nuovo.

Uso sul Pi:   python3 ~/nb-fonti/fonti_casa.py            (scarica e pubblica)
              python3 ~/nb-fonti/fonti_casa.py --prova    (scarica e stampa, senza pubblicare)
              python3 ~/nb-fonti/fonti_casa.py --solo comunicati   (solo la posta; pubblica se c'è un comunicato nuovo)
"""
import argparse
import datetime as dt
import email.utils
import hashlib
import html
import json
import os
import re
import shutil
import ssl
import subprocess
import sys
import tempfile
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor

CARTELLA = os.environ.get("NB_FONTI_CARTELLA") or os.path.expanduser("~/nb-fonti")   # la variabile serve per le prove
ARCHIVIO = os.path.join(CARTELLA, "archivio")
REMOTO = "git@github.com:ernbale/notizie-benevento-fonti.git"
CHIAVE = os.path.expanduser("~/.ssh/nb_fonti")
UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36"
MESI = ["gennaio", "febbraio", "marzo", "aprile", "maggio", "giugno", "luglio", "agosto", "settembre", "ottobre",
        "novembre", "dicembre"]
NUOVE_PER_GIRO = 15   # pagine di comunicati aperte al massimo per giro e per fonte
TESTO_MAX = 8000

ANAS_LISTA = "https://www.stradeanas.it/it/comunicati-stampa?field_press_region_target_id=6"   # 6 = Campania
ASL_LISTA = "https://www.aslbenevento.it/notizie"
ASL_INTERMEDIO = "http://cacert.actalis.it/certs/actalis-authovg3"   # dall'«Authority Information Access» del sito
ANAS_RSS = "https://www.stradeanas.it/it/rss.xml"   # nazionale, solo gli ultimi 10: serve per i comunicati appena usciti
TV7_FEED = "https://www.tvsette.net/feed/?cat=-228"   # 228 = AdnKronos: notizie nazionali d'agenzia, più di metà del feed
ALBO_BN = "https://albo.comune.benevento.it/mc/mc_p_ricerca.php?noHeaderFooter=1&"
REGIONE = "https://www.regione.campania.it/comunicazione/area-stampa/comunicati"


def fuso():
    try:
        from zoneinfo import ZoneInfo
        return ZoneInfo("Europe/Rome")
    except Exception:
        return dt.timezone(dt.timedelta(hours=1))


def scarica(url, ctx=None, codifica="utf-8"):
    # prima curl, con 3 tentativi: TV7 (dietro Cloudflare) a volte resta muto con Python e risponde a curl, e la sera
    # del 21 ott 2026 ci metteva da 1 a 30 secondi a richiesta. L'ASL (ctx col certificato aggiunto) va solo con Python.
    if ctx is None:
        p = subprocess.run(["curl", "-sfL", "--compressed", "-m", "60", "--retry", "2", "--retry-all-errors",
                            "-A", UA, "-H", "Accept-Language: it-IT,it;q=0.9", url], capture_output=True)
        if p.returncode == 0:
            return p.stdout.decode(codifica, "replace")
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Language": "it-IT,it;q=0.9"})
    with urllib.request.urlopen(req, timeout=30, context=ctx) as r:
        return r.read().decode(r.headers.get_content_charset() or "utf-8", "replace")


def contesto_asl():
    """Certificati di sistema più l'intermedio di Actalis che il sito dell'ASL non manda (la catena si verifica
    comunque fino alla radice di sistema: un intermedio falso non passerebbe)."""
    pem = os.path.join(CARTELLA, "actalis-ov-g3.pem")
    if not os.path.exists(pem):
        with urllib.request.urlopen(ASL_INTERMEDIO, timeout=30) as r:
            der = r.read()
        with open(pem, "w") as f:
            f.write(ssl.DER_cert_to_PEM_cert(der))
    ctx = ssl.create_default_context()
    ctx.load_verify_locations(cafile=pem)
    return ctx


def testo(frammento):
    s = re.sub(r"<(script|style|nav|svg|form)[^>]*>.*?</\1>", " ", frammento, flags=re.S | re.I)
    s = re.sub(r"<(br|/p|/h\d|/li|/div|/tr)[^>]*>", "\n", s, flags=re.I)
    s = html.unescape(re.sub(r"<[^>]+>", " ", s))
    righe = [r.strip() for r in re.sub(r"[ \t\xa0]+", " ", s).split("\n")]
    return "\n".join(r for r in righe if r)[:TESTO_MAX]


def assoluto(base, href):
    return urllib.parse.urljoin(base, html.unescape(href))


# ---------------------------------------------------------------- le tre fonti

def tv7(vecchie):
    voci = []
    for pagina in (1, 2):   # 10 per pagina: due pagine sono circa un giorno, e il giro è ogni 30 minuti
        try:
            radice = ET.fromstring(scarica(TV7_FEED if pagina == 1 else f"{TV7_FEED}&paged={pagina}"))
        except Exception:
            if pagina == 1:
                raise
            break
        for it in radice.iter("item"):
            corpo = it.findtext("{http://purl.org/rss/1.0/modules/content/}encoded") or it.findtext("description") or ""
            data = email.utils.parsedate_to_datetime(it.findtext("pubDate")).astimezone(fuso())
            voci.append({"titolo": html.unescape(it.findtext("title") or "").strip(),
                         "link": (it.findtext("link") or "").strip(),
                         "data": data.isoformat(timespec="minutes"),
                         "categorie": [c.text for c in it.findall("category") if c.text],
                         "testo": testo(corpo)})
    return voci


def anas(vecchie):
    pagina = scarica(ANAS_LISTA)
    link = []
    for href, t in re.findall(r'<a[^>]+href="(/it/[^"#?]+)"[^>]*>(.*?)</a>', pagina, re.S):
        t = testo(t)
        if "anas" in t.lower() and len(t) > 30 and href not in link:
            link.append(href)
    try:   # i comunicati della Campania appena usciti, dal feed nazionale
        for it in ET.fromstring(scarica(ANAS_RSS)).iter("item"):
            u = urllib.parse.urlparse((it.findtext("link") or "").strip()).path
            if (it.findtext("title") or "").upper().startswith("CAMPANIA") and u.startswith("/it/") and u not in link:
                link.insert(0, u)
    except Exception:
        pass   # basta la lista della Campania
    voci, aperte = [], 0
    for href in link:
        url = assoluto(ANAS_LISTA, href)
        if url in vecchie:
            voci.append(vecchie[url])
            continue
        if aperte >= NUOVE_PER_GIRO:   # le altre al prossimo giro
            continue
        aperte += 1
        b = scarica(url)
        def campo(classe):
            m = re.search(rf'<div class="press_release__{classe}">(.*?)</div>', b, re.S)
            return testo(m.group(1)) if m else ""
        giorno = campo("publishdate")   # «30 Agosto 2026»: ANAS non dà l'ora
        m = re.match(r"(\d{1,2}) (\w+) (\d{4})", giorno)
        data = (f"{m.group(3)}-{MESI.index(m.group(2).lower()) + 1:02d}-{int(m.group(1)):02d}"
                if m and m.group(2).lower() in MESI else giorno)
        i = b.find('<div class="press_release__body">')
        fine = [k for k in (b.find('class="press_release__', i + 10), b.find("<footer", i)) if k > 0]
        corpo = testo(b[i:min(fine) if fine else len(b)]) if i >= 0 else ""
        titolo = re.search(r"<title>(.*?)</title>", b, re.S)
        voci.append({"titolo": re.sub(r"\s+-\s+Anas$", "", testo(titolo.group(1)) if titolo else ""),
                     "link": url, "data": data, "regione": campo("press-region"),
                     "compartimento": campo("press-district"),
                     "testo": corpo})
    return voci


def asl(vecchie):
    ctx = contesto_asl()
    pagina = scarica(ASL_LISTA, ctx)
    link = []
    for href in re.findall(r'href="(/notizie/[^"#?]+)"', pagina):
        if href not in link:
            link.append(href)
    voci, aperte = [], 0
    for href in link:
        url = assoluto(ASL_LISTA, href)
        if url in vecchie:
            voci.append(vecchie[url])
            continue
        if aperte >= NUOVE_PER_GIRO:
            continue
        aperte += 1
        b = scarica(url, ctx)
        m = re.search(r"<strong>data</strong>\s*(\d{2})/(\d{2})/(\d{4})", b)
        i = b.find("<h1")
        j = b.find("<footer", i)
        corpo = testo(b[i:j if j > 0 else len(b)]) if i >= 0 else ""
        righe = corpo.split("\n")
        voci.append({"titolo": righe[0] if righe else "", "link": url,
                     "data": f"{m.group(3)}-{m.group(2)}-{m.group(1)}" if m else "",
                     "testo": "\n".join(r for r in righe[1:] if r not in ("Condividi su", "Argomenti:"))})
    return voci


COMUNI = [   # (Comune, pagine con l'elenco di avvisi e notizie); None = sito che non si legge senza browser
    ('Airola', None),
    ('Amorosi', ['https://comune.amorosi.bn.it/', 'https://comune.amorosi.bn.it/novita/']),
    ('Apice', ['https://www.comune.apice.bn.it/']),
    ('Apollosa', ['https://www.comune.apollosa.bn.it/', 'https://www.comune.apollosa.bn.it/Novita/Comunicati']),
    ('Arpaia', ['https://www.comune.arpaia.bn.it/', 'https://www.comune.arpaia.bn.it/it/novita']),
    ('Arpaise', ['https://comune.arpaise.bn.it/', 'https://comune.arpaise.bn.it/novita/']),
    ('Baselice', ['https://comune.baselice.bn.it/', 'https://comune.baselice.bn.it/novita/']),
    ('Benevento', ['https://comune.benevento.it/', 'https://comune.benevento.it/novita/']),
    ('Bonea', None),
    ('Bucciano', None),
    ('Buonalbergo', ['https://www.comune.buonalbergo.bn.it/']),
    ('Calvi', ['https://www.comune.calvi.bn.it/']),
    ('Campolattaro', ['https://www.comune.campolattaro.bn.it/']),
    ('Campoli del Monte Taburno', ['https://comune.campolidelmontetaburno.bn.it/', 'https://comune.campolidelmontetaburno.bn.it/novita/']),
    ('Casalduni', ['https://www.comune.casalduni.bn.it/']),
    ('Castelfranco in Miscano', ['https://www.comune.castelfrancoinmiscano.bn.it/']),
    ('Castelpagano', ['https://www.comune.castelpagano.bn.it/']),
    ('Castelpoto', ['https://comune.castelpoto.bn.it/', 'https://comune.castelpoto.bn.it/novita/']),
    ('Castelvenere', ['https://www.comune.castelvenere.bn.it/']),
    ('Castelvetere in Val Fortore', ['https://www.comune.castelvetereinvalfortore.bn.it/']),
    ('Cautano', ['https://comune.cautano.bn.it/', 'https://comune.cautano.bn.it/novita/']),
    ('Ceppaloni', ['https://www.comune.ceppaloni.bn.it/']),
    ('Cerreto Sannita', ['https://www.comune.cerretosannita.bn.it/', 'https://www.comune.cerretosannita.bn.it/it/novita']),
    ('Circello', ['https://comune.circello.bn.it/', 'https://comune.circello.bn.it/novita/']),
    ('Colle Sannita', ['https://www.comune.collesannita.bn.it/c062025/po/elenco_news.php?&area=H']),
    ('Cusano Mutri', ['https://www.comune.cusanomutri.bn.it/', 'https://www.comune.cusanomutri.bn.it/it/novita']),
    ('Dugenta', ['https://comune.dugenta.bn.it/', 'https://comune.dugenta.bn.it/novita/']),
    ('Durazzano', ['https://comune.durazzano.bn.it/', 'https://comune.durazzano.bn.it/novita/']),
    ('Faicchio', ['https://comune.faicchio.bn.it/', 'https://comune.faicchio.bn.it/novita/']),
    ('Foglianise', ['https://comune.foglianise.bn.it/', 'https://comune.foglianise.bn.it/novita/']),
    ('Foiano di Val Fortore', ['https://comune.foianodivalfortore.bn.it/', 'https://comune.foianodivalfortore.bn.it/novita/']),
    ('Forchia', ['https://www.comune.forchia.bn.it/c062032/po/elenco_news.php?&area=H']),
    ("Fragneto l'Abate", ['https://www.comune.fragnetolabate.bn.it/']),
    ('Fragneto Monforte', ['https://www.comune.fragnetomonforte.bn.it/']),
    ('Frasso Telesino', ['https://comune.frassotelesino.bn.it/', 'https://comune.frassotelesino.bn.it/novita/']),
    ('Ginestra degli Schiavoni', ['https://comune.ginestradeglischiavoni.bn.it/', 'https://comune.ginestradeglischiavoni.bn.it/novita/']),
    ('Guardia Sanframondi', ['https://www.comune.guardiasanframondi.bn.it/']),
    ('Limatola', ['https://www.comune.limatola.bn.it/']),
    ('Melizzano', ['https://comune.melizzano.bn.it/', 'https://comune.melizzano.bn.it/novita/']),
    ('Moiano', ['https://www.comune.moiano.bn.it/']),
    ('Molinara', ['https://www.comune.molinara.bn.it/']),
    ('Montefalcone di Val Fortore', None),
    ('Montesarchio', ['https://www.comune.montesarchio.bn.it/', 'https://www.comune.montesarchio.bn.it/it/novita']),
    ('Morcone', ['https://comune.morcone.bn.it/', 'https://comune.morcone.bn.it/novita/']),
    ('Paduli', ['https://www.comune.paduli.bn.it/']),
    ('Pago Veiano', ['https://www.comune.pagoveiano.bn.it/c062046/po/elenco_news.php?&area=H']),
    ('Pannarano', None),
    ('Paolisi', ['https://comune.paolisi.bn.it/', 'https://comune.paolisi.bn.it/novita/']),
    ('Paupisi', ['https://www.comune.paupisi.bn.it/']),
    ('Pesco Sannita', ['https://www.comune.pescosannita.bn.it/']),
    ('Pietraroja', ['https://comune.pietraroja.bn.it/', 'https://comune.pietraroja.bn.it/novita/']),
    ('Pietrelcina', ['https://www.comune.pietrelcina.bn.it/']),
    ('Ponte', ['https://www.comune.ponte.bn.it/']),
    ('Pontelandolfo', ['https://www.comune.pontelandolfo.bn.it/']),
    ('Puglianello', ['https://comune.puglianello.bn.it/', 'https://comune.puglianello.bn.it/novita/']),
    ('Reino', ['https://www.comune.reino.bn.it/']),
    ('San Bartolomeo in Galdo', ['https://www.comune.sanbartolomeoingaldo.bn.it/new/']),
    ('San Giorgio la Molara', ['https://comune.sangiorgiolamolara.bn.it/', 'https://comune.sangiorgiolamolara.bn.it/novita/']),
    ('San Giorgio del Sannio', ['https://www.comune.sangiorgiodelsannio.bn.it/']),
    ('San Leucio del Sannio', ['https://www.comune.sanleuciodelsannio.bn.it/']),
    ('San Lorenzello', ['https://comune.sanlorenzello.bn.it/', 'https://comune.sanlorenzello.bn.it/it/novita']),
    ('San Lorenzo Maggiore', ['https://comune.sanlorenzomaggiore.bn.it/', 'https://comune.sanlorenzomaggiore.bn.it/novita/']),
    ('San Lupo', ['https://www.comune.sanlupo.bn.it/']),
    ('San Marco dei Cavoti', ['https://www.comune.sanmarcodeicavoti.bn.it/', 'https://www.comune.sanmarcodeicavoti.bn.it/novita/']),
    ('San Martino Sannita', ['https://comune.sanmartinosannita.bn.it/']),
    ('San Nazzaro', ['https://www.comune.sannazzaro.bn.it/']),
    ('San Nicola Manfredi', ['https://www.comune.sannicolamanfredi.bn.it/c062067/po/elenco_news.php?&area=H']),
    ('San Salvatore Telesino', ['https://comune.sansalvatoretelesino.bn.it/', 'https://comune.sansalvatoretelesino.bn.it/novita/']),
    ("Sant'Agata de' Goti", ['https://www.comune.santagatadegoti.bn.it/']),
    ("Sant'Angelo a Cupolo", ['https://comune.santangeloacupolo.bn.it/', 'https://comune.santangeloacupolo.bn.it/novita/']),
    ("Sant'Arcangelo Trimonte", ['https://www.comune.santarcangelotrimonte.bn.it/c062078/po/elenco_news.php?&area=H']),
    ('Santa Croce del Sannio', ['https://www.comune.santacrocedelsannio.bn.it/']),
    ('Sassinoro', ['https://www.comune.sassinoro.bn.it/']),
    ('Solopaca', ['https://comune.solopaca.bn.it/', 'https://comune.solopaca.bn.it/novita/']),
    ('Telese Terme', ['https://www.comune.teleseterme.bn.it/', 'https://www.comune.teleseterme.bn.it/it/novita']),
    ('Tocco Caudio', ['https://comune.toccocaudio.bn.it/', 'https://comune.toccocaudio.bn.it/novita/']),
    ('Torrecuso', ['https://www.comune.torrecuso.bn.it/', 'https://www.comune.torrecuso.bn.it/Novita/']),
    ('Vitulano', ['https://comune.vitulano.bn.it/', 'https://comune.vitulano.bn.it/novita/']),
]

def albo_bn(vecchie):
    """L'albo pretorio del Comune di Benevento: le ordinanze (traffico, divieti, scuole…) delle prime pagine.
    La pagina è in latin-1; ogni pubblicazione ha i suoi campi in una cella «visible-xs» («Tipo», «Oggetto»…)."""
    voci = []
    for pag in (1, 2, 3):
        pagina = scarica(ALBO_BN + (f"&pag={pag}" if pag > 1 else ""), codifica="latin-1")
        for id_, blocco in re.findall(r'<td data-id="(\d+)" class="visible-xs">(.*?)</td>', pagina, re.S):
            campi = {testo(k).lower(): testo(v).replace("\n", " ")
                     for k, v in re.findall(r"<strong>(.*?)</strong>\s*<div[^>]*>(.*?)</div>", blocco, re.S)}
            if "ordinanz" not in campi.get("tipo", "").lower():
                continue   # determine, decreti, nomine, notifiche: non sono notizie
            g = re.match(r"(\d{2})/(\d{2})/(\d{4})", campi.get("data inizio", ""))
            voci.append({"titolo": campi.get("oggetto", "")[:300],
                         "link": f"https://albo.comune.benevento.it/mc/mc_p_dettaglio.php?id_pubbl={id_}",
                         "data": f"{g[3]}-{g[2]}-{g[1]}" if g else "", "mittente": campi.get("mittente", ""),
                         "tipo": campi.get("tipo", ""), "numero_atto": campi.get("numero atto", ""),
                         "data_atto": campi.get("data atto", ""), "testo": campi.get("oggetto", "")})
    return voci


def regione(vecchie):
    """I comunicati stampa della Regione Campania, col testo (l'agente tiene solo quelli che riguardano il Sannio)."""
    pagina = scarica(REGIONE)
    voci, aperte = [], 0
    for href, titolo in re.findall(r'<a href="(https://www\.regione\.campania\.it/comunicazione/area-stampa/comunicati/'
                                   r'[^"#?]+)"\s+title="Vai a ([^"]+)"', pagina):
        if href in vecchie:
            voci.append(vecchie[href])
            continue
        if aperte >= NUOVE_PER_GIRO:
            continue
        aperte += 1
        b = scarica(href)
        i = b.find("<h1")
        j = b.find("<footer", i if i >= 0 else 0)
        g = re.match(r"(\d{2})/(\d{2})/(\d{4})", html.unescape(titolo))
        righe = testo(b[i if i >= 0 else 0:j if j > 0 else len(b)]).split("\n")
        inizio = next((k for k, r in enumerate(righe) if re.match(r"\d{2}/\d{2}/\d{4} - Comunicato", r)), 0)
        voci.append({"titolo": html.unescape(titolo), "link": href,
                     "data": f"{g[3]}-{g[2]}-{g[1]}" if g else "",
                     "testo": "\n".join(righe[inizio + 1:])[:5000]})   # dopo il titolo: niente menu del sito
    return voci


# un link è un avviso o una notizia se ha la forma di quelli dei sistemi usati dai Comuni del Sannio
VOCE_COMUNE = re.compile(r"/(novita|notizi[ae]|news|avvis[oi]|comunicat[oi](?:[-_]stampa)?|ordinanz[ae])(/|_)|novita_\d+\.html"
                         r"|mostra_news\.php\?id=\d+|[?&]art=\d+|/new/\d{3,}-[^/]+\.html$", re.I)
NON_VOCE = re.compile(r"/(categor|argoment|tag)|/page/\d+/?$|feed|\?(page|paged)=|/(novita|notizie|avvisi|comunicati|news)/?$"
                      r"|elenco_news", re.I)
GENERICI = {"leggi di più", "leggi tutto", "ulteriori dettagli", "dettagli", "vai alla pagina", "leggi", "approfondisci",
            "continua a leggere", "scopri di più"}
NUOVE_COMUNI_PER_GIRO = 40
DATA_IT = re.compile(r"\b(\d{1,2})[/.-](\d{1,2})[/.-](20\d\d)\b|\b(\d{1,2})\s+(" + "|".join(MESI) + r")\s+(20\d\d)\b", re.I)


def voci_elenco(pagina, base):
    """I link agli avvisi in una pagina di elenco del Comune: {indirizzo: testo del link}."""
    host = urllib.parse.urlparse(base).netloc.removeprefix("www.")
    out = {}
    for href, t in re.findall(r'<a[^>]+href="([^"#]+)"[^>]*>(.*?)</a>', pagina, re.S):
        u = assoluto(base, href)
        if urllib.parse.urlparse(u).netloc.removeprefix("www.") != host or not VOCE_COMUNE.search(u) or NON_VOCE.search(u):
            continue
        t = testo(t).replace("\n", " ")
        if t.lower() in GENERICI or len(t) < 12:
            t = ""
        if u not in out or len(t) > len(out[u]):
            out[u] = t
    return out


def dettaglio_comune(nome, url, titolo_link, adesso):
    """Apre l'avviso: titolo, data scritta nella pagina (se c'è) e testo."""
    b = scarica(url)
    i = b.find("<h1")
    j = b.find("<footer", i if i >= 0 else 0)
    corpo = testo(b[i if i >= 0 else 0:j if j > 0 else len(b)])
    righe = corpo.split("\n")
    titolo = (righe[0] if i >= 0 and righe else "") or titolo_link
    if not titolo:
        m = re.search(r"<title>(.*?)</title>", b, re.S)
        titolo = testo(m.group(1)) if m else url
    m = DATA_IT.search(corpo)
    data_avviso = ""
    if m:
        try:
            g, me, a = (m.group(1), m.group(2), m.group(3)) if m.group(1) else (m.group(4), MESI.index(m.group(5).lower()) + 1, m.group(6))
            data_avviso = dt.date(int(a), int(me), int(g)).isoformat()
        except ValueError:
            pass
    return {"comune": nome, "titolo": titolo[:300], "link": url, "data": adesso.date().isoformat(),
            "primo_visto": adesso.isoformat(timespec="minutes"), "data_avviso": data_avviso,
            "testo": "\n".join(righe[1:] if i >= 0 else righe)[:3000]}


def comuni(vecchie):
    adesso = dt.datetime.now(fuso())
    p_visti = os.path.join(CARTELLA, "comuni-visti.json")
    try:
        with open(p_visti, encoding="utf-8") as f:
            visti = json.load(f)
    except (OSError, ValueError):
        visti = {}

    def elenco(c):
        trovate, errore = {}, ""
        for p in c[1]:
            try:
                trovate.update(voci_elenco(scarica(p), p))
            except Exception as e:
                errore = type(e).__name__
        return c[0], trovate, errore

    with ThreadPoolExecutor(8) as ex:
        elenchi = list(ex.map(elenco, [c for c in COMUNI if c[1]]))
    non_letti = [f"{n} (il sito si legge solo col browser o non funziona)" for n, p in COMUNI if not p]
    da_aprire = []
    for nome, trovate, errore in elenchi:
        if not trovate:
            non_letti.append(f"{nome} ({errore or 'nessun avviso trovato'})")
        elif nome not in visti:   # prima lettura: si prende nota di tutto, non si segnala niente
            visti[nome] = list(trovate)
        else:
            gia = set(visti[nome])
            da_aprire += [(nome, u, t) for u, t in trovate.items() if u not in gia and u not in vecchie]

    def apri(x):
        try:
            return dettaglio_comune(*x, adesso)
        except Exception:
            return None   # si riprova al prossimo giro

    voci = []
    with ThreadPoolExecutor(6) as ex:
        for (nome, u, _), v in zip(da_aprire, ex.map(apri, da_aprire[:NUOVE_COMUNI_PER_GIRO])):
            if v is None:
                continue
            visti[nome].append(u)
            vecchio = v["data_avviso"] and v["data_avviso"] < (adesso.date() - dt.timedelta(days=10)).isoformat()
            if not vecchio:   # un avviso di settimane fa ricomparso in pagina non è una notizia
                voci.append(v)

    # gli albi pretori: ricordati a parte («albo:<Comune>»), perché l'elenco wp ha tutte le pubblicazioni in corso
    def albo(x):
        nome, (tipo, url) = x
        try:
            return nome, tipo, atti_albo(tipo, url, adesso)
        except Exception:
            return nome, tipo, None
    with ThreadPoolExecutor(8) as ex:
        albi = list(ex.map(albo, ALBI.items()))
    albi_non_letti = sorted(n for n, _, atti in albi if atti is None)
    atti_nuovi = []
    for nome, tipo, atti in albi:
        if atti is None:
            continue
        chiave = "albo:" + nome
        if chiave not in visti:   # prima lettura: solo nota
            visti[chiave] = [a["link"] for a in atti]
            continue
        gia = set(visti[chiave])
        atti_nuovi += [(nome, tipo, a) for a in atti if a["link"] not in gia and a["link"] not in vecchie]

    def apri_atto(x):
        nome, tipo, a = x
        try:
            allegato = testo_allegato(tipo, a)
        except Exception:
            allegato = ""   # l'atto esce lo stesso, con l'oggetto
        oggetto = re.sub(r"^POSTA CERTIFICATA:\s*", "", a["oggetto"]).strip()
        return {"comune": nome, "titolo": oggetto[:300], "link": a["link"], "data": adesso.date().isoformat(),
                "primo_visto": adesso.isoformat(timespec="minutes"), "data_avviso": a["data"], "fonte": "albo pretorio",
                "testo": (f"Albo pretorio del Comune di {nome}: {a['tipo']}" + (f" n. {a['numero']}" if a["numero"] else "")
                          + f", pubblicato il {a['data']}.\nOggetto: {oggetto}"
                          + (f"\n\nDal PDF allegato:\n{allegato}" if allegato else ""))[:6000]}
    with ThreadPoolExecutor(6) as ex:
        for (nome, _, a), v in zip(atti_nuovi, ex.map(apri_atto, atti_nuovi[:NUOVI_ATTI_PER_GIRO])):
            visti["albo:" + nome].append(a["link"])
            voci.append(v)
    if not PROVA:
        with open(p_visti + ".tmp", "w", encoding="utf-8") as f:
            json.dump({k: v[-(1000 if k.startswith("albo:") else 300):] for k, v in visti.items()}, f, ensure_ascii=False)
        os.replace(p_visti + ".tmp", p_visti)
    return voci, {"comuni_letti": f"{len(COMUNI) - len(non_letti)} su {len(COMUNI)}", "comuni_non_letti": non_letti,
                  "albi_letti": f"{len(ALBI) - len(albi_non_letti)} su {len(ALBI)}", "albi_non_letti": albi_non_letti}


# Gli albi pretori dei Comuni (dal 23 ott 2026, «il giro agente si deve impegnare molto di più» sui Comuni): le
# ordinanze, gli avvisi e i bandi che non escono tra le notizie dei loro siti. Due sistemi coprono 57 Comuni (Benevento
# ha il suo, albo_bn): «halley» = mc_p_ricerca.php, come l'albo di Benevento; «wp» = tema design-comuni-italia, che dà
# l'elenco in JSON (?proxy_albo=1) e il dettaglio con gli allegati (?proxy_dettaglio_id=). Indirizzi trovati il 23 ott
# dalla homepage o dal codice ISTAT (halleyweb.com/c062NNN), controllando che la pagina fosse di quel Comune.
ALBI = {
    'Amorosi': ('wp', 'https://comune.amorosi.bn.it/albo-pretorio/'),
    'Apice': ('halley', 'https://www.halleyweb.com/c062003/mc/mc_p_ricerca.php'),
    'Arpaia': ('halley', 'https://halleyweb.com/c062005/mc/mc_p_ricerca.php'),
    'Arpaise': ('wp', 'https://comune.arpaise.bn.it/albo-pretorio/'),
    'Buonalbergo': ('halley', 'https://www.halleyweb.com/c062011/mc/mc_p_ricerca.php'),
    'Calvi': ('halley', 'https://calvi.halleyweb.it/mc/mc_p_ricerca.php'),
    'Campolattaro': ('halley', 'https://www.halleyweb.com/c062013/mc/mc_p_ricerca.php'),
    'Campoli del Monte Taburno': ('wp', 'https://comune.campolidelmontetaburno.bn.it/albo-pretorio/'),
    'Castelfranco in Miscano': ('halley', 'https://www.halleyweb.com/c062016/mc/mc_p_ricerca.php'),
    'Castelpagano': ('halley', 'https://castelpagano.halleyweb.it/mc/mc_p_ricerca.php'),
    'Castelpoto': ('wp', 'https://comune.castelpoto.bn.it/albo-pretorio/'),
    'Castelvetere in Val Fortore': ('halley', 'https://castelvetereinvalfortore.halleyweb.it/c062020/mc/mc_p_ricerca.php'),
    'Cautano': ('wp', 'https://comune.cautano.bn.it/albo-pretorio/'),
    'Ceppaloni': ('halley', 'https://ceppaloni.halleyweb.it/mc/mc_p_ricerca.php'),
    'Circello': ('wp', 'https://comune.circello.bn.it/albo-pretorio/'),
    'Colle Sannita': ('halley', 'https://www.halleyweb.com/c062025/mc/mc_p_ricerca.php'),
    'Dugenta': ('wp', 'https://comune.dugenta.bn.it/albo-pretorio/'),
    'Durazzano': ('wp', 'https://comune.durazzano.bn.it/albo-pretorio/'),
    'Faicchio': ('wp', 'https://comune.faicchio.bn.it/albo-pretorio/'),
    'Foglianise': ('wp', 'https://comune.foglianise.bn.it/albo-pretorio/'),
    'Forchia': ('halley', 'https://www.halleyweb.com/c062032/mc/mc_p_ricerca.php'),
    "Fragneto l'Abate": ('halley', 'https://www.halleyweb.com/c062033/mc/mc_p_ricerca.php'),
    'Fragneto Monforte': ('halley', 'https://www.halleyweb.com/c062034/mc/mc_p_ricerca.php'),
    'Frasso Telesino': ('wp', 'https://comune.frassotelesino.bn.it/albo-pretorio/'),
    'Limatola': ('halley', 'https://limatola.halleyweb.it/mc/mc_p_ricerca.php'),
    'Melizzano': ('wp', 'https://comune.melizzano.bn.it/albo-pretorio/'),
    'Molinara': ('halley', 'https://molinara.halleyweb.it/c062041/mc/mc_p_ricerca.php'),
    'Morcone': ('wp', 'https://comune.morcone.bn.it/albo-pretorio/'),
    'Paduli': ('halley', 'https://www.halleyweb.com/c062045/mc/mc_p_ricerca.php'),
    'Pago Veiano': ('halley', 'https://www.halleyweb.com/c062046/mc/mc_p_ricerca.php'),
    'Pannarano': ('halley', 'https://www.halleyweb.com/c062047/mc/mc_p_ricerca.php'),
    'Paolisi': ('halley', 'https://www.halleyweb.com/c062048/mc/mc_p_ricerca.php'),
    'Paupisi': ('halley', 'https://paupisi.halleyweb.it/c062049/mc/mc_p_ricerca.php'),
    'Pesco Sannita': ('halley', 'https://www.halleyweb.com/c062050/mc/mc_p_ricerca.php'),
    'Pietraroja': ('wp', 'https://comune.pietraroja.bn.it/albo-pretorio/'),
    'Pietrelcina': ('halley', 'https://www.halleyweb.com/c062052/mc/mc_p_ricerca.php'),
    'Ponte': ('halley', 'https://ponte.halleyweb.it/c062053/mc/mc_p_ricerca.php'),
    'Pontelandolfo': ('halley', 'https://www.halleyweb.com/c062054/mc/mc_p_ricerca.php'),
    'Puglianello': ('wp', 'https://comune.puglianello.bn.it/albo-pretorio/'),
    'Reino': ('halley', 'https://www.halleyweb.com/c062056/mc/mc_p_ricerca.php'),
    'San Giorgio la Molara': ('wp', 'https://comune.sangiorgiolamolara.bn.it/albo-pretorio/'),
    'San Giorgio del Sannio': ('halley', 'https://www.halleyweb.com/c062058/mc/mc_p_ricerca.php'),
    'San Leucio del Sannio': ('halley', 'https://www.halleyweb.com/c062060/mc/mc_p_ricerca.php'),
    'San Lorenzo Maggiore': ('wp', 'https://comune.sanlorenzomaggiore.bn.it/albo-pretorio/'),
    'San Lupo': ('halley', 'https://www.halleyweb.com/c062063/mc/mc_p_ricerca.php'),
    'San Martino Sannita': ('halley', 'https://www.halleyweb.com/c062065/mc/mc_p_ricerca.php'),
    'San Nazzaro': ('halley', 'https://www.halleyweb.com/c062066/mc/mc_p_ricerca.php'),
    'San Nicola Manfredi': ('halley', 'https://www.halleyweb.com/c062067/mc/mc_p_ricerca.php'),
    "Sant'Agata de' Goti": ('halley', 'https://santagatadegoti.halleyweb.it/mc/mc_p_ricerca.php'),
    "Sant'Angelo a Cupolo": ('wp', 'https://comune.santangeloacupolo.bn.it/albo-pretorio/'),
    "Sant'Arcangelo Trimonte": ('halley', 'https://www.halleyweb.com/c062078/mc/mc_p_ricerca.php'),
    'Santa Croce del Sannio': ('halley', 'https://www.halleyweb.com/c062069/mc/mc_p_ricerca.php'),
    'Sassinoro': ('halley', 'https://sassinoro.halleyweb.it/mc/mc_p_ricerca.php'),
    'Solopaca': ('halley', 'https://www.halleyweb.com/c062073/mc/mc_p_ricerca.php'),
    'Tocco Caudio': ('wp', 'https://comune.toccocaudio.bn.it/albo-pretorio/'),
    'Torrecuso': ('halley', 'https://torrecuso.halleyweb.it/c062076/mc/mc_p_ricerca.php'),
    'Vitulano': ('wp', 'https://comune.vitulano.bn.it/albo-pretorio/'),
}
ATTO_SI = re.compile(r"ordinanz|avvis|bando di concorso|bandi e avvisi|rende noto|manifest|concors", re.I)
ATTO_NO = re.compile(r"deposit|esproprio|accertament|creditor|espletamento|gar[ae]\b|elettoral|riunione|consiglio comunale"
                     r"|liquidazion|altri enti|altre pa|paesaggistic|reperibilit|pronta disponibilit|turni", re.I)
OGGETTO_NO = re.compile(r"liquidazion|pubblicazion[ei] di matrimonio|deposito|notifica|esproprio|abusiv|pronta disponibilit"
                        r"|reperibilit|turni (di )?p\.? ?d|catasto|autorizzazione paesaggistica|permesso di costruire"
                        r"|errata corrige", re.I)
GIORNI_ALBO = 3            # gli atti pubblicati da tanti giorni (quelli più vecchi non sono notizie nuove)
NUOVI_ATTI_PER_GIRO = 30   # dettagli e PDF aperti al massimo per giro


def atti_albo(tipo, url, adesso):
    """Gli atti dell'albo di un Comune che possono interessare la gente (ordinanze, avvisi, bandi), pubblicati negli
    ultimi GIORNI_ALBO giorni: [{tipo, oggetto, data, numero, link, dettaglio}]."""
    limite = (adesso.date() - dt.timedelta(days=GIORNI_ALBO)).isoformat()
    out = []
    if tipo == "wp":
        for x in json.loads(scarica(url + "?proxy_albo=1")):
            out.append({"tipo": str(x.get("tipo") or ""), "oggetto": str(x.get("oggetto") or ""),
                        "data": str(x.get("dataPubblicazione") or "")[:10], "numero": str(x.get("numero") or ""),
                        "link": f"{url}?dettaglio_id={x.get('id')}", "dettaglio": f"{url}?proxy_dettaglio_id={x.get('id')}"})
    else:
        cartella = url.rsplit("/", 1)[0] + "/"
        for pag in (1, 2):
            pagina = scarica(url + "?noHeaderFooter=1" + (f"&pag={pag}" if pag > 1 else ""), codifica="latin-1")
            for id_, blocco in re.findall(r'<td data-id="(\d+)" class="visible-xs">(.*?)</td>', pagina, re.S):
                campi = {testo(k).lower(): testo(v).replace("\n", " ")
                         for k, v in re.findall(r"<strong>(.*?)</strong>\s*<div[^>]*>(.*?)</div>", blocco, re.S)}
                g = re.match(r"(\d{2})/(\d{2})/(\d{4})", campi.get("data inizio", ""))
                out.append({"tipo": campi.get("tipo", ""), "oggetto": campi.get("oggetto", ""),
                            "data": f"{g[3]}-{g[2]}-{g[1]}" if g else "", "numero": campi.get("numero atto", ""),
                            "link": f"{cartella}mc_p_dettaglio.php?id_pubbl={id_}",
                            "dettaglio": f"{cartella}mc_p_dettaglio.php?id_pubbl={id_}"})
    return [a for a in out if a["data"] >= limite and ATTO_SI.search(a["tipo"]) and not ATTO_NO.search(a["tipo"])
            and not OGGETTO_NO.search(a["oggetto"])]


def testo_allegato(tipo, a):
    """Il testo del primo PDF allegato all'atto (le prime 3 pagine), se c'è e si legge: «» altrimenti."""
    if tipo == "wp":
        allegati = [x.get("url") for x in json.loads(scarica(a["dettaglio"])).get("allegati") or []]
    else:
        pagina = scarica(a["dettaglio"], codifica="latin-1")
        allegati = [assoluto(a["dettaglio"], h) for h in dict.fromkeys(re.findall(r"mc_attachment\.php\?mc=\d+", pagina))]
    for u in [x for x in allegati if x][:2]:
        with tempfile.NamedTemporaryFile(suffix=".pdf") as f:
            if subprocess.run(["curl", "-sfL", "-m", "60", "-A", UA, "-o", f.name, u], capture_output=True).returncode:
                continue
            with open(f.name, "rb") as fh:
                if fh.read(5) != b"%PDF-":   # i .p7m firmati e gli altri formati non si leggono qui
                    continue
            r = subprocess.run(["pdftotext", "-l", "3", "-layout", f.name, "-"], capture_output=True, timeout=60)
            t = re.sub(r"[ \t]+", " ", r.stdout.decode("utf-8", "replace")).strip()
            if t:
                return t
    return ""


POSTA_CONF = os.path.join(CARTELLA, "posta.conf")   # indirizzo e password della casella, li scrive --imposta-posta
POSTA_SERVER = "imaps.aruba.it"
# Nella casella arrivano anche cose che non sono comunicati: rimbalzi, risposte automatiche, avvisi di Aruba e le
# risposte alla nostra mail agli uffici stampa del 24 ott 2026. Non vanno all'agente: il 24 ott alle 12:06 il giro ha
# visto 13 rimbalzi e un comunicato vero (CISL FP) e ha scritto «0 utili, solo risposte automatiche».
NON_COMUNICATO_DA = re.compile(r"mailer-daemon|mail-daemon|postmaster|mail delivery|no-?reply.*aruba", re.I)
NON_COMUNICATO_OGGETTO = re.compile(
    r"^\s*(undeliver|undelivered|recapito fallito|mancato recapito|delivery status|returned mail|mail delivery|"
    r"auto(matic)?\s*(reply|risposta)?\s*:|risposta automatica|out of office|fuori sede|assente)", re.I)
NON_COMUNICATO_DOMINI = ("staff.aruba.it", ".ad.aruba.it")
# Le risposte alla nostra mail («grazie, vi abbiamo aggiunti») non sono comunicati, ma un ufficio stampa può anche
# rispondere mandando un comunicato: allora vanno all'agente come gli altri (voluto il 24 ott 2026, dopo la risposta
# della Soprintendenza delle 15:55). Conta un documento o un'immagine grande allegati, o testo scritto da loro.
# l'oggetto delle nostre mail: agli uffici stampa (24 ott 2026) e alle Pro Loco (25 ott 2026)
RISPOSTA_NOSTRA = re.compile(r"comunicati stampa per notizie benevento|eventi delle pro loco su notizie benevento", re.I)
NOSTRA_MAIL = "vi scriviamo da notizie benevento"   # dove comincia la nostra mail citata nella risposta
RIGA_CITAZIONE = re.compile(r"^\s*(>|_{5,}|-{5,}|(da|from|inviato|sent|a|to|cc|oggetto|subject|data|date)\s*:)"
                            r"|(ha scritto|wrote)\s*:\s*$", re.I)
# Le righe della firma (social, sito, indirizzi): nella risposta della Soprintendenza del 24 ott valevano 131 caratteri
RIGA_FIRMA = re.compile(r"https?:|www\.|@|^\s*(fb|ig|facebook|instagram|threads|spreaker|twitter|x|linkedin|youtube|"
                        r"tel|telefono|cell|fax|pec|e-?mail|sito|web)\b\s*:", re.I)
AVVISO_LEGALE = re.compile(r"d\.\s?lgs\.?\s*(n\.?\s*)?196|196/2003|gdpr|2016/679|informazioni contenute nella|"
                           r"informazioni contenute in questa|questo messaggio e|this e-?mail|confidential|"
                           r"stampare questa|prima di stampare", re.I)
ALLEGATO_DOCUMENTO = re.compile(r"\.(pdf|docx?|odt|rtf|txt|pptx?|xlsx?)$", re.I)
IMMAGINE_GRANDE = 150_000   # byte: una locandina sì, il logo della firma no
PROSA_MIN = 200   # caratteri di frasi vere scritte da loro: più di un «grazie, vi abbiamo aggiunti» (nel dubbio passa)


def id_posta(link):
    """L'id breve di un comunicato: lo stesso sul Pi, nel giro lampo (comunicati_visti.json) e nelle notizie."""
    return hashlib.sha1(link.encode("utf-8")).hexdigest()[:12]


def non_comunicato(titolo, mittente, dominio, m=None):
    """Il motivo per cui una mail non è un comunicato (rimbalzo, risposta automatica, avviso del provider, risposta
    alla nostra mail senza un comunicato dentro), o ''. Senza la mail (m) le risposte alla nostra mail restano."""
    if NON_COMUNICATO_DA.search(mittente or "") or (dominio or "").endswith(NON_COMUNICATO_DOMINI):
        return "rimbalzo o avviso del provider"
    if NON_COMUNICATO_OGGETTO.search(titolo or ""):
        return "risposta automatica"
    if m is not None:
        if (m.get("Auto-Submitted") or "no").strip().lower() != "no" or m.get("X-Autoreply") or m.get("X-Autorespond"):
            return "risposta automatica"
        if m.get_content_type() == "multipart/report":
            return "rimbalzo"
        if RISPOSTA_NOSTRA.search(titolo or "") and not contenuto_risposta(m):
            return "risposta alla nostra mail, senza comunicato"
    return ""


def contenuto_risposta(m):
    """Cosa porta una risposta alla nostra mail oltre al ringraziamento ('' se niente): un documento o un'immagine
    grande allegati, o testo scritto da loro (prima della nostra mail citata; contano solo le righe lunghe, non quelle
    della firma, le intestazioni della citazione e gli avvisi legali fino alla riga vuota) di almeno PROSA_MIN caratteri."""
    for parte in m.walk():
        nome = parte.get_filename() or ""
        if ALLEGATO_DOCUMENTO.search(nome):
            return f"allegato {nome}"
        if parte.get_content_maintype() == "image" and len(parte.get_payload(decode=True) or b"") > IMMAGINE_GRANDE:
            return f"immagine allegata {nome}".strip()
    corpo = _testo_mail(m)[0]
    i = corpo.lower().find(NOSTRA_MAIL)
    loro = corpo[:i] if i >= 0 else corpo
    prosa, avviso = 0, False
    for r in loro.splitlines():
        r = r.strip()
        avviso = bool(r) and (avviso or bool(AVVISO_LEGALE.search(r)))
        if not avviso and len(r) >= 60 and not RIGA_CITAZIONE.search(r) and not RIGA_FIRMA.search(r):
            prosa += len(r)
    return f"{prosa} caratteri scritti da loro" if prosa >= PROSA_MIN else ""


def _testo_mail(m):
    """Il testo di una mail (la parte di testo semplice, se no l'HTML ripulito) e quello degli allegati PDF."""
    corpo, allegati, pdf = "", [], []
    for parte in m.walk():
        tipo, nome = parte.get_content_type(), parte.get_filename()
        if nome:
            allegati.append(nome)
            if tipo == "application/pdf" or nome.lower().endswith(".pdf"):
                try:   # pdftotext (poppler) se c'è sul Pi; se no l'allegato resta solo nel nome
                    r = subprocess.run(["pdftotext", "-layout", "-", "-"], input=parte.get_payload(decode=True),
                                       capture_output=True, timeout=30)
                    pdf.append(f"[allegato {nome}]\n" + r.stdout.decode("utf-8", "replace"))
                except (OSError, subprocess.SubprocessError):
                    pass
            continue
        if tipo in ("text/plain", "text/html"):
            t = parte.get_payload(decode=True) or b""
            t = t.decode(parte.get_content_charset() or "utf-8", "replace")
            t = testo(t) if tipo == "text/html" else t
            if t.strip() and (not corpo or tipo == "text/plain"):   # un testo semplice vuoto non copre l'HTML
                corpo = t
    tutto = re.sub(r"\n{3,}", "\n\n", (corpo.strip() + "\n\n" + "\n\n".join(pdf)).strip())
    return tutto[:TESTO_MAX], allegati


# Le locandine: le immagini grandi delle mail (allegate o nel testo) e la prima pagina dei PDF corti si salvano
# nell'archivio, in allegati/<id del comunicato>/1.jpg …, per usarle al posto delle foto fatte con l'IA (voluto dal
# proprietario il 25 ott 2026: «se mandano locandine noi le dobbiamo usare, in questo caso niente immagini AI»).
# Pillow sta in un ambiente a parte sul Pi (~/nb-fonti/venv-img), solo per rimpicciolirle.
ALLEGATI = "allegati"
IMMAGINE_MIN = 60_000   # byte: sotto sono loghi e firme
IMMAGINI_PER_MAIL = 4
PDF_PAGINE_MAX = 2      # un PDF più lungo è un documento, non una locandina
LATO_MAX = 1600
VENV_IMG = os.path.join(CARTELLA, "venv-img", "bin", "python3")
RIDUCI = ("import io, sys\nfrom PIL import Image, ImageOps\n"
          "im = ImageOps.exif_transpose(Image.open(io.BytesIO(sys.stdin.buffer.read())))\n"
          "if im.mode in ('RGBA', 'LA', 'P'):\n"
          "    im = im.convert('RGBA'); f = Image.new('RGB', im.size, 'white'); f.paste(im, mask=im.getchannel('A')); im = f\n"
          f"im = im.convert('RGB'); im.thumbnail(({LATO_MAX}, {LATO_MAX}))\n"
          "im.save(sys.stdout.buffer, 'JPEG', quality=85, optimize=True, progressive=True)\n"
          "sys.stderr.write(f'{im.width} {im.height}')\n")


def riduci(dati):
    """Un'immagine (jpg, png, webp…) in JPEG di al massimo LATO_MAX px per lato: (byte, larghezza, altezza)."""
    r = subprocess.run([VENV_IMG, "-c", RIDUCI], input=dati, capture_output=True, timeout=60)
    if r.returncode:
        raise RuntimeError(r.stderr.decode("utf-8", "replace")[-300:])
    w, h = map(int, r.stderr.decode().split()[-2:])
    return r.stdout, w, h


def immagini_mail(m, ident):
    """Le immagini grandi di una mail e la prima pagina dei suoi PDF corti, salvate in allegati/<ident>/ dell'archivio:
    [{"file": "allegati/<ident>/1.jpg", "da": nome dell'allegato, "larghezza", "altezza"}]."""
    out = []
    for parte in m.walk():
        if len(out) >= IMMAGINI_PER_MAIL:
            break
        if parte.is_multipart():
            continue
        nome = parte.get_filename() or ""
        dati = parte.get_payload(decode=True) or b""
        try:
            if parte.get_content_maintype() == "image" and len(dati) >= IMMAGINE_MIN:
                jpg, w, h = riduci(dati)
            elif dati and (parte.get_content_type() == "application/pdf" or nome.lower().endswith(".pdf")):
                with tempfile.TemporaryDirectory() as td:
                    pdf = os.path.join(td, "a.pdf")
                    with open(pdf, "wb") as f:
                        f.write(dati)
                    info = subprocess.run(["pdfinfo", pdf], capture_output=True, timeout=30).stdout.decode("utf-8", "replace")
                    pagine = re.search(r"^Pages:\s+(\d+)", info, re.M)
                    if not pagine or int(pagine[1]) > PDF_PAGINE_MAX:
                        continue
                    subprocess.run(["pdftoppm", "-png", "-r", "150", "-f", "1", "-l", "1", "-singlefile", pdf,
                                    os.path.join(td, "p")], check=True, capture_output=True, timeout=60)
                    with open(os.path.join(td, "p.png"), "rb") as f:
                        jpg, w, h = riduci(f.read())
            else:
                continue
        except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as e:
            print(f"  immagine della mail {ident} ({nome or 'nel testo'}) non salvata: {e}", file=sys.stderr)
            continue
        rel = f"{ALLEGATI}/{ident}/{len(out) + 1}.jpg"
        os.makedirs(os.path.join(ARCHIVIO, ALLEGATI, ident), exist_ok=True)
        with open(os.path.join(ARCHIVIO, rel), "wb") as f:
            f.write(jpg)
        out.append({"file": rel, "da": nome or "immagine nel testo della mail", "larghezza": w, "altezza": h})
    return out


def pulisci_allegati(voci):
    """Via le immagini dei comunicati che non sono più in comunicati.json (più vecchi di 7 giorni)."""
    cartella = os.path.join(ARCHIVIO, ALLEGATI)
    tenere = {v.get("id") for v in voci}
    for d in os.listdir(cartella) if os.path.isdir(cartella) else []:
        if d not in tenere:
            shutil.rmtree(os.path.join(cartella, d), ignore_errors=True)


def posta(vecchie):
    """I comunicati arrivati a comunicati@notiziebenevento.it (Aruba): ultimi 7 giorni, casella aperta in sola lettura
    (non si segna niente come letto). Del mittente si tengono nome e dominio, non l'indirizzo."""
    import email
    import email.header
    import email.utils as eu
    import imaplib
    try:
        with open(POSTA_CONF, encoding="utf-8") as f:
            conf = json.load(f)
    except OSError:
        raise RuntimeError("casella non ancora collegata (manca posta.conf: fonti_casa.py --imposta-posta)") from None
    dec = lambda x: str(email.header.make_header(email.header.decode_header(x or "")))
    voci = []
    scartate = [l for l, v in vecchie.items() if not v]   # le mail già riconosciute come non comunicati
    adesso = dt.datetime.now(fuso()).isoformat(timespec="minutes")
    with imaplib.IMAP4_SSL(conf.get("server", POSTA_SERVER), 993, timeout=60) as M:
        M.login(conf["utente"], conf["password"])
        M.select("INBOX", readonly=True)
        dal = (dt.date.today() - dt.timedelta(days=7)).strftime("%d-%b-%Y")
        _, num = M.search(None, "SINCE", dal)
        for n in num[0].split()[-40:]:
            _, dati = M.fetch(n, "(BODY.PEEK[])")
            m = email.message_from_bytes(dati[0][1])
            mid = (m.get("Message-ID") or f"{m.get('Date')}-{m.get('Subject')}").strip()
            link = "posta:" + re.sub(r"[<>\s]", "", mid)
            if link in vecchie:
                continue
            nome, indirizzo = eu.parseaddr(dec(m.get("From")))
            mittente, dominio = nome or indirizzo.split("@")[0], indirizzo.rsplit("@", 1)[-1].lower()
            if non_comunicato(dec(m.get("Subject")), f"{nome} {indirizzo}", dominio, m):
                scartate.append(link)
                continue
            try:
                quando = eu.parsedate_to_datetime(m.get("Date")).astimezone(fuso()).isoformat(timespec="minutes")
            except (TypeError, ValueError):
                quando = dt.datetime.now(fuso()).isoformat(timespec="minutes")
            corpo, allegati = _testo_mail(m)
            v = {"id": id_posta(link), "titolo": dec(m.get("Subject")) or "(senza oggetto)", "link": link,
                 "data": quando, "arrivata": adesso, "mittente": mittente, "dominio": dominio,
                 "allegati": allegati, "testo": corpo}
            immagini = immagini_mail(m, v["id"])
            if immagini:
                v["immagini"] = immagini
            voci.append(v)
    return voci, {"scartate": scartate[-300:]}


def imposta_posta():
    """Chiede indirizzo e password della casella (la password non si vede), prova ad entrare e li salva sul Pi."""
    import getpass
    import imaplib
    utente = input("Indirizzo della casella [comunicati@notiziebenevento.it]: ").strip() or "comunicati@notiziebenevento.it"
    password = getpass.getpass("Password della casella (non si vede mentre la scrivi): ")
    try:
        with imaplib.IMAP4_SSL(POSTA_SERVER, 993, timeout=60) as M:
            M.login(utente, password)
            M.select("INBOX", readonly=True)
    except Exception as e:
        sys.exit(f"Non riesco a entrare nella casella ({type(e).__name__}): controlla indirizzo e password. Niente salvato.")
    os.makedirs(CARTELLA, exist_ok=True)
    vecchio = os.umask(0o077)
    try:
        with open(POSTA_CONF, "w", encoding="utf-8") as f:
            json.dump({"utente": utente, "password": password, "server": POSTA_SERVER}, f)
    finally:
        os.umask(vecchio)
    os.chmod(POSTA_CONF, 0o600)
    print(f"✓ casella {utente} collegata: dal prossimo giro (ogni 30 minuti) i comunicati vanno in comunicati.json")


PROVA = False
FONTI = {
    "anas": ("ANAS, comunicati della Campania", ANAS_LISTA, anas, 10),
    "asl": ("ASL Benevento, notizie e avvisi", ASL_LISTA, asl, 30),
    "tv7": ("TV7 Benevento (tvsette.net), feed con il testo degli articoli", TV7_FEED, tv7, 4),
    "comuni": ("I siti dei 78 Comuni della provincia, avvisi e notizie nuovi", "siti dei Comuni", comuni, 4),
    "albo": ("Albo pretorio del Comune di Benevento, ordinanze", ALBO_BN, albo_bn, 7),
    "regione": ("Regione Campania, comunicati stampa col testo", REGIONE, regione, 4),
    "comunicati": ("Comunicati arrivati per posta a comunicati@notiziebenevento.it", "comunicati@notiziebenevento.it",
                   posta, 7),
}


def leggi(nome, adesso):
    titolo, indirizzo, funzione, giorni = FONTI[nome]
    percorso = os.path.join(ARCHIVIO, f"{nome}.json")
    try:
        with open(percorso, encoding="utf-8") as f:
            prima = json.load(f)
    except (OSError, ValueError):
        prima = {}
    vecchie = {v["link"]: v for v in prima.get("voci", [])}
    dati = {"fonte": titolo, "indirizzo": indirizzo, "controllato": adesso.isoformat(timespec="minutes")}
    try:   # le mail scartate (non comunicati) restano note, così non si riaprono a ogni giro
        nuove = funzione({**{l: {} for l in prima.get("scartate", [])}, **vecchie})
        if isinstance(nuove, tuple):   # i Comuni dicono anche quali siti non si sono letti
            nuove, extra = nuove
            dati.update(extra)
        dati["esito"] = f"letta: {len(nuove)} voci"
        dati["ultima_lettura_riuscita"] = dati["controllato"]
    except Exception as e:   # la fonte non risponde: restano le voci di prima, e lo si dice
        nuove = []
        dati["esito"] = f"non raggiungibile: {type(e).__name__}: {e}"[:300]
        dati["ultima_lettura_riuscita"] = prima.get("ultima_lettura_riuscita", "")
    tutte = {v["link"]: v for v in list(vecchie.values()) + nuove}
    if nome == "comunicati":   # le voci di prima che non sono comunicati (rimbalzi…) escono; a tutte il loro id
        if "scartate" not in dati:
            dati["scartate"] = prima.get("scartate", [])
        for l, v in list(tutte.items()):
            if non_comunicato(v.get("titolo"), v.get("mittente"), v.get("dominio")):
                del tutte[l]
                dati["scartate"] = (dati["scartate"] + [l])[-300:]
            else:
                v.setdefault("id", id_posta(l))
    limite = (adesso - dt.timedelta(days=giorni)).date().isoformat()
    dati["voci"] = sorted((v for v in tutte.values() if v.get("data", "")[:10] >= limite),
                          key=lambda v: v.get("data", ""), reverse=True)[:200 if nome == "comuni" else 80]
    if nome == "comunicati" and not PROVA:
        pulisci_allegati(dati["voci"])
    return dati


LEGGIMI = """# Fonti lette da casa per Notizie Benevento

Le scarica ogni 30 minuti il Raspberry Pi di casa (`strumenti/fonti_casa.py` nell'archivio del sito), perché dal cloud
dell'agente non si aprono: ANAS e TV7 rifiutano le connessioni dall'estero, il sito dell'ASL ha il certificato
incompleto. La casella dei comunicati la legge ogni 5 minuti.

- `anas.json`: comunicati ANAS della Campania, ultimi 10 giorni (`data` senza ora, `compartimento` = ufficio ANAS).
- `asl.json`: notizie e avvisi dell'ASL Benevento, ultimi 30 giorni.
- `tv7.json`: articoli di TV7 Benevento con il testo, ultimi 4 giorni (TV7 copre anche Irpinia e Campania).
- `albo.json`: le ordinanze dell'albo pretorio del Comune di Benevento, ultimi 7 giorni (`mittente`, `numero_atto`,
  `data` = inizio della pubblicazione; il `testo` è l'oggetto dell'ordinanza).
- `regione.json`: i comunicati stampa della Regione Campania col testo, ultimi 4 giorni (tutta la Campania: tenere
  solo quelli che riguardano il Sannio).
- `comuni.json`: avvisi e notizie NUOVI dei siti dei 78 Comuni della provincia, ultimi 4 giorni: `comune`,
  `primo_visto` (quando è comparso sul sito: per sapere cosa è nuovo dall'ultimo giro), `data_avviso` (la prima data
  scritta nella pagina, se c'è), `testo`. `comuni_letti` e `comuni_non_letti` dicono quali siti si sono letti.
  Dal 23 ott 2026 ci sono anche gli atti nuovi degli albi pretori di 57 Comuni (`fonte`: «albo pretorio»): ordinanze,
  avvisi e bandi (niente determine, delibere, permessi), con `data_avviso` = inizio della pubblicazione e nel `testo`
  tipo, numero, oggetto e il testo del PDF allegato quando si legge. `albi_letti` e `albi_non_letti`.
- `comunicati.json`: i comunicati arrivati per posta a comunicati@notiziebenevento.it, ultimi 7 giorni: `id` (breve,
  lo stesso di comunicati_visti.json del sito), `titolo` = oggetto, `data` = la data della mail, `arrivata` = quando
  il Pi l'ha vista, `mittente` (nome) e `dominio` (dopo la @), `allegati`, `testo` (con quello dei PDF allegati). Il
  `link` è «posta:…»: non è un indirizzo da citare. Rimbalzi, risposte automatiche e avvisi di Aruba non ci sono
  (`scartate`: solo i loro riferimenti). Appena ne arriva uno il Pi fa partire il giro lampo (COMUNICATI.md del sito).
  `immagini` (dal 25 ott 2026): le immagini grandi della mail e la prima pagina dei PDF di 1-2 pagine, in JPEG nella
  cartella `allegati/<id>/` (`file`, `da` = nome dell'allegato, `larghezza`, `altezza`): le locandine degli eventi.

In ogni file: `controllato` = ultimo tentativo, `esito`, `ultima_lettura_riuscita`, `voci` (titolo, link, data,
testo). Il `link` è quello originale da citare tra le fonti. Archivio privato: i testi restano di chi li ha scritti.
"""


def pubblica(adesso):
    env = dict(os.environ, GIT_SSH_COMMAND=f"ssh -i {CHIAVE} -o IdentitiesOnly=yes -o StrictHostKeyChecking=accept-new")
    def git(*a):
        return subprocess.run(["git", "-C", ARCHIVIO, *a], env=env, check=True, capture_output=True, text=True)
    if not os.path.isdir(os.path.join(ARCHIVIO, ".git")):
        git("init", "-q", "-b", "main")
        git("remote", "add", "origin", REMOTO)
        git("config", "user.name", "Pi di casa")
        git("config", "user.email", "ernbale@users.noreply.github.com")
    git("add", "-A")
    msg = f"Fonti lette da casa alle {adesso:%H:%M} del {adesso:%d/%m}"
    ha_commit = subprocess.run(["git", "-C", ARCHIVIO, "rev-parse", "-q", "--verify", "HEAD"],
                               capture_output=True).returncode == 0
    git("commit", "-q", "--amend", "-m", msg) if ha_commit else git("commit", "-q", "-m", msg)
    git("push", "-q", "-f", "origin", "HEAD:main")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--prova", action="store_true", help="scarica e stampa, senza pubblicare")
    ap.add_argument("--imposta-posta", action="store_true", help="collega la casella dei comunicati (chiede la password)")
    ap.add_argument("--solo", nargs="+", choices=list(FONTI), help="legge solo queste fonti e pubblica solo se c'è "
                    "qualcosa di nuovo (dal cron ogni 5 minuti per la posta)")
    a = ap.parse_args()
    if a.imposta_posta:
        return imposta_posta()
    global PROVA
    PROVA = a.prova
    adesso = dt.datetime.now(fuso())
    os.makedirs(ARCHIVIO, exist_ok=True)
    esiti, nuove = [], 0
    for nome in a.solo or FONTI:
        try:
            with open(os.path.join(ARCHIVIO, f"{nome}.json"), encoding="utf-8") as f:
                prima = {v["link"] for v in json.load(f).get("voci", [])}
        except (OSError, ValueError):
            prima = set()
        dati = leggi(nome, adesso)
        nuove += sum(v["link"] not in prima for v in dati["voci"])
        esiti.append(f"{nome} {dati['esito']} ({len(dati['voci'])} tenute)")
        if a.prova:
            for v in dati["voci"][:3]:
                print(f"  {nome}: {v['data']} | {v['titolo'][:80]} | {len(v['testo'])} car.")
            continue
        with open(os.path.join(ARCHIVIO, f"{nome}.json"), "w", encoding="utf-8") as f:
            json.dump(dati, f, ensure_ascii=False, indent=1)
    if a.solo:   # ogni 5 minuti: si pubblica e si scrive nel registro solo se è arrivato qualcosa o la fonte non va
        if nuove and not a.prova:
            pubblica(adesso)
        if nuove or any("non raggiungibile" in x for x in esiti):
            print(f"{adesso:%Y-%m-%d %H:%M} solo " + " · ".join(esiti) + (f" · {nuove} nuove" + ("" if a.prova else ", pubblicate") if nuove else ""))
        return
    if not a.prova:
        with open(os.path.join(ARCHIVIO, "LEGGIMI.md"), "w", encoding="utf-8") as f:
            f.write(LEGGIMI)
        pubblica(adesso)
    print(f"{adesso:%Y-%m-%d %H:%M} " + " · ".join(esiti))


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"{dt.datetime.now():%Y-%m-%d %H:%M} ERRORE: {type(e).__name__}: {e}", file=sys.stderr)
        sys.exit(1)
