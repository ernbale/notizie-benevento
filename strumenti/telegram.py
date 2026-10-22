#!/usr/bin/env python3
"""Pubblica sul canale Telegram (t.me/notiziebenevento) le notizie nuove e gli aggiornamenti, appena escono sul sito.

Lo esegue GitHub dopo ogni pubblicazione del sito, come facebook.py. Su Telegram si legge tutto di seguito, come un
notiziario: qui niente pausa di un'ora come su Facebook, ma al massimo POR_GIRO messaggi per volta e MAX_GIORNO al
giorno, solo dalle 7 alle 22 (alle 23 solo le allerte importanti, come su Facebook).
- Notizia nuova: titolo, riassunto, link (Telegram mostra l'anteprima con l'immagine della notizia).
- Aggiornamento (il riquadro «Aggiornamento» dell'articolo): «Aggiornamento» + titolo + la frase della novità.
- Il bot non può rileggere il canale: cosa è già uscito lo ricorda in un file (--stato) che GitHub conserva tra
  una pubblicazione e l'altra (cache). Se il file non c'è (la prima volta, o GitHub l'ha perso) segna come già
  uscito tutto quello che c'è e non pubblica niente: meglio una notizia in meno che dieci doppioni.
- La chiave del bot è nel segreto TELEGRAM_TOKEN di GitHub; senza chiave non fa niente. Nei log mai la chiave.

Uso:  TELEGRAM_TOKEN=… python3 strumenti/telegram.py --stato /percorso/telegram.json
      python3 strumenti/telegram.py --prova      (dice cosa pubblicherebbe, senza chiave e senza toccare Telegram)
"""
import argparse
import datetime as dt
import html
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from facebook import SITO, fuso, quando   # stessa ora delle notizie di facebook.py

CANALE = "@notiziebenevento"
TITOLO_CANALE = "Notizie Benevento"
API = "https://api.telegram.org"
POR_GIRO = 6
MAX_GIORNO = 40
ORE_FINESTRA = 6            # notizie e aggiornamenti più vecchi di così non si mandano più
DALLE, ALLE = 7, 22
GIORNI_STATO = 4            # quanto si ricorda di cosa è già uscito


