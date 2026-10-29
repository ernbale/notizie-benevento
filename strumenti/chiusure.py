#!/usr/bin/env python3
"""Le chiusure decise dai Comuni (scuole, parchi, cimiteri…): il file chiusure.json del sito, da cui nascono la pagina
«Scuole chiuse», la striscia rossa in prima pagina e i messaggi sui social a qualsiasi ora (strumenti/chiusure_social.py).

Voluto dal proprietario il 23 ott 2026: «dobbiamo essere veloci… senza limite di orario anche per la pubblicazione…
una strategia a prova di bomba». Come funziona:
- La vedetta del Pi (strumenti/vedetta.py) controlla i siti dei Comuni, l'albo di Benevento e i titoli dei giornali ogni
  5-10 minuti, giorno e notte; ogni chiusura che trova la scrive come «pista» in chiusure.json dell'archivio privato
  notizie-benevento-fonti e fa partire subito il giro Chiusure (una routine a parte da quella oraria).
- Il giro Chiusure (e, come rete, lo stesso giro ogni ora) legge le piste con --da-fare, controlla ogni chiusura sulla
  fonte ufficiale e la scrive in un file che passa a --unisci: questo programma la controlla, la mette in chiusure.json
  e (con --pubblica) fa il commit e il push, riprovando da capo se nel frattempo qualcuno ha pubblicato. Solo questo
  programma scrive chiusure.json: due giri insieme non si pestano i piedi.

Una chiusura: {"comune", "cosa" (tutto quello che chiude quel Comune in quei giorni, cominciando dal luogo: il riquadro
della prima pagina ne mostra la prima parte, fino alla via o alla parentesi), "giorni" ["AAAA-MM-GG", …],
"motivo", "fonte": {"nome", "url"}}; l'id (comune-primo giorno), «aggiunta» e «aggiornata» li mette questo programma.

Uso:  python3 strumenti/chiusure.py --da-fare                       (cosa c'è da fare: piste nuove, allerta, chiusure)
      python3 strumenti/chiusure.py --unisci /tmp/chiusure_nuove.json [--pubblica]
      python3 strumenti/chiusure.py --controlla                     (controlla chiusure.json com'è)
"""
import argparse
import datetime as dt
import json
import os
import re
import subprocess
import sys
import unicodedata

QUI = os.path.dirname(os.path.abspath(__file__))
SITO = os.path.dirname(QUI)
FILE = os.path.join(SITO, "chiusure.json")
PISTE = os.path.join(os.path.dirname(SITO), "notizie-benevento-fonti", "chiusure.json")
sys.path.insert(0, QUI)
from meteo import COMUNI_BN   # noqa: E402

ALTRI_ENTI = ["Provincia di Benevento", "Prefettura di Benevento"]   # le superiori a volte le chiude la Provincia
LIVELLI = ["verde", "gialla", "arancione", "rossa"]


def fuso():
    from zoneinfo import ZoneInfo
    return ZoneInfo("Europe/Rome")


def slug(s):
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", "-", s).strip("-")


def leggi(p, vuoto):
    try:
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return vuoto


def attive(dati, oggi):
    """Le chiusure di oggi e dei prossimi giorni (non revocate), in ordine di primo giorno e Comune."""
    out = [c for c in dati.get("chiusure", []) if not c.get("revocata") and max(c.get("giorni") or [""]) >= oggi.isoformat()]
    return sorted(out, key=lambda c: (min(c["giorni"]), c["comune"]))


