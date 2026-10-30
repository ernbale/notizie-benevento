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
   da solo (comunicati_lampo.py): qui si dà l'allarme. Dal 25 ott 2026 anche gli articoli dei siti ufficiali
   (ufficiali.json, strumenti/ufficiali.py), dopo SITO_MAX minuti. Dal 26 ott 2026 anche un comunicato «in sospeso»
   (il giro lampo non ha potuto scriverlo perché il Pi non ha letto un allegato: COMUNICATI.md): l'avviso si ripete
   ogni ora (SOSPESO_ORE) finché qualcuno non lo sistema (dopo il San Pio delle 12:12, scartato e mai più visto).
8. Fonti lette da casa (dal 25 ott 2026: l'albo di Benevento e 37 albi su Halley giù dalle 00:30, e nessuno se n'era
   accorto): solo sul Pi, una fonte dell'archivio di casa (~/nb-fonti/archivio) che non si legge da più di
   FONTE_FERMA_ORE ore, o che si legge solo dalla riserva, o gli albi dei Comuni letti meno di ALBI_MINIMI su 57: un
   avviso solo, ripetuto dopo 24 ore se è ancora ferma (fonti_ferme.json); l'archivio che non si aggiorna proprio (il
   cron di fonti_casa.py fermo). La sentinella di GitHub riprova gli indirizzi da fuori e dice se è giù per tutti o
   solo per la connessione di casa.
