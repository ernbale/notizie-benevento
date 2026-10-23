#!/usr/bin/env python3
"""Pubblica sul canale Telegram (t.me/notiziebenevento) le notizie nuove e gli aggiornamenti, appena escono sul sito.

Lo esegue GitHub dopo ogni pubblicazione del sito, come facebook.py. Su Telegram si legge tutto di seguito, come un
notiziario: qui niente pausa di un'ora come su Facebook, ma al massimo POR_GIRO messaggi per volta e MAX_GIORNO al
giorno, solo dalle 6 fino al giro delle 22 compreso (alle 23 solo le allerte arancioni o rosse, come su Facebook).
- Notizia nuova: titolo, riassunto, link (Telegram mostra l'anteprima con l'immagine della notizia).
- Aggiornamento (il riquadro «Aggiornamento» dell'articolo): «Aggiornamento» + titolo + la frase della novità.
- Il bot non può rileggere il canale: cosa è già uscito lo ricorda in un file (--stato) che GitHub conserva tra
  una pubblicazione e l'altra (cache). In più legge l'anteprima pubblica del canale (t.me/s/…, gli ultimi
  messaggi): una notizia che è già lì non si rimanda mai. Se il file non c'è (la prima volta, o GitHub l'ha perso)
  lo rifà dall'anteprima: già uscito ciò che è sul canale o è più vecchio del suo ultimo messaggio; se nemmeno
  l'anteprima si legge, segna come già uscito tutto: meglio una notizia in meno che dieci doppioni.
- Il conto dei messaggi del giorno è fatto solo sui messaggi mandati davvero (22 ott: le 126 notizie segnate come
  già uscite alla prima volta erano contate come messaggi e il canale è rimasto muto dalle 16 alle 21).
- Arretrati (TG_RECUPERA=1, dal pulsante di GitHub): manda tutto quello che manca delle ultime ORE_FINESTRA ore.
- La chiave del bot è nel segreto TELEGRAM_TOKEN di GitHub; senza chiave non fa niente. Nei log mai la chiave.

Uso:  TELEGRAM_TOKEN=… python3 strumenti/telegram.py --stato /percorso/telegram.json
      python3 strumenti/telegram.py --prova      (dice cosa pubblicherebbe, senza chiave e senza toccare Telegram)
"""
import argparse
import datetime as dt
import html
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from facebook import SITO, allerta_seria, fuso, quando   # stessa ora delle notizie e stesse allerte di facebook.py

CANALE = "@notiziebenevento"
TITOLO_CANALE = "Notizie Benevento"
ANTEPRIMA = "https://t.me/s/notiziebenevento"   # la pagina pubblica del canale: gli ultimi messaggi, senza chiave
API = "https://api.telegram.org"
POR_GIRO = 6
MAX_GIORNO = 80             # solo un freno contro un errore che manda a raffica: un giorno pieno ne fa 40-50
PAUSA = 3                   # secondi tra un messaggio e l'altro (Telegram ne accetta una ventina al minuto)
ORE_FINESTRA = 12           # notizie e aggiornamenti più vecchi di così non si mandano più (l'ora è quella
                            # dell'articolo fonte: una notizia trovata tardi ha l'ora del mattino)
DALLE, ALLE = 6, 23   # come facebook.py
GIORNI_STATO = 4            # quanto si ricorda di cosa è già uscito


def chiama(token, metodo, dati=None):
    req = urllib.request.Request(f"{API}/bot{token}/{metodo}", data=json.dumps(dati or {}).encode(),
                                 headers={"Content-Type": "application/json"}, method="POST")
    for prova in range(3):
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.load(r)["result"]
        except urllib.error.HTTPError as e:
            try:
                d = json.load(e)
            except ValueError:
                d = {}
            attesa = (d.get("parameters") or {}).get("retry_after")
            if e.code == 429 and attesa and prova < 2:   # troppi messaggi di fila: Telegram dice quanto aspettare
                time.sleep(int(attesa) + 1)
                continue
            raise RuntimeError(f"Telegram {e.code}: {d.get('description', '')}") from None   # mai l'indirizzo con la chiave


def sul_canale():
    """Dall'anteprima pubblica (l'ultima ventina di messaggi): le notizie che ci sono, l'ora del primo messaggio
    visibile e quella dell'ultimo; None se non si legge."""
    try:
        req = urllib.request.Request(ANTEPRIMA, headers={"User-Agent": "Mozilla/5.0 (notiziebenevento.it)"})
        with urllib.request.urlopen(req, timeout=30) as r:
            pagina = r.read().decode("utf-8", "replace")
        ore = [dt.datetime.fromisoformat(x) for x in re.findall(r'<time datetime="([^"]+)"', pagina)]
    except Exception as e:
        print(f"Telegram: non leggo l'anteprima del canale ({e})")
        return None
    if not ore:
        print("Telegram: l'anteprima del canale non ha messaggi leggibili")
        return None
    return set(re.findall(r"notiziebenevento\.it/notizia/([a-z0-9-]+)", pagina)), min(ore), max(ore)


