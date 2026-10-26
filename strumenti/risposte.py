#!/usr/bin/env python3
"""La risposta di cortesia a chi ci manda un comunicato: appena il comunicato è sul sito, una mail breve col link
dell'articolo, in risposta alla sua mail.

Voluta dal proprietario il 26 ott 2026 («una email di ringraziamento sì, mi sembra una cortesia corretta»): chi ci
manda un comunicato vede subito che è uscito e ha il link pronto da mettere sul suo sito o sui social. Il testo
(TESTO, qui sotto) l'ha approvato lui: non si cambia senza di lui.

Gira sul Pi di casa ogni 5 minuti (cron, con flock -n), dove stanno le password delle caselle (posta.conf e pec.conf,
lette da qui e mai stampate). Ogni volta:
1. legge comunicati_visti.json dal sito: i comunicati con esito «pubblicato» o «gia_nel_sito» e la loro notizia; quelli
   trattati prima che le risposte partissero («dal» in risposte.json) non hanno risposta;
2. prende solo le mail, non gli articoli dei siti ufficiali (id «u…»): in comunicati.json dell'archivio c'è il link
   «posta:<Message-ID>» e la mail si ritrova nelle caselle comunicati@ e PEC, aperte in sola lettura;
3. controlla che la pagina della notizia sia online (se la notizia è stata unita a un'altra, il link è quello della
   notizia rimasta); se dopo ATTESA_PAGINA ore non c'è ancora, lascia perdere;
4. risponde a chi l'ha mandata (Reply-To se c'è, se no From; mai a una lista di posta, a un «noreply», a una mail
   automatica o a una nostra casella): dalla PEC se il comunicato è arrivato da una PEC, se no da comunicati@. Una copia
   va nella posta inviata di quella casella.

Niente doppioni: una sola risposta per comunicato, e una sola per indirizzo e notizia (due comunicati dello stesso
mittente finiti nella stessa notizia: una risposta). Lo stato è in ~/nb-fonti/risposte.json, sul Pi e fuori
dall'archivio che va su GitHub: prima di mandare si scrive «in invio», dopo «mandata». Se il server risponde con un
errore la mail non è partita e si riprova al giro dopo (al massimo TENTATIVI volte); se invece il collegamento cade a
metà invio la mail resta «da controllare» e non si rimanda: meglio una risposta persa che due. Al massimo PER_GIRO
risposte ogni volta e PER_GIORNO al giorno: se un errore facesse partire troppe mail, si ferma da solo.

Chi risponde alla nostra risposta («grazie») non manda un comunicato: fonti_casa.py lo riconosce dal Message-ID
(«.nb-risposta@») o dalla nostra frase citata e non lo passa al giro lampo.

Uso sul Pi:  python3 ~/nb-fonti/sentinella/risposte.py           (dal cron, ogni 5 minuti; la prima volta segna «dal»)
             python3 ~/nb-fonti/sentinella/risposte.py --prova   (cosa farebbe con i comunicati di comunicati_visti.json,
                                                                  anche quelli di prima di «dal», senza mandare niente)
             python3 ~/nb-fonti/sentinella/risposte.py --prova-a redazione@notiziebenevento.it --comunicato ID [--da PEC]
                                                                 (la risposta vera di quel comunicato, mandata a una
                                                                  nostra casella con «[PROVA]» nell'oggetto)
"""
import argparse
import datetime as dt
import email
import email.header
import email.utils
import html
import imaplib
import json
import os
import re
import smtplib
import ssl
import sys
import time
import urllib.error
import urllib.request
from email.message import EmailMessage

QUI = os.path.dirname(os.path.abspath(__file__))
CARTELLA = os.environ.get("NB_FONTI_CARTELLA") or os.path.expanduser("~/nb-fonti")
sys.path.insert(0, CARTELLA)
sys.path.insert(0, QUI)
import fonti_casa as F   # noqa: E402  (le caselle, la busta PEC, il link di una mail)

