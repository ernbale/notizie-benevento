#!/usr/bin/env python3
"""La sentinella: ogni quarto d'ora controlla che il giro dell'agente, il sito e il canale Telegram stiano al passo,
e ripara da sola quello che può. Nata il 22 ott 2026: GitHub ha tenuto ferma in coda per 78 minuti la pubblicazione
del giro delle 19 (sul sito è arrivato alle 20:30) e il canale Telegram è rimasto muto dalle 16 alle 21 senza che
nessuno se ne accorgesse.

1. Pubblicazione ferma in coda da più di CODA_MAX minuti senza essere partita: la annulla e ne lancia un'altra, che
   prende tutte le notizie fino a quel momento.
2. Sito indietro: notizie.json del ramo main più nuovo di quello online da più di RITARDO_MAX minuti e nessuna
   pubblicazione in corso: ne lancia una.
3. Canale Telegram muto: dalle 7 alle 23 (un'ora dopo l'inizio dei post), sul sito c'è una notizia più nuova dell'ultimo messaggio del canale, da più
   di TG_MAX minuti: lancia una pubblicazione con gli arretrati di Telegram.
5. Chiusure dei Comuni (dal 23 ott 2026, vedi strumenti/chiusure.py): la vedetta del Pi ferma da più di VEDETTA_MAX
   minuti, una pista non vista dal giro Chiusure dopo PISTA_MAX minuti (solo sul Pi), una chiusura del sito che dopo
   TG_CHIUSURE minuti non è sul canale Telegram, o l'ultima pubblicazione col passo delle chiusure in rosso: nei due
   ultimi casi rilancia la pubblicazione, che rimanda solo quello che manca (niente doppioni).
6. Curiosità del Sannio (dal 24 ott 2026, vedi CURIOSITA.md): la scorta in curiosita.json basta per meno di
   SCORTA_MINIMA giorni (la routine del lunedì non l'ha rifornita), o dopo le 12:30 la curiosità di oggi non è ancora
   sul sito o sul canale Telegram: in quel caso rilancia la pubblicazione (curiosita_social.py non fa doppioni).
7. Comunicati per email (dal 24 ott 2026, vedi COMUNICATI.md): solo sul Pi, un comunicato arrivato da più di
   COMUNICATO_MAX minuti che il giro lampo non ha ancora trattato (comunicati_visti.json del sito). Il Pi lo rilancia
   da solo (comunicati_lampo.py): qui si dà l'allarme.
4. Giro mancato: notizie.json non aggiornato da più di GIRO_MAX minuti, dalle 7:30 alle 23; dalle 23 a mezzanotte
   solo se per domani c'è allerta arancione o rossa, perché il giro delle 23 l'agente lo fa solo allora (stessa prova,
   allerta_domani.py; il 22 ott la sentinella è finita in rosso alle 23:32 per un giro che giustamente non c'era).
   Lo può solo segnalare: l'agente gira sui server di Anthropic.

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
import errno
import getpass
import json
import os
import re
import socket
import sys
import time
import urllib.error
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from facebook import SITO, fuso, quando
from telegram import DALLE, ALLE, sul_canale
from allerta_domani import allerte

REPO = "ernbale/notizie-benevento"
API = "https://api.github.com"
FLUSSO = "pubblica.yml"
CODA_MAX = 20       # minuti in coda senza partire
RITARDO_MAX = 25    # minuti di ritardo del sito rispetto a main
TG_MAX = 75         # minuti di silenzio del canale con una notizia nuova sul sito
GIRO_MAX = 80       # minuti dall'ultimo giro (uno all'ora)
AVVISO_ORE = 2      # dal Pi, la sentinella di GitHub (la mail) al massimo una volta ogni tante ore
VEDETTA_MAX = 20    # minuti senza un giro della vedetta delle chiusure (sul Pi)
PISTA_MAX = 45      # minuti: una pista della vedetta non ancora vista dal giro Chiusure
TG_CHIUSURE = 20    # minuti: una chiusura del sito non ancora sul canale Telegram
SCORTA_MINIMA = 14  # giorni di curiosità in programma: sotto, la routine del lunedì non ha rifornito
COMUNICATO_MAX = 30  # minuti: un comunicato per email non ancora trattato dal giro lampo
CARTELLA_PI = os.path.expanduser("~/nb-fonti")
PAUSA_RETE = 20     # secondi prima del secondo tentativo se la rete fa cilecca


def apri(req, metodo="GET"):
    """urlopen con un secondo tentativo dopo PAUSA_RETE se la rete fa cilecca (23 ott 08:32 «No route to host» sul Pi).
    Le scritture (POST) si riprovano solo se la connessione non è proprio partita: dopo un timeout GitHub
    potrebbe averle già ricevute, e un rilancio doppio non lo vogliamo."""
    try:
        return urllib.request.urlopen(req, timeout=30)
    except urllib.error.HTTPError:   # il server ha risposto: non è la rete
        raise
    except OSError as e:   # URLError, timeout, SSL
        motivo = getattr(e, "reason", e)
        mai_partita = (isinstance(motivo, (socket.gaierror, ConnectionRefusedError))
                       or getattr(motivo, "errno", None) in (errno.EHOSTUNREACH, errno.ENETUNREACH))
        if metodo != "GET" and not mai_partita:
            raise
        time.sleep(PAUSA_RETE)
        return urllib.request.urlopen(req, timeout=30)


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
            with apri(req, metodo) as r:
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
    with apri(f"{SITO}/notizie.json?sentinella={int(time.time())}") as r:
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
    if ((adesso.hour, adesso.minute) >= (7, 30) and adesso - a_main > dt.timedelta(minutes=GIRO_MAX)
            and (adesso.hour < 23 or giro_delle_23(adesso))):
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


def giro_delle_23(adesso):
    """Stasera c'è il giro delle 23? Solo se per domani c'è allerta arancione o rossa: la stessa prova dell'agente."""
    try:
        return bool(allerte(adesso)[1])
    except Exception:   # come l'agente: se meteo.json non si legge, il giro delle 23 non lo fa
        return False


