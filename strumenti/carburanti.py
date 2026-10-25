#!/usr/bin/env python3
"""I prezzi dei carburanti dei distributori della provincia di Benevento → carburanti.json.

Dati aperti del Ministero delle Imprese e del Made in Italy (Osservatorio prezzi carburanti, licenza IODL 2.0): ogni
mattina il Ministero pubblica l'elenco dei distributori attivi e i prezzi comunicati dai gestori (prezzo_alle_8.csv:
i prezzi in vigore alle 8 del giorno di «estrazione»). Si tengono benzina, gasolio, GPL e metano, self e servito, con
la data in cui il gestore li ha comunicati. Nelle classifiche entrano solo i prezzi self comunicati da al massimo
GIORNI_VALIDI giorni: un prezzo vecchio può non essere più quello alla pompa.

Voluto dal proprietario il 23 ott 2026: «una piccola tabellina con la classifica dei prezzi benzina e diesel» in prima
pagina (i 5 meno cari) e una pagina con tutti i distributori di Benevento e provincia.

Il sito del Ministero non risponde a chi si collega dall'estero (23 ott 2026: da GitHub «Failed to connect … after
20000 ms»), come ANAS e TV7: i prezzi li scarica il Pi di casa (cron, con --manda) e li passa alla pubblicazione su
GitHub (pubblica.yml, campo «carburanti»: il file compresso, 14 KB) con la chiave della sentinella, che può solo
avviare le pubblicazioni. Lo fa solo quando il Ministero ha dati più nuovi di quelli sul sito.

Uso:  python3 strumenti/carburanti.py [--uscita carburanti.json]               (scarica e scrive, per le prove)
      python3 carburanti.py --uscita ~/nb-fonti/carburanti.json --manda ~/nb-fonti/github.conf   (sul Pi, dal cron)
Esce con codice 1 senza scrivere niente se i file non arrivano o non tornano.
"""
import argparse
import base64
import csv
import datetime as dt
import gzip
import io
import json
import os
import re
import statistics
import subprocess
import sys
import unicodedata
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from meteo import COMUNI_BN   # noqa: E402

BASE = "https://www.mimit.gov.it/images/exportCSV/"
SITO = "https://notiziebenevento.it"
REPO = "ernbale/notizie-benevento"
UA = "NotizieBenevento/1.0 (https://notiziebenevento.it)"
CARBURANTI = {"Benzina": "benzina", "Gasolio": "gasolio", "GPL": "gpl", "Metano": "metano"}
GIORNI_VALIDI = 8
MINIMO_IMPIANTI = 100   # in provincia sono circa 175: molti meno vuol dire un file rotto


def scarica(nome):
    p = subprocess.run(["curl", "-sSfL", "--compressed", "--connect-timeout", "20", "-m", "240", "--retry", "2",
                        "--retry-all-errors", "-A", UA, BASE + nome], capture_output=True)
    if p.returncode:   # curl 28 col collegamento fermo = il sito non risponde a chi è all'estero (come ANAS e TV7)
        raise RuntimeError(f"{nome}: curl {p.returncode} {p.stderr.decode(errors='replace').strip()[:150]}")
    righe = p.stdout.decode("utf-8", "replace").splitlines()
    m = re.match(r"Estrazione del (\d{4}-\d{2}-\d{2})", righe[0] if righe else "")
    if not m:
        raise RuntimeError(f"{nome}: prima riga inattesa {righe[:1]}")
    return m.group(1), list(csv.DictReader(io.StringIO("\n".join(righe[1:])), delimiter="|"))


def chiave(s):
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z]", "", s)


COMUNE = {chiave(c): c for c in COMUNI_BN}


MESI = "Gennaio|Febbraio|Marzo|Aprile|Maggio|Giugno|Luglio|Agosto|Settembre|Ottobre|Novembre|Dicembre"


def bello(s):
    """«S.S. 7 APPIA KM 236 S/N 82011» → «S.S. 7 Appia km 236»: senza CAP, «snc», maiuscole a caso."""
    s = re.sub(r"\b\d{5}\b|\bs\.?\s?n\.?\s?c\.?(?=\s|$|,)|\bs/n\b", " ", s or "", flags=re.I)
    s = re.sub(r"\s+", " ", s).strip(" ,-")
    if s.isupper() or s.islower():
        s = " ".join(w if re.fullmatch(r"(?:[A-Z]\.){1,3}|S[SPR]\d*|\d+\w*", w) else w.capitalize() for w in s.split())
        s = re.sub(r"\b(Km|Snc)\b", lambda m: m.group(1).lower(), s)
        s = re.sub(r"\b(Di|Del|Della|Dei|Delle|De|Da|In|E|Al|Alla|Per)\b", lambda m: m.group(1).lower(), s)
        s = re.sub(r"\b([Dd]|[Ss]ant|[Ll]|[Aa]ll|[Dd]ell)'(\w)", lambda m: m.group(1) + "'" + m.group(2).upper(), s)
    s = re.sub(r"\s*-\s*\d{3,5}$", "", s)   # un CAP tagliato in fondo («Nord-Ovest - 8020»)
    return s[:1].upper() + s[1:]


