#!/usr/bin/env python3
"""La posta del sito da leggere nelle statistiche (scheda «Posta»): la PEC notiziebenevento@pec.it, redazione@ e
comunicati@notiziebenevento.it, lette in diretta dal Pi di casa.

Voluto dal proprietario il 25 ott 2026: «in statistiche una altra pagina, una sorta di outlook dove posso leggere
anche le email di notiziebenevento@pec.it, redazione@notiziebenevento.it e comunicati@notiziebenevento.it… con
etichette da quale casella provengono»; e poi «io voglio solo leggerle, non inviare e altro, compreso allegati».

I comunicati dei mittenti non ufficiali (dal 26 ott 2026: lui, «la pubblicazione dei comunicati istantanea solo da fonti
ufficiali, un tizio che manda qualcosa dobbiamo valutarla», «i comunicati non ufficiali da valutare io») qui hanno tre
pulsanti: «Pubblica», «Pubblica e fidati del mittente», «Non pubblicare» (/api/valuta). La decisione va in
~/nb-fonti/valutati.json (e il mittente in mittenti_fidati.json), e subito parte la lettura della posta col giro lampo,
come quando arriva una mail: il comunicato approvato esce in pochi minuti.

SOLA LETTURA, tranne una cosa. Le caselle si aprono con EXAMINE e i messaggi con BODY.PEEK: aprire una mail non la segna
come letta, e non si sposta, non si cancella, non si manda niente. L'unica cosa che la pagina cambia è il segno di
letta di una mail, col pulsante «Segna come letta» / «Segna come non letta» (voluto dal proprietario il 25 ott 2026:
«metti un pulsante letto e il contrario», dopo aver letto una mail nella pagina e trovato il pallino ancora acceso):
/api/segna, solo il flag \\Seen di quel messaggio, e la cartella torna subito in sola lettura.
Gli allegati si aprono (immagini e PDF) o si scaricano; dei .docx, .doc, .odt e .rtf si legge anche il testo, dei .p7m firmati (le PEC
della PA) il documento che c'è dentro.

Perché qui e non nei dati delle statistiche: sono mail di altre persone, non vanno pubblicate sul sito neanche
cifrate. Restano nelle caselle; il Pi le legge quando la pagina le chiede e non ne tiene copia su disco (solo in
memoria, gli elenchi, per andare veloce).

Sicurezza:
- ascolta solo su 127.0.0.1:8109; da fuori ci si arriva da Caddy, https://casalego.duckdns.org:36092/posta/;
- ogni richiesta vuole un gettone, che /posta/api/entra dà solo a chi ha la chiave delle statistiche (quella che la
  pagina ricava dalla parola d'ordine e che ha già in memoria): il Pi la prova su statistiche/dati.json del sito, che
  con la chiave giusta si apre; se la parola d'ordine delle statistiche cambia, cambia anche qui, da sola;
- dopo FALLITI_MAX tentativi sbagliati in un'ora da uno stesso indirizzo, e TENTATIVI_MAX in tutto, /entra si ferma;
- risposte solo alla pagina del sito (CORS), mai in cache; gli HTML delle mail li mostra la pagina in un riquadro
  chiuso (sandbox, niente script, immagini da fuori solo se si chiede).

Le password delle caselle sono quelle già sul Pi: posta.conf (comunicati@, fonti_casa.py --imposta-posta),
pec.conf (la PEC, fonti_casa.py --imposta-pec) e redazione.conf (questo programma, --imposta redazione).

Uso:  python3 posta_web.py                        (il servizio: nb-posta.service)
      python3 posta_web.py --imposta redazione    (collega redazione@notiziebenevento.it: chiede la password)
      python3 posta_web.py --prova                (legge le caselle e stampa cosa vede, senza servizio)
"""
import argparse
import base64
import datetime as dt
import email
import email.header
import email.policy
import email.utils as eu
import hashlib
import html
import imaplib
import json
import os
import re
import secrets
import subprocess
import sys
import tempfile
import threading
import time
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

CARTELLA = os.environ.get("NB_FONTI_CARTELLA") or os.path.expanduser("~/nb-fonti")
sys.path.insert(0, CARTELLA)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import fonti_casa as F   # noqa: E402  (la busta PEC, i nomi degli allegati, i testi dei .docx, gli id dei comunicati)
# la lettura della posta col giro lampo, come la lancia posta_diretta.py quando arriva una mail (stessi lucchetti)
LETTURA = ["/usr/bin/flock", "-w", "240", "/tmp/nb_comunicati.lock", "/bin/sh", "-c",
           f"/usr/bin/flock -w 240 /tmp/nb_fonti.lock /usr/bin/timeout 120 /usr/bin/python3 {CARTELLA}/fonti_casa.py "
           f"--solo comunicati >> {CARTELLA}/fonti.log 2>&1; /usr/bin/timeout 90 /usr/bin/python3 "
           f"{CARTELLA}/sentinella/comunicati_lampo.py >> {CARTELLA}/comunicati.log 2>&1"]

