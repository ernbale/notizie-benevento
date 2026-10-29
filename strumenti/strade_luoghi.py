#!/usr/bin/env python3
"""Dove sono le strade chiuse → strade-luoghi.json (i tondi della mappa in cima a «Strade chiuse», una strada per tondo).

Voluto dal proprietario il 29 ott 2026: a mappa ingrandita le 6 voci di Benevento stavano tutte in un tondo al centro
della città, come se le chiusure fossero lì («zoomando la mappa i pallini si separano?» → «si fallo»). Le strade si
leggono nel titolo e nel «luogo» delle notizie con «traffico» (strade_nel_testo: «via Cocchia e via Cavour», «via Cupa
Ponticelli, Collevaccino e Pertini», «strada comunale Centofontane», «frazione Civitella»; mai statali e provinciali,
che sono lunghe chilometri) e si cercano una volta sola su OpenStreetMap (Nominatim: al massimo una richiesta al
secondo, col nome del sito; regole d'uso https://operations.osmfoundation.org/policies/nominatim/). Una strada vale solo
se OpenStreetMap la mette in quel Comune e a pochi chilometri dal suo centro; se no il tondo resta al centro del paese.
Quel che si è trovato (e non trovato) resta nel file pubblicato sul sito, che il giro dopo rilegge: così ogni strada
si chiede una volta (le non trovate si richiedono dopo una settimana). Lo esegue GitHub a ogni pubblicazione, prima di
pagine.py, che lo legge (segnaposti_strade); se non risponde, la mappa va come prima.

Uso:  python3 strumenti/strade_luoghi.py [--uscita strade-luoghi.json] [--al-massimo 20]
"""
import argparse
import datetime as dt
import json
import math
import os
import re
import sys
import time
import unicodedata
import urllib.parse
import urllib.request

QUI = os.path.dirname(os.path.abspath(__file__))
SITO = "https://notiziebenevento.it"
UA = "NotizieBenevento/1.0 (https://notiziebenevento.it)"
RIPROVA_DOPO = 7   # giorni: una strada non trovata si richiede dopo una settimana
RAGGIO_KM = {"Benevento": 9}   # quanto può stare lontana dal centro del Comune (Benevento è grande)
RAGGIO_KM_PAESE = 6

TIPI = (r"(?i:via|viale|piazza|piazzale|piazzetta|largo|corso|vico|vicolo|traversa|salita|rampa|contrada|c\.da|"
        r"località|frazione|rione|strada comunale|strada vicinale|ponte)")
LEGA = r"(?:d[ei]|del|dell[aoe']?|dei|degli|delle|de|d'|da|dal|dalla|al|alla|alle|ai|a|in|sul|sulla)"
# una parola del nome: con la maiuscola («Cocchia», «S.»), un numero romano («IV Novembre») o un giorno («24 Maggio»);
# solo spazi tra le parole, mai un a capo (il luogo e il titolo sono due righe)
PAROLA = r"(?:[A-ZÀ-Ý](?:\.|[\wÀ-ÿ'’-]*)|[IVXL]+|\d{1,2}(?=[ \t]+[A-ZÀ-Ý]))"
NOME = rf"(?:{LEGA}[ \t]+)?{PAROLA}(?:[ \t]+(?:{LEGA}[ \t]+)?{PAROLA})*"
STRADA = re.compile(rf"\b({TIPI})[ \t]+({NOME})")
# «via Cupa Ponticelli, Collevaccino e Pertini»: dopo una strada, altri nomi senza «via» davanti
SEGUITO = re.compile(rf"^(?:,[ \t]*|[ \t]+e[ \t]+)({NOME})(?=[ \t,:;.]|$)", re.M)


def _piano(s):
    return unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().lower().replace("’", "'").strip()


