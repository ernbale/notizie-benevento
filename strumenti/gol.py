#!/usr/bin/env python3
"""Le partite del Benevento in diretta su Telegram, Facebook e Instagram: ogni gol, la fine del primo tempo e la fine
della partita, ognuno con la sua immagine.

Voluto dal proprietario (24-25 ott 2026): «cerchiamo di attirare altri e ogni gol istantaneamente telegram instagram
e facebook», «fai i gol, fine primo tempo con quello che è successo e fine partita con riassunto finale».

Gira su GitHub (.github/workflows/gol.yml) per tutta la partita: lo fa partire il Pi di casa 20 minuti prima del calcio
d'inizio (sentinella/gol_via.py). Legge la diretta di ESPN (la stessa fonte della pagina calcio/, gratis e senza
chiave) ogni 15 secondi e manda:
- ogni gol, nostro o subito: «⚽ GOL DEL BENEVENTO!» o «⚽ Gol del Catanzaro», il minuto, chi ha segnato, il risultato;
- un gol tolto dal VAR (il risultato ufficiale torna indietro): «❌ Gol annullato» col risultato giusto;
- la fine del primo tempo: risultato, gol, espulsi, ammoniti, possesso e tiri;
- la fine della partita: risultato, il racconto dei gol, espulsi, possesso e tiri, i punti in classifica, la prossima.
Telegram con il suono, Facebook e Instagram con l'immagine (1080×1350, come quelle delle notizie), che si carica nel ramo
gol-immagini del repository: così è online subito (raw.githubusercontent.com), senza aspettare la pubblicazione del sito.

Un gol si manda quando il risultato ufficiale e l'azione del gol sono d'accordo; se il risultato cambia e l'azione non
arriva entro un minuto, il gol esce senza il nome di chi ha segnato. Un risultato che torna indietro per mezzo minuto è
un gol annullato.

Niente doppioni: cosa è già uscito, canale per canale, lo ricorda un file (--stato, che GitHub conserva tra un lavoro e
l'altro); se il file non c'è (il lavoro ripartito da zero) lo si ricostruisce dai canali stessi: l'anteprima pubblica di
Telegram, i post della Pagina e di Instagram delle ultime ore, riconosciuti dal segno in testa e dal risultato.
Niente fallimenti: ogni invio si riprova 3 volte (facebook.riprova, che non riprova alla cieca un invio forse riuscito);
se un canale non va gli altri escono lo stesso e il programma finisce con errore (lavoro rosso, mail al proprietario,
e il Pi lo rilancia).

Uso:  python3 strumenti/gol.py --stato FILE [--partita ID]          (con TELEGRAM_TOKEN, FB_PAGE_TOKEN, GH_TOKEN)
      python3 strumenti/gol.py --prova CARTELLA [--partita ID]        (la diretta vera, ma scrive solo nella cartella)
      python3 strumenti/gol.py --rigioca SUMMARY.json --prova CARTELLA (una partita finita, minuto per minuto)
      python3 strumenti/gol.py --registrazione DIR --partita ID --prova CARTELLA   (le registrazioni del Pi)
      --squadra ID: per le prove con un'altra squadra al posto del Benevento.
"""
import argparse
import base64
import datetime as dt
import glob
import gzip
import html
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

QUI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, QUI)
import facebook   # noqa: E402
import telegram   # noqa: E402
from calcio import NOMI   # noqa: E402
from facebook import PAGINA, SITO, fuso   # noqa: E402

ESPN = "https://site.api.espn.com/apis/site/v2/sports/soccer/ita.2"
BENEVENTO = "4059"
REPO = "ernbale/notizie-benevento"
RAMO = "gol-immagini"
UA = "notiziebenevento.it"   # come calcio.py: ESPN rifiuta (403) un nome con l'indirizzo tra parentesi
PAGINA_CALCIO = f"{SITO}/calcio/"
OGNI = 15                 # secondi tra una lettura e l'altra durante la partita
OGNI_PRIMA = 60           # prima del calcio d'inizio
ATTESA_AZIONE = 60        # un risultato cambiato senza l'azione del gol: dopo un minuto il gol esce lo stesso
ATTESA_ANNULLATO = 30     # un risultato tornato indietro per tanto così è un gol annullato
FINE_ATTESA = 60          # a partita finita si aspetta un minuto, così le statistiche sono quelle finali
MARCA = "#BeneventoCalcio"   # in fondo ai post di Facebook e Instagram (instagram.py non li conta tra le notizie)
SEGNI = {"gol": "⚽", "annullato": "❌", "intervallo": "⏸", "finale": "🏁"}
GIORNI = ["lunedì", "martedì", "mercoledì", "giovedì", "venerdì", "sabato", "domenica"]
MESI = ["gennaio", "febbraio", "marzo", "aprile", "maggio", "giugno", "luglio", "agosto", "settembre", "ottobre",
        "novembre", "dicembre"]
CANALI = ("telegram", "facebook", "instagram")
riprova = facebook.riprova


# ---------------------------------------------------------------- l'italiano delle squadre e dei minuti

FEMMINILI = re.compile(r"^(juve stabia|sampdoria|cremonese|carrarese|virtus entella|reggiana|salernitana|ternana|"
                       r"triestina|lucchese|spal|feralpisal|pro vercelli|virtus)", re.I)   # come in calcio.js


def art(nome):
    """L'articolo: il Benevento, l'Arezzo, la Juve Stabia, lo Spezia."""
    if FEMMINILI.match(nome):
        return "l'" if re.match(r"[aeiou]", nome, re.I) else "la "
    if nome.lower() == "spezia":
        return "lo "
    return "l'" if re.match(r"[aeiouàèéìòù]", nome, re.I) else "il "


PREP = {"di": {"il ": "del ", "lo ": "dello ", "la ": "della ", "l'": "dell'"},
        "a": {"il ": "al ", "lo ": "allo ", "la ": "alla ", "l'": "all'"},
        "con": {"il ": "con il ", "lo ": "con lo ", "la ": "con la ", "l'": "con l'"}}


def con(prep, nome):
    a = art(nome)
    return (PREP[prep][a] if prep else a) + nome


def maiusc(s):
    return s[:1].upper() + s[1:]


def al_minuto(minuto):
    """«al 49'», «all'8'», «all'87'»."""
    m = re.match(r"\d+", minuto or "")
    n = int(m.group()) if m else 0
    return ("all'" if n in (1, 8, 11) or 80 <= n <= 89 else "al ") + (minuto or "")


NUMERI = {1: "un", 2: "due", 3: "tre", 4: "quattro", 5: "cinque"}


def gol_di_scarto(n):
    return f"{NUMERI.get(n, n)} gol" if n > 1 else "un gol"


# ---------------------------------------------------------------- la partita, dalla diretta di ESPN