INDIRIZZO, PORTA = "127.0.0.1", 8109
SITO = "https://notiziebenevento.it"
ORIGINI = {SITO, "https://www.notiziebenevento.it", "http://127.0.0.1:8765", "http://localhost:8765"}
STATISTICHE = os.environ.get("NB_POSTA_STATISTICHE") or SITO + "/statistiche/dati.json"   # la variabile: per le prove
VISTI = SITO + "/comunicati_visti.json"
CASELLE = [   # l'ordine è quello delle etichette nella pagina
    {"id": "pec", "nome": "PEC", "indirizzo": "notiziebenevento@pec.it", "conf": "pec.conf",
     "server": "imaps.pec.aruba.it", "webmail": "https://webmail.pec.it/"},
    {"id": "redazione", "nome": "Redazione", "indirizzo": "redazione@notiziebenevento.it", "conf": "redazione.conf",
     "server": "imaps.aruba.it", "webmail": "https://webmail.aruba.it/"},
    {"id": "comunicati", "nome": "Comunicati", "indirizzo": "comunicati@notiziebenevento.it", "conf": "posta.conf",
     "server": "imaps.aruba.it", "webmail": "https://webmail.aruba.it/"},
]
PER_ID = {c["id"]: c for c in CASELLE}
CARTELLE = [("inbox", "In arrivo"), ("sent", "Inviati"), ("spam", "Spam"), ("trash", "Cestino")]
PER_PAGINA = 50
TIENI = 400                 # messaggi per cartella di cui si tiene il riassunto in memoria
GRANDE = 3_000_000          # byte: sopra, per l'elenco si leggono solo le intestazioni
GETTONE_ORE = 12
FALLITI_MAX, TENTATIVI_MAX = 8, 40   # all'ora: per indirizzo, in tutto
ANTEPRIMA = 180
IMMAGINI_VEDIBILI = {"image/jpeg", "image/png", "image/gif", "image/webp"}
FIRME = {"application/pkcs7-signature", "application/x-pkcs7-signature"}   # la firma della mail, non un allegato
CID_MAX = 3_000_000         # byte di immagini «nel testo» (cid:) messe dentro l'HTML


def dec(x):
    try:
        return str(email.header.make_header(email.header.decode_header(x or ""))).strip()
    except (ValueError, LookupError, UnicodeDecodeError):
        return str(x or "").strip()


def adesso():
    return dt.datetime.now(F.fuso())


# ---------------------------------------------------------------- le caselle (IMAP, sola lettura)

class Casella:
    """Una casella: una connessione IMAP tenuta aperta (si riapre se cade), le cartelle e i riassunti in memoria."""

    def __init__(self, c):
        self.c, self.M, self.lock = c, None, threading.Lock()
        self.cartelle = None    # tipo → nome IMAP
        self.riassunti = {}     # (cartella, uidvalidity, uid) → riassunto
        self.errore = ""

    def conf(self):
        with open(os.path.join(CARTELLA, self.c["conf"]), encoding="utf-8") as f:
            return json.load(f)

    def collegata(self):
        return os.path.exists(os.path.join(CARTELLA, self.c["conf"]))

    def imap(self):
        if self.M is not None:
            try:
                if self.M.noop()[0] == "OK":
                    return self.M
            except Exception:
                pass
            self.chiudi()
        conf = self.conf()
        M = imaplib.IMAP4_SSL(conf.get("server", self.c["server"]), 993, timeout=40)
        M.login(conf["utente"], conf["password"])
        self.M = M
        return M

    def chiudi(self):
        try:
            if self.M is not None:
                self.M.logout()
        except Exception:
            pass
        self.M = None

    def trova_cartelle(self, M):
        if self.cartelle is not None:
            return self.cartelle
        trovate = {"inbox": "INBOX"}
        _, righe = M.list()
        for r in righe or []:
            r = r.decode("utf-8", "replace") if isinstance(r, bytes) else str(r)
            m = re.match(r'\((?P<att>[^)]*)\)\s+(?:"[^"]*"|NIL)\s+(?P<nome>.+)$', r)
            if not m:
                continue
            nome, att = m["nome"].strip().strip('"'), m["att"].lower()
            basso = nome.lower()
            for tipo, segni, parole in (("sent", "\\sent", ("sent", "inviat")), ("spam", "\\junk", ("spam", "junk")),
                                        ("trash", "\\trash", ("trash", "cestino", "deleted"))):
                if tipo not in trovate and (segni in att or any(p in basso for p in parole)):
                    trovate[tipo] = nome
        self.cartelle = trovate
        return trovate

    def esamina(self, M, tipo):
        """EXAMINE della cartella (sola lettura): (nome IMAP, uidvalidity) o None se la cartella non c'è."""
        nome = self.trova_cartelle(M).get(tipo)
        if not nome:
            return None
        ok, _ = M.select(f'"{nome}"', readonly=True)
        if ok != "OK":
            return None
        uv = (M.response("UIDVALIDITY")[1] or [b"0"])[0]
        return nome, int(uv or 0)

    def elenco(self, tipo):
        """I riassunti della cartella, dal più nuovo (al massimo TIENI). Le intestazioni nuove si leggono una volta."""
        with self.lock:
            try:
                M = self.imap()
                sel = self.esamina(M, tipo)
                if not sel:
                    return []
                _, uv = sel
                _, dati = M.uid("SEARCH", None, "ALL")
                uids = [int(u) for u in (dati[0] or b"").split()][-TIENI:]
                letti = leggi_flag(M, uids)
                nuovi = [u for u in uids if (tipo, uv, u) not in self.riassunti]
                for i in range(0, len(nuovi), 25):
                    self._riassumi(M, tipo, uv, nuovi[i:i + 25])
                self.errore = ""
            except Exception as e:
                self.chiudi()
                self.errore = f"{type(e).__name__}: {str(e)[:160]}"
                raise
        out = []
        for u in reversed(uids):
            r = self.riassunti.get((tipo, uv, u))
            if r:
                r = dict(r, letto=letti.get(u, r.get("letto", True)))
                out.append(r)
        for k in [k for k in self.riassunti if k[0] == tipo and (k[1] != uv or k[2] not in set(uids))]:
            del self.riassunti[k]
        return out

    def _riassumi(self, M, tipo, uv, uids):
        insieme = ",".join(map(str, uids))
        _, dati = M.uid("FETCH", insieme, "(UID FLAGS RFC822.SIZE)")
        dimensioni = {}
        for x in dati or []:
            s = x.decode() if isinstance(x, bytes) else (x[0].decode() if isinstance(x, tuple) else "")
            m = re.search(r"UID (\d+)", s)
            d = re.search(r"RFC822\.SIZE (\d+)", s)
            if m:
                dimensioni[int(m[1])] = int(d[1]) if d else 0
        piccoli = [u for u in uids if dimensioni.get(u, 0) <= GRANDE]
        grandi = [u for u in uids if u not in piccoli]
        for gruppo, parte in ((piccoli, "BODY.PEEK[]"), (grandi, "BODY.PEEK[HEADER]")):
            if not gruppo:
                continue
            _, dati = M.uid("FETCH", ",".join(map(str, gruppo)), f"(UID FLAGS {parte})")
            for x in dati or []:
                if not isinstance(x, tuple):
                    continue
                testa = x[0].decode("utf-8", "replace")
                m = re.search(r"UID (\d+)", testa)
                if not m:
                    continue
                u = int(m[1])
                try:
                    r = riassunto(self.c["id"], tipo, u, email.message_from_bytes(x[1]), dimensioni.get(u, 0),
                                  completo=parte == "BODY.PEEK[]")
                except Exception as e:   # un messaggio storto non ferma l'elenco
                    r = {"casella": self.c["id"], "cartella": tipo, "uid": u, "oggetto": "(non si legge)",
                         "da_nome": "", "da": "", "a": [], "data": "", "ts": 0, "allegati": 0, "dim": dimensioni.get(u, 0),
                         "tipo": "", "anteprima": f"{type(e).__name__}", "mid": ""}
                r["letto"] = "\\Seen" in testa
                self.riassunti[(tipo, uv, u)] = r

    def letto(self, tipo, uid):
        """Se il messaggio è segnato come letto (\\Seen), o None se non c'è."""
        with self.lock:
            M = self.imap()
            if not self.esamina(M, tipo):
                raise KeyError("cartella")
            return leggi_flag(M, [uid]).get(uid)

    def segna(self, tipo, uid, letto):
        """Segna un messaggio come letto o non letto: solo il flag \\Seen, col comando STORE sul suo uid (la cartella
        si apre in scrittura solo per questo e torna subito in sola lettura). Restituisce il segno di adesso."""
        with self.lock:
            M = self.imap()
            nome = self.trova_cartelle(M).get(tipo)
            if not nome or M.select(f'"{nome}"')[0] != "OK":
                raise KeyError("cartella")
            try:
                if uid not in leggi_flag(M, [uid]):
                    raise KeyError("messaggio")
                ok, _ = M.uid("STORE", str(uid), "+FLAGS.SILENT" if letto else "-FLAGS.SILENT", "(\\Seen)")
                if ok != "OK":
                    raise RuntimeError("Aruba non ha accettato il segno")
                adesso = leggi_flag(M, [uid]).get(uid)
            finally:
                try:
                    M.select(f'"{nome}"', readonly=True)
                except Exception:
                    self.chiudi()
            for k, r in self.riassunti.items():
                if k[0] == tipo and k[2] == uid:
                    r["letto"] = adesso
            return adesso

    def messaggio(self, tipo, uid):
        """Il messaggio intero (email.message.Message), dalla cartella in sola lettura."""
        with self.lock:
            M = self.imap()
            if not self.esamina(M, tipo):
                raise KeyError("cartella")
            _, dati = M.uid("FETCH", str(uid), "(BODY.PEEK[])")
        corpo = next((x[1] for x in dati or [] if isinstance(x, tuple)), None)
        if corpo is None:
            raise KeyError("messaggio")
        return email.message_from_bytes(corpo)

    def contatori(self):
        """Per ogni cartella che c'è: (non lette, totali), con STATUS (non apre niente)."""
        out = {}
        with self.lock:
            M = self.imap()
            for tipo, nome in self.trova_cartelle(M).items():
                try:
                    _, d = M.status(f'"{nome}"', "(MESSAGES UNSEEN)")
                    s = d[0].decode() if d and isinstance(d[0], bytes) else ""
                    tot, non = re.search(r"MESSAGES (\d+)", s), re.search(r"UNSEEN (\d+)", s)
                    out[tipo] = {"totale": int(tot[1]) if tot else 0, "non_lette": int(non[1]) if non else 0}
                except Exception:
                    out[tipo] = {"totale": None, "non_lette": None}
        return out


