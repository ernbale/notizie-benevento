#!/usr/bin/env python3
"""Pubblica su Instagram (l'account aziendale collegato alla Pagina Facebook) le notizie più importanti, una alla volta.

Lo esegue GitHub dopo ogni pubblicazione del sito, come facebook.py, che ne è il modello:
- Al massimo una notizia ogni PAUSA_MINUTI e MAX_GIORNO al giorno, dalle 8 alle 21: su Instagram poche e buone.
- Sceglie la più importante tra le notizie delle ultime 12 ore non ancora uscite (stessa importanza di facebook.py).
- L'immagine è img/ig/<id>.jpg (1080×1350, la fa pagine.py): titolo grande e, se c'è, la foto illustrativa con la
  scritta che è fatta con l'intelligenza artificiale. Instagram la scarica dal sito, che deve essere già online.
- Cosa è già uscito lo legge da Instagram stesso (il link della notizia scritto nella didascalia).
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
from facebook import PAGINA, SITO, candidate, chiama, fuso   # stessa chiave, stessa scelta delle notizie

MAX_GIORNO = 8
PAUSA_MINUTI = 90
DALLE, ALLE = 8, 21


def didascalia(n):
    m = n["titolo"].strip()
    if n.get("sintesi"):
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
    luogo = re.sub(r"[^A-Za-zÀ-ÿ0-9]", "", (n.get("luogo") or "").title())
    if luogo and luogo.lower() != "benevento":
        tag.append("#" + luogo)
    return m + "\n\n" + " ".join(tag + ["#notizie"])


def gia_pubblicate(ig, token, adesso):
    r = chiama("GET", f"{ig}/media", token, {"fields": "caption,timestamp", "limit": 50})
    ids, oggi, ultimo = set(), 0, None
    for p in r.get("data", []):
        t = dt.datetime.strptime(p["timestamp"], "%Y-%m-%dT%H:%M:%S%z").astimezone(fuso())
        m = re.search(r"notiziebenevento\.it/notizia/([a-z0-9-]+)", p.get("caption") or "")
        if m:
            ids.add(m.group(1))
        oggi += t.date() == adesso.date()
        ultimo = max(ultimo, t) if ultimo else t
    return ids, oggi, ultimo


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
        for n in candidate(notizie, set(), adesso)[:3]:
            print(f"--- {SITO}/img/ig/{n['id']}.jpg\n{didascalia(n)}\n")
        return

    token = os.environ.get("FB_PAGE_TOKEN", "").strip()
    if not token:
        print("Instagram: nessuna chiave (segreto FB_PAGE_TOKEN), non pubblico niente")
        return
    if not DALLE <= adesso.hour < ALLE:
        print(f"Instagram: sono le {adesso:%H:%M}, si pubblica dalle {DALLE} alle {ALLE}")
        return
    pag = chiama("GET", "me", token, {"fields": "name,instagram_business_account{id,username}"})
    if pag.get("name") != PAGINA:
        raise RuntimeError(f"la chiave non è della Pagina «{PAGINA}»: non pubblico niente")
    ig = (pag.get("instagram_business_account") or {}).get("id")
    if not ig:
        print("Instagram: la Pagina non ha ancora un account Instagram collegato, non pubblico niente")
        return
    gia, oggi, ultimo = gia_pubblicate(ig, token, adesso)
    if oggi >= MAX_GIORNO:
        print(f"Instagram: già {oggi} post oggi, basta così")
        return
    if ultimo and adesso - ultimo < dt.timedelta(minutes=PAUSA_MINUTI):
        print(f"Instagram: l'ultimo post è delle {ultimo:%H:%M}, aspetto")
        return
    for n in candidate(notizie, gia, adesso):
        img = f"{SITO}/img/ig/{n['id']}.jpg"
        if not online(img):   # l'immagine si fa solo per le notizie recenti della prima pagina
            continue
        cont = chiama("POST", f"{ig}/media", token, {"image_url": img, "caption": didascalia(n)})["id"]
        for _ in range(12):   # Instagram scarica e prepara l'immagine: di solito pochi secondi
            if chiama("GET", cont, token, {"fields": "status_code"}).get("status_code") == "FINISHED":
                break
            time.sleep(5)
        chiama("POST", f"{ig}/media_publish", token, {"creation_id": cont})
        print(f"Instagram: pubblicata {n['id']} ({oggi + 1} oggi)")
        return
    print("Instagram: nessuna notizia nuova da pubblicare")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print("AVVISO Instagram:", e, file=sys.stderr)
        sys.exit(1)
