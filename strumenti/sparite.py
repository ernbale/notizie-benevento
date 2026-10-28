#!/usr/bin/env python3
"""Nessuna notizia già uscita sparisce dal sito: la rete sotto archivia.py.

Voluta dal proprietario il 28 ott 2026, quando il giro delle 08:06 tolse la notizia di Arpaia (parcheggio del cimitero
chiuso), già uscita, e nessuno lo fermò: «non deve mai più ricapitare». archivia.py, a ogni giro, rimette le voci tolte
rispetto all'ultimo salvataggio (rimetti_sparite); questo controlla tutto il resto (unioni di git, commit a mano, giri
che non passano da archivia.py) contro il sito com'è adesso.

A ogni pubblicazione (pubblica.yml, prima delle pagine) legge dal sito notizie.json, archivio/indice.json ed
eventi.json. Una notizia, un approfondimento o un evento che sul sito c'è e qui non c'è più (né in prima pagina, né in
archivio, né unito in un altro o tolto apposta: archivio/rimandi.json, «notizie», «eventi», «tolte») si rimette com'era
sul sito: in prima pagina se era lì, nel suo mese dell'archivio se era in archivio. Con --manda va anche nel repository,
con un commit a parte sopra l'ultimo main (come le foto di strumenti/foto_ia.py), così il giro dopo lo ritrova.

Uso:  python3 strumenti/sparite.py            controlla e rimette qui
      python3 strumenti/sparite.py --manda    in più il commit nel repository
Esce sempre con 0 (la pubblicazione non si ferma): se il sito non risponde non controlla, e lo dice.
"""
import argparse
import glob
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from archivia import leggi, testo_json, voce_indice   # noqa: E402

RADICE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SITO = "https://notiziebenevento.it"
SOLO_SUL_SITO = ("foto_ia",)   # li mette la pubblicazione (foto_ia.py --segna), nel repository non ci sono


