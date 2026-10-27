#!/usr/bin/env python3
"""Le fonti ufficiali dal Pi ogni 5 minuti: appena una società sportiva, il Comune di Benevento, la Provincia, l'ASL,
l'acqua (Alto Calore, GESESA) o i trasporti (EAV, AIR) pubblicano qualcosa sul loro sito, l'articolo va al giro lampo
come un comunicato arrivato per posta (COMUNICATI.md del sito, strumenti/comunicati.py).

Voluto dal proprietario il 25 ott 2026 («dobbiamo recuperare qualche minuto, dobbiamo arrivare prima»): la Miwa Basket
aveva messo la vittoria di Ragusa sul suo sito alle 21:01 e noi l'abbiamo pubblicata alle 21:09 solo perché il giro di
ogni ora partiva alle 21:06; con l'articolo uscito alle 21:07 saremmo usciti alle 22:09, un'ora dopo NTR24 Sport. Prima
di questo programma i siti ufficiali li leggeva solo il giro di ogni ora: da 0 a 60 minuti di ritardo.

Il cron lo lancia ogni 5 minuti; poi comunicati_lampo.py fa partire il giro lampo per le voci nuove (lì anche la regola
che le tiene ferme mentre lavora il giro di ogni ora, per non fare doppioni). Qui:
- legge i feed delle FONTI (le società sportive sono quelle ufficiali di giornali.py, UFFICIALI) e i file dell'ASL,
  dell'ANAS e della Regione che fonti_casa.py aggiorna ogni 30 minuti;
- per le fonti di tutta la Campania (ANAS, Regione, EAV, AIR, Alto Calore) tiene solo quello che nomina un Comune della
  provincia, Benevento o il Sannio;
- un articolo è nuovo se il suo link non si è mai visto e se è uscito da meno di ORE_NUOVO ore (o oggi o ieri, per le
  fonti che danno solo il giorno): un articolo vecchio ritoccato o tornato in cima al feed non riparte;
- la prima volta che vede una fonte prende solo nota di quello che c'è: le cose vecchie non sono nuove;
- le voci nuove vanno in ufficiali.json dell'archivio privato notizie-benevento-fonti, che pubblica subito (col
  lucchetto di fonti_casa.py, come la vedetta): ci sono `id` («u» e 11 caratteri, nello stesso elenco degli id dei
  comunicati per posta: comunicati_visti.json del sito), `tipo` = «sito», `titolo`, `link` (da citare), `data` (quando
  è uscito), `arrivata` (quando l'ha visto il Pi), `mittente` (la fonte), `dominio`, `testo` (quello del feed).
Scrive nel registro (ufficiali.log) solo quando trova qualcosa o qualcosa non va. Stato in ufficiali_visti.json.

Dal 27 ott 2026 il Benevento Calcio ogni minuto (lui: «i comunicati stampa del Benevento Calcio … da pubblicare
istantaneamente, priorità max»): un giro con --solo «Benevento Calcio» legge solo la sua pagina delle notizie (una
richiesta al minuto; gli articoli si aprono solo quando sono nuovi) e, se trova qualcosa, il cron fa partire subito il
giro lampo. Tutti e due i giri usano lo stesso lucchetto (/tmp/nb_ufficiali.lock) e lo stesso stato: un articolo si
trova una volta sola. Il giro con --solo non tocca l'esito delle altre fonti in ufficiali.json: aggiunge solo le voci.

Uso sul Pi:  python3 ~/nb-fonti/sentinella/ufficiali.py            (dal cron, ogni 5 minuti)
             python3 ~/nb-fonti/sentinella/ufficiali.py --solo "Benevento Calcio"   (dal cron, ogni minuto)
             python3 ~/nb-fonti/sentinella/ufficiali.py --prova    (legge e dice cosa è nuovo, senza scrivere)
             python3 ~/nb-fonti/sentinella/ufficiali.py --prova --tutte   (tutto quello delle ultime ore che passerebbe)
"""
import argparse
import contextlib
import datetime as dt
import fcntl
import hashlib
import json
import os
import re
import sys
import time
import urllib.parse
from concurrent.futures import ThreadPoolExecutor

QUI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, QUI)
import vedetta as V   # noqa: E402  (archivio, lucchetto, fonti_casa e giornali: tutto come la vedetta)

