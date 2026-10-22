#!/usr/bin/env python3
"""C'è un'allerta arancione o rossa per domani nel Sannio? Serve al giro delle 23 dell'agente, che lavora solo in
quelle sere (le ordinanze dei sindaci sulle scuole escono spesso dopo il giro delle 22).

Legge le allerte di meteo.json (le mette insieme strumenti/meteo.py ogni ora): il bollettino della Protezione civile
per le tre zone del Sannio e, se il bollettino non è ancora uscito, Meteoalarm per la Campania.
Stampa «SÌ: …» ed esce con 0 se c'è, «NO: …» ed esce con 1 se non c'è (2 se meteo.json non si legge).

Uso:  python3 strumenti/allerta_domani.py
"""
import datetime as dt
import json
import os
import sys
import urllib.request

SITO = "https://notiziebenevento.it/meteo.json"
GRAVI = {"arancione", "rossa"}


def meteo():
    try:
        with urllib.request.urlopen(f"{SITO}?t={int(dt.datetime.now().timestamp())}", timeout=30) as r:
            return json.load(r)
    except Exception:   # il sito non risponde: la copia nel repository
        with open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "meteo.json"),
                  encoding="utf-8") as f:
            return json.load(f)


def main():
    from zoneinfo import ZoneInfo
    domani = (dt.datetime.now(ZoneInfo("Europe/Rome")) + dt.timedelta(days=1)).date().isoformat()
    try:
        g = (meteo().get("allerte") or {}).get("giorni", {}).get(domani) or {}
    except Exception as e:
        print(f"NO: meteo.json non si legge ({type(e).__name__}): controlla a mano il bollettino della Protezione civile")
        sys.exit(2)
    zone = g.get("zone") or {}
    gravi = [f"{z} ({v.get('livello')})" for z, v in zone.items() if v.get("livello") in GRAVI]
    if not zone:   # bollettino non ancora uscito: Meteoalarm, che vale per tutta la Campania
        gravi = [f"Meteoalarm Campania ({m.get('livello')}, {m.get('tipo')})" for m in g.get("meteoalarm") or []
                 if m.get("livello") in GRAVI]
    if gravi:
        print(f"SÌ: allerta per domani {domani}: {', '.join(gravi)}")
        sys.exit(0)
    livelli = sorted({v.get("livello") for v in zone.values()}) or ["nessuna"]
    print(f"NO: per domani {domani} niente allerta arancione o rossa (bollettino: {', '.join(map(str, livelli))})")
    sys.exit(1)


if __name__ == "__main__":
    main()
