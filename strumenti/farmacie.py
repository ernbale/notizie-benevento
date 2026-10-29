#!/usr/bin/env python3
"""Le farmacie di turno di Benevento città → farmacie.json (pagina farmacie-di-turno/, strumenti/pagine.py).

Voluta dal proprietario il 29 ott 2026, la prima delle pagine di Servizi (lui: «facciamo 2 3 e 4 pero 1 per volta
partiamo dalla 2», «pianifica bene ogni cosa non ti deve sfuggire nulla»). La fonte è il PDF che Federfarma Benevento
mette ogni mese su federfarmabenevento.it/turni.html («Turni Farmacie Città Benevento», di solito verso il 26 per il
mese dopo): il servizio diurno a settimane e il notturno a gruppi di giorni, con gli orari e le note dell'ASL. Copre
solo la città: i paesi hanno turni per zona che online non ci sono.

Il telefono (lui, 29 ott 2026: «metti il numero di telefono è utile») viene dall'elenco delle farmacie della stessa
Federfarma (federfarmabenevento.it/farmacie.html): ogni farmacia dei turni si abbina a una di Benevento dell'elenco
per nome (titolare o ragione sociale) e via; il numero si scrive solo se l'abbinamento è sicuro (una sola farmacia
con quel nome). Dell'elenco si tengono solo telefono e indirizzo col numero civico (per la mappa), non i titolari.

Il PDF si legge con pdftotext -layout. Un turno si scrive solo se il controllo passa: ogni giorno ha un turno diurno e
uno notturno, senza buchi né sovrapposizioni, e il mese del titolo è coperto tutto. Se il PDF non si apre o non torna
resta il file di prima (e il Pi scrive l'errore in farmacie-errore.json: lo legge la sentinella). I turni del PDF di
prima restano per i giorni che il nuovo non copre, così al cambio del mese non c'è un buco. Orari e note si prendono
dal PDF con le loro parole: una nota che non si trova più non si scrive.

Come i carburanti, lo scarica il Pi di casa (cron, con --manda) e lo passa alla pubblicazione su GitHub (pubblica.yml,
campo «farmacie»), quando i turni sono diversi da quelli sul sito (anche se sul sito il file non c'è più).

Uso:  python3 strumenti/farmacie.py [--uscita farmacie.json] [--pdf turni.pdf] [--oggi AAAA-MM-GG]   (per le prove)
      python3 farmacie.py --uscita ~/nb-fonti/farmacie.json --manda ~/nb-fonti/github.conf      (sul Pi, dal cron)
Esce con codice 1 senza scrivere niente se il PDF non arriva o non torna.
"""
import argparse
import base64
import datetime as dt
import email.utils
import gzip
import hashlib
import html
import json
import os
import re
import subprocess
import sys
import tempfile
import urllib.request

SITO = "https://notiziebenevento.it"
REPO = "ernbale/notizie-benevento"
UA = "NotizieBenevento/1.0 (https://notiziebenevento.it)"
PAGINA_FONTE = "https://www.federfarmabenevento.it/turni.html"
PDF = "https://www.federfarmabenevento.it/turni/turni%20farmacie.pdf"
ELENCO = "https://www.federfarmabenevento.it/farmacie.html"
GENERICHE = {"farmacia", "farmacie", "sas", "snc", "srl", "dott", "dottor", "dottssa", "figli", "del", "della", "di",
             "via", "viale", "corso", "piazza", "rione"}
RX_TELEFONO = re.compile(r"^(0\d{5,10}|3\d{8,9})$")
MESI = {"gen": 1, "feb": 2, "mar": 3, "apr": 4, "mag": 5, "giu": 6, "lug": 7, "ago": 8, "set": 9, "ott": 10, "nov": 11,
        "dic": 12}
MESI_LUNGHI = ["gennaio", "febbraio", "marzo", "aprile", "maggio", "giugno", "luglio", "agosto", "settembre", "ottobre",
               "novembre", "dicembre"]
