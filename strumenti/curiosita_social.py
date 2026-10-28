#!/usr/bin/env python3
"""La curiosità del Sannio del giorno (curiosita.json) su Telegram, Facebook e Instagram, alle 12.

Voluta dal proprietario il 24 ott 2026: «un post al giorno da pubblicare ogni giorno alle 12: una curiosità, una
storia, un fatto del passato, un detto, una superstizione, una leggenda… di Benevento», «cominciamo oggi alle 12 con
Instagram, Facebook e Telegram», «nessun fallimento, nessuna storia scritta male, perfezione».

Lo esegue GitHub a ogni pubblicazione del sito, dopo che il sito è online (la foto e la pagina della curiosità devono
già esserci); alle 12 la pubblicazione la fa partire il Pi di casa. Esce la curiosità con la data di oggi, dalle 12
alle 22 (se fino alle 22 non è uscita, non esce più: il passo di GitHub diventa rosso e arriva la mail).
- Telegram: la foto della curiosità (img/ig/curiosita-<slug>.jpg, la fa pagine.py) col racconto e il link alla pagina.
- Facebook: la stessa foto col racconto, le fonti e il link alla pagina (facebook.foto_con_testo: mai un doppio post).
- Instagram: la stessa foto con lo stesso testo e gli hashtag.
Le curiosità non contano nei limiti delle notizie (facebook.py conta solo i post con una notizia, instagram.py salta
quelli con #CuriositàDelSannio).

Niente doppioni: cosa è già uscito lo ricorda un file (--stato, che GitHub conserva come quello delle chiusure) e lo si
ricontrolla sui canali stessi (il link alla pagina della curiosità nell'anteprima pubblica di Telegram, il titolo nei
post di Facebook e di Instagram). Se il file non c'è e un canale non si legge, su quel canale non si pubblica (meglio
dopo che due volte) e il programma finisce con errore. Ogni chiamata si riprova 3 volte; se un canale non va gli altri
escono lo stesso e il programma finisce con errore (la pubblicazione dopo riprova).

Uso:  python3 strumenti/curiosita_social.py --stato FILE        (con TELEGRAM_TOKEN e FB_PAGE_TOKEN)
      python3 strumenti/curiosita_social.py --prova [--giorno 2026-10-24]   (i testi che manderebbe, senza chiavi)
"""
import argparse
import datetime as dt
import html
import json
import os
import re
import sys
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from facebook import PAGINA, SITO, fuso   # noqa: E402
import facebook   # noqa: E402
import telegram   # noqa: E402

DALLE, ALLE = 12, 22
HASHTAG = "#CuriositàDelSannio"   # in ogni post di Instagram: così instagram.py non la conta tra le notizie
CANALI = ("telegram", "facebook", "instagram")
GIORNI_STATO = 30
MAX_DIDASCALIA_TG = 1000   # Telegram: 1024 caratteri al massimo per il testo di una foto
MAX_DIDASCALIA_IG = 2200

riprova = facebook.riprova
online = facebook.online


def pagina(c):
    return f"{SITO}/curiosita/{c['slug']}/"


def foto(c):
    return f"{SITO}/img/ig/curiosita-{c['slug']}.jpg"


def paragrafi(c):
    return [x.strip() for x in c["testo"].split("\n\n") if x.strip()]


def credito(c):
    """«Foto: autore, licenza (Wikimedia Commons).», la nota della foto fatta con l'IA o niente se la curiosità non ha
    foto."""
    if (c.get("immagine") or {}).get("ia"):
        return "Immagine illustrativa creata con l'intelligenza artificiale."
    cr = ((c.get("immagine") or {}).get("credito") or "").strip()
    return f"{cr.replace(' · ', ', ')} (Wikimedia Commons)." if cr else ""


def fonti(c):
    return " · ".join(f["titolo"].split(" (")[0] for f in c.get("fonti") or [])


def hashtag_luogo(c):
    """#Pietraroja, #GuardiaSanframondi…; niente per Benevento (c'è già)."""
    parole = re.findall(r"[A-Za-zÀ-ÿ]+", (c.get("luogo") or "").split(" e ")[0])
    h = "".join(p[:1].upper() + p[1:] for p in parole)
    return "" if not h or h == "Benevento" else f" #{h}"


def testo_facebook(c):
    t = f"{c['titolo']}\n\n{c['testo'].strip()}\n\nFonti: {fonti(c)}."
    if credito(c):
        t += f"\n{credito(c)}"
    return t + f"\n\nLa storia con le fonti e tutte le curiosità del Sannio: {pagina(c)}"