def leggi_flag(M, uids):
    """uid → letto (\\Seen), in una sola richiesta."""
    if not uids:
        return {}
    _, dati = M.uid("FETCH", f"{uids[0]}:{uids[-1]}", "(UID FLAGS)")
    out = {}
    for x in dati or []:
        s = x.decode() if isinstance(x, bytes) else (x[0].decode() if isinstance(x, tuple) else "")
        m = re.search(r"UID (\d+)", s)
        if m:
            out[int(m[1])] = "\\Seen" in s
    return out


# ---------------------------------------------------------------- dal messaggio a quello che si mostra

def tipo_e_vero(m):
    """(il messaggio da mostrare, il tipo): una PEC si mostra tolta dalla busta del gestore (fonti_casa.busta_pec)."""
    vero, tipo = F.busta_pec(m)
    return vero, tipo


def mittente(m):
    nome, ind = eu.parseaddr(dec(m.get("From")))
    if not ind and nome:
        ind = nome
    return nome, ind


def destinatari(m):
    return [(dec(n), a) for n, a in eu.getaddresses([dec(m.get(h)) for h in ("To", "Cc") if m.get(h)])][:30]


def quando(m):
    try:
        d = eu.parsedate_to_datetime(m.get("Date"))
        if d.tzinfo is None:
            d = d.replace(tzinfo=dt.timezone.utc)
        return d.astimezone(F.fuso())
    except (TypeError, ValueError):
        return None


def foglie(m):
    """Le parti «foglia» del messaggio, in ordine: [(n, parte)]. Le stesse n per elenco allegati e download."""
    return [(i, p) for i, p in enumerate(x for x in m.walk() if not x.is_multipart())]


def e_allegato(p):
    disp = (p.get("Content-Disposition") or "").lower()
    tipo = p.get_content_type()
    if F.nome_allegato(p):
        return True
    if disp.startswith("attachment"):
        return True
    return tipo not in ("text/plain", "text/html") and not tipo.startswith("multipart/")


