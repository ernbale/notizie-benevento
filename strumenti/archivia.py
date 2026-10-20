#!/usr/bin/env python3
"""Controlla notizie.json e sposta in archivio le notizie uscite dalla prima pagina.

Nessuna notizia viene mai cancellata:
- in prima pagina restano le notizie di oggi e dei 2 giorni prima, gli avvisi ufficiali ancora in vigore
  (`in_vigore_fino`) e le notizie collegate a un approfondimento attivo;
- le altre passano in archivio/AAAA-MM.json (mese di `pubblicato`), con l'articolo completo;
- un approfondimento passa in archivio quando ha `"archiviato": true` o non è aggiornato da più di 7 giorni;
- archivio/indice.json si rifà ogni volta da tutti i mesi (serve alla ricerca e ai link vecchi).

Uso:  python3 strumenti/archivia.py            controlla, archivia e scrive i file
      python3 strumenti/archivia.py --prova    controlla e dice cosa farebbe, senza scrivere
      python3 strumenti/archivia.py --oggi 2026-10-25   (solo per le prove)
Esce con codice 1, senza scrivere niente, se trova un errore.
Alla fine stampa una riga «CAMBIATO: <file>» per ogni file da pubblicare.
"""
import argparse
import datetime as dt
import glob
import json
import os
import re
import sys

CAT = {"strade", "cronaca", "meteo", "politica", "eventi", "altro"}
ZONE = {"benevento", "telesina", "caudina", "fortore", "provincia"}
STATI = {"confermata", "ufficiale"}
VIETATE = ["choc", "shock", "incredibile", "ecco cosa", "non crederai", "!", "?"]
ISO = re.compile(r"^\d{4}-\d{2}-\d{2}(T\d{2}:\d{2}(:\d{2})?[+-]\d{2}:\d{2})?$")
GIORNO = re.compile(r"^\d{4}-\d{2}-\d{2}$")
GIORNI_PRIMA_PAGINA = 3      # oggi + i 2 giorni prima
GIORNI_APPROFONDIMENTO = 7


def oggi_roma():
    try:
        from zoneinfo import ZoneInfo
        return dt.datetime.now(ZoneInfo("Europe/Rome")).date()
    except Exception:
        print("AVVISO: fuso Europe/Rome non disponibile, uso UTC+1")
        return (dt.datetime.utcnow() + dt.timedelta(hours=1)).date()


def vuoto(v):
    return v is None or (isinstance(v, str) and not v.strip()) or (isinstance(v, (list, dict)) and len(v) == 0)


def leggi(path, predefinito=None):
    if not os.path.exists(path):
        return predefinito
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def testo_json(d):
    return json.dumps(d, ensure_ascii=False, indent=1) + "\n"


