#!/usr/bin/env python3
"""La guardia medica (continuità assistenziale) nel Sannio → strumenti/guardia_medica.json, per la pagina
/guardia-medica/ e il riquadro nelle pagine dei Comuni.

Voluta dal proprietario il 29 ott 2026 («b ok metti quelli disponibili ordine per distanza»). Le postazioni sono
quelle del sito dell'ASL Benevento (Servizi → Guardia Medica, una scheda ciascuna: 22 il 29 ott 2026), con
l'indirizzo (il campo «Luogo»), il Comune, i telefoni e gli orari. L'ASL non scrive quali paesi fanno capo a ogni
postazione: la pagina le mette tutte in ordine di distanza dal paese scelto, in linea d'aria, e lo dice. Le schede a
volte non tornano col loro titolo (Benevento: titolo «Via Minghetti», indirizzo «Via XXIV Maggio, 24»): vale
«Luogo», che è l'indirizzo. Il punto sulla mappa: la via su OpenStreetMap (strade_luoghi.cerca), se no il centro del
paese.

Il sito dell'ASL ha il certificato incompleto (manca l'intermedio di Actalis): lo si scarica una volta, come in
fonti_casa.py.

Uso:  python3 strumenti/guardia_medica.py              rilegge l'ASL e riscrive il file (sul Mac, a mano)
      python3 strumenti/guardia_medica.py --controlla  sul server (fino al 30 ott 2026 il Pi), alle 7:25: se l'ASL ha cambiato le postazioni
                                                       avvisa il proprietario (una volta per cambiamento); il file
                                                       sul sito lo aggiorno io dopo averlo guardato
"""
import argparse
import datetime as dt
import difflib
import hashlib
import html
import json
import os
import re
import ssl
import sys
import time
import urllib.request

QUI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, QUI)

ASL = "https://www.aslbenevento.it"
ELENCO = ASL + "/servizi-funzionali/lista-servizi-funzionali/guardia-medica"
INTERMEDIO = "http://cacert.actalis.it/certs/actalis-authovg3"   # dall'«Authority Information Access» del sito
UA = {"User-Agent": "NotizieBenevento/1.0 (https://notiziebenevento.it)"}
FILE = os.path.join(QUI, "guardia_medica.json")
PUBBLICATO = "https://notiziebenevento.it/strumenti/guardia_medica.json"   # dal 30 ott 2026 il sito è sul server, non su GitHub
CARTELLA_PI = os.path.expanduser("~/nb-fonti")
# come scrive i Comuni l'ASL → come si chiamano (meteo.COMUNI_BN)
NOMI = {"pietralcina": "Pietrelcina", "castelvetere in valfortore": "Castelvetere in Val Fortore",
        "sant'agata dei goti": "Sant'Agata de' Goti"}


def contesto():
    pem = os.path.join(CARTELLA_PI if os.path.isdir(CARTELLA_PI) else os.path.expanduser("~/.cache"),
                       "actalis-ov-g3.pem")
    if not os.path.exists(pem):
        os.makedirs(os.path.dirname(pem), exist_ok=True)
        with urllib.request.urlopen(INTERMEDIO, timeout=30) as r:
            der = r.read()
        with open(pem, "w") as f:
            f.write(ssl.DER_cert_to_PEM_cert(der))
    ctx = ssl.create_default_context()
    ctx.load_verify_locations(cafile=pem)
    return ctx


def scarica(url, ctx):
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=40, context=ctx) as r:
        return r.read().decode("utf-8", "replace")


def righe(pagina):
    t = re.sub(r"<script.*?</script>|<style.*?</style>", "", pagina, flags=re.S)
    t = html.unescape(re.sub(r"<[^>]+>", "\n", t)).replace("’", "'")
    return [r for r in (" ".join(x.split()) for x in t.split("\n")) if r]


def comune_vero(nome):
    from meteo import COMUNI_BN
    n = re.sub(r"\s*\(BN\)\s*$", "", nome).strip()
    piano = {c.lower().replace("’", "'"): c for c in COMUNI_BN}
    k = n.lower()
    if k in NOMI:
        return NOMI[k]
    if k in piano:
        return piano[k]
    vicino = difflib.get_close_matches(k, list(piano), n=1, cutoff=0.85)
    if vicino:
        return piano[vicino[0]]
    raise ValueError(f"Comune sconosciuto nella scheda dell'ASL: {nome!r}")


def bella(via):
    """«Viale dei pini» → «Viale dei Pini»; via il «(Distretto Sanitario …)» in fondo."""
    via = re.sub(r"\s*\(Distretto[^)]*\)\s*$", "", via).strip()
    return " ".join(w if re.fullmatch(r"(di|del|della|delle|dei|degli|de|da|e)", w) or not w[:1].islower()
                    else w[:1].upper() + w[1:] for w in via.split(" "))


def telefono(t):
    return re.sub(r"\D", "", t)


