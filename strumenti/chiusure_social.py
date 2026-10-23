#!/usr/bin/env python3
"""Le chiusure dei Comuni (chiusure.json, strumenti/chiusure.py) su Telegram, Facebook e Instagram, a qualsiasi ora.

Voluto dal proprietario il 23 ott 2026: «in caso di chiusura va messa su tutti i social a qualsiasi ora e anche sito»,
Telegram «con suono, è importante», «non ci deve essere nessun fallimento, nessun doppione».

Lo esegue GitHub dopo ogni pubblicazione del sito, prima degli altri social. Niente orari, niente limiti al giorno,
niente pausa. Per le chiusure nuove o cambiate (chiave id@ora dell'ultima modifica):
- Telegram: un messaggio con il suono (anche di notte) con le chiusure nuove, ognuna col link alla sua voce della
  pagina Scuole chiuse (…/scuole-chiuse/#id) e all'ordinanza.
- Facebook: un post con la foto dell'elenco (img/ig/chiusure-….jpg, la fa pagine.py) e nel testo tutte le chiusure di
  oggi e dei prossimi giorni, con le novità in fondo. Se la foto non passa, un post col link alla pagina.
- Instagram: la stessa foto con lo stesso testo.

Niente doppioni: cosa è già uscito lo ricorda un file (--stato, che GitHub conserva come quello di telegram.py) e lo si
ricontrolla sui canali stessi: su Telegram i link #id nell'anteprima pubblica, su Facebook e Instagram il nome del Comune
in un post delle chiusure («🚸» in testa) uscito dopo l'ultima modifica. Se il file non c'è e un canale non si legge,
su quel canale non si pubblica (meglio un minuto dopo che due volte) e il programma finisce con errore.
Niente fallimenti: ogni chiamata si riprova 3 volte; se un canale non va gli altri escono lo stesso, il programma
finisce con errore (il passo di GitHub diventa rosso e arriva la mail) e la sentinella rilancia la pubblicazione.

Uso:  python3 strumenti/chiusure_social.py --stato FILE      (con TELEGRAM_TOKEN e FB_PAGE_TOKEN)
      python3 strumenti/chiusure_social.py --prova           (dice cosa manderebbe, senza chiavi e senza toccare niente)
"""
import argparse
import datetime as dt
import html
import json
import os
import re
import socket
import sys
import time
import urllib.error
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from facebook import GRAPH, PAGINA, SITO, fuso   # noqa: E402
import facebook   # noqa: E402
import telegram   # noqa: E402

PAGINA_CHIUSURE = f"{SITO}/scuole-chiuse/"
SEGNO = "🚸"   # in testa a ogni messaggio delle chiusure: così si riconoscono sui canali
GIORNI = ["lunedì", "martedì", "mercoledì", "giovedì", "venerdì", "sabato", "domenica"]
MESI = ["gennaio", "febbraio", "marzo", "aprile", "maggio", "giugno", "luglio", "agosto", "settembre", "ottobre",
        "novembre", "dicembre"]


def riprova(fare, cosa, lettura=False):
    """Tre tentativi (dopo 5 e 30 secondi): un errore di passaggio non deve perdere una chiusura. Una lettura si
    riprova sempre; un invio solo se il canale ha risposto di no (errore HTTP) o la connessione non è nemmeno partita:
    se la risposta si è persa per strada (tempo scaduto) il messaggio potrebbe essere uscito, e riprovare alla cieca
    farebbe un doppione. In quel caso si finisce con errore e alla pubblicazione dopo il canale si ricontrolla."""
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


def chiave(c):
    return f"{c['id']}@{c.get('aggiornata') or c.get('aggiunta')}"


def ora_di(c):
    return dt.datetime.fromisoformat(c.get("aggiornata") or c.get("aggiunta"))


def giorno(g, oggi):
    d = dt.date.fromisoformat(g)
    nome = f"{GIORNI[d.weekday()]} {d.day} {MESI[d.month - 1]}"
    return f"Oggi, {nome}" if d == oggi else f"Domani, {nome}" if d == oggi + dt.timedelta(days=1) else nome.capitalize()


def per_giorno(chiusure, oggi):
    per = {}
    for c in chiusure:
        if not c.get("revocata"):
            for g in c.get("giorni") or []:
                if g >= oggi.isoformat():
                    per.setdefault(g, []).append(c)
    return {g: sorted(per[g], key=lambda c: c["comune"]) for g in sorted(per)}


def scuole(chiusure):
    return any("scuol" in c.get("cosa", "").lower() for c in chiusure)


# ---------------------------------------------------------------- i testi

def esc(s):
    """Per l'HTML di Telegram: solo &, < e > (gli apostrofi restano apostrofi)."""
    return html.escape(str(s), quote=False)


