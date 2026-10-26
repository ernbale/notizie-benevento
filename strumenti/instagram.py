#!/usr/bin/env python3
"""Pubblica su Instagram (l'account aziendale collegato alla Pagina Facebook) le notizie più importanti, una alla volta.

Lo esegue GitHub dopo ogni pubblicazione del sito, come facebook.py, che ne è il modello:
- Le notizie dei comunicati arrivati per posta («subito», giro lampo) escono appena ci sono, senza pausa né tetto.
- Una notizia ogni PAUSA_MINUTI, senza tetto al giorno, dalle 6 fino al giro delle 22 compreso (come Facebook: 20
  minuti, scelta del proprietario il 26 ott 2026, «nessun tetto ma distanziati almeno ogni 15/20 minuti»; prima 25
  minuti e 35 al giorno, 50 e 20, all'inizio 90 minuti e 8).
- Sceglie la prima della classifica dei social (facebook.py, CLASSIFICA) tra quelle che valgono almeno SOGLIA_IG
  (4: le più importanti); i comunicati («subito») tutti.
- L'immagine è img/ig/<id>.jpg (1080×1350, la fa pagine.py): titolo grande e, se c'è, la foto illustrativa con la
  scritta che è fatta con l'intelligenza artificiale. Instagram la scarica dal sito, che deve essere già online.
- Cosa è già uscito lo legge da Instagram stesso (il link della notizia scritto nella didascalia).
- Dalle RIEPILOGO_DALLE, come ultimo post del giorno, il riepilogo della giornata («Il Sannio oggi»): un carosello con
  la copertina e le immagini delle notizie più importanti uscite oggi. La scelta e la copertina le fa pagine.py
  (img/ig/oggi.json), così sul sito c'è già tutto quando Instagram scarica le immagini. Dopo il riepilogo le notizie
  continuano a uscire.
- Alle 23 (il giro delle sere di allerta) solo la notizia di un'allerta arancione o rossa, come su Facebook e
  Telegram: è la più utile per chi ha figli a scuola. La gialla no.
- La chiave è la stessa della Pagina (segreto FB_PAGE_TOKEN), con i permessi instagram_basic e
  instagram_content_publish. Senza account Instagram collegato alla Pagina non fa niente.

- Quando Meta risponde «troppe richieste» (26 ott 2026, 15:17: 16 notizie arretrate insieme) non la si chiama per
  FERMO_MINUTI: lo ricorda --stato, poi si riprende da soli.

Uso:  FB_PAGE_TOKEN=… python3 strumenti/instagram.py --stato FILE
      python3 strumenti/instagram.py --prova      (dice cosa pubblicherebbe, senza chiave e senza toccare Instagram)
"""
import argparse
import datetime as dt
import json
import os
import re
import sys
import time
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from facebook import (AGG, LIMITE_META, PAGINA, RIEPILOGO_DALLE, RIEPILOGO_PAUSA, SITO, SOGLIA_IG,  # come Facebook
                      TITOLO_RIEPILOGO, allerta_seria, candidate, chiama, coda, fuso, quando, recenti, rilievo,
                      titoli_usciti, tutti_i_post)

PAUSA_MINUTI = 20
FERMO_MINUTI = 60   # quando Meta dice «troppe richieste» non la si chiama per un'ora (il suo conto è sull'ultima ora)
DALLE, ALLE = 6, 23   # come facebook.py
QUANTE, ALMENO = 5, 3  # notizie nel riepilogo; con meno di ALMENO notizie oggi niente riepilogo


def del_giorno(notizie, adesso):
    """Le notizie più importanti uscite oggi, per il riepilogo: il rilievo di facebook.py senza lo sconto per le ore
    passate (a pari rilievo la più recente). La usa pagine.py per la copertina."""
    out = []
    for n in notizie:
        t = quando(n, adesso)
        if t and t.astimezone(fuso()).date() == adesso.date() and t <= adesso:
            out.append((rilievo(n, adesso, adesso), t, n))
    out.sort(key=lambda x: (-x[0], -x[1].timestamp()))
    return [n for _, _, n in out[:QUANTE]]