SITO = "https://notiziebenevento.it"
STATO = os.path.join(CARTELLA, "risposte.json")
NOME = "Notizie Benevento"
ESITI = ("pubblicato", "gia_nel_sito")
CASELLE = {   # da dove si risponde: (file con indirizzo e password, server IMAP, server SMTP)
    "comunicati@": (F.POSTA_CONF, F.POSTA_SERVER, "smtps.aruba.it"),
    "PEC": (F.PEC_CONF, F.PEC_SERVER, "smtps.pec.aruba.it"),
}
TESTO = """Buongiorno,
il vostro comunicato è online su Notizie Benevento:
{link}

Grazie per averci scritto.
La redazione di Notizie Benevento

Messaggio automatico.
"""
PER_GIRO, PER_GIORNO = 5, 30
GIORNI, MAIL_MAX = 7, 80   # la mail si cerca tra quelle degli ultimi 7 giorni, le ultime 80 di ogni casella
ATTESA_PAGINA = 3          # ore dal giro lampo
TENTATIVI = 12             # giri (uno ogni 5 minuti: un'ora) con la casella che non si collega
TIENI = 60                 # giorni di stato
ERRORE_ORE = 1             # lo stesso errore nel registro al massimo una volta all'ora
INDIRIZZO = re.compile(r"^[^@\s<>()\[\],;:\"]+@[a-z0-9-]+(\.[a-z0-9-]+)*\.[a-z]{2,}$", re.I)
NOREPLY = re.compile(r"(^|[._+-])(no-?reply|do-?not-?reply|non-?rispondere|mailer-daemon|postmaster|bounces?)"
                     r"([._+-]|$)", re.I)
RISPOSTA = re.compile(r"^\s*((re|r|ri)\s*:\s*)+", re.I)
CANONICO = re.compile(r'<link rel="canonical" href="([^"]+)"')
NOSTRO_DOMINIO = "notiziebenevento.it"


def adesso():
    return dt.datetime.now(F.fuso())


def scrivi(testo):
    print(f"{adesso():%d/%m %H:%M} {testo}", flush=True)


def leggi(p, vuoto):
    try:
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return vuoto


def salva(stato):
    tmp = STATO + ".tmp"
    vecchio = os.umask(0o077)
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(stato, f, ensure_ascii=False, indent=1)
        os.replace(tmp, STATO)
    finally:
        os.umask(vecchio)


def dec(x):
    try:
        return str(email.header.make_header(email.header.decode_header(x or ""))).strip()
    except (ValueError, LookupError, UnicodeDecodeError):
        return str(x or "").strip()


def data(x):
    try:
        return dt.datetime.fromisoformat(str(x))
    except (TypeError, ValueError):
        return None


def scarica(url):
    """(stato HTTP, testo) di una pagina del sito, sempre fresca (non quella tenuta dalla cache)."""
    r = urllib.request.Request(f"{url}{'&' if '?' in url else '?'}t={int(time.time())}",
                               headers={"User-Agent": "NotizieBenevento-risposte/1.0"})
    try:
        with urllib.request.urlopen(r, timeout=30) as x:
            return x.status, x.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, ""


def visti():
    s, t = scarica(SITO + "/comunicati_visti.json")
    if s != 200:
        raise RuntimeError(f"comunicati_visti.json del sito: risposta {s}")
    return json.loads(t).get("visti") or {}


def pagina(notizia):
    """Il link della notizia sul sito, o '' se la pagina non c'è ancora. Una notizia unita a un'altra ha la pagina che
    rimanda a quella rimasta: il link è quello."""
    s, t = scarica(f"{SITO}/notizia/{notizia}/")
    m = CANONICO.search(t) if s == 200 else None
    link = html.unescape(m[1]) if m else ""
    return link if link.startswith(SITO + "/notizia/") else ""


def destinatario(m):
    """(indirizzo, motivo): a chi si risponde, o '' e il motivo per cui no."""
    if (m.get("Auto-Submitted") or "no").strip().lower() != "no" or m.get("X-Autoreply") or m.get("X-Autorespond") \
            or (m.get("Precedence") or "").strip().lower() == "junk":
        return "", "mail automatica"
    lista = " ".join(str(m.get(h) or "") for h in ("List-Id", "List-Post")).lower()
    # da una lista di posta il Reply-To può essere la lista intera: si risponde solo a chi l'ha scritta
    risp = [] if lista.strip() else email.utils.getaddresses([dec(x) for x in m.get_all("Reply-To") or []])
    motivo = "nessun indirizzo valido"
    for _, a in risp + email.utils.getaddresses([dec(x) for x in m.get_all("From") or []]):
        a = a.strip()
        if not INDIRIZZO.match(a):
            continue
        dominio = a.rsplit("@", 1)[1].lower()
        if dominio == NOSTRO_DOMINIO or dominio.endswith("." + NOSTRO_DOMINIO) or a.lower() == F.PEC_INDIRIZZO:
            motivo = "è una nostra casella"
        elif NOREPLY.search(a.rsplit("@", 1)[0]):
            motivo = "indirizzo che non riceve risposte"
        elif a.lower() in lista:
            motivo = "è una lista di posta"
        else:
            return a, ""
    return "", motivo