def testo_telegram(nuove, oggi):
    """Il messaggio di Telegram (HTML) con le sole chiusure nuove o cambiate, diviso se è troppo lungo."""
    testa = f"{SEGNO} <b>{'Scuole chiuse' if scuole(nuove) else 'Chiusure dei Comuni'}</b>"
    righe = []
    for c in sorted(nuove, key=lambda c: (min(c["giorni"]), c["comune"])):
        quando = ", ".join(giorno(g, oggi).lower() for g in c["giorni"] if g >= oggi.isoformat()) or "finita"
        f = c.get("fonte") or {}
        r = (f'• <a href="{PAGINA_CHIUSURE}#{c["id"]}">{esc(c["comune"])}</a>: '
             + ("<b>revocata</b>, " if c.get("revocata") else "") + f"{esc(c['cosa'])} ({quando})")
        if c.get("aggiornata") and not c.get("revocata"):
            r += " — <i>aggiornata</i>"
        if str(f.get("url") or "").startswith("http"):
            r += f' · <a href="{esc(f["url"]).replace(chr(34), "&quot;")}">{esc(f.get("nome") or "ordinanza")}</a>'
        righe.append(r)
    piede = f'\n\nTutte le chiusure, con le ordinanze: <a href="{PAGINA_CHIUSURE}">notiziebenevento.it/scuole-chiuse</a>'
    pezzi, cur = [], []
    for r in righe:   # Telegram tiene 4096 caratteri: oltre, più messaggi
        if cur and len(testa) + len("\n".join(cur + [r])) + len(piede) > 3800:
            pezzi.append(cur)
            cur = []
        cur.append(r)
    pezzi.append(cur)
    return [f"{testa}{' (segue)' if i else ''}\n\n" + "\n".join(p) + piede for i, p in enumerate(pezzi)]


def testo_post(tutte, nuove, oggi, instagram=False):
    """Facebook e Instagram: tutte le chiusure di oggi e dei prossimi giorni, con le novità in fondo."""
    per = per_giorno(tutte, oggi)
    m = f"{SEGNO} {'Scuole chiuse' if scuole(tutte) else 'Chiusure dei Comuni'}"
    agg = max((ora_di(c) for c in tutte), default=None)
    if agg:
        m += f" – aggiornato alle {agg.astimezone(fuso()):%H:%M}"
    for g, cs in per.items():
        m += f"\n\n{giorno(g, oggi)}:\n" + "\n".join(f"• {c['comune']}: {c['cosa']}" for c in cs)
    revocate = [c["comune"] for c in nuove if c.get("revocata")]
    if revocate:
        m += "\n\nRevocata la chiusura: " + ", ".join(revocate) + "."
    novita = sorted({c["comune"] for c in nuove if not c.get("revocata")})
    if novita and len(novita) < len({c["comune"] for cs in per.values() for c in cs}):
        m += "\n\nNovità: " + ", ".join(novita) + "."
    if instagram:
        m += "\n\nLe ordinanze e l'elenco sempre aggiornato su notiziebenevento.it (link nella bio)."
        return m + "\n\n#Benevento #Sannio #scuolechiuse #allertameteo"
    return m + f"\n\nLe ordinanze e l'elenco sempre aggiornato: {PAGINA_CHIUSURE}"


# ---------------------------------------------------------------- cosa è già uscito, letto dai canali

def uscite_telegram(piu_vecchia):
    """{id: [ore dei messaggi che lo citano]} dall'anteprima pubblica del canale, pagine indietro finché serve."""
    trovate, prima = {}, None
    for _ in range(6):
        url = telegram.ANTEPRIMA + (f"?before={prima}" if prima else "")
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (notiziebenevento.it)"})
        with urllib.request.urlopen(req, timeout=30) as r:
            pagina = r.read().decode("utf-8", "replace")
        blocchi = re.split(r'(?=<div class="tgme_widget_message_wrap)', pagina)[1:]
        if not blocchi:
            break
        ore = []
        for b in blocchi:
            t = re.search(r'<time datetime="([^"]+)"', b)
            if not t:
                continue
            t = dt.datetime.fromisoformat(t.group(1))
            ore.append(t)
            for i in re.findall(r"notiziebenevento\.it/scuole-chiuse/#([a-z0-9-]+)", b):
                trovate.setdefault(i, []).append(t)
        n = re.findall(r'data-post="[^/"]+/(\d+)"', pagina)
        if not ore or min(ore) < piu_vecchia or not n:
            break
        prima = min(int(x) for x in n)
    return trovate


def post_chiusure(elenco, campo_testo, campo_ora):
    """[(ora, testo)] dei post delle chiusure (quelli che cominciano con 🚸)."""
    out = []
    for p in elenco:
        t = p.get(campo_testo) or ""
        if t.startswith(SEGNO):
            out.append((dt.datetime.strptime(p[campo_ora], "%Y-%m-%dT%H:%M:%S%z"), t))
    return out