GIORNI_TENUTI = 3          # i turni già finiti si tengono ancora per qualche giorno (la notte tra ieri e oggi)
TURNO_MAX = 10             # giorni: un turno più lungo è un errore di lettura
RX_RIGA = re.compile(r"^\s*(\d{1,2})\s+([a-z]{3})\s+(\d{1,2})\s+([a-z]{3})\s+(\S.*?)\s*$", re.I)
RX_VIA = re.compile(r"\b(Via|Viale|V\.le|Corso|C\.so|Piazza|P\.zza|Piazzetta|Largo|Contrada|C\.da|Vico|Strada|Stazione|"
                    r"Rione|Traversa|Rampa)\b")
RX_TITOLO = re.compile(r"Turni\s+Farmacie.*?\n\s*([A-Za-z]+)\s+(\d{4})", re.S | re.I)


def bello(s):
    """Le parole TUTTE MAIUSCOLE del PDF con l'iniziale maiuscola («ABBATIELLO» → «Abbatiello»); le sigle corte
    (SNC, SAS, SRL) come «Snc»."""
    return re.sub(r"\b[A-ZÀ-Ý][A-ZÀ-Ý']+\b", lambda m: m.group(0).capitalize(), s)


def farmacia(testo):
    """«ABBATIELLO Via F.lli Rosselli - rione PACEVECCHIA» → nome e indirizzo."""
    testo = re.sub(r"\s+", " ", testo).strip()
    m = RX_VIA.search(testo)
    nome, via = (testo[:m.start()], testo[m.start():]) if m and m.start() > 0 else (testo, "")
    return {"nome": bello(nome.strip(" -,")), "indirizzo": bello(via.strip(" -,")).replace(" - ", ", ")}


def data_del(g, mese, anno_titolo, mese_titolo):
    """Il giorno «25 ott» nel PDF di «Novembre 2026»: l'anno è quello che lo mette più vicino al mese del titolo."""
    m = MESI[mese.lower()]
    cand = [dt.date(a, m, int(g)) for a in (anno_titolo - 1, anno_titolo, anno_titolo + 1)]
    rif = dt.date(anno_titolo, mese_titolo, 15)
    return min(cand, key=lambda d: abs((d - rif).days))


def leggi_pdf(dati):
    """Il testo del PDF, con le colonne al loro posto (pdftotext -layout)."""
    with tempfile.TemporaryDirectory() as td:
        p = os.path.join(td, "turni.pdf")
        with open(p, "wb") as f:
            f.write(dati)
        r = subprocess.run(["pdftotext", "-layout", p, "-"], capture_output=True, text=True, timeout=60)
    if r.returncode != 0:
        raise ValueError(f"pdftotext non legge il PDF ({r.stderr.strip()[:200]})")
    return r.stdout


def leggi_turni(testo):
    """Turni, orari e note dal testo del PDF. ValueError se qualcosa non torna (non si scrive niente)."""
    t = RX_TITOLO.search(testo)
    nomi_mesi = {n: i + 1 for i, n in enumerate(MESI_LUNGHI)}
    if not t or t.group(1).lower() not in nomi_mesi:
        raise ValueError("non trovo il mese nel titolo («Turni Farmacie Città Benevento», «Novembre 2026»)")
    mese_t, anno_t = nomi_mesi[t.group(1).lower()], int(t.group(2))
    i_d, i_n, i_o = testo.find("SERVIZIO DIURNO"), testo.find("SERVIZIO NOTTURNO"), testo.find("ORARI")
    if not 0 <= i_d < i_n < i_o:
        raise ValueError("non trovo le parti «SERVIZIO DIURNO», «SERVIZIO NOTTURNO» e «ORARI»")
    out = {"mese": f"{anno_t}-{mese_t:02d}"}
    for chiave, pezzo in (("diurno", testo[i_d:i_n]), ("notturno", testo[i_n:i_o])):
        turni = []
        for riga in pezzo.splitlines():
            m = RX_RIGA.match(riga)
            if not m:
                continue
            if m.group(2).lower() not in MESI or m.group(4).lower() not in MESI:
                raise ValueError(f"mese che non conosco nella riga «{riga.strip()}»")
            dal = data_del(m.group(1), m.group(2), anno_t, mese_t)
            al = data_del(m.group(3), m.group(4), anno_t, mese_t)
            f = farmacia(m.group(5))
            if not f["nome"]:
                raise ValueError(f"farmacia senza nome nella riga «{riga.strip()}»")
            turni.append({"dal": dal.isoformat(), "al": al.isoformat(), **f})
        controlla(turni, chiave, anno_t, mese_t)
        out[chiave] = turni
    out.update(orari_e_note(testo[i_o:]))
    return out