def prendi(percorso):
    req = urllib.request.Request(f"{SITO}/{percorso}?t={int(time.time())}", headers={"User-Agent": "notiziebenevento-sparite"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode("utf-8"))


def dal_sito():
    """Quello che il sito mostra adesso: {"notizie": {...}, "indice": [...], "eventi": [...], "mesi": {}}."""
    n = prendi("notizie.json")
    return {"notizie": n, "indice": prendi("archivio/indice.json").get("voci") or [],
            "eventi": (prendi("eventi.json").get("eventi") or []), "mesi": {}}


def mese_dal_sito(sito, mese):
    if mese not in sito["mesi"]:
        sito["mesi"][mese] = prendi(f"archivio/{mese}.json")
    return sito["mesi"][mese]


def qui(base):
    """Gli id che ci sono qui (prima pagina, archivio, unite o tolte apposta)."""
    d = leggi(os.path.join(base, "notizie.json"), {}) or {}
    ids = {x.get("id") for x in (d.get("notizie") or []) + (d.get("approfondimenti") or [])}
    for p in glob.glob(os.path.join(base, "archivio", "[0-9][0-9][0-9][0-9]-[0-9][0-9].json")):
        m = leggi(p, {}) or {}
        ids |= {x.get("id") for x in (m.get("notizie") or []) + (m.get("approfondimenti") or [])}
    ev = {x.get("id") for x in (leggi(os.path.join(base, "eventi.json"), {}) or {}).get("eventi") or []}
    for p in glob.glob(os.path.join(base, "archivio", "eventi-[0-9][0-9][0-9][0-9]-[0-9][0-9].json")):
        ev |= {x.get("id") for x in (leggi(p, {}) or {}).get("eventi") or []}
    rim = leggi(os.path.join(base, "archivio", "rimandi.json"), {}) or {}
    tolte = set(rim.get("tolte") or {})
    return ids | set(rim.get("notizie") or {}) | tolte, ev | set(rim.get("eventi") or {}) | tolte


def sparite(base, sito):
    """[(dove, tipo, voce)]: dove è "prima", "eventi" o il mese dell'archivio (AAAA-MM)."""
    ids, ev_ids = qui(base)
    out = []
    for chiave, tipo in (("notizie", "notizia"), ("approfondimenti", "approfondimento")):
        for x in sito["notizie"].get(chiave) or []:
            if x.get("id") not in ids:
                out.append(("prima", tipo, x))
    for v in sito["indice"]:
        if v.get("id") in ids or any(v.get("id") == x.get("id") for _, _, x in out):
            continue
        m = mese_dal_sito(sito, v["mese"])
        tipo = v.get("tipo") or "notizia"
        x = next((y for y in m.get("notizie" if tipo == "notizia" else "approfondimenti") or [] if y.get("id") == v["id"]), None)
        if x is not None:
            out.append((v["mese"], tipo, x))
    for x in sito["eventi"]:
        if x.get("id") not in ev_ids:
            out.append(("eventi", "evento", x))
    return out


def rimetti(base, lista):
    """Rimette le voci nei file; restituisce i file cambiati (relativi a base)."""
    cambiati = set()
    lista = [(dove, tipo, {k: v for k, v in x.items() if k not in SOLO_SUL_SITO}) for dove, tipo, x in lista]
    p_n = os.path.join(base, "notizie.json")
    d = leggi(p_n)
    for dove, tipo, x in lista:
        if dove == "prima" and tipo == "notizia":
            k = next((i for i, n in enumerate(d["notizie"]) if str(n.get("pubblicato")) < str(x.get("pubblicato"))),
                     len(d["notizie"]))
            d["notizie"].insert(k, x)
        elif dove == "prima":
            d.setdefault("approfondimenti", []).append(x)
        else:
            continue
        cambiati.add("notizie.json")
    if "notizie.json" in cambiati:
        with open(p_n, "w", encoding="utf-8") as f:
            f.write(testo_json(d))
    archiviate = [(dove, tipo, x) for dove, tipo, x in lista if dove not in ("prima", "eventi")]
    if archiviate:
        p_i = os.path.join(base, "archivio", "indice.json")
        indice = leggi(p_i, {"voci": []})
        for dove, tipo, x in archiviate:
            p_m = os.path.join(base, "archivio", dove + ".json")
            m = leggi(p_m, {"notizie": [], "approfondimenti": []})
            if tipo == "notizia":
                m.setdefault("notizie", []).append(x)
                m["notizie"].sort(key=lambda y: y.get("pubblicato", ""), reverse=True)
            else:
                m.setdefault("approfondimenti", []).append(x)
                m["approfondimenti"].sort(key=lambda y: y.get("aggiornato", ""), reverse=True)
            with open(p_m, "w", encoding="utf-8") as f:
                f.write(testo_json(m))
            indice["voci"].append(voce_indice(x, tipo, dove))
            cambiati.add(os.path.join("archivio", dove + ".json"))
        indice["voci"].sort(key=lambda v: v["pubblicato"], reverse=True)
        with open(p_i, "w", encoding="utf-8") as f:
            f.write(testo_json(indice))
        cambiati.add(os.path.join("archivio", "indice.json"))
    eventi = [x for dove, _, x in lista if dove == "eventi"]
    if eventi:
        p_e = os.path.join(base, "eventi.json")
        ev = leggi(p_e, {"eventi": []})
        ev["eventi"] = sorted(ev["eventi"] + eventi, key=lambda y: (y.get("inizio", ""), y.get("ora") or "", y.get("id", "")))
        with open(p_e, "w", encoding="utf-8") as f:
            f.write(testo_json(ev))
        cambiati.add("eventi.json")
    return sorted(cambiati)


def git(*args, cwd=RADICE, check=True):
    return subprocess.run(["git", *args], cwd=cwd, check=check, capture_output=True, text=True)


def manda(sito):
    """Lo stesso, sopra l'ultimo main, su una copia a parte (worktree); se un giro spinge nel frattempo, si riprova."""
    for prova in range(4):
        git("fetch", "-q", "origin", "main")
        wt = tempfile.mkdtemp(prefix="sparite-")
        git("worktree", "add", "-q", "--detach", wt, "origin/main")
        try:
            lista = sparite(wt, sito)
            if not lista:
                print("sparite: nel repository ci sono già tutte")
                return True
            file_ = rimetti(wt, lista)
            git("add", "--", *file_, cwd=wt)
            msg = "Rimesse le voci sparite dal sito: " + ", ".join(x["id"] for _, _, x in lista)
            git("-c", "user.name=Claude", "-c", "user.email=noreply@anthropic.com", "commit", "-q", "-m", msg[:300], cwd=wt)
            if git("push", "-q", "origin", "HEAD:main", cwd=wt, check=False).returncode == 0:
                print(f"sparite: {len(lista)} rimesse anche nel repository")
                return True
        finally:
            git("worktree", "remove", "--force", wt, check=False)
            shutil.rmtree(wt, ignore_errors=True)
        time.sleep(5 * (prova + 1))
    print("::warning::sparite: non riesco a rimetterle nel repository (sul sito ci sono; si riprova alla pubblicazione dopo)")
    return False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--manda", action="store_true", help="anche il commit nel repository")
    a = ap.parse_args()
    try:
        sito = dal_sito()
    except Exception as e:
        print(f"::warning::sparite: il sito non risponde ({type(e).__name__}): controllo saltato")
        return
    try:
        lista = sparite(RADICE, sito)
    except Exception as e:
        print(f"::warning::sparite: controllo non riuscito ({type(e).__name__}: {str(e)[:200]})")
        return
    if not lista:
        print("sparite: nessuna, sul sito c'è tutto quello che c'era")
        return
    for dove, tipo, x in lista:
        print(f"::warning::sparite: {tipo} {x['id']} c'era sul sito e qui mancava: rimessa ({dove})")
    rimetti(RADICE, lista)
    if a.manda:
        try:
            manda(sito)
        except Exception as e:
            print(f"::warning::sparite: commit non riuscito ({type(e).__name__}: {str(e)[:200]})")


if __name__ == "__main__":
    main()
