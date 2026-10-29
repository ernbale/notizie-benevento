#!/usr/bin/env python3
"""«Il paese in breve» nelle pagine dei Comuni → strumenti/comuni_scheda.json (html_paese_breve in pagine.py).

Voluto dal proprietario il 29 ott 2026 (prima «c da verificare voglio vedere cosa esce», poi, vista l'anteprima, «si fai
1»). Per ognuno dei 78 Comuni, da fonti ufficiali o aperte:
- ISTAT, popolazione al 1° gennaio (POSAS, la stima dell'anno): gli abitanti;
- Wikidata: altitudine e superficie;
- Wikipedia (il riquadro della voce): come si chiamano gli abitanti, patrono e giorno della festa, frazioni;
- IndicePA, l'indice delle pubbliche amministrazioni (lo aggiorna il Comune): indirizzo del municipio, CAP, PEC, sito.
  Solo gli enti «Comune di …»: con lo stesso codice ISTAT ci sono anche consorzi e unioni (29 ott 2026: per Telese e
  Benevento usciva la PEC di un consorzio);
- Ministero dell'Interno, amministratori in carica (sindaci e organi straordinari): il sindaco, con la data dell'elezione.
Il sindaco si scrive solo se l'indice e il Ministero dicono la stessa persona, o se l'elezione viene dopo l'ultimo
aggiornamento dell'indice (Calvi: eletto il 24 maggio 2026, l'indice è di aprile). Se l'indice è più nuovo e dice un'altra
cosa, la riga non esce e si stampa (Airola, 29 ott 2026: il Ministero ad agosto ha il sindaco, l'indice del 21 ottobre
un commissario prefettizio): nel dubbio niente. Se il Ministero non ha il Comune vale l'indice, senza la data.
Il telefono del municipio non c'è in nessuna di queste fonti: non si scrive.

Uso:  python3 strumenti/comuni_scheda.py   (sul Mac, a mano: dopo le elezioni comunali e una volta l'anno, quando
                                             l'ISTAT pubblica gli abitanti del 1° gennaio; guarda le righe stampate)
"""
import csv
import datetime as dt
import io
import json
import os
import re
import sys
import unicodedata
import urllib.parse
import urllib.request
import zipfile

QUI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, QUI)
from meteo import COMUNI_BN   # noqa: E402
import stemmi as ST           # noqa: E402   (chiedi, titoli_wikipedia)

FILE = os.path.join(QUI, "comuni_scheda.json")
UA = {"User-Agent": "NotizieBenevento/1.0 (https://notiziebenevento.it)"}
ISTAT = "https://demo.istat.it/data/posas/POSAS_{anno}_it_Comuni.zip"
IPA = "https://indicepa.gov.it/ipa-dati/api/3/action/datastore_search"
IPA_ENTI = "d09adf99-dc10-4349-8c53-27b1e5aa97b6"   # dataset «enti» di IndicePA
SINDACI = "https://dait.interno.gov.it/documenti/sindaciincarica.csv"
COMMISSARI = "https://dait.interno.gov.it/documenti/organistraordinariincarica.csv"
MESI = ["gennaio", "febbraio", "marzo", "aprile", "maggio", "giugno", "luglio", "agosto", "settembre", "ottobre",
        "novembre", "dicembre"]


def scarica(url, timeout=120):
    with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"}), timeout=timeout) as r:
        return r.read()


def semplice(s):
    s = unicodedata.normalize("NFKD", (s or "").lower().replace("’", "'")).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z]+", " ", s).strip()


def wikidata():
    """{nome: {"istat", "alt", "area"}} dei Comuni della provincia (codice ISTAT 062…)."""
    q = ('SELECT ?nome ?istat ?alt ?area WHERE { ?c wdt:P635 ?istat . FILTER(STRSTARTS(?istat, "062")) '
         '?c wdt:P31 wd:Q747074 . ?c rdfs:label ?nome . FILTER(LANG(?nome)="it") '
         'OPTIONAL { ?c wdt:P2044 ?alt } OPTIONAL { ?c wdt:P2046 ?area } }')
    out = {}
    for b in ST.chiedi("https://query.wikidata.org/sparql", query=q, format="json")["results"]["bindings"]:
        g = lambda k: (b.get(k) or {}).get("value")   # noqa: E731
        x = out.setdefault(g("nome"), {"istat": g("istat"), "alt": set(), "area": set()})
        for k in ("alt", "area"):
            if g(k):
                x[k].add(g(k))
    return {n: {"istat": v["istat"], "alt": sorted(v["alt"]), "area": sorted(v["area"])} for n, v in out.items()}


