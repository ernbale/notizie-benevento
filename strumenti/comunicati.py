#!/usr/bin/env python3
"""I comunicati arrivati per posta a comunicati@notiziebenevento.it: lo strumento del giro lampo (COMUNICATI.md).

Voluto dal proprietario il 24 ott 2026: «questi sono comunicati ufficiali, deve essere istantanea lettura,
preparazione articolo, pubblicazione istantanea Instagram Facebook Telegram… non deve ricapitare assolutamente».
Il Pi legge la casella ogni 5 minuti e, appena arriva un comunicato vero, fa partire il giro lampo
(strumenti/comunicati_lampo.py); il giro lampo legge i comunicati con --da-fare, scrive l'articolo in un file e lo
passa a --unisci: questo programma lo controlla (le stesse regole di archivia.py), lo mette in testa a notizie.json
con «subito» (Facebook e Instagram lo pubblicano senza aspettare la pausa) e con l'id del comunicato in «comunicati»,
segna il comunicato in comunicati_visti.json e (con --pubblica) fa il commit e il push, ripartendo dal main di adesso
se nel frattempo qualcuno ha pubblicato. Non archivia e non tocca le altre notizie: così il giro di ogni ora, che può
lavorare nello stesso momento, si unisce senza conflitti (strumenti/unisci_notizie.py).

Dal 25 ott 2026 (il proprietario: «deve aggiungerlo anche al calendario, stai attento a non creare doppioni») un
comunicato su un evento del calendario (AGENTE.md, «Il calendario degli eventi») va anche in eventi.json: in «eventi»
l'evento completo; se è già in calendario, con lo stesso id (lo sostituisce: date, orari, fonti, locandina). Un evento
nuovo che somiglia a uno che c'è già (stesso Comune, stessi giorni, titolo simile) è un errore: si aggiorna quello.
La locandina arrivata con la mail («immagini» del comunicato) si indica con "locandina": "<id del comunicato>/<n>",
nella notizia e nell'evento: la copia in img/locandine/ archivia.risolvi_locandine(), e niente foto fatta con l'IA.

Il file per --unisci:
{"notizie": [ {una notizia completa come in AGENTE.md, «comunicati»: ["id del comunicato"]} ],
 "eventi": [ {un evento completo come in AGENTE.md} ],   (facoltativo)
 "esiti": [ {"comunicato": "id", "esito": "pubblicato", "notizia": "id della notizia nuova"},
            {"comunicato": "id", "esito": "gia_nel_sito", "notizia": "id della notizia che c'è già"},
            {"comunicato": "id", "esito": "scartato", "motivo": "perché non si pubblica"} ]}
Ogni comunicato di --da-fare deve avere il suo esito. Il motivo resta nel resoconto del giro: comunicati_visti.json
(pubblico) tiene solo id, esito, notizia e ora.

Uso:  python3 strumenti/comunicati.py --da-fare
      python3 strumenti/comunicati.py --unisci /tmp/comunicati_esito.json [--pubblica]
"""
import argparse
import copy
import datetime as dt
import glob
import hashlib
import json
import os
import re
import subprocess
import sys

QUI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, QUI)
import archivia as A   # noqa: E402
import giornali as G   # noqa: E402

SITO = os.path.dirname(QUI)
FILE = os.path.join(SITO, "comunicati_visti.json")
NOTIZIE = os.path.join(SITO, "notizie.json")
EVENTI = os.path.join(SITO, "eventi.json")
ESITI = ("pubblicato", "gia_nel_sito", "scartato")
GIORNI_DA_FARE = 3      # i comunicati arrivati da più giorni non sono più «da fare» per il giro lampo
GIORNI_VISTI = 30       # quanto si ricordano i comunicati trattati


def fuso():
    from zoneinfo import ZoneInfo
    return ZoneInfo("Europe/Rome")


def leggi(p, vuoto):
    try:
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return vuoto


def comunicati():
    """Le voci di comunicati.json dell'archivio di casa (accanto al sito, o in /home/user nel cloud)."""
    for base in (os.environ.get("NB_FONTI_ARCHIVIO") or G.FONTI_CASA, "/home/user/notizie-benevento-fonti"):
        d = leggi(os.path.join(base, "comunicati.json"), None)
        if isinstance(d, dict):
            return d
    return {}