def controlla(d, err, avv):
    """Le stesse regole di AGENTE.md, sul file della prima pagina."""
    for k in ("aggiornato", "giornali_letti", "notizie", "approfondimenti"):
        if k not in d:
            err.append(f"manca il campo {k}")
    if err:
        return
    if not ISO.match(str(d.get("aggiornato", ""))):
        err.append("aggiornato non è una data ISO")

    def url_validi(o, dove):
        if isinstance(o, dict):
            for k, v in o.items():
                if k == "url":
                    if not isinstance(v, str) or not re.match(r"^https?://", v):
                        err.append(f"{dove}: url non valido {v!r}")
                else:
                    url_validi(v, dove)
        elif isinstance(o, list):
            for x in o:
                url_validi(x, dove)

    for n in d["notizie"]:
        w = n.get("id", "?")
        for k in ("id", "titolo", "sintesi", "categoria", "zona", "luogo", "pubblicato", "stato", "fonti", "articolo"):
            if vuoto(n.get(k)):
                err.append(f"{w}: campo vuoto o mancante {k}")
        if not re.match(r"^[a-z0-9]+(-[a-z0-9]+)*$", str(n.get("id", ""))):
            err.append(f"{w}: id non valido (solo minuscole, numeri e trattini)")
        if n.get("categoria") not in CAT:
            err.append(f"{w}: categoria non ammessa {n.get('categoria')!r}")
        if n.get("zona") not in ZONE:
            err.append(f"{w}: zona non ammessa {n.get('zona')!r}")
        if n.get("stato") not in STATI:
            err.append(f"{w}: stato non ammesso {n.get('stato')!r}")
        if not isinstance(n.get("rilevante"), bool):
            err.append(f"{w}: rilevante deve essere true o false")
        if not ISO.match(str(n.get("pubblicato", ""))):
            err.append(f"{w}: pubblicato non ISO {n.get('pubblicato')!r}")
        if "in_vigore_fino" in n and not GIORNO.match(str(n.get("in_vigore_fino"))):
            err.append(f"{w}: in_vigore_fino deve essere AAAA-MM-GG")
        tl = str(n.get("titolo", "")).lower()
        for b in VIETATE:
            if b in tl:
                err.append(f"{w}: titolo con {b!r}")
        nomi_prima = [f.get("nome") for f in n.get("fonti", [])]
        if len(nomi_prima) != len(set(nomi_prima)):
            err.append(f"{w}: testata ripetuta nelle fonti di prima pagina")
        for f in n.get("fonti", []):
            if vuoto(f.get("nome")) or vuoto(f.get("url")):
                err.append(f"{w}: fonte di prima pagina incompleta {f}")
        if n.get("stato") == "confermata":
            testate = {re.sub(r"\s*\(.*\)$", "", x or "") for x in nomi_prima}
            if len(testate) < 2:
                err.append(f"{w}: 'confermata' con meno di 2 testate")
        a = n.get("articolo") or {}
        if vuoto(a.get("cosa")):
            err.append(f"{w}: articolo.cosa vuoto")
        nomi = [f.get("nome") for f in a.get("fonti", [])]
        if not nomi:
            err.append(f"{w}: articolo.fonti vuoto")
        if len(nomi) != len(set(nomi)):
            err.append(f"{w}: nomi ripetuti in articolo.fonti")
        for f in a.get("fonti", []):
            for k in ("nome", "titolo", "url", "data"):
                if vuoto(f.get(k)):
                    err.append(f"{w}: articolo.fonti {f.get('nome')} senza {k}")
        for sez in ("cronologia", "concordano", "divergono"):
            for x in a.get(sez) or []:
                if vuoto(x.get("fatto" if sez == "cronologia" else "testo")):
                    err.append(f"{w}: {sez} con testo vuoto")
                if sez == "cronologia" and vuoto(x.get("data")):
                    err.append(f"{w}: cronologia senza data")
                if vuoto(x.get("fonti")):
                    err.append(f"{w}: {sez} senza fonti")
                for nm in x.get("fonti", []):
                    if nm not in nomi:
                        err.append(f"{w}: {sez} cita {nm!r} che non è in articolo.fonti")
        url_validi(n, w)

    for ap in d["approfondimenti"]:
        w = ap.get("id", "?")
        for k in ("id", "titolo", "sommario", "luogo", "aggiornato", "collegate", "in_breve", "sezioni", "fonti"):
            if vuoto(ap.get(k)):
                err.append(f"{w}: campo vuoto o mancante {k}")
        if not re.match(r"^[a-z0-9]+(-[a-z0-9]+)*$", str(ap.get("id", ""))):
            err.append(f"{w}: id non valido (solo minuscole, numeri e trattini)")
        if not ISO.match(str(ap.get("aggiornato", ""))):
            err.append(f"{w}: aggiornato non ISO")
        nomi = [f.get("nome") for f in ap.get("fonti", [])]
        if len(nomi) != len(set(nomi)):
            err.append(f"{w}: nomi ripetuti in fonti")
        for f in ap.get("fonti", []):
            for k in ("nome", "titolo", "url", "data"):
                if vuoto(f.get(k)):
                    err.append(f"{w}: fonte {f.get('nome')} senza {k}")

        def citazioni(lst, dove):
            for x in lst or []:
                if vuoto(x.get("fonti")):
                    err.append(f"{w}: {dove} senza fonti")
                for nm in x.get("fonti", []):
                    if nm not in nomi:
                        err.append(f"{w}: {dove} cita {nm!r} che non è nelle fonti")
        citazioni(ap.get("in_breve"), "in_breve")
        for s in ap.get("sezioni", []):
            citazioni(s.get("paragrafi"), "sezione " + str(s.get("titolo")) + "/paragrafi")
            citazioni(s.get("punti"), "sezione " + str(s.get("titolo")) + "/punti")
        citazioni(ap.get("domande"), "domande")
        citazioni(ap.get("cronologia"), "cronologia")
        url_validi(ap, w)


