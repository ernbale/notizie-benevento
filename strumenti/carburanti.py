#!/usr/bin/env python3
"""I prezzi dei carburanti dei distributori della provincia di Benevento → carburanti.json.

Dati aperti del Ministero delle Imprese e del Made in Italy (Osservatorio prezzi carburanti, licenza IODL 2.0): ogni
mattina il Ministero pubblica l'elenco dei distributori attivi e i prezzi comunicati dai gestori (prezzo_alle_8.csv:
i prezzi in vigore alle 8 del giorno di «estrazione»). Si tengono benzina, gasolio, GPL e metano, self e servito, con
la data in cui il gestore li ha comunicati. Nelle classifiche entrano solo i prezzi self comunicati da al massimo
GIORNI_VALIDI giorni: un prezzo vecchio può non essere più quello alla pompa.

Voluto dal proprietario il 23 ott 2026: «una piccola tabellina con la classifica dei prezzi benzina e diesel» in prima
pagina (i 5 meno cari) e una pagina con tutti i distributori di Benevento e provincia.

Uso:  python3 strumenti/carburanti.py [--uscita carburanti.json] [--se-piu-vecchio-di ORE]
Esce con codice 1 senza scrivere niente se i file non arrivano o non tornano. Con --se-piu-vecchio-di non riscarica
se il file che c'è già (quello pubblicato, nel giro di GitHub) è stato scaricato da meno ore: il Ministero cambia i
dati una volta al giorno.
"""
import argparse
import csv
import datetime as dt
import io
import json
import os
import re
import statistics
import subprocess
import sys
import unicodedata

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from meteo import COMUNI_BN   # noqa: E402

BASE = "https://www.mimit.gov.it/images/exportCSV/"
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


def marchio(b):
    """«CONAD» → «Conad»; le sigle restano (Q8, IP, API)."""
    b = (b or "").strip()
    if b.lower() == "pompe bianche":
        return "Pompa bianca"
    return b.title() if len(b) > 3 and re.fullmatch(r"[A-Z ]+", b) else b   # API-IP, ESSO-X: come sono


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--uscita", default=os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                                     "carburanti.json"))
    ap.add_argument("--se-piu-vecchio-di", type=float, help="ore: non riscaricare se il file è più recente")
    a = ap.parse_args()
    if a.se_piu_vecchio_di:
        try:
            with open(a.uscita, encoding="utf-8") as f:
                prima = dt.datetime.fromisoformat(json.load(f)["scaricato"])
            if dt.datetime.now(dt.timezone.utc) - prima < dt.timedelta(hours=a.se_piu_vecchio_di):
                print(f"carburanti: tengo quelli scaricati alle {prima:%H:%M} UTC")
                return
        except (OSError, ValueError, KeyError, TypeError):
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
        nome = bello(r.get("Nome Impianto"))
        try:
            lat, lon = float(r["Latitudine"]), float(r["Longitudine"])
        except (KeyError, TypeError, ValueError):
            lat = lon = None
        impianti[r["idImpianto"]] = {
            "id": r["idImpianto"], "bandiera": marchio(bandiera),
            "nome": nome, "indirizzo": bello(r.get("Indirizzo")), "comune": comune, "lat": lat, "lon": lon,
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


if __name__ == "__main__":
    main()