def controlla(turni, chiave, anno, mese):
    if len(turni) < 3:
        raise ValueError(f"servizio {chiave}: solo {len(turni)} turni")
    for a, b in zip(turni, turni[1:]):
        if dt.date.fromisoformat(b["dal"]) != dt.date.fromisoformat(a["al"]) + dt.timedelta(days=1):
            raise ValueError(f"servizio {chiave}: tra il turno che finisce il {a['al']} e quello che comincia il "
                             f"{b['dal']} c'è un buco o una sovrapposizione")
    for x in turni:
        d = (dt.date.fromisoformat(x["al"]) - dt.date.fromisoformat(x["dal"])).days
        if not 0 <= d < TURNO_MAX:
            raise ValueError(f"servizio {chiave}: il turno dal {x['dal']} al {x['al']} non torna")
    primo = dt.date(anno, mese, 1)
    ultimo = (primo + dt.timedelta(days=32)).replace(day=1) - dt.timedelta(days=1)
    if turni[0]["dal"] > primo.isoformat() or turni[-1]["al"] < ultimo.isoformat():
        raise ValueError(f"servizio {chiave}: i turni vanno dal {turni[0]['dal']} al {turni[-1]['al']}, non coprono "
                         f"tutto il mese del titolo")


def _ora(s):
    return s.replace(".", ":").zfill(5)


def orari_e_note(testo):
    """Gli orari e le note in fondo al PDF, solo quelli che si riconoscono (le parole sono le loro)."""
    piatto = re.sub(r"\s+", " ", testo)
    out = {"orari": {}, "note": {}}
    m = re.search(r"Venerd[iì]\s*(\d{1,2}[:.]\d\d)\s*[-–]\s*(\d{1,2}[:.]\d\d)\s+(\d{1,2}[:.]\d\d)\s*[-–]\s*(\d{1,2}[:.]\d\d)",
                  testo)
    if m:
        out["orari"]["feriali"] = [[_ora(m.group(1)), _ora(m.group(2))], [_ora(m.group(3)), _ora(m.group(4))]]
    m = re.search(r"Sabato\s+(\d{1,2}[:.]\d\d)\s*[-–]\s*(\d{1,2}[:.]\d\d)", testo)
    if m:
        out["orari"]["sabato"] = [[_ora(m.group(1)), _ora(m.group(2))]]
    m = re.search(r"LE FARMACIE (.+?) giorni feriali\s*:\s*(\d{1,2}[:.]\d\d)\s*[-–]\s*(\d{1,2}[:.]\d\d)", piatto, re.I)
    if m:
        out["note"]["continuato"] = {"farmacie": bello(m.group(1).strip()), "dalle": _ora(m.group(2)),
                                     "alle": _ora(m.group(3))}
    m = re.search(r"LE FARMACIE ((?:(?!LE FARMACIE).)+?) sono APERTE il SABATO POMERIGGIO", piatto, re.I)
    if m:
        out["note"]["sabato_pomeriggio"] = bello(m.group(1).strip())
    m = re.search(r"TURNO NOTTURNO DECORRE DALLA CHIUSURA POMERIDIANA \(ORE (\d{1,2}[,.:]\d\d)\).*?FINO ALLA? "
                  r"APERTURA ANTIMERIDIANA DEL GIORNO SUCCESSIVO \(ORE (\d{1,2}[,.:]\d\d)\)", piatto, re.I)
    if m:
        out["note"]["notte"] = {"dalle": _ora(m.group(1).replace(",", ":")), "alle": _ora(m.group(2).replace(",", ":"))}
    m = re.search(r"CHIAMATA NOTTURNA\s*€\s*(\d+[,.]\d\d)", piatto, re.I)
    if m and re.search(r"ricetta medica recante la dicitura", piatto, re.I):
        out["note"]["chiamata"] = m.group(1).replace(".", ",")
    return out


