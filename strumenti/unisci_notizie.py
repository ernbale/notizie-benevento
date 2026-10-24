#!/usr/bin/env python3
"""Unisce due versioni di notizie.json notizia per notizia (driver di unione di git, vedi .gitattributes).

Serve dal 24 ott 2026, da quando il giro lampo dei comunicati (strumenti/comunicati.py) pubblica in qualsiasi momento,
anche mentre lavora il giro di ogni ora: tutti e due mettono le notizie nuove in testa al file e per git sarebbe un
conflitto, e il giro di ogni ora (che non deve provare altri modi) perderebbe tutto il suo lavoro. Con questo driver:
- una notizia nuova solo da una parte entra (quelle arrivate dal main vanno in testa);
- una notizia cambiata solo da una parte prende quella versione; cambiata da tutte e due, vince la nostra (il giro
  che sta pubblicando: ha letto le fonti adesso);
- una notizia tolta da una parte (archiviata) e non cambiata dall'altra resta tolta;
- gli altri campi come le notizie; «aggiornato» il più recente.
Se un file non è un JSON valido esce con errore e git segna il conflitto come prima.

Il giro di ogni ora lo usa così (prompt della routine, punto 7):
  git -c merge.notizie.driver="python3 strumenti/unisci_notizie.py %O %A %B" pull --rebase origin main
In un rebase %A è il main (dove si sta riapplicando il nostro commit) e %B il nostro commit: il risultato va in %A.

Uso a mano:  python3 strumenti/unisci_notizie.py BASE MAIN NOSTRA   (scrive il risultato in MAIN)
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from archivia import testo_json   # noqa: E402  (lo stesso formato del file)

ELENCHI = ("notizie", "approfondimenti")


def unisci_elenco(base, su, mio):
    B = {x.get("id"): x for x in base}
    U = {x.get("id"): x for x in su}
    M = {x.get("id"): x for x in mio}
    uguale = lambda a, b: json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)
    out = [x for x in su if x.get("id") not in B and x.get("id") not in M]   # nuove dal main: in testa
    for x in mio:
        i = x.get("id")
        if i in B and i not in U and uguale(x, B[i]):
            continue   # tolta dal main (archiviata) e non toccata da noi
        if i in B and i in U and not uguale(U[i], B[i]) and uguale(x, B[i]):
            out.append(U[i])   # cambiata solo dal main
        else:
            out.append(x)
    return out


def unisci(base, su, mio):
    out = dict(mio)
    for k in set(base) | set(su) | set(mio):
        if k in ELENCHI:
            out[k] = unisci_elenco(base.get(k) or [], su.get(k) or [], mio.get(k) or [])
        elif k == "aggiornato":
            out[k] = max(str(su.get(k) or ""), str(mio.get(k) or "")) or None
        elif k not in mio and k in su and k not in base:
            out[k] = su[k]
        elif k in su and json.dumps(mio.get(k), sort_keys=True) == json.dumps(base.get(k), sort_keys=True):
            out[k] = su[k]   # cambiato solo dal main
    return out


def main():
    if len(sys.argv) != 4:
        print(__doc__)
        return 2
    try:
        dati = []
        for p in sys.argv[1:]:
            with open(p, encoding="utf-8") as f:
                dati.append(json.load(f))
    except (OSError, ValueError) as e:
        print(f"unisci_notizie: non riesco a leggere i tre file ({e}): conflitto da risolvere a mano", file=sys.stderr)
        return 1
    risultato = unisci(*dati)
    with open(sys.argv[2], "w", encoding="utf-8") as f:
        f.write(testo_json(risultato))
    return 0


if __name__ == "__main__":
    sys.exit(main())