def testo_instagram(c):
    t = f"{c['titolo']}\n\n{c['testo'].strip()}\n\nFonti: {fonti(c)}."
    if credito(c):
        t += f"\n{credito(c)}"
    return t + (f"\n\nUna curiosità del Sannio ogni giorno alle 12, tutte su notiziebenevento.it (link nella bio)."
                f"\n\n{HASHTAG} #Benevento #Sannio{hashtag_luogo(c)}")


def testo_telegram(c):
    """HTML per la didascalia della foto: titolo, racconto (se non ci sta, i primi paragrafi) e il link."""
    esc = lambda s: html.escape(s, quote=False)
    link = f'<a href="{pagina(c)}">La storia con le fonti</a>'
    par = paragrafi(c)
    for n in range(len(par), 0, -1):
        corpo = "\n\n".join(esc(p) for p in par[:n]) + ("" if n == len(par) else "\n\n…")
        t = f"<b>{esc(c['titolo'])}</b>\n\n{corpo}\n\n{link}"
        if len(re.sub(r"<[^>]+>", "", html.unescape(t))) <= MAX_DIDASCALIA_TG:
            return t
    return f"<b>{esc(c['titolo'])}</b>\n\n{link}"


# ---------------------------------------------------------------- cosa è già uscito, letto dai canali

def su_telegram(c):
    req = urllib.request.Request(telegram.ANTEPRIMA, headers={"User-Agent": "Mozilla/5.0 (notiziebenevento.it)"})
    with urllib.request.urlopen(req, timeout=30) as r:
        pagina_ = r.read().decode("utf-8", "replace")
    if "tgme_widget_message" not in pagina_:
        raise RuntimeError("l'anteprima del canale non ha messaggi leggibili")
    return f"notiziebenevento.it/curiosita/{c['slug']}/" in pagina_


def su_facebook(token, c):
    r = facebook.chiama("GET", "me/posts", token, {"fields": "message,created_time", "limit": 50})
    return any(c["titolo"] in (p.get("message") or "") for p in r.get("data", []))


def su_instagram(token, ig, c):
    r = facebook.chiama("GET", f"{ig}/media", token, {"fields": "caption,timestamp", "limit": 50})
    return any(c["titolo"] in (p.get("caption") or "") for p in r.get("data", []))


# ---------------------------------------------------------------- l'invio

def manda_telegram(token, c):
    if online(foto(c)):
        riprova(lambda: telegram.chiama(token, "sendPhoto", {"chat_id": telegram.CANALE, "photo": foto(c),
                                                             "caption": testo_telegram(c), "parse_mode": "HTML"}),
                "Telegram (foto)")
    else:   # senza foto online: il testo con l'anteprima della pagina
        riprova(lambda: telegram.chiama(token, "sendMessage", {"chat_id": telegram.CANALE, "text": testo_telegram(c),
                                                               "parse_mode": "HTML",
                                                               "link_preview_options": {"url": pagina(c),
                                                                                        "prefer_large_media": True}}),
                "Telegram")


def manda_instagram(token, ig, c):
    if not online(foto(c)):
        raise RuntimeError(f"Instagram: la foto non è online ({foto(c)}): riprovo alla prossima pubblicazione")
    import instagram
    cont = riprova(lambda: facebook.chiama("POST", f"{ig}/media", token, {"image_url": foto(c),
                                                                          "caption": testo_instagram(c)})["id"],
                   "Instagram")
    instagram.aspetta(cont, token)
    riprova(lambda: facebook.chiama("POST", f"{ig}/media_publish", token, {"creation_id": cont}), "Instagram (pubblica)")


