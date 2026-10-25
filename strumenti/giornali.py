#!/usr/bin/env python3
"""L'elenco degli articoli nuovi dei giornali del Sannio, per il giro dell'agente.

Legge i 14 giornali (feed RSS; Ottopagine dalla sua pagina /bn/ con la data di ogni articolo; TV7 dal file tv7.json
che scarica il computer di casa) e i comunicati delle società sportive (fonte ufficiale), tiene gli articoli usciti dall'ultimo giro e li raggruppa per fatto (titoli con
le stesse parole), mettendo accanto anche gli articoli delle ultime 24 ore sullo stesso fatto: così si vede subito
quante testate lo riportano. Toglie i gruppi già citati in una notizia del sito.

Per ogni gruppo l'agente scrive una decisione nel diario del giro (/tmp/diario.json, «decisioni»): archivia.py --giro
controlla che non ne manchi nessuna. Così niente sparisce in silenzio (22 ott 2026: al giro delle 9:07 l'agente aveva
guardato solo le storie che conosceva e lasciato fuori Unisannio in Dad, Coldiretti, l'autocisterna scortata…).

Scrive /tmp/titoli.json (i gruppi) e /tmp/fonti_giornali.txt (le righe dei giornali per il registro delle fonti,
che archivia.py legge insieme a /tmp/fonti.txt). Solo libreria standard: nel cloud dell'agente non si installa niente.

Uso:  python3 strumenti/giornali.py [--dal AAAA-MM-GGTHH:MM]
"""
import argparse
import concurrent.futures as cf
import datetime as dt
import email.utils
import glob
import html
import json
import os
import re
import sys
import unicodedata
import urllib.request

SITO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FONTI_CASA = os.path.join(os.path.dirname(SITO), "notizie-benevento-fonti")
AGENTE = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130 Safari/537.36"
MARGINE = dt.timedelta(minutes=20)       # prima dell'ultimo giro: gli articoli usciti mentre lavorava
CONTESTO = dt.timedelta(hours=24)        # articoli più vecchi che servono solo a contare le testate di un fatto
MAX_INDIETRO = dt.timedelta(hours=14)    # il primo giro del mattino guarda dalla sera prima, non oltre
LAMPO_MINUTI = 40   # un comunicato per email non ancora trattato dal giro lampo dopo tanto lo decide il giro di ogni ora