def git(*a, controlla=True):
    return subprocess.run(["git", "-C", SITO, *a], capture_output=True, text=True, check=controlla)


def simili(c, notizie, adesso):
    """Le notizie degli ultimi 3 giorni che sembrano lo stesso fatto del comunicato (parole del titolo in comune)."""
    p = G.parole(c.get("titolo", "") + " " + str(c.get("testo", ""))[:200])
    out = []
    for n in notizie:
        if str(n.get("pubblicato", ""))[:10] < (adesso.date() - dt.timedelta(days=3)).isoformat():
            continue
        q = G.parole(n.get("titolo", ""))
        comuni = len(p & q)
        if comuni >= 2:
            out.append((comuni, n))
    return [n for _, n in sorted(out, key=lambda x: -x[0])[:4]]


def da_fare(adesso):
    c = comunicati()
    visti = leggi(FILE, {}).get("visti") or {}
    limite = (adesso - dt.timedelta(days=GIORNI_DA_FARE)).isoformat()
    voci = [v for v in c.get("voci") or [] if v.get("id") and v["id"] not in visti
            and (v.get("arrivata") or v.get("data") or "") >= limite]
    notizie = leggi(NOTIZIE, {}).get("notizie") or []
    print(f"Ora: {adesso:%Y-%m-%d %H:%M}")
    print(f"Casella comunicati@: ultimo controllo del Pi {c.get('controllato') or 'mai'} · {c.get('esito') or '?'}")
    print(f"Comunicati da trattare: {len(voci)}")
    for v in voci:
        print(f"\n[{v['id']}] arrivato {v.get('arrivata') or v.get('data')} · da {v.get('mittente')} "
              f"(dominio {v.get('dominio')})" + (f" · allegati: {', '.join(v['allegati'])}" if v.get("allegati") else ""))
        print(f"  oggetto: {v.get('titolo')}")
        for n in simili(v, notizie, adesso):
            print(f"  POSSIBILE STESSO FATTO già sul sito: {n['id']} · {n.get('pubblicato', '')[:16]} · {n.get('titolo')}")
        for k, im in enumerate(v.get("immagini") or [], 1):   # le locandine: guardale (Read) prima di usarle
            print(f"  immagine {v['id']}/{k}: {os.path.join(A.archivio_fonti() or '', im.get('file', ''))} "
                  f"({im.get('da')}, {im.get('larghezza')}×{im.get('altezza')})")
        print("  testo:\n    " + str(v.get("testo") or "").strip().replace("\n", "\n    "))
    print("\n" + (f"DA FARE: {len(voci)} comunicati" if voci else "NIENTE DA FARE: nessun comunicato nuovo"))


def scegli_foto_nuova(n, notizie):
    """La versione della foto del tema per la sola notizia nuova: la meno usata in prima pagina (le altre non si
    toccano, le sistema il giro di ogni ora)."""
    v = A.versioni_foto(n.get("immagine") or "") if n.get("categoria") != "cronaca" else []
    n.pop("foto", None)
    if v:
        usate = [x.get("foto") for x in notizie]
        n["foto"] = min(v, key=lambda x: (usate.count(x), hashlib.md5((n["id"] + x).encode()).hexdigest()))