def oggetto(m):
    s = RISPOSTA.sub("", " ".join(dec(m.get("Subject")).split()))
    return "Re: " + s if s and s != "(senza oggetto)" else "Il vostro comunicato su Notizie Benevento"


def messaggio(conf, a, m, link, prova=False):
    r = EmailMessage()
    r["From"] = email.utils.formataddr((NOME, conf["utente"]))
    r["To"] = a
    r["Subject"] = ("[PROVA] " if prova else "") + oggetto(m)
    r["Date"] = email.utils.formatdate(localtime=True)
    r["Message-ID"] = email.utils.make_msgid(idstring="nb-risposta", domain=conf["utente"].rsplit("@", 1)[1])
    mid = " ".join(str(m.get("Message-ID") or "").split())
    if mid:
        r["In-Reply-To"] = mid
        prima = [x for x in str(m.get("References") or "").split() if x != mid]
        r["References"] = " ".join(prima[-10:] + [mid])
    r["Auto-Submitted"] = "auto-replied"         # RFC 3834: le loro risposte automatiche non ci rispondono
    r["X-Auto-Response-Suppress"] = "All"        # (Outlook ed Exchange: niente «fuori sede» in risposta)
    r.set_content(TESTO.format(link=link), cte="quoted-printable")
    return r


def conf_di(casella):
    conf = leggi(CASELLE[casella][0], None)
    if not isinstance(conf, dict) or not conf.get("utente") or not conf.get("password"):
        raise RuntimeError(f"casella {casella} non collegata ({os.path.basename(CASELLE[casella][0])})")
    return conf


def cerca(casella, cercati):
    """Le mail di una casella con il link tra i cercati: {link: (mail, tipo)}, tipo come in fonti_casa.busta_pec().
    Sola lettura (EXAMINE e BODY.PEEK: niente segnato come letto). Per le PEC la mail vera è dentro la busta."""
    conf = conf_di(casella)
    trovate = {}
    with imaplib.IMAP4_SSL(conf.get("server", CASELLE[casella][1]), 993, timeout=60) as M:
        M.login(conf["utente"], conf["password"])
        M.select("INBOX", readonly=True)
        _, num = M.search(None, "SINCE", (dt.date.today() - dt.timedelta(days=GIORNI)).strftime("%d-%b-%Y"))
        numeri = [n.decode() for n in num[0].split()[-MAIL_MAX:]]
        if not numeri:
            return trovate
        _, dati = M.fetch(",".join(numeri), "(BODY.PEEK[HEADER])")
        for x in dati:
            if not isinstance(x, tuple):
                continue
            h, tipo = email.message_from_bytes(x[1]), ""
            if h.get("X-Ricevuta"):
                continue
            if h.get("X-Trasporto"):   # una busta PEC: la mail vera è l'allegato postacert.eml
                _, d = M.fetch(x[0].split()[0].decode(), "(BODY.PEEK[])")
                h, tipo = F.busta_pec(email.message_from_bytes(d[0][1]))
                if tipo == "ricevuta":
                    continue
            link = F.link_posta(h)
            if link in cercati and link not in trovate:
                trovate[link] = (h, tipo)
    return trovate


def cartella_inviata(imap):
    """La cartella della posta inviata (quella col segno \\Sent, o col nome solito)."""
    _, righe = imap.list()
    nomi = []
    for r in righe or []:
        r = r.decode("utf-8", "replace")
        nome = r.rsplit(' "', 1)[-1].rstrip('"') if r.endswith('"') else r.rsplit(" ", 1)[-1]
        if "\\Sent" in r:
            return nome
        nomi.append(nome)
    return next((n for n in ("INBOX.Sent", "Sent", "INBOX.Posta inviata", "Posta inviata") if n in nomi), None)


