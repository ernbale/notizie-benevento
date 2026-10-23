#!/usr/bin/env python3
"""Pubblica sulla Pagina Facebook (facebook.com/notiziebenevento) le notizie nuove, una alla volta.

Lo esegue GitHub dopo ogni pubblicazione del sito (a ogni giro dell'agente e ogni ora), così la pagina della
notizia è già online quando Facebook ne legge titolo e immagine di anteprima.

- Al massimo una notizia all'ora (almeno 50 minuti tra un post e l'altro), e al massimo 20 al giorno (per i giorni con tante notizie), solo dalle 6
  fino al giro delle 22 compreso, come i giri (scelta del proprietario, 23 ott 2026): come le pagine dei giornali locali, senza raffiche che sembrano spam. Dalle 23 alle 24 solo le allerte
  arancioni o rosse (allerta_seria): è il giro della sera prima di un'allerta arancione o rossa, con le scuole chiuse
  per domani. La gialla alle 23 no (scelta del proprietario, 23 ott 2026: vale per Facebook, Telegram e Instagram).
- Dalle RIEPILOGO_DALLE il riepilogo della giornata («Il Sannio oggi»): la copertina di Instagram (pagine.py) con le
  notizie più importanti di oggi e i loro link. È in più delle 20 notizie (scelta del proprietario, 23 ott 2026: «20 +
  riepilogo per entrambi») e dopo, fino al mattino, solo le allerte delle 23.
- Sceglie la più importante tra le notizie delle ultime 12 ore non ancora pubblicate (stessa importanza della prima
  pagina del sito: rilevante e numero di fonti, che calano col tempo).
- Cosa è già uscito lo legge dalla Pagina stessa (i link dei post): niente file da tenere nel repository. Se Facebook
  non risponde alla lettura non pubblica niente, per non fare doppioni.
- La chiave è il «token della Pagina» nel segreto FB_PAGE_TOKEN di GitHub; senza chiave non fa niente.
  Il repository è pubblico: nei log si stampano solo gli esiti, mai la chiave.

Uso:  FB_PAGE_TOKEN=… python3 strumenti/facebook.py [--sito .] [--stato FILE]
      FB_SUBITO=2 …   (lanciato a mano da GitHub: 2 notizie adesso, senza aspettare la pausa tra un post e l'altro)
      python3 strumenti/facebook.py --prova      (dice cosa pubblicherebbe, senza chiave e senza toccare Facebook)
"""
import argparse
import datetime as dt
import json
import os
import re
import socket
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

SITO = "https://notiziebenevento.it"
PAGINA = "Notizie Benevento"
GRAPH = "https://graph.facebook.com"
MAX_GIORNO = 20
PAUSA_MINUTI = 50
ORE_FINESTRA = 12
RIEPILOGO_DALLE = 20   # il riepilogo della giornata, su Facebook e su Instagram (dalle 20: voluto dal proprietario)
RIEPILOGO_PAUSA = 30   # minuti dall'ultimo post
TITOLO_RIEPILOGO = "Il Sannio oggi"
DALLE, ALLE = 6, 23   # dalle 6 fino al giro delle 22 compreso (ALLE è l'ora in cui si smette)


def fuso():
    try:
        from zoneinfo import ZoneInfo
        return ZoneInfo("Europe/Rome")
    except Exception:
        return dt.timezone(dt.timedelta(hours=1))


def quando(n, adesso):
    """L'ora di pubblicazione; con la sola data, come fa il sito: a metà tra mezzanotte e adesso, non oltre mezzogiorno."""
    p = str(n.get("pubblicato") or "")
    if re.match(r"^\d{4}-\d{2}-\d{2}$", p):
        mezzanotte = dt.datetime.fromisoformat(p + "T00:00:00").replace(tzinfo=fuso())
        return min(mezzanotte + dt.timedelta(hours=12), mezzanotte + max(adesso - mezzanotte, dt.timedelta(0)) / 2)
    try:
        t = dt.datetime.fromisoformat(p)
        return t if t.tzinfo else t.replace(tzinfo=fuso())
    except ValueError:
        return None


def rilievo(n, t, adesso):
    ore = max(0.0, (adesso - t).total_seconds() / 3600)
    fonti = n.get("fonti") if isinstance(n.get("fonti"), list) else [1]
    return ((5 if n.get("rilevante") else 1) + min(len(fonti), 6) * 0.25) * 0.5 ** (ore / 18)


def allerta_seria(n):
    """La notizia di un'allerta arancione o rossa, l'unica che esce alle 23 su tutti i social (la gialla no)."""
    return (n.get("categoria") == "meteo" and bool(n.get("rilevante"))
            and re.search(r"\b(arancion[ei]|ross[ae])\b", n.get("titolo") or "", re.I) is not None)


def candidate(notizie, gia, adesso):
    out = []
    for n in notizie:
        t = quando(n, adesso)
        if not t or n.get("id") in gia or t > adesso or adesso - t > dt.timedelta(hours=ORE_FINESTRA):
            continue
        out.append((rilievo(n, t, adesso), n))
    return [n for _, n in sorted(out, key=lambda x: -x[0])]


