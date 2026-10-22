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

Dove gira: sul Pi di casa ogni 15 minuti (cron, --pi), perché gli orari di GitHub saltano proprio quando GitHub è
carico (la sera del 22 ott non è mai partita); e su GitHub (sentinella.yml) come riserva. Se qualcosa non va, su
GitHub finisce in rosso e GitHub manda una mail al proprietario; dal Pi fa partire la sentinella di GitHub, che
ricontrolla e finisce in rosso lei (al massimo una volta ogni AVVISO_ORE ore). Le riparazioni restano tra gli avvisi.

Parla con GitHub con le sue API: su GitHub con il GITHUB_TOKEN (GH_TOKEN), sul Pi con una chiave limitata a questo
solo sito (Actions lettura e scrittura, Contents sola lettura) nel file --chiave, che scrive --imposta-chiave.
La chiave non si stampa mai.

Uso:  python3 strumenti/sentinella.py                 (su GitHub, con GH_TOKEN)
      python3 sentinella.py --pi                      (sul Pi, dal cron)
      python3 sentinella.py --imposta-chiave          (sul Pi, una volta: chiede la chiave, la prova e la salva)
      python3 strumenti/sentinella.py --prova         (dice cosa farebbe, senza annullare né lanciare niente)
"""
import argparse
import datetime as dt
import getpass
import json
import os
import sys
import time
import urllib.error
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from facebook import SITO, fuso, quando
from telegram import DALLE, ALLE, sul_canale

REPO = "ernbale/notizie-benevento"
API = "https://api.github.com"
FLUSSO = "pubblica.yml"
CODA_MAX = 20       # minuti in coda senza partire
RITARDO_MAX = 25    # minuti di ritardo del sito rispetto a main
TG_MAX = 75         # minuti di silenzio del canale con una notizia nuova sul sito
GIRO_MAX = 80       # minuti dall'ultimo giro (uno all'ora)
AVVISO_ORE = 2      # dal Pi, la sentinella di GitHub (la mail) al massimo una volta ogni tante ore
CARTELLA_PI = os.path.expanduser("~/nb-fonti")


class GitHub:
    def __init__(self, token):
        self.token = token
        self.scade = None   # quando scade la chiave (GitHub lo dice in ogni risposta, per le chiavi con scadenza)

    def chiama(self, metodo, percorso, dati=None, grezzo=False):
        req = urllib.request.Request(f"{API}/{percorso}", method=metodo,
                                     data=json.dumps(dati).encode() if dati is not None else None,
                                     headers={"Authorization": f"Bearer {self.token}",
                                              "Accept": "application/vnd.github.raw" if grezzo else "application/vnd.github+json",
                                              "X-GitHub-Api-Version": "2022-11-28", "User-Agent": "nb-sentinella"})
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                self.scade = r.headers.get("github-authentication-token-expiration") or self.scade
                corpo = r.read()
        except urllib.error.HTTPError as e:
            try:
                msg = json.loads(e.read()).get("message", "")
            except ValueError:
                msg = ""
            raise RuntimeError(f"GitHub {e.code} su {metodo} {percorso.split('?')[0]}: {msg}") from None
        if grezzo:
            return corpo.decode("utf-8")
        return json.loads(corpo) if corpo else {}

    def lancia(self, flusso, inputs=None):
        self.chiama("POST", f"repos/{REPO}/actions/workflows/{flusso}/dispatches", {"ref": "main", "inputs": inputs or {}})


def leggi_chiave(percorso):
    t = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
    if t:
        return t.strip()
    try:
        with open(percorso, encoding="utf-8") as f:
            return json.load(f)["token"].strip()
    except (OSError, ValueError, KeyError):
        sys.exit(f"Sentinella: manca la chiave di GitHub ({percorso}: sentinella.py --imposta-chiave)")


def imposta_chiave(percorso):
    """Chiede la chiave (non si vede), controlla che possa leggere e lanciare le pubblicazioni, la salva (600)."""
    token = getpass.getpass("Chiave di GitHub per la sentinella (non si vede mentre la incolli): ").strip()
    gh = GitHub(token)
    try:
        gh.chiama("GET", f"repos/{REPO}/actions/workflows/{FLUSSO}/runs?per_page=1")
        gh.chiama("GET", f"repos/{REPO}/contents/notizie.json?ref=main", grezzo=True)
    except Exception as e:   # sul Pi nel log una riga, non un traceback
        sys.exit(f"La chiave non va: {e}. Niente salvato.")
    os.makedirs(os.path.dirname(percorso), exist_ok=True)
    vecchio = os.umask(0o077)
    try:
        with open(percorso, "w", encoding="utf-8") as f:
            json.dump({"token": token}, f)
    finally:
        os.umask(vecchio)
    os.chmod(percorso, 0o600)
    print(f"✓ chiave salvata ({percorso})" + (f", scade il {gh.scade}" if gh.scade else ", senza scadenza"))
    print("  (il permesso di lanciare le pubblicazioni si vedrà alla prima riparazione)")


def iso(s):
    return dt.datetime.fromisoformat(s.replace("Z", "+00:00"))


def minuti(d):
    return int(d.total_seconds() // 60)


def controlla(gh, su_main, adesso, prova):
    """Restituisce (riparati, problemi): le frasi da scrivere."""
    problemi, riparati = [], []

    # 1. pubblicazioni in coda che non partono
    corse = gh.chiama("GET", f"repos/{REPO}/actions/workflows/{FLUSSO}/runs?per_page=15").get("workflow_runs", [])
    attive = []
    for c in corse:
        if c["status"] == "completed":
            continue
        lavori = gh.chiama("GET", f"repos/{REPO}/actions/runs/{c['id']}/jobs").get("jobs", [])
        partita = any(j.get("status") not in ("queued", "waiting", "pending", "requested") for j in lavori)
        attesa = adesso - iso(c["created_at"])
        if not partita and attesa > dt.timedelta(minutes=CODA_MAX):
            riparati.append(f"la pubblicazione {c['id']} era ferma in coda da {minuti(attesa)} minuti: annullata")
            if not prova:
                gh.chiama("POST", f"repos/{REPO}/actions/runs/{c['id']}/cancel")
        else:
            attive.append(c)

    # 2. sito indietro rispetto a main
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

    if lancia:
        riparati.append(f"lanciata una pubblicazione{' con gli arretrati di Telegram' if recupera else ''}"
                        f"{' (prova: in realtà no)' if prova else ''}")
        if not prova:
            gh.lancia(FLUSSO, {"telegram_recupera": "1" if recupera else "0"})

    # la chiave del Pi: avviso due settimane prima che scada
    if gh.scade:
        try:
            scade = dt.datetime.strptime(gh.scade.replace(" UTC", ""), "%Y-%m-%d %H:%M:%S").replace(tzinfo=dt.timezone.utc)
            if scade - adesso < dt.timedelta(days=14):
                problemi.append(f"la chiave GitHub della sentinella scade il {scade.astimezone(fuso()):%d/%m/%Y}: rifarla")
        except ValueError:
            pass
    return riparati, problemi


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sito", default=os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    ap.add_argument("--pi", action="store_true", help="sul Pi: notizie.json da GitHub e avviso tramite la sentinella di GitHub")
    ap.add_argument("--chiave", default=os.path.join(CARTELLA_PI, "github.conf"))
    ap.add_argument("--imposta-chiave", action="store_true")
    ap.add_argument("--prova", action="store_true")
    a = ap.parse_args()
    if a.imposta_chiave:
        return imposta_chiave(a.chiave)
    adesso = dt.datetime.now(fuso())
    gh = GitHub(leggi_chiave(a.chiave))
    if a.pi:   # sul Pi il sito non c'è: notizie.json del ramo main lo dà GitHub (senza la cache di raw.githubusercontent)
        su_main = json.loads(gh.chiama("GET", f"repos/{REPO}/contents/notizie.json?ref=main", grezzo=True))
    else:
        with open(os.path.join(a.sito, "notizie.json"), encoding="utf-8") as f:
            su_main = json.load(f)
    riparati, problemi = controlla(gh, su_main, adesso, a.prova)

    ora = f"{adesso:%d/%m %H:%M}"
    for m in riparati:
        print(f"{ora} riparato: {m}" if a.pi else f"::warning::Sentinella: {m}")
    for m in problemi:
        print(f"{ora} PROBLEMA: {m}" if a.pi else f"::error::Sentinella: {m}")
    if not riparati and not problemi:
        print(f"{ora} tutto al passo (giro delle {iso(su_main['aggiornato']):%H:%M})" if a.pi
              else f"Sentinella: tutto al passo (giro delle {iso(su_main['aggiornato']):%H:%M}, sito uguale)")
    if problemi and a.pi and not a.prova:   # la mail la manda GitHub: faccio partire la sentinella di là
        stato_f = os.path.join(CARTELLA_PI, "sentinella.json")
        try:
            with open(stato_f, encoding="utf-8") as f:
                ultimo = iso(json.load(f)["avviso"])
        except (OSError, ValueError, KeyError):
            ultimo = None
        if not ultimo or adesso - ultimo > dt.timedelta(hours=AVVISO_ORE):
            gh.lancia("sentinella.yml")
            with open(stato_f, "w", encoding="utf-8") as f:
                json.dump({"avviso": adesso.isoformat(timespec="minutes")}, f)
            print(f"{ora} avviso: lanciata la sentinella di GitHub (mail se resta rosso)")
    if problemi and not a.pi:
        sys.exit(1)


if __name__ == "__main__":
    try:
        main()
    except Exception as e:   # sul Pi nel log una riga, non un traceback
        print(f"{dt.datetime.now(fuso()):%d/%m %H:%M} ERRORE: {e}" if "--pi" in sys.argv else f"::error::Sentinella: {e}")
        sys.exit(1)
