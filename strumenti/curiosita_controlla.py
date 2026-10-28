#!/usr/bin/env python3
"""Controlla curiosita.json (le regole sono in CURIOSITA.md) e dice per quanti giorni basta la scorta.

Va passato prima di ogni commit che tocca le curiosità (lo fa anche la routine che le rifornisce). Controlla: campi,
slug e date unici, date di seguito senza buchi, categoria, lunghezze (anche dei testi per Telegram e Instagram), la
domanda finale, le fonti, la foto (file presente, JPEG, lato lungo al massimo 1200, credito, pagina di Commons e
«mostra»: cosa si vede, che deve essere il protagonista della storia; guardarla resta al secondo controllo) e,
per «accadde oggi», che giorno e mese del titolo siano quelli della data. Esce con errore se qualcosa non va.

Uso:  python3 strumenti/curiosita_controlla.py [--sito .] [--scorta-minima 14]
"""
import argparse
import datetime as dt
import html
import json
import os
import re
import sys

QUI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, QUI)
CATEGORIE = {"leggenda", "storia", "detto", "superstizione", "tradizione", "cibo", "paese", "accadde oggi"}
MESI = ["gennaio", "febbraio", "marzo", "aprile", "maggio", "giugno", "luglio", "agosto", "settembre", "ottobre",
        "novembre", "dicembre"]
EMOJI = re.compile("[\U0001F300-\U0001FAFF☀-➿]")