def copia_in_inviata(casella, r):
    """Una copia nella posta inviata, così si vede dalla webmail e dalla scheda Posta (una comodità: è già partita)."""
    try:
        conf = conf_di(casella)
        with imaplib.IMAP4_SSL(conf.get("server", CASELLE[casella][1]), 993, timeout=60) as imap:
            imap.login(conf["utente"], conf["password"])
            c = cartella_inviata(imap)
            if not c:
                return "nessuna cartella della posta inviata"
            imap.append(f'"{c}"', "\\Seen", imaplib.Time2Internaldate(time.time()), r.as_bytes())
            return f"copia in «{c}»"
    except Exception as e:
        return f"copia non salvata ({type(e).__name__})"


class Invio:
    """Le connessioni SMTP del giro, una per casella, aperte solo quando servono."""

    def __init__(self):
        self.s = {}

    def apri(self, casella):
        """Collegamento e accesso: un errore qui vuol dire che non è partito niente."""
        if casella not in self.s:
            conf = conf_di(casella)
            s = smtplib.SMTP_SSL(CASELLE[casella][2], 465, context=ssl.create_default_context(), timeout=60)
            try:
                s.login(conf["utente"], conf["password"])
            except Exception:
                s.close()
                raise
            self.s[casella] = (s, conf)
        return self.s[casella][1]

    def manda(self, casella, r):
        self.s[casella][0].send_message(r)

    def lascia(self, casella):
        """Dopo un errore il collegamento non si riusa: al prossimo invio se ne apre uno nuovo."""
        s, _ = self.s.pop(casella, (None, None))
        try:
            s and s.close()
        except Exception:
            pass

    def chiudi(self):
        for s, _ in self.s.values():
            try:
                s.quit()
            except Exception:
                pass


def comunicati_mail():
    """Le mail dell'archivio (comunicati.json): id → voce."""
    d = leggi(os.path.join(F.ARCHIVIO, "comunicati.json"), {})
    return {v["id"]: v for v in d.get("voci") or [] if isinstance(v, dict) and v.get("id")
            and v.get("tipo") != "sito" and str(v.get("link") or "").startswith("posta:")}


def errore(stato, testo):
    """Un errore del giro nel registro, lo stesso al massimo una volta ogni ERRORE_ORE."""
    e = stato.get("errore") or {}
    ora = adesso()
    q = data(e.get("quando"))
    if e.get("testo") != testo or not q or ora - q > dt.timedelta(hours=ERRORE_ORE):
        scrivi("ERRORE: " + testo)
        stato["errore"] = {"testo": testo, "quando": ora.isoformat(timespec="minutes")}