def chiusure(gh, adesso, pi, sito, prova):
    """Le chiusure dei Comuni arrivano dappertutto? (punto 5 in cima). Restituisce (riparati, problemi)."""
    riparati, problemi = [], []
    if pi:
        sito_c = json.loads(gh.chiama("GET", f"repos/{REPO}/contents/chiusure.json?ref=main", grezzo=True))
        try:
            with open(os.path.join(CARTELLA_PI, "vedetta.json"), encoding="utf-8") as f:
                ultimo = iso(json.load(f)["ultimo_giro"])
        except (OSError, ValueError, KeyError):
            ultimo = None
        if not ultimo or adesso - ultimo > dt.timedelta(minutes=VEDETTA_MAX):
            problemi.append("la vedetta delle chiusure è ferma" + (f" dalle {ultimo:%H:%M}" if ultimo else "") +
                            " (cron del Pi, ~/nb-fonti/vedetta.log)")
        try:
            with open(os.path.join(CARTELLA_PI, "archivio", "chiusure.json"), encoding="utf-8") as f:
                piste = json.load(f).get("piste") or []
        except (OSError, ValueError):
            piste = []
        viste = set(sito_c.get("viste") or [])
        for p in piste:
            if p["id"] not in viste and adesso - iso(p["trovata"]) > dt.timedelta(minutes=PISTA_MAX):
                problemi.append(f"la pista di {p.get('comune') or '?'} trovata alle {iso(p['trovata']):%H:%M} "
                                f"({p.get('titolo', '')[:60]}) non è ancora stata vista dal giro Chiusure")
    else:
        with open(os.path.join(sito, "chiusure.json"), encoding="utf-8") as f:
            sito_c = json.load(f)
    oggi = adesso.date().isoformat()
    attive = [c for c in sito_c.get("chiusure") or [] if max(c.get("giorni") or [""]) >= oggi]
    rilancia = False
    if attive:
        ritardo = [c for c in attive if adesso - iso(c.get("aggiornata") or c["aggiunta"]) > dt.timedelta(minutes=TG_CHIUSURE)]
        if ritardo:
            req = urllib.request.Request("https://t.me/s/notiziebenevento", headers={"User-Agent": "Mozilla/5.0 (notiziebenevento.it)"})
            with apri(req) as r:
                pagina = r.read().decode("utf-8", "replace")
            sul_canale_ = set(re.findall(r"notiziebenevento\.it/scuole-chiuse/#([a-z0-9-]+)", pagina))
            ore = [dt.datetime.fromisoformat(x) for x in re.findall(r'<time datetime="([^"]+)"', pagina)]
            mancano = [c for c in ritardo if c["id"] not in sul_canale_ and (not ore or iso(c.get("aggiornata") or c["aggiunta"]) > min(ore))]
            if mancano:
                problemi.append(f"chiusure non ancora sul canale Telegram: {', '.join(c['comune'] for c in mancano)}")
                rilancia = True
        corse = gh.chiama("GET", f"repos/{REPO}/actions/workflows/{FLUSSO}/runs?per_page=5").get("workflow_runs", [])
        if any(c["status"] != "completed" for c in corse):
            rilancia = False   # una pubblicazione è già in corso: rimanda lei quello che manca
        else:
            fatta = next((c for c in corse if c["status"] == "completed"), None)
            if fatta and fatta.get("conclusion") == "failure":
                lavori = gh.chiama("GET", f"repos/{REPO}/actions/runs/{fatta['id']}/jobs").get("jobs", [])
                if any(st.get("name", "").startswith("Chiusure non uscite") and st.get("conclusion") == "failure"
                       for j in lavori for st in j.get("steps") or []):
                    problemi.append("l'ultima pubblicazione non ha mandato le chiusure su tutti i canali")
                    rilancia = True
        if rilancia:
            riparati.append("rilanciata la pubblicazione per le chiusure" + (" (prova: in realtà no)" if prova else ""))
            if not prova:
                gh.lancia(FLUSSO, {"telegram_recupera": "0"})
    return riparati, problemi