def messaggio(n):
    m = n["titolo"].strip() + ("\n\n" + n["sintesi"].strip() if n.get("sintesi") else "")
    if n.get("stato") == "una_fonte" and n.get("fonti"):
        m += f"\n\nPer ora lo riporta solo {n['fonti'][0].get('nome', '')}."
    return m


def chiama(metodo, percorso, token, dati=None):
    dati = dict(dati or {}, access_token=token)
    corpo = urllib.parse.urlencode(dati).encode()
    if metodo == "GET":
        req = urllib.request.Request(f"{GRAPH}/{percorso}?{corpo.decode()}")
    else:
        req = urllib.request.Request(f"{GRAPH}/{percorso}", data=corpo, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        # l'errore di Facebook dice cosa non va (chiave scaduta, permesso mancante…) e non contiene la chiave
        try:
            err = json.load(e).get("error", {})
            raise RuntimeError(f"Facebook {e.code}: {err.get('message', '')} (codice {err.get('code')})") from None
        except ValueError:
            raise RuntimeError(f"Facebook {e.code}") from None


def riprova(fare, cosa, lettura=False):
    """Tre tentativi (dopo 5 e 30 secondi): un errore di passaggio non deve far perdere un post. Una lettura si
    riprova sempre; un invio solo se Facebook ha risposto di no (errore HTTP) o la connessione non è nemmeno partita:
    se la risposta si è persa per strada (tempo scaduto) il post potrebbe essere uscito, e riprovare alla cieca farebbe
    un doppione. In quel caso si finisce con errore e alla volta dopo si ricontrolla sulla Pagina."""
    for attesa in (5, 30, None):
        try:
            return fare()
        except Exception as e:
            incerto = isinstance(e, (TimeoutError, socket.timeout)) or (
                isinstance(e, urllib.error.URLError) and isinstance(e.reason, (TimeoutError, socket.timeout)))
            if attesa is None or (incerto and not lettura):
                raise RuntimeError(f"{cosa}: {e}" + (" (forse è uscito: si ricontrolla dopo)" if incerto else "")) from None
            print(f"  {cosa}: {e} — riprovo tra {attesa} s")
            time.sleep(attesa)


def online(url):
    try:
        with urllib.request.urlopen(urllib.request.Request(url, method="HEAD"), timeout=20) as r:
            return r.status == 200
    except Exception:
        return False


def foto_con_testo(token, foto, testo, link):
    """Un post con la foto (se è online) e il testo; se Facebook dice di no alla foto, un post col testo e il link.
    Se la foto è uscita non si fa mai anche il post col link: il testo, se manca, si aggiunge al post della foto."""
    if foto and online(foto):
        r = None
        try:
            r = riprova(lambda: chiama("POST", "me/photos", token, {"url": foto, "caption": testo}), "Facebook (foto)")
        except RuntimeError as e:
            if "forse è uscito" in str(e):
                raise
            print(f"  Facebook: la foto non è passata ({e}): pubblico il post col link")
        if r:
            pid = r.get("post_id") or f"{r.get('page_id', '')}_{r.get('id')}"
            letto = riprova(lambda: chiama("GET", pid, token, {"fields": "message"}), "Facebook (rilettura)", True)
            if not (letto.get("message") or "").strip():   # il testo deve esserci: se manca, lo si scrive nel post
                riprova(lambda: chiama("POST", pid, token, {"message": testo}), "Facebook (testo del post)")
            return
    riprova(lambda: chiama("POST", "me/feed", token, {"message": testo, "link": link}), "Facebook")


def testo_riepilogo(giorno, notizie):
    m = f"{TITOLO_RIEPILOGO}, {giorno}: le notizie più importanti della giornata.\n\n"
    m += "\n\n".join(f"{i}. {n['titolo'].strip()}\n{SITO}/notizia/{n['id']}/" for i, n in enumerate(notizie, 1))
    return m + f"\n\nTutte le notizie di Benevento e del Sannio: {SITO}/"


def gia_pubblicate(token, adesso):
    """Gli id delle notizie già sulla Pagina, quante notizie oggi (il riepilogo e le chiusure non contano), l'ora
    dell'ultima e se il riepilogo di oggi c'è già."""
    r = chiama("GET", "me/posts", token, {"fields": "created_time,message,attachments{unshimmed_url,url}", "limit": 50})
    ids, oggi, ultimo, riepilogo = set(), 0, None, False
    for p in r.get("data", []):
        t = dt.datetime.strptime(p["created_time"], "%Y-%m-%dT%H:%M:%S%z").astimezone(fuso())
        riepilogo |= t.date() == adesso.date() and (p.get("message") or "").startswith(TITOLO_RIEPILOGO)
        for a in (p.get("attachments") or {}).get("data", []):
            u = a.get("unshimmed_url") or a.get("url") or ""
            u = urllib.parse.parse_qs(urllib.parse.urlparse(u).query).get("u", [u])[0]  # link «l.facebook.com/l.php?u=»
            m = re.search(r"notiziebenevento\.it/notizia/([a-z0-9-]+)", u)
            if m:
                ids.add(m.group(1))
                oggi += t.date() == adesso.date()
                ultimo = max(ultimo, t) if ultimo else t
    return ids, oggi, ultimo, riepilogo


def fai_riepilogo(token, a, notizie, adesso, ultimo):
    """Il riepilogo della giornata, se è il momento: True se ha finito il lavoro di questa volta (pubblicato o da
    aspettare), False se oggi non c'è (poche notizie) e si va avanti con le notizie normali."""
    from instagram import riepilogo_pronto
    r = riepilogo_pronto(a.sito, notizie, adesso)
    if not r:
        print("Facebook: niente riepilogo oggi (poche notizie)")
        return False
    if ultimo and adesso - ultimo < dt.timedelta(minutes=RIEPILOGO_PAUSA):
        print(f"Facebook: l'ultimo post è delle {ultimo:%H:%M}, il riepilogo al prossimo giro")
        return True
    stato = {}
    if a.stato:
        try:
            with open(a.stato, encoding="utf-8") as f:
                stato = json.load(f)
        except (OSError, ValueError):
            pass
    if stato.get("riepilogo_tentato") == adesso.date().isoformat():
        # tentato prima e non visto sulla Pagina: forse è uscito senza testo. Meglio niente che due riepiloghi
        raise RuntimeError("il riepilogo di oggi è già stato tentato ma sulla Pagina non si vede: controllare a mano")
    if a.stato:
        os.makedirs(os.path.dirname(a.stato) or ".", exist_ok=True)
        with open(a.stato, "w", encoding="utf-8") as f:
            json.dump({"riepilogo_tentato": adesso.date().isoformat()}, f)
    giorno, scelte, immagini = r
    foto_con_testo(token, immagini[0], testo_riepilogo(giorno, scelte), f"{SITO}/")
    print(f"Facebook: pubblicato il riepilogo della giornata ({len(scelte)} notizie)")
    return True


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sito", default=os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    ap.add_argument("--prova", action="store_true", help="dice cosa pubblicherebbe, senza toccare Facebook")
    ap.add_argument("--stato", help="il file dove si segna il riepilogo tentato (lo conserva GitHub)")
    a = ap.parse_args()
    adesso = dt.datetime.now(fuso())
    with open(os.path.join(a.sito, "notizie.json"), encoding="utf-8") as f:
        notizie = json.load(f).get("notizie", [])

    if a.prova:
        for n in candidate(notizie, set(), adesso)[:MAX_GIORNO]:
            print(f"- {n['id']}\n  {messaggio(n)[:160]}…\n  {SITO}/notizia/{n['id']}/")
        return

    token = os.environ.get("FB_PAGE_TOKEN", "").strip()
    if not token:
        print("Facebook: nessuna chiave (segreto FB_PAGE_TOKEN), non pubblico niente")
        return
    sera = adesso.hour == 23   # alle 23 solo le allerte arancioni o rosse: chi ha figli a scuola guarda la sera
    if not DALLE <= adesso.hour < ALLE and not sera:
        print(f"Facebook: sono le {adesso:%H:%M}, si pubblica dalle {DALLE} fino al giro delle {ALLE - 1}")
        return
    # la chiave deve essere quella della Pagina Notizie Benevento: mai pubblicare altrove (profilo, altre pagine)
    chi = chiama("GET", "me", token, {"fields": "name"}).get("name")
    if chi != PAGINA:
        raise RuntimeError(f"la chiave non è della Pagina «{PAGINA}»: non pubblico niente")
    gia, oggi, ultimo, riepilogo = gia_pubblicate(token, adesso)
    if not sera:
        if riepilogo:
            print("Facebook: il riepilogo di oggi è già uscito, a domani")
            return
        if adesso.hour >= RIEPILOGO_DALLE and fai_riepilogo(token, a, notizie, adesso, ultimo):
            return
        if oggi >= MAX_GIORNO:
            print(f"Facebook: già {oggi} notizie oggi (il massimo è {MAX_GIORNO}, più il riepilogo), basta così")
            return
    subito = int(os.environ.get("FB_SUBITO") or 0)   # solo quando lo chiede il proprietario, dal pulsante di GitHub
    if not subito and ultimo and adesso - ultimo < dt.timedelta(minutes=PAUSA_MINUTI):
        print(f"Facebook: l'ultimo post è delle {ultimo:%H:%M}, aspetto")
        return
    lista = candidate(notizie, gia, adesso)
    if sera:
        lista = [n for n in lista if allerta_seria(n)]
        if not lista:
            print("Facebook: sono le 23, a quest'ora si pubblicano solo le allerte arancioni o rosse")
            return
    if not lista:
        print("Facebook: nessuna notizia nuova da pubblicare")
        return
    for n in lista[:max(1, min(max(subito, 1), MAX_GIORNO - oggi))]:
        chiama("POST", "me/feed", token, {"message": messaggio(n), "link": f"{SITO}/notizia/{n['id']}/"})
        oggi += 1
        print(f"Facebook: pubblicata {n['id']} ({oggi} oggi)")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print("AVVISO Facebook:", e, file=sys.stderr)
        sys.exit(1)