def wikipedia():
    """{Comune: campi del riquadro della voce su it.wikipedia}."""
    titoli, out = ST.titoli_wikipedia(), {}
    tl = list(titoli)
    for i in range(0, len(tl), 40):
        d = ST.chiedi("https://it.wikipedia.org/w/api.php", action="query", prop="revisions", rvprop="content",
                      rvslots="main", titles="|".join(tl[i:i + 40]), format="json", formatversion=2)
        for p in d["query"]["pages"]:
            txt = p["revisions"][0]["slots"]["main"]["content"]
            campi = {}
            for k in ("Patrono", "Festivo", "Nome abitanti", "Sottodivisioni"):
                m = re.search(r"\|\s*" + re.escape(k) + r"\s*=\s*([^\n]*)", txt)
                if m:
                    campi[k] = m.group(1).strip()
            out[titoli[p["title"]]] = campi
    return out


def pulisci(t):
    """Il testo di un campo di Wikipedia senza note, link, modelli, corsivi e a capo."""
    t = re.sub(r"<ref[^>]*/>|<ref.*?</ref>", "", t or "", flags=re.S)
    t = re.sub(r"\[\[(?:[^|\]]*\|)?([^\]]*)\]\]", r"\1", t)
    t = re.sub(r"\{\{.*?\}\}", "", t)
    t = re.sub(r"<br\s*/?>", "; ", t).replace("''", "")
    t = re.sub(r"<[^>]+>", "", t)
    if t.strip().startswith("|"):
        return ""
    return re.sub(r"\s+", " ", t).strip(" ,;")


def istat():
    """(anno, {codice ISTAT: abitanti al 1° gennaio}) dal file POSAS più recente."""
    for anno in (dt.date.today().year, dt.date.today().year - 1):
        try:
            z = zipfile.ZipFile(io.BytesIO(scarica(ISTAT.format(anno=anno))))
        except Exception:
            continue
        nome = next(n for n in z.namelist() if n.lower().endswith(".csv"))
        righe = z.read(nome).decode("utf-8-sig").splitlines()[1:]   # la prima riga è il titolo
        tot = {r["Codice comune"]: int(r["Totale"]) for r in csv.DictReader(righe, delimiter=";")
               if r["Codice comune"].startswith("062") and r["Età"] == "999"}
        if len(tot) >= 78:
            return anno, tot
    raise RuntimeError("ISTAT: niente popolazione dei Comuni per quest'anno né per il passato")


def indicepa():
    """{codice ISTAT: ente} dei Comuni della provincia («Comune di …» soltanto)."""
    q = urllib.parse.urlencode({"resource_id": IPA_ENTI, "filters": json.dumps({"Codice_Categoria": "L6"}),
                                "limit": 10000})
    rec = json.loads(scarica(f"{IPA}?{q}", 180))["result"]["records"]
    return {str(r["Codice_comune_ISTAT"]): r for r in rec if str(r.get("Codice_comune_ISTAT") or "").startswith("062")
            and str(r.get("Denominazione_ente") or "").lower().startswith("comune di")}


def ministero(url):
    """(data dell'elenco, {nome semplice: riga}) dei Comuni BN da un CSV degli amministratori in carica."""
    righe = scarica(url, 180).decode("utf-8", "replace").splitlines()
    data = (re.search(r"(\d{2}/\d{2}/\d{4})", righe[1]) or [None, None])[1]
    out = {}
    for r in csv.DictReader(righe[2:], delimiter=";"):
        if (r.get("sigla_provincia") or "").strip() == "BN":
            out[semplice(r["denominazione_comune"])] = {k: (v or "").strip() for k, v in r.items()}
    return data, out


def iso(d):
    """«03/10/2021» → «2021-10-03»."""
    try:
        return dt.datetime.strptime(d, "%d/%m/%Y").date().isoformat()
    except (TypeError, ValueError):
        return None


def stessa_persona(a, b):
    a, b = set(semplice(a).split()), set(semplice(b).split())
    return bool(a and b) and (a <= b or b <= a)


def sindaco(c, sin, com, data_min, ipa):
    """{"carica", "nome", "dal", "fonte"} o None (vedi la regola in testa). Stampa i casi da guardare."""
    m = sin.get(semplice(c)) or com.get(semplice(c))
    i_nome = f"{ipa.get('Nome_responsabile') or ''} {ipa.get('Cognome_responsabile') or ''}".strip()
    i_carica, i_data = (ipa.get("Titolo_responsabile") or "").strip(), str(ipa.get("Data_aggiornamento") or "")[:10]
    if m:
        nome = f"{m['nome'].title()} {m['cognome'].title()}"
        carica = m["descrizione_carica"].strip().capitalize()
        if carica == "Sindaco" and m.get("sesso") == "F":
            carica = "Sindaca"
        voce = {"carica": carica, "nome": nome, "dal": iso(m.get("data_elezione")) if carica.startswith("Sindac")
                else iso(m.get("data_entrata_in_carica")), "fonte": "ministero"}
        if not i_nome or stessa_persona(nome, i_nome) or (voce["dal"] or "") >= i_data:
            return voce
        print(f"{c}: il Ministero ({data_min}) dice {carica} {nome}, l'indice delle PA ({i_data}) {i_carica} {i_nome}: "
              "la riga del sindaco non esce, guardalo")
        return None
    if i_nome and re.match(r"sindac", i_carica, re.I):
        print(f"{c}: il Ministero ({data_min}) non lo ha; dall'indice delle PA ({i_data}): {i_carica} {i_nome}")
        return {"carica": i_carica.capitalize(), "nome": i_nome.title() if i_nome.isupper() else i_nome, "dal": None,
                "fonte": "indicepa"}
    print(f"{c}: nessun sindaco né commissario nelle fonti")
    return None