F, G = V.F, V.G
STATO = os.path.join(V.CARTELLA, "ufficiali_visti.json")
ARCHIVIO_FILE = os.path.join(F.ARCHIVIO, "ufficiali.json")
ORE_NUOVO = 6        # un articolo uscito da più ore non è nuovo
GIORNI_TIENI = 3     # quanto restano le voci in ufficiali.json
GIORNI_VISTI = 30    # quanto si ricordano i link visti
TESTO_MAX = 6000
APRI_MAX = 6         # articoli del Benevento Calcio aperti al massimo per giro (per la data)
GESESA = "https://www.gesesa.a-acqua.it/news/_jcr_content/root/avvisi_news_copy.jsonsearchmedia.json"
# Il lucchetto di comunicati_lampo.py: mentre qui si scrivono le voci nuove e si pubblica l'archivio, il giro lampo non
# parte (partirebbe con l'archivio non ancora su GitHub e non troverebbe le voci)
LUCCHETTO_LAMPO = "/tmp/nb_comunicati.lock"

# (nome della fonte, come si legge, indirizzo, solo quello che riguarda il Sannio). Il nome è quello da citare tra le
# fonti. ⛔ FIPAV (pallavolo): i suoi siti vietano la lettura automatica. La LND (dilettanti) no: i suoi comunicati
# ufficiali sono bollettini settimanali di risultati e squalifiche, li guarda il giro di ogni ora.
ENTI = [
    ("Comune di Benevento", "rss", "https://comune.benevento.it/tipi_notizia/comunicati/feed/", False),
    ("Provincia di Benevento", "rss", "https://www.provincia.benevento.it/rss.xml", False),
    ("Comune di San Marco dei Cavoti", "rss", "https://www.comune.sanmarcodeicavoti.bn.it/feed/", False),
    ("Alto Calore Servizi", "rss", "https://altocalore.it/avvisi/feed/", True),
    ("Alto Calore Servizi", "rss", "https://altocalore.it/category/comunicati/feed/", True),
    ("GESESA", "gesesa", GESESA, False),
    ("EAV", "rss", "https://www.eavsrl.it/feed/", True),
    ("AIR Campania", "rss", "https://aircampania.it/feed/", True),
    ("ASL Benevento", "casa", "asl.json", False),
    ("ANAS", "casa", "anas.json", True),
    ("Regione Campania", "casa", "regione.json", True),
]
SPORT = [(nome, tipo, url, tipo == "wp-sannio") for nome, _, tipo, url, _ in G.TESTATE
         if nome in G.UFFICIALI and nome != "LND Benevento"]
FONTI = SPORT + ENTI

# Il Sannio: i 78 Comuni, Benevento, Sannio, Valle Caudina e Telesina, Fortore. «Ponte» da solo è una parola comune:
# vale solo come «Ponte (BN)» o «Comune di Ponte».
_NOMI = sorted((re.escape(c) for c in V.COMUNI_BN if c != "Ponte"), key=len, reverse=True)
SANNIO = re.compile(r"\b(?:" + "|".join(_NOMI) + r")\b|benevent|sanni[ot]|caudin|telesin|fortor|"
                    r"\bPonte\s*\(BN\)|\bcomune di ponte\b", re.I)
MESI = {m: i for i, m in enumerate(F.MESI, 1)}


def id_voce(link):
    return "u" + hashlib.sha1(G.norma_url(link).encode("utf-8")).hexdigest()[:11]


def data_italiana(s):
    """«01 ottobre 2026» → la data (GESESA scrive così)."""
    m = re.match(r"\s*(\d{1,2})\s+([a-zà]+)\s+(\d{4})", str(s or "").lower())
    if not m or m[2] not in MESI:
        return None
    try:
        return dt.date(int(m[3]), MESI[m[2]], int(m[1]))
    except ValueError:
        return None