def giro(stato, prova=False):
    """Un giro: le risposte da mandare. Restituisce 0, o 1 se qualcosa non è andato."""
    ora = adesso()
    fatte = stato.setdefault("fatte", {})
    dal = None if prova else data(stato.get("dal"))
    try:
        v = visti()
    except Exception as e:
        errore(stato, f"non leggo comunicati_visti.json dal sito ({type(e).__name__}: {e})"[:300])
        return 1
    mail = comunicati_mail()

    def segna(cid, cosa, **altro):
        if prova:
            scrivi(f"[prova] {cid}: {cosa}" + "".join(f" · {k}: {x}" for k, x in altro.items() if x))
            return
        fatte[cid] = {"stato": cosa, "quando": ora.isoformat(timespec="minutes"),
                      **{k: x for k, x in altro.items() if x not in (None, "")}}

    da_fare = []
    for cid, e in v.items():
        if not isinstance(e, dict) or e.get("esito") not in ESITI or not e.get("notizia"):
            continue
        if cid in fatte and fatte[cid].get("stato") != "errore":
            continue
        quando = data(e.get("quando"))
        if dal and (not quando or quando < dal):
            continue
        if cid not in mail:
            if not cid.startswith("u"):   # gli articoli dei siti ufficiali non hanno nessuno a cui rispondere
                segna(cid, "saltata", motivo="non è una mail dell'archivio dei comunicati")
            continue
        da_fare.append((quando or ora, cid, e))
    if not da_fare:
        return 0
    da_fare.sort(key=lambda x: x[0])

    pronti = []
    for quando, cid, e in da_fare:
        link = pagina(e["notizia"])
        if link:
            pronti.append((cid, e, link))
        elif ora - quando > dt.timedelta(hours=ATTESA_PAGINA):
            segna(cid, "saltata", motivo=f"la pagina di {e['notizia']} non è online", notizia=e["notizia"])
        elif prova:
            scrivi(f"[prova] {cid}: la pagina di {e['notizia']} non è ancora online, aspetto")
    if not pronti:
        return 0

    cercati = {mail[cid]["link"] for cid, _, _ in pronti}
    trovate, non_lette = {}, []
    for casella in CASELLE:
        try:
            for l, (m, tipo) in cerca(casella, cercati - set(trovate)).items():
                trovate[l] = (m, tipo)
        except Exception as e:
            non_lette.append(casella)
            errore(stato, f"non leggo la casella {casella} ({type(e).__name__}: {e})"[:300])

    invio, esito, guaste, mandate_oggi = Invio(), 0, set(), sum(
        1 for x in fatte.values() if x.get("stato") == "mandata" and str(x.get("quando", ""))[:10] == ora.date().isoformat())
    mandate_ora = 0
    try:
        for cid, e, link in pronti:
            voce = mail[cid]
            chi = f"{voce.get('mittente')} (@{voce.get('dominio')})"
            vecchio = fatte.get(cid) or {}
            tentativi = int(vecchio.get("tentativi") or 0)
            if voce["link"] not in trovate:
                if non_lette and tentativi + 1 < TENTATIVI:
                    segna(cid, "errore", motivo="casella non letta", tentativi=tentativi + 1, notizia=link)
                else:
                    segna(cid, "saltata", motivo="la mail non è più nelle caselle", notizia=link)
                continue
            m, tipo = trovate[voce["link"]]
            a, motivo = destinatario(m)
            if not a:
                segna(cid, "saltata", motivo=motivo, notizia=link)
                if not prova:
                    scrivi(f"nessuna risposta a {chi} per {cid}: {motivo}")
                continue
            if any(x.get("a", "").lower() == a.lower() and x.get("notizia") == link
                   and x.get("stato") in ("mandata", "in invio", "da controllare") for k, x in fatte.items() if k != cid):
                segna(cid, "saltata", motivo="a questo indirizzo è già partita la risposta per la stessa notizia",
                      a=a, notizia=link)
                continue
            casella = "PEC" if tipo == "pec" else "comunicati@"
            if prova:
                scrivi(f"[prova] {cid}: risponderei da {casella} a {a} ({chi}) · «{oggetto(m)}» · {link}")
                continue
            if casella in guaste:   # non si collega: niente altri tentativi di accesso in questo giro
                segna(cid, "errore", tentativi=tentativi, casella=casella, a=a, notizia=link, motivo="casella non collegata")
                continue
            if mandate_ora >= PER_GIRO or mandate_oggi >= PER_GIORNO:
                errore(stato, f"troppe risposte ({mandate_ora} in questo giro, {mandate_oggi} oggi): mi fermo, "
                              "le altre aspettano il giro dopo")
                break
            try:
                conf = invio.apri(casella)
            except Exception as x:
                guaste.add(casella)
                n = tentativi + 1
                segna(cid, "errore" if n < TENTATIVI else "non mandata", tentativi=n, casella=casella, a=a,
                      notizia=link, motivo=f"{type(x).__name__}: {x}"[:200])
                scrivi(f"risposta a {chi} per {cid} non partita: {casella} non si collega ({type(x).__name__}: "
                       f"{x})"[:300] + ("" if n < TENTATIVI else " — lascio perdere"))
                esito = 1
                continue
            r = messaggio(conf, a, m, link)
            segna(cid, "in invio", casella=casella, a=a, notizia=link, message_id=r["Message-ID"])
            salva(stato)   # prima di mandare: se si ferma qui, la mail non riparte due volte
            try:
                invio.manda(casella, r)
            except smtplib.SMTPRecipientsRefused as x:
                segna(cid, "rifiutata", casella=casella, a=a, notizia=link, motivo=str(x)[:200])
                scrivi(f"risposta a {chi} per {cid}: indirizzo {a} rifiutato dal server ({str(x)[:150]})")
                continue
            except smtplib.SMTPResponseException as x:   # il server ha detto no: la mail non è partita
                n = tentativi + 1
                cosa = "errore" if 400 <= x.smtp_code < 500 and n < TENTATIVI else "rifiutata"
                segna(cid, cosa, casella=casella, a=a, notizia=link, tentativi=n, motivo=f"{x.smtp_code} {x.smtp_error!r}"[:200])
                scrivi(f"risposta a {chi} per {cid} non partita: {casella} risponde {x.smtp_code} "
                       f"{x.smtp_error!r}"[:300])
                invio.lascia(casella)
                esito = 1
                continue
            except Exception as x:   # collegamento caduto a metà: non si sa se è partita, non si rimanda
                segna(cid, "da controllare", casella=casella, a=a, notizia=link, message_id=r["Message-ID"],
                      motivo=f"{type(x).__name__}: {x}"[:200])
                scrivi(f"DA CONTROLLARE: risposta a {chi} per {cid}, invio interrotto ({type(x).__name__}: {x}); "
                       "non la rimando")
                invio.lascia(casella)
                esito = 1
                continue
            mandate_ora += 1
            mandate_oggi += 1
            segna(cid, "mandata", casella=casella, a=a, notizia=link, message_id=r["Message-ID"])
            salva(stato)
            scrivi(f"risposta mandata da {casella} a {a} ({chi}) per il comunicato {cid} → {link}; "
                   + copia_in_inviata(casella, r))
    finally:
        invio.chiudi()
    return esito