def allerta(oggi):
    """Il livello di allerta più alto per oggi e per domani, da meteo.json (bollettino o Meteoalarm). meteo.json non
    è nel repository (lo rifà ogni pubblicazione): si legge dal sito, come allerta_domani.py (23 ott 2026: nel cloud
    il giro Chiusure lo leggeva «verde» anche con l'allerta gialla). Se non si legge, «sconosciuta»: nel dubbio si cerca."""
    from allerta_domani import meteo
    try:
        m = meteo()
    except Exception:
        return {g.isoformat(): "sconosciuta (meteo.json non si legge)" for g in (oggi, oggi + dt.timedelta(days=1))}
    out = {}
    for g in (oggi, oggi + dt.timedelta(days=1)):
        x = ((m.get("allerte") or {}).get("giorni") or {}).get(g.isoformat()) or {}
        livelli = [z.get("livello") for z in (x.get("zone") or {}).values()]
        if not livelli:
            livelli = [w.get("livello") for w in x.get("meteoalarm") or []]
        out[g.isoformat()] = max(livelli, key=lambda l: LIVELLI.index(l) if l in LIVELLI else 0, default="verde")
    return out


NOMI = {n.lower(): n for n in COMUNI_BN + ALTRI_ENTI}   # «San Giorgio la Molara» = «San Giorgio La Molara»


def controlla_una(c, oggi, err):
    w = f"chiusura {c.get('comune') or '?'}"
    c["comune"] = NOMI.get(str(c.get("comune") or "").strip().lower(), c.get("comune"))
    if c.get("comune") not in COMUNI_BN + ALTRI_ENTI:
        err.append(f"{w}: «comune» deve essere uno dei 78 Comuni del Sannio scritto come in strumenti/meteo.py "
                   f"(COMUNI_BN), oppure {' o '.join(ALTRI_ENTI)}")
    if not str(c.get("cosa") or "").strip() or len(str(c.get("cosa"))) > 220:
        err.append(f"{w}: «cosa» vuoto o più lungo di 220 caratteri")
    g = c.get("giorni")
    if not isinstance(g, list) or not g or not all(re.match(r"^\d{4}-\d{2}-\d{2}$", str(x)) for x in g):
        err.append(f"{w}: «giorni» deve essere un elenco di date AAAA-MM-GG")
    else:
        for x in g:
            d = dt.date.fromisoformat(x)
            if not oggi - dt.timedelta(days=1) <= d <= oggi + dt.timedelta(days=14):
                err.append(f"{w}: il giorno {x} è troppo lontano da oggi ({oggi}): controlla l'ordinanza")
    f = c.get("fonte") or {}
    if not str(f.get("nome") or "").strip() or not re.match(r"^https?://", str(f.get("url") or "")):
        err.append(f"{w}: «fonte» vuole «nome» e «url» (l'ordinanza o il comunicato del Comune)")
    if len(str(c.get("motivo") or "")) > 140:
        err.append(f"{w}: «motivo» più lungo di 140 caratteri")