def voci_feed(testo):
    """Le voci di un feed RSS con il testo (content:encoded se c'è, se no la descrizione)."""
    out = []
    for it in re.findall(r"<item\b.*?</item>", testo, re.S | re.I):
        ti = re.search(r"<title>(.*?)</title>", it, re.S | re.I)
        li = re.search(r"<link>(.*?)</link>", it, re.S | re.I)
        da = re.search(r"<pubDate>(.*?)</pubDate>", it, re.S | re.I) or re.search(r"<dc:date>(.*?)</dc:date>", it, re.S)
        co = re.search(r"<content:encoded>(.*?)</content:encoded>", it, re.S | re.I) or \
            re.search(r"<description>(.*?)</description>", it, re.S | re.I)
        if ti and li:
            out.append({"titolo": G.pulisci(ti[1]), "link": G.pulisci(li[1]),
                        "data": G.data_rss(G.pulisci(da[1]) if da else ""), "testo": G.pulisci(co[1] if co else "")})
    return out


def voci_numerate(tipo, url, visti, prima_volta):
    """Il sito del Benevento Calcio non ha un feed: i link della pagina delle notizie (giornali.NUMERATI); la data si
    legge aprendo l'articolo, e si aprono solo quelli mai visti (al massimo APRI_MAX per giro)."""
    base, schema = G.NUMERATI[tipo]
    trovati = {}
    for m in re.finditer(schema, G.scarica(url), re.S):
        tit = G.pulisci(m[3])
        if tit.lower() in ("leggi", "leggi tutto", "continua"):
            tit = ""
        prima = trovati.get(m[1])
        trovati[m[1]] = (tit if not prima or len(tit) > len(prima[0]) else prima[0], int(m[2]))
    voci, aperti = [], 0
    for h, (tit, _) in sorted(trovati.items(), key=lambda x: -x[1][1])[:40]:
        u = base + h
        v = {"titolo": tit or h, "link": u, "data": None, "testo": ""}
        if not prima_volta and G.norma_url(u) not in visti:
            if aperti >= APRI_MAX:
                v["da_aprire"] = True   # al giro dopo: non si segna come visto
            else:
                aperti += 1
                # un link mai visto nella pagina delle notizie è appena comparso: senza la data scritta, vale adesso
                v["data"] = G.data_pagina(u) or V.adesso_roma()
        voci.append(v)
    return voci


def leggi_fonte(fonte, visti=None, prima_volta=False):
    """Le voci di una fonte: [{titolo, link, data (datetime con fuso, o date se la fonte dà solo il giorno), testo}]."""
    nome, tipo, url, _ = fonte
    if tipo == "casa":
        with open(os.path.join(F.ARCHIVIO, url), encoding="utf-8") as f:
            d = json.load(f)
        if not str(d.get("esito") or "").startswith("letta"):
            raise RuntimeError(f"{url}: {str(d.get('esito'))[:80]}")
        out = []
        for v in d.get("voci") or []:
            s = str(v.get("data") or "")
            data = G.data_rss(s) if len(s) > 10 else (dt.date.fromisoformat(s) if re.match(r"\d{4}-\d\d-\d\d$", s) else None)
            out.append({"titolo": v.get("titolo", ""), "link": v.get("link", ""), "data": data, "testo": v.get("testo", "")})
        return out
    if tipo == "gesesa":
        d = json.loads(G.scarica(url))
        return [{"titolo": x.get("title", ""), "link": urllib.parse.urljoin(url, x.get("link") or ""),
                 "data": data_italiana(x.get("mediaDate")),
                 "testo": (x.get("title") or "") + (". Comuni: " + ", ".join(t.get("label", "") for t in x["tags"])
                                                     if isinstance(x.get("tags"), list) else "")}
                for x in d.get("results") or [] if x.get("link")]
    if tipo in G.NUMERATI:
        return voci_numerate(tipo, url, visti or {}, prima_volta)
    voci = voci_feed(G.scarica(url))
    if tipo == "wp-benevento":
        voci = [v for v in voci if "/benevento/" in v["link"]]
    return voci


def recente(data, adesso):
    if isinstance(data, dt.datetime):
        return adesso - dt.timedelta(hours=ORE_NUOVO) <= data <= adesso + dt.timedelta(minutes=10)
    if isinstance(data, dt.date):
        return data >= adesso.date() - dt.timedelta(days=1)
    return False


def del_sannio(v):
    return bool(SANNIO.search(v["titolo"] + " " + v["testo"][:2000]))


def chiave(fonte):
    return f"{fonte[0]}|{fonte[2]}"


