#!/usr/bin/env python3
"""Il giro lampo dei comunicati: sul Pi di casa, appena nella casella comunicati@ arriva un comunicato vero, fa
partire subito l'agente che scrive l'articolo e lo pubblica sul sito, e dal sito su Telegram, Facebook e Instagram.

Voluto dal proprietario il 24 ott 2026, dopo il comunicato della CISL FP arrivato alle 11:51 e uscito solo alle 13:06
(preso da NTR24): «questi sono comunicati ufficiali, deve essere istantanea lettura, preparazione articolo,
pubblicazione istantanea Instagram Facebook Telegram… poi su sito… lettura ogni 5 min nessuno sconto… non deve
ricapitare assolutamente».

Il cron lo lancia ogni 5 minuti subito dopo `fonti_casa.py --solo comunicati`, che legge la casella e mette i
comunicati (senza rimbalzi e risposte automatiche) in comunicati.json dell'archivio privato, già pubblicato. Qui:
- un comunicato mai visto → fa partire la routine «giro lampo» (la stessa delle chiusure, con la sua chiave in
  routine.conf: vedetta.py --imposta-avvio) con un testo che comincia con «COMUNICATI»: la routine segue
  COMUNICATI.md del sito;
- un comunicato avviato ma dopo RILANCIA_DOPO minuti non ancora in comunicati_visti.json del sito → la rilancia, al
  massimo RILANCI volte (poi è la sentinella a dare l'allarme, punto 7);
- la prima volta prende solo nota dei comunicati che ci sono già: non sono nuovi.
Scrive nel registro (comunicati.log) solo quando fa qualcosa o qualcosa non va. Stato in comunicati_lampo.json.

Dal 25 ott 2026 (lui: «dobbiamo recuperare qualche minuto, dobbiamo arrivare prima») anche gli articoli nuovi dei siti
ufficiali (ufficiali.json dell'archivio, li trova strumenti/ufficiali.py ogni 5 minuti; `tipo` = «sito»), con le stesse
regole. Ma quelli li legge anche il giro di ogni ora (alle :06, dalle 6 alle 22), e se lo stesso articolo lo scrivessero
tutti e due sarebbe un doppione: un articolo dei siti ufficiali che arriva tra le :04 e le :25 (ATTESA) aspetta che il
giro di quell'ora abbia pubblicato (il commit «Notizie delle HH:» sul main) o le :25; poi il giro lampo lo trova già
sul sito («gia_nel_sito», ed esce subito sui social) o lo pubblica. I comunicati per posta non aspettano mai.

Uso sul Pi:  python3 ~/nb-fonti/sentinella/comunicati_lampo.py              (dal cron, ogni 5 minuti)
             python3 ~/nb-fonti/sentinella/comunicati_lampo.py --prova      (dice cosa farebbe, senza avviare)
             python3 ~/nb-fonti/sentinella/comunicati_lampo.py --prova-avvio (prova antincendio del giro lampo)
"""
import argparse
import datetime as dt
import json
import os
import sys

QUI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, QUI)
import vedetta as V   # noqa: E402  (chiave della routine, archivio, GitHub: tutto come la vedetta)

STATO = os.path.join(V.CARTELLA, "comunicati_lampo.json")
COMUNICATI = os.path.join(V.F.ARCHIVIO, "comunicati.json")
UFFICIALI = os.path.join(V.F.ARCHIVIO, "ufficiali.json")   # gli articoli dei siti ufficiali (strumenti/ufficiali.py)
GIRO_ORE = range(6, 23)   # il giro di ogni ora parte alle :06, dalle 6 alle 22
ATTESA = (4, 25)          # minuti dell'ora in cui un articolo dei siti ufficiali aspetta il giro di ogni ora
RILANCIA_DOPO = 15   # minuti
RILANCI = 3          # avvii in tutto per un comunicato


def visti_sul_sito():
    """id → esito dei comunicati già trattati (comunicati_visti.json del sito su GitHub)."""
    from sentinella import GitHub, leggi_chiave
    gh = GitHub(leggi_chiave(os.path.join(V.CARTELLA, "github.conf")))
    d = json.loads(gh.chiama("GET", f"repos/{V.REPO}/contents/comunicati_visti.json?ref=main", grezzo=True))
    return d.get("visti") or {}


