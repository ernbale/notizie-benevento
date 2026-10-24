#!/usr/bin/env python3
"""Pubblica su Instagram (l'account aziendale collegato alla Pagina Facebook) le notizie più importanti, una alla volta.

Lo esegue GitHub dopo ogni pubblicazione del sito, come facebook.py, che ne è il modello:
- Le notizie dei comunicati arrivati per posta («subito», giro lampo) escono appena ci sono, senza pausa né tetto.
- Al massimo una notizia ogni PAUSA_MINUTI e MAX_GIORNO al giorno, dalle 6 fino al giro delle 22 compreso
  (come Facebook: 25 minuti e 35 al giorno, scelta del proprietario il 24 ott 2026; prima 50 minuti e 20, all'inizio
  90 minuti e 8).
- Sceglie la più importante tra le notizie delle ultime 12 ore non ancora uscite (stessa importanza di facebook.py).
- L'immagine è img/ig/<id>.jpg (1080×1350, la fa pagine.py): titolo grande e, se c'è, la foto illustrativa con la
  scritta che è fatta con l'intelligenza artificiale. Instagram la scarica dal sito, che deve essere già online.
- Cosa è già uscito lo legge da Instagram stesso (il link della notizia scritto nella didascalia).
- Dalle RIEPILOGO_DALLE, come ultimo post del giorno, il riepilogo della giornata («Il Sannio oggi»): un carosello con
  la copertina e le immagini delle notizie più importanti uscite oggi. La scelta e la copertina le fa pagine.py
  (img/ig/oggi.json), così sul sito c'è già tutto quando Instagram scarica le immagini. È in più delle MAX_GIORNO
  notizie (scelta del proprietario, 23 ott 2026: «20 + riepilogo per entrambi»); il riepilogo e le chiusure non contano.
- Alle 23 (il giro delle sere di allerta) solo la notizia di un'allerta arancione o rossa, come su Facebook e
  Telegram, anche dopo il riepilogo e oltre MAX_GIORNO: è la più utile per chi ha figli a scuola. La gialla no.
- La chiave è la stessa della Pagina (segreto FB_PAGE_TOKEN), con i permessi instagram_basic e
  instagram_content_publish. Senza account Instagram collegato alla Pagina non fa niente.

Uso:  FB_PAGE_TOKEN=… python3 strumenti/instagram.py
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
from facebook import (AGG, PAGINA, RIEPILOGO_DALLE, RIEPILOGO_PAUSA, SITO, TITOLO_RIEPILOGO,  # come Facebook
                      allerta_seria, candidate, chiama, coda, fuso, quando, rilievo, titoli_usciti)

MAX_GIORNO = 35
PAUSA_MINUTI = 25
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
    if n.get("immagine") and n.get("categoria") != "cronaca":
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
    if any(n.get("immagine") and n.get("categoria") != "cronaca" for n in notizie):
        m += "\n\nLe immagini illustrative sono create con l'intelligenza artificiale: non sono foto dei fatti."
    return m + "\n\n#Benevento #Sannio #notizie"


def gia_pubblicate(ig, token, adesso):
    """Le notizie già uscite (id → titoli usciti), quante notizie oggi (il riepilogo, le chiusure e le curiosità non
    contano), l'ora dell'ultimo post (le curiosità non contano neanche qui) e se il riepilogo di oggi c'è già."""
    r = chiama("GET", f"{ig}/media", token, {"fields": "caption,timestamp", "limit": 50})
    ids, oggi, ultimo, riepilogo = {}, 0, None, False
    for p in r.get("data", []):
        t = dt.datetime.strptime(p["timestamp"], "%Y-%m-%dT%H:%M:%S%z").astimezone(fuso())
        m = re.search(r"notiziebenevento\.it/notizia/([a-z0-9-]+)", p.get("caption") or "")
        if m:
            titoli_usciti(ids, m.group(1), p.get("caption"))
        didascalia_ = p.get("caption") or ""
        if "#CuriositàDelSannio" in didascalia_:   # la curiosità delle 12 (curiosita_social.py) non conta tra le notizie
            continue
        oggi += t.date() == adesso.date() and not didascalia_.startswith((TITOLO_RIEPILOGO, "🚸"))
        riepilogo |= t.date() == adesso.date() and didascalia_.startswith(TITOLO_RIEPILOGO)
        ultimo = max(ultimo, t) if ultimo else t
    return ids, oggi, ultimo, riepilogo


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
    a = ap.parse_args()
    adesso = dt.datetime.now(fuso())
    with open(os.path.join(a.sito, "notizie.json"), encoding="utf-8") as f:
        notizie = json.load(f).get("notizie", [])

    if a.prova:
        for n, agg in coda(notizie, {}, adesso)[:3]:
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
    pag = chiama("GET", "me", token, {"fields": "name,instagram_business_account{id,username}"})
    if pag.get("name") != PAGINA:
        raise RuntimeError(f"la chiave non è della Pagina «{PAGINA}»: non pubblico niente")
    ig = (pag.get("instagram_business_account") or {}).get("id")
    if not ig:
        print("Instagram: la Pagina non ha ancora un account Instagram collegato, non pubblico niente")
        return
    gia, oggi, ultimo, riepilogo = gia_pubblicate(ig, token, adesso)
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
    if riepilogo:
        print("Instagram: il riepilogo di oggi è già uscito, a domani")
        return
    if adesso.hour >= RIEPILOGO_DALLE:
        r = riepilogo_pronto(a.sito, notizie, adesso)
        if r and ultimo and adesso - ultimo < dt.timedelta(minutes=RIEPILOGO_PAUSA):
            print(f"Instagram: l'ultimo post è delle {ultimo:%H:%M}, il riepilogo al prossimo giro")
            return
        if r and all(online(u) for u in r[2]):
            pubblica_riepilogo(ig, token, *r)
            print(f"Instagram: pubblicato il riepilogo della giornata ({len(r[1])} notizie, {oggi + 1} post oggi)")
            return
        print("Instagram: niente riepilogo oggi (poche notizie o immagini non ancora online)")
    if oggi >= MAX_GIORNO:
        print(f"Instagram: già {oggi} notizie oggi (il massimo è {MAX_GIORNO}, più il riepilogo), basta così")
        return
    if ultimo and adesso - ultimo < dt.timedelta(minutes=PAUSA_MINUTI):
        print(f"Instagram: l'ultimo post è delle {ultimo:%H:%M}, aspetto")
        return
    for n, agg in coda(notizie, gia, adesso):
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