def didascalia(n, aggiornamento=False):
    m = n["titolo"].strip()
    if aggiornamento:   # un aggiornamento che ha cambiato il titolo (facebook.aggiornate): la novità al posto della sintesi
        m = AGG + m + "\n\n" + n["articolo"]["aggiornamento"]["testo"].strip()
    elif n.get("sintesi"):
        m += "\n\n" + n["sintesi"].strip()
    fonti = [f.get("nome") for f in n.get("fonti") or [] if f.get("nome")]
    if n.get("stato") == "una_fonte" and fonti:
        m += f"\n\nPer ora lo riporta solo {fonti[0]}."
    elif n.get("stato") == "ufficiale":
        m += "\n\nFonte ufficiale."
    elif fonti:
        m += f"\n\n{len(fonti)} fonti confrontate: {', '.join(fonti[:6])}{' e altre.' if len(fonti) > 6 else '.'}"
    m += f"\n\nLeggi tutto su notiziebenevento.it (link nella bio):\n{SITO}/notizia/{n['id']}/"
    if n.get("foto_inviate"):   # le foto vere mandate col comunicato (pagine.immagini_ig_foto): niente IA
        piu = len(n["foto_inviate"]) > 1
        m += f"\n\n{'Le foto inviate' if piu else 'Foto inviata'} da {n.get('foto_da') or 'chi ha mandato il comunicato'}."
    elif n.get("immagine") and n.get("categoria") != "cronaca" and not n.get("locandina"):   # la locandina è vera
        m += "\n\nImmagine illustrativa creata con l'intelligenza artificiale: non è una foto del fatto."
    tag = ["#Benevento", "#Sannio"]
    for luogo in re.split(r"[,;/]| e ", n.get("luogo") or ""):   # «Napoli, Sannio» → #Napoli (#Sannio c'è già)
        t = "#" + re.sub(r"[^A-Za-zÀ-ÿ0-9]", "", luogo.title())
        if len(t) > 1 and t.lower() not in (x.lower() for x in tag):
            tag.append(t)
    return m + "\n\n" + " ".join(tag + ["#notizie"])


def didascalia_riepilogo(giorno, notizie):
    m = f"{TITOLO_RIEPILOGO}, {giorno}: le notizie più importanti della giornata.\n\n"
    m += "\n".join(f"{i}. {n['titolo'].strip()}" for i, n in enumerate(notizie, 1))
    m += "\n\nScorri le immagini. Leggi tutto su notiziebenevento.it (link nella bio)."
    if any(n.get("immagine") and n.get("categoria") != "cronaca" and not n.get("locandina") and not n.get("foto_inviate")
           for n in notizie):
        m += "\n\nLe immagini illustrative sono create con l'intelligenza artificiale: non sono foto dei fatti."
    return m + "\n\n#Benevento #Sannio #notizie"


def gia_pubblicate(ig, token, adesso):
    """Le notizie già uscite (id → titoli usciti), quante notizie oggi (il riepilogo, le chiusure, le curiosità e i gol
    non contano), l'ora dell'ultimo post (le curiosità e i gol non contano neanche qui), se il riepilogo di oggi c'è già
    e l'ora dell'ultimo post di ogni notizia (id → ora)."""
    ora_post = lambda p: dt.datetime.strptime(p["timestamp"], "%Y-%m-%dT%H:%M:%S%z").astimezone(fuso())
    post = tutti_i_post(f"{ig}/media", token, "caption,timestamp", adesso, ora_post)   # gli ultimi giorni, non 50 post
    ids, oggi, ultimo, riepilogo, uscite = {}, 0, None, False, {}
    for p in post:
        t = ora_post(p)
        m = re.search(r"notiziebenevento\.it/notizia/([a-z0-9-]+)", p.get("caption") or "")
        if m:
            titoli_usciti(ids, m.group(1), p.get("caption"))
            uscite[m.group(1)] = max(uscite.get(m.group(1), t), t)
        didascalia_ = p.get("caption") or ""
        if "#CuriositàDelSannio" in didascalia_:   # la curiosità delle 12 (curiosita_social.py) non conta tra le notizie
            continue
        if "#BeneventoCalcio" in didascalia_:   # i gol e i risultati del Benevento (gol.py, MARCA): non contano neanche loro
            continue
        oggi += t.date() == adesso.date() and not didascalia_.startswith((TITOLO_RIEPILOGO, "🚸"))
        riepilogo |= t.date() == adesso.date() and didascalia_.startswith(TITOLO_RIEPILOGO)
        ultimo = max(ultimo, t) if ultimo else t
    return ids, oggi, ultimo, riepilogo, uscite