def prova_a(indirizzo, cid, da=None):
    """La risposta vera di un comunicato, mandata a una nostra casella con «[PROVA]» nell'oggetto. Lo stato non cambia."""
    if not (indirizzo.lower().endswith("@" + NOSTRO_DOMINIO) or indirizzo.lower() == F.PEC_INDIRIZZO):
        sys.exit("--prova-a solo verso una nostra casella (…@notiziebenevento.it o la PEC del sito)")
    e = visti().get(cid)
    if not e or e.get("esito") not in ESITI:
        sys.exit(f"{cid}: in comunicati_visti.json non è «pubblicato» né «gia_nel_sito»")
    voce = comunicati_mail().get(cid)
    if not voce:
        sys.exit(f"{cid}: non è una mail di comunicati.json")
    link = pagina(e["notizia"])
    if not link:
        sys.exit(f"{cid}: la pagina di {e['notizia']} non è online")
    trovate = {}
    for casella in CASELLE:
        trovate.update(cerca(casella, {voce["link"]} - set(trovate)))
    if voce["link"] not in trovate:
        sys.exit(f"{cid}: la mail non è nelle caselle")
    m, tipo = trovate[voce["link"]]
    a, motivo = destinatario(m)
    casella = da or ("PEC" if tipo == "pec" else "comunicati@")
    print(f"il cron risponderebbe a: {a or '(nessuno: ' + motivo + ')'} da {'PEC' if tipo == 'pec' else 'comunicati@'}")
    invio = Invio()
    try:
        r = messaggio(invio.apri(casella), indirizzo, m, link, prova=True)
        invio.manda(casella, r)
    finally:
        invio.chiudi()
    print(f"prova mandata da {casella} a {indirizzo}: «{r['Subject']}» {r['Message-ID']}; {copia_in_inviata(casella, r)}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--prova", action="store_true", help="dice cosa farebbe, senza mandare e senza scrivere lo stato")
    ap.add_argument("--prova-a", metavar="INDIRIZZO", help="manda la risposta di --comunicato a una nostra casella")
    ap.add_argument("--comunicato", metavar="ID")
    ap.add_argument("--da", choices=list(CASELLE), help="con --prova-a: la casella da cui mandarla")
    a = ap.parse_args()
    if a.prova_a:
        if not a.comunicato:
            ap.error("--prova-a vuole anche --comunicato")
        return prova_a(a.prova_a, a.comunicato, a.da)
    stato = leggi(STATO, None)
    if a.prova:
        return giro(stato if isinstance(stato, dict) else {}, prova=True)
    if not isinstance(stato, dict) or not stato.get("dal"):
        ora = adesso().isoformat(timespec="minutes")
        salva({"nota": "Le risposte di cortesia a chi ci manda un comunicato (strumenti/risposte.py): «dal» = da "
                       "quando partono, «fatte» = comunicato → stato.", "dal": ora, "fatte": {}})
        scrivi(f"risposte di cortesia attive: rispondo ai comunicati pubblicati da adesso ({ora})")
        return 0
    prima = json.dumps(stato, sort_keys=True)
    esito = giro(stato)
    limite = (adesso() - dt.timedelta(days=TIENI)).isoformat()
    stato["fatte"] = {k: x for k, x in stato.get("fatte", {}).items() if str(x.get("quando", "")) >= limite}
    if json.dumps(stato, sort_keys=True) != prima:
        salva(stato)
    return esito


if __name__ == "__main__":
    sys.exit(main() or 0)
