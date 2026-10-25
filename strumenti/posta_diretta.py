#!/usr/bin/env python3
"""La posta in diretta: sul Pi di casa resta collegato alle caselle comunicati@notiziebenevento.it e PEC (IMAP IDLE) e,
appena arriva una mail, fa leggere la casella e partire il giro lampo, senza aspettare il controllo dei 5 minuti.

Voluto dal proprietario il 25 ott 2026 («dobbiamo recuperare qualche minuto, dobbiamo arrivare prima»): il comunicato
della Miwa Basket mandato alle 21:06 il Pi l'aveva visto alle 21:10, al controllo dei 5 minuti. Il controllo dei 5
minuti resta (cron di fonti_casa.py --solo comunicati): se questo programma si ferma, la posta si legge lo stesso.

Il cron lo lancia ogni minuto con flock -n: se gira già non succede niente, se si è fermato riparte da solo. Per ogni
casella un filo: entra in sola lettura (EXAMINE: non segna niente come letto) e aspetta in IDLE. Quando il server dice
che ci sono più mail di prima («* N EXISTS»), dopo ASPETTA secondi (una PEC arriva insieme alle sue ricevute) fa girare
fonti_casa.py --solo comunicati e comunicati_lampo.py, gli stessi del cron e con gli stessi lucchetti. Ogni RINNOVA
minuti chiude e riapre l'IDLE (i server lo chiudono dopo 30); se la connessione cade riprova dopo 30 s, 1, 2, 5
minuti (nel registro, posta_diretta.log, i primi 5 errori di fila e poi uno ogni ora). Le password restano in
posta.conf e pec.conf (600), lette da qui e mai stampate.

Uso sul Pi:  python3 ~/nb-fonti/sentinella/posta_diretta.py              (dal cron, ogni minuto, con flock -n)
             python3 ~/nb-fonti/sentinella/posta_diretta.py --prova 120  (si collega e dice cosa sente per 120 s,
                                                                          senza far partire niente)
"""
import argparse
import base64
import datetime as dt
import json
import os
import re
import select
import socket
import ssl
import subprocess
import sys
import threading
import time

QUI = os.path.dirname(os.path.abspath(__file__))
CARTELLA = os.environ.get("NB_FONTI_CARTELLA") or os.path.expanduser("~/nb-fonti")
CASELLE = [("comunicati@", os.path.join(CARTELLA, "posta.conf"), "imaps.aruba.it"),
           ("PEC", os.path.join(CARTELLA, "pec.conf"), "imaps.pec.aruba.it")]
ASPETTA = 15        # secondi dopo l'ultima mail nuova prima di leggere la casella
RINNOVA = 10 * 60   # secondi di IDLE prima di rinnovarlo (così una connessione morta in silenzio si scopre presto)
ATTESE = (30, 60, 120, 300)   # secondi prima di ricollegarsi dopo un errore (poi sempre l'ultimo)
LETTURA = ["/usr/bin/flock", "-w", "240", "/tmp/nb_comunicati.lock", "/bin/sh", "-c",
           f"/usr/bin/flock -w 240 /tmp/nb_fonti.lock /usr/bin/timeout 120 /usr/bin/python3 {CARTELLA}/fonti_casa.py "
           f"--solo comunicati >> {CARTELLA}/fonti.log 2>&1; /usr/bin/timeout 90 /usr/bin/python3 "
           f"{QUI}/comunicati_lampo.py >> {CARTELLA}/comunicati.log 2>&1"]


def scrivi(testo):
    print(f"{dt.datetime.now():%d/%m %H:%M:%S} {testo}", flush=True)