def giro_dell_ora_fatto(adesso):
    """Il giro di ogni ora di quest'ora ha già pubblicato? (un commit «Notizie delle HH:» sul main da HH:00)"""
    from sentinella import GitHub, leggi_chiave
    gh = GitHub(leggi_chiave(os.path.join(V.CARTELLA, "github.conf")))
    dal = adesso.replace(minute=0, second=0, microsecond=0).astimezone(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    commit = gh.chiama("GET", f"repos/{V.REPO}/commits?sha=main&since={dal}&per_page=50")
    return any(str((x.get("commit") or {}).get("message", "")).startswith(f"Notizie delle {adesso:%H}:") for x in commit)


def aspetta_il_giro(adesso, fatto):
    """Un articolo dei siti ufficiali deve aspettare il giro di ogni ora? fatto() lo chiede a GitHub (solo se serve):
    se GitHub non risponde si aspetta, al massimo fino alle :25."""
    if adesso.hour not in GIRO_ORE or not ATTESA[0] <= adesso.minute < ATTESA[1]:
        return False
    try:
        return not fatto()
    except Exception as e:
        print(f"{adesso:%d/%m %H:%M} non so se il giro di ogni ora ha pubblicato ({type(e).__name__}: {e}): aspetto")
        return True


def testo_avvio(voci, prova=False):
    righe = [f"- [{v['id']}] {v.get('data', '')[11:16]} · "
             + ("dal sito ufficiale di " if v.get("tipo") == "sito" else "") + f"{v.get('mittente', '')} "
             f"({v.get('dominio', '')}) · {v.get('titolo', '')[:150]}" for v in voci]
    testa = ("COMUNICATI PROVA ANTINCENDIO dal Pi: nessun comunicato vero. Fai il giro in modalità prova, come dice "
             "COMUNICATI.md." if prova else
             f"COMUNICATI: {len(voci)} da trattare subito, come dice COMUNICATI.md (i testi veri li legge "
             "strumenti/comunicati.py --da-fare; queste righe sono solo un promemoria).")
    return testa + ("\n" + "\n".join(righe) if righe else "")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--prova", action="store_true", help="dice cosa farebbe, senza avviare né scrivere")
    ap.add_argument("--prova-avvio", action="store_true", help="fa partire il giro lampo in prova")
    a = ap.parse_args()
    adesso = V.adesso_roma()
    ora = f"{adesso:%d/%m %H:%M}"
    if a.prova_avvio:
        print(f"{ora} prova antincendio comunicati: {V.avvia(testo_avvio([], prova=True))}")
        return
    voci = [v for p in (COMUNICATI, UFFICIALI) for v in (V.leggi(p, {}).get("voci") or []) if v.get("id")]
    stato = V.leggi(STATO, None)
    if stato is None:   # la prima volta: quelli che ci sono già non sono nuovi
        stato = {"lanciati": {v["id"]: {"primo": None, "volte": 0, "gia": True} for v in voci}}
        if not a.prova:
            V.scrivi(STATO, stato)
        print(f"{ora} prima volta: {len(voci)} comunicati già presenti segnati come visti")
        return
    lanciati = stato.setdefault("lanciati", {})
    nuovi = [v for v in voci if v["id"] not in lanciati]
    attesa = [v for v in voci if v["id"] in lanciati and not lanciati[v["id"]].get("gia")
              and lanciati[v["id"]]["volte"] < RILANCI
              and adesso - dt.datetime.fromisoformat(lanciati[v["id"]]["ultimo"]) >= dt.timedelta(minutes=RILANCIA_DOPO)]
    rilanci = []
    if attesa:
        try:
            visti = visti_sul_sito()
            rilanci = [v for v in attesa if v["id"] not in visti]
        except Exception as e:   # senza la risposta di GitHub non si rilancia (meglio che un doppio giro)
            print(f"{ora} ERRORE: non leggo comunicati_visti.json del sito ({type(e).__name__}: {e})")
    da_fare = nuovi + rilanci
    if any(v.get("tipo") == "sito" for v in da_fare):
        fatto = {}
        if aspetta_il_giro(adesso, lambda: fatto.setdefault("f", giro_dell_ora_fatto(adesso))):
            ferme = [v for v in da_fare if v.get("tipo") == "sito"]
            attese = stato.setdefault("attese", {})
            nuove_attese = [v for v in ferme if v["id"] not in attese]
            for v in nuove_attese:
                attese[v["id"]] = adesso.isoformat(timespec="minutes")
            if nuove_attese and not a.prova:
                V.scrivi(STATO, stato)
            if nuove_attese:
                print(f"{ora} aspettano il giro delle {adesso:%H}:06 (niente doppioni): "
                      + ", ".join(f"{v['id']} «{v.get('titolo', '')[:60]}»" for v in nuove_attese))
            da_fare = [v for v in da_fare if v.get("tipo") != "sito"]
    if not da_fare:
        return
    nomi = ", ".join(f"{v['id']} «{v.get('titolo', '')[:60]}»" for v in da_fare)
    if a.prova:
        print(f"{ora} PROVA: avvierei il giro lampo per {nomi}")
        return
    try:
        sessione = V.avvia(testo_avvio(da_fare))
    except Exception as e:   # riprova al giro dopo (fra 5 minuti): lo stato non cambia
        print(f"{ora} ERRORE: giro lampo non avviato ({e}) per {nomi}")
        sys.exit(1)
    for v in da_fare:
        x = lanciati.setdefault(v["id"], {"primo": adesso.isoformat(timespec="minutes"), "volte": 0})
        x["volte"] += 1
        x["ultimo"] = adesso.isoformat(timespec="minutes")
    limite = (adesso - dt.timedelta(days=10)).isoformat()
    stato["lanciati"] = {k: x for k, x in lanciati.items() if x.get("gia") or (x.get("ultimo") or "") >= limite
                         or k in {v["id"] for v in voci}}
    stato["attese"] = {k: q for k, q in (stato.get("attese") or {}).items() if k not in lanciati and q >= limite}
    V.scrivi(STATO, stato)
    print(f"{ora} giro lampo avviato ({'nuovi' if nuovi else 'rilancio'}): {nomi} → {sessione}")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"{dt.datetime.now():%d/%m %H:%M} ERRORE: {type(e).__name__}: {e}")
        sys.exit(1)
