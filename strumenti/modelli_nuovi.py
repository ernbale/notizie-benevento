#!/usr/bin/env python3
"""Sul Pi di casa, una volta al giorno: guarda se Anthropic ha pubblicato modelli Claude nuovi e, se sì, avvisa il
proprietario su WhatsApp e per email (sentinella.manda_a_casa).

Voluto dal proprietario il 27 ott 2026: «nominiamo Fable 5.1 come scrittore giornalista ufficiale del nostro
giornale? da controllare ogni giorno se escono modelli nuovi per migliorare sempre di più». Il programma non cambia
niente da solo: un modello nuovo si prova prima sui dati veri e poi decide lui quale usano le routine.

Legge la pagina pubblica dei modelli (niente chiavi) e ne tira fuori gli identificativi («claude-fable-5-1»…); li
confronta con quelli già visti (modelli.json nella cartella del Pi). Il primo giro li impara soltanto. Se la pagina
non si legge o non ha più identificativi per 3 giorni di fila, arriva un solo avviso: va sistemato il programma.

Uso sul Pi:  python3 ~/nb-fonti/sentinella/modelli_nuovi.py [--prova]
"""
import argparse
import datetime as dt
import json
import os
import re
import sys
import urllib.request

QUI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, QUI)

CARTELLA = os.environ.get("NB_FONTI_CARTELLA") or os.path.expanduser("~/nb-fonti")
STATO = os.path.join(CARTELLA, "modelli.json")
PAGINA = "https://platform.claude.com/docs/en/about-claude/models/overview"
ID = re.compile(r"\bclaude-[a-z]+-\d+(?:-\d+)?\b")
ERRORI_PRIMA_DI_AVVISARE = 3


def modelli_sulla_pagina():
    """Gli identificativi dei modelli sulla pagina, dal più citato (i modelli di oggi stanno in tutte le tabelle)."""
    req = urllib.request.Request(PAGINA, headers={"User-Agent": "Mozilla/5.0 (notiziebenevento.it)"})
    with urllib.request.urlopen(req, timeout=60) as r:
        pagina = r.read().decode("utf-8", "replace")
    conta = {}
    for m in ID.findall(pagina):
        conta[m] = conta.get(m, 0) + 1
    return sorted(conta, key=lambda m: (-conta[m], m))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--prova", action="store_true", help="dice cosa manderebbe, senza mandare né salvare niente")
    a = ap.parse_args()
    adesso = dt.datetime.now().astimezone().isoformat(timespec="minutes")
    try:
        with open(STATO, encoding="utf-8") as f:
            stato = json.load(f)
    except (OSError, ValueError):
        stato = {}
    visti = stato.get("visti") or []

    try:
        trovati = modelli_sulla_pagina()
        if not trovati:
            raise RuntimeError("nessun identificativo claude-… sulla pagina (è cambiata?)")
    except Exception as e:
        errori = int(stato.get("errori_di_fila") or 0) + 1
        print(f"{adesso} modelli: pagina non letta ({type(e).__name__}: {str(e)[:150]}), "
              f"{'il primo giorno' if errori == 1 else f'{errori} giorni di fila'}")
        if a.prova:
            return 1
        stato["errori_di_fila"] = errori
        if errori == ERRORI_PRIMA_DI_AVVISARE:
            from sentinella import manda_a_casa
            esiti = manda_a_casa(f"⚠️ Il controllo dei modelli Claude nuovi non riesce a leggere la pagina di Anthropic "
                                 f"da {errori} giorni ({type(e).__name__}). Va sistemato modelli_nuovi.py sul Pi.\n{PAGINA}",
                                 "⚠️ Controllo dei modelli Claude fermo")
            print(f"{adesso} modelli: avviso del controllo fermo: {', '.join(esiti)}")
        with open(STATO, "w", encoding="utf-8") as f:
            json.dump(stato, f, ensure_ascii=False, indent=1)
        return 1

    nuovi = [m for m in trovati if m not in visti]
    if not visti:
        print(f"{adesso} modelli: primo giro, imparati {len(trovati)}: {', '.join(trovati)}")
    elif nuovi:
        testo = (f"🆕 Anthropic ha pubblicato {'un modello nuovo' if len(nuovi) == 1 else f'{len(nuovi)} modelli nuovi'}: "
                 f"{', '.join(nuovi)}.\n\nPer Notizie Benevento non cambia niente da solo: prima si prova sui dati veri "
                 f"e poi decidi tu se diventa lo scrittore del giornale.\n\nI modelli e a cosa servono: {PAGINA}")
        if a.prova:
            print(f"{adesso} modelli: manderei\n{testo}")
            return 0
        from sentinella import manda_a_casa
        esiti = manda_a_casa(testo, f"🆕 Modello Claude nuovo: {', '.join(nuovi)}")
        print(f"{adesso} modelli: nuovi {', '.join(nuovi)}: {', '.join(esiti)}")
        if not any(e in ("WhatsApp mandato", "email mandata") for e in esiti):
            trovati = [m for m in trovati if m not in nuovi]   # avviso non arrivato: domani si riprova
    else:
        print(f"{adesso} modelli: niente di nuovo ({len(trovati)} sulla pagina; i primi: {', '.join(trovati[:4])})")
    if a.prova:
        return 0
    stato.update({"visti": sorted(set(visti) | set(trovati)), "ultimo_controllo": adesso, "errori_di_fila": 0,
                  "sulla_pagina": trovati})
    with open(STATO, "w", encoding="utf-8") as f:
        json.dump(stato, f, ensure_ascii=False, indent=1)
    return 0


if __name__ == "__main__":
    sys.exit(main())