def strade_nel_testo(testo, comuni=()):
    """Le strade nominate nel testo, nell'ordine: ["via Cocchia", "via Cavour"]. Niente nomi di Comuni («via Roma,
    Benevento» non fa una «via Benevento») e niente doppioni."""
    vietati = {_piano(c) for c in comuni}
    out, visti = [], set()

    def metti(tipo, nome):
        nome = nome.strip(" .,'’")
        if not nome or _piano(nome) in vietati:
            return
        s = f"{tipo.lower()} {nome}"
        if _piano(s) not in visti:
            visti.add(_piano(s))
            out.append(s)
    for m in STRADA.finditer(str(testo or "")):
        tipo = "contrada" if m.group(1).lower() == "c.da" else m.group(1)
        metti(tipo, m.group(2))
        resto = testo[m.end():]
        while True:
            s = SEGUITO.match(resto)
            if not s or re.match(rf"(?:{TIPI})\b", s.group(1), re.I):
                break
            metti(tipo, s.group(1))
            resto = resto[s.end():]
    return out


def chiave(comune, strada):
    return f"{_piano(comune)}|{_piano(strada)}"


def _km(a, b):
    la1, lo1, la2, lo2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    h = math.sin((la2 - la1) / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2
    return 12742 * math.asin(math.sqrt(h))


def _chiedi(param):
    q = urllib.parse.urlencode({**param, "format": "jsonv2", "addressdetails": 1, "limit": 5, "countrycodes": "it"})
    req = urllib.request.Request("https://nominatim.openstreetmap.org/search?" + q,
                                 headers={"User-Agent": UA, "Accept-Language": "it"})
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.load(r)


UNITA = "zero uno due tre quattro cinque sei sette otto nove dieci undici dodici tredici quattordici quindici sedici " \
        "diciassette diciotto diciannove".split()


def _in_lettere(k):
    """1-39 in lettere, come li scrive OpenStreetMap («Piazza Quattro Novembre», «Via Ventiquattro Maggio»)."""
    if k < 20:
        return UNITA[k]
    dec, u = ("venti", "trenta")[k // 10 - 2], k % 10
    if u == 0:
        return dec
    return (dec[:-1] if u in (1, 8) else dec) + UNITA[u]   # ventuno, ventotto


def _romano(w):
    v = {"i": 1, "v": 5, "x": 10, "l": 50}
    if not re.fullmatch(r"[ivxl]+", w):
        return None
    n = 0
    for a, b in zip(w, w[1:] + " "):
        n += -v[a] if b != " " and v[b] > v[a] else v[a]
    return n


def _parole(s):
    """Le parole che contano di un nome, coi numeri in lettere: «IV Novembre», «4 Novembre» e «Quattro Novembre»
    danno le stesse."""
    out = []
    for w in re.split(r"[^a-z0-9]+", _piano(s)):
        if not w or re.fullmatch(LEGA, w):
            continue
        k = int(w) if w.isdigit() else _romano(w)
        out.append(_in_lettere(k) if k and 0 < k < 40 else w)
    return out


def cerca(strada, comune, centro, attesa=1.1):
    """(lat, lon) della strada in quel Comune, o None. Tre ricerche: per strada e città, libera, col solo nome (su
    OpenStreetMap «via Cavour» è «Via Camillo Benso Conte di Cavour», «via Cancelleria» la frazione Cancelleria). Vale
    solo un risultato che ha nel nome tutte le parole della strada, che OpenStreetMap mette nel Comune, vicino al suo
    centro, e che è una strada o un luogo (non la fermata dell'autobus «Cimitero»)."""
    raggio = RAGGIO_KM.get(comune, RAGGIO_KM_PAESE)
    nome = re.sub(rf"^{TIPI}[ \t]+", "", strada)
    voglio = set(_parole(nome))
    prove = [({"street": strada, "city": comune, "county": "Benevento", "country": "Italia"}, False),
             ({"q": f"{strada}, {comune}, provincia di Benevento"}, False),
             ({"q": f"{nome}, {comune}"}, False),
             # a Benevento tante «via X» stanno nella contrada X (via San Marco, contrada San Marco: il cimitero)
             ({"q": f"contrada {nome}, {comune}"}, True)]
    for p, solo_luoghi in prove:
        time.sleep(attesa)
        for r in _chiedi(p):
            ind = r.get("address") or {}
            dove = {_piano(str(ind.get(k) or "")) for k in ("city", "town", "village", "municipality", "hamlet")}
            punto = (float(r["lat"]), float(r["lon"]))
            cat, tipo = r.get("category") or r.get("class"), r.get("type")
            if cat == "highway" and not solo_luoghi:
                if tipo in ("bus_stop", "platform", "stop", "street_lamp", "crossing", "traffic_signals"):
                    continue
            elif cat != "place":
                continue
            if not voglio <= set(_parole(r.get("name") or "")):
                continue
            if _piano(comune) in dove and _km(punto, centro) <= raggio:
                return round(punto[0], 5), round(punto[1], 5)
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--uscita", default=os.path.join(os.path.dirname(QUI), "strade-luoghi.json"))
    ap.add_argument("--notizie", default=os.path.join(os.path.dirname(QUI), "notizie.json"))
    ap.add_argument("--al-massimo", type=int, default=20, help="strade nuove da chiedere a ogni giro")
    ap.add_argument("--tempo", type=int, default=100, help="secondi al massimo per le richieste, poi salva e smette")
    a = ap.parse_args()
    sys.path.insert(0, QUI)
    from pagine import comuni_di
    from chiusure import slug
    with open(os.path.join(QUI, "comuni_coordinate.json"), encoding="utf-8") as f:
        coord = json.load(f)
    luoghi = {}
    for fonte in (a.uscita, f"{SITO}/strade-luoghi.json?t={int(time.time())}"):   # il file locale, poi quello sul sito
        try:
            if fonte.startswith("http"):
                with urllib.request.urlopen(urllib.request.Request(fonte, headers={"User-Agent": UA}), timeout=30) as r:
                    vecchi = json.load(r).get("luoghi") or {}
            else:
                with open(fonte, encoding="utf-8") as f:
                    vecchi = json.load(f).get("luoghi") or {}
            luoghi = {**vecchi, **luoghi}
        except Exception:
            pass
    with open(a.notizie, encoding="utf-8") as f:
        notizie = json.load(f)["notizie"]
    oggi = dt.date.today().isoformat()
    soglia = (dt.date.today() - dt.timedelta(days=RIPROVA_DOPO)).isoformat()
    da_fare = []
    for n in notizie:
        if not n.get("traffico"):
            continue
        comuni = comuni_di(n.get("luogo"))
        for c in comuni[:1]:
            for s in strade_nel_testo(f"{n.get('luogo') or ''}\n{n.get('titolo') or ''}", comuni):
                v = luoghi.get(chiave(c, s))
                if v is None or ("no" in v and v["no"] < soglia):
                    if (c, s) not in da_fare:
                        da_fare.append((c, s))
    fatte = trovate = 0
    inizio = time.monotonic()
    for c, s in da_fare[:a.al_massimo]:
        if time.monotonic() - inizio > a.tempo:   # OpenStreetMap lento: il resto al giro dopo, quel che c'è si salva
            break
        k = coord[slug(c)]
        try:
            p = cerca(s, c, (k["lat"], k["lon"]))
        except Exception as e:   # OpenStreetMap non risponde: si riprova al giro dopo
            print(f"strade: {s}, {c}: {type(e).__name__}, riprovo dopo", file=sys.stderr)
            break
        fatte += 1
        luoghi[chiave(c, s)] = {"lat": p[0], "lon": p[1]} if p else {"no": oggi}
        trovate += bool(p)
    tmp = a.uscita + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump({"aggiornato": dt.datetime.now(dt.timezone.utc).isoformat(timespec="minutes"),
                   "fonte": "OpenStreetMap (Nominatim), © OpenStreetMap contributors, ODbL", "luoghi": luoghi},
                  f, ensure_ascii=False, separators=(",", ":"))
    os.replace(tmp, a.uscita)
    print(f"strade: {len(luoghi)} conosciute, {fatte} chieste ora ({trovate} trovate), "
          f"{max(0, len(da_fare) - fatte)} al prossimo giro")


if __name__ == "__main__":
    main()