def corpo_testo(m):
    """(testo semplice, html) del messaggio: la prima parte di ciascun tipo che non è un allegato."""
    testo = html_ = ""
    for _, p in foglie(m):
        if e_allegato(p):
            continue
        t = p.get_content_type()
        try:
            s = (p.get_payload(decode=True) or b"").decode(p.get_content_charset() or "utf-8", "replace")
        except LookupError:
            s = (p.get_payload(decode=True) or b"").decode("latin-1", "replace")
        if t == "text/plain" and not testo:
            testo = s
        elif t == "text/html" and not html_:
            html_ = s
    return testo, html_


def anteprima_da(testo, html_):
    t = testo or F.testo(html_ or "", massimo=None) if (testo or html_) else ""
    t = re.sub(r"(?m)^>.*$", " ", t)
    return re.sub(r"\s+", " ", t).strip()[:ANTEPRIMA]


def allegati_di(m):
    out = []
    for n, p in foglie(m):
        if not e_allegato(p) or p.get_content_type() in FIRME:
            continue
        nome = F.nome_allegato(p) or f"allegato-{n + 1}"
        dati = p.get_payload(decode=True) or b""
        out.append({"n": n, "nome": nome, "tipo": p.get_content_type(), "dim": len(dati),
                    "cid": (p.get("Content-ID") or "").strip("<> "),
                    "vedi": vedibile(nome, p.get_content_type()), "testo": nome.lower().endswith(F.DOCUMENTI_SCRITTI)})
    return out


def vedibile(nome, tipo):
    """Come lo apre la pagina: «immagine», «pdf», «p7m» (il documento firmato dentro) o "" (si scarica)."""
    basso = nome.lower()
    if basso.endswith(".p7m"):
        return "p7m"
    if tipo == "application/pdf" or basso.endswith(".pdf"):
        return "pdf"
    if tipo in IMMAGINI_VEDIBILI or basso.endswith((".jpg", ".jpeg", ".png", ".gif", ".webp")):
        return "immagine"
    return ""


def tipo_mail(vero, tipo_busta, cartella):
    """L'etichetta del messaggio: ricevuta PEC, PEC certificata, non certificata, mail non consegnata (rimbalzo),
    avviso del gestore della casella o risposta automatica ("" per una mail normale)."""
    if tipo_busta in ("ricevuta", "pec", "anomalia"):
        return tipo_busta
    if cartella == "inbox":
        nome, ind = mittente(vero)
        dominio = ind.rsplit("@", 1)[-1].lower()
        motivo = F.non_comunicato(dec(vero.get("Subject")), f"{nome} {ind}", dominio, vero)
        if not motivo or "nostra mail" in motivo:
            return ""
        if F.NON_COMUNICATO_DA.search(f"{nome} {ind}") or motivo == "rimbalzo":
            return "rimbalzo"
        if dominio.endswith(F.NON_COMUNICATO_DOMINI):
            return "avviso"
        return "automatica"
    return ""


def riassunto(casella, cartella, uid, m, dim, completo=True):
    vero, tb = tipo_e_vero(m)
    if not completo and tb == "" and m.get("X-Trasporto"):   # busta PEC grande: chi la manda è nell'intestazione
        tb = "pec" if (m.get("X-Trasporto") or "").strip().lower() == "posta-certificata" else "anomalia"
    nome, ind = mittente(vero)
    oggetto = dec(vero.get("Subject"))
    if not completo and tb in ("pec", "anomalia"):
        oggetto = re.sub(r"^(POSTA CERTIFICATA|ANOMALIA MESSAGGIO):\s*", "", oggetto)
        pc = re.match(r"Per conto di:\s*(\S+)", dec(m.get("From")))
        if pc:
            nome, ind = "", pc[1]
    d = quando(vero) or quando(m)
    if completo:
        testo, html_ = corpo_testo(vero)
        anteprima, allegati = anteprima_da(testo, html_), len(allegati_di(vero))
    else:
        anteprima = "(messaggio grande: si legge aprendolo)"
        allegati = 1 if m.get_content_type().startswith("multipart/") else 0
    mid = (vero.get("Message-ID") or f"{vero.get('Date')}-{vero.get('Subject')}").strip()
    return {"casella": casella, "cartella": cartella, "uid": uid, "da_nome": nome, "da": ind,
            "a": [a for _, a in destinatari(vero)][:5], "oggetto": oggetto or "(senza oggetto)",
            "data": d.isoformat(timespec="minutes") if d else "", "ts": d.timestamp() if d else 0,
            "allegati": allegati, "dim": dim, "tipo": tipo_mail(vero, tb, cartella) if completo else tb,
            "anteprima": anteprima, "mid": "posta:" + re.sub(r"[<>\s]", "", mid)}


# ---------------------------------------------------------------- i comunicati: cosa ne ha fatto il sito

_visti = {"quando": 0, "dati": {}}
_archivio = {"quando": 0, "voci": set(), "scartate": set()}


def visti():
    """comunicati_visti.json del sito (pubblico), ogni 2 minuti al massimo."""
    if time.time() - _visti["quando"] > 120:
        try:
            with urllib.request.urlopen(urllib.request.Request(VISTI + f"?t={int(time.time())}",
                                                               headers={"User-Agent": "nb-posta"}), timeout=15) as r:
                _visti["dati"] = json.load(r).get("visti") or {}
        except Exception:
            pass
        _visti["quando"] = time.time()
    return _visti["dati"]


def archivio():
    """I comunicati che il Pi ha passato al giro lampo e quelli scartati (comunicati.json dell'archivio di casa)."""
    if time.time() - _archivio["quando"] > 60:
        try:
            with open(os.path.join(F.ARCHIVIO, "comunicati.json"), encoding="utf-8") as f:
                d = json.load(f)
            _archivio["voci"] = {v.get("id"): {k: v.get(k) for k in ("fonte", "fonte_perche", "valutato")}
                                 for v in d.get("voci") or []}
            _archivio["scartate"] = set(d.get("scartate") or [])
        except (OSError, ValueError):
            pass
        _archivio["quando"] = time.time()
    return _archivio


