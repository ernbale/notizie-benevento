#!/usr/bin/env python3
"""Sul Pi di casa, alle 12: fa partire la pubblicazione del sito su GitHub, così la curiosità del Sannio del giorno esce
puntuale sui social (strumenti/curiosita_social.py) e sul sito. Con --controlla (12:25 e 12:50): se sul sito la
curiosità di oggi ancora non c'è, la fa ripartire (gli orari di GitHub a volte saltano). Con --giro (alle :00, :20 e
:40 dalle 6 alle 21, dal 26 ott 2026; prima solo alle :40): una pubblicazione in più per i social, così c'è sempre
un'occasione ogni 20 minuti (facebook.py e instagram.py: una notizia ogni 20 minuti, voluto dal proprietario). Usa la chiave della sentinella (github.conf: solo Actions).
Dal 30 ott 2026, col sito vero sul server Aruba, la pubblicazione la chiede al server (sentinella.chiedi_pubblicazione).

Uso sul Pi:  python3 ~/nb-fonti/sentinella/curiosita_via.py [--controlla | --giro]
"""
import argparse
import datetime as dt
import json
import os
import sys
import urllib.request

QUI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, QUI)
from sentinella import GitHub, chiedi_pubblicazione, leggi_chiave, sito_sul_server   # noqa: E402

CARTELLA = os.environ.get("NB_FONTI_CARTELLA") or os.path.expanduser("~/nb-fonti")
SITO = "https://notiziebenevento.it"


def sul_sito_oggi(oggi):
    req = urllib.request.Request(f"{SITO}/curiosita/ultime.json?t={dt.datetime.now().timestamp():.0f}",
                                 headers={"User-Agent": "nb-curiosita", "Cache-Control": "no-cache"})
    with urllib.request.urlopen(req, timeout=30) as r:
        ultime = json.load(r).get("curiosita") or []
    return bool(ultime) and ultime[0].get("data") == oggi


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--controlla", action="store_true")
    ap.add_argument("--giro", action="store_true")
    a = ap.parse_args()
    adesso = dt.datetime.now().astimezone()
    oggi = adesso.date().isoformat()
    if a.controlla:
        try:
            if sul_sito_oggi(oggi):
                print(f"{adesso:%Y-%m-%d %H:%M} curiosità di oggi già sul sito")
                return
        except Exception as e:
            print(f"{adesso:%Y-%m-%d %H:%M} non leggo il sito ({type(e).__name__}: {e}): rilancio")
    chiedi_pubblicazione(None if sito_sul_server() else GitHub(leggi_chiave(os.path.join(CARTELLA, "github.conf"))))
    print(f"{adesso:%Y-%m-%d %H:%M} pubblicazione {'chiesta al server' if sito_sul_server() else 'avviata'}" + (" (la curiosità non era ancora sul sito)" if a.controlla
                                                             else " (giro delle :40 per i social)" if a.giro else ""))


if __name__ == "__main__":
    main()
