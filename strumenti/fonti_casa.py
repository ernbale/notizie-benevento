#!/usr/bin/env python3
"""Scarica dal K12 di casa le fonti di Notizie Benevento che dal cloud dell'agente non si aprono e le mette
nell'archivio privato ernbale/notizie-benevento-fonti, che l'agente trova accanto al suo.

- ANAS: i comunicati della Campania (escono più o meno una volta a settimana) più quelli della Campania nel feed
  nazionale, che ne tiene solo gli ultimi 10 di tutta Italia ma li ha appena escono.
- ASL Benevento: notizie e avvisi. Il sito ha il certificato incompleto (manca il pezzo intermedio di Actalis,
  che Chrome si procura da solo e i programmi no): lo si scarica una volta e si aggiunge.
- TV7 Benevento: il feed senza le notizie nazionali dell'agenzia AdnKronos, con il testo intero degli articoli.

ANAS e TV7 rifiutano le connessioni dall'estero (il cloud dell'agente, GitHub), da casa si aprono.

Gira ogni 30 minuti dal cron del K12, solo libreria standard di Python. Per ogni fonte tiene le voci degli ultimi
giorni, aggiunge le nuove e scrive l'esito della lettura; se una fonte non risponde lascia le voci vecchie e lo
scrive. Pubblica sempre un commit solo (riscritto ogni volta), così l'archivio resta piccolo.
La chiave per scrivere è una chiave di deploy valida solo per quell'archivio (~/.ssh/nb_fonti sul K12).

Uso sul K12:  python3 ~/nb-fonti/fonti_casa.py            (scarica e pubblica)
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

CARTELLA = os.path.expanduser("~/nb-fonti")
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


def fuso():
    try:
        from zoneinfo import ZoneInfo
        return ZoneInfo("Europe/Rome")
    except Exception:
        return dt.timezone(dt.timedelta(hours=1))


def scarica(url, ctx=None):
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


FONTI = {
    "anas": ("ANAS, comunicati della Campania", ANAS_LISTA, anas, 10),
    "asl": ("ASL Benevento, notizie e avvisi", ASL_LISTA, asl, 30),
    "tv7": ("TV7 Benevento (tvsette.net), feed con il testo degli articoli", TV7_FEED, tv7, 4),
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

Le scarica ogni 30 minuti il K12 di casa (`strumenti/fonti_casa.py` nell'archivio del sito), perché dal cloud
dell'agente non si aprono: ANAS e TV7 rifiutano le connessioni dall'estero, il sito dell'ASL ha il certificato
incompleto.

- `anas.json`: comunicati ANAS della Campania, ultimi 10 giorni (`data` senza ora, `compartimento` = ufficio ANAS).
- `asl.json`: notizie e avvisi dell'ASL Benevento, ultimi 30 giorni.
- `tv7.json`: articoli di TV7 Benevento con il testo, ultimi 4 giorni (TV7 copre anche Irpinia e Campania).

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
        git("config", "user.name", "K12 di casa")
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