def controlla(sito):
    """(errori, curiosità)"""
    import curiosita_social as C
    err = []
    with open(os.path.join(sito, "curiosita.json"), encoding="utf-8") as f:
        tutte = json.load(f).get("curiosita")
    if not isinstance(tutte, list) or not tutte:
        return ["curiosita.json: manca l'elenco «curiosita»"], []
    slugs, date = set(), []
    for i, c in enumerate(tutte, 1):
        nome = f"{i}. {c.get('slug', '?')}"
        for k in ("slug", "data", "categoria", "luogo", "titolo", "testo", "fonti"):
            if not c.get(k):
                err.append(f"{nome}: manca «{k}»")
        if err and err[-1].startswith(nome):
            continue
        if not re.fullmatch(r"[a-z0-9]+(-[a-z0-9]+)*", c["slug"]):
            err.append(f"{nome}: slug non valido (solo minuscole, cifre e trattini)")
        if c["slug"] in slugs:
            err.append(f"{nome}: slug ripetuto")
        slugs.add(c["slug"])
        try:
            d = dt.date.fromisoformat(c["data"])
            date.append(d)
        except ValueError:
            err.append(f"{nome}: data non valida ({c['data']})")
            continue
        if c["categoria"] not in CATEGORIE:
            err.append(f"{nome}: categoria «{c['categoria']}» non prevista ({', '.join(sorted(CATEGORIE))})")
        if len(c["titolo"]) > 70:
            err.append(f"{nome}: titolo di {len(c['titolo'])} caratteri (al massimo 70)")
        par = [p for p in c["testo"].split("\n\n") if p.strip()]
        corpo = "\n\n".join(par[:-1])
        if not 450 <= len(corpo) <= 950:
            err.append(f"{nome}: racconto di {len(corpo)} caratteri (500-900, domanda finale esclusa)")
        if len(par) < 3:
            err.append(f"{nome}: servono almeno 2 paragrafi e la domanda finale, separati da una riga vuota")
        if not par[-1].strip().endswith("?") or len(par[-1]) > 140:
            err.append(f"{nome}: l'ultima riga deve essere una domanda breve per i commenti")
        if c["testo"].count("!") > 1 or EMOJI.search(c["titolo"] + c["testo"]):
            err.append(f"{nome}: troppi punti esclamativi o emoji")
        for f in c["fonti"]:
            if not f.get("titolo") or not re.match(r"^https://", str(f.get("url") or "")):
                err.append(f"{nome}: fonte senza titolo o senza indirizzo https ({f})")
        if c["categoria"] == "accadde oggi":
            m = re.search(r"(\d{1,2})\s+(" + "|".join(MESI) + r")", c["titolo"], re.I)
            if not m or (int(m.group(1)), MESI.index(m.group(2).lower()) + 1) != (d.day, d.month):
                err.append(f"{nome}: «accadde oggi» ma giorno e mese del titolo non sono quelli della data {c['data']}")
        im = c.get("immagine")
        if im and im.get("ia"):
            # la foto fatta con l'IA (CURIOSITA.md, «La foto»): la fa strumenti/foto_ia.py alla pubblicazione
            if im.get("file") != f"/img/curiosita/{c['slug']}.jpg":
                err.append(f"{nome}: la foto dell'IA si chiama /img/curiosita/{c['slug']}.jpg")
            if not 60 <= len(str(im.get("scena") or "").strip()) <= 700:
                err.append(f"{nome}: la foto dell'IA vuole «scena», da 60 a 700 caratteri (CURIOSITA.md)")
            if not str(im.get("mostra") or "").strip():
                err.append(f"{nome}: la foto vuole «mostra», cosa si vede: il protagonista della storia (CURIOSITA.md)")
        elif im:
            p = os.path.join(sito, str(im.get("file", "")).lstrip("/"))
            if not str(im.get("file", "")).startswith("/img/curiosita/") or not os.path.exists(p):
                err.append(f"{nome}: la foto {im.get('file')} non c'è in img/curiosita/")
            else:
                try:
                    from PIL import Image
                    with Image.open(p) as x:
                        if x.format != "JPEG" or max(x.size) > 1200:
                            err.append(f"{nome}: la foto deve essere JPEG con il lato lungo al massimo 1200 ({x.format} {x.size})")
                except ImportError:
                    pass
            if not im.get("credito") or not str(im.get("pagina", "")).startswith("https://commons.wikimedia.org/"):
                err.append(f"{nome}: la foto vuole «credito» e la «pagina» di Wikimedia Commons")
            if not str(im.get("mostra") or "").strip():
                err.append(f"{nome}: la foto vuole «mostra», cosa si vede: il protagonista della storia (CURIOSITA.md)")
        tg = re.sub(r"<[^>]+>", "", html.unescape(C.testo_telegram(c)))
        if "…" in tg:
            err.append(f"{nome}: su Telegram il racconto non ci sta intero ({len(c['testo'])} caratteri): accorciarlo")
        if len(C.testo_instagram(c)) > C.MAX_DIDASCALIA_IG:
            err.append(f"{nome}: il testo per Instagram supera {C.MAX_DIDASCALIA_IG} caratteri")
    if len(set(date)) != len(date):
        err.append("due curiosità con la stessa data")
    elif date:
        ordinate = sorted(date)
        buchi = [str(a + dt.timedelta(days=1)) for a, b in zip(ordinate, ordinate[1:]) if (b - a).days != 1]
        if buchi:
            err.append(f"date con buchi: manca la curiosità del {', '.join(buchi)}")
    return err, tutte


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sito", default=os.path.dirname(QUI))
    ap.add_argument("--scorta-minima", type=int, default=14)
    a = ap.parse_args()
    err, tutte = controlla(a.sito)
    oggi = dt.date.today()
    ultima = max((c["data"] for c in tutte if c.get("data")), default=None)
    giorni = (dt.date.fromisoformat(ultima) - oggi).days if ultima else -1
    print(f"curiosità: {len(tutte)} in tutto, l'ultima in programma è del {ultima}: la scorta basta per {giorni} giorni"
          + (f" (sotto i {a.scorta_minima}: va rifornita)" if giorni < a.scorta_minima else ""))
    for e in err:
        print(f"ERRORE: {e}")
    if not err:
        print("curiosita.json: tutto a posto")
    return 1 if err else 0


if __name__ == "__main__":
    sys.exit(main())