def strada(s, comune=""):
    """L'indirizzo come lo scrive bello(), poi con le abbreviazioni tutte allo stesso modo («C/da» → «Contrada»,
    «S.s.372» → «SS 372», «Km. 62,046» → «km 62+046») e senza il paese ripetuto («Via Via Roma 26 , Fragneto
    Monforte (bn)» → «Via Roma 26»)."""
    s = bello(s)
    # il paese con la provincia in fondo, a volte con il numero dopo
    m = re.search(r"\s*,\s*[^,()]*\(\s*bn\s*\)\s*(\d+\w*)?$", s, flags=re.I)
    if m:
        s, civico = s[:m.start()].strip(), m.group(1)
        if civico and not s.endswith(" " + civico):
            s += " " + civico
    s = re.sub(r"\s+sn$", "", s, flags=re.I)
    s = re.sub(r"\b([A-Z])([A-Z]{3,})\b", lambda m: m.group(1) + m.group(2).lower(), s)   # «dir. PADULI»
    # il tipo di strada scritto due volte o abbreviato
    s = re.sub(r"^(?:Via|V\.)\s+(?=(?:Via|Contrada|C\s?[./]\s?da|Strada|S\.\s?S\b|SS)\b)", "", s, flags=re.I)
    s = re.sub(r"^V\.\s*", "Via ", s)
    s = re.sub(r"\b[Cc]\s?[./]\s?[Dd]a\b\.?\s*", "Contrada ", s)
    s = re.sub(r"\bLocalit[aà]'?(?=\s|$)|\bLoc\.\s*", "Località ", s)
    s = re.sub(r"\bPrvinciale\b", "Provinciale", s)
    s = re.sub(r"\bProv(?:\.le|\.)?\s+", "Provinciale ", s)
    s = re.sub(r"\bZona Ind\.?(?=\s|$)", "Zona Industriale", s)
    s = re.sub(r"\bS\.\s?sc\.\s?vel\.\s*", "Strada a scorrimento veloce ", s, flags=re.I)
    s = re.sub(r"\b([IVXivx]{2,})\s+(?=(?:" + MESI + r")\b)", lambda m: m.group(1).upper() + " ", s)
    # strade statali e provinciali: «S.S. 7», «S.s.372», «SS87», «Statale 90», «87 Sannitica» → «SS 7» …
    s = re.sub(r"\bS\.\s?S(?:\.\s*|\s+|(?=\d))", "SS ", s, flags=re.I)
    s = re.sub(r"\bS\.\s?P(?:\.\s*|\s+|(?=\d))", "SP ", s, flags=re.I)
    s = re.sub(r"\b(SS|SP)(?=\d)", r"\1 ", s)
    s = re.sub(r"\b(?:Strada\s+)?Statale\s+(?=\d|Appia\b)", "SS ", s)
    s = re.sub(r"^(\d+)\s+(Sannitica|Telesina|Appia)\b", r"SS \1 \2", s)
    s = re.sub(r"(?<=[a-z]{3})\s+(?=SS \d)", ", ", s)   # «Contrada Olivola SS 88» → «Contrada Olivola, SS 88»
    s = re.sub(r"\bS\.\s?([a-z])", lambda m: "S. " + m.group(1).upper(), s)   # «S.giovanni» → «S. Giovanni»
    # i chilometri: «Km. 62,046», «km.44+319», «km 51+ 515» → «km 62+046»
    s = re.sub(r",?\s*\b[Kk]m\.?\s*", " km ", s)
    s = re.sub(r"\bkm (\d+)\s*[.,+]\s*(\d{3})\b", r"km \1+\2", s)
    s = re.sub(r"(km \d+(?:\+\d+)?)\s+(?:\d+|S\.C\.|Dx|Sx)$", r"\1", s)
    s = re.sub(r"(km \d+(?:\+\d+)?)\s*-?\s*(?=(?:Contrada|Località|Via)\b)", r"\1, ", s)
    s = re.sub(r"(km \d+(?:\+\d+)?)\s*-\s*([a-z])", lambda m: m.group(1) + ", " + m.group(2).upper(), s)
    s = re.sub(r",?\s*\b(?:[Dd]irezione|[Dd]ir\.)\s*", ", direzione ", s)
    s = re.sub(r"(?<=[a-z])-([a-z])", lambda m: "-" + m.group(1).upper(), s)   # «Sannita-castelpagano»
    s = re.sub(r"\b(Località|Contrada|Frazione|direzione)\s+([a-z])", lambda m: m.group(1) + " " + m.group(2).upper(), s)
    s = re.sub(r"(?<=[a-z])\s+(?=(?:Località|Zona Industriale)\b)", ", ", s)
    s = re.sub(r"^(SS|SP) (\d+) (\d+)$", r"\1 \2, \3", s)   # «SP84 221»: il numero civico
    s = re.sub(r"\s*/\s+", " / ", s)
    s = re.sub(r"\s+,", ",", s)
    s = re.sub(r",(?=[^\s\d])", ", ", s)
    s = re.sub(r"\s+", " ", s).strip(" ,-")
    if comune:   # «Contrada Ciofani Benevento»; ma non «… direzione Paduli» né «SP Colle Sannita-Castelpagano»
        s = re.sub(r"(?<!direzione)(?<=\w)[\s,]+" + re.escape(comune) + "$", "", s, flags=re.I)
    return s[:1].upper() + s[1:]