def gia_nel_post(c, posts):
    """La chiusura è già in un post delle chiusure uscito dopo la sua ultima modifica (col nome del Comune)."""
    return any(t >= ora_di(c) and c["comune"] in testo for t, testo in posts)


# ---------------------------------------------------------------- l'invio

def online(url):
    try:
        with urllib.request.urlopen(urllib.request.Request(url, method="HEAD"), timeout=20) as r:
            return r.status == 200
    except Exception:
        return False


def manda_telegram(token, testi):
    for t in testi:
        riprova(lambda: telegram.chiama(token, "sendMessage", {   # col suono: niente disable_notification
            "chat_id": telegram.CANALE, "text": t, "parse_mode": "HTML",
            "link_preview_options": {"is_disabled": True}}), "Telegram")


def manda_facebook(token, testo, foto):
    """La foto dell'elenco col testo; se Facebook dice di no alla foto, il post col link alla pagina. Se la foto è
    uscita non si fa mai anche il post col link: il testo, se manca, si aggiunge al post della foto."""
    if foto and online(foto):
        r = None
        try:
            r = riprova(lambda: facebook.chiama("POST", "me/photos", token, {"url": foto, "caption": testo}), "Facebook (foto)")
        except RuntimeError as e:
            if "forse è uscito" in str(e):
                raise
            print(f"  Facebook: la foto non è passata ({e}): pubblico il post col link")
        if r:
            pid = r.get("post_id") or f"{r.get('page_id', '')}_{r.get('id')}"
            letto = riprova(lambda: facebook.chiama("GET", pid, token, {"fields": "message"}), "Facebook (rilettura)", True)
            if not (letto.get("message") or "").strip():   # il testo deve esserci: se manca, lo si scrive nel post
                riprova(lambda: facebook.chiama("POST", pid, token, {"message": testo}), "Facebook (testo del post)")
            return
    riprova(lambda: facebook.chiama("POST", "me/feed", token, {"message": testo, "link": PAGINA_CHIUSURE}), "Facebook")