class Imap:
    """Il minimo di IMAP che serve: entrare, EXAMINE, IDLE. Una riga alla volta, con un tempo massimo di attesa."""

    def __init__(self, server, porta=993, contesto=None, collega=None):
        self.server, self.buf, self.n = server, b"", 0
        if collega:   # nelle prove: un socket già aperto
            self.s = collega
        else:
            ctx = contesto or ssl.create_default_context()
            self.s = ctx.wrap_socket(socket.create_connection((server, porta), timeout=60), server_hostname=server)
        self.s.settimeout(60)

    def riga(self, attesa):
        """La prossima riga del server, o None se in `attesa` secondi non arriva niente."""
        fine = time.monotonic() + attesa
        while b"\r\n" not in self.buf:
            pronto = getattr(self.s, "pending", lambda: 0)() or select.select([self.s], [], [], max(0, fine - time.monotonic()))[0]
            if not pronto:
                return None
            try:
                dati = self.s.recv(65536)
            except ssl.SSLWantReadError:
                continue
            if not dati:
                raise ConnectionError("il server ha chiuso la connessione")
            self.buf += dati
        riga, self.buf = self.buf.split(b"\r\n", 1)
        return riga.decode("utf-8", "replace")

    def manda(self, testo):
        self.s.sendall(testo.encode("utf-8") + b"\r\n")

    def comando(self, testo, attesa=60):
        """Manda un comando e legge fino alla sua risposta: le righe «*» che ha ricevuto."""
        self.n += 1
        tag = f"N{self.n}"
        self.manda(f"{tag} {testo}")
        righe = []
        while True:
            r = self.riga(attesa)
            if r is None:
                raise TimeoutError(f"nessuna risposta a {testo.split()[0]}")
            if r.startswith(tag + " "):
                if not r[len(tag) + 1:].upper().startswith("OK"):
                    raise RuntimeError(f"{testo.split()[0]} rifiutato: {r[len(tag) + 1:][:120]}")
                return righe
            righe.append(r)

    def entra(self, utente, password):
        saluto = self.riga(60)
        if not saluto or not saluto.startswith("* OK"):
            raise RuntimeError(f"saluto del server inatteso: {str(saluto)[:80]}")
        segreto = base64.b64encode(f"\0{utente}\0{password}".encode("utf-8")).decode()
        self.n += 1
        tag = f"N{self.n}"
        self.manda(f"{tag} AUTHENTICATE PLAIN {segreto}")   # SASL-IR: Aruba lo accetta su una riga
        while True:
            r = self.riga(60)
            if r is None:
                raise TimeoutError("nessuna risposta all'accesso")
            if r.startswith("+"):   # il server vuole il segreto a parte (senza SASL-IR)
                self.manda(segreto)
                continue
            if r.startswith(tag + " "):
                if not r[len(tag) + 1:].upper().startswith("OK"):
                    raise RuntimeError("accesso rifiutato (password cambiata? fonti_casa.py --imposta-posta/--imposta-pec)")
                return

    def esamina(self):
        """EXAMINE INBOX (sola lettura): quante mail ci sono."""
        for r in self.comando("EXAMINE INBOX"):
            m = re.match(r"\* (\d+) EXISTS", r, re.I)
            if m:
                return int(m[1])
        return 0

    def aspetta(self, quante, durata, quando_cambia):
        """IDLE per `durata` secondi: quando le mail diventano più di `quante` chiama quando_cambia() e chiude l'IDLE.
        Restituisce quante mail ci sono adesso."""
        self.n += 1
        tag = f"N{self.n}"
        self.manda(f"{tag} IDLE")
        r = self.riga(60)
        if not r or not r.startswith("+"):
            raise RuntimeError(f"IDLE rifiutato: {str(r)[:80]}")
        fine, nuova = time.monotonic() + durata, False
        while not nuova and time.monotonic() < fine:
            r = self.riga(min(60, max(1, fine - time.monotonic())))
            if r is None:
                continue
            if r.upper().startswith("* BYE"):
                raise ConnectionError(f"il server chiude: {r[:80]}")
            m = re.match(r"\* (\d+) (EXISTS|EXPUNGE)", r, re.I)
            if m and m[2].upper() == "EXISTS":
                nuova = int(m[1]) > quante
                quante = int(m[1])
            elif m:
                quante = max(0, quante - 1)
        self.manda("DONE")
        while True:
            r = self.riga(60)
            if r is None:
                raise TimeoutError("nessuna risposta a DONE")
            m = re.match(r"\* (\d+) EXISTS", r, re.I)
            if m:
                nuova = nuova or int(m[1]) > quante
                quante = int(m[1])
            if r.startswith(tag + " "):
                break
        if nuova:
            quando_cambia()
        return quante

    def chiudi(self):
        try:
            self.manda(f"N{self.n + 1} LOGOUT")
            self.s.close()
        except OSError:
            pass