def giro(adesso, tutte=False, fonti=None):
    fonti = FONTI if fonti is None else fonti
    stato = V.leggi(STATO, None) or {"fonti": [], "visti": {}}
    if tutte:   # --prova --tutte: come se tutte le fonti fossero già note e nessun link visto
        stato = {"fonti": [chiave(fo) for fo in fonti], "visti": {}}
    visti, iniziate = stato.setdefault("visti", {}), set(stato.setdefault("fonti", []))
    with ThreadPoolExecutor(8) as ex:
        letture = list(ex.map(lambda fo: (fo, *_prova(leggi_fonte, fo, visti, chiave(fo) not in iniziate)), fonti))
    nuove, lette, non_lette, prime = [], [], [], []
    for fonte, voci, errore in letture:
        nome, tipo, url, solo_sannio = fonte
        if errore:
            non_lette.append(f"{nome} ({errore[:60]})")
            continue
        lette.append(nome)
        prima_volta = chiave(fonte) not in iniziate
        for v in voci:
            k = G.norma_url(v["link"])
            if not k or k in visti or v.get("da_aprire"):
                continue
            visti[k] = adesso.isoformat(timespec="minutes")
            if prima_volta or not recente(v["data"], adesso) or (solo_sannio and not del_sannio(v)):
                continue
            data = v["data"].astimezone(F.fuso()).isoformat(timespec="minutes") \
                if isinstance(v["data"], dt.datetime) else v["data"].isoformat()
            nuove.append({"id": id_voce(v["link"]), "tipo": "sito", "titolo": v["titolo"][:300], "link": v["link"],
                          "data": data, "arrivata": adesso.isoformat(timespec="minutes"), "mittente": nome,
                          "dominio": urllib.parse.urlparse(v["link"]).hostname or "", "testo": v["testo"][:TESTO_MAX]})
        if prima_volta:
            iniziate.add(chiave(fonte))
            prime.append(nome)
    limite = (adesso - dt.timedelta(days=GIORNI_VISTI)).isoformat()
    stato["visti"] = {k: q for k, q in visti.items() if q >= limite}
    stato["fonti"] = sorted(iniziate)
    return stato, nuove, lette, non_lette, prime