def manda(token, tipo, n):
    chiama(token, "sendMessage", {"chat_id": CANALE, "text": testo(tipo, n), "parse_mode": "HTML",
                                  "link_preview_options": {"url": f"{SITO}/notizia/{n['id']}/", "prefer_large_media": True}})


def chiave_agg(n):
    return f"{n['id']}@{((n.get('articolo') or {}).get('aggiornamento') or {}).get('quando')}"


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
    canale = sul_canale()
    subito = int(os.environ.get("TG_SUBITO") or 0)   # solo quando lo chiede il proprietario, dal pulsante di GitHub
    recupera = os.environ.get("TG_RECUPERA", "0") not in ("", "0", "false")
    if stato is None:   # prima volta (o ricordo perso): lo rifaccio dal canale, o segno tutto come già uscito
        ora = adesso.isoformat(timespec="minutes")
        stato = {"mandati": {}, "inviati": []}
        for n in notizie:
            t = quando(n, adesso)
            ag = ((n.get("articolo") or {}).get("aggiornamento") or {}).get("quando")
            if not canale or n["id"] in canale[0] or (t and t <= canale[2]):
                stato["mandati"][n["id"]] = ora
                try:
                    if not canale or not ag or dt.datetime.fromisoformat(ag) <= canale[2]:
                        stato["mandati"][chiave_agg(n)] = ora
                except (ValueError, TypeError):
                    stato["mandati"][chiave_agg(n)] = ora
        print(f"Telegram: nessun ricordo di cosa è già uscito, rifatto {'dal canale' if canale else 'segnando tutto come già uscito'}")
    stato.setdefault("inviati", [])   # l'ora di ogni messaggio mandato davvero: il conto del giorno si fa su questi

    def segna(chiave, n):
        stato["mandati"][chiave] = adesso.isoformat(timespec="minutes")
        stato["mandati"][chiave_agg(n)] = adesso.isoformat(timespec="minutes")   # l'aggiornamento che c'è è già nel testo
        stato["inviati"].append(dt.datetime.now(fuso()).isoformat(timespec="seconds"))

    try:   # il ricordo si salva anche se un messaggio va storto a metà: quelli già mandati non si rimandano
        if subito:   # le ultime notizie uscite, adesso (per il primo messaggio del canale)
            ultime = sorted((x for x in notizie if quando(x, adesso) and quando(x, adesso) <= adesso),
                            key=lambda x: quando(x, adesso))[-subito:]
            for n in ultime:
                if canale and n["id"] in canale[0]:
                    continue
                manda(token, "nuova", n)
                segna(n["id"], n)
                print(f"Telegram: mandata subito {n['id']}")
                time.sleep(PAUSA)
        else:
            sera = adesso.hour == 23
            if not DALLE <= adesso.hour < ALLE and not sera:
                print(f"Telegram: sono le {adesso:%H:%M}, si pubblica dalle {DALLE} fino al giro delle {ALLE - 1}")
            else:
                gia = set(stato["mandati"])
                if canale:   # una notizia già sul canale non si rimanda, qualunque cosa dica il ricordo
                    gia |= canale[0]
                oggi = sum(1 for v in stato["inviati"] if v[:10] == adesso.date().isoformat())
                lista = da_mandare(notizie, gia, adesso)
                if sera:
                    lista = [x for x in lista if allerta_seria(x[3])]
                quante = max(0, MAX_GIORNO - oggi) if recupera else max(0, min(POR_GIRO, MAX_GIORNO - oggi))
                fatte = 0
                for _, chiave, tipo, n in lista[:quante]:
                    if fatte:
                        time.sleep(PAUSA)
                    manda(token, tipo, n)
                    segna(chiave, n)
                    fatte += 1
                    print(f"Telegram: {tipo} {chiave}")
                if not lista:
                    print("Telegram: niente di nuovo da mandare")
                elif len(lista) > fatte:
                    print(f"Telegram: ne restano {len(lista) - fatte} per la prossima volta ({oggi + fatte} messaggi oggi)")
                    if oggi + fatte >= MAX_GIORNO:
                        raise RuntimeError(f"raggiunto il freno di {MAX_GIORNO} messaggi al giorno con {len(lista) - fatte} notizie ancora da mandare")
    finally:
        salva(stato, a.stato, notizie, adesso)


def salva(stato, percorso, notizie, adesso):
    soglia = (adesso - dt.timedelta(days=GIORNI_STATO)).isoformat()
    stato["mandati"] = {k: v for k, v in stato["mandati"].items() if v >= soglia or k.split("@")[0] in {n["id"] for n in notizie}}
    stato["inviati"] = [v for v in stato["inviati"] if v >= (adesso - dt.timedelta(days=2)).isoformat()]
    os.makedirs(os.path.dirname(os.path.abspath(percorso)), exist_ok=True)
    with open(percorso, "w", encoding="utf-8") as f:
        json.dump(stato, f, ensure_ascii=False)


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print("AVVISO Telegram:", e, file=sys.stderr)
        sys.exit(1)
