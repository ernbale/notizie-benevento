#!/usr/bin/env python3
"""Il meteo di ogni Comune del Sannio → meteo-comuni.json (il riquadro «Meteo» nelle pagine dei Comuni).

Voluto dal proprietario il 29 ott 2026 («nelle pagine dei comuni lo metterei in una colonna di destra simile alla nostra
home… meteo e farmacia sempre nella colonna di destra», «meteo del comune si intende»). Benevento ha la sua pagina con
8 modelli (strumenti/meteo.py → meteo.json); per i 78 Comuni basta una previsione sola: Open-Meteo, il modello che
sceglie lui per quel punto («best match»), con una richiesta per tutti insieme (le coordinate sono in
strumenti/comuni_coordinate.json, prese il 29 ott 2026 dal geocoding di Open-Meteo, tutte in provincia di Benevento).
Per ogni Comune: adesso (temperatura, tempo, giorno o notte) e oggi, domani e dopodomani (massima, minima, tempo,
probabilità di pioggia). Lo esegue GitHub a ogni pubblicazione, dopo meteo.py; se non risponde resta quello di prima.

Uso:  python3 strumenti/meteo_comuni.py [--uscita meteo-comuni.json]
Esce con codice 1 senza scrivere niente se i dati non arrivano o non tornano.
"""
import argparse
import datetime as dt
import json
import os
import sys
import urllib.parse
import urllib.request

QUI = os.path.dirname(os.path.abspath(__file__))
UA = "NotizieBenevento/1.0 (https://notiziebenevento.it)"
FUSO = "Europe/Rome"


def condizione(codice, prob=None):
    """Il codice WMO del tempo → le condizioni della pagina Meteo (COND e icona() in index.html)."""
    c = int(codice or 0)
    if c >= 95:
        return "temporale"
    if c in (71, 73, 75, 77, 85, 86):
        return "neve"
    if c in (65, 67, 82):
        return "pioggia-forte"
    if c in (63, 81, 66):
        return "pioggia"
    if c in (51, 53, 55, 56, 57, 61, 80):
        return "pioggia-debole"
    if c in (45, 48):
        return "nebbia"
    if prob is not None and prob >= 40:
        return "possibili-piogge"
    return {0: "sereno", 1: "poco-nuvoloso", 2: "nuvoloso"}.get(c, "coperto")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--uscita", default=os.path.join(os.path.dirname(QUI), "meteo-comuni.json"))
    a = ap.parse_args()
    with open(os.path.join(QUI, "comuni_coordinate.json"), encoding="utf-8") as f:
        comuni = json.load(f)
    chiavi = list(comuni)
    q = urllib.parse.urlencode({
        "latitude": ",".join(str(comuni[k]["lat"]) for k in chiavi),
        "longitude": ",".join(str(comuni[k]["lon"]) for k in chiavi),
        "current": "temperature_2m,weather_code,is_day",
        "daily": "weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max",
        "timezone": FUSO, "forecast_days": 3})
    req = urllib.request.Request("https://api.open-meteo.com/v1/forecast?" + q, headers={"User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            dati = json.load(r)
    except Exception as e:
        print(f"ERRORE: Open-Meteo non risponde ({type(e).__name__}: {e})", file=sys.stderr)
        sys.exit(1)
    if isinstance(dati, dict):
        dati = [dati]
    if len(dati) != len(chiavi):
        print(f"ERRORE: {len(dati)} risposte per {len(chiavi)} Comuni", file=sys.stderr)
        sys.exit(1)
    out = {}
    for k, d in zip(chiavi, dati):
        c, g = d.get("current") or {}, d.get("daily") or {}
        try:
            giorni = [{"data": g["time"][i], "max": g["temperature_2m_max"][i], "min": g["temperature_2m_min"][i],
                       "cond": condizione(g["weather_code"][i], g["precipitation_probability_max"][i]),
                       "prob": g["precipitation_probability_max"][i]} for i in range(len(g["time"]))]
            ora = {"t": c["temperature_2m"], "cond": condizione(c["weather_code"]), "giorno": c["is_day"], "quando": c["time"]}
        except (KeyError, IndexError, TypeError):
            print(f"ERRORE: dati incompleti per {comuni[k]['nome']}", file=sys.stderr)
            sys.exit(1)
        if ora["t"] is None or not giorni or giorni[0]["max"] is None:
            print(f"ERRORE: dati vuoti per {comuni[k]['nome']}", file=sys.stderr)
            sys.exit(1)
        out[k] = {"nome": comuni[k]["nome"], "ora": ora, "giorni": giorni}
    tmp = a.uscita + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump({"aggiornato": dt.datetime.now(dt.timezone.utc).isoformat(timespec="minutes"),
                   "fonte": "Open-Meteo (open-meteo.com, CC BY 4.0)", "comuni": out}, f, ensure_ascii=False,
                  separators=(",", ":"))
    os.replace(tmp, a.uscita)
    print(f"meteo dei Comuni: {len(out)} Comuni")


if __name__ == "__main__":
    main()