def riepilogo_pronto(sito, notizie, adesso):
    """(giorno, notizie, indirizzi delle immagini) del riepilogo di oggi preparato da pagine.py, o None."""
    try:
        with open(os.path.join(sito, "img", "ig", "oggi.json"), encoding="utf-8") as f:
            r = json.load(f)
    except (OSError, ValueError):
        return None
    per_id = {n.get("id"): n for n in notizie}
    scelte = [per_id[i] for i in r.get("ids", []) if i in per_id]
    if r.get("data") != adesso.date().isoformat() or len(scelte) < ALMENO or len(scelte) != len(r["ids"]):
        return None
    return r["giorno"], scelte, [f"{SITO}/{r['copertina']}"] + [f"{SITO}/img/ig/{n['id']}.jpg" for n in scelte]


def aspetta(cont, token):
    for _ in range(12):   # Instagram scarica e prepara l'immagine: di solito pochi secondi
        if chiama("GET", cont, token, {"fields": "status_code"}).get("status_code") == "FINISHED":
            return
        time.sleep(5)


def pubblica_notizia(ig, token, n, aggiornamento=False):
    """Un post con l'immagine della notizia; False se l'immagine non è online (si fa solo per le notizie recenti
    della prima pagina). L'immagine ha il titolo di adesso: pagine.py la rifà quando il titolo cambia."""
    img = f"{SITO}/img/ig/{n['id']}.jpg"
    if not online(img):
        return False
    # con le foto mandate col comunicato un carosello: l'immagine della notizia e poi le foto, intere (fino a 10)
    foto = [] if aggiornamento else [f"{SITO}/img/ig/{n['id']}-foto-{k}.jpg" for k in range(1, len(n.get("foto_inviate") or []) + 1)][:9]
    foto = [u for u in foto if online(u)]
    if foto:
        figli = [chiama("POST", f"{ig}/media", token, {"image_url": u, "is_carousel_item": "true"})["id"] for u in [img] + foto]
        for c in figli:
            aspetta(c, token)
        cont = chiama("POST", f"{ig}/media", token, {"media_type": "CAROUSEL", "children": ",".join(figli),
                                                     "caption": didascalia(n, aggiornamento)})["id"]
    else:
        cont = chiama("POST", f"{ig}/media", token, {"image_url": img, "caption": didascalia(n, aggiornamento)})["id"]
    aspetta(cont, token)
    chiama("POST", f"{ig}/media_publish", token, {"creation_id": cont})
    return True


def pubblica_riepilogo(ig, token, giorno, scelte, immagini):
    figli = [chiama("POST", f"{ig}/media", token, {"image_url": u, "is_carousel_item": "true"})["id"] for u in immagini]
    for c in figli:
        aspetta(c, token)
    cont = chiama("POST", f"{ig}/media", token, {"media_type": "CAROUSEL", "children": ",".join(figli),
                                                 "caption": didascalia_riepilogo(giorno, scelte)})["id"]
    aspetta(cont, token)
    chiama("POST", f"{ig}/media_publish", token, {"creation_id": cont})


def online(url):
    try:
        with urllib.request.urlopen(urllib.request.Request(url, method="HEAD"), timeout=20) as r:
            return r.status == 200
    except Exception:
        return False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sito", default=os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    ap.add_argument("--prova", action="store_true")
    ap.add_argument("--stato", help="il file dove si ricorda se Meta ci ha fermato (lo conserva GitHub)")
    a = ap.parse_args()
    adesso = dt.datetime.now(fuso())
    with open(os.path.join(a.sito, "notizie.json"), encoding="utf-8") as f:
        notizie = json.load(f).get("notizie", [])

    if a.prova:
        for n, agg in coda(notizie, {}, adesso, SOGLIA_IG)[:3]:
            print(f"--- {SITO}/img/ig/{n['id']}.jpg\n{didascalia(n, agg)}\n")
        r = riepilogo_pronto(a.sito, notizie, adesso)
        print(f"--- riepilogo: {', '.join(r[2])}\n{didascalia_riepilogo(r[0], r[1])}" if r
              else "--- riepilogo: oggi non c'è (manca img/ig/oggi.json o poche notizie)")
        return

    token = os.environ.get("FB_PAGE_TOKEN", "").strip()
    if not token:
        print("Instagram: nessuna chiave (segreto FB_PAGE_TOKEN), non pubblico niente")
        return
    sera = adesso.hour == 23   # alle 23 solo le allerte arancioni o rosse, come Facebook e Telegram
    if not DALLE <= adesso.hour < ALLE and not sera:
        print(f"Instagram: sono le {adesso:%H:%M}, si pubblica dalle {DALLE} fino al giro delle {ALLE - 1}")
        return
    stato = leggi_stato(a.stato)
    if stato.get("fermo_fino", "") > adesso.isoformat():
        print(f"Instagram: Meta ci ha fermato per troppe richieste, riprendo dopo le {stato['fermo_fino'][11:16]}")
        return
    try:
        giro(a, notizie, adesso, token, sera)
    except RuntimeError as e:
        if not LIMITE_META.search(str(e)):
            raise
        fino = (adesso + dt.timedelta(minutes=FERMO_MINUTI)).isoformat(timespec="minutes")
        scrivi_stato(a.stato, dict(stato, fermo_fino=fino))
        print(f"Instagram: Meta dice che abbiamo fatto troppe richieste ({e}): fermo fino alle {fino[11:16]}, poi si "
              "riprende da soli")