def comunicato(r):
    """Per le mail arrivate a comunicati@ e alla PEC: cosa ne ha fatto il giro lampo (pubblicato, già sul sito,
    scartato, in sospeso, in lavorazione) con l'indirizzo della notizia. None se non è un comunicato."""
    if r["casella"] not in ("comunicati", "pec") or r["cartella"] != "inbox" or \
            r.get("tipo") in ("ricevuta", "rimbalzo", "automatica", "avviso"):
        return None
    ident = F.id_posta(r["mid"])
    v = visti().get(ident)
    if v:
        x = {"esito": v.get("esito"), "quando": v.get("quando")}
        if v.get("notizia"):
            x["url"] = f"{SITO}/notizia/{v['notizia']}/"
        return x
    a = archivio()
    if ident in a["voci"]:
        voce = a["voci"][ident] or {}
        decisa = (F.leggi_json(F.VALUTATI, {}).get(ident) or {}).get("decisione") or voce.get("valutato")
        if voce.get("fonte") == "da_valutare" and not decisa:
            return {"esito": "da_valutare", "id": ident, "perche": voce.get("fonte_perche") or ""}
        if voce.get("fonte") == "da_valutare" and decisa == "scarta":
            return {"esito": "scartato_da_te", "id": ident}
        return {"esito": "in_lavorazione"}
    return None


def valuta(corpo):
    """La decisione del proprietario su un comunicato da valutare: in valutati.json (e il mittente tra i fidati se lo
    chiede), poi la lettura della posta e il giro lampo partono subito. Restituisce la risposta per la pagina."""
    cid, cartella, uid, decisione = corpo.get("casella"), corpo.get("cartella"), corpo.get("uid"), corpo.get("decisione")
    if cid not in ("comunicati", "pec") or cartella != "inbox" or not isinstance(uid, int) or uid <= 0 \
            or decisione not in ("pubblica", "scarta") or not isinstance(corpo.get("fidati", False), bool):
        raise ValueError("richiesta storta")
    vero, _ = tipo_e_vero(CASE[cid].messaggio(cartella, uid))
    ident = F.id_posta(F.link_posta(vero))
    if (archivio()["voci"].get(ident) or {}).get("fonte") != "da_valutare":
        _archivio["quando"] = 0   # forse il Pi l'ha appena letta: si riguarda
        if (archivio()["voci"].get(ident) or {}).get("fonte") != "da_valutare":
            raise KeyError("non è un comunicato da valutare")
    fidato = None
    if decisione == "pubblica" and corpo.get("fidati"):
        indirizzo = eu.parseaddr(str(vero.get("From") or ""))[1]
        fidato = F.fidati_aggiungi(indirizzo)
    valutati = F.leggi_json(F.VALUTATI, {})
    valutati[ident] = {"decisione": decisione, "quando": dt.datetime.now(F.fuso()).isoformat(timespec="minutes")}
    tmp = F.VALUTATI + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(valutati, f, ensure_ascii=False, indent=1)
    os.replace(tmp, F.VALUTATI)
    subprocess.Popen(LETTURA, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
    return {"esito": "scartato_da_te" if decisione == "scarta" else "in_lavorazione", "id": ident,
            "fidato": f"{'indirizzo' if fidato and fidato[0] == 'indirizzi' else 'dominio'} {fidato[1]}" if fidato else ""}


# ---------------------------------------------------------------- gli allegati

def contenuto_p7m(dati):
    """Il documento dentro un .p7m firmato (CAdES), con openssl; None se non si apre. La firma non si verifica: si
    legge solo il contenuto."""
    with tempfile.TemporaryDirectory() as td:
        ingresso, uscita = os.path.join(td, "a.p7m"), os.path.join(td, "a.out")
        with open(ingresso, "wb") as f:
            f.write(dati)
        for forma in ("DER", "PEM"):
            r = subprocess.run(["openssl", "cms", "-verify", "-noverify", "-binary", "-inform", forma,
                                "-in", ingresso, "-out", uscita], capture_output=True, timeout=60)
            if r.returncode == 0 and os.path.getsize(uscita):
                with open(uscita, "rb") as f:
                    return f.read()
        if re.match(rb"^[A-Za-z0-9+/=\r\n]+$", dati[:200]):   # a volte il .p7m è in base64 senza intestazioni
            try:
                return contenuto_p7m(base64.b64decode(dati))
            except ValueError:
                pass
    return None


TIPI = {".pdf": "application/pdf", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png",
        ".gif": "image/gif", ".webp": "image/webp", ".docx": "application/octet-stream", ".odt": "application/octet-stream"}


# ---------------------------------------------------------------- la chiave delle statistiche e i gettoni

_statistiche = {"quando": 0, "busta": None}
_buone = set()        # sha256 delle chiavi già provate e giuste (finché dati.json non cambia sale)
_gettoni = {}         # gettone → scadenza (epoch)
_tentativi = []       # (epoch, indirizzo, riuscito)
_blocco = threading.Lock()


def busta_statistiche(forza=False):
    if forza or not _statistiche["busta"] or time.time() - _statistiche["quando"] > 600:
        try:
            url = STATISTICHE + (f"?t={int(time.time())}" if STATISTICHE.startswith("http") else "")
            with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "nb-posta"}), timeout=20) as r:
                b = json.load(r)
            if _statistiche["busta"] and b.get("sale") != _statistiche["busta"].get("sale"):
                _buone.clear()
            _statistiche["busta"] = b
        except Exception:
            if not _statistiche["busta"]:
                raise
        _statistiche["quando"] = time.time()
    return _statistiche["busta"]