# Indirizzi che il gestore ha scritto senza il tipo di strada («NAPOLI 50», senza «Via») o male, controllati uno per
# uno sulla mappa (OpenStreetMap) il 25 ott 2026, voluto dal proprietario: «Oroil deve essere via Napoli». La chiave è
# l'indirizzo come esce da strada(): se il gestore lo cambia, la correzione non vale più e resta il suo.
INDIRIZZI = {
    ("Benevento", "Napoli 50"): "Via Napoli 50",
    ("Benevento", "Delle Puglie 25"): "Via delle Puglie 25",
    ("Benevento", "Virgilio"): "Viale Virgilio",
    ("Benevento", "Nenni 17"): "Via Pietro Nenni 17",
    ("Benevento", "San Vitale"): "Contrada San Vitale",
    ("Benevento", "Bachelet"): "Via Vittorio Bachelet",
    ("Benevento", "Bissolati"): "Piazza Bissolati",
    ("Benevento", "Contrada san vito presso centro commerciale Buonvento"): "Contrada San Vito, centro commerciale Buonvento",
    ("Bonea", "Fizzo 52"): "Via Fizzo 52",
    ("Bucciano", "Provinciale 28"): "Via Provinciale 28",
    ("Calvi", "Strada Statale km 274+250, San Giorgio del Sannio"): "SS 7 Appia km 274+250",
    ("Ceppaloni", "Appia, SS 7 km 251 - San Giovanni"): "SS 7 Appia km 251, San Giovanni",
    ("Foglianise", "Silvio Pedicini"): "Via Silvio Pedicini",
    ("Foiano di Val Fortore", "Nazionale"): "Via Nazionale",
    ("Moiano", "Provinciale Moiano - Sant'Agata"): "Strada Provinciale Moiano-Sant'Agata",
    ("Montefalcone di Val Fortore", "Renato Zeppa 10"): "Via Renato Zeppa 10",
    ("Montesarchio", "Napoli 102"): "Via Napoli 102",
    ("Montesarchio", "F. Caracciolo"): "Via Francesco Caracciolo",
    ("Pago Veiano", "Vittorio Veneto 142"): "Via Vittorio Veneto 142",
    ("Paolisi", "Appia 69"): "Via Appia 69",
    ("San Giorgio del Sannio", "Alessandro Manzoni"): "Via Alessandro Manzoni",
    ("San Giorgio La Molara", "SP S. G.la Molara Pago Veiano Contrada San Marcuccio"):
        "SP San Giorgio La Molara-Pago Veiano, Contrada San Marcuccio",
    ("San Lorenzello", "Cerreto 37"): "Via Cerreto 37",   # nell'elenco c'è anche «VIA CERRETO 41»
    ("San Marco dei Cavoti", "XXV Aprile 34"): "Via XXV Aprile 34",
    ("San Nicola Manfredi", "Palati 45"): "Contrada Palati 45",
    ("Santa Croce del Sannio", "Generale de Maria"): "Corso Generale De Maria",
    ("Telese Terme", "S. Giovanni, Località Piana"): "Via San Giovanni, località Piana",
}