def curiosita(gh, adesso, pi, sito, prova):
    """Le curiosità del Sannio: scorta e uscita di oggi (punto 6 in cima). Restituisce (riparati, problemi)."""
    riparati, problemi = [], []
    if pi:
        tutte = json.loads(gh.chiama("GET", f"repos/{REPO}/contents/curiosita.json?ref=main", grezzo=True)).get("curiosita") or []
    else:
        with open(os.path.join(sito, "curiosita.json"), encoding="utf-8") as f:
            tutte = json.load(f).get("curiosita") or []
    oggi = adesso.date()
    ultima = max((dt.date.fromisoformat(c["data"]) for c in tutte), default=None)
    if not ultima or (ultima - oggi).days < SCORTA_MINIMA:
        problemi.append("la scorta delle curiosità " + (f"finisce il {ultima:%d/%m} ({(ultima - oggi).days} giorni)"
                        if ultima else "è vuota") + ": la routine del lunedì non l'ha rifornita (CURIOSITA.md)")
    di_oggi = next((c for c in tutte if c["data"] == oggi.isoformat()), None)
    if di_oggi and (adesso.hour, adesso.minute) >= (12, 30) and adesso.hour < 22:
        mancano = []
        req = urllib.request.Request(f"{SITO}/curiosita/ultime.json?t={int(adesso.timestamp())}",
                                     headers={"User-Agent": "nb-sentinella", "Cache-Control": "no-cache"})
        try:
            with apri(req) as r:
                ultime = json.load(r).get("curiosita") or []
            if not ultime or ultime[0].get("slug") != di_oggi["slug"]:
                mancano.append("sul sito")
        except Exception:
            mancano.append("sul sito (non risponde)")
        req = urllib.request.Request("https://t.me/s/notiziebenevento", headers={"User-Agent": "Mozilla/5.0 (notiziebenevento.it)"})
        with apri(req) as r:
            if f"notiziebenevento.it/curiosita/{di_oggi['slug']}/" not in r.read().decode("utf-8", "replace"):
                mancano.append("sul canale Telegram")
        if mancano:
            problemi.append(f"la curiosità di oggi («{di_oggi['titolo'][:50]}») alle {adesso:%H:%M} non è ancora "
                            + " né ".join(mancano))
            corse = gh.chiama("GET", f"repos/{REPO}/actions/workflows/{FLUSSO}/runs?per_page=5").get("workflow_runs", [])
            if not any(c["status"] != "completed" for c in corse):
                riparati.append("rilanciata la pubblicazione per la curiosità" + (" (prova: in realtà no)" if prova else ""))
                if not prova:
                    gh.lancia(FLUSSO)
    return riparati, problemi


def comunicati(gh, adesso, pi):
    """I comunicati per email sono stati trattati dal giro lampo? (punto 7 in cima). Restituisce i problemi."""
    if not pi:
        return []
    try:
        with open(os.path.join(CARTELLA_PI, "archivio", "comunicati.json"), encoding="utf-8") as f:
            voci = json.load(f).get("voci") or []
    except (OSError, ValueError):
        return ["non leggo comunicati.json dell'archivio di casa (~/nb-fonti/archivio)"]
    visti = json.loads(gh.chiama("GET", f"repos/{REPO}/contents/comunicati_visti.json?ref=main", grezzo=True)).get("visti") or {}
    try:
        with open(os.path.join(CARTELLA_PI, "comunicati_lampo.json"), encoding="utf-8") as f:
            vecchi = {k for k, x in (json.load(f).get("lanciati") or {}).items() if x.get("gia")}
    except (OSError, ValueError):
        vecchi = set()
    problemi = []
    for v in voci:
        quando = v.get("arrivata") or v.get("data")
        arrivata = iso(quando) if quando else None
        if (v.get("id") and v["id"] not in visti and v["id"] not in vecchi and arrivata
                and dt.timedelta(minutes=COMUNICATO_MAX) < adesso - arrivata < dt.timedelta(hours=24)):
            problemi.append(f"il comunicato di {v.get('mittente') or v.get('dominio')} arrivato alle {arrivata:%H:%M} "
                            f"(«{str(v.get('titolo'))[:60]}») non è ancora stato trattato dal giro lampo "
                            "(~/nb-fonti/comunicati.log)")
    return problemi


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
    try:
        r2, p2 = chiusure(gh, adesso, a.pi, a.sito, a.prova)
        riparati += r2
        problemi += p2
    except Exception as e:
        problemi.append(f"non riesco a controllare le chiusure dei Comuni ({type(e).__name__}: {e})")
    try:
        r3, p3 = curiosita(gh, adesso, a.pi, a.sito, a.prova)
        riparati += r3
        problemi += p3
    except Exception as e:
        problemi.append(f"non riesco a controllare le curiosità ({type(e).__name__}: {e})")
    try:
        problemi += comunicati(gh, adesso, a.pi)
    except Exception as e:
        problemi.append(f"non riesco a controllare i comunicati per email ({type(e).__name__}: {e})")

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