def chiama(token, metodo, dati=None):
    req = urllib.request.Request(f"{API}/bot{token}/{metodo}", data=json.dumps(dati or {}).encode(),
                                 headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.load(r)["result"]
    except urllib.error.HTTPError as e:
        try:
            msg = json.load(e).get("description", "")
        except ValueError:
            msg = ""
        raise RuntimeError(f"Telegram {e.code}: {msg}") from None   # l'indirizzo con la chiave non si stampa mai


def da_mandare(notizie, gia, adesso):
    """Le notizie nuove e gli aggiornamenti delle ultime ORE_FINESTRA ore non ancora sul canale, dal più vecchio."""
    out = []
    for n in notizie:
        t = quando(n, adesso)
        if t and n.get("id") not in gia and t <= adesso and adesso - t <= dt.timedelta(hours=ORE_FINESTRA):
            out.append((t, n["id"], "nuova", n))
        ag = (n.get("articolo") or {}).get("aggiornamento") or {}
        if ag.get("quando") and str(ag.get("testo") or "").strip():
            try:
                ta = dt.datetime.fromisoformat(ag["quando"])
            except ValueError:
                continue
            chiave = f"{n['id']}@{ag['quando']}"
            if chiave not in gia and n.get("id") in gia and ta <= adesso and adesso - ta <= dt.timedelta(hours=ORE_FINESTRA):
                out.append((ta, chiave, "aggiornamento", n))
    return sorted(out, key=lambda x: x[0])


def testo(tipo, n):
    e = lambda s: html.escape(str(s or "").strip(), quote=False)
    link = f"{SITO}/notizia/{n['id']}/"
    if tipo == "aggiornamento":
        ag = n["articolo"]["aggiornamento"]
        return f"🔴 <b>Aggiornamento</b> · {e(n['titolo'])}\n\n{e(ag['testo'])}\n\n{link}"
    m = f"<b>{e(n['titolo'])}</b>"
    if n.get("sintesi"):
        m += f"\n\n{e(n['sintesi'])}"
    if n.get("stato") == "una_fonte" and n.get("fonti"):
        m += f"\n\n<i>Per ora lo riporta solo {e(n['fonti'][0].get('nome'))}.</i>"
    return m + f"\n\n{link}"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sito", default=os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    ap.add_argument("--stato", default=os.path.join(os.environ.get("RUNNER_TEMP", "/tmp"), "telegram.json"))
    ap.add_argument("--prova", action="store_true")
    a = ap.parse_args()
    adesso = dt.datetime.now(fuso())
    with open(os.path.join(a.sito, "notizie.json"), encoding="utf-8") as f:
        notizie = json.load(f).get("notizie", [])

    if a.prova:
        for _, chiave, tipo, n in da_mandare(notizie, set(), adesso)[:POR_GIRO]:
            print(f"--- {chiave}\n{testo(tipo, n)}\n")
        return

    token = os.environ.get("TELEGRAM_TOKEN", "").strip()
    if not token:
        print("Telegram: nessuna chiave (segreto TELEGRAM_TOKEN), non pubblico niente")
        return
    # il bot deve scrivere solo sul canale Notizie Benevento
    chat = chiama(token, "getChat", {"chat_id": CANALE})
    if chat.get("title") != TITOLO_CANALE or chat.get("type") != "channel":
        raise RuntimeError(f"{CANALE} non è il canale «{TITOLO_CANALE}»: non pubblico niente")

    try:
        with open(a.stato, encoding="utf-8") as f:
            stato = json.load(f)
    except (OSError, ValueError):
        stato = None
    if stato is None:   # prima volta (o ricordo perso): segno tutto come già uscito
        gia = {n["id"] for n in notizie}
        gia |= {f"{n['id']}@{((n.get('articolo') or {}).get('aggiornamento') or {}).get('quando')}" for n in notizie}
        stato = {"mandati": {k: adesso.isoformat(timespec="minutes") for k in gia}}
        print(f"Telegram: nessun ricordo di cosa è già uscito, segno come già mandate {len(notizie)} notizie e riparto da qui")
    else:
        sera = adesso.hour == 23
        if not DALLE <= adesso.hour < ALLE and not sera:
            print(f"Telegram: sono le {adesso:%H:%M}, si pubblica dalle {DALLE} alle {ALLE}")
        else:
            gia = set(stato.get("mandati", {}))
            oggi = sum(1 for v in stato["mandati"].values() if v[:10] == adesso.date().isoformat())
            lista = da_mandare(notizie, gia, adesso)
            if sera:
                lista = [x for x in lista if x[3].get("categoria") == "meteo" and x[3].get("rilevante")]
            fatte = 0
            for _, chiave, tipo, n in lista[:max(0, min(POR_GIRO, MAX_GIORNO - oggi))]:
                chiama(token, "sendMessage", {"chat_id": CANALE, "text": testo(tipo, n), "parse_mode": "HTML",
                                              "link_preview_options": {"url": f"{SITO}/notizia/{n['id']}/",
                                                                       "prefer_large_media": True}})
                stato["mandati"][chiave] = adesso.isoformat(timespec="minutes")
                fatte += 1
                print(f"Telegram: {tipo} {chiave}")
            if not fatte:
                print("Telegram: niente di nuovo da mandare" if not lista else f"Telegram: già {oggi} messaggi oggi, basta così")
    soglia = (adesso - dt.timedelta(days=GIORNI_STATO)).isoformat()
    stato["mandati"] = {k: v for k, v in stato["mandati"].items() if v >= soglia or k.split("@")[0] in {n["id"] for n in notizie}}
    os.makedirs(os.path.dirname(os.path.abspath(a.stato)), exist_ok=True)
    with open(a.stato, "w", encoding="utf-8") as f:
        json.dump(stato, f, ensure_ascii=False)



if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print("AVVISO Telegram:", e, file=sys.stderr)
        sys.exit(1)