@contextlib.contextmanager
def lucchetto(percorso, attesa=240):
    with open(percorso, "a") as l:
        fine = time.time() + attesa
        while True:
            try:
                fcntl.flock(l, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.time() > fine:
                    raise RuntimeError(f"{percorso} occupato da più di {attesa} secondi")
                time.sleep(2)
        try:
            yield
        finally:
            fcntl.flock(l, fcntl.LOCK_UN)


def _prova(f, *a):
    try:
        return f(*a), None
    except Exception as e:
        return [], f"{type(e).__name__}: {e}"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--prova", action="store_true", help="legge e dice cosa è nuovo, senza scrivere né pubblicare")
    ap.add_argument("--tutte", action="store_true", help="con --prova: tutto quello delle ultime ORE_NUOVO ore che "
                    "passerebbe, come se nessun link fosse mai stato visto")
    ap.add_argument("--solo", metavar="NOME", help="solo le fonti col nome che contiene NOME (es. «Benevento Calcio»)")
    a = ap.parse_args()
    if a.tutte and not a.prova:
        ap.error("--tutte solo con --prova")
    fonti = [fo for fo in FONTI if a.solo.lower() in fo[0].lower()] if a.solo else FONTI
    if not fonti:
        ap.error(f"nessuna fonte col nome «{a.solo}»")
    adesso = V.adesso_roma()
    ora = f"{adesso:%d/%m %H:%M}"
    stato, nuove, lette, non_lette, prime = giro(adesso, a.tutte, fonti)
    if a.prova:
        print(f"{ora} PROVA: lette {len(lette)} fonti su {len(FONTI)}"
              + (f"; non lette: {'; '.join(non_lette)}" if non_lette else "")
              + (f"; prima volta (solo presa nota): {', '.join(prime)}" if prime else ""))
        for v in nuove:
            print(f"  NUOVA {v['id']} · {v['mittente']} · {v['data']} · {v['titolo'][:90]}\n        {v['link']}")
        return
    if a.solo:   # il giro di un minuto: solo le voci nuove; l'esito delle fonti resta quello del giro di 5 minuti
        if non_lette and adesso.minute % 15 == 0:   # se il sito è giù, una riga ogni quarto d'ora, non ogni minuto
            print(f"{ora} {a.solo}: non letta ({'; '.join(non_lette)[:200]})")
        if not nuove:
            V.scrivi(STATO, stato)
            return
        with lucchetto(LUCCHETTO_LAMPO):
            vecchio = V.leggi(ARCHIVIO_FILE, {}) or {}
            limite = (adesso - dt.timedelta(days=GIORNI_TIENI)).isoformat()
            ids = {v["id"] for v in nuove}
            voci = nuove + [v for v in vecchio.get("voci") or [] if v.get("id") not in ids and str(v.get("arrivata")) >= limite]
            V.scrivi(ARCHIVIO_FILE, dict(vecchio, voci=voci))
            try:
                V.pubblica_archivio(adesso)
            except Exception as e:   # come nel giro di 5 minuti: le voci nuove si riprovano al giro dopo
                V.scrivi(ARCHIVIO_FILE, vecchio)
                print(f"{ora} ERRORE ({a.solo}): archivio non pubblicato ({type(e).__name__}: {e}): riprovo")
                sys.exit(1)
            print(f"{ora} {len(nuove)} nuove, archivio pubblicato: "
                  + "; ".join(f"{v['id']} {v['mittente']} «{v['titolo'][:60]}»" for v in nuove))
            V.scrivi(STATO, stato)
        return
    with lucchetto(LUCCHETTO_LAMPO):
        scrivi_e_pubblica(adesso, ora, stato, nuove, lette, non_lette, prime)


def scrivi_e_pubblica(adesso, ora, stato, nuove, lette, non_lette, prime):
    vecchio = V.leggi(ARCHIVIO_FILE, {}) or {}
    limite = (adesso - dt.timedelta(days=GIORNI_TIENI)).isoformat()
    ids = {v["id"] for v in nuove}
    voci = nuove + [v for v in vecchio.get("voci") or [] if v.get("id") not in ids and str(v.get("arrivata")) >= limite]
    riuscita = len(lette) * 2 >= len(FONTI)
    dati = {"fonte": "Siti delle fonti ufficiali (società sportive, Comune e Provincia di Benevento, ASL, acqua, "
                     "trasporti), letti dal Pi ogni 5 minuti",
            "indirizzo": "", "controllato": adesso.isoformat(timespec="minutes"),
            "esito": (f"letta: {len(lette)} fonti su {len(FONTI)}" if riuscita
                      else f"non raggiungibile: lette solo {len(lette)} fonti su {len(FONTI)}"),
            "ultima_lettura_riuscita": adesso.isoformat(timespec="minutes") if riuscita
            else vecchio.get("ultima_lettura_riuscita", ""),
            "fonti_non_lette": non_lette, "voci": voci}
    V.scrivi(ARCHIVIO_FILE, dati)
    if nuove:
        try:
            V.pubblica_archivio(adesso)
        except Exception as e:   # il giro lampo legge l'archivio pubblicato: senza, le voci nuove si riprovano dopo
            V.scrivi(ARCHIVIO_FILE, dict(dati, voci=voci[len(nuove):]))
            print(f"{ora} ERRORE: archivio non pubblicato ({type(e).__name__}: {e}): {len(nuove)} nuove riprovate "
                  "al giro dopo")
            sys.exit(1)
        print(f"{ora} {len(nuove)} nuove, archivio pubblicato: "
              + "; ".join(f"{v['id']} {v['mittente']} «{v['titolo'][:60]}»" for v in nuove))
    V.scrivi(STATO, stato)   # i link visti si segnano solo adesso: se qualcosa va storto prima, si riprovano
    if prime:
        print(f"{ora} prima volta, solo presa nota: {', '.join(prime)}")
    if not riuscita:
        print(f"{ora} ATTENZIONE: lette solo {len(lette)} fonti su {len(FONTI)}: {'; '.join(non_lette)[:400]}")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"{dt.datetime.now():%d/%m %H:%M} ERRORE: {type(e).__name__}: {e}")
        sys.exit(1)