def chiave_giusta(chiave_b64):
    from cryptography.exceptions import InvalidTag
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    try:
        k = base64.b64decode(chiave_b64, validate=True)
    except (ValueError, TypeError):
        return False
    if len(k) != 32:
        return False
    impronta = hashlib.sha256(k).hexdigest()
    if impronta in _buone:
        return True
    for forza in (False, True):   # se non si apre, si riprova con dati.json appena scaricato
        b = busta_statistiche(forza)
        try:
            AESGCM(k).decrypt(base64.b64decode(b["iv"]), base64.b64decode(b["dati"]), None)
            _buone.add(impronta)
            return True
        except InvalidTag:
            continue
    return False


def entra(indirizzo, chiave_b64):
    ora = time.time()
    with _blocco:
        _tentativi[:] = [t for t in _tentativi if ora - t[0] < 3600]
        falliti_qui = sum(1 for t in _tentativi if t[1] == indirizzo and not t[2])
        falliti = sum(1 for t in _tentativi if not t[2])
        if falliti_qui >= FALLITI_MAX or falliti >= TENTATIVI_MAX:
            return None, "troppi tentativi sbagliati: riprova fra un'ora"
    ok = chiave_giusta(chiave_b64)
    with _blocco:
        _tentativi.append((ora, indirizzo, ok))
        if not ok:
            return None, "chiave sbagliata"
        for g in [g for g, s in _gettoni.items() if s < ora]:
            del _gettoni[g]
        g = secrets.token_urlsafe(32)
        _gettoni[g] = ora + GETTONE_ORE * 3600
        return g, ""


def gettone_valido(g):
    with _blocco:
        s = _gettoni.get(g or "")
        return bool(s and s > time.time())


# ---------------------------------------------------------------- il servizio

CASE = {c["id"]: Casella(c) for c in CASELLE}


def caselle_json():
    out = []
    for c in CASELLE:
        k = CASE[c["id"]]
        x = {"id": c["id"], "nome": c["nome"], "indirizzo": c["indirizzo"], "webmail": c["webmail"],
             "collegata": k.collegata(), "cartelle": []}
        if x["collegata"]:
            try:
                cont = k.contatori()
                x["cartelle"] = [{"id": t, "nome": n, **cont[t]} for t, n in CARTELLE if t in cont]
            except Exception as e:
                k.chiudi()
                x["errore"] = f"non si apre ({type(e).__name__}: {str(e)[:120]})"
        out.append(x)
    return out


def messaggi_json(q):
    caselle = [q.get("casella")] if q.get("casella") in PER_ID else [c["id"] for c in CASELLE]
    cartella = q.get("cartella") if q.get("cartella") in dict(CARTELLE) else "inbox"
    cerca = (q.get("cerca") or "").strip().lower()[:100]
    ricevute = q.get("ricevute") == "1"
    solo_non_lette = q.get("non_lette") == "1"
    da = max(0, int(q.get("da") or 0)) if str(q.get("da") or "0").isdigit() else 0
    tutti, errori = [], {}
    for cid in caselle:
        k = CASE[cid]
        if not k.collegata():
            continue
        try:
            tutti += k.elenco(cartella)
        except Exception as e:
            errori[cid] = f"{type(e).__name__}: {str(e)[:120]}"
    nascoste = 0
    if not ricevute:
        nascoste = sum(1 for r in tutti if r.get("tipo") == "ricevuta")
        tutti = [r for r in tutti if r.get("tipo") != "ricevuta"]
    if solo_non_lette:
        tutti = [r for r in tutti if not r.get("letto")]
    if cerca:
        parole = cerca.split()
        tutti = [r for r in tutti if all(p in " ".join((r["oggetto"], r["da_nome"], r["da"], " ".join(r["a"]),
                                                         r["anteprima"])).lower() for p in parole)]
    tutti.sort(key=lambda r: r.get("ts") or 0, reverse=True)
    pagina = [dict(r, comunicato=comunicato(r)) for r in tutti[da:da + PER_PAGINA]]
    return {"messaggi": pagina, "totale": len(tutti), "altri": len(tutti) > da + PER_PAGINA, "errori": errori,
            "ricevute_nascoste": nascoste}


def ripulisci_html(h, allegati, parti):
    """L'HTML della mail per il riquadro chiuso della pagina: via script, cornici, oggetti, refresh e attributi on…;
    le immagini «cid:» del messaggio diventano data: (fino a CID_MAX byte)."""
    h = re.sub(r"(?is)<(script|iframe|object|embed|frameset|applet)\b.*?(</\1\s*>|$)", "", h)
    h = re.sub(r"(?is)</?(script|iframe|object|embed|frame|frameset|applet|base|link|meta|form)\b[^>]*>", "", h)

    def tag(mm):   # dentro i tag: via gli attributi on… e i link javascript:
        t = re.sub(r"(?i)\son\w+\s*=\s*(\"[^\"]*\"|'[^']*'|[^\s>]+)", "", mm[0])
        return re.sub(r"(?i)(href|src)\s*=\s*([\"']?)\s*javascript:[^\"'>\s]*\2", r'\1="#"', t)
    h = re.sub(r"<[a-zA-Z][^>]*>", tag, h)
    totale = 0
    per_cid = {a["cid"]: a for a in allegati if a.get("cid")}

    def sostituisci(mm):
        nonlocal totale
        a = per_cid.get(urllib.parse.unquote(mm[1]))
        if not a or a["tipo"] not in IMMAGINI_VEDIBILI:
            return mm[0]
        dati = parti[a["n"]].get_payload(decode=True) or b""
        if totale + len(dati) > CID_MAX:
            return mm[0]
        totale += len(dati)
        a["nel_testo"] = True
        return f"data:{a['tipo']};base64,{base64.b64encode(dati).decode()}"
    return re.sub(r"(?i)cid:([^\"'\s>)]+)", sostituisci, h)