def scheda(url, pagina):
    r = righe(pagina)
    def dopo(et):   # l'ultima volta che c'è: la prima è spesso l'indice della scheda
        i = max([k for k, x in enumerate(r) if x == et], default=-1)
        return r[i + 1] if 0 <= i < len(r) - 1 else ""
    titoli = [x for x in r if re.match(r"(Guardia Medica Distretto|Presidio di Continuit)", x)]
    titolo = titoli[1] if len(titoli) > 1 else (titoli[0] if titoli else "")
    distretto = (re.search(r"Distretto di (.+?) \(", titolo) or [None, ""])[1]
    tel = []
    for i, x in enumerate(r):
        if x == "Numero" and i + 1 < len(r) and telefono(r[i + 1]) and telefono(r[i + 1]) not in tel:
            tel.append(telefono(r[i + 1]))
    orari = dopo("Orari di accesso al pubblico")
    if orari == "Servizi collegati":
        orari = ""
    comune = comune_vero(dopo("Comune"))
    return {"id": url.rstrip("/").rsplit("/", 1)[1], "titolo": titolo, "distretto": distretto,
            "indirizzo": bella(dopo("Nome luogo")), "cap": dopo("CAP"), "comune": comune, "telefoni": tel,
            "orari": orari, "fonte": url}


def leggi_asl():
    ctx = contesto()
    elenco = scarica(ELENCO, ctx)
    link = sorted(set(re.findall(r'href="(/servizio-strutturale/[^"]+)"', elenco)))
    if len(link) < 15:
        raise RuntimeError(f"l'elenco dell'ASL ha solo {len(link)} postazioni: pagina cambiata?")
    out = []
    for l in link:
        out.append(scheda(ASL + l, scarica(ASL + l, ctx)))
        time.sleep(1)
    return sorted(out, key=lambda p: (p["comune"], p["indirizzo"]))


def impronta(postazioni):
    campi = [{k: p[k] for k in ("id", "indirizzo", "comune", "telefoni", "orari")} for p in postazioni]
    return hashlib.sha256(json.dumps(campi, ensure_ascii=False, sort_keys=True).encode()).hexdigest()[:16]


def sulla_mappa(postazioni):
    from chiusure import slug          # sul Mac: sul Pi (--controlla) la mappa non serve
    from strade_luoghi import cerca
    with open(os.path.join(QUI, "comuni_coordinate.json"), encoding="utf-8") as f:
        coord = json.load(f)
    for p in postazioni:
        c = coord[slug(p["comune"])]
        via = re.sub(r"\s+\d+\S*$", "", p["indirizzo"].split(",")[0]).strip()
        # «Via Maielli/Beltiglio»: la via, se no la frazione dopo la barra
        prove = [via.split("/")[0].strip()] + ([f"frazione {via.split('/', 1)[1].strip()}"] if "/" in via else [])
        punto = None
        for v in prove:
            try:
                punto = cerca(v, p["comune"], (c["lat"], c["lon"])) if v else None
            except Exception as e:   # OpenStreetMap non risponde: centro del paese
                print(f"guardia medica: {v}, {p['comune']}: {type(e).__name__}", file=sys.stderr)
            if punto:
                break
        p["lat"], p["lon"] = punto or (c["lat"], c["lon"])
        p["punto"] = "via" if punto else "centro del paese"


def controlla():
    """Sul Pi: l'ASL ha cambiato le postazioni rispetto al file sul sito? Avviso una volta per cambiamento."""
    ora = leggi_asl()
    with urllib.request.urlopen(urllib.request.Request(PUBBLICATO + f"?t={int(time.time())}", headers=UA),
                                timeout=30) as r:
        sito = json.load(r)
    nuova = impronta(ora)
    if nuova == sito.get("impronta"):
        print(f"guardia medica: {len(ora)} postazioni, come sul sito")
        return
    stato_p = os.path.join(CARTELLA_PI, "guardia-avvisata.json")
    try:
        with open(stato_p, encoding="utf-8") as f:
            visti = json.load(f)
    except (OSError, ValueError):
        visti = {}
    vecchie = {p["id"]: p for p in sito.get("postazioni") or []}
    nuove = {p["id"]: p for p in ora}
    cambi = ([f"• nuova: {p['titolo']}" for i, p in nuove.items() if i not in vecchie]
             + [f"• tolta: {p['titolo']}" for i, p in vecchie.items() if i not in nuove]
             + [f"• cambiata: {p['titolo']}" for i, p in nuove.items() if i in vecchie
                and impronta([p]) != impronta([vecchie[i]])])
    print("guardia medica: l'ASL ha cambiato qualcosa\n" + "\n".join(cambi))
    if nuova in visti:
        return
    from sentinella import manda_a_casa
    esiti = manda_a_casa("ℹ️ Notizie Benevento, guardia medica: l'ASL Benevento ha cambiato le postazioni sul suo sito.\n"
                         + "\n".join(cambi[:12]) + "\nLa pagina del sito ha ancora quelle di prima: da aggiornare "
                         "(python3 strumenti/guardia_medica.py sul Mac).", "Notizie Benevento: guardia medica da aggiornare")
    print("guardia medica: avviso", ", ".join(esiti))
    if any("mandat" in x and "NON" not in x for x in esiti):
        visti[nuova] = dt.datetime.now(dt.timezone.utc).isoformat(timespec="minutes")
        with open(stato_p, "w", encoding="utf-8") as f:
            json.dump(visti, f)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--controlla", action="store_true")
    a = ap.parse_args()
    if a.controlla:
        controlla()
        return
    post = leggi_asl()
    sulla_mappa(post)
    dati = {"aggiornato": dt.datetime.now(dt.timezone.utc).isoformat(timespec="minutes"), "fonte": ELENCO,
            "impronta": impronta(post), "postazioni": post}
    with open(FILE, "w", encoding="utf-8") as f:
        json.dump(dati, f, ensure_ascii=False, indent=1)
        f.write("\n")
    print(f"guardia medica: {len(post)} postazioni ({sum(p['punto'] == 'via' for p in post)} sulla via, "
          f"le altre al centro del paese)")


if __name__ == "__main__":
    main()