def unisci(dati, nuove, adesso, err):
    """Mette le chiusure nuove o aggiornate in dati (per id = comune-primo giorno). Restituisce le frasi di quel che fa."""
    oggi = adesso.date()
    per_id = {c["id"]: c for c in dati.setdefault("chiusure", [])}
    fatte = []
    # l'ora in cui la vedetta ha trovato la chiusura (per le statistiche: quanto ci mette ad arrivare sul sito): la pista
    # indicata, o la prima delle piste viste in questo giro con lo stesso Comune
    piste = {p.get("id"): p for p in leggi(PISTE, {}).get("piste") or []}
    viste_ora = [piste[v] for v in nuove.get("viste") or [] if v in piste]
    for c in nuove.get("chiusure") or []:
        if not isinstance(c, dict):
            err.append(f"chiusura non valida: {c!r}")
            continue
        controlla_una(c, oggi, err)
        if err:
            continue
        c = {k: c[k] for k in ("comune", "cosa", "giorni", "motivo", "fonte", "revocata", "nota", "pista") if k in c}
        c["giorni"] = sorted(set(c["giorni"]))
        c["id"] = f"{slug(c['comune'])}-{c['giorni'][0]}"
        ora = adesso.isoformat(timespec="seconds")   # al secondo: chiusure_social.py la confronta con l'ora dei post
        p = piste.get(c.get("pista")) or min((x for x in viste_ora if (x.get("comune") or "").lower() == c["comune"].lower()),
                                              key=lambda x: x.get("trovata") or "", default=None)
        if p:
            c["pista"], c["trovata"] = p["id"], p.get("trovata")
        if c["id"] in per_id:
            vecchia = per_id[c["id"]]
            for k in ("pista", "trovata"):   # restano quelle della prima volta
                if vecchia.get(k):
                    c[k] = vecchia[k]
            confronta = lambda x: {k: v for k, v in x.items() if k not in ("id", "aggiunta", "aggiornata", "pista", "trovata")}
            if confronta(vecchia) != confronta(c):
                c["aggiunta"], c["aggiornata"] = vecchia.get("aggiunta") or ora, ora
                per_id[c["id"]].clear()
                per_id[c["id"]].update(c)
                fatte.append(f"aggiornata {c['comune']} {dt.date.fromisoformat(c['giorni'][0]):%d/%m}")
        else:
            c["aggiunta"] = ora
            dati["chiusure"].append(c)
            per_id[c["id"]] = c
            fatte.append(f"nuova {c['comune']} {dt.date.fromisoformat(c['giorni'][0]):%d/%m}")
    scartate = {s.get("pista"): s for s in dati.get("scartate") or []}
    for s in nuove.get("scartate") or []:
        if isinstance(s, dict) and s.get("pista"):
            scartate[s["pista"]] = {"pista": s["pista"], "motivo": str(s.get("motivo") or "")[:200],
                                    "quando": adesso.isoformat(timespec="minutes")}
    dati["scartate"] = list(scartate.values())[-200:]   # per le statistiche: perché una pista non è uscita
    viste = dati.setdefault("viste", [])
    for v in (nuove.get("viste") or []) + [s.get("pista") for s in nuove.get("scartate") or [] if isinstance(s, dict)]:
        if v and v not in viste:
            viste.append(v)
    dati["viste"] = viste[-500:]
    # le chiusure finite da più di due giorni escono dal file (restano nella storia di git)
    dati["chiusure"] = [c for c in dati["chiusure"] if max(c["giorni"]) >= (oggi - dt.timedelta(days=2)).isoformat()]
    dati["aggiornato"] = adesso.isoformat(timespec="minutes")
    return fatte


def scrivi(dati):
    with open(FILE + ".tmp", "w", encoding="utf-8") as f:
        json.dump(dati, f, ensure_ascii=False, indent=1)
        f.write("\n")
    os.replace(FILE + ".tmp", FILE)


def git(*a, controlla=True):
    return subprocess.run(["git", "-C", SITO, *a], capture_output=True, text=True, check=controlla)