def messaggio_json(q):
    cid, cartella = q.get("casella"), q.get("cartella")
    if cid not in PER_ID or cartella not in dict(CARTELLE) or not str(q.get("uid") or "").isdigit():
        raise KeyError("richiesta")
    m = CASE[cid].messaggio(cartella, int(q["uid"]))
    vero, tb = tipo_e_vero(m)
    parti = dict(foglie(vero))
    allegati = allegati_di(vero)
    testo, html_ = corpo_testo(vero)
    nome, ind = mittente(vero)
    d = quando(vero) or quando(m)
    out = {"casella": cid, "cartella": cartella, "uid": int(q["uid"]), "oggetto": dec(vero.get("Subject")) or "(senza oggetto)",
           "da_nome": nome, "da": ind, "a": destinatari(vero), "data": d.isoformat(timespec="minutes") if d else "",
           "testo": testo[:400_000], "html": ripulisci_html(html_, allegati, parti)[:1_500_000] if html_ else "",
           "allegati": allegati, "tipo": tipo_mail(vero, tb, cartella)}
    try:   # per il pulsante «Segna come letta / non letta»
        out["letto"] = CASE[cid].letto(cartella, int(q["uid"]))
    except Exception:
        out["letto"] = None
    if tb in ("pec", "anomalia", "ricevuta"):   # la busta del gestore: chi l'ha certificata e quando
        out["busta"] = {"oggetto": dec(m.get("Subject")), "da": dec(m.get("From")), "data": (quando(m) or d).isoformat(timespec="minutes") if (quando(m) or d) else "",
                        "ricevuta": m.get("X-Ricevuta") or ""}
    mid = (vero.get("Message-ID") or f"{vero.get('Date')}-{vero.get('Subject')}").strip()
    out["comunicato"] = comunicato({"casella": cid, "cartella": cartella, "tipo": out["tipo"],
                                    "mid": "posta:" + re.sub(r"[<>\s]", "", mid)})
    for a in out["allegati"]:
        a.pop("cid", None)
    return out


def allegato(q):
    """(byte, tipo, nome, in linea) di un allegato; dei .p7m il documento dentro; dei .docx/.doc/.odt/.rtf, con testo=1, il
    testo."""
    cid, cartella = q.get("casella"), q.get("cartella")
    if cid not in PER_ID or cartella not in dict(CARTELLE) or not str(q.get("uid") or "").isdigit() \
            or not str(q.get("n") or "").isdigit():
        raise KeyError("richiesta")
    vero, _ = tipo_e_vero(CASE[cid].messaggio(cartella, int(q["uid"])))
    parti = dict(foglie(vero))
    p = parti.get(int(q["n"]))
    if p is None:
        raise KeyError("allegato")
    nome = F.nome_allegato(p) or f"allegato-{int(q['n']) + 1}"
    dati = p.get_payload(decode=True) or b""
    if q.get("testo") == "1" and nome.lower().endswith(F.DOCUMENTI_SCRITTI):
        t = F.testo_documento(dati, nome) or "(nel documento non c'è testo da leggere)"
        return t.encode("utf-8"), "text/plain; charset=utf-8", nome + ".txt", True
    if q.get("dentro") == "1" and nome.lower().endswith(".p7m"):
        interno = contenuto_p7m(dati)
        if interno is None:
            raise KeyError("p7m")
        nome = nome[:-4]
        ext = os.path.splitext(nome.lower())[1]
        tipo = TIPI.get(ext, "application/octet-stream")
        if ext in F.DOCUMENTI_SCRITTI and q.get("testo") == "1":
            return (F.testo_documento(interno, nome) or "").encode("utf-8"), "text/plain; charset=utf-8", nome + ".txt", True
        return interno, tipo, nome, tipo in IMMAGINI_VEDIBILI or tipo == "application/pdf"
    tipo = p.get_content_type()
    if vedibile(nome, tipo) == "pdf":
        return dati, "application/pdf", nome, True
    if vedibile(nome, tipo) == "immagine":
        t = tipo if tipo in IMMAGINI_VEDIBILI else TIPI.get(os.path.splitext(nome.lower())[1], "application/octet-stream")
        return dati, t, nome, t in IMMAGINI_VEDIBILI
    return dati, "application/octet-stream", nome, False   # tutto il resto si scarica e basta (mai HTML nella pagina)


