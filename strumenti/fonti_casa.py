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

Uso sul Pi:   python3 ~/nb-fonti/fonti_casa.py            (scarica e pubblica)
              python3 ~/nb-fonti/fonti_casa.py --prova    (scarica e stampa, senza pubblicare)
"""
import argparse
import datetime as dt
import email.utils
import html
import json
import os
import re
import ssl
import subprocess
import sys
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
    if not PROVA:
        with open(p_visti + ".tmp", "w", encoding="utf-8") as f:
            json.dump({k: v[-300:] for k, v in visti.items()}, f, ensure_ascii=False)
        os.replace(p_visti + ".tmp", p_visti)
    return voci, {"comuni_letti": f"{len(COMUNI) - len(non_letti)} su {len(COMUNI)}", "comuni_non_letti": non_letti}


PROVA = False
FONTI = {
    "anas": ("ANAS, comunicati della Campania", ANAS_LISTA, anas, 10),
    "asl": ("ASL Benevento, notizie e avvisi", ASL_LISTA, asl, 30),
    "tv7": ("TV7 Benevento (tvsette.net), feed con il testo degli articoli", TV7_FEED, tv7, 4),
    "comuni": ("I siti dei 78 Comuni della provincia, avvisi e notizie nuovi", "siti dei Comuni", comuni, 4),
    "albo": ("Albo pretorio del Comune di Benevento, ordinanze", ALBO_BN, albo_bn, 7),
    "regione": ("Regione Campania, comunicati stampa col testo", REGIONE, regione, 4),
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
    try:
        nuove = funzione(vecchie)
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
    limite = (adesso - dt.timedelta(days=giorni)).date().isoformat()
    dati["voci"] = sorted((v for v in tutte.values() if v.get("data", "")[:10] >= limite),
                          key=lambda v: v.get("data", ""), reverse=True)[:80]
    return dati


LEGGIMI = """# Fonti lette da casa per Notizie Benevento

Le scarica ogni 30 minuti il Raspberry Pi di casa (`strumenti/fonti_casa.py` nell'archivio del sito), perché dal cloud
dell'agente non si aprono: ANAS e TV7 rifiutano le connessioni dall'estero, il sito dell'ASL ha il certificato
incompleto.

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
    a = ap.parse_args()
    global PROVA
    PROVA = a.prova
    adesso = dt.datetime.now(fuso())
    os.makedirs(ARCHIVIO, exist_ok=True)
    esiti = []
    for nome in FONTI:
        dati = leggi(nome, adesso)
        esiti.append(f"{nome} {dati['esito']} ({len(dati['voci'])} tenute)")
        if a.prova:
            for v in dati["voci"][:3]:
                print(f"  {nome}: {v['data']} | {v['titolo'][:80]} | {len(v['testo'])} car.")
            continue
        with open(os.path.join(ARCHIVIO, f"{nome}.json"), "w", encoding="utf-8") as f:
            json.dump(dati, f, ensure_ascii=False, indent=1)
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
