#!/usr/bin/env python3
"""I turni delle farmacie dei paesi del Sannio, zona per zona (pagina farmacie-di-turno/, strumenti/farmacie.py).

Voluti dal proprietario il 29 ott 2026 («altra cosa per gli altri comuni come facciamo?», poi «ok va bene fai così»: la
tendina «Il tuo paese» nella pagina delle farmacie e il riquadro nelle pagine dei Comuni). La fonte è l'Ordine dei
Farmacisti della Provincia di Benevento (ordinefarmacistibn.it, «Turni Farmacie»): un PDF per zona («TURNI E FERIE
ANNUALI 2026»), fatto da un foglio di calcolo, con una colonna per farmacia e le righe «inizio» e «fine» di ogni turno
settimanale, le ferie e le regole della zona («FARMACIA DI TURNO», «FARMACIA NON DI TURNO»). Escono una volta l'anno.

Come si leggono: pdftotext -layout tiene le colonne al loro posto; ogni data va alla colonna dell'«inizio» o della
«fine» più vicina nella riga dei titoli, e la colonna dice la farmacia (i nomi in alto, nello stesso ordine). Gli anni
scritti male («31/01/2006», «21/03/2025» in mezzo al 2026) si correggono con quello che fa tornare il turno di una
settimana. Poi il controllo: messi in fila, ogni turno comincia il giorno in cui finisce quello prima (o il giorno
dopo), senza buchi né sovrapposizioni. Una zona che non passa il controllo non si scrive: la pagina dice «turni non
disponibili» con il link al PDF dell'Ordine. Il telefono e il paese di ogni farmacia vengono dall'elenco di Federfarma
Benevento (strumenti/farmacie.py, leggi_elenco), abbinato per nome.

Uso:  python3 strumenti/farmacie_paesi.py [--cartella DIR]   (scarica, legge e stampa le zone: per le prove)
Lo usa strumenti/farmacie.py (zone()), sul Pi, insieme ai turni della città.
"""
import argparse
import datetime as dt
import hashlib
import html
import json
import os
import re
import subprocess
import sys
import tempfile
import urllib.request

PAGINA = "https://www.ordinefarmacistibn.it/per-il-cittadino/turni-farmacie/"
UA = "NotizieBenevento/1.0 (https://notiziebenevento.it)"
RX_DATA = re.compile(r"(?<![\d/])(\d{1,2})/(\d{1,2})/(\d{2,4})(?![\d/])")
RX_PAROLA = re.compile(r"[A-Za-zÀ-ÿ']{3,}")
# il momento del cambio di turno, dalle parole del PDF (l'ora si usa solo per sapere chi c'è «adesso» quel giorno)
CAMBI = [(re.compile(r"ALLE ORE 13[:.,]00", re.I), "13:00", "alle 13"),
         (re.compile(r"ALLE 0?8[:.,]30", re.I), "08:30", "alle 8:30"),
         (re.compile(r"CHIUSURA ANTIM\w*", re.I), "13:00", "alla chiusura del mattino"),
         (re.compile(r"CHIUSURA SERALE", re.I), "20:00", "alla chiusura della sera"),
         (re.compile(r"APERTURA ANTIM\w*", re.I), "09:00", "all'apertura del mattino")]
GIORNI = ["lunedì", "martedì", "mercoledì", "giovedì", "venerdì", "sabato", "domenica"]
GENERICHE = {"farmacia", "farmacie", "sas", "snc", "srl", "dott", "dottor", "eredi", "figli", "del", "della", "di",
             "holding", "sant", "san", "santa"}


def parole(s):
    return {w for w in re.findall(r"[a-zà-ÿ]{3,}", s.lower().replace("'", " ")) if w not in GENERICHE}


def bello(s):
    return re.sub(r"\b[A-ZÀ-Ý][A-ZÀ-Ý']+\b", lambda m: m.group(0).capitalize(), s)


def frase(s):
    """«ASSICURERA' IL SERVIZIO A BATTENTI APERTI…» → «Assicurerà il servizio a battenti aperti…» (gli accenti scritti
    con l'apostrofo tornano accenti)."""
    s = re.sub(r"\s+", " ", s).strip(" *")
    if sum(c.isupper() for c in s) > sum(c.islower() for c in s):
        s = s.lower()
    s = re.sub(r"\b(a|e|i|o|u)'(?=\s|$|[,.;:])", lambda m: {"a": "à", "e": "è", "i": "ì", "o": "ò", "u": "ù"}[m.group(1)], s)
    s = re.sub(r"(ra|rà)' ", "rà ", s)
    return s[:1].upper() + s[1:]