def unisci(d, visti, entrata, voci, adesso, err):
    """Mette le notizie nuove in testa a d e gli esiti in visti. Restituisce i titoli pubblicati."""
    nuove = entrata.get("notizie") or []
    esiti = entrata.get("esiti") or []
    if not isinstance(nuove, list) or not isinstance(esiti, list):
        err.append("«notizie» ed «esiti» devono essere elenchi")
        return []
    ids_voci = {v["id"] for v in voci if v.get("id")}
    attuali = {n.get("id") for n in d.get("notizie", []) + d.get("approfondimenti", [])}
    indice = leggi(os.path.join(SITO, "archivio", "indice.json"), {}).get("voci") or []
    in_archivio = {x.get("id") for x in indice}
    rimandi = (leggi(os.path.join(SITO, "archivio", "rimandi.json"), {}) or {}).get("notizie") or {}
    per_id = {}
    for n in nuove:
        i = n.get("id") if isinstance(n, dict) else None
        if not i:
            err.append(f"notizia senza «id»: {str(n)[:80]}")
            continue
        if i in attuali or i in in_archivio or i in rimandi or i in per_id:
            err.append(f"{i}: id già usato (sul sito, in archivio o due volte qui): scegline un altro")
        if A.CHIUSURA.search(str(n.get("titolo") or "")):
            err.append(f"{i}: parla di una chiusura decisa da un Comune: la pubblica il giro Chiusure, non questo")
        per_id[i] = n
    trattati, pubblicate = set(), set()
    for e in esiti:
        cid, es = e.get("comunicato"), e.get("esito")
        w = f"esito del comunicato {cid}"
        if cid not in ids_voci:
            err.append(f"{w}: in comunicati.json non c'è")
            continue
        if cid in trattati:
            err.append(f"{w}: due esiti per lo stesso comunicato")
        trattati.add(cid)
        if es not in ESITI:
            err.append(f"{w}: «esito» deve essere uno di {', '.join(ESITI)}")
        elif es == "pubblicato":
            if e.get("notizia") not in per_id:
                err.append(f"{w}: la notizia {e.get('notizia')!r} non è tra le «notizie» del file")
            else:
                pubblicate.add(e["notizia"])
                per_id[e["notizia"]].setdefault("comunicati", [])
                if cid not in per_id[e["notizia"]]["comunicati"]:
                    per_id[e["notizia"]]["comunicati"].append(cid)
        elif es == "gia_nel_sito" and e.get("notizia") not in attuali | in_archivio:
            err.append(f"{w}: la notizia {e.get('notizia')!r} non c'è né in prima pagina né in archivio")
        elif es == "scartato" and len(str(e.get("motivo") or "").strip()) < 10:
            err.append(f"{w}: scrivi il «motivo» (serve al resoconto)")
    for i in per_id:
        if i not in pubblicate:
            err.append(f"{i}: notizia senza un comunicato con esito «pubblicato» che la indichi")
    if err:
        return []
    for n in reversed(nuove):
        n["subito"] = True
        n.setdefault("pubblicato", adesso.isoformat(timespec="seconds"))
        scegli_foto_nuova(n, d.get("notizie", []))
        d["notizie"].insert(0, n)
    ora = adesso.isoformat(timespec="minutes")
    for e in esiti:
        visti[e["comunicato"]] = {k: v for k, v in {"esito": e["esito"], "notizia": e.get("notizia"), "quando": ora}.items() if v}
    return [n.get("titolo", "") for n in nuove]


