#!/usr/bin/env python3
"""Pubblica sulla Pagina Facebook (facebook.com/notiziebenevento) le notizie nuove, una alla volta.

Lo esegue GitHub dopo ogni pubblicazione del sito (a ogni giro dell'agente e ogni ora), così la pagina della
notizia è già online quando Facebook ne legge titolo e immagine di anteprima.

- Al massimo una notizia all'ora (almeno 50 minuti tra un post e l'altro), e al massimo 20 al giorno (per i giorni con tante notizie), solo dalle 7
  alle 22: come le pagine dei giornali locali, senza raffiche che sembrano spam. Dalle 23 alle 24 solo le allerte
  importanti (`rilevante`): è il giro della sera prima di un'allerta arancione o rossa, con le scuole chiuse per domani.
- Sceglie la più importante tra le notizie delle ultime 12 ore non ancora pubblicate (stessa importanza della prima
  pagina del sito: rilevante e numero di fonti, che calano col tempo).
- Cosa è già uscito lo legge dalla Pagina stessa (i link dei post): niente file da tenere nel repository. Se Facebook
  non risponde alla lettura non pubblica niente, per non fare doppioni.
- La chiave è il «token della Pagina» nel segreto FB_PAGE_TOKEN di GitHub; senza chiave non fa niente.
  Il repository è pubblico: nei log si stampano solo gli esiti, mai la chiave.

Uso:  FB_PAGE_TOKEN=… python3 strumenti/facebook.py [--sito .]
      FB_SUBITO=2 …   (lanciato a mano da GitHub: 2 notizie adesso, senza aspettare la pausa tra un post e l'altro)
      python3 strumenti/facebook.py --prova      (dice cosa pubblicherebbe, senza chiave e senza toccare Facebook)
"""
import argparse
import datetime as dt
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request

SITO = "https://notiziebenevento.it"
PAGINA = "Notizie Benevento"
GRAPH = "https://graph.facebook.com"
MAX_GIORNO = 20
PAUSA_MINUTI = 50
ORE_FINESTRA = 12
DALLE, ALLE = 7, 22


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


def gia_pubblicate(token, adesso):
    """Gli id delle notizie già sulla Pagina, quanti post oggi e l'ora dell'ultimo."""
    r = chiama("GET", "me/posts", token, {"fields": "created_time,attachments{unshimmed_url,url}", "limit": 50})
    ids, oggi, ultimo = set(), 0, None
    for p in r.get("data", []):
        t = dt.datetime.strptime(p["created_time"], "%Y-%m-%dT%H:%M:%S%z").astimezone(fuso())
        for a in (p.get("attachments") or {}).get("data", []):
            u = a.get("unshimmed_url") or a.get("url") or ""
            u = urllib.parse.parse_qs(urllib.parse.urlparse(u).query).get("u", [u])[0]  # link «l.facebook.com/l.php?u=»
            m = re.search(r"notiziebenevento\.it/notizia/([a-z0-9-]+)", u)
            if m:
                ids.add(m.group(1))
                oggi += t.date() == adesso.date()
                ultimo = max(ultimo, t) if ultimo else t
    return ids, oggi, ultimo


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sito", default=os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    ap.add_argument("--prova", action="store_true", help="dice cosa pubblicherebbe, senza toccare Facebook")
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
    sera = adesso.hour == 23   # alle 23 solo le allerte: chi ha figli a scuola guarda la sera
    if not DALLE <= adesso.hour < ALLE and not sera:
        print(f"Facebook: sono le {adesso:%H:%M}, si pubblica dalle {DALLE} alle {ALLE}")
        return
    # la chiave deve essere quella della Pagina Notizie Benevento: mai pubblicare altrove (profilo, altre pagine)
    chi = chiama("GET", "me", token, {"fields": "name"}).get("name")
    if chi != PAGINA:
        raise RuntimeError(f"la chiave non è della Pagina «{PAGINA}»: non pubblico niente")
    gia, oggi, ultimo = gia_pubblicate(token, adesso)
    if oggi >= MAX_GIORNO:
        print(f"Facebook: già {oggi} notizie oggi, basta così")
        return
    subito = int(os.environ.get("FB_SUBITO") or 0)   # solo quando lo chiede il proprietario, dal pulsante di GitHub
    if not subito and ultimo and adesso - ultimo < dt.timedelta(minutes=PAUSA_MINUTI):
        print(f"Facebook: l'ultimo post è delle {ultimo:%H:%M}, aspetto")
        return
    lista = candidate(notizie, gia, adesso)
    if sera:
        lista = [n for n in lista if n.get("categoria") == "meteo" and n.get("rilevante")]
        if not lista:
            print("Facebook: sono le 23, a quest'ora si pubblicano solo le allerte importanti")
            return
    if not lista:
        print("Facebook: nessuna notizia nuova da pubblicare")
        return
    for n in lista[:min(max(subito, 1), MAX_GIORNO - oggi)]:
        chiama("POST", "me/feed", token, {"message": messaggio(n), "link": f"{SITO}/notizia/{n['id']}/"})
        oggi += 1
        print(f"Facebook: pubblicata {n['id']} ({oggi} oggi)")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print("AVVISO Facebook:", e, file=sys.stderr)
        sys.exit(1)