def leggi_elenco(testo_html, tutte=False):
    """Le farmacie di Benevento città dell'elenco di Federfarma (con tutte=True quelle di tutta la provincia, per i
    paesi: strumenti/farmacie_paesi.py): [{"parole", "via", "comune", "telefono"}] (senza i titolari)."""
    out = []
    for tr in re.findall(r"<tr\b.*?</tr>", testo_html, re.S | re.I):
        celle = [re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", c))).strip()
                 for c in re.findall(r"<td\b.*?</td>", tr, re.S | re.I)]
        if len(celle) < 6 or (celle[4].upper() != "BENEVENTO" and not tutte) or not celle[4].strip():
            continue
        tel = re.sub(r"\D", "", celle[5])
        if not RX_TELEFONO.match(tel):
            if not tutte:
                continue
            tel = ""   # per i paesi la farmacia serve lo stesso (si abbina ai turni), senza numero
        # «nome» è la ragione sociale («FARMACIA PACEVECCHIA SRL»), vuota se c'è solo il titolare: il titolare non si
        # pubblica (serve solo ad abbinare, in «parole»)
        ragione = celle[2].strip(" .-")
        tit = set(re.findall(r"[a-zà-ÿ]{2,}", celle[1].lower()))
        if tit and tit <= set(re.findall(r"[a-zà-ÿ]{2,}", ragione.lower())):   # «DOTT. LOMBARDI GIUSEPPE»: è il titolare
            ragione = ""
        out.append({"nome": ragione, "parole": parole(celle[1] + " " + celle[2]), "via": celle[3], "parole_via": parole(celle[3]),
                    "comune": bello(re.sub(r"\s+", " ", celle[4]).strip()), "telefono": tel})
    if len(out) < (60 if tutte else 8):
        raise ValueError(f"nell'elenco delle farmacie ci sono solo {len(out)} farmacie di Benevento con il telefono")
    return out


def parole(s):
    return {w for w in re.findall(r"[a-zà-ÿ]{3,}", s.lower()) if w not in GENERICHE}


def abbina(turni, elenco):
    """Telefono e via col civico dall'elenco, a ogni turno che si riconosce senza dubbi. Restituisce i nomi non trovati."""
    mancano = set()
    for k in ("diurno", "notturno"):
        for x in turni[k]:
            nome, via = parole(x["nome"]), parole(x["indirizzo"])
            punti = sorted(((2 * len(nome & f["parole"]) + len(via & f["parole_via"]), i) for i, f in enumerate(elenco)),
                           reverse=True)
            if punti and punti[0][0] >= 2 and nome & elenco[punti[0][1]]["parole"] and \
                    (len(punti) == 1 or punti[0][0] > punti[1][0]):
                f = elenco[punti[0][1]]
                x["telefono"], x["via_mappa"] = f["telefono"], bello(f["via"])
            else:
                mancano.add(x["nome"])
    return sorted(mancano)