# nome come nel registro delle fonti, autorevole per la regola 2, come si legge, homepage (se il feed non risponde)
TESTATE = [
    ("Ottopagine", True, "ottopagine", "https://www.ottopagine.it/bn/", "https://www.ottopagine.it/bn/"),
    ("Il Sannio Quotidiano", True, "wp", "https://www.ilsannioquotidiano.it/feed/", "https://www.ilsannioquotidiano.it/"),
    ("NTR24", True, "wp", "https://www.ntr24.tv/feed/", "https://www.ntr24.tv/"),
    ("Lab TV", True, "wp", "https://www.labtv.net/feed/", "https://www.labtv.net/"),
    ("Cronache del Sannio", True, "wp", "https://www.cronachedelsannio.it/sannionews24/feed/",
     "https://www.cronachedelsannio.it/sannionews24/"),
    ("Fremondoweb", False, "wp", "https://www.fremondoweb.com/category/notizie-dalla-valle-telesina/feed/",
     "https://www.fremondoweb.com/category/notizie-dalla-valle-telesina/"),
    ("Gazzetta di Benevento", False, "rss", "https://www.gazzettabenevento.it/rss.xml", "https://www.gazzettabenevento.it/"),
    ("Anteprima24", True, "wp-benevento", "https://www.anteprima24.it/feed/", "https://www.anteprima24.it/benevento/"),
    ("InfoSannio", False, "wp", "https://www.infosannionews.it/feed/", "https://www.infosannionews.it/"),
    ("Benevento Giornale", False, "wp", "https://www.beneventogiornale.com/feed/", "https://www.beneventogiornale.com/"),
    ("BeneventoNews24", True, "wp", "https://www.beneventonews24.it/feed/", "https://www.beneventonews24.it/"),
    ("Il Mattino", True, "rss", "https://www.ilmattino.it/rss/benevento.xml", "https://www.ilmattino.it/benevento/"),
    ("TV7 Benevento", True, "casa", "tv7.json", ""),
    ("Il Caudino", False, "wp", "https://ilcaudino.it/feed/", "https://ilcaudino.it/"),
    # lo sport di NTR24 sta su un sito a parte (dal 2023 il feed sport del sito principale è fermo)
    ("NTR24 Sport", True, "wp", "https://sport.ntr24.tv/feed/", "https://sport.ntr24.tv/"),
    ("SannioSport", False, "wp", "https://sanniosport.it/feed/", "https://sanniosport.it/"),
    # società sportive del Sannio con un sito che pubblica comunicati (censimento del 22 ott 2026): fonte ufficiale
    ("Benevento Calcio", True, "beneventocalcio", "https://www.beneventocalcio.club/news/1.shtml",
     "https://www.beneventocalcio.club/news/"),
    ("Miwa Basket Benevento", True, "wp", "https://www.cestisticabenevento.it/feed/", "https://www.cestisticabenevento.it/"),
    ("Benevento 5", True, "wp", "https://ssdbenevento5.it/feed/", "https://ssdbenevento5.it/"),
    ("Accademia Volley Benevento", True, "wp", "https://www.accademiavolley.com/feed/", "https://www.accademiavolley.com/"),
    ("Rugby Benevento", True, "wp", "https://beneventorugby.com/feed/", "https://beneventorugby.com/"),
    ("Rugby IV Circolo Benevento", True, "wp", "https://www.rugbyivcircolobenevento.com/feed/",
     "https://www.rugbyivcircolobenevento.com/"),
    ("Apice Calcio", True, "wp", "https://www.apicecalcio1964.it/feed/", "https://www.apicecalcio1964.it/"),
    ("Tennis Club 2002 Benevento", True, "wp", "https://www.tennisclub2002.it/feed/", "https://www.tennisclub2002.it/"),
    ("GS Meomartini", True, "wp", "https://www.gsmeomartini.it/feed/", "https://www.gsmeomartini.it/"),
    # leghe e federazioni: i comunicati della LND di Benevento (dilettanti) e, dai feed nazionali, solo le squadre sannite
    ("LND Benevento", True, "wp",
     "https://campania.lnd.it/category/comunicati-ufficiali-2026-2027/delegazioni-provinciali-comunicati-ufficiali-2026-2027/"
     "delegaz-prov-di-benevento-delegazioni-provinciali-comunicati-ufficiali-2026-2027/feed/",
     "https://campania.lnd.it/comunicati-ufficiali-deleg-prov-di-benevento-2026-2027/"),
    ("Divisione Calcio a 5", True, "wp-sannio", "https://divisionecalcioa5.it/feed/", "https://divisionecalcioa5.it/"),
    ("Federazione Pallamano", True, "wp-sannio", "https://www.federhandball.it/feed/", "https://www.federhandball.it/"),
    ("Federazione Rugby", True, "wp-sannio", "https://federugby.it/feed/", "https://federugby.it/"),
]
# fonti ufficiali (regola 2: bastano da sole). ⛔ FIPAV (pallavolo): i suoi siti vietano la lettura automatica
UFFICIALI = {"Benevento Calcio", "Miwa Basket Benevento", "Benevento 5", "Accademia Volley Benevento", "Rugby Benevento",
             "Rugby IV Circolo Benevento", "Apice Calcio", "Tennis Club 2002 Benevento", "GS Meomartini", "LND Benevento",
             "Divisione Calcio a 5", "Federazione Pallamano", "Federazione Rugby"}
SANNIO = re.compile(r"benevent|sanni|telese|montesarchio|airola|apice|ceppaloni|paduli|morcone|cerreto|"
                    r"san giorgio del sannio|sant'agata|solopaca|vitulano|faicchio|cusano", re.I)

# parole che non dicono di quale fatto si parla
VUOTE = set("""benevento sannio sannita sanniti provincia provinciale comune comunale citta oggi domani ieri anche ancora
sono stato stata stati state essere della delle dello degli dalla dalle dallo dagli nella nelle nello negli sulla
sulle sullo sugli alla alle allo agli come dopo prima contro verso senza sotto sopra tutti tutte tutto ogni questo
questa quella quello presso fino nuovo nuova nuovi nuove grande primo prima anni anno giorno giorni settimana mese
lunedi martedi mercoledi giovedi venerdi sabato domenica ottobre novembre dicembre gennaio febbraio marzo aprile
maggio giugno luglio agosto settembre video foto news live ecco cosa perche quando dove mentre sara saranno arriva
fare fatto fatti dice dicono parla annuncia serie bkt 2025 2026 2027 2028""".split())   # sport: «Serie BKT 2026-2027» è in tutti i titoli