def leggi_pagina(testo_html):
    """Gli allegati della pagina dell'Ordine: [(id, titolo)] dei turni dei paesi (non le ferie e lo specchietto della città)."""
    out = []
    for r in re.findall(r"<tr[^>]*>(.*?)</tr>", testo_html, re.S):
        m = re.search(r'href="[^"]*download\.php\?id=(\d+)"', r)
        if not m:
            continue
        tit = re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", r))).strip()
        tit = re.sub(r"\s+\d+ KB\s+\d+$", "", tit)
        if re.search(r"turni|tabella", tit, re.I) and not re.search(r"specchietto|ferie", tit, re.I):
            out.append((m.group(1), tit))
    return out


def scarica(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.read()


def testo_pdf(dati):
    with tempfile.TemporaryDirectory() as td:
        p = os.path.join(td, "z.pdf")
        with open(p, "wb") as f:
            f.write(dati)
        r = subprocess.run(["pdftotext", "-layout", p, "-"], capture_output=True, text=True, timeout=60)
    if r.returncode != 0:
        raise ValueError(f"pdftotext non legge il PDF ({r.stderr.strip()[:150]})")
    return r.stdout


def data(testo):
    """Una data del PDF («24/10/2026», «05/01/26», anche «23-03--2026»); None se non si capisce («16/5/826», «4//26»)."""
    m = re.fullmatch(r"(\d{1,2})[/-]+(\d{1,2})[/-]+(\d{2,4})", testo)
    if not m:
        return None
    g, me, a = (int(x) for x in m.groups())
    a = a + 2000 if a < 100 else a
    try:
        return dt.date(a, me, g) if 2020 <= a <= 2035 else None
    except ValueError:
        return None


def aggiusta(d, vicino):
    """Un anno scritto male: quello (tra l'anno prima e il dopo di `vicino`) che porta la data più vicina a `vicino`."""
    if d is None or abs((d - vicino).days) <= 40:
        return d
    cand = []
    for a in (vicino.year - 1, vicino.year, vicino.year + 1):
        try:
            cand.append(d.replace(year=a))
        except ValueError:
            pass
    return min(cand, key=lambda x: abs((x - vicino).days))


RX_QUASI_DATA = re.compile(r"(?<![\d/-])\d{1,2}[/-]+\d{0,2}[/-]+\d{2,4}(?![\d/-])")
NON_COMUNI = {"sannio", "sannita", "valle", "fortore", "monte", "taburno", "terme", "fraz", "beltiglio", "galdo",
              "goti", "val", "san", "santa", "sant", "degli", "dei", "del"}


def parole_comune(c):
    return {w for w in re.findall(r"[a-zà-ÿ]{4,}", c.lower().replace("'", " ")) if w not in NON_COMUNI}


def leggi_zona(testo, comuni_noti=()):
    """Farmacie (nomi delle colonne e, se c'è, il paese della colonna), turni [(colonna, dal, al)], regole, correzioni.
    ValueError se la tabella non si legge. Le righe della tabella si leggono in ordine (riga per riga, da sinistra):
    è l'ordine dei turni, uno dopo l'altro."""
    righe = testo.splitlines()
    i_tit = next((i for i, l in enumerate(righe) if re.search(r"\binizio\b", l, re.I) and re.search(r"\bfine\b", l, re.I)), None)
    i_ferie = next((i for i, l in enumerate(righe) if re.search(r"FERIE ANNUALI", l, re.I)), 0)
    fine_testa = i_tit if i_tit is not None else next(
        (i for i, l in enumerate(righe) if re.search(r"FARMACI[AE].*(TURNO|RIMARRANNO)|SOPRAINDICATE", l, re.I)), len(righe))
    colonne = []
    if i_tit is not None:
        tit = righe[i_tit]
        colonne = [m.start() for m in re.finditer(r"\binizio\b", tit, re.I)]
    n = len(colonne)
    # i nomi delle farmacie: la prima riga dopo «FERIE ANNUALI» con n pezzi (o, senza tabella, con dei nomi) che non sia
    # quella dei paesi («CASALDUNI   PAUPISI   PONTE»): quella dice il paese di ogni colonna
    noti = [parole_comune(c) for c in comuni_noti]
    nomi, paesi = None, None
    for l in righe[:i_ferie]:   # la riga dei paesi può stare anche sopra il titolo
        pezzi = [p.strip(" ,") for p in re.split(r"\s{3,}", l.strip()) if p.strip(" ,")]
        if len(pezzi) >= 2 and (not n or len(pezzi) == n) and \
                sum(1 for p in pezzi if any(parole_comune(p) & c for c in noti if c)) >= len(pezzi) // 2 + 1:
            paesi = pezzi
    for l in righe[i_ferie + 1:fine_testa]:
        pezzi = [p.strip(" ,") for p in re.split(r"\s{3,}", l.strip()) if p.strip(" ,")]
        if not pezzi or re.search(r"\bDA\b|\bA:|\bDal\b|\bAl\b|pervenut|esonero|TURNI", l, re.I) or (n and len(pezzi) != n):
            continue
        if not all(RX_PAROLA.search(p) for p in pezzi):
            continue
        di_paesi = sum(1 for p in pezzi if any(parole_comune(p) & c for c in noti if c)) >= max(1, len(pezzi) // 2 + 1)
        if di_paesi and paesi is None:
            paesi = pezzi
            continue
        nomi = pezzi
        break
    fine_tab = len(righe) if i_tit is None else next((i for i in range(i_tit + 1, len(righe))
                     if re.search(r"FARMACI[AE].*TURNO|SOPRAINDICATE|RIMARRANNO", righe[i], re.I)), len(righe))
    if i_tit is None or not any(RX_QUASI_DATA.search(l) for l in righe[i_tit + 1:fine_tab]):
        return nomi or [], paesi, [], regole(righe[fine_testa if i_tit is None else fine_tab:]), []   # zona senza turni
    if not nomi:
        raise ValueError(f"non trovo i nomi delle {n} farmacie")
    grezzi = []   # [colonna, dal, al, testo della riga] in ordine di lettura
    for l in righe[i_tit + 1:fine_tab]:
        pezzi = [(m.start(), m.group(0)) for m in RX_QUASI_DATA.finditer(l)]
        if not pezzi:
            continue
        if len(pezzi) % 2:
            raise ValueError(f"numero dispari di date nella riga «{l.strip()}»")
        for k in range(0, len(pezzi), 2):
            x = pezzi[k][0]
            c = min(range(n), key=lambda j: abs(colonne[j] - x))
            grezzi.append([c, data(pezzi[k][1]), data(pezzi[k + 1][1]), l.strip()])
    ultimo_errore = None
    for ordine in ("lettura", "data"):   # di solito le righe sono già in fila; con le ferie di mezzo no (Airola)
        try:
            fila, correzioni = correggi([list(t) for t in grezzi], ordine)
            controlla([(c, a, b) for c, a, b, _ in fila])
            return nomi, paesi, [(c, a, b) for c, a, b, _ in fila], regole(righe[fine_tab:]), correzioni
        except ValueError as e:
            ultimo_errore = e
    # niente da fare con tutto il calendario: si tengono i turni che tornano, dall'inizio fino al primo che non torna
    # (Pago Veiano e Fragneto, 2026: da novembre le settimane sono scritte come dicembre)
    fila, (corretti, _) = [], correggi([list(t) for t in grezzi], "lettura", severo=False)
    for c, a, b, riga in corretti:
        if a is None or b is None or not 1 <= (b - a).days <= 20 or (fila and not fila[-1][2] <= a <= fila[-1][2] + dt.timedelta(days=1)):
            break
        fila.append((c, a, b))
    if len(fila) >= 4:
        raise Parziale(fila, f"{ultimo_errore}; tenuti i turni fino al {fila[-1][2]:%d/%m/%Y}")
    raise ultimo_errore


class Parziale(Exception):
    """Il calendario torna solo fino a un certo giorno: `fila` sono i turni buoni."""
    def __init__(self, fila, msg):
        super().__init__(msg)
        self.fila = fila


def correggi(grezzi, ordine, severo=True):
    """Gli anni sbagliati (con il turno prima) e poi un giorno o un mese sbagliato, che dice il turno prima o quello
    dopo, solo se l'altra data del turno torna. Restituisce (turni in fila, correzioni)."""
    for i, t in enumerate(grezzi):
        if i and ordine == "lettura" and t[1] is not None and grezzi[i - 1][2] is not None:
            t[1] = aggiusta(t[1], grezzi[i - 1][2])
        if t[2] is not None and t[1] is not None:
            t[2] = aggiusta(t[2], t[1] + dt.timedelta(days=7))
    if ordine == "data":
        if any(t[1] is None for t in grezzi):
            raise ValueError("una data d'inizio che non si capisce")
        grezzi.sort(key=lambda t: t[1])
    correzioni = []
    for i, t in enumerate(grezzi):
        prima = grezzi[i - 1][2] if i else None
        dopo = grezzi[i + 1][1] if i + 1 < len(grezzi) else None
        ok_a = prima is None or (t[1] is not None and prima <= t[1] <= prima + dt.timedelta(days=1))
        ok_b = t[1] is not None and t[2] is not None and 1 <= (t[2] - t[1]).days <= 20
        if not ok_a and prima is not None and t[2] is not None and 4 <= (t[2] - prima).days <= 16:
            correzioni.append(f"«{t[3]}»: l'inizio è {prima:%d/%m/%Y} (il giorno in cui finisce il turno prima)")
            t[1] = prima
        elif not ok_b and t[1] is not None and dopo is not None and 4 <= (dopo - t[1]).days <= 16:
            correzioni.append(f"«{t[3]}»: la fine è {dopo:%d/%m/%Y} (il giorno in cui comincia il turno dopo)")
            t[2] = dopo
        if (t[1] is None or t[2] is None) and severo:
            raise ValueError(f"una data che non si capisce nella riga «{t[3]}»")
    if len(correzioni) > 4 and severo:
        raise ValueError(f"troppe date da correggere ({len(correzioni)})")
    return grezzi, correzioni


def regole(righe):
    """Le regole della zona, con le loro parole («FARMACIA DI TURNO …», «FARMACIA NON DI TURNO …»): [(titolo, frasi)]."""
    out, cur = [], None
    for l in righe:
        s = l.strip()
        if not s:
            continue
        if re.fullmatch(r"(LA )?FARMACIA (CHE )?(NON )?(E' )?DI TURNO", s, re.I):
            cur = ("La farmacia di turno" if not re.search(r"NON", s, re.I) else "Le farmacie non di turno", [])
            out.append(cur)
            continue
        if cur is None:
            cur = ("Le farmacie della zona", [])
            out.append(cur)
        cur[1].append(s)
    return [(t, frase(" ".join(r))) for t, r in out if r]


def controlla(turni):
    """Messi in fila: nessun buco né sovrapposizione (un turno comincia il giorno in cui finisce quello prima, o il dopo)."""
    fila = list(turni)
    for (c1, a1, b1), (c2, a2, b2) in zip(fila, fila[1:]):
        if not (b1 <= a2 <= b1 + dt.timedelta(days=1)):
            raise ValueError(f"tra il turno che finisce il {b1:%d/%m/%Y} e quello che comincia il {a2:%d/%m/%Y} c'è "
                             f"{'un buco' if a2 > b1 else 'una sovrapposizione'}")
    for c, a, b in fila:
        if not 1 <= (b - a).days <= 20:
            raise ValueError(f"turno dal {a:%d/%m/%Y} al {b:%d/%m/%Y}: non torna")
    return fila


def cambio(regole_zona):
    """Quando cambia il turno: (giorno della settimana o None, ora per «adesso», parole). Dalla frase che lo dice
    («Inizierà il turno all'apertura antimeridiana del sabato…», «…dalla apertura antimeridiana del lunedì alla…»)."""
    testo = " ".join(f for _, f in regole_zona)
    m = re.search(r"inizier\S*\s+(il\s+)?(il\s+)?turno(.{0,200}?)success", testo, re.I | re.S) or \
        re.search(r"servizio\s+(dalla|dall')(.{0,200}?)success", testo, re.I | re.S)
    pezzo = m.group(m.lastindex) if m else ""
    giorni = [(m.start(), i) for i, g in enumerate(GIORNI) for m in re.finditer(rf"\b{g[:-1]}", pezzo, re.I)]
    giorno = min(giorni)[1] if giorni else None
    momenti = [(m.start(), ora, par) for rx, ora, par in CAMBI for m in rx.finditer(pezzo)]
    if momenti:
        _, ora, par = min(momenti)
        return giorno, ora, par
    return giorno, "09:00", "al mattino"


def abbina(nomi, paesi, elenco, testo_zona):
    """Ogni nome di colonna alla farmacia dell'elenco di Federfarma (nome, paese, telefono); None se non è sicuro.
    Se il PDF dice il paese della colonna, la farmacia è di quel paese (l'unica che c'è, o quella col nome giusto);
    se no, quella col nome giusto tra i paesi scritti nel PDF della zona. Mai una farmacia di un paese fuori zona
    (Airola 2026: «MAURO» è la farmacia di Moiano, non il dottor Mauro di Calvi)."""
    zona = parole_comune(testo_zona)
    out = []
    for k, n in enumerate(nomi):
        p = parole(n)
        col = parole_comune(paesi[k]) if paesi and k < len(paesi) else set()
        if col:
            qui = [f for f in elenco if parole_comune(f["comune"]) & col]
            col_nome = [f for f in qui if p & f["parole"]]
            out.append(col_nome[0] if len(col_nome) == 1 else qui[0] if len(qui) == 1 and not col_nome else None)
            continue
        cand = [f for f in elenco if p & f["parole"] and parole_comune(f["comune"]) & zona]
        punti = sorted(((len(p & f["parole"]), i) for i, f in enumerate(cand)), reverse=True)
        out.append(cand[punti[0][1]] if punti and (len(punti) == 1 or punti[0][0] > punti[1][0]) else None)
    return out


def zone(elenco, cartella=None):
    """Tutte le zone: [{"titolo", "pdf", "impronta", "farmacie", "turni", "regole", "cambio", "correzioni", "problema"}].
    `elenco`: le farmacie di tutta la provincia (strumenti/farmacie.py, leggi_elenco(tutte=True)). Una zona con
    «problema» non ha turni (la pagina rimanda al PDF)."""
    pagina = scarica(PAGINA).decode("utf-8", "replace")
    comuni = sorted({f["comune"] for f in elenco})
    out = []
    for id_, titolo in leggi_pagina(pagina):
        url = f"https://www.ordinefarmacistibn.it/wp-content/plugins/download-attachments/includes/download.php?id={id_}"
        z = {"titolo": titolo, "pdf": url, "farmacie": [], "turni": [], "regole": [], "correzioni": [], "problema": ""}
        try:
            dati = scarica(url)
            z["impronta"] = hashlib.sha256(dati).hexdigest()[:16]
            if cartella:
                with open(os.path.join(cartella, f"zona-{id_}.pdf"), "wb") as f:
                    f.write(dati)
            testo = testo_pdf(dati)
            try:
                nomi, paesi, turni, reg, corr = leggi_zona(testo, comuni)
            except Parziale as p:   # i nomi e le regole servono lo stesso: si rilegge senza la tabella
                nomi, paesi, _, reg, corr = leggi_zona(re.sub(r"\binizio\b", "inizi0", testo), comuni)
                turni, z["problema"] = p.fila, f"calendario che torna solo in parte: {p}"
                z["fino_al"] = p.fila[-1][2].isoformat()
            testa = titolo + " " + " ".join(testo.splitlines()[:6])
            z["regole"] = [{"titolo": t, "testo": f} for t, f in reg]
            z["correzioni"] = corr
            g, ora, par = cambio(reg)
            z["cambio"] = {"giorno": GIORNI[g] if g is not None else None, "ora": ora, "parole": par}
            if not turni:   # zona senza turni (il PDF dice solo come sono aperte): tutte le farmacie dei suoi paesi
                zona = parole_comune(testa)
                z["farmacie"] = [{"nome": bello(f["nome"]), "comune": f["comune"], "telefono": f["telefono"],
                                  "via_mappa": bello(f["via"])} for f in elenco if parole_comune(f["comune"]) & zona]
            else:
                farm = abbina(nomi, paesi, elenco, testa)
                if any(not f for f in farm):
                    raise ValueError("farmacie che non riconosco nell'elenco: " + ", ".join(n for n, f in zip(nomi, farm) if not f))
                z["farmacie"] = [{"nome": bello(n), "comune": f["comune"], "telefono": f["telefono"],
                                  "via_mappa": bello(f["via"])} for n, f in zip(nomi, farm)]
                fila = controlla(turni)
                z["turni"] = [{"dal": a.isoformat(), "al": b.isoformat(), "farmacia": c} for c, a, b in fila]
        except Exception as e:
            z["problema"] = f"{type(e).__name__}: {re.sub(chr(10), ' ', str(e))[:220]}"
            z["turni"] = []
        out.append(z)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cartella", help="dove salvare i PDF (per guardarli)")
    a = ap.parse_args()
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import farmacie as F
    elenco = F.leggi_elenco(F.scarica_elenco(), tutte=True)
    for z in zone(elenco, a.cartella):
        t = z["turni"]
        print(f"{z['titolo'][:70]:70} | {len(z['farmacie'])} farmacie | {len(t)} turni"
              + (f" {t[0]['dal']}→{t[-1]['al']}" if t else "") + (f" | PROBLEMA: {z['problema']}" if z["problema"] else ""))
        for f in z["farmacie"]:
            print(f"      {f['nome']:28} {f['comune']:24} {f['telefono']}")
        print(f"      cambio: {z.get('cambio')}")
        for c in z.get("correzioni") or []:
            print(f"      CORRETTO {c}")


if __name__ == "__main__":
    main()