def unisci(nuovi, vecchi, oggi):
    """I turni del PDF nuovo e, per i giorni prima del suo inizio, quelli del file di prima (non più vecchi di
    GIORNI_TENUTI giorni)."""
    limite = (oggi - dt.timedelta(days=GIORNI_TENUTI)).isoformat()
    out = dict(nuovi)
    for chiave in ("diurno", "notturno"):
        inizio = nuovi[chiave][0]["dal"]
        prima = []
        for x in (vecchi or {}).get(chiave) or []:
            if x["dal"] >= inizio or x["al"] < limite:
                continue
            if x["al"] >= inizio:   # a cavallo: si taglia al giorno prima del PDF nuovo
                x = dict(x, al=(dt.date.fromisoformat(inizio) - dt.timedelta(days=1)).isoformat())
            prima.append(x)
        out[chiave] = prima + nuovi[chiave]   # quelli del PDF tutti: così la firma cambia solo se cambia il PDF
    return out


def firma(d):
    """Quello che conta per sapere se sul sito c'è già lo stesso: turni, orari, note e i paesi."""
    pezzi = {k: d.get(k) for k in ("diurno", "notturno", "orari", "note", "paesi")}
    return hashlib.sha256(json.dumps(pezzi, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:16]


def paesi(elenco_html, vecchi, oggi, chiave=None):
    """I turni dei paesi, zona per zona (strumenti/farmacie_paesi.py), e le farmacie di tutta la provincia col
    telefono. Se l'Ordine o l'elenco non rispondono, quelli di prima. Sul Pi (chiave) avvisa il proprietario solo degli
    errori importanti, una volta per file (lui, 29 ott 2026: «quando errore è importante», «piccoli errori lasciamo
    correre»): una zona che non si legge o che torna solo in parte; le date ricostruite no."""
    try:
        import farmacie_paesi as FP
        tutte = leggi_elenco(elenco_html or scarica_elenco(), tutte=True)
        limite = (oggi - dt.timedelta(days=21)).isoformat()
        zone = []
        for z in FP.zone(tutte):
            zone.append({k: z.get(k) for k in ("titolo", "pdf", "impronta", "farmacie", "regole", "cambio", "problema", "fino_al", "nota")}
                        | {"turni": [t for t in z.get("turni") or [] if t["al"] >= limite]})
        out = {"fonte": {"nome": "Ordine dei Farmacisti della Provincia di Benevento", "pagina": FP.PAGINA},
               "zone": zone, "elenco": [{k: f[k] for k in ("nome", "comune", "telefono", "via")} for f in tutte]}
    except Exception as e:
        print(f"farmacie: turni dei paesi non letti ({type(e).__name__}: {str(e)[:200]}): restano quelli di prima",
              file=sys.stderr)
        return vecchi.get("paesi") or {}
    gravi = [z for z in out["zone"] if z.get("problema")]
    # un calendario che finisce entro 3 giorni (a gennaio, finché l'Ordine non mette quelli dell'anno nuovo)
    presto = (oggi + dt.timedelta(days=3)).isoformat()
    for z in out["zone"]:
        if z.get("turni") and not z.get("problema") and z["turni"][-1]["al"] <= presto:
            gravi.append(dict(z, impronta=f"{z.get('impronta')}:fine", problema=f"il calendario finisce il "
                              f"{dt.date.fromisoformat(z['turni'][-1]['al']):%d/%m/%Y} e l'Ordine non ha ancora messo quello nuovo"))
    for z in gravi:
        print(f"farmacie: zona «{z['titolo']}»: {z['problema']}", file=sys.stderr)
    if chiave and gravi:
        avvisa(gravi, os.path.join(os.path.dirname(os.path.abspath(chiave)), "farmacie-avvisate.json"))
    return out


def avvisa(gravi, stato_p):
    """WhatsApp ed email al proprietario (sentinella.manda_a_casa) per le zone nuove con un errore importante."""
    try:
        with open(stato_p, encoding="utf-8") as f:
            visti = json.load(f)
    except (OSError, ValueError):
        visti = {}
    nuove = [z for z in gravi if z.get("impronta") and z["impronta"] not in visti]
    if not nuove:
        return
    try:
        from sentinella import manda_a_casa
        testo = ("⚠️ Notizie Benevento, farmacie dei paesi: nel calendario dell'Ordine dei Farmacisti c'è un errore "
                 "importante.\n" + "\n".join(f"• {z['titolo']}: {z['problema']}" for z in nuove)
                 + "\nSul sito restano solo i turni che tornano; per gli altri giorni la pagina dice di chiamare la farmacia.")
        esiti = manda_a_casa(testo, "⚠️ Notizie Benevento: calendario delle farmacie da controllare")
        print("farmacie: avviso", ", ".join(esiti))
        if not any("mandat" in x and "NON" not in x for x in esiti):   # non è partito niente: si riprova al giro dopo
            return
    except Exception as e:
        print(f"farmacie: avviso non mandato ({type(e).__name__}: {e})", file=sys.stderr)
        return
    visti.update({z["impronta"]: dt.datetime.now(dt.timezone.utc).isoformat(timespec="minutes") for z in nuove})
    with open(stato_p, "w", encoding="utf-8") as f:
        json.dump(visti, f, ensure_ascii=False)


def scarica_elenco():
    req = urllib.request.Request(ELENCO, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.read().decode("utf-8", "replace")


def scarica():
    req = urllib.request.Request(PDF, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=60) as r:
        dati = r.read()
        modificato = r.headers.get("Last-Modified")
    if not dati.startswith(b"%PDF"):
        raise ValueError("quello che arriva non è un PDF")
    quando = email.utils.parsedate_to_datetime(modificato).astimezone(dt.timezone.utc).isoformat(timespec="minutes") \
        if modificato else None
    return dati, quando


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--uscita", default="farmacie.json")
    ap.add_argument("--pdf", help="un PDF già scaricato (per le prove)")
    ap.add_argument("--oggi", help="AAAA-MM-GG (per le prove)")
    ap.add_argument("--manda", help="la chiave della sentinella (github.conf): manda i turni alla pubblicazione")
    a = ap.parse_args()
    oggi = dt.date.fromisoformat(a.oggi) if a.oggi else dt.datetime.now().date()
    errore_p = os.path.join(os.path.dirname(os.path.abspath(a.uscita)), "farmacie-errore.json")
    try:
        if a.pdf:
            with open(a.pdf, "rb") as f:
                dati, modificato = f.read(), None
        else:
            dati, modificato = scarica()
        nuovi = leggi_turni(leggi_pdf(dati))
    except Exception as e:
        msg = f"{type(e).__name__}: {re.sub(r'\s+', ' ', str(e))[:300]}"
        print(f"farmacie: PDF dei turni non letto ({msg}): resta il file di prima", file=sys.stderr)
        if a.manda:   # per la sentinella del Pi
            with open(errore_p, "w", encoding="utf-8") as f:
                json.dump({"quando": dt.datetime.now(dt.timezone.utc).isoformat(timespec="minutes"), "errore": msg}, f,
                          ensure_ascii=False)
        sys.exit(1)
    try:
        with open(a.uscita, encoding="utf-8") as f:
            vecchi = json.load(f)
    except (OSError, ValueError):
        vecchi = {}
    elenco_html = None
    try:   # i telefoni: se l'elenco non si apre, quelli del file di prima (per nome)
        elenco_html = scarica_elenco()
        mancano = abbina(nuovi, leggi_elenco(elenco_html))
    except Exception as e:
        print(f"farmacie: elenco con i telefoni non letto ({type(e).__name__}: {str(e)[:200]}): uso quelli di prima",
              file=sys.stderr)
        prima = {x["nome"]: x for k in ("diurno", "notturno") for x in vecchi.get(k) or [] if x.get("telefono")}
        for k in ("diurno", "notturno"):
            for x in nuovi[k]:
                if x["nome"] in prima:
                    x["telefono"], x["via_mappa"] = prima[x["nome"]]["telefono"], prima[x["nome"]].get("via_mappa", "")
        mancano = sorted({x["nome"] for k in ("diurno", "notturno") for x in nuovi[k] if not x.get("telefono")})
    if mancano:
        print(f"farmacie: senza telefono (non le riconosco nell'elenco): {', '.join(mancano)}", file=sys.stderr)
    out = unisci(nuovi, vecchi, oggi)
    out = {"aggiornato": dt.datetime.now(dt.timezone.utc).isoformat(timespec="minutes"),
           "fonte": {"nome": "Federfarma Benevento", "pagina": PAGINA_FONTE, "pdf": PDF, "elenco": ELENCO,
                     "modificato": modificato or (vecchi.get("fonte") or {}).get("modificato")},
           **out}
    out["paesi"] = paesi(elenco_html, vecchi, oggi, a.manda)
    out["firma"] = firma(out)
    tmp = a.uscita + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    os.replace(tmp, a.uscita)
    if os.path.exists(errore_p):
        os.remove(errore_p)
    d0, n0 = out["diurno"], out["notturno"]
    print(f"farmacie: turni di {out['mese']} letti; diurni dal {d0[0]['dal']} al {d0[-1]['al']}, notturni dal "
          f"{n0[0]['dal']} al {n0[-1]['al']} (firma {out['firma']})")
    if a.manda:
        manda(out, a.manda)


def manda(dati, chiave):
    """Fa partire la pubblicazione su GitHub coi turni (compressi) se sul sito non ci sono questi. Non più di una volta
    ogni ora per gli stessi turni: se la pubblicazione non va, si riprova al giro dopo."""
    try:
        with urllib.request.urlopen(urllib.request.Request(f"{SITO}/farmacie.json", headers={"User-Agent": UA}),
                                    timeout=30) as r:
            sul_sito = json.load(r).get("firma", "")
    except Exception:   # il file non c'è ancora (prima volta) o il sito non risponde: si manda
        sul_sito = ""
    if sul_sito == dati["firma"]:
        print("farmacie: sul sito ci sono già questi turni")
        return
    stato_p = os.path.join(os.path.dirname(os.path.abspath(chiave)), "farmacie-mandati.json")
    try:
        with open(stato_p, encoding="utf-8") as f:
            stato = json.load(f)
    except (OSError, ValueError):
        stato = {}
    if stato.get("firma") == dati["firma"] and \
            dt.datetime.now(dt.timezone.utc) - dt.datetime.fromisoformat(stato["quando"]) < dt.timedelta(minutes=60):
        print(f"farmacie: turni già mandati alle {stato['quando'][11:16]} UTC, aspetto")
        return
    with open(chiave, encoding="utf-8") as f:
        token = json.load(f)["token"].strip()
    pacco = base64.b64encode(gzip.compress(json.dumps(dati, ensure_ascii=False, separators=(",", ":")).encode(), 9)).decode()
    req = urllib.request.Request(f"https://api.github.com/repos/{REPO}/actions/workflows/pubblica.yml/dispatches",
                                 method="POST", data=json.dumps({"ref": "main", "inputs": {"farmacie": pacco}}).encode(),
                                 headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json",
                                          "X-GitHub-Api-Version": "2022-11-28", "User-Agent": "nb-farmacie"})
    with urllib.request.urlopen(req, timeout=60):
        pass
    with open(stato_p, "w", encoding="utf-8") as f:
        json.dump({"firma": dati["firma"], "quando": dt.datetime.now(dt.timezone.utc).isoformat()}, f)
    prima = "erano altri" if sul_sito else "non c'erano"
    print(f"farmacie: mandati alla pubblicazione i turni (firma {dati['firma']}, {len(pacco)} caratteri; sul sito {prima})")


if __name__ == "__main__":
    main()