class Postino:
    """Fa girare la lettura della casella (LETTURA) ASPETTA secondi dopo l'ultima mail nuova; una alla volta."""

    def __init__(self, comando, aspetta=ASPETTA, prova=False):
        self.comando, self.attesa, self.prova = comando, aspetta, prova
        self.cv, self.ultima = threading.Condition(), None
        threading.Thread(target=self._lavora, daemon=True).start()

    def suona(self, chi):
        with self.cv:
            self.ultima = time.monotonic()
            self.cv.notify()
        scrivi(f"{chi}: mail nuova" + (" (prova: non leggo la casella)" if self.prova else ""))

    def _lavora(self):
        while True:
            with self.cv:
                while self.ultima is None:
                    self.cv.wait()
                while time.monotonic() - self.ultima < self.attesa:
                    self.cv.wait(self.attesa - (time.monotonic() - self.ultima))
                self.ultima = None
            if self.prova:
                continue
            inizio = time.monotonic()
            try:
                r = subprocess.run(self.comando, timeout=600)
                scrivi(f"casella letta e giro lampo controllato in {time.monotonic() - inizio:.0f} s"
                       + (f" (uscita {r.returncode}: vedi fonti.log e comunicati.log)" if r.returncode else ""))
            except Exception as e:
                scrivi(f"ERRORE nel leggere la casella: {type(e).__name__}: {e}")


def segui(nome, conf_p, server, postino, fino=None):
    """Tiene collegata una casella per sempre (o fino a `fino`, nelle prove), riprovando dopo gli errori."""
    errori = 0
    while fino is None or time.monotonic() < fino:
        imap = None
        try:
            with open(conf_p, encoding="utf-8") as f:
                conf = json.load(f)
            imap = Imap(conf.get("server", server))
            imap.entra(conf["utente"], conf["password"])
            quante = imap.esamina()
            scrivi(f"{nome}: collegata, {quante} mail, aspetto quelle nuove")
            errori = 0
            while fino is None or time.monotonic() < fino:
                durata = RINNOVA if fino is None else max(1, min(RINNOVA, fino - time.monotonic()))
                quante = imap.aspetta(quante, durata, lambda: postino.suona(nome))
                imap.comando("NOOP")
        except FileNotFoundError:
            scrivi(f"{nome}: {os.path.basename(conf_p)} non c'è, casella non seguita")
            return
        except Exception as e:
            attesa = ATTESE[min(errori, len(ATTESE) - 1)]
            errori += 1
            if errori <= 5 or errori % 12 == 0:
                scrivi(f"{nome}: {type(e).__name__}: {str(e)[:160]} — mi ricollego tra {attesa} s"
                       + (f" ({errori} errori di fila)" if errori > 1 else ""))
            if imap:
                imap.chiudi()
            if fino is not None and time.monotonic() + attesa >= fino:
                return
            time.sleep(attesa)
            continue
        if imap:
            imap.chiudi()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--prova", type=int, metavar="SECONDI", help="si collega e dice cosa sente, senza far partire niente")
    a = ap.parse_args()
    postino = Postino(LETTURA, prova=bool(a.prova))
    fino = time.monotonic() + a.prova if a.prova else None
    scrivi("posta in diretta: avvio" + (f" (prova per {a.prova} s)" if a.prova else ""))
    fili = [threading.Thread(target=segui, args=(nome, conf, server, postino, fino), daemon=True)
            for nome, conf, server in CASELLE]
    for t in fili:
        t.start()
    for t in fili:
        t.join()
    scrivi("posta in diretta: fine" + (" della prova" if a.prova else " (nessuna casella da seguire)"))


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