def indirizzo(s, cap, comune):
    """«PIAZZA MUNICIPIO» → «Piazza Municipio»; via il CAP e il nome del Comune in fondo («Via Roma 50 82020 CIRCELLO»)."""
    s = re.sub(r"\s+", " ", s or "").strip(" ,")
    s = re.sub(r"\s*,?\s*" + re.escape(cap or "#") + r"\b.*$", "", s) if cap else s
    s = re.sub(r"\s*,?\s*" + re.escape(comune) + r"\s*$", "", s, flags=re.I)
    piccole = {"di", "del", "della", "delle", "dei", "degli", "de", "da", "e", "in", "a"}
    parole = []
    for k, w in enumerate(s.split(" ")):
        if k and w.lower() in piccole:   # «Piazza Della Ricostruzione» → «Piazza della Ricostruzione»
            w = w.lower()
        elif w.isupper() and len(w) > 1 and not re.fullmatch(r"[IVXLC]+|S\.?N\.?C?|N\.?", w):
            w = w.capitalize()
        elif k == 0 or (w.islower() and w not in piccole and len(w) > 2):
            w = w[:1].upper() + w[1:]
        parole.append(w)
    return " ".join(parole)


def numero(x):
    try:
        v = float(str(x).replace(",", "."))
    except (TypeError, ValueError):
        return None
    return int(v) if v == int(v) else round(v, 2)


def main():
    wd, wi = wikidata(), wikipedia()
    anno, abitanti = istat()
    ipa = indicepa()
    data_sin, sin = ministero(SINDACI)
    data_com, com = ministero(COMMISSARI)
    comuni = {}
    for c in COMUNI_BN:
        w, i = wd.get(c) or {}, wi.get(c) or {}
        cod = w.get("istat")
        if not cod:
            print(f"{c}: non è su Wikidata col codice ISTAT: scheda vuota")
            continue
        p = ipa.get(cod) or {}
        if not p:
            print(f"{c}: non è nell'indice delle PA")
        fraz = pulisci(i.get("Sottodivisioni"))
        x = {"istat": cod, "abitanti": abitanti.get(cod), "altitudine": numero((w.get("alt") or [None])[0]),
             "superficie": numero((w.get("area") or [None])[0]), "nome_abitanti": pulisci(i.get("Nome abitanti")),
             "patrono": pulisci(i.get("Patrono")), "festa": pulisci(i.get("Festivo")),
             "frazioni": "" if fraz.lower() in ("nessuna", "nessuno", "-") else fraz,
             "cap": p.get("CAP") or "", "municipio": indirizzo(p.get("Indirizzo"), p.get("CAP"), c),
             "pec": next((p.get(f"Mail{k}") for k in range(1, 6) if p.get(f"Tipo_Mail{k}") == "Pec"), "") or "",
             "sito": (p.get("Sito_istituzionale") or "").strip(), "ipa_aggiornato": str(p.get("Data_aggiornamento") or "")[:10],
             "sindaco": sindaco(c, sin, com, data_sin, p)}
        comuni[c] = {k: v for k, v in x.items() if v not in (None, "")}
    dati = {"aggiornato": dt.date.today().isoformat(), "abitanti_al": f"{anno}-01-01", "ministero_al": iso(data_sin),
            "fonti": {"istat": ISTAT.format(anno=anno), "indicepa": "https://www.indicepa.gov.it/",
                      "ministero": "https://dait.interno.gov.it/elezioni/open-data/amministratori-locali-in-carica"},
            "comuni": comuni}
    with open(FILE, "w", encoding="utf-8") as f:
        json.dump(dati, f, ensure_ascii=False, indent=1)
        f.write("\n")
    pieni = {k: sum(1 for v in comuni.values() if v.get(k)) for k in ("abitanti", "altitudine", "patrono", "festa",
                                                                       "frazioni", "municipio", "pec", "sito", "sindaco")}
    print(f"comuni_scheda.json: {len(comuni)} Comuni; abitanti al 1° gennaio {anno}, sindaci del Ministero al "
          f"{data_sin}; righe piene: {pieni}")


if __name__ == "__main__":
    main()