def unisci_eventi(ev, entrata, err):
    """Gli eventi del file in eventi.json: con un id che c'è già lo sostituiscono, se no si aggiungono. Restituisce i
    titoli (i controlli, doppioni compresi, li fa poi archivia.controlla_eventi)."""
    nuovi = entrata.get("eventi") or []
    if not isinstance(nuovi, list) or not all(isinstance(x, dict) and x.get("id") for x in nuovi):
        err.append("«eventi» deve essere un elenco di eventi, ognuno col suo «id»")
        return []
    in_archivio = set()
    for q in glob.glob(os.path.join(SITO, "archivio", "eventi-*.json")):
        in_archivio |= {x.get("id") for x in leggi(q, {}).get("eventi") or []}
    lista = ev.setdefault("eventi", [])
    titoli = []
    for x in nuovi:
        if x["id"] in in_archivio:
            err.append(f"evento {x['id']}: id di un evento già in archivio: scegline un altro")
            continue
        i = next((k for k, y in enumerate(lista) if y.get("id") == x["id"]), None)
        if i is None:
            lista.append(x)
            titoli.append("evento nuovo: " + str(x.get("titolo")))
        else:
            lista[i] = x
            titoli.append("evento aggiornato: " + str(x.get("titolo")))
    return titoli


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--da-fare", action="store_true")
    ap.add_argument("--unisci")
    ap.add_argument("--pubblica", action="store_true", help="con --unisci: commit e push (riparte da capo se serve)")
    a = ap.parse_args()
    adesso = dt.datetime.now(fuso())
    if a.da_fare:
        return da_fare(adesso)
    if not a.unisci:
        ap.print_help()
        return 2
    entrata = leggi(a.unisci, None)
    if not isinstance(entrata, dict):
        print(f"ERRORE: {a.unisci} non è un JSON con «notizie» ed «esiti»")
        return 1
    voci = comunicati().get("voci") or []
    if a.pubblica:
        altro = [r for r in git("status", "--porcelain").stdout.splitlines()
                 if not r.endswith(("notizie.json", "comunicati_visti.json", "eventi.json")) and "img/locandine/" not in r]
        if altro:   # il giro lampo scrive solo con questo programma: il resto si perderebbe nel ripartire da capo
            print("ERRORE: ci sono altri file cambiati (" + "; ".join(altro[:5]) + "): il giro lampo scrive solo "
                  "notizie.json, eventi.json, comunicati_visti.json e le locandine, e solo con questo programma")
            return 1
        git("fetch", "-q", "origin", "main")
        git("reset", "-q", "--hard", "origin/main")   # si parte dal main di adesso: la sessione può essere vecchia
    for tentativo in range(5):
        d = leggi(NOTIZIE, None)
        if not isinstance(d, dict):
            print("ERRORE: notizie.json non si legge")
            return 1
        cartella = leggi(FILE, {})
        visti = cartella.get("visti") or {}
        err, avv = [], []
        titoli = unisci(d, visti, copy.deepcopy(entrata), voci, adesso, err)
        ev = None
        if entrata.get("eventi") and not err:
            ev = leggi(EVENTI, None)
            if not isinstance(ev, dict):
                err.append("eventi.json non si legge")
            else:
                titoli += unisci_eventi(ev, copy.deepcopy(entrata), err)
                if not err:
                    A.controlla_eventi(ev, err)
        if not err:
            A.controlla(d, err, avv, adesso)
        if err:
            for x in avv:
                print("AVVISO:", x)
            print("\n".join(f"ERRORE: {x}" for x in err) + "\nNiente è stato scritto: correggi il file e rilancia.")
            return 1
        # le locandine si copiano nel sito solo adesso, con tutti i controlli passati
        A.risolvi_locandine(d.get("notizie", []) + ((ev or {}).get("eventi") or []))
        limite = (adesso - dt.timedelta(days=GIORNI_VISTI)).isoformat()
        visti = {k: v for k, v in visti.items() if v.get("quando", "") >= limite}
        with open(NOTIZIE, "w", encoding="utf-8") as f:
            f.write(A.testo_json(d))
        if ev is not None:
            with open(EVENTI, "w", encoding="utf-8") as f:
                f.write(A.testo_json(ev))
        with open(FILE, "w", encoding="utf-8") as f:
            f.write(A.testo_json({"nota": "Comunicati arrivati per posta e già trattati dal giro lampo "
                                          "(strumenti/comunicati.py): id, esito, notizia, ora.", "visti": visti}))
        print("OK: " + ("; ".join(titoli) if titoli else "nessuna notizia nuova (comunicati segnati come visti)"))
        if not a.pubblica:
            return 0
        git("add", "notizie.json", "comunicati_visti.json", "eventi.json")
        if os.path.isdir(os.path.join(SITO, "img", "locandine")):
            git("add", "img/locandine")
        msg = f"Comunicato delle {adesso:%H:%M}: " + ("; ".join(titoli)[:120] if titoli else "comunicati visti")
        git("commit", "-q", "-m", msg)
        if git("push", "-q", "origin", "HEAD:main", controlla=False).returncode == 0:
            print("PUBBLICATO: il sito si aggiorna in pochi minuti, poi Telegram, Facebook e Instagram")
            return 0
        print(f"il push è stato rifiutato (tentativo {tentativo + 1}): riprendo il main di adesso e riunisco")
        git("fetch", "-q", "origin", "main")
        git("reset", "-q", "--hard", "origin/main")
    print("ERRORE: dopo 5 tentativi il push non passa: scrivilo nel resoconto")
    return 1


if __name__ == "__main__":
    sys.exit(main() or 0)
