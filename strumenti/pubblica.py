#!/usr/bin/env python3
"""Pubblica su GitHub, in UN SOLO commit, i file che archivia.py ha segnato come CAMBIATO.

Un solo commit vuol dire: o arrivano tutti i file (notizie, mese dell'archivio, indice) o nessuno.
Così una notizia non può mai sparire a metà strada tra la prima pagina e l'archivio.

Uso nella routine (il proxy aggiunge da solo il token per api.github.com):
    python3 strumenti/archivia.py | tee esito.txt
    python3 strumenti/pubblica.py --da esito.txt --messaggio "Notizie delle 14:00"
Uso dal Mac per le prove (usa il login di `gh`):
    python3 strumenti/pubblica.py --gh --ramo prova file1 file2
"""
import argparse
import base64
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request

REPO = os.environ.get("NB_REPO", "ernbale/notizie-benevento")


class Errore(Exception):
    pass


def api(metodo, percorso, corpo=None, con_gh=False):
    if con_gh:
        cmd = ["gh", "api", "-X", metodo, percorso]
        if corpo is not None:
            cmd += ["--input", "-"]
        r = subprocess.run(cmd, input=json.dumps(corpo) if corpo is not None else None,
                           capture_output=True, text=True)
        if r.returncode != 0:
            raise Errore(f"{metodo} {percorso}: {r.stderr.strip() or r.stdout.strip()}")
        return json.loads(r.stdout) if r.stdout.strip() else {}
    req = urllib.request.Request("https://api.github.com" + percorso, method=metodo,
                                 data=json.dumps(corpo).encode() if corpo is not None else None,
                                 headers={"Accept": "application/vnd.github+json",
                                          "X-GitHub-Api-Version": "2022-11-28",
                                          "User-Agent": "notizie-benevento-agente",
                                          "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            testo = r.read().decode()
            return json.loads(testo) if testo.strip() else {}
    except urllib.error.HTTPError as e:
        raise Errore(f"{metodo} {percorso}: HTTP {e.code} {e.read().decode()[:300]}")


def file_da_esito(percorso):
    out = []
    with open(percorso, encoding="utf-8") as f:
        righe = f.read().splitlines()
    if not any(r.strip() == "OK" for r in righe):
        raise Errore("archivia.py non ha finito con OK: non pubblico niente")
    for r in righe:
        if r.startswith("CAMBIATO:"):
            out.append(r.split(":", 1)[1].strip())
    return out


def pubblica(files, messaggio, ramo, con_gh, base):
    for p in files:
        if os.path.isabs(p) or ".." in p.split("/"):
            raise Errore(f"percorso non ammesso: {p}")
        if not os.path.isfile(os.path.join(base, p)):
            raise Errore(f"file mancante: {p}")
    blob = {}
    for p in files:
        with open(os.path.join(base, p), "rb") as f:
            dati = f.read()
        if p.endswith(".json"):
            json.loads(dati.decode("utf-8"))  # mai pubblicare un JSON rotto
        r = api("POST", f"/repos/{REPO}/git/blobs",
                {"content": base64.b64encode(dati).decode(), "encoding": "base64"}, con_gh)
        blob[p] = r["sha"]
    for tentativo in range(1, 4):
        ref = api("GET", f"/repos/{REPO}/git/ref/heads/{ramo}", None, con_gh)
        padre = ref["object"]["sha"]
        albero_padre = api("GET", f"/repos/{REPO}/git/commits/{padre}", None, con_gh)["tree"]["sha"]
        albero = api("POST", f"/repos/{REPO}/git/trees", {
            "base_tree": albero_padre,
            "tree": [{"path": p, "mode": "100644", "type": "blob", "sha": s} for p, s in blob.items()],
        }, con_gh)["sha"]
        if albero == albero_padre:
            print("NIENTE DA PUBBLICARE: i file online sono già uguali")
            return None
        commit = api("POST", f"/repos/{REPO}/git/commits",
                     {"message": messaggio, "tree": albero, "parents": [padre]}, con_gh)["sha"]
        try:
            # force=False: se nel frattempo qualcuno ha pubblicato, non si cancella niente, si riprova
            api("PATCH", f"/repos/{REPO}/git/refs/heads/{ramo}", {"sha": commit, "force": False}, con_gh)
            return commit
        except Errore as e:
            print(f"tentativo {tentativo}: il ramo è cambiato nel frattempo, riprovo ({e})")
            time.sleep(3)
    raise Errore("non sono riuscito ad aggiornare il ramo dopo 3 tentativi")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("files", nargs="*")
    ap.add_argument("--da", help="file con l'uscita di archivia.py (righe CAMBIATO:)")
    ap.add_argument("--messaggio", default="Notizie aggiornate")
    ap.add_argument("--ramo", default="main")
    ap.add_argument("--gh", action="store_true", help="usa il login di gh (prove dal Mac)")
    ap.add_argument("--cartella", default=os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    a = ap.parse_args()
    try:
        files = list(a.files)
        if a.da:
            files += file_da_esito(a.da)
        files = sorted(set(files))
        if not files:
            print("NIENTE DA PUBBLICARE")
            return
        commit = pubblica(files, a.messaggio, a.ramo, a.gh, a.cartella)
        if commit:
            print(f"PUBBLICATO {commit[:7]} su {a.ramo}: {', '.join(files)}")
    except Errore as e:
        print("ERRORE:", e)
        sys.exit(1)


if __name__ == "__main__":
    main()