def manda_instagram(token, ig, testo, foto):
    if not foto or not online(foto):
        raise RuntimeError(f"Instagram: l'immagine delle chiusure non è online ({foto}): riprovo alla prossima pubblicazione")
    import instagram
    cont = riprova(lambda: facebook.chiama("POST", f"{ig}/media", token, {"image_url": foto, "caption": testo})["id"],
                   "Instagram")
    instagram.aspetta(cont, token)
    riprova(lambda: facebook.chiama("POST", f"{ig}/media_publish", token, {"creation_id": cont}), "Instagram (pubblica)")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sito", default=os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    ap.add_argument("--stato", help="il file che ricorda cosa è già uscito (lo conserva GitHub)")
    ap.add_argument("--prova", action="store_true")
    a = ap.parse_args()
    adesso = dt.datetime.now(fuso())
    oggi = adesso.date()
    try:
        with open(os.path.join(a.sito, "chiusure.json"), encoding="utf-8") as f:
            dati = json.load(f)
    except (OSError, ValueError):
        print("Chiusure: chiusure.json non c'è, niente da fare")
        return 0
    tutte = [c for c in dati.get("chiusure", []) if max(c.get("giorni") or [""]) >= oggi.isoformat()]
    if not tutte:
        print("Chiusure: nessuna chiusura per oggi o i prossimi giorni")
        return 0
    try:
        with open(os.path.join(a.sito, "img", "ig", "chiusure.json"), encoding="utf-8") as f:
            foto = f"{SITO}/{json.load(f)['immagine']}"
    except (OSError, ValueError, KeyError):
        foto = None

    stato, stato_perso = {}, True
    if a.stato:
        try:
            with open(a.stato, encoding="utf-8") as f:
                stato, stato_perso = json.load(f), False
        except (OSError, ValueError):
            pass
    for canale in ("telegram", "facebook", "instagram"):
        stato.setdefault(canale, {})
    chiavi = {chiave(c) for c in tutte}

    if a.prova:
        print("Telegram:\n" + "\n---\n".join(testo_telegram(tutte, oggi)))
        print(f"\nFacebook (foto {foto}):\n" + testo_post(tutte, tutte, oggi))
        print("\nInstagram:\n" + testo_post(tutte, tutte, oggi, instagram=True))
        return 0

    errori = []
    piu_vecchia = min(ora_di(c) for c in tutte) - dt.timedelta(hours=1)
    # i canali di cui il ricordo non basta: file perso, o un invio dall'esito incerto (risposta persa per strada).
    # Restano incerti finché non si rileggono: fino ad allora lì non si manda niente, per non fare doppioni.
    incerti = set(stato.get("incerti") or []) | ({"telegram", "facebook", "instagram"} if stato_perso else set())

    def segna(canale, cs):
        for c in cs:
            stato[canale][chiave(c)] = adesso.isoformat(timespec="seconds")

    def da_mandare(canale, gia_uscita):
        """Le chiusure non ancora uscite su quel canale (None se non si può sapere: allora non si manda)."""
        try:
            letto = gia_uscita()
        except Exception as e:
            if canale in incerti:
                errori.append(f"{canale}: non so cosa è già uscito (ricordo incerto e canale illeggibile: {e}), "
                              "non mando: si riprova alla prossima pubblicazione")
                return None
            print(f"  {canale}: non leggo il canale ({e}), mi fido del ricordo")
            letto = lambda c: False
        else:
            incerti.discard(canale)
            segna(canale, [c for c in tutte if chiave(c) not in stato[canale] and letto(c)])   # già sul canale
        return [c for c in tutte if chiave(c) not in stato[canale]]

    def invio_fallito(canale, e):
        if "forse è uscito" in str(e):
            incerti.add(canale)
        errori.append(f"{canale}: {e}")

    tg = os.environ.get("TELEGRAM_TOKEN", "").strip()
    fb = os.environ.get("FB_PAGE_TOKEN", "").strip()
    try:
        if not tg:
            raise RuntimeError("manca TELEGRAM_TOKEN")

        def tg_letto():
            usc = riprova(lambda: uscite_telegram(piu_vecchia), "Telegram (anteprima del canale)", True)
            return lambda c: any(t >= ora_di(c) for t in usc.get(c["id"], []))
        nuove = da_mandare("telegram", tg_letto)
        if nuove:
            manda_telegram(tg, testo_telegram(nuove, oggi))
            segna("telegram", nuove)
            print(f"Chiusure su Telegram: {', '.join(c['comune'] for c in nuove)}")
    except Exception as e:
        invio_fallito("telegram", e)

    ig = None
    try:
        if not fb:
            raise RuntimeError("manca FB_PAGE_TOKEN")
        pag = riprova(lambda: facebook.chiama("GET", "me", fb, {"fields": "name,instagram_business_account{id}"}), "Facebook",
                      True)
        if pag.get("name") != PAGINA:
            raise RuntimeError(f"la chiave non è della Pagina «{PAGINA}»: non pubblico niente")
        ig = (pag.get("instagram_business_account") or {}).get("id")

        def fb_letto():
            r = riprova(lambda: facebook.chiama("GET", "me/posts", fb, {"fields": "message,created_time", "limit": 50}),
                        "Facebook (post)", True)
            posts = post_chiusure(r.get("data", []), "message", "created_time")
            return lambda c: gia_nel_post(c, posts)
        nuove = da_mandare("facebook", fb_letto)
        if nuove:
            manda_facebook(fb, testo_post(tutte, nuove, oggi), foto)
            segna("facebook", tutte)   # il post le contiene tutte
            print(f"Chiusure su Facebook: {', '.join(c['comune'] for c in nuove)}")
    except Exception as e:
        invio_fallito("facebook", e)

    try:
        if not fb:
            raise RuntimeError("manca FB_PAGE_TOKEN")
        if not ig:
            raise RuntimeError("la Pagina non ha un account Instagram collegato (o Facebook non ha risposto)")

        def ig_letto():
            r = riprova(lambda: facebook.chiama("GET", f"{ig}/media", fb, {"fields": "caption,timestamp", "limit": 50}),
                        "Instagram (post)", True)
            posts = post_chiusure(r.get("data", []), "caption", "timestamp")
            return lambda c: gia_nel_post(c, posts)
        nuove = da_mandare("instagram", ig_letto)
        if nuove:
            manda_instagram(fb, ig, testo_post(tutte, nuove, oggi, instagram=True), foto)
            segna("instagram", tutte)
            print(f"Chiusure su Instagram: {', '.join(c['comune'] for c in nuove)}")
    except Exception as e:
        invio_fallito("instagram", e)

    if a.stato:   # il ricordo: solo le chiusure ancora in corso
        for canale in ("telegram", "facebook", "instagram"):
            stato[canale] = {k: v for k, v in stato[canale].items() if k in chiavi}
        stato["incerti"] = sorted(incerti)
        os.makedirs(os.path.dirname(a.stato) or ".", exist_ok=True)
        with open(a.stato, "w", encoding="utf-8") as f:
            json.dump(stato, f, ensure_ascii=False, indent=1)
    for e in errori:
        print(f"AVVISO Chiusure: {e}", file=sys.stderr)
    if not errori:
        print("Chiusure: tutto uscito su Telegram, Facebook e Instagram")
    return 1 if errori else 0


if __name__ == "__main__":
    sys.exit(main())