MESI_IT = {"gen": "Jan", "feb": "Feb", "mar": "Mar", "apr": "Apr", "mag": "May", "giu": "Jun", "lug": "Jul",
           "ago": "Aug", "set": "Sep", "ott": "Oct", "nov": "Nov", "dic": "Dec"}
GIORNI_IT = {"lun": "Mon", "mar": "Tue", "mer": "Wed", "gio": "Thu", "ven": "Fri", "sab": "Sat", "dom": "Sun"}


def fuso():
    from zoneinfo import ZoneInfo
    return ZoneInfo("Europe/Rome")


def scarica(url, timeout=25):
    req = urllib.request.Request(url, headers={"User-Agent": AGENTE, "Accept-Language": "it-IT,it;q=0.9"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        dati = r.read()
        cs = r.headers.get_content_charset()
    if not cs:
        m = re.search(rb'encoding=["\']([\w-]+)', dati[:200])
        cs = m.group(1).decode() if m else "utf-8"
    return dati.decode(cs, errors="replace")


def pulisci(s):
    s = re.sub(r"<!\[CDATA\[|\]\]>", "", s or "")
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", s))).strip()


def data_rss(s):
    s = (s or "").strip()
    if not s:
        return None
    p = s.split()
    if p and p[0].rstrip(",").lower() in GIORNI_IT:   # Il Mattino: «gio, 22 ott 2026 00:00:06 +0200»
        p[0] = GIORNI_IT[p[0].rstrip(",").lower()] + ","
        if len(p) > 2 and p[2].lower() in MESI_IT:
            p[2] = MESI_IT[p[2].lower()]
        s = " ".join(p)
    try:
        d = email.utils.parsedate_to_datetime(s)
    except (TypeError, ValueError):
        try:
            d = dt.datetime.fromisoformat(s.replace("Z", "+00:00"))
        except ValueError:
            return None
    return d if d.tzinfo else d.replace(tzinfo=fuso())


def voci_rss(testo):
    out = []
    for it in re.findall(r"<item\b.*?</item>", testo, re.S | re.I):
        ti = re.search(r"<title>(.*?)</title>", it, re.S | re.I)
        li = re.search(r"<link>(.*?)</link>", it, re.S | re.I)
        da = re.search(r"<pubDate>(.*?)</pubDate>", it, re.S | re.I) or re.search(r"<dc:date>(.*?)</dc:date>", it, re.S)
        if ti and li:
            out.append({"titolo": pulisci(ti.group(1)), "url": pulisci(li.group(1)), "data": data_rss(pulisci(da.group(1)) if da else "")})
    return out


def leggi_feed(tipo, url, dal_contesto):
    """Le voci di un feed; per WordPress va alle pagine dopo finché non arriva a quelle più vecchie del contesto."""
    voci, pagine = [], 4 if tipo in ("wp", "wp-benevento") else 1
    for n in range(1, pagine + 1):
        u = url if n == 1 else f"{url}{'&' if '?' in url else '?'}paged={n}"
        try:
            nuove = voci_rss(scarica(u))
        except Exception:
            if n == 1:
                raise
            break
        voci += nuove
        date = [v["data"] for v in nuove if v["data"]]
        if not nuove or (date and min(date) < dal_contesto):
            break
    if tipo == "wp-benevento":   # Anteprima24 è di tutta la Campania: solo la sezione Benevento
        voci = [v for v in voci if "/benevento/" in v["url"]]
    elif tipo == "wp-sannio":    # feed nazionali (leghe, federazioni): solo i titoli con squadre o paesi del Sannio
        voci = [v for v in voci if SANNIO.search(v["titolo"])]
    return voci


def data_pagina(url):
    t = scarica(url, timeout=20)
    m = (re.search(r'article:published_time"\s+content="([^"]+)"', t) or re.search(r'"datePublished":\s*"([^"]+)"', t))
    if not m:
        return None
    d = dt.datetime.fromisoformat(m.group(1).replace("Z", "+00:00"))
    return d if d.tzinfo else d.replace(tzinfo=fuso())


# siti senza feed ma con gli articoli numerati (il numero più alto è il più nuovo): dove sono i link
NUMERATI = {
    "ottopagine": ("https://www.ottopagine.it", r'<a [^>]*href="(/bn/[a-z-]+/(\d+)/[^"]+\.shtml)"[^>]*>(.*?)</a>'),
    "beneventocalcio": ("https://www.beneventocalcio.club",
                        r'<a [^>]*href="(/news/(?:notizie|comunicatistampa|iniziativegiallorosse)/(\d+)/[^"]+\.shtml)"[^>]*>(.*?)</a>'),
}


def leggi_numerati(tipo, url, dal):
    """Ottopagine e il sito del Benevento Calcio non hanno un feed: i link della pagina, dal più nuovo (numero più
    alto), con la data scritta in ogni articolo; si ferma quando arriva a quelli più vecchi dell'ultimo giro."""
    base, schema = NUMERATI[tipo]
    t = scarica(url)
    visti = {}
    for m in re.finditer(schema, t, re.S):
        tit = pulisci(m.group(3))
        if tit.lower() in ("leggi", "leggi tutto", "continua"):
            tit = ""
        if len(tit) > len(visti.get(m.group(1), ("", 0))[0]) or m.group(1) not in visti:
            visti[m.group(1)] = (tit or visti.get(m.group(1), ("", 0))[0], int(m.group(2)))
    link = sorted(visti.items(), key=lambda x: -x[1][1])[:40]
    voci = []
    with cf.ThreadPoolExecutor(8) as ex:
        for i in range(0, len(link), 8):
            pezzo = link[i:i + 8]
            date = list(ex.map(lambda x: _prova(data_pagina, base + x[0]), pezzo))
            for (h, (tit, _)), d in zip(pezzo, date):
                voci.append({"titolo": tit or h, "url": base + h, "data": d})
            if all(d and d < dal for d in date):
                break
    return voci


def _prova(f, *a):
    try:
        return f(*a)
    except Exception:
        return None


def leggi_casa(nome_file):
    with open(os.path.join(FONTI_CASA, nome_file), encoding="utf-8") as f:
        d = json.load(f)
    return [{"titolo": v.get("titolo", ""), "url": v.get("link", ""), "data": data_rss(v.get("data"))}
            for v in d.get("voci", [])], d.get("controllato")


def _semplice(t):
    t = unicodedata.normalize("NFKD", t.lower())
    return "".join(c for c in t if not unicodedata.combining(c))


def _nomi_composti():
    """«Sant'Agata de' Goti» → una parola sola: tre parole in comune non devono bastare per fare lo stesso fatto."""
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from meteo import COMUNI_BN
    nomi = [_semplice(c) for c in COMUNI_BN] + ["valle caudina", "valle telesina", "palazzo mosti", "fortore",
                                                "ponte delle tavole", "castel del lago", "san pio"]
    return sorted((n for n in nomi if re.search(r"\W", n)), key=len, reverse=True)


NOMI_COMPOSTI = _nomi_composti()


def parole(titolo):
    t = _semplice(titolo).replace("’", "'")
    for n in NOMI_COMPOSTI:
        t = t.replace(n, re.sub(r"\W", "", n))
    return {w for w in re.findall(r"[a-z0-9]+", t) if (len(w) >= 4 or w.isdigit()) and w not in VUOTE}


def stesso_fatto(a, b):
    comuni = a & b
    return len(comuni) >= 3 or (len(comuni) >= 2 and len(comuni) / max(1, min(len(a), len(b))) >= 0.5)


def norma_url(u):
    u = re.sub(r"^https?://(www\.)?", "", (u or "").strip().lower())
    return re.sub(r"[?#].*$", "", u).rstrip("/")


def citati():
    """url → id della notizia (o approfondimento) che lo cita, in prima pagina e in archivio."""
    out = {}
    file = [os.path.join(SITO, "notizie.json")] + sorted(glob.glob(os.path.join(SITO, "archivio", "[0-9]*-[0-9]*.json")))
    for p in file:
        try:
            with open(p, encoding="utf-8") as f:
                d = json.load(f)
        except (OSError, ValueError):
            continue
        for n in d.get("notizie", []) + d.get("approfondimenti", []):
            for fo in (n.get("fonti") or []) + ((n.get("articolo") or {}).get("fonti") or []):
                if fo.get("url"):
                    out.setdefault(norma_url(fo["url"]), n.get("id"))
            for c in n.get("comunicati") or []:   # i comunicati per email da cui viene la notizia (id di comunicati.json)
                out.setdefault(norma_url("posta:" + str(c)), n.get("id"))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dal", help="articoli usciti da quest'ora (di solito: l'ultimo giro, letto da notizie.json)")
    ap.add_argument("--uscita", default="/tmp/titoli.json")
    ap.add_argument("--registro", default="/tmp/fonti_giornali.txt")
    a = ap.parse_args()
    adesso = dt.datetime.now(fuso())
    if a.dal:
        dal = dt.datetime.fromisoformat(a.dal)
        dal = dal if dal.tzinfo else dal.replace(tzinfo=fuso())
    else:
        try:
            with open(os.path.join(SITO, "notizie.json"), encoding="utf-8") as f:
                dal = dt.datetime.fromisoformat(json.load(f)["aggiornato"]) - MARGINE
        except (OSError, ValueError, KeyError):
            dal = adesso - dt.timedelta(hours=3)
        dal = max(dal, adesso - MAX_INDIETRO)
    dal_contesto = dal - CONTESTO

    def leggi(t):
        nome, autorevole, tipo, url, home = t
        if tipo == "casa":
            voci, controllato = leggi_casa(url)
            return nome, voci, f"letta (da casa, controllato {str(controllato)[11:16]})"
        if tipo in NUMERATI:
            return nome, leggi_numerati(tipo, url, dal), "letta (pagina delle notizie, data di ogni articolo)"
        try:
            return nome, leggi_feed(tipo, url, dal_contesto), "letta (feed)"
        except Exception:   # secondo tentativo, poi la homepage: se risponde quella, la legge l'agente a mano
            try:
                return nome, leggi_feed(tipo, url, dal_contesto), "letta (feed, al secondo tentativo)"
            except Exception as e:
                scarica(home)
                return nome, [], (f"letta solo la homepage {home} (il feed {url} non risponde: {type(e).__name__}): "
                                  "i suoi articoli NON sono nell'elenco, guardali a mano")

    risultati, registro = {}, []
    with cf.ThreadPoolExecutor(8) as ex:
        fut = {ex.submit(leggi, t): t for t in TESTATE}
        for f in cf.as_completed(fut):
            nome, autorevole, tipo, url, home = fut[f]
            try:
                _, voci, come = f.result()
                risultati[nome] = (autorevole, voci)
                nuove = sum(1 for v in voci if v["data"] and v["data"] >= dal)
                registro.append(f"{nome} | {come} | {nuove} articoli dall'ultimo giro (elenco /tmp/titoli.json)")
            except Exception as e:
                motivo = f"{type(e).__name__}: {str(e)[:80]}"
                registro.append(f"{nome} | non raggiungibile (riprovato con {home or url}: {motivo}) | "
                                "riprova a mano più tardi")
                risultati[nome] = (autorevole, [])

    # gli avvisi e gli atti nuovi dei Comuni (comuni.json da casa: i loro siti e, dal 23 ott 2026, gli albi pretori),
    # fonte ufficiale, con l'ora in cui sono comparsi: anche per loro una decisione ciascuno, come per i giornali
    # (lui, 23 ott: «per i comuni il giro agente si deve impegnare molto di più, troppo poche pubblicate»)
    comunali = set()
    try:
        with open(os.path.join(FONTI_CASA, "comuni.json"), encoding="utf-8") as f:
            for v in json.load(f).get("voci", []):
                nome = f"Comune di {v.get('comune')}"
                comunali.add(nome)
                risultati.setdefault(nome, (True, []))[1].append(
                    {"titolo": v.get("titolo", ""), "url": v.get("link", ""), "data": data_rss(v.get("primo_visto"))})
    except (OSError, ValueError) as e:
        print(f"ATTENZIONE: comuni.json (siti e albi dei Comuni) non si legge ({type(e).__name__}): guardalo a mano")
    n_comuni = sum(1 for nome in comunali for v in risultati[nome][1] if v["data"] and v["data"] >= dal)

    # i comunicati arrivati per posta (comunicati.json da casa): appena arrivano li pubblica il giro lampo
    # (COMUNICATI.md, strumenti/comunicati.py). Qui entrano quelli che il giro lampo ha scartato e quelli che dopo
    # LAMPO_MINUTI non ha ancora trattato (anche se arrivati prima dell'ultimo giro): una decisione ciascuno, come per i
    # giornali. Il 24 ott 2026 il comunicato della CISL FP, in mezzo a 13 rimbalzi, è sfuggito al giro delle 12:06.
    gia = citati()
    postali, n_posta, in_lampo = set(), 0, 0
    try:
        with open(os.path.join(SITO, "comunicati_visti.json"), encoding="utf-8") as f:
            visti = json.load(f).get("visti") or {}
    except (OSError, ValueError):
        visti = {}
    try:
        with open(os.path.join(FONTI_CASA, "comunicati.json"), encoding="utf-8") as f:
            posta = json.load(f).get("voci", [])
    except (OSError, ValueError) as e:
        posta = []
        print(f"ATTENZIONE: comunicati.json (posta) non si legge ({type(e).__name__}): guardalo a mano")
    for v in posta:
        arrivata = data_rss(v.get("arrivata") or v.get("data"))
        if not v.get("id") or not arrivata or adesso - arrivata > dt.timedelta(hours=24):
            continue
        n_posta += 1
        esito = visti.get(v["id"]) or {}
        if esito.get("esito") in ("pubblicato", "gia_nel_sito"):
            gia[norma_url("posta:" + v["id"])] = esito.get("notizia")
        elif not esito and adesso - arrivata < dt.timedelta(minutes=LAMPO_MINUTI):
            in_lampo += 1   # ci sta lavorando il giro lampo
            continue
        nome = f"Comunicato per email: {v.get('mittente') or v.get('dominio')}"
        postali.add(nome)
        quando = arrivata if (esito or arrivata >= dal) else dal   # non trattato dal giro lampo: è da decidere adesso
        risultati.setdefault(nome, (True, []))[1].append(
            {"titolo": v.get("titolo", ""), "url": "posta:" + v["id"], "data": quando})
    articoli = []
    for nome, (autorevole, voci) in risultati.items():
        for v in voci:
            if not v["data"] or v["data"] < dal_contesto or v["data"] > adesso + dt.timedelta(minutes=10):
                continue
            articoli.append({"testata": nome, "autorevole": autorevole, "titolo": v["titolo"], "url": v["url"],
                             "data": v["data"], "parole": parole(v["titolo"]), "citato": gia.get(norma_url(v["url"]))})
    # gruppi: stesso fatto se i titoli hanno abbastanza parole in comune (unione a catena)
    capo = list(range(len(articoli)))

    def radice(i):
        while capo[i] != i:
            capo[i] = capo[capo[i]]
            i = capo[i]
        return i
    for i in range(len(articoli)):
        for j in range(i + 1, len(articoli)):
            if stesso_fatto(articoli[i]["parole"], articoli[j]["parole"]):
                capo[radice(i)] = radice(j)
    gruppi = {}
    for i, x in enumerate(articoli):
        gruppi.setdefault(radice(i), []).append(x)

    elenco = []
    for g in gruppi.values():
        nuovi = [x for x in g if x["data"] >= dal]
        if not nuovi:
            continue
        if all(x["citato"] for x in nuovi):   # già nelle notizie del sito: niente da decidere
            continue
        g.sort(key=lambda x: x["data"])
        elenco.append({
            "titolo": max(nuovi, key=lambda x: x["data"])["titolo"],
            "ultimo": max(x["data"] for x in nuovi),
            "testate": sorted({x["testata"] for x in g}),
            "autorevoli": sorted({x["testata"] for x in g if x["autorevole"]}),
            "ufficiali": sorted({x["testata"] for x in g if x["testata"] in UFFICIALI or x["testata"] in comunali
                                 or x["testata"] in postali}),
            "comuni": sorted({x["testata"] for x in g if x["testata"] in comunali}),
            "comunicati": sorted({x["testata"] for x in g if x["testata"] in postali}),
            "citato_in": sorted({x["citato"] for x in g if x["citato"]}),
            "articoli": [{"testata": x["testata"], "titolo": x["titolo"], "url": x["url"],
                          "data": x["data"].astimezone(fuso()).isoformat(timespec="minutes"),
                          "nuovo": x["data"] >= dal, "citato_in": x["citato"]} for x in g],
        })
    elenco.sort(key=lambda g: g["ultimo"], reverse=True)
    for i, g in enumerate(elenco, 1):
        g["id"] = f"G{i}"
        g["ultimo"] = g["ultimo"].astimezone(fuso()).isoformat(timespec="minutes")
    uscita = {"creato": adesso.isoformat(timespec="minutes"), "dal": dal.isoformat(timespec="minutes"),
              "gruppi": [{"id": g.pop("id"), **g} for g in elenco]}
    with open(a.uscita, "w", encoding="utf-8") as f:
        json.dump(uscita, f, ensure_ascii=False, indent=1)
    ordine = [t[0] for t in TESTATE]
    registro.sort(key=lambda r: ordine.index(r.split(" | ")[0]) if r.split(" | ")[0] in ordine else len(ordine))
    with open(a.registro, "w", encoding="utf-8") as f:
        f.write("\n".join(registro) + "\n")

    print(f"Articoli dei giornali e avvisi dei Comuni ({n_comuni} nuovi da siti e albi pretori) usciti dalle "
          f"{dal.strftime('%H:%M')} del {dal.strftime('%d/%m')}: {len(elenco)} fatti da decidere (scrivi una decisione "
          "per ognuno in «decisioni» del diario)")
    print(f"Comunicati per email delle ultime 24 ore: {n_posta} (quelli già pubblicati dal giro lampo non sono "
          f"nell'elenco; {in_lampo} in lavorazione adesso dal giro lampo: non toccarli). Quelli nell'elenco "
          "(«Comunicato per email: …», url «posta:<id>») leggili in comunicati.json dell'archivio di casa (campo id).\n")
    for r in registro:
        if "non raggiungibile" in r or "solo la homepage" in r:
            print("ATTENZIONE:", r)
    for g in uscita["gruppi"]:
        aut = f"{len(g['autorevoli'])} autorevoli" if g["autorevoli"] else "nessuna autorevole"
        if g["ufficiali"]:
            aut += f", fonte ufficiale: {', '.join(g['ufficiali'])}"
        cit = f" · già in: {', '.join(g['citato_in'])}" if g["citato_in"] else ""
        print(f"{g['id']} · {len(g['testate'])} testate ({aut}){cit}")
        for x in g["articoli"]:
            print(f"   {'*' if x['nuovo'] else ' '} {x['data'][5:10].replace('-', '/')} {x['data'][11:16]} "
                  f"{x['testata']}: {x['titolo'][:110]}\n       {x['url']}")
    print(f"\n(* = uscito dall'ultimo giro) · elenco completo in {a.uscita} · righe del registro in {a.registro}")
    try:   # le date ufficiali di teatri e concerti ancora senza evento (strumenti/stagioni.py, dal 25 ott 2026)
        import stagioni
        print("\n" + stagioni.riepilogo())
    except Exception as e:
        print(f"\nATTENZIONE: strumenti/stagioni.py non è andato ({type(e).__name__}: {e}): lancialo a mano")
    try:   # le voci scartate da archivia.py al giro prima (diario/quarantena.json, dal 25 ott 2026)
        with open(os.path.join(SITO, "diario", "quarantena.json"), encoding="utf-8") as f:
            voci_q = json.load(f).get("voci") or []
    except (OSError, ValueError):
        voci_q = []
    if voci_q:
        print(f"\nIN QUARANTENA: {len(voci_q)} voci scartate da archivia.py per errori, da correggere e rimettere in "
              "notizie.json o eventi.json (AGENTE.md, «La quarantena»):")
        for x in voci_q:
            q = str(x.get("quando", ""))
            print(f"- {x.get('tipo')} {x.get('id')}: {x.get('stato')} (dalle {q[11:16]} del {q[8:10]}/{q[5:7]}); "
                  f"errori: {' · '.join(str(e)[:160] for e in x.get('errori') or [])}")


if __name__ == "__main__":
    main()