def da_fare(adesso):
    oggi = adesso.date()
    dati = leggi(FILE, {})
    piste = leggi(PISTE, {})
    viste = set(dati.get("viste") or [])
    nuove = [p for p in piste.get("piste") or [] if p.get("id") not in viste]
    al = allerta(oggi)
    att = attive(dati, oggi)
    print(f"Ora: {adesso:%Y-%m-%d %H:%M}")
    print("Allerta: " + ", ".join(f"{g} {l}" for g, l in al.items()))
    ctrl = piste.get("controllato")
    print(f"Vedetta del Pi: ultimo controllo {ctrl or 'mai'}" + (f" · {piste.get('esito')}" if piste.get("esito") else ""))
    print(f"Chiusure già pubblicate per oggi e i prossimi giorni: {len(att)}")
    for c in att:
        print(f"  - {c['comune']} | {', '.join(c['giorni'])} | {c['cosa']} | {c['fonte']['url']}")
    print(f"Piste nuove della vedetta: {len(nuove)}")
    for p in nuove:
        print(f"\n[{p.get('id')}] {p.get('comune') or '?'} · {p.get('fonte')} · trovata {p.get('trovata')}\n"
              f"  titolo: {p.get('titolo')}\n  link: {p.get('link')}")
        for k in ("pdf",):
            if p.get(k):
                print(f"  {k}: {', '.join(p[k])}")
        print("  testo: " + str(p.get("testo") or "")[:2500].replace("\n", "\n    "))
    in_allerta = any(l not in LIVELLI or LIVELLI.index(l) >= 1 for l in al.values())   # sconosciuta = come allerta
    vedetta_ferma = not ctrl or adesso - dt.datetime.fromisoformat(ctrl) > dt.timedelta(minutes=45)
    if not nuove and not in_allerta and not vedetta_ferma:
        print("\nNIENTE DA FARE: nessuna pista nuova, nessuna allerta per oggi o domani, la vedetta del Pi lavora.")
    else:
        motivi = (["piste nuove"] if nuove else []) + (["allerta"] if in_allerta else []) + \
                 (["vedetta del Pi ferma: cerca tu sui giornali"] if vedetta_ferma else [])
        print(f"\nDA FARE: {', '.join(motivi)}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--da-fare", action="store_true")
    ap.add_argument("--unisci")
    ap.add_argument("--pubblica", action="store_true", help="con --unisci: commit e push (riprova da capo se serve)")
    ap.add_argument("--controlla", action="store_true")
    a = ap.parse_args()
    adesso = dt.datetime.now(fuso())
    if a.da_fare:
        return da_fare(adesso)
    if a.controlla:
        err = []
        for c in leggi(FILE, {}).get("chiusure", []):
            controlla_una(c, adesso.date() - dt.timedelta(days=3), err)
        print("\n".join(f"ERRORE: {x}" for x in err) or "OK")
        return 1 if err else 0
    if not a.unisci:
        ap.print_help()
        return 2
    nuove = leggi(a.unisci, None)
    if not isinstance(nuove, dict):
        print(f"ERRORE: {a.unisci} non è un JSON con «chiusure», «viste» e «scartate»")
        return 1
    altro = [r for r in git("status", "--porcelain").stdout.splitlines() if not r.endswith("chiusure.json")]
    if a.pubblica and altro:   # il giro Chiusure cambia solo chiusure.json: il resto si perderebbe nel riprovare
        print("ERRORE: ci sono altri file cambiati (" + "; ".join(altro[:5]) + "): il giro Chiusure scrive solo "
              "chiusure.json, e solo con questo programma")
        return 1
    for prova in range(4):
        dati = leggi(FILE, {"aggiornato": None, "viste": [], "chiusure": []})
        err = []
        fatte = unisci(dati, nuove, adesso, err)
        if err:
            print("\n".join(f"ERRORE: {x}" for x in err) + "\nNiente è stato scritto: correggi e rilancia.")
            return 1
        scrivi(dati)
        print("OK: " + (", ".join(fatte) or "nessuna chiusura nuova o cambiata (piste segnate come viste)"))
        if not a.pubblica:
            return 0
        if not git("status", "--porcelain", "--", "chiusure.json").stdout.strip():
            print("Niente da pubblicare: chiusure.json è uguale a quello pubblicato")
            return 0
        git("add", "chiusure.json")
        git("commit", "-q", "-m", f"Chiusure delle {adesso:%H:%M}: " + (", ".join(fatte) or "piste viste"))
        if git("push", "-q", "origin", "HEAD:main", controlla=False).returncode == 0:
            print("PUBBLICATO: il sito e i social si aggiornano in pochi minuti")
            return 0
        # qualcuno ha pubblicato nel frattempo: si riparte dal main di adesso e si rifà l'unione
        print(f"il push è stato rifiutato (tentativo {prova + 1}): riprendo il main di adesso e riunisco")
        git("fetch", "-q", "origin", "main")
        git("reset", "-q", "--hard", "origin/main")
    print("ERRORE: dopo 4 tentativi il push non passa: scrivilo nel resoconto")
    return 1


if __name__ == "__main__":
    sys.exit(main() or 0)