def leggi_stato(percorso):
    try:
        with open(percorso, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError, TypeError):
        return {}


def scrivi_stato(percorso, stato):
    if percorso:
        os.makedirs(os.path.dirname(percorso) or ".", exist_ok=True)
        with open(percorso, "w", encoding="utf-8") as f:
            json.dump(stato, f)


def giro(a, notizie, adesso, token, sera):
    """Una volta: un comunicato «subito», o l'allerta delle 23, o il riepilogo della sera, o la notizia più importante."""
    pag = chiama("GET", "me", token, {"fields": "name,instagram_business_account{id,username}"})
    if pag.get("name") != PAGINA:
        raise RuntimeError(f"la chiave non è della Pagina «{PAGINA}»: non pubblico niente")
    ig = (pag.get("instagram_business_account") or {}).get("id")
    if not ig:
        print("Instagram: la Pagina non ha ancora un account Instagram collegato, non pubblico niente")
        return
    gia, oggi, ultimo, riepilogo, uscite = gia_pubblicate(ig, token, adesso)
    if not sera:   # un comunicato ufficiale (giro lampo, «subito»): esce adesso, senza pausa né tetto (come facebook.py)
        for n in candidate(notizie, gia, adesso):
            if n.get("subito") and pubblica_notizia(ig, token, n):
                print(f"Instagram: pubblicata subito {n['id']} (comunicato, {oggi + 1} oggi)")
                return
    if sera:
        for n in candidate(notizie, gia, adesso):
            if allerta_seria(n) and pubblica_notizia(ig, token, n):
                print(f"Instagram: pubblicata l'allerta {n['id']} ({oggi + 1} oggi)")
                return
        print("Instagram: sono le 23, a quest'ora si pubblicano solo le allerte arancioni o rosse")
        return
    if not riepilogo and adesso.hour >= RIEPILOGO_DALLE:
        r = riepilogo_pronto(a.sito, notizie, adesso)
        if r and ultimo and adesso - ultimo < dt.timedelta(minutes=RIEPILOGO_PAUSA):
            print(f"Instagram: l'ultimo post è delle {ultimo:%H:%M}, il riepilogo al prossimo giro")
            return
        if r and all(online(u) for u in r[2]):
            pubblica_riepilogo(ig, token, *r)
            print(f"Instagram: pubblicato il riepilogo della giornata ({len(r[1])} notizie, {oggi + 1} post oggi)")
            return
        print("Instagram: niente riepilogo oggi (poche notizie o immagini non ancora online)")
    if ultimo and adesso - ultimo < dt.timedelta(minutes=PAUSA_MINUTI):
        print(f"Instagram: l'ultimo post è delle {ultimo:%H:%M}, aspetto")
        return
    for n, agg in coda(notizie, gia, adesso, SOGLIA_IG, recenti(notizie, uscite, adesso)):
        if pubblica_notizia(ig, token, n, agg):
            cosa = "pubblicato l'aggiornamento di" if agg else "pubblicata"
            print(f"Instagram: {cosa} {n['id']} ({oggi + 1} oggi)")
            return
    print("Instagram: nessuna notizia nuova da pubblicare")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print("AVVISO Instagram:", e, file=sys.stderr)
        sys.exit(1)
