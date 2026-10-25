#!/usr/bin/env python3
"""Sul Pi di casa, ogni 5 minuti: fa partire su GitHub la diretta dei gol del Benevento (.github/workflows/gol.yml,
strumenti/gol.py) 20 minuti prima del calcio d'inizio, e la rilancia se durante la partita si è fermata.

Voluto dal proprietario il 25 ott 2026: «fai i gol, fine primo tempo con quello che è successo e fine partita con
riassunto finale». La partita e il suo stato li legge dal tabellone di oggi di ESPN (la stessa fonte di gol.py). Per la
partita del Benevento che comincia entro 20 minuti o è cominciata da meno di 3 ore:
- un lavoro «Gol <id> · diretta» in corso o in coda: niente;
- uno finito bene (gol.py finisce bene solo dopo il riassunto finale, o con la partita rinviata): niente;
- nessuno, o finiti male: lo fa partire, al massimo 6 volte per partita (dopo, la mail dei lavori rossi basta).
Usa la chiave della sentinella (github.conf: solo Actions). Scrive nel registro solo quando c'è una partita.

Uso sul Pi:  python3 ~/nb-fonti/sentinella/gol_via.py [--prova]     (--prova: dice cosa farebbe, senza lanciare)
"""
import argparse
import datetime as dt
import gzip
import json
import os
import sys
import urllib.request

QUI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, QUI)
from sentinella import REPO, GitHub, leggi_chiave   # noqa: E402

CARTELLA = os.environ.get("NB_FONTI_CARTELLA") or os.path.expanduser("~/nb-fonti")
ESPN = "https://site.api.espn.com/apis/site/v2/sports/soccer/ita.2/scoreboard"
BENEVENTO = "4059"
PRIMA = dt.timedelta(minutes=20)
DOPO = dt.timedelta(hours=3)
MAX_LANCI = 6
IN_CORSO = ("queued", "in_progress", "waiting", "pending", "requested")


def partita_di_oggi():
    giorno = dt.datetime.now().astimezone().strftime("%Y%m%d")   # senza data ESPN dà il giorno americano
    req = urllib.request.Request(f"{ESPN}?dates={giorno}", headers={"User-Agent": "notiziebenevento.it",   # 403 con «(https…)»
                                                                     "Accept-Encoding": "gzip"})
    with urllib.request.urlopen(req, timeout=30) as r:
        raw = r.read()
    d = json.loads(gzip.decompress(raw) if raw[:2] == b"\x1f\x8b" else raw)
    for e in d.get("events") or []:
        comp = e["competitions"][0]
        if any(c["team"]["id"] == BENEVENTO for c in comp["competitors"]):
            nomi = {c["homeAway"]: c["team"]["displayName"] for c in comp["competitors"]}
            inizio = dt.datetime.fromisoformat(e["date"].replace("Z", "+00:00"))
            return e["id"], inizio, comp["status"]["type"], f"{nomi.get('home')}-{nomi.get('away')}"
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--prova", action="store_true")
    a = ap.parse_args()
    adesso = dt.datetime.now().astimezone()
    try:
        trovata = partita_di_oggi()
    except Exception as e:
        print(f"{adesso:%Y-%m-%d %H:%M} il tabellone di ESPN non risponde ({type(e).__name__}: {e})")
        sys.exit(1)
    if not trovata:
        if a.prova:
            print(f"{adesso:%Y-%m-%d %H:%M} oggi il Benevento non gioca")
        return
    pid, inizio, stato, nome = trovata
    if not inizio - PRIMA <= adesso <= inizio + DOPO:
        if a.prova:
            print(f"{adesso:%Y-%m-%d %H:%M} {nome} alle {inizio.astimezone():%H:%M}: non è ancora il momento")
        return
    gh = GitHub(leggi_chiave(os.path.join(CARTELLA, "github.conf")))
    lavori = gh.chiama("GET", f"repos/{REPO}/actions/workflows/gol.yml/runs?per_page=30").get("workflow_runs") or []
    miei = [r for r in lavori if (r.get("display_title") or "").startswith(f"Gol {pid} · diretta")]
    if any(r.get("status") in IN_CORSO for r in miei):
        return   # la diretta è già in corso: niente da dire ogni 5 minuti
    if any(r.get("conclusion") == "success" for r in miei):
        if a.prova:
            print(f"{adesso:%Y-%m-%d %H:%M} {nome}: diretta già finita bene")
        return
    if len(miei) >= MAX_LANCI:
        print(f"{adesso:%Y-%m-%d %H:%M} {nome}: già {len(miei)} lavori finiti male, non la rilancio più")
        return
    perche = "prima volta" if not miei else f"il lavoro di prima è finito con «{miei[0].get('conclusion')}»"
    if a.prova:
        print(f"{adesso:%Y-%m-%d %H:%M} {nome} ({pid}, {stato.get('name')}): la lancerei ({perche})")
        return
    gh.lancia("gol.yml", {"partita": pid, "modo": "diretta"})
    print(f"{adesso:%Y-%m-%d %H:%M} {nome} ({pid}, {stato.get('name')}): diretta dei gol avviata ({perche})")


if __name__ == "__main__":
    main()