def indirizzo(s, comune):
    a = strada(s, comune)
    return INDIRIZZI.get((comune, a), a)


def nome_impianto(s, comune):
    """Il nome che si vede per le pompe bianche: «Goil Bonea» → «Goil», «_sudpetroli1» → «Sudpetroli»; se è solo il
    paese o comincia col paese («Benevento - Via Napoli», «Durazzano») è un'etichetta, non un nome: niente."""
    n = bello(s)
    if n.startswith("_"):
        n = re.sub(r"\d+$", "", n.lstrip("_")).capitalize()
    if not comune:
        return n
    if n.lower().startswith(comune.lower()):
        return ""
    return re.sub(r"[\s_-]*" + re.escape(comune) + "$", "", n, flags=re.I).strip()


def marchio(b, nome=""):
    """«CONAD» → «Conad»; le sigle restano (Q8, IP, API). Una bandiera fatta solo di numeri («357») è un codice: si
    prende la prima parola del nome («Rainbow_Castelvenere» → «Rainbow»)."""
    b = (b or "").strip()
    if b.lower() == "pompe bianche":
        return "Pompa bianca"
    if b.isdigit():
        return re.split(r"[_\s-]", nome.strip())[0].capitalize() if nome.strip() else "Pompa bianca"
    return b.title() if len(b) > 3 and re.fullmatch(r"[A-Z ]+", b) else b   # API-IP, ESSO-X: come sono


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--uscita", default=os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                                     "carburanti.json"))
    ap.add_argument("--manda", metavar="CHIAVE", help="file con la chiave di GitHub: passa i prezzi alla pubblicazione "
                                                     "se sono più nuovi di quelli sul sito")
    a = ap.parse_args()
    if a.manda:
        # il Ministero mette i prezzi di ieri (estrazione) una volta al giorno: se ce li abbiamo già, niente da scaricare
        try:
            with open(a.uscita, encoding="utf-8") as f:
                gia = json.load(f)
            ieri = (dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=1)).date() - dt.timedelta(days=1)
            if gia.get("estrazione", "") >= ieri.isoformat():
                return manda(gia, a.manda)
        except (OSError, ValueError):
            pass
    try:
        est_a, anag = scarica("anagrafica_impianti_attivi.csv")
        est_p, prezzi = scarica("prezzo_alle_8.csv")
    except Exception as e:
        print(f"carburanti: dati del Ministero non arrivati ({e})", file=sys.stderr)
        sys.exit(1)
    impianti = {}
    for r in anag:
        if (r.get("Provincia") or "").strip() != "BN":
            continue
        comune = COMUNE.get(chiave(r.get("Comune")), bello(r.get("Comune")))
        bandiera = (r.get("Bandiera") or "").strip()
        nome = nome_impianto(r.get("Nome Impianto"), comune)
        try:
            lat, lon = float(r["Latitudine"]), float(r["Longitudine"])
        except (KeyError, TypeError, ValueError):
            lat = lon = None
        impianti[r["idImpianto"]] = {
            "id": r["idImpianto"], "bandiera": marchio(bandiera, r.get("Nome Impianto") or ""),
            "nome": nome, "indirizzo": indirizzo(r.get("Indirizzo"), comune), "comune": comune, "lat": lat, "lon": lon,
            "prezzi": {}}
    limite = (dt.date.fromisoformat(est_p) - dt.timedelta(days=GIORNI_VALIDI)).isoformat()
    for r in prezzi:
        i, tipo = impianti.get(r.get("idImpianto")), CARBURANTI.get((r.get("descCarburante") or "").strip())
        if not i or not tipo:
            continue
        try:
            prezzo = float(r["prezzo"])
            quando = dt.datetime.strptime(r["dtComu"].strip(), "%d/%m/%Y %H:%M:%S").isoformat(timespec="minutes")
        except (KeyError, ValueError):
            continue
        if not 0.3 < prezzo < 5:   # errori di battitura dei gestori (0.001, 1999…)
            continue
        modo = "self" if r.get("isSelf") == "1" else "servito"
        p = i["prezzi"].setdefault(tipo, {})
        if modo not in p or quando > p[modo]["dt"]:   # lo stesso carburante due volte: vale l'ultimo comunicato
            p[modo] = {"prezzo": prezzo, "dt": quando, "valido": quando[:10] >= limite}
    con_prezzi = [i for i in impianti.values() if i["prezzi"]]
    if len(impianti) < MINIMO_IMPIANTI or len(con_prezzi) < MINIMO_IMPIANTI * 0.6:
        print(f"carburanti: solo {len(impianti)} impianti in provincia, {len(con_prezzi)} con prezzi: file sospetto",
              file=sys.stderr)
        sys.exit(1)
    classifiche, medie = {}, {}
    for tipo in ("benzina", "gasolio"):
        validi = [(i["prezzi"][tipo]["self"]["prezzo"], -int(i["prezzi"][tipo]["self"]["dt"].replace("-", "")[:8]), i["id"])
                  for i in con_prezzi if (i["prezzi"].get(tipo) or {}).get("self", {}).get("valido")]
        classifiche[tipo] = [x[2] for x in sorted(validi)]
        medie[tipo] = round(statistics.mean(x[0] for x in validi), 3) if validi else None
    out = {"estrazione": est_p, "anagrafica": est_a,
           "scaricato": dt.datetime.now(dt.timezone.utc).isoformat(timespec="minutes"),
           "fonte": "Ministero delle Imprese e del Made in Italy, Osservatorio prezzi carburanti (dati aperti, IODL 2.0)",
           "giorni_validi": GIORNI_VALIDI, "classifiche": classifiche, "medie_self": medie,
           "impianti": sorted(con_prezzi, key=lambda i: (i["comune"], i["bandiera"], i["indirizzo"]))}
    tmp = a.uscita + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, separators=(",", ":"))
    os.replace(tmp, a.uscita)
    print(f"carburanti: {len(con_prezzi)} distributori con prezzi su {len(impianti)} (estrazione {est_p}); "
          f"benzina self meno cara {impianti[classifiche['benzina'][0]]['prezzi']['benzina']['self']['prezzo']:.3f}, "
          f"gasolio {impianti[classifiche['gasolio'][0]]['prezzi']['gasolio']['self']['prezzo']:.3f}")
    if a.manda:
        manda(out, a.manda)