def di_oggi(sito, giorno):
    with open(os.path.join(sito, "curiosita.json"), encoding="utf-8") as f:
        tutte = json.load(f).get("curiosita") or []
    oggi = [c for c in tutte if c.get("data") == giorno]
    if len(oggi) > 1:
        raise RuntimeError(f"curiosita.json: {len(oggi)} curiosità con la data {giorno}, ne deve uscire una")
    return oggi[0] if oggi else None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sito", default=os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    ap.add_argument("--stato", help="il file che ricorda cosa è già uscito (lo conserva GitHub)")
    ap.add_argument("--prova", action="store_true")
    ap.add_argument("--giorno", help="solo con --prova: la curiosità di quel giorno (AAAA-MM-GG)")
    a = ap.parse_args()
    adesso = dt.datetime.now(fuso())
    giorno = a.giorno if a.prova and a.giorno else adesso.date().isoformat()
    c = di_oggi(a.sito, giorno)
    if not c:
        print(f"Curiosità: nessuna per il {giorno}" + ("" if a.prova else " (la scorta è finita? vedi curiosita.json)"))
        return 0 if a.prova else (1 if adesso.hour >= DALLE else 0)

    if a.prova:
        for nome, t in (("Telegram", re.sub(r"<[^>]+>", "", html.unescape(testo_telegram(c)))),
                        ("Facebook", testo_facebook(c)), ("Instagram", testo_instagram(c))):
            print(f"===== {nome} ({len(t)} caratteri)\n{t}\n")
        print(f"foto: {foto(c)} ({'online' if online(foto(c)) else 'NON ancora online'})\npagina: {pagina(c)}")
        return 0

    stato, stato_perso = {}, True
    if a.stato:
        try:
            with open(a.stato, encoding="utf-8") as f:
                stato, stato_perso = json.load(f), False
        except (OSError, ValueError):
            pass
    for canale in CANALI:
        stato.setdefault(canale, {})
    fatto = {k: c["slug"] in stato[k] for k in CANALI}
    if all(fatto.values()):
        print(f"Curiosità: «{c['titolo']}» è già uscita su Telegram, Facebook e Instagram")
        return 0
    if adesso.hour < DALLE:
        print(f"Curiosità: «{c['titolo']}» esce alle {DALLE}")
        return 0
    if adesso.hour >= ALLE:
        print(f"AVVISO Curiosità: «{c['titolo']}» non è uscita su {', '.join(k for k in CANALI if not fatto[k])} "
              f"entro le {ALLE}: oggi non esce più", file=sys.stderr)
        return 1

    incerti = set(stato.get("incerti") or []) | (set(CANALI) if stato_perso else set())
    errori = []

    def segna(canale):
        stato[canale][c["slug"]] = adesso.isoformat(timespec="seconds")

    def pubblica(canale, gia_uscita, manda):
        """Ricontrolla sul canale e, se non c'è, manda; ogni errore resta di quel canale."""
        if c["slug"] in stato[canale]:
            return
        try:
            try:
                letta = riprova(gia_uscita, f"{canale} (rilettura)", True)
            except Exception as e:
                if canale in incerti:
                    raise RuntimeError(f"non so se è già uscita (ricordo incerto e canale illeggibile: {e}), non mando:"
                                       " si riprova alla prossima pubblicazione") from None
                print(f"  {canale}: non leggo il canale ({e}), mi fido del ricordo")
                letta = False
            incerti.discard(canale)
            if letta:
                print(f"Curiosità: su {canale} c'era già")
            else:
                manda()
                print(f"Curiosità su {canale}: «{c['titolo']}»")
            segna(canale)
        except Exception as e:
            if "forse è uscito" in str(e):
                incerti.add(canale)
            errori.append(f"{canale}: {e}")

    tg = os.environ.get("TELEGRAM_TOKEN", "").strip()
    fb = os.environ.get("FB_PAGE_TOKEN", "").strip()
    if tg:
        pubblica("telegram", lambda: su_telegram(c), lambda: manda_telegram(tg, c))
    else:
        errori.append("telegram: manca TELEGRAM_TOKEN")
    ig = None
    if fb:
        try:
            pag = riprova(lambda: facebook.chiama("GET", "me", fb, {"fields": "name,instagram_business_account{id}"}),
                          "Facebook", True)
            if pag.get("name") != PAGINA:
                raise RuntimeError(f"la chiave non è della Pagina «{PAGINA}»: non pubblico niente")
            ig = (pag.get("instagram_business_account") or {}).get("id")
            pubblica("facebook", lambda: su_facebook(fb, c),
                     lambda: facebook.foto_con_testo(fb, foto(c), testo_facebook(c), pagina(c)))
            if ig:
                pubblica("instagram", lambda: su_instagram(fb, ig, c), lambda: manda_instagram(fb, ig, c))
            else:
                errori.append("instagram: la Pagina non ha un account Instagram collegato")
        except Exception as e:
            errori.append(f"facebook/instagram: {e}")
    else:
        errori.append("facebook e instagram: manca FB_PAGE_TOKEN")

    if a.stato:   # il ricordo: le curiosità degli ultimi GIORNI_STATO giorni
        limite = (adesso - dt.timedelta(days=GIORNI_STATO)).isoformat()
        for canale in CANALI:
            stato[canale] = {k: v for k, v in stato[canale].items() if v >= limite}
        stato["incerti"] = sorted(incerti)
        os.makedirs(os.path.dirname(a.stato) or ".", exist_ok=True)
        with open(a.stato, "w", encoding="utf-8") as f:
            json.dump(stato, f, ensure_ascii=False, indent=1)
    for e in errori:
        print(f"AVVISO Curiosità: {e}", file=sys.stderr)
    if not errori:
        print(f"Curiosità: «{c['titolo']}» uscita su Telegram, Facebook e Instagram")
    return 1 if errori else 0


if __name__ == "__main__":
    sys.exit(main())