def leggi_json(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Encoding": "gzip"})
    with urllib.request.urlopen(req, timeout=20) as r:
        raw = r.read()
    return json.loads(gzip.decompress(raw) if raw[:2] == b"\x1f\x8b" else raw)


def apri(percorso):
    with open(percorso, "rb") as f:
        raw = f.read()
    return json.loads(gzip.decompress(raw) if raw[:2] == b"\x1f\x8b" else raw)


def nome_squadra(t):
    return NOMI.get(t.get("displayName"), t.get("displayName") or t.get("name") or "?")


def stato_partita(s):
    """Quello che serve della diretta (summary di ESPN): squadre, risultato, stato, azioni, statistiche."""
    comp = s["header"]["competitions"][0]
    cs = {c["homeAway"]: c for c in comp["competitors"]}
    casa, fuori = cs["home"]["team"], cs["away"]["team"]
    st = comp.get("status") or {}
    tipo = st.get("type") or {}
    cognomi = {}
    for r in s.get("rosters") or []:
        for x in r.get("roster") or []:
            a = x.get("athlete") or {}
            if a.get("id"):
                cognomi[a["id"]] = a.get("lastName") or a.get("displayName")
    stats = {}
    for t in (s.get("boxscore") or {}).get("teams") or []:
        stats[(t.get("team") or {}).get("id")] = {x.get("name"): x.get("displayValue") for x in t.get("statistics") or []}

    def punti(c):
        try:
            return int(c.get("score"))
        except (TypeError, ValueError):
            return 0

    return {
        "id": comp.get("id") or (s.get("header") or {}).get("id"),
        "casa": casa["id"], "fuori": fuori["id"],
        "nomi": {casa["id"]: nome_squadra(casa), fuori["id"]: nome_squadra(fuori)},
        "loghi": {t["id"]: next((l["href"] for l in t.get("logos") or [] if l.get("href")),
                                f"https://a.espncdn.com/i/teamlogos/soccer/500/{t['id']}.png") for t in (casa, fuori)},
        "gol": {casa["id"]: punti(cs["home"]), fuori["id"]: punti(cs["away"])},
        "stato": tipo.get("state") or "pre",          # pre, in, post
        "fase": tipo.get("name") or "",               # STATUS_FIRST_HALF, STATUS_HALFTIME, STATUS_FULL_TIME…
        "finita": bool(tipo.get("completed")),
        "minuto": st.get("displayClock") or "",
        "quando": comp.get("date"),
        "azioni": s.get("keyEvents") or [],
        "cognomi": cognomi,
        "stats": stats,
        "stadio": ((s.get("gameInfo") or {}).get("venue") or {}).get("fullName") or "",
    }


def tipo_azione(k):
    return str((k.get("type") or {}).get("type") or (k.get("type") or {}).get("text") or "").lower()


def e_gol(k):
    return bool(k.get("scoringPlay")) or "goal" in tipo_azione(k)


def ordine(k):
    return ((k.get("period") or {}).get("number") or 0, (k.get("clock") or {}).get("value") or 0)


def chi(k, p, indice=0):
    """Il cognome di chi ha fatto l'azione (dalle formazioni), o il nome come lo scrive ESPN."""
    part = k.get("participants") or k.get("athletesInvolved") or []
    if len(part) <= indice:
        return ""
    a = part[indice].get("athlete") or part[indice]
    if p["cognomi"].get(a.get("id")):
        return p["cognomi"][a["id"]]
    n = str(a.get("displayName") or "").split()
    return " ".join(n[1:]) if len(n) > 1 else (n[0] if n else "")


def gol_della_partita(p):
    """Le azioni dei gol in ordine, ognuna con la squadra a cui va. Per gli autogol non è chiaro se ESPN scriva la
    squadra di chi l'ha fatto o quella a cui va: si sceglie il verso che fa tornare il risultato ufficiale (come in
    calcio.js)."""
    gol = sorted((k for k in p["azioni"] if e_gol(k)), key=ordine)
    out = []
    for k in gol:
        t = (k.get("team") or {}).get("id")
        if "own" in tipo_azione(k):
            t = p["fuori"] if t == p["casa"] else p["casa"]
        out.append([k, t])
    casa = sum(1 for _, t in out if t == p["casa"])
    autogol = [x for x in out if "own" in tipo_azione(x[0])]
    if autogol and casa != p["gol"][p["casa"]]:
        for x in autogol:   # l'altro verso
            x[1] = p["fuori"] if x[1] == p["casa"] else p["casa"]
    return [(k, t) for k, t in out]


# ---------------------------------------------------------------- cosa dire

def risultato(p, gol=None):
    g = gol or p["gol"]
    return f"{p['nomi'][p['casa']]} {g[p['casa']]}-{g[p['fuori']]} {p['nomi'][p['fuori']]}"


def come(k):
    t = tipo_azione(k)
    return " di testa" if "header" in t else " su rigore" if "penalty" in t else " su punizione" if "free" in t else ""


def verbo_gol(prima, dopo, squadra, p):
    """«sblocca la partita», «pareggia», «raddoppia»… dal risultato prima e dopo il gol."""
    altra = p["fuori"] if squadra == p["casa"] else p["casa"]
    mio, loro = dopo[squadra], dopo[altra]
    if mio == 1 and loro == 0:
        return "sblocca la partita"
    if mio == loro:
        return "pareggia"
    if mio - loro == 1 and prima[squadra] == prima[altra]:
        return "porta avanti " + con("", p["nomi"][squadra])
    if mio == 2 and loro == 0:
        return "raddoppia"
    if mio == 3 and loro == 0:
        return "cala il tris"
    return "allunga" if mio > loro else "accorcia le distanze"


def frase_gol(g, p):
    """«49' Siatounis sblocca la partita.» / «Autogol di Rossi.»"""
    if g.get("autogol"):
        return f"{g['minuto']} Autogol di {g['chi']}." if g.get("chi") else f"{g['minuto']} Autogol."
    if not g.get("chi"):   # il gol c'è nel risultato ma non ancora l'azione: il soggetto è la squadra
        v = "va in vantaggio" if g["verbo"].startswith("porta avanti") else g["verbo"]
        return f"{g['minuto']} {maiusc(con('', p['nomi'][g['squadra']]))} {v}.".strip()
    return f"{g['minuto']} {g['chi']} {g['verbo']}{g.get('come', '')}.".strip()


def marcatori(p, gol, squadra):
    out = []
    for g in gol:
        if g["squadra"] == squadra and g.get("valido", True):
            extra = " (aut.)" if g.get("autogol") else " (rig.)" if g.get("come") == " su rigore" else ""
            out.append(f"{g['minuto']} {g.get('chi') or '?'}{extra}".strip())
    return out


def cartellini(p, colore, fino_al_periodo=9):
    """[(minuto, cognome, squadra)] dei gialli o dei rossi."""
    out = []
    for k in sorted(p["azioni"], key=ordine):
        t = tipo_azione(k)
        if ordine(k)[0] > fino_al_periodo:
            continue
        if (colore == "rosso" and "red" in t) or (colore == "giallo" and "yellow" in t and "red" not in t):
            out.append(((k.get("clock") or {}).get("displayValue") or "", chi(k, p), (k.get("team") or {}).get("id")))
    return out


def numeri(p):
    """«Possesso palla 58-42, tiri in porta 9-2 (tiri 18-12).», casa prima."""
    a, b = p["stats"].get(p["casa"]) or {}, p["stats"].get(p["fuori"]) or {}
    parti = []
    try:
        pa = round(float(a.get("possessionPct")))
        parti.append(f"possesso palla {pa}-{100 - pa}")
    except (TypeError, ValueError):
        pass
    if a.get("shotsOnTarget") is not None and b.get("shotsOnTarget") is not None:
        parti.append(f"tiri in porta {a['shotsOnTarget']}-{b['shotsOnTarget']}")
    if a.get("totalShots") is not None and b.get("totalShots") is not None:
        parti.append(f"tiri {a['totalShots']}-{b['totalShots']}")
    return (maiusc(", ".join(parti)) + ".") if parti else ""


def racconto_gol(p, gol, noi):
    """«Il Benevento passa al 22' con Siatounis e raddoppia al 27' con Kouan; il Vicenza accorcia al 68' con Corazza e
    pareggia all'87' con Caferri.»"""
    validi = [g for g in gol if g.get("valido", True)]
    if not validi:
        return "Nessun gol."
    parole = {"sblocca la partita": "passa", "pareggia": "pareggia", "raddoppia": "raddoppia", "cala il tris": "cala il tris",
              "allunga": "allunga", "accorcia le distanze": "accorcia"}
    pezzi, soggetto, gruppo = [], None, []
    for g in validi:
        v = parole.get(g["verbo"], "passa in vantaggio" if g["verbo"].startswith("porta avanti") else "segna")
        quando = al_minuto(g["minuto"]) if g.get("minuto") else ""
        chi_ = f" con {g['chi']}" if g.get("chi") and not g.get("autogol") else (
            f" con un autogol di {g['chi']}" if g.get("chi") else " con un autogol" if g.get("autogol") else "")
        azione = f"{v} {quando}{chi_}".replace("  ", " ").strip()
        if g["squadra"] != soggetto:
            if gruppo:
                pezzi.append(gruppo)
            soggetto, gruppo = g["squadra"], [maiusc(con("", p["nomi"][g["squadra"]])) + " " + azione]
        else:
            gruppo.append(azione)

    def unisci(xs):
        return xs[0] if len(xs) == 1 else ", ".join(xs[:-1]) + " e " + xs[-1]

    pezzi.append(gruppo)
    frasi = [unisci(x) for x in pezzi]
    testo = "; ".join([frasi[0]] + [f[0].lower() + f[1:] if f.startswith(("Il ", "Lo ", "La ", "L'")) else f
                                    for f in frasi[1:]])
    return testo + "."


def esito(p, noi):
    io, altro = (p["casa"], p["fuori"]) if p["casa"] == noi else (p["fuori"], p["casa"])
    a, b = p["gol"][io], p["gol"][altro]
    nome = p["nomi"][io]
    if a > b:
        return f"Vince {con('', nome)}!", 3
    if a == b:
        return "Finisce in parità.", 1
    return f"Sconfitta per {con('', nome)}.", 0


def commento_intervallo(p, noi):
    io = noi
    altro = p["fuori"] if io == p["casa"] else p["casa"]
    a, b = p["gol"][io], p["gol"][altro]
    nome = maiusc(con("", p["nomi"][io]))
    if a == b:
        return "Si va al riposo sullo 0-0." if a == 0 else f"Si va al riposo in parità, {a}-{b}."
    if a > b:
        return f"{nome} va al riposo in vantaggio." if a - b == 1 else f"{nome} va al riposo avanti di {gol_di_scarto(a - b)}."
    return f"{nome} va al riposo sotto di {gol_di_scarto(b - a)}."


def data(iso):
    try:
        t = dt.datetime.fromisoformat(str(iso).replace("Z", "+00:00"))
        return t if t.tzinfo else t.replace(tzinfo=fuso())
    except ValueError:
        return dt.datetime.min.replace(tzinfo=dt.timezone.utc)


def quando_detto(iso):
    t = dt.datetime.fromisoformat(iso).astimezone(fuso())
    ora = f"{t.hour}" if t.minute == 0 else f"{t:%H:%M}"
    return f"{GIORNI[t.weekday()]} {t.day} {MESI[t.month - 1]} alle {ora}"


def testi(tipo, p, noi, dati, calcio=None):
    """I tre testi (telegram, facebook, instagram) di un'uscita."""
    piede_tg = f"La diretta, la classifica e gli altri campi: {PAGINA_CALCIO}"
    piede_fb = piede_tg + f"\n\n{MARCA} #SerieB"
    piede_ig = "La diretta, la classifica e gli altri campi sul sito: notiziebenevento.it/calcio" + \
               f"\n\n{MARCA} #SerieB #Benevento #Sannio"
    if tipo == "gol":
        g = dati["gol"]
        testa = "⚽ GOL DEL BENEVENTO!" if g["squadra"] == noi and noi == BENEVENTO else \
            f"⚽ GOL {con('di', p['nomi'][noi]).upper()}!" if g["squadra"] == noi else f"⚽ Gol {con('di', p['nomi'][g['squadra']])}."
        corpo = f"{testa}\n{frase_gol(g, p)}\n\n{dati['risultato']}"
    elif tipo == "annullato":
        g = dati["gol"]
        di = f"di {g['chi']} " if g.get("chi") else ""
        corpo = (f"❌ Gol annullato: non vale il gol {di}{('(' + g['minuto'] + ') ') if g.get('minuto') else ''}"
                 f"{con('di', p['nomi'][g['squadra']])}.\n\n{dati['risultato']}").replace("  ", " ")
    elif tipo == "intervallo":
        righe = [f"⏸ Fine primo tempo: {dati['risultato']}", commento_intervallo(p, noi), ""]
        for sq in (p["casa"], p["fuori"]):
            m = marcatori(p, dati["gol_lista"], sq)
            if m:
                righe.append(f"⚽ {', '.join(m)} ({p['nomi'][sq]})")
        for minuto, nome, sq in cartellini(p, "rosso", 1):
            righe.append(f"🟥 {minuto} espulso {nome} ({p['nomi'].get(sq, '')})")
        gialli = cartellini(p, "giallo", 1)
        if gialli:
            righe.append("🟨 Ammoniti: " + ", ".join(f"{n} ({p['nomi'].get(s, '')})" for _, n, s in gialli))
        if numeri(p):
            righe.append("📊 " + numeri(p))
        corpo = "\n".join(righe).replace("\n\n\n", "\n\n").rstrip()
    else:   # finale
        frase, punti = esito(p, noi)
        righe = [f"🏁 Finale: {dati['risultato']}", frase, "", racconto_gol(p, dati["gol_lista"], noi)]
        rossi = cartellini(p, "rosso")
        if rossi:
            righe.append("🟥 Espulsi: " + ", ".join(f"{n} ({p['nomi'].get(s, '')}, {m})" for m, n, s in rossi))
        if numeri(p):
            righe.append("📊 " + numeri(p))
        dopo = []
        if calcio:
            riga = next((r for r in calcio.get("classifica") or [] if r.get("id") == noi), None)
            questa = next((x for x in calcio.get("partite") or [] if x.get("id") == p["id"]), {})
            if riga and riga.get("pt") is not None:   # calcio.json letto prima della fine: la partita non c'è ancora
                gia = questa.get("stato") == "post"
                nome = maiusc(con("", p["nomi"][noi]))
                pt = riga["pt"] + (0 if gia else punti)
                dopo.append(f"{nome} {'sale' if punti else 'resta'} a {pt} punti in classifica.")
            inizio = data(p.get("quando"))
            prossima = next((x for x in sorted(calcio.get("partite") or [], key=lambda x: data(x.get("quando")))
                             if x.get("stato") == "pre" and x.get("id") != p["id"] and data(x.get("quando")) > inizio),
                            None)
            if prossima:
                sq = calcio.get("squadre") or {}
                nomi = [(sq.get(prossima["casa"]) or {}).get("nome", "?"), (sq.get(prossima["fuori"]) or {}).get("nome", "?")]
                ora = quando_detto(prossima["quando"]) if prossima.get("ora_certa") else \
                    quando_detto(prossima["quando"]).split(" alle ")[0] + " (orario da confermare)"
                dopo.append(f"Prossima partita: {ora}, {nomi[0]}-{nomi[1]}.")
        if dopo:
            righe += [""] + dopo
        corpo = "\n".join(righe).rstrip()
    return corpo + "\n\n" + piede_tg, corpo + "\n\n" + piede_fb, corpo + "\n\n" + piede_ig


# ---------------------------------------------------------------- l'immagine

def immagine(percorso, tipo, p, noi, dati, cartella_loghi):
    from PIL import Image, ImageDraw
    from pagine import FONT_BLACK, FONT_BOLD, _a_capo, _font, _testata
    W, H = 1080, 1350
    ROSSO, NERO, GRIGIO, CARTA, RIGA = "#c4161c", "#111111", "#5b5249", "#fdeedd", "#e3c9ad"
    im = Image.new("RGB", (W, H), CARTA)
    d = ImageDraw.Draw(im)
    _testata(d, W)
    x = 60
    occhiello = {"gol": "SERIE B · IN DIRETTA", "annullato": "SERIE B · IN DIRETTA", "intervallo": "SERIE B · INTERVALLO",
                 "finale": "SERIE B · RISULTATO FINALE"}[tipo]
    d.text((x, 205), occhiello, font=_font(FONT_BOLD, 30), fill=ROSSO, anchor="lm")
    g = dati.get("gol")
    nostro = g and g["squadra"] == noi
    if tipo == "gol":
        titolo = f"GOL {con('di', p['nomi'][g['squadra']]).upper()}!" if nostro else f"Gol {con('di', p['nomi'][g['squadra']])}"
        colore = ROSSO if nostro else NERO
    elif tipo == "annullato":
        titolo, colore = "Gol annullato", NERO
    elif tipo == "intervallo":
        titolo, colore = "Fine primo tempo", NERO
    else:
        titolo = esito(p, noi)[0].rstrip("!.")
        colore = ROSSO if esito(p, noi)[1] == 3 else NERO
    for size in range(104, 50, -4):
        ft = _font(FONT_BLACK, size)
        righe = _a_capo(titolo, ft, W - 120)
        if len(righe) <= 2:
            break
    y = 250
    for r in righe:
        d.text((x, y), r, font=ft, fill=colore)
        y += size * 1.1
    if tipo in ("gol", "annullato"):
        sotto = frase_gol(g, p) if tipo == "gol" else f"Non vale il gol{(' di ' + g['chi']) if g.get('chi') else ''}" + \
            (f" ({g['minuto']})" if g.get("minuto") else "")
        fs = _font(FONT_BOLD, 46)
        for r in _a_capo(sotto, fs, W - 120)[:2]:
            d.text((x, y + 14), r, font=fs, fill=GRIGIO)
            y += 58
    # il tabellone: i due stemmi, i nomi e il risultato
    yt = y + 80
    lato = 230
    for i, sq in enumerate((p["casa"], p["fuori"])):
        cx = 60 + lato // 2 + 20 if i == 0 else W - 60 - lato // 2 - 20
        lg = logo(sq, p, cartella_loghi)
        if lg:
            lg = lg.copy()
            lg.thumbnail((lato, lato))
            im.paste(lg, (int(cx - lg.width / 2), int(yt + (lato - lg.height) / 2)), lg)
        else:
            d.ellipse([cx - lato / 2 + 20, yt + 20, cx + lato / 2 - 20, yt + lato - 20], fill=RIGA)
        fn = _font(FONT_BOLD, 40)
        nome = p["nomi"][sq]
        while fn.getlength(nome) > 330 and fn.size > 26:
            fn = _font(FONT_BOLD, fn.size - 2)
        d.text((cx, yt + lato + 46), nome, font=fn, fill=NERO, anchor="mm")
    ris = dati["gol_ora"]
    fr = _font(FONT_BLACK, 190)
    d.text((W / 2, yt + lato / 2), f"{ris[p['casa']]}–{ris[p['fuori']]}", font=fr, fill=NERO, anchor="mm")
    y = yt + lato + 110
    # sotto il tabellone: i marcatori (intervallo e fine) o il minuto
    con_gol = any(g.get("valido", True) for g in dati.get("gol_lista") or [])
    if con_gol or tipo in ("intervallo", "finale"):   # sotto il tabellone: chi ha segnato, gli espulsi, i numeri
        d.line([x, y, W - x, y], fill=RIGA, width=3)
        y += 30
        fm = _font(FONT_BOLD, 34)
        for sq in (p["casa"], p["fuori"]):
            m = marcatori(p, dati["gol_lista"], sq)
            if m:
                for r in _a_capo(f"{p['nomi'][sq]}: {', '.join(m)}", fm, W - 120)[:2]:
                    d.text((x, y), r, font=fm, fill=NERO)
                    y += 46
        rossi = cartellini(p, "rosso", 1 if tipo == "intervallo" else 9) if tipo in ("intervallo", "finale") else []
        if rossi:
            for r in _a_capo("Espulsi: " + ", ".join(f"{n} ({m})" for m, n, s in rossi), fm, W - 120)[:2]:
                d.text((x, y), r, font=fm, fill=ROSSO)
                y += 46
        nu = numeri(p) if tipo in ("intervallo", "finale") else ""
        if nu and y < H - 190:
            for r in _a_capo(nu, _font(FONT_BOLD, 30), W - 120)[:2]:
                d.text((x, y + 8), r, font=_font(FONT_BOLD, 30), fill=GRIGIO)
                y += 42
    d.rectangle([0, H - 14, W, H], fill=ROSSO)
    d.text((x, H - 56), "La diretta e la classifica: notiziebenevento.it/calcio", font=_font(FONT_BOLD, 30),
           fill=NERO, anchor="lm")
    im.save(percorso, "JPEG", quality=88, optimize=True)


def logo(sq, p, cartella):
    """Lo stemma grande (500 px) da ESPN, una volta per partita; se non arriva, quello piccolo del sito."""
    from PIL import Image
    dove = os.path.join(cartella, f"{sq}.png")
    if not os.path.exists(dove):
        try:
            req = urllib.request.Request(p["loghi"][sq], headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=20) as r, open(dove, "wb") as f:
                f.write(r.read())
        except Exception:
            piccolo = os.path.join(os.path.dirname(QUI), "img", "calcio", f"{sq}.png")
            if not os.path.exists(piccolo):
                return None
            dove = piccolo
    try:
        return Image.open(dove).convert("RGBA")
    except Exception:
        return None


# ---------------------------------------------------------------- il cronista: dalla diretta alle uscite

class Cronista:
    """Tiene il conto dei gol già detti e decide cosa mandare a ogni lettura della diretta."""

    def __init__(self, stato, noi):
        self.s = stato
        self.noi = noi
        self.s.setdefault("gol", [])        # i gol già detti: {id, squadra, minuto, chi, verbo, come, autogol, valido}
        self.s.setdefault("attese", {})     # da quando si vede un risultato senza azione, o tornato indietro
        self.s.setdefault("uscite", {})     # chiave → {canale: ora}

    def conti(self):
        c = {}
        for g in self.s["gol"]:
            if g.get("valido", True):
                c[g["squadra"]] = c.get(g["squadra"], 0) + 1
        return c

    def passo(self, p, adesso):
        """[(chiave, tipo, dati)] delle uscite nuove."""
        out = []
        conti = self.conti()
        ora = {sq: conti.get(sq, 0) for sq in (p["casa"], p["fuori"])}
        azioni = gol_della_partita(p)
        detti = {g["id"] for g in self.s["gol"] if g.get("id")}
        # le azioni arrivate dopo un gol già detto senza nome: si danno a quel gol (senza dirlo di nuovo)
        for g in self.s["gol"]:
            if not g.get("id") and g.get("valido", True):
                libera = next((k for k, sq in azioni if sq == g["squadra"] and k.get("id") not in detti), None)
                if libera:
                    g.update(id=libera.get("id"), chi=chi(libera, p), minuto=(libera.get("clock") or {}).get("displayValue") or g.get("minuto", ""))
                    detti.add(libera.get("id"))
        nuove = [(k, sq) for k, sq in azioni if k.get("id") not in detti]
        # i gol nuovi, nell'ordine in cui sono stati segnati
        for k, sq in nuove:
            if ora[sq] >= p["gol"][sq]:
                continue   # l'azione c'è, il risultato ufficiale non ancora: si aspetta il risultato
            out.append(self.di_gol(p, sq, k, ora, adesso))
        for sq in (p["casa"], p["fuori"]):
            if p["gol"][sq] > ora[sq]:
                chiave_attesa = f"senza_azione:{sq}:{ora[sq] + 1}"
                inizio = dt.datetime.fromisoformat(self.s["attese"].setdefault(chiave_attesa, adesso.isoformat()))
                if (adesso - inizio).total_seconds() >= ATTESA_AZIONE:
                    while p["gol"][sq] > ora[sq]:
                        out.append(self.di_gol(p, sq, None, ora, adesso))
            if p["gol"][sq] <= ora[sq]:
                for k in [k for k in self.s["attese"] if k.startswith(f"senza_azione:{sq}:")]:
                    self.s["attese"].pop(k, None)
            chiave_giu = f"giu:{sq}:{p['gol'][sq]}"
            if p["gol"][sq] < ora[sq]:
                inizio = dt.datetime.fromisoformat(self.s["attese"].setdefault(chiave_giu, adesso.isoformat()))
                if (adesso - inizio).total_seconds() >= ATTESA_ANNULLATO:
                    while p["gol"][sq] < ora[sq]:
                        g = [x for x in self.s["gol"] if x["squadra"] == sq and x.get("valido", True)][-1]
                        g["valido"] = False
                        ora[sq] -= 1
                        out.append((f"annullato:{g['n']}", "annullato",
                                    {"gol": dict(g), "risultato": risultato(p, ora), "gol_ora": dict(ora)}))
                    self.s["attese"].pop(chiave_giu, None)
            else:
                for k in [k for k in self.s["attese"] if k.startswith(f"giu:{sq}:")]:
                    self.s["attese"].pop(k, None)
        if p["fase"] == "STATUS_HALFTIME" and "intervallo" not in self.s["uscite"] and \
                not any(c[1] in ("gol", "annullato") for c in out):
            out.append(("intervallo", "intervallo", {"risultato": risultato(p), "gol_ora": dict(p["gol"]),
                                                    "gol_lista": list(self.s["gol"])}))
        if p["finita"] and "finale" not in self.s["uscite"] and not out:
            inizio = dt.datetime.fromisoformat(self.s["attese"].setdefault("finale", adesso.isoformat()))
            if (adesso - inizio).total_seconds() >= FINE_ATTESA and ora == p["gol"]:
                out.append(("finale", "finale", {"risultato": risultato(p), "gol_ora": dict(p["gol"]),
                                                 "gol_lista": list(self.s["gol"])}))
        return out

    def di_gol(self, p, sq, k, ora, adesso):
        prima = dict(ora)
        ora[sq] += 1
        n = len(self.s["gol"]) + 1
        g = {"n": n, "id": k.get("id") if k else None, "squadra": sq,
             "minuto": ((k.get("clock") or {}).get("displayValue") if k else p.get("minuto")) or "",
             "chi": chi(k, p) if k else "", "come": come(k) if k else "", "autogol": bool(k and "own" in tipo_azione(k)),
             "verbo": verbo_gol(prima, ora, sq, p), "valido": True}
        self.s["gol"].append(g)
        return (f"gol:{n}", "gol", {"gol": dict(g), "risultato": risultato(p, ora), "gol_ora": dict(ora),
                                    "gol_lista": [dict(x) for x in self.s["gol"]]})


# ---------------------------------------------------------------- l'invio

def github(metodo, percorso, token, dati=None):
    req = urllib.request.Request(f"https://api.github.com/repos/{REPO}/{percorso}", method=metodo,
                                 data=json.dumps(dati).encode() if dati is not None else None,
                                 headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json",
                                          "X-GitHub-Api-Version": "2022-11-28", "User-Agent": "nb-gol"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"GitHub {e.code} su {percorso}") from None


def carica(percorso, nome, token):
    """L'immagine nel ramo gol-immagini: l'indirizzo raw.githubusercontent.com è online subito."""
    try:
        github("GET", f"git/ref/heads/{RAMO}", token)
    except RuntimeError as e:
        if "404" not in str(e):
            raise
        base = github("GET", "git/ref/heads/main", token)["object"]["sha"]
        github("POST", "git/refs", token, {"ref": f"refs/heads/{RAMO}", "sha": base})
    with open(percorso, "rb") as f:
        contenuto = base64.b64encode(f.read()).decode()
    riprova(lambda: github("PUT", f"contents/{nome}", token, {"message": f"Gol: {nome}", "content": contenuto,
                                                              "branch": RAMO}), "GitHub (immagine)")
    url = f"https://raw.githubusercontent.com/{REPO}/{RAMO}/{nome}"
    for _ in range(12):
        if facebook.online(url):
            return url
        time.sleep(3)
    raise RuntimeError(f"l'immagine non è online: {url}")


def manda(testi_, canali, chiavi, url, ig):
    """Un'uscita sui canali dove non c'è ancora (canali: canale → ora). Restituisce gli errori. Se un invio forse è
    uscito (la risposta si è persa), il canale si segna «incerto» e non si riprova: meglio uno in meno che un doppione."""
    tg_testo, fb_testo, ig_testo = testi_
    errori = []

    def tenta(canale, fare):
        try:
            fare()
            canali[canale] = ora_iso()
        except Exception as e:
            if "forse è uscito" in str(e):
                canali[canale] = "incerto"
            errori.append(f"{maiusc(canale)}: {e}")

    def su_instagram():
        q = riprova(lambda: facebook.chiama("GET", f"{ig}/content_publishing_limit", chiavi["facebook"],
                                            {"fields": "quota_usage,config"}), "Instagram (quota)", True)
        q = (q.get("data") or [{}])[0]
        if q.get("quota_usage", 0) >= (q.get("config") or {}).get("quota_total", 50):
            raise RuntimeError(f"finiti i post di oggi ({q.get('quota_usage')}): questo non esce")
        import instagram
        cont = riprova(lambda: facebook.chiama("POST", f"{ig}/media", chiavi["facebook"],
                                               {"image_url": url, "caption": ig_testo[:2200]})["id"], "Instagram")
        instagram.aspetta(cont, chiavi["facebook"])
        riprova(lambda: facebook.chiama("POST", f"{ig}/media_publish", chiavi["facebook"], {"creation_id": cont}),
                "Instagram (pubblica)")

    if "telegram" not in canali:   # col suono: niente disable_notification
        tenta("telegram", lambda: riprova(lambda: telegram.chiama(chiavi["telegram"], "sendPhoto", {
            "chat_id": telegram.CANALE, "photo": url, "caption": tg_testo[:1024]}), "Telegram"))
    if "facebook" not in canali:
        tenta("facebook", lambda: facebook.foto_con_testo(chiavi["facebook"], url, fb_testo, PAGINA_CALCIO))
    if "instagram" not in canali and ig:
        tenta("instagram", su_instagram)
    return errori


def ora_iso():
    return dt.datetime.now(fuso()).isoformat(timespec="seconds")


def gia_sui_canali(p, chiavi, ig, da):
    """Se il file dello stato non c'è: cosa è già uscito per questa partita, letto dai canali (testi che cominciano
    con il segno e contengono il risultato). {chiave del testo: set(canali)}"""
    trovati = {}

    def segna(testo, canale):
        testo = html.unescape(testo or "").strip()
        if not testo or testo[0] not in "".join(SEGNI.values()) or p["nomi"][p["casa"]] not in testo:
            return
        trovati.setdefault(testo.split("\n\n")[0] if testo.startswith(("⏸", "🏁")) else testo.split("\n\n")[1]
                           if testo.startswith(("⚽", "❌")) and "\n\n" in testo else testo[:80], set()).add(canale)
        trovati.setdefault("#" + testo[0], set()).add(canale)

    try:
        req = urllib.request.Request(telegram.ANTEPRIMA, headers={"User-Agent": "Mozilla/5.0 (notiziebenevento.it)"})
        with urllib.request.urlopen(req, timeout=30) as r:
            pagina = r.read().decode("utf-8", "replace")
        for b in re.split(r'(?=<div class="tgme_widget_message_wrap)', pagina)[1:]:
            t = re.search(r'<time datetime="([^"]+)"', b)
            m = re.search(r'<div class="tgme_widget_message_text[^"]*"[^>]*>(.*?)</div>', b, re.S)
            if t and m and dt.datetime.fromisoformat(t.group(1)) >= da:
                segna(re.sub(r"<br\s*/?>", "\n", re.sub(r"<(?!br)[^>]+>", "", m.group(1))), "telegram")
    except Exception as e:
        raise RuntimeError(f"Telegram non si legge ({e}): senza il file dello stato non so cosa è già uscito") from None
    for p_ in riprova(lambda: facebook.chiama("GET", "me/posts", chiavi["facebook"], {"fields": "created_time,message",
                                                                                     "limit": 30}), "Facebook", True).get("data", []):
        if dt.datetime.strptime(p_["created_time"], "%Y-%m-%dT%H:%M:%S%z") >= da:
            segna(p_.get("message"), "facebook")
    if ig:
        for p_ in riprova(lambda: facebook.chiama("GET", f"{ig}/media", chiavi["facebook"], {"fields": "caption,timestamp",
                                                                                           "limit": 30}), "Instagram", True).get("data", []):
            if dt.datetime.strptime(p_["timestamp"], "%Y-%m-%dT%H:%M:%S%z") >= da:
                segna(p_.get("caption"), "instagram")
    return trovati


def chiave_testo(tg_testo):
    """La parte di un testo che si cerca sui canali (vedi gia_sui_canali)."""
    if tg_testo.startswith(("⏸", "🏁")):
        return tg_testo.split("\n\n")[0]
    if tg_testo.startswith(("⚽", "❌")):
        return tg_testo.split("\n\n")[1]
    return tg_testo[:80]


# ---------------------------------------------------------------- le prove: una partita finita, minuto per minuto

def rigioca(finale, passo_s=30):
    """Le letture che avrebbe dato la diretta di una partita finita, una ogni OGNI secondi finti e mezzo minuto di
    gioco: le azioni fino a quel momento e il risultato che ne viene, con l'intervallo e la fine. [(ora, summary)]"""
    p = stato_partita(finale)
    gol = gol_della_partita(p)
    fine1 = max([ordine(k)[1] for k in p["azioni"] if ordine(k)[0] == 1] + [2700])
    fine2 = max([ordine(k)[1] for k in p["azioni"]] + [5400])
    fasi = [(1, t, "STATUS_FIRST_HALF") for t in range(0, int(fine1) + 1, passo_s)]
    fasi += [(1, int(fine1), "STATUS_HALFTIME")] * 6
    fasi += [(2, t, "STATUS_SECOND_HALF") for t in range(2700, int(fine2) + 1, passo_s)]
    fasi += [(2, int(fine2), "STATUS_FULL_TIME")] * 8
    t0 = dt.datetime.now(fuso()).replace(microsecond=0)
    letture = []
    for i, (periodo, orologio, fase) in enumerate(fasi):
        s = json.loads(json.dumps(finale))
        finita = fase == "STATUS_FULL_TIME"
        s["keyEvents"] = [k for k in finale.get("keyEvents") or [] if finita or ordine(k) <= (periodo, orologio)]
        conto = {"home": 0, "away": 0}
        for k, sq in gol:
            if finita or ordine(k) <= (periodo, orologio):
                conto["home" if sq == p["casa"] else "away"] += 1
        comp = s["header"]["competitions"][0]
        for c in comp["competitors"]:
            c["score"] = str(conto[c["homeAway"]])
        comp["status"] = {"type": {"name": fase, "state": "post" if finita else "in", "completed": finita},
                          "displayClock": f"{orologio // 60 + 1}'", "period": periodo}
        letture.append((t0 + dt.timedelta(seconds=i * OGNI), s))
    return letture


def registrazione(cartella, partita):
    """Le letture registrate dal Pi (calcio_prove/registra.sh): partita-<id>-HHMMSS.json, in ordine."""
    out = []
    oggi = dt.datetime.now(fuso()).date()
    for f in sorted(glob.glob(os.path.join(cartella, f"partita-{partita}-*.json"))):
        hms = re.search(r"-(\d{6})\.json$", f).group(1)
        t = dt.datetime.combine(oggi, dt.time(int(hms[:2]), int(hms[2:4]), int(hms[4:])), fuso())
        try:
            out.append((t, apri(f)))
        except Exception:
            print(f"  registrazione: {os.path.basename(f)} non si legge, salto")
    return out


# ---------------------------------------------------------------- il collaudo dei canali, senza pubblicare

def collaudo(chiavi, cartella):
    """Prova tutto quello che serve in partita senza pubblicare niente: l'immagine (dell'ultima partita finita del
    Benevento) caricata nel ramo e online, la chiave di Telegram, la Pagina, la quota di Instagram e Instagram che
    scarica e prepara l'immagine (il contenitore si crea ma non si pubblica: dopo 24 ore sparisce da solo)."""
    ok = True

    def esito(cosa, fare):
        nonlocal ok
        try:
            print(f"collaudo: {cosa}: {fare()}")
        except Exception as e:
            ok = False
            print(f"collaudo: {cosa}: NON VA ({e})")

    ultima = next((x for x in reversed(sorted((leggi_json(f"{SITO}/calcio.json").get("partite") or []),
                                              key=lambda x: data(x.get("quando")))) if x.get("stato") == "post"), None)
    p = stato_partita(leggi_json(f"{ESPN}/summary?event={ultima['id']}"))
    cr = Cronista({}, BENEVENTO)
    uscite = cr.passo(dict(p, finita=False, fase="STATUS_SECOND_HALF"), dt.datetime.now(fuso()))
    chiave, tipo, dati = (uscite or [(None, "finale", {"risultato": risultato(p), "gol_ora": dict(p["gol"]), "gol_lista": []})])[0]
    percorso = os.path.join(cartella, "collaudo.jpg")
    immagine(percorso, tipo, p, BENEVENTO, dati, cartella)
    url = None

    def su_github():
        nonlocal url
        url = carica(percorso, f"gol/collaudo/{dt.datetime.now(fuso()):%Y%m%d-%H%M%S}.jpg", chiavi["github"])
        return url

    esito("immagine nel ramo e online", su_github)
    esito("Telegram (chiave del bot)", lambda: "@" + telegram.chiama(chiavi["telegram"], "getMe")["username"])
    pag = {}

    def pagina():
        pag.update(facebook.chiama("GET", "me", chiavi["facebook"], {"fields": "name,instagram_business_account{id}"}))
        if pag.get("name") != PAGINA:
            raise RuntimeError(f"la chiave è di «{pag.get('name')}»")
        return pag["name"]

    esito("Facebook (Pagina)", pagina)
    ig = (pag.get("instagram_business_account") or {}).get("id")

    def quota():
        q = (facebook.chiama("GET", f"{ig}/content_publishing_limit", chiavi["facebook"],
                             {"fields": "quota_usage,config"}).get("data") or [{}])[0]
        return f"{q.get('quota_usage')} post nelle ultime 24 ore su {(q.get('config') or {}).get('quota_total')}"

    def prepara():
        if not url:
            raise RuntimeError("manca l'immagine")
        cont = facebook.chiama("POST", f"{ig}/media", chiavi["facebook"], {"image_url": url, "caption": "collaudo"})["id"]
        for _ in range(12):
            st = facebook.chiama("GET", cont, chiavi["facebook"], {"fields": "status_code"}).get("status_code")
            if st == "FINISHED":
                return "immagine scaricata e pronta (non pubblicata)"
            if st == "ERROR":
                raise RuntimeError("Instagram non accetta l'immagine")
            time.sleep(5)
        raise RuntimeError("Instagram non ha finito di preparare l'immagine")

    if ig:
        esito("Instagram (quota)", quota)
        esito("Instagram (immagine dal ramo)", prepara)
    else:
        ok = False
        print("collaudo: Instagram: la Pagina non ha un account Instagram collegato")
    print("collaudo: tutto a posto" if ok else "collaudo: qualcosa non va (sopra)")
    return ok


# ---------------------------------------------------------------- il giro

def trova_partita(partita, noi):
    """La partita di oggi della squadra (o quella chiesta): l'id ESPN."""
    if partita:
        return partita
    giorno = dt.datetime.now(fuso()).strftime("%Y%m%d")   # senza data ESPN dà il giorno americano
    for e in leggi_json(f"{ESPN}/scoreboard?dates={giorno}").get("events") or []:
        if any(c["team"]["id"] == noi for c in e["competitions"][0]["competitors"]):
            return e["id"]
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--stato", help="il file con cosa è già uscito")
    ap.add_argument("--partita", default="", help="id ESPN (vuoto: la partita di oggi del Benevento)")
    ap.add_argument("--squadra", default=BENEVENTO, help="per le prove: la squadra «nostra»")
    ap.add_argument("--prova", metavar="CARTELLA", help="non pubblica: scrive immagini e testi nella cartella")
    ap.add_argument("--rigioca", metavar="SUMMARY", help="prova su una partita finita, minuto per minuto")
    ap.add_argument("--registrazione", metavar="DIR", help="prova sulle registrazioni del Pi")
    ap.add_argument("--fino", type=float, default=200, help="minuti al massimo (GitHub ferma il lavoro dopo 230)")
    ap.add_argument("--collaudo", metavar="CARTELLA", help="prova i canali senza pubblicare niente")
    a = ap.parse_args()
    if a.collaudo:
        os.makedirs(a.collaudo, exist_ok=True)
        chiavi = {"telegram": os.environ.get("TELEGRAM_TOKEN", "").strip(),
                  "facebook": os.environ.get("FB_PAGE_TOKEN", "").strip(), "github": os.environ.get("GH_TOKEN", "").strip()}
        sys.exit(0 if collaudo(chiavi, a.collaudo) else 1)
    noi = a.squadra
    prova = a.prova
    if prova:
        os.makedirs(prova, exist_ok=True)
    cartella_loghi = os.path.join(prova or os.path.dirname(os.path.abspath(a.stato or ".")) or ".", "loghi")
    os.makedirs(cartella_loghi, exist_ok=True)

    letture = None
    if a.rigioca:
        letture = rigioca(apri(a.rigioca))
        partita = stato_partita(letture[0][1])["id"]
    elif a.registrazione:
        partita = a.partita
        letture = registrazione(a.registrazione, partita)
        if not letture:
            sys.exit(f"gol: nessuna registrazione della partita {partita} in {a.registrazione}")
    else:
        partita = trova_partita(a.partita, noi)
        if not partita:
            print("gol: oggi la squadra non gioca (nessuna partita nel tabellone di ESPN)")
            return
    print(f"gol: partita {partita}" + (" (prova, non pubblico niente)" if prova else ""))

    try:
        calcio = leggi_json(f"{SITO}/calcio.json")
    except Exception:
        calcio = None

    stato = {}
    if a.stato and os.path.exists(a.stato):
        with open(a.stato, encoding="utf-8") as f:
            stato = json.load(f)
        if stato.get("partita") != partita:
            stato = {}
    stato["partita"] = partita
    cronista = Cronista(stato, noi)

    chiavi = {"telegram": os.environ.get("TELEGRAM_TOKEN", "").strip(), "facebook": os.environ.get("FB_PAGE_TOKEN", "").strip(),
              "github": os.environ.get("GH_TOKEN", "").strip()}
    ig = None
    if not prova:
        mancano = [k for k, v in chiavi.items() if not v]
        if mancano:
            sys.exit(f"gol: mancano le chiavi {', '.join(mancano)}: non pubblico niente")
        pag = riprova(lambda: facebook.chiama("GET", "me", chiavi["facebook"], {"fields": "name,instagram_business_account{id}"}),
                      "Facebook", True)
        if pag.get("name") != PAGINA:
            sys.exit(f"gol: la chiave non è della Pagina «{PAGINA}»: non pubblico niente")
        ig = (pag.get("instagram_business_account") or {}).get("id")

    def salva():
        if a.stato:
            os.makedirs(os.path.dirname(os.path.abspath(a.stato)), exist_ok=True)
            tmp = a.stato + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(stato, f, ensure_ascii=False, indent=1)
            os.replace(tmp, a.stato)

    def da_mandare(u):
        return [c for c in CANALI if c not in u["canali"] and (c != "instagram" or ig)]

    def invia(chiave, u, p):
        """Un'uscita sui canali dove manca: l'immagine (rifatta se il lavoro è ripartito), caricata, poi i canali."""
        u["tentativi"] = u.get("tentativi", 0) + 1
        if not u.get("url"):
            percorso = os.path.join(cartella_loghi, os.path.basename(u["nome"]))
            if not os.path.exists(percorso):
                immagine(percorso, u["tipo"], p, noi, u["dati"], cartella_loghi)
            try:
                u["url"] = carica(percorso, u["nome"], chiavi["github"])
            except Exception as e:
                print(f"  AVVISO {u['tipo']}: immagine non caricata ({e}), riprovo")
                return
        for e in manda(u["testi"], u["canali"], chiavi, u["url"], ig):
            print(f"  AVVISO {e}")

    inizio = time.time()
    problemi, letti_male, sui_canali, p = [], 0, None, None
    indice = 0
    while True:
        if letture is not None:
            if indice >= len(letture):
                break
            adesso, s = letture[indice]
            indice += 1
        else:
            adesso = dt.datetime.now(fuso())
            try:
                s = leggi_json(f"{ESPN}/summary?event={partita}")
                letti_male = 0
            except Exception as e:
                letti_male += 1
                print(f"  {adesso:%H:%M:%S} la diretta non risponde ({e})")
                if letti_male > 40:   # dieci minuti senza diretta
                    problemi.append("la diretta di ESPN non risponde da dieci minuti")
                    break
                time.sleep(OGNI)
                continue
        p = stato_partita(s)
        if p["fase"] in ("STATUS_POSTPONED", "STATUS_CANCELED", "STATUS_ABANDONED", "STATUS_SUSPENDED"):
            print(f"gol: partita {p['fase']}: niente da mandare")
            break
        if not prova and sui_canali is None and not stato.get("uscite") and p["stato"] != "pre":
            # il lavoro è ripartito senza il file: si guarda sui canali cosa è già uscito, per non rifarlo
            sui_canali = gia_sui_canali(p, chiavi, ig, adesso - dt.timedelta(hours=4))
        for chiave, tipo, dati in cronista.passo(p, adesso):
            uscita = testi(tipo, p, noi, dati, calcio)
            u = stato["uscite"].setdefault(chiave, {"canali": {}})
            u.update(tipo=tipo, testi=list(uscita), dati=dati,
                     nome=f"gol/{partita}/{chiave.replace(':', '-')}-{adesso:%H%M%S}.jpg")
            for c in (sui_canali or {}).get(chiave_testo(uscita[0]), ()):
                u["canali"].setdefault(c, "già sul canale")
            print(f"  {adesso:%H:%M:%S} {tipo}: {uscita[0].splitlines()[0]} · {dati['risultato']}")
            if prova:
                percorso = os.path.join(prova, os.path.basename(u["nome"]))
                immagine(percorso, tipo, p, noi, dati, cartella_loghi)
                with open(percorso[:-4] + ".txt", "w", encoding="utf-8") as f:
                    f.write(f"--- Telegram\n{uscita[0]}\n\n--- Facebook\n{uscita[1]}\n\n--- Instagram\n{uscita[2]}\n")
                for c in CANALI:
                    u["canali"][c] = "prova"
            salva()
        if not prova:   # quello che manca (uscite nuove o canali che non hanno risposto prima), fino a 5 volte
            for chiave, u in list(stato["uscite"].items()):
                if da_mandare(u) and u.get("tentativi", 0) < 5:
                    invia(chiave, u, p)
                    salva()
        salva()
        finale = stato["uscite"].get("finale")
        if finale and (prova or not da_mandare(finale) or finale.get("tentativi", 0) >= 5):
            print("gol: partita finita, mandato il riassunto")
            break
        if letture is None:
            if (time.time() - inizio) / 60 > a.fino:
                problemi.append(f"dopo {a.fino:.0f} minuti la partita non è ancora finita")
                break
            time.sleep(OGNI_PRIMA if p["stato"] == "pre" else OGNI)
    salva()
    if not prova:
        for chiave, u in stato["uscite"].items():
            if da_mandare(u):
                problemi.append(f"{chiave} non è uscito su {', '.join(da_mandare(u))}")
            incerti = [c for c, v in u["canali"].items() if v == "incerto"]
            if incerti:
                problemi.append(f"{chiave}: su {', '.join(incerti)} forse è uscito, da controllare")
    if problemi:
        print("AVVISO gol: " + "; ".join(problemi[-8:]), file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