def manda(dati, chiave):
    """Fa partire la pubblicazione su GitHub coi prezzi (compressi) se sul sito ci sono quelli di un giorno prima. Non
    più di una volta ogni ora per gli stessi prezzi: se la pubblicazione non va, si riprova al giro dopo."""
    try:
        with urllib.request.urlopen(urllib.request.Request(f"{SITO}/carburanti.json", headers={"User-Agent": UA}),
                                    timeout=30) as r:
            sul_sito = json.load(r).get("estrazione", "")
    except Exception:   # il file non c'è ancora (prima volta) o il sito non risponde: si manda
        sul_sito = ""
    if sul_sito >= dati["estrazione"]:
        print(f"carburanti: sul sito ci sono già i prezzi del {sul_sito}")
        return
    stato_p = os.path.join(os.path.dirname(os.path.abspath(chiave)), "carburanti-mandati.json")
    try:
        with open(stato_p, encoding="utf-8") as f:
            stato = json.load(f)
    except (OSError, ValueError):
        stato = {}
    if stato.get("estrazione") == dati["estrazione"] and \
            dt.datetime.now(dt.timezone.utc) - dt.datetime.fromisoformat(stato["quando"]) < dt.timedelta(minutes=60):
        print(f"carburanti: prezzi del {dati['estrazione']} già mandati alle {stato['quando'][11:16]} UTC, aspetto")
        return
    with open(chiave, encoding="utf-8") as f:
        token = json.load(f)["token"].strip()
    pacco = base64.b64encode(gzip.compress(json.dumps(dati, ensure_ascii=False, separators=(",", ":")).encode(), 9)).decode()
    req = urllib.request.Request(f"https://api.github.com/repos/{REPO}/actions/workflows/pubblica.yml/dispatches",
                                 method="POST", data=json.dumps({"ref": "main", "inputs": {"carburanti": pacco}}).encode(),
                                 headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json",
                                          "X-GitHub-Api-Version": "2022-11-28", "User-Agent": "nb-carburanti"})
    with urllib.request.urlopen(req, timeout=60):
        pass
    with open(stato_p, "w", encoding="utf-8") as f:
        json.dump({"estrazione": dati["estrazione"], "quando": dt.datetime.now(dt.timezone.utc).isoformat()}, f)
    print(f"carburanti: mandati alla pubblicazione i prezzi del {dati['estrazione']} ({len(pacco)} caratteri; "
          f"sul sito erano del {sul_sito or 'mai'})")


if __name__ == "__main__":
    main()