def voce_indice(x, tipo, mese):
    if tipo == "notizia":
        return {"id": x["id"], "tipo": "notizia", "titolo": x.get("titolo", ""), "sintesi": x.get("sintesi", ""),
                "luogo": x.get("luogo", ""), "categoria": x.get("categoria", ""), "zona": x.get("zona", ""),
                "pubblicato": x.get("pubblicato", ""), "cosa": (x.get("articolo") or {}).get("cosa", ""), "mese": mese}
    return {"id": x["id"], "tipo": "approfondimento", "titolo": x.get("titolo", ""), "sintesi": x.get("sommario", ""),
            "luogo": x.get("luogo", ""), "pubblicato": x.get("aggiornato", ""), "cosa": "", "mese": mese}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--prova", action="store_true", help="non scrive niente")
    ap.add_argument("--oggi", help="data AAAA-MM-GG da usare al posto di oggi (prove)")
    ap.add_argument("--cartella", default=os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    a = ap.parse_args()
    base = a.cartella
    oggi = dt.date.fromisoformat(a.oggi) if a.oggi else oggi_roma()
    p_notizie = os.path.join(base, "notizie.json")
    cart_arch = os.path.join(base, "archivio")
    p_indice = os.path.join(cart_arch, "indice.json")

    err, avv = [], []
    try:
        d = leggi(p_notizie)
    except Exception as e:
        print("ERRORE: notizie.json non è un JSON valido:", e)
        sys.exit(1)
    if d is None:
        print("ERRORE: manca notizie.json")
        sys.exit(1)
    controlla(d, err, avv)

    # Archivio esistente: si legge tutto, non si toglie mai niente.
    mesi = {}
    for p in sorted(glob.glob(os.path.join(cart_arch, "[0-9][0-9][0-9][0-9]-[0-9][0-9].json"))):
        try:
            m = leggi(p)
        except Exception as e:
            err.append(f"{os.path.basename(p)} non è un JSON valido: {e}")
            continue
        m.setdefault("notizie", [])
        m.setdefault("approfondimenti", [])
        mesi[os.path.basename(p)[:7]] = m
    originali = {k: testo_json(v) for k, v in mesi.items()}

    in_archivio = {}
    for mese, m in mesi.items():
        for x in m["notizie"] + m["approfondimenti"]:
            if x.get("id") in in_archivio:
                err.append(f"id {x.get('id')!r} doppio nell'archivio ({in_archivio[x.get('id')]} e {mese})")
            in_archivio[x.get("id")] = mese

    correnti = [n.get("id") for n in d.get("notizie", [])] + [x.get("id") for x in d.get("approfondimenti", [])]
    doppi = {i for i in correnti if correnti.count(i) > 1}
    if doppi:
        err.append(f"id doppi in notizie.json: {sorted(doppi)}")
    for i in correnti:
        if i in in_archivio:
            err.append(f"id {i!r} è già usato da una notizia in archivio ({in_archivio[i]}): scegline un altro, "
                       f"per esempio {i}-{oggi.isoformat()}")

    tutti_gli_id = set(correnti) | set(in_archivio)
    for x in d.get("approfondimenti", []):
        for c in x.get("collegate", []):
            if c not in tutti_gli_id:
                err.append(f"{x.get('id')}: notizia collegata {c!r} non esiste")

    if err:
        for x in avv:
            print("AVVISO:", x)
        for x in err:
            print("ERRORE:", x)
        print(f"{len(err)} ERRORI: niente è stato scritto")
        sys.exit(1)

    # Cosa resta in prima pagina e cosa va in archivio.
    soglia_pp = (oggi - dt.timedelta(days=GIORNI_PRIMA_PAGINA - 1)).isoformat()
    soglia_ap = (oggi - dt.timedelta(days=GIORNI_APPROFONDIMENTO)).isoformat()
    restano_ap, vanno_ap = [], []
    for x in d["approfondimenti"]:
        if x.get("archiviato") or x["aggiornato"][:10] < soglia_ap:
            vanno_ap.append(x)
        else:
            restano_ap.append(x)
    collegate_attive = {c for x in restano_ap for c in x.get("collegate", [])}

    restano, vanno = [], []
    for n in d["notizie"]:
        giorno = n["pubblicato"][:10]
        if giorno >= soglia_pp:
            restano.append(n)
        elif n.get("in_vigore_fino") and n["in_vigore_fino"] >= oggi.isoformat():
            restano.append(n)
        elif n["id"] in collegate_attive:
            restano.append(n)
        else:
            vanno.append(n)

    for n in vanno:
        mese = n["pubblicato"][:7]
        x = dict(n)
        x["archiviato_il"] = oggi.isoformat()
        mesi.setdefault(mese, {"notizie": [], "approfondimenti": []})["notizie"].append(x)
        print(f"ARCHIVIATA: {n['id']} ({n['pubblicato'][:10]}) → archivio/{mese}.json")
    for ap_ in vanno_ap:
        mese = ap_["aggiornato"][:7]
        x = dict(ap_)
        x["archiviato"] = True
        x["archiviato_il"] = oggi.isoformat()
        mesi.setdefault(mese, {"notizie": [], "approfondimenti": []})["approfondimenti"].append(x)
        print(f"ARCHIVIATO APPROFONDIMENTO: {ap_['id']} → archivio/{mese}.json")

    nuovo = dict(d)
    nuovo["notizie"] = restano
    nuovo["approfondimenti"] = restano_ap

    # Prima di scrivere: ogni notizia di prima deve stare in prima pagina o in archivio, una volta sola.
    dopo = [n["id"] for n in nuovo["notizie"]] + [x["id"] for x in nuovo["approfondimenti"]]
    for m in mesi.values():
        dopo += [x["id"] for x in m["notizie"] + m["approfondimenti"]]
    for i in set(correnti) | set(in_archivio):
        if dopo.count(i) != 1:
            print(f"ERRORE GRAVE: {i!r} compare {dopo.count(i)} volte dopo l'archiviazione: niente è stato scritto")
            sys.exit(1)

    for m in mesi.values():
        m["notizie"].sort(key=lambda x: x.get("pubblicato", ""), reverse=True)
        m["approfondimenti"].sort(key=lambda x: x.get("aggiornato", ""), reverse=True)
    voci = []
    for mese, m in mesi.items():
        voci += [voce_indice(x, "notizia", mese) for x in m["notizie"]]
        voci += [voce_indice(x, "approfondimento", mese) for x in m["approfondimenti"]]
    voci.sort(key=lambda v: v["pubblicato"], reverse=True)
    indice = {"aggiornato": nuovo.get("aggiornato"), "voci": voci}

    da_scrivere = []
    for mese, m in sorted(mesi.items()):
        t = testo_json(m)
        if originali.get(mese) != t:
            da_scrivere.append((os.path.join(cart_arch, mese + ".json"), t))
    vecchio_indice = leggi(p_indice, {}) if os.path.exists(p_indice) else None
    if vecchio_indice is None or vecchio_indice.get("voci") != voci:
        da_scrivere.append((p_indice, testo_json(indice)))
    if vanno or vanno_ap:
        da_scrivere.append((p_notizie, testo_json(nuovo)))

    print(f"Oggi {oggi.isoformat()}: in prima pagina {len(restano)} notizie e {len(restano_ap)} approfondimenti; "
          f"archiviate ora {len(vanno)} notizie e {len(vanno_ap)} approfondimenti; in archivio in tutto {len(voci)}.")
    for x in avv:
        print("AVVISO:", x)
    # notizie.json va sempre pubblicato: l'agente lo ha appena aggiornato anche quando non si archivia niente
    # (se è uguale a quello online, pubblica.py dice «niente da pubblicare»).
    notizie_da_segnare = not any(p == p_notizie for p, _ in da_scrivere)
    if a.prova:
        for p, _ in da_scrivere:
            print("CAMBIEREBBE:", os.path.relpath(p, base))
        if notizie_da_segnare:
            print("CAMBIEREBBE: notizie.json")
        print("PROVA: niente è stato scritto")
        return
    os.makedirs(cart_arch, exist_ok=True)
    # Prima l'archivio, poi la prima pagina: se qualcosa va storto a metà, una notizia è al massimo in due posti, mai in nessuno.
    for p, t in da_scrivere:
        tmp = p + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(t)
        os.replace(tmp, p)
        print("CAMBIATO:", os.path.relpath(p, base))
    if notizie_da_segnare:
        print("CAMBIATO: notizie.json")
    print("OK")


if __name__ == "__main__":
    main()
