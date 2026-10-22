#!/usr/bin/env python3
"""La sentinella: ogni quarto d'ora controlla che il giro dell'agente, il sito e il canale Telegram stiano al passo,
e ripara da sola quello che può. Nata il 22 ott 2026: GitHub ha tenuto ferma in coda per 78 minuti la pubblicazione
del giro delle 19 (sul sito è arrivato alle 20:30) e il canale Telegram è rimasto muto dalle 16 alle 21 senza che
nessuno se ne accorgesse.

1. Pubblicazione ferma in coda da più di CODA_MAX minuti senza essere partita: la annulla e ne lancia un'altra, che
   prende tutte le notizie fino a quel momento.
2. Sito indietro: notizie.json del ramo main più nuovo di quello online da più di RITARDO_MAX minuti e nessuna
   pubblicazione in corso: ne lancia una.
3. Canale Telegram muto: dalle 8 alle 22, sul sito c'è una notizia più nuova dell'ultimo messaggio del canale, da più
   di TG_MAX minuti: lancia una pubblicazione con gli arretrati di Telegram.
4. Giro mancato: notizie.json non aggiornato da più di GIRO_MAX minuti (dalle 7:30 a mezzanotte). Lo può solo
   segnalare: l'agente gira sui server di Anthropic.
Se qualcosa non va la sentinella finisce in rosso e GitHub manda una mail al proprietario; quello che ha riparato da
sola resta scritto tra gli avvisi gialli.

Uso (su GitHub, con GH_TOKEN):  python3 strumenti/sentinella.py
      python3 strumenti/sentinella.py --prova     (dice cosa farebbe, senza annullare né lanciare niente)
"""
import argparse
import datetime as dt
import json
import os
import subprocess
import sys
import time
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from facebook import SITO, fuso, quando
from telegram import DALLE, ALLE, sul_canale

FLUSSO = "pubblica.yml"
CODA_MAX = 20       # minuti in coda senza partire
RITARDO_MAX = 25    # minuti di ritardo del sito rispetto a main
TG_MAX = 75         # minuti di silenzio del canale con una notizia nuova sul sito
GIRO_MAX = 80       # minuti dall'ultimo giro (uno all'ora)


def gh(*args):
    return subprocess.run(["gh", *args], check=True, capture_output=True, text=True).stdout


def iso(s):
    return dt.datetime.fromisoformat(s.replace("Z", "+00:00"))


def minuti(d):
    return int(d.total_seconds() // 60)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sito", default=os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    ap.add_argument("--prova", action="store_true")
    a = ap.parse_args()
    adesso = dt.datetime.now(fuso())
    problemi, riparati = [], []

    # 1. pubblicazioni in coda che non partono
    corse = json.loads(gh("run", "list", "--workflow", FLUSSO, "-L", "15", "--json", "databaseId,status,createdAt"))
    attive = []
    for c in corse:
        if c["status"] == "completed":
            continue
        lavori = json.loads(gh("run", "view", str(c["databaseId"]), "--json", "jobs"))["jobs"]
        partita = any(j.get("status") not in ("queued", "waiting", "pending", "requested") for j in lavori)
        attesa = adesso - iso(c["createdAt"])
        if not partita and attesa > dt.timedelta(minutes=CODA_MAX):
            riparati.append(f"la pubblicazione {c['databaseId']} era ferma in coda da {minuti(attesa)} minuti: annullata")
            if not a.prova:
                gh("run", "cancel", str(c["databaseId"]))
        else:
            attive.append(c)

    # 2. sito indietro rispetto a main
    with open(os.path.join(a.sito, "notizie.json"), encoding="utf-8") as f:
        su_main = json.load(f)
    with urllib.request.urlopen(f"{SITO}/notizie.json?sentinella={int(time.time())}", timeout=30) as r:
        online = json.load(r)
    a_main, a_sito = iso(su_main["aggiornato"]), iso(online["aggiornato"])
    lancia, recupera = False, False
    if a_main > a_sito and adesso - a_main > dt.timedelta(minutes=RITARDO_MAX):
        msg = f"il sito è fermo al giro delle {a_sito:%H:%M}, su main c'è quello delle {a_main:%H:%M}"
        if attive:
            problemi.append(msg + " (una pubblicazione è in corso)")
        else:
            riparati.append(msg + ": lanciata una pubblicazione")
            lancia = True

    # 3. canale Telegram muto mentre il sito va avanti
    if DALLE + 1 <= adesso.hour < ALLE:
        canale = sul_canale()
        if canale is None:
            problemi.append("non si legge l'anteprima del canale Telegram (t.me/s/notiziebenevento)")
        else:
            ids, _, ultimo = canale
            mancano = [n["id"] for n in online.get("notizie", [])
                       if len(str(n.get("pubblicato") or "")) > 10 and n["id"] not in ids
                       and (t := quando(n, adesso)) and ultimo < t <= adesso]
            if mancano and adesso - ultimo > dt.timedelta(minutes=TG_MAX):
                problemi.append(f"il canale Telegram è muto dalle {ultimo.astimezone(fuso()):%H:%M} e mancano "
                                f"{len(mancano)} notizie del sito ({', '.join(mancano[:3])}…)")
                lancia = recupera = not attive

    # 4. giro mancato
    if (adesso.hour, adesso.minute) >= (7, 30) and adesso - a_main > dt.timedelta(minutes=GIRO_MAX):
        problemi.append(f"nessun giro dell'agente da {minuti(adesso - a_main)} minuti (l'ultimo è delle {a_main:%H:%M})")

    if lancia and not a.prova:
        gh("workflow", "run", FLUSSO, "--ref", "main", "-f", f"telegram_recupera={1 if recupera else 0}")
    for m in riparati:
        print(f"::warning::Sentinella: {m}")
    for m in problemi:
        print(f"::error::Sentinella: {m}")
    if lancia:
        print(f"Sentinella: lanciata una pubblicazione{' con gli arretrati di Telegram' if recupera else ''}"
              f"{' (prova: in realtà no)' if a.prova else ''}")
    if not riparati and not problemi:
        print(f"Sentinella: tutto al passo (giro delle {a_main:%H:%M}, sito uguale)")
    if problemi:
        sys.exit(1)


if __name__ == "__main__":
    main()