class Servizio(BaseHTTPRequestHandler):
    server_version = "nb-posta"
    sys_version = ""

    def log_message(self, fmt, *a):   # niente indirizzi né oggetti nel registro
        pass

    def origine(self):
        o = self.headers.get("Origin") or ""
        return o if o in ORIGINI else ""

    def intestazioni(self, codice, tipo, lunghezza, extra=None):
        self.send_response(codice)
        self.send_header("Content-Type", tipo)
        self.send_header("Content-Length", str(lunghezza))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        o = self.origine()
        if o:
            self.send_header("Access-Control-Allow-Origin", o)
            self.send_header("Vary", "Origin")
            self.send_header("Access-Control-Expose-Headers", "Content-Disposition, X-Nome")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()

    def rispondi(self, codice, dati):
        b = json.dumps(dati, ensure_ascii=False).encode("utf-8")
        self.intestazioni(codice, "application/json; charset=utf-8", len(b))
        self.wfile.write(b)

    def do_OPTIONS(self):
        self.send_response(204)
        o = self.origine()
        if o:
            self.send_header("Access-Control-Allow-Origin", o)
            self.send_header("Vary", "Origin")
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Authorization, Content-Type")
            self.send_header("Access-Control-Max-Age", "600")
        self.send_header("Content-Length", "0")
        self.end_headers()

    def percorso(self):
        u = urllib.parse.urlsplit(self.path)
        p = u.path[len("/posta"):] if u.path.startswith("/posta/") else u.path
        return p, {k: v[0] for k, v in urllib.parse.parse_qs(u.query).items()}

    def autorizzato(self):
        a = self.headers.get("Authorization") or ""
        return a.startswith("Bearer ") and gettone_valido(a[7:].strip())

    def do_POST(self):
        p, _ = self.percorso()
        if p not in ("/api/entra", "/api/segna", "/api/valuta"):
            return self.rispondi(404, {"errore": "non c'è"})
        try:
            n = min(int(self.headers.get("Content-Length") or 0), 4096)
            corpo = json.loads(self.rfile.read(n) or b"{}")
        except (ValueError, TypeError):
            return self.rispondi(400, {"errore": "richiesta storta"})
        if p == "/api/valuta":   # «Pubblica» / «Pubblica e fidati del mittente» / «Non pubblicare» (comunicati da valutare)
            if not self.autorizzato():
                return self.rispondi(401, {"errore": "serve entrare"})
            try:
                return self.rispondi(200, valuta(corpo))
            except ValueError as e:
                return self.rispondi(400, {"errore": str(e)})
            except KeyError as e:
                return self.rispondi(404, {"errore": f"non trovato ({e})"})
            except Exception as e:
                return self.rispondi(502, {"errore": f"non riesco ({type(e).__name__}: {str(e)[:120]})"})
        if p == "/api/segna":   # «Segna come letta / non letta»: l'unica cosa che la pagina cambia nelle caselle
            if not self.autorizzato():
                return self.rispondi(401, {"errore": "serve entrare"})
            cid, cartella, uid = corpo.get("casella"), corpo.get("cartella"), corpo.get("uid")
            if cid not in PER_ID or cartella not in dict(CARTELLE) or not isinstance(uid, int) or uid <= 0 \
                    or not isinstance(corpo.get("letto"), bool):
                return self.rispondi(400, {"errore": "richiesta storta"})
            try:
                return self.rispondi(200, {"letto": CASE[cid].segna(cartella, uid, corpo["letto"])})
            except KeyError as e:
                return self.rispondi(404, {"errore": f"non trovato ({e})"})
            except Exception as e:
                CASE[cid].chiudi()
                return self.rispondi(502, {"errore": f"la casella non risponde ({type(e).__name__})"})
        chi = (self.headers.get("X-Forwarded-For") or self.client_address[0]).split(",")[0].strip()
        try:
            g, perche = entra(chi, str(corpo.get("chiave") or ""))
        except Exception as e:
            return self.rispondi(503, {"errore": f"non riesco a leggere le statistiche del sito ({type(e).__name__})"})
        if not g:
            return self.rispondi(429 if "troppi" in perche else 403, {"errore": perche})
        self.rispondi(200, {"gettone": g, "ore": GETTONE_ORE})

    def do_GET(self):
        p, q = self.percorso()
        if p == "/api/stato":
            return self.rispondi(200, {"ok": True})
        if not p.startswith("/api/"):
            return self.rispondi(404, {"errore": "non c'è"})
        if not self.autorizzato():
            return self.rispondi(401, {"errore": "serve entrare"})
        try:
            if p == "/api/caselle":
                return self.rispondi(200, {"caselle": caselle_json(), "cartelle": CARTELLE})
            if p == "/api/messaggi":
                return self.rispondi(200, messaggi_json(q))
            if p == "/api/messaggio":
                return self.rispondi(200, messaggio_json(q))
            if p == "/api/allegato":
                dati, tipo, nome, in_linea = allegato(q)
                disp = ("inline" if in_linea else "attachment") + "; filename*=UTF-8''" + urllib.parse.quote(nome)
                self.intestazioni(200, tipo, len(dati), {"Content-Disposition": disp, "X-Nome": urllib.parse.quote(nome),
                                                         "Content-Security-Policy": "sandbox"})
                return self.wfile.write(dati)
        except KeyError as e:
            return self.rispondi(404, {"errore": f"non trovato ({e})"})
        except Exception as e:
            return self.rispondi(502, {"errore": f"la casella non risponde ({type(e).__name__}: {str(e)[:140]})"})
        self.rispondi(404, {"errore": "non c'è"})


def imposta(cid):
    """Chiede la password di una casella (non si vede), prova ad entrare in sola lettura e la salva sul Pi (600)."""
    import getpass
    c = PER_ID[cid]
    utente = input(f"Indirizzo della casella [{c['indirizzo']}]: ").strip() or c["indirizzo"]
    password = getpass.getpass("Password della casella (non si vede mentre la scrivi): ")
    try:
        with imaplib.IMAP4_SSL(c["server"], 993, timeout=60) as M:
            M.login(utente, password)
            M.select("INBOX", readonly=True)
    except Exception as e:
        sys.exit(f"Non riesco a entrare nella casella ({type(e).__name__}): controlla indirizzo e password. Niente salvato.")
    file = os.path.join(CARTELLA, c["conf"])
    vecchio = os.umask(0o077)
    try:
        with open(file, "w", encoding="utf-8") as f:
            json.dump({"utente": utente, "password": password, "server": c["server"]}, f)
    finally:
        os.umask(vecchio)
    os.chmod(file, 0o600)
    print(f"✓ casella {utente} collegata: si legge nella scheda «Posta» delle statistiche")


def prova():
    for c in CASELLE:
        k = CASE[c["id"]]
        if not k.collegata():
            print(f"{c['nome']}: non collegata ({c['conf']} manca)")
            continue
        try:
            cont = k.contatori()
            el = k.elenco("inbox")
            print(f"{c['nome']}: {cont} · in arrivo {len(el)}")
            for r in el[:4]:
                print(f"   {r['data'][:16]} · {r['tipo'] or '-':9} · {r['da'][:30]:30} · {r['oggetto'][:50]}")
        except Exception as e:
            print(f"{c['nome']}: ERRORE {type(e).__name__}: {e}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--imposta", choices=[c["id"] for c in CASELLE if c["id"] != "comunicati" and c["id"] != "pec"])
    ap.add_argument("--prova", action="store_true")
    a = ap.parse_args()
    if a.imposta:
        return imposta(a.imposta)
    if a.prova:
        return prova()
    s = ThreadingHTTPServer((INDIRIZZO, PORTA), Servizio)
    s.daemon_threads = True
    print(f"{adesso():%d/%m %H:%M} posta: in ascolto su {INDIRIZZO}:{PORTA}", flush=True)
    s.serve_forever()


if __name__ == "__main__":
    main()