4. Giro mancato: notizie.json non aggiornato da più di GIRO_MAX minuti, dalle 7:30 alle 23; dalle 23 a mezzanotte
   solo se per domani c'è allerta arancione o rossa, perché il giro delle 23 l'agente lo fa solo allora (stessa prova,
   allerta_domani.py; il 22 ott la sentinella è finita in rosso alle 23:32 per un giro che giustamente non c'era).
   Lo può solo segnalare: l'agente gira sui server di Anthropic.

Dove gira: sul Pi di casa ogni 15 minuti (cron, --pi), perché gli orari di GitHub saltano proprio quando GitHub è
carico (la sera del 22 ott non è mai partita); e su GitHub (sentinella.yml) come riserva. Se qualcosa non va, su
GitHub finisce in rosso e GitHub manda una mail al proprietario; dal Pi fa partire la sentinella di GitHub passandole
i problemi visti dal Pi (input «avviso»: quelli che da GitHub non si vedono, come la vedetta ferma o una fonte di casa,
fino al 25 ott non arrivavano nella mail), che ricontrolla, li aggiunge ai suoi e finisce in rosso (al massimo una volta
ogni AVVISO_ORE ore). Le riparazioni restano tra gli avvisi.

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
import fcntl
import getpass
import json
import os
import re
import socket
import sys
import time
import urllib.error
import urllib.parse
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
SOSPESO_ORE = 1     # …ma ogni ora se c'è un comunicato in sospeso
DA_VALUTARE_ORE = 3  # un comunicato di un mittente non ufficiale ancora da valutare: promemoria dopo tante ore
VEDETTA_MAX = 20    # minuti senza un giro della vedetta delle chiusure (sul Pi)
PISTA_MAX = 45      # minuti: una pista della vedetta non ancora vista dal giro Chiusure
TG_CHIUSURE = 20    # minuti: una chiusura del sito non ancora sul canale Telegram
SCORTA_MINIMA = 14  # giorni di curiosità in programma: sotto, la routine del lunedì non ha rifornito
COMUNICATO_MAX = 30  # minuti: un comunicato per email non ancora trattato dal giro lampo
SITO_MAX = 50        # minuti: un articolo dei siti ufficiali (può aspettare il giro di ogni ora fino alle :20)
FONTE_FERMA_ORE = 3  # ore senza una lettura riuscita di una fonte di casa (come la regola dell'agente in AGENTE.md)
ARCHIVIO_FERMO = 90  # minuti senza un giro di fonti_casa.py (gira ogni 30)
ALBI_MINIMI = 45     # albi pretori dei Comuni letti (su 57): sotto, per più di FONTE_FERMA_ORE ore, avviso
RIPETI_ORE = 24      # una fonte ancora ferma si ricorda una volta al giorno
NON_DA_FUORI = ("stradeanas.it", "tvsette.net")   # rifiutano le connessioni dall'estero: da GitHub non si prova
CARTELLA_PI = os.path.expanduser("~/nb-fonti")
PAUSA_RETE = 20     # secondi prima del secondo tentativo se la rete fa cilecca
# Dal Pi l'avviso arriva al proprietario anche su WhatsApp (Home Assistant) e per email (da comunicati@): voluto il
# 25 ott 2026, «mi deve avvisare per email e wapp tramite ha». Dove mandarlo sta in avvisi.conf (solo sul Pi: indirizzo
# e token di Home Assistant, servizio WhatsApp, email); la casella per mandare è quella di posta.conf.
AVVISI_CONF = os.path.join(CARTELLA_PI, "avvisi.conf")
POSTA_CONF = os.path.join(CARTELLA_PI, "posta.conf")
# Dal 29 ott 2026 (lui: «fai il whatsapp diretto con callmebot») il WhatsApp può andare diretto a CallMeBot, senza Home
# Assistant: serve al server Aruba, che Home Assistant di casa non lo vede. Lo fa se avvisi.conf ha «callmebot»
# ({"telefono", "apikey"}, quelli della voce «WhatsApp Papà» di Home Assistant); se no, come prima, da Home Assistant.
CALLMEBOT = "https://api.callmebot.com/whatsapp.php"
# La password della PEC per i programmi di posta (verifica in 2 passaggi di Aruba) scade ogni 6 mesi: si avvisa prima.
# La data è quella di pec.conf, che fonti_casa.py --imposta-pec riscrive quando se ne mette una nuova.
PEC_CONF = os.path.join(CARTELLA_PI, "pec.conf")
PEC_SCADE_GIORNI = 182
PEC_PREAVVISO_GIORNI = 10


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


# Dal trasloco su Aruba (30 ott 2026) il sito vero lo pubblica il server (strumenti/pubblica_server.sh, fatto partire
# ogni minuto da strumenti/pubblica_se_serve.sh): dove c'è ~/sito-stato/ACCESO (cioè sul server, col sito vero lì) una
# pubblicazione si chiede lasciando il file ~/sito-stato/pubblica, non a GitHub (lì c'è solo la copia di riserva), e
# «in corso» vuol dire una pubblicazione del server che sta girando o è già chiesta. Altrove (la sentinella di GitHub)
# resta tutto come prima.
STATO_SERVER = os.path.expanduser("~/sito-stato")


def leggi_json(percorso):
    try:
        with open(percorso, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def sito_sul_server():
    return os.path.exists(os.path.join(STATO_SERVER, "ACCESO"))


def server_in_corso():
    """Una pubblicazione del server chiesta o in corso (il suo lucchetto è preso)."""
    if os.path.exists(os.path.join(STATO_SERVER, "pubblica")):
        return True
    try:
        with open("/tmp/nb_pubblica.lock", "a") as f:
            fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
            fcntl.flock(f, fcntl.LOCK_UN)
        return False
    except OSError:
        return True


def pubblicazione_in_corso(gh):
    if sito_sul_server():
        return server_in_corso()
    corse = gh.chiama("GET", f"repos/{REPO}/actions/workflows/{FLUSSO}/runs?per_page=5").get("workflow_runs", [])
    return any(c["status"] != "completed" for c in corse)


def chiedi_pubblicazione(gh, telegram_recupera=False):
    """Fa partire una pubblicazione: quella del server se il sito vero è lì, se no quella di GitHub."""
    if sito_sul_server():
        if telegram_recupera:
            open(os.path.join(STATO_SERVER, "telegram_recupera"), "w").close()
        open(os.path.join(STATO_SERVER, "pubblica"), "w").close()
    else:
        gh.lancia(FLUSSO, {"telegram_recupera": "1" if telegram_recupera else "0"})


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
    if sito_sul_server():   # le corse di GitHub sono la copia di riserva: conta la pubblicazione del server
        attive = [True] if server_in_corso() else []

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
            chiedi_pubblicazione(gh, recupera)

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
        if sito_sul_server():   # l'esito dell'ultima pubblicazione del server (pubblica_server.sh)
            if server_in_corso():
                rilancia = False   # una pubblicazione è già in corso o chiesta: rimanda lei quello che manca
            elif leggi_json(os.path.join(STATO_SERVER, "ultimo_esito.json")).get("chiusure") is False:
                problemi.append("l'ultima pubblicazione non ha mandato le chiusure su tutti i canali")
                rilancia = True
        else:
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
                chiedi_pubblicazione(gh)
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
        # l'anteprima del canale ha solo gli ultimi 20 messaggi: se non è lì la si cerca (26 ott 2026: la curiosità delle
        # 12 c'era, ma alle 15 era già fuori dall'anteprima e la sentinella rilanciava la pubblicazione ogni mezz'ora)
        link = f"notiziebenevento.it/curiosita/{di_oggi['slug']}/"
        for u in ("https://t.me/s/notiziebenevento", "https://t.me/s/notiziebenevento?q=" + urllib.parse.quote(di_oggi["slug"])):
            req = urllib.request.Request(u, headers={"User-Agent": "Mozilla/5.0 (notiziebenevento.it)"})
            with apri(req) as r:
                if link in r.read().decode("utf-8", "replace"):
                    break
        else:
            mancano.append("sul canale Telegram")
        if mancano:
            problemi.append(f"la curiosità di oggi («{di_oggi['titolo'][:50]}») alle {adesso:%H:%M} non è ancora "
                            + " né ".join(mancano))
            if not pubblicazione_in_corso(gh):
                riparati.append("rilanciata la pubblicazione per la curiosità" + (" (prova: in realtà no)" if prova else ""))
                if not prova:
                    chiedi_pubblicazione(gh)
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
    try:   # gli articoli dei siti ufficiali (dal 25 ott 2026): il file c'è solo da quando gira strumenti/ufficiali.py
        with open(os.path.join(CARTELLA_PI, "archivio", "ufficiali.json"), encoding="utf-8") as f:
            voci += [v for v in json.load(f).get("voci") or [] if isinstance(v, dict)]
    except FileNotFoundError:
        pass
    except (OSError, ValueError):
        return ["non leggo ufficiali.json dell'archivio di casa (~/nb-fonti/archivio)"]
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
        sito = v.get("tipo") == "sito"
        if v.get("fonte") == "da_valutare" and v.get("valutato") != "pubblica":   # decide il proprietario (dal 26 ott)
            if (not v.get("valutato") and arrivata and not v.get("spam")   # lo spam vero si ignora: l'avviso è uno
                    and dt.timedelta(hours=DA_VALUTARE_ORE) < adesso - arrivata < dt.timedelta(days=3)):
                problemi.append(f"DA VALUTARE da {minuti(adesso - arrivata)} minuti il comunicato di "
                                f"{v.get('mittente') or v.get('dominio')} («{str(v.get('titolo'))[:60]}», "
                                f"{v.get('fonte_perche')}): scheda Posta delle statistiche, «Pubblica» o «Non pubblicare»")
            continue
        if (v.get("id") and v["id"] not in visti and v["id"] not in vecchi and arrivata
                and dt.timedelta(minutes=SITO_MAX if sito else COMUNICATO_MAX) < adesso - arrivata < dt.timedelta(hours=24)):
            problemi.append((f"l'articolo del sito di {v.get('mittente')} visto alle {arrivata:%H:%M}" if sito else
                             f"il comunicato di {v.get('mittente') or v.get('dominio')} arrivato alle {arrivata:%H:%M}")
                            + f" («{str(v.get('titolo'))[:60]}») non è ancora stato trattato dal giro lampo "
                            "(~/nb-fonti/comunicati.log)")
        elif (visti.get(v.get("id")) or {}).get("esito") == "sospeso" and arrivata:
            problemi.append(f"IN SOSPESO il comunicato di {v.get('mittente') or v.get('dominio')} arrivato il "
                            f"{arrivata:%d/%m alle %H:%M} («{str(v.get('titolo'))[:60]}»): il Pi non ha letto "
                            + "; ".join(v.get("allegati_non_letti") or ["un allegato"])
                            + ". Va letto a mano (scheda Posta delle statistiche) e pubblicato, o il Pi va aiutato a leggerlo")
    return problemi


def fonti_di_casa(adesso, prova):
    """Le fonti lette da casa si leggono ancora? (punto 8 in cima). Solo sul Pi. Restituisce (problemi, note): i
    problemi vanno nell'avviso, le note solo nel registro (una fonte già avvisata, una che è tornata)."""
    cartella = os.path.join(CARTELLA_PI, "archivio")
    stato_f = os.path.join(CARTELLA_PI, "fonti_ferme.json")
    try:
        with open(stato_f, encoding="utf-8") as f:
            stato = json.load(f)
    except (OSError, ValueError):
        stato = {}
    ferme, piu_recente, albi_bassi = {}, None, False   # ferme: chiave → (da quando, cosa dire, indirizzo da riprovare)
    for nome in sorted(os.listdir(cartella)):
        if not nome.endswith(".json") or nome == "chiusure.json":   # chiusure.json lo controlla il punto 5
            continue
        try:
            with open(os.path.join(cartella, nome), encoding="utf-8") as f:
                d = json.load(f)
            controllato = iso(d["controllato"])
        except (OSError, ValueError, KeyError, TypeError):
            continue
        piu_recente = max(piu_recente or controllato, controllato)
        esito = str(d.get("esito") or "")
        fonte = d.get("fonte") or nome
        indirizzo = d.get("indirizzo") if str(d.get("indirizzo") or "").startswith("http") else ""
        if not esito.startswith("letta") or esito.startswith("letta solo la riserva"):
            try:
                dal = iso(d["ultima_lettura_riuscita"])
            except (KeyError, ValueError, TypeError):
                dal = None
            if not dal or adesso - dal > dt.timedelta(hours=FONTE_FERMA_ORE):
                ferme[nome[:-5]] = (dal, f"{fonte}: {esito[:140]}", indirizzo)
        if nome == "comunicati.json" and str(d.get("pec") or "").startswith("non letta"):   # la PEC del sito
            try:                                                                             # (dal 25 ott 2026)
                dal = iso(d["pec_ultima_lettura"])
            except (KeyError, ValueError, TypeError):
                dal = None
            if not dal or adesso - dal > dt.timedelta(hours=FONTE_FERMA_ORE):
                ferme["pec"] = (dal, f"PEC del sito notiziebenevento@pec.it: {d['pec'][:140]} (comunicati@ si legge lo "
                                     "stesso; se è cambiata la password: fonti_casa.py --imposta-pec)", "")
        if nome == "comunicati.json" and str(d.get("spam") or "").startswith("non letto"):   # lo Spam delle caselle
            try:                                                                                 # (dal 26 ott 2026)
                dal = iso(d["spam_ultima_lettura"])
            except (KeyError, ValueError, TypeError):
                dal = None
            if not dal or adesso - dal > dt.timedelta(hours=FONTE_FERMA_ORE):
                ferme["spam"] = (dal, f"Spam delle caselle: {d['spam'][:160]} (un comunicato messo lì da Aruba non "
                                      "si vedrebbe; la Posta in arrivo si legge lo stesso)", "")
        if nome == "comuni.json":   # gli albi pretori dei Comuni: non c'è l'ora dell'ultima lettura, la si ricorda qui
            m = re.match(r"(\d+) su (\d+)", str(d.get("albi_letti") or ""))
            if m and int(m[1]) < ALBI_MINIMI:
                albi_bassi = True
                dal = iso(stato.get("albi", {}).get("dal") or adesso.isoformat())
                if adesso - dal > dt.timedelta(hours=FONTE_FERMA_ORE):
                    nl = d.get("albi_non_letti") or []
                    ferme["albi"] = (dal, f"albi pretori dei Comuni: letti {m[1]} su {m[2]} (non si leggono "
                                     f"{', '.join(nl[:6])}{'…' if len(nl) > 6 else ''})", albo_di_prova(nl))
                else:
                    stato.setdefault("albi", {"dal": dal.isoformat(timespec="minutes")})
    problemi, note = [], []
    if piu_recente and adesso - piu_recente > dt.timedelta(minutes=ARCHIVIO_FERMO):
        problemi.append(f"le fonti di casa non si aggiornano dalle {piu_recente:%H:%M} (cron di fonti_casa.py, "
                        "~/nb-fonti/fonti.log)")
    nuovo = {}
    for chiave, (dal, cosa, indirizzo) in ferme.items():
        vecchio = stato.get(chiave) or {}
        avvisato = vecchio.get("avvisato")
        quando = f" dalle {dal.astimezone(fuso()):%H:%M del %d/%m}" if dal else ""
        if avvisato and adesso - iso(avvisato) < dt.timedelta(hours=RIPETI_ORE):
            note.append(f"ancora ferma{quando}, già avvisato: {cosa}")
            nuovo[chiave] = vecchio
        else:
            problemi.append(f"fonte ferma{quando}: {cosa}" + (f" [prova: {indirizzo}]" if indirizzo else ""))
            nuovo[chiave] = {"dal": dal.isoformat(timespec="minutes") if dal else "", "avvisato": adesso.isoformat(timespec="minutes")}
    if os.path.exists(PEC_CONF):   # la password della PEC per i programmi di posta: prima che scada
        scade = dt.datetime.fromtimestamp(os.path.getmtime(PEC_CONF), fuso()) + dt.timedelta(days=PEC_SCADE_GIORNI)
        if adesso >= scade - dt.timedelta(days=PEC_PREAVVISO_GIORNI):
            vecchio = stato.get("pec_scade") or {}
            if vecchio.get("avvisato") and adesso - iso(vecchio["avvisato"]) < dt.timedelta(hours=RIPETI_ORE):
                nuovo["pec_scade"] = vecchio
            else:
                problemi.append(f"la password della PEC del sito per i programmi di posta scade verso il {scade:%d/%m/%Y}: "
                                "farne una nuova (webmail PEC → Impostazioni → Account e sicurezza → Password per "
                                "programmi di posta) e rimetterla sul Pi con fonti_casa.py --imposta-pec")
                nuovo["pec_scade"] = {"avvisato": adesso.isoformat(timespec="minutes")}
    for chiave in stato:
        if chiave not in ferme and chiave not in nuovo and stato[chiave].get("avvisato"):
            note.append(f"tornata a funzionare: {chiave}")
    if albi_bassi and "albi" not in ferme:
        nuovo.setdefault("albi", stato["albi"])   # albi sotto soglia da poco: si ricorda da quando
    if not prova:
        with open(stato_f, "w", encoding="utf-8") as f:
            json.dump(nuovo, f, ensure_ascii=False, indent=1)
    return problemi, note


def avvisa_casa(problemi, adesso):
    """L'avviso al proprietario su WhatsApp (Home Assistant) e per email, con lo stesso testo della mail di GitHub.
    Un canale che non va non ferma l'altro. Restituisce cosa è successo, per il registro."""
    testo = f"⚠️ Notizie Benevento, la sentinella ({adesso:%d/%m %H:%M}):\n" + "\n".join(f"• {p}" for p in problemi)
    return manda_a_casa(testo, f"⚠️ Notizie Benevento: {len(problemi)} {'problema' if len(problemi) == 1 else 'problemi'}",
                        "\n\nIl registro è sul Pi: ~/nb-fonti/sentinella.log\n")


def manda_a_casa(testo, oggetto, coda=""):
    """Un messaggio al proprietario su WhatsApp (CallMeBot diretto o Home Assistant) e per email (da comunicati@, a lui): lo usano la
    sentinella e il giro lampo (i comunicati da valutare). Restituisce cosa è successo, per il registro."""
    try:
        with open(AVVISI_CONF, encoding="utf-8") as f:
            conf = json.load(f)
    except (OSError, ValueError):
        try:   # su GitHub: la chiave di CallMeBot dal segreto CALLMEBOT (la mail la manda GitHub, col lavoro in rosso)
            conf = {"callmebot": json.loads(os.environ["CALLMEBOT"])}
        except (KeyError, ValueError):
            return ["avvisi.conf manca: niente WhatsApp né email"]
    esiti = []
    try:
        if conf.get("callmebot"):   # WhatsApp diretto a CallMeBot (solo testo)
            cmb = conf["callmebot"]
            url = CALLMEBOT + "?" + urllib.parse.urlencode({"phone": cmb["telefono"], "text": testo[:1500],
                                                            "apikey": cmb["apikey"]})
            with urllib.request.urlopen(url, timeout=30) as r:
                risposta = r.read().decode("utf-8", "replace")
            if not re.search(r"queued", risposta, re.I):   # CallMeBot risponde 200 anche agli errori, con la spiegazione
                spiega = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", risposta)).strip()
                for segreto in (cmb["telefono"], cmb["apikey"]):
                    spiega = spiega.replace(segreto, "…")
                raise RuntimeError(spiega[:120])
            esiti.append("WhatsApp mandato (CallMeBot)")
        else:   # WhatsApp: il servizio notify di Home Assistant (CallMeBot, solo testo)
            dominio, servizio = conf["whatsapp"].split(".", 1)
            req = urllib.request.Request(f"{conf['ha_url'].rstrip('/')}/api/services/{dominio}/{servizio}", method="POST",
                                         data=json.dumps({"message": testo[:1500]}).encode(),
                                         headers={"Authorization": f"Bearer {conf['ha_token']}",
                                                  "Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=30) as r:
                r.read()
            esiti.append("WhatsApp mandato")
    except Exception as e:
        esiti.append(f"WhatsApp NON mandato ({type(e).__name__}: {str(e)[:120]})")
    if "email" not in conf:
        return esiti
    try:   # email: dalla casella dei comunicati (Aruba)
        import smtplib
        import ssl
        from email.message import EmailMessage
        from email.utils import formataddr, formatdate, make_msgid
        with open(POSTA_CONF, encoding="utf-8") as f:
            posta = json.load(f)
        m = EmailMessage()
        m["From"] = formataddr(("Sentinella di Notizie Benevento", posta["utente"]))
        m["To"] = conf["email"]
        m["Subject"] = oggetto
        m["Date"] = formatdate(localtime=True)
        m["Message-ID"] = make_msgid(domain=posta["utente"].split("@")[1])
        m.set_content(testo + coda)
        with smtplib.SMTP_SSL("smtps.aruba.it", 465, context=ssl.create_default_context(), timeout=60) as s:
            s.login(posta["utente"], posta["password"])
            s.send_message(m)
        esiti.append("email mandata")
    except Exception as e:
        esiti.append(f"email NON mandata ({type(e).__name__}: {str(e)[:120]})")
    return esiti


def albo_di_prova(non_letti):
    """L'indirizzo di uno degli albi non letti, per riprovarlo da GitHub (fonti_casa.ALBI, accanto sul Pi)."""
    try:
        sys.path.insert(0, CARTELLA_PI)
        from fonti_casa import ALBI
        return next(ALBI[n][1] for n in non_letti if n in ALBI)
    except Exception:
        return ""


def da_fuori(avviso):
    """Su GitHub: riprova gli indirizzi «[prova: …]» dell'avviso del Pi e dice se rispondono da fuori."""
    righe = []
    for riga in avviso.split(" | "):
        m = re.search(r"\[prova: (https?://[^\]\s]+)\]", riga)
        riga = re.sub(r"\s*\[prova: [^\]]*\]", "", riga).strip()
        if m and any(h in m[1] for h in NON_DA_FUORI):
            riga += " (da fuori non si può provare: quel sito rifiuta le connessioni dall'estero)"
        elif m:
            try:
                req = urllib.request.Request(m[1], headers={"User-Agent": "Mozilla/5.0 (nb-sentinella)"})
                with urllib.request.urlopen(req, timeout=30) as r:
                    r.read(2000)
                riga += " (da GitHub risponde: il problema è la connessione di casa o un blocco sul nostro indirizzo)"
            except Exception as e:
                riga += f" (non risponde nemmeno da GitHub, {type(e).__name__}: è giù per tutti)"
        if riga:
            righe.append(riga)
    return righe


FARMACIE_GIORNI = 2   # avviso quando i turni delle farmacie sul sito finiscono entro questi giorni


def farmacie(adesso, pi):
    """I turni delle farmacie sul sito (pagina farmacie-di-turno/, strumenti/farmacie.py): ci sono, coprono oggi e i
    prossimi giorni; sul Pi anche se il PDF di Federfarma non si legge (farmacie-errore.json)."""
    problemi = []
    try:
        with apri(f"{SITO}/farmacie.json?sentinella={int(time.time())}") as r:
            d = json.load(r)
        fine = min(d["diurno"][-1]["al"], d["notturno"][-1]["al"])
        if fine <= (adesso.date() + dt.timedelta(days=FARMACIE_GIORNI)).isoformat():
            g = dt.date.fromisoformat(fine)
            problemi.append(f"i turni delle farmacie sul sito finiscono il {g:%d/%m}: Federfarma Benevento non ha ancora "
                            "messo il PDF nuovo (federfarmabenevento.it/turni.html) o il Pi non l'ha mandato")
    except Exception as e:
        problemi.append(f"i turni delle farmacie non ci sono sul sito (farmacie.json: {type(e).__name__})")
    if pi:
        try:
            with open(os.path.join(CARTELLA_PI, "farmacie-errore.json"), encoding="utf-8") as f:
                err = json.load(f)
            problemi.append(f"il PDF dei turni delle farmacie non si legge dalle {iso(err['quando']).astimezone(fuso()):%d/%m %H:%M}"
                            f" ({err.get('errore', '')[:150]}): sul sito restano i turni di prima")
        except (OSError, ValueError, KeyError):
            pass
    return problemi


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sito", default=os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    ap.add_argument("--pi", action="store_true", help="sul Pi: notizie.json da GitHub e avviso tramite la sentinella di GitHub")
    ap.add_argument("--chiave", default=os.path.join(CARTELLA_PI, "github.conf"))
    ap.add_argument("--imposta-chiave", action="store_true")
    ap.add_argument("--prova", action="store_true")
    ap.add_argument("--prova-avviso", action="store_true", help="sul Pi: un avviso di prova su WhatsApp e per email")
    a = ap.parse_args()
    if a.imposta_chiave:
        return imposta_chiave(a.chiave)
    adesso = dt.datetime.now(fuso())
    if a.prova_avviso:
        print(", ".join(avvisa_casa(["PROVA: da adesso gli avvisi della sentinella arrivano anche qui, su WhatsApp e "
                                     "per email. Non c'è niente da fare."], adesso)))
        return
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
    try:
        problemi += farmacie(adesso, a.pi)
    except Exception as e:
        problemi.append(f"non riesco a controllare i turni delle farmacie ({type(e).__name__}: {e})")
    note = []
    if a.pi:
        try:
            p4, note = fonti_di_casa(adesso, a.prova)
            problemi += p4
        except Exception as e:
            problemi.append(f"non riesco a controllare le fonti di casa ({type(e).__name__}: {e})")
    elif os.environ.get("AVVISO_PI", "").strip():   # i problemi visti dal Pi, che da qui non si vedono
        problemi += [f"dal Pi: {x}" for x in da_fuori(os.environ["AVVISO_PI"].strip())]

    ora = f"{adesso:%d/%m %H:%M}"
    for m in riparati:
        print(f"{ora} riparato: {m}" if a.pi else f"::warning::Sentinella: {m}")
    for m in problemi:
        print(f"{ora} PROBLEMA: {m}" if a.pi else f"::error::Sentinella: {m}")
    for m in note:
        print(f"{ora} nota: {m}")
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
        ore = SOSPESO_ORE if any(p.startswith("IN SOSPESO") for p in problemi) else AVVISO_ORE
        if not ultimo or adesso - ultimo > dt.timedelta(hours=ore) - dt.timedelta(minutes=5):
            try:
                gh.lancia("sentinella.yml", {"avviso": " | ".join(problemi)[:1000]})
                print(f"{ora} avviso: lanciata la sentinella di GitHub (mail se resta rosso)")
            except Exception as e:   # WhatsApp ed email partono lo stesso
                print(f"{ora} avviso: sentinella di GitHub NON lanciata ({type(e).__name__}: {e})")
            with open(stato_f, "w", encoding="utf-8") as f:
                json.dump({"avviso": adesso.isoformat(timespec="minutes")}, f)
            print(f"{ora} avviso: {', '.join(avvisa_casa(problemi, adesso))}")
    if problemi and not a.pi:
        server_fermo(adesso, [p for p in problemi if p.startswith("nessun giro dell'agente")])
        sys.exit(1)


def server_fermo(adesso, problemi):
    """Su GitHub (dal trasloco su Aruba, 30 ott 2026): il WhatsApp al proprietario quando il server sembra fermo (il
    sito non risponde, o nessun giro da GIRO_MAX minuti), perché in quel caso la sentinella del server è ferma con lui.
    Gli altri problemi li manda già il server: niente doppioni. Mai quando la sentinella l'ha lanciata il server
    (AVVISO_PI). Al massimo una volta ogni AVVISO_ORE: l'ultimo avviso sta in SENTINELLA_STATO (la cache di GitHub)."""
    if not problemi or not os.environ.get("CALLMEBOT") or os.environ.get("AVVISO_PI", "").strip():
        return
    stato_f = os.path.join(os.environ.get("SENTINELLA_STATO") or ".", "avviso_server.json")
    try:
        with open(stato_f, encoding="utf-8") as f:
            ultimo = iso(json.load(f)["avviso"])
    except (OSError, ValueError, KeyError):
        ultimo = None
    if ultimo and adesso - ultimo < dt.timedelta(hours=AVVISO_ORE) - dt.timedelta(minutes=5):
        print(f"Sentinella: WhatsApp già mandato alle {ultimo.astimezone(fuso()):%H:%M}")
        return
    testo = ("⚠️ Notizie Benevento: il server Aruba sembra fermo (lo dice la sentinella di GitHub, "
             f"{adesso.astimezone(fuso()):%d/%m %H:%M}):\n" + "\n".join(f"• {p}" for p in problemi))
    print("Sentinella:", ", ".join(manda_a_casa(testo, "⚠️ Notizie Benevento: il server sembra fermo")))
    os.makedirs(os.path.dirname(stato_f) or ".", exist_ok=True)
    with open(stato_f, "w", encoding="utf-8") as f:
        json.dump({"avviso": adesso.isoformat(timespec="minutes")}, f)


if __name__ == "__main__":
    try:
        main()
    except Exception as e:   # sul Pi nel log una riga, non un traceback
        print(f"{dt.datetime.now(fuso()):%d/%m %H:%M} ERRORE: {e}" if "--pi" in sys.argv else f"::error::Sentinella: {e}")
        if "--pi" not in sys.argv:   # su GitHub: il sito non risponde = probabilmente il server è fermo
            server_fermo(dt.datetime.now(dt.timezone.utc), [f"la sentinella non riesce a fare i controlli, forse il sito non risponde ({type(e).__name__}: {str(e)[:150]})"])
        sys.exit(1)
