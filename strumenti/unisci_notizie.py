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
Dal 25 ott 2026, col giro lampo che pubblica anche gli articoli dei siti ufficiali (strumenti/ufficiali.py):
- una notizia cambiata da tutte e due le parti tiene i campi del giro lampo cambiati solo dal main (CAMPI_LAMPO:
  «subito», le foto e la locandina arrivate per posta, l'elenco dei «comunicati»), se no si perderebbero la foto e
  l'uscita sui social decise dal giro lampo mentre il giro di ogni ora aggiornava la stessa notizia;
- una notizia nuova nostra che cita tra le fonti la stessa pagina (o viene dallo stesso comunicato) di una notizia
  nuova arrivata dal main è un doppione: resta quella del main (è uscita prima, anche sui social) e la nostra si
  toglie, scrivendolo su stderr. Lo stesso se quella del main l'ha fatta il giro lampo (ha «comunicati»), è della
  stessa sezione e i titoli hanno almeno 3 parole importanti in comune (la Miwa a Ragusa: il giro lampo dal sito della
  Cestistica, il giro di ogni ora da NTR24 Sport); con titoli simili ma senza il giro lampo restano tutte e due, e lo
  si scrive.
Dal 26 ott 2026 (le fonti ufficiali segnate con "ufficiale": true, pagine.vista_ufficiale): una notizia cambiata da
tutte e due le parti tiene anche i segni «ufficiale» che il main ha messo sulle sue fonti (stesso nome), se no il
giro di ogni ora partito prima li cancellerebbe aggiornando la notizia.
Se un file non è un JSON valido esce con errore e git segna il conflitto come prima.

Il giro di ogni ora lo usa così (prompt della routine, punto 7):
  git -c merge.notizie.driver="python3 strumenti/unisci_notizie.py %O %A %B" pull --rebase origin main
In un rebase %A è il main (dove si sta riapplicando il nostro commit) e %B il nostro commit: il risultato va in %A.

Uso a mano:  python3 strumenti/unisci_notizie.py BASE MAIN NOSTRA   (scrive il risultato in MAIN)
"""
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from archivia import testo_json   # noqa: E402  (lo stesso formato del file)

ELENCHI = ("notizie", "approfondimenti")
CAMPI_LAMPO = ("subito", "comunicati", "foto_inviate", "foto_da", "locandina")
_VUOTE = {"della", "delle", "dello", "degli", "dalla", "dalle", "nella", "nelle", "sulla", "sulle", "alla", "alle",
          "benevento", "sannio", "contro", "dopo", "prima", "anche", "oggi", "domani", "ottobre", "novembre", "dicembre"}


def _pagine(n):
    """Le pagine (con un percorso dopo il dominio) citate tra le fonti, come le conta strumenti/comunicati.py."""
    out = set()
    for f in (n.get("fonti") or []) + ((n.get("articolo") or {}).get("fonti") or []):
        u = str((f or {}).get("url") or "").strip().lower() if isinstance(f, dict) else ""
        if re.match(r"^https?://", u):
            u = re.sub(r"[?#].*$", "", re.sub(r"^https?://(www\.)?", "", u)).rstrip("/")
            if "/" in u:
                out.add(u)
    return out


def _parole(t):
    return {w for w in re.findall(r"[a-zà-ù0-9]+", str(t or "").lower()) if (len(w) >= 4 or w.isdigit()) and w not in _VUOTE}


def _doppione(x, y):
    """Perché la notizia x è la stessa di y: «stessa pagina»/«stesso comunicato», «titoli simili», o ''."""
    if _pagine(x) & _pagine(y):
        return "stessa pagina tra le fonti"
    if set(x.get("comunicati") or []) & set(y.get("comunicati") or []):
        return "stesso comunicato"
    a, b = _parole(x.get("titolo")), _parole(y.get("titolo"))
    if x.get("categoria") == y.get("categoria") and len(a & b) >= 3:
        return "titoli simili"
    return ""


def _ufficiali(n):
    """I nomi delle fonti segnate "ufficiale": true (in fonti e in articolo.fonti)."""
    a = n.get("articolo") if isinstance(n.get("articolo"), dict) else {}
    return {f.get("nome") for l in (n.get("fonti"), a.get("fonti")) if isinstance(l, list)
            for f in l if isinstance(f, dict) and f.get("ufficiale") is True}


def _con_ufficiali(x, nomi):
    """x (copia) con "ufficiale": true sulle fonti che si chiamano come in nomi."""
    segna = lambda l: [dict(f, ufficiale=True) if isinstance(f, dict) and f.get("nome") in nomi
                       and f.get("ufficiale") is not True else f for f in l]
    x = dict(x)
    if isinstance(x.get("fonti"), list):
        x["fonti"] = segna(x["fonti"])
    if isinstance(x.get("articolo"), dict) and isinstance(x["articolo"].get("fonti"), list):
        x["articolo"] = dict(x["articolo"], fonti=segna(x["articolo"]["fonti"]))
    return x


def unisci_elenco(base, su, mio):
    B = {x.get("id"): x for x in base}
    U = {x.get("id"): x for x in su}
    M = {x.get("id"): x for x in mio}
    uguale = lambda a, b: json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)
    out = [x for x in su if x.get("id") not in B and x.get("id") not in M]   # nuove dal main: in testa
    nuove_main = list(out)
    for x in mio:
        i = x.get("id")
        if i in B and i not in U and uguale(x, B[i]):
            continue   # tolta dal main (archiviata) e non toccata da noi
        if i in B and i in U and not uguale(U[i], B[i]) and uguale(x, B[i]):
            out.append(U[i])   # cambiata solo dal main
        elif i in B and i in U:   # cambiata da tutte e due: la nostra, coi campi del giro lampo cambiati solo dal main
            x = dict(x)
            for k in CAMPI_LAMPO:
                if not uguale(U[i].get(k), B[i].get(k)) and uguale(x.get(k), B[i].get(k)):
                    if k in U[i]:
                        x[k] = U[i][k]
                    else:
                        x.pop(k, None)
            nuovi = _ufficiali(U[i]) - _ufficiali(B[i])   # i segni «ufficiale» messi dal main
            if nuovi:
                x = _con_ufficiali(x, nuovi)
            out.append(x)
        elif i not in B and i not in U:   # nuova nostra: è lo stesso fatto di una nuova arrivata dal main?
            uguali = [(y, _doppione(x, y)) for y in nuove_main]
            certo = next(((y, p) for y, p in uguali if p in ("stessa pagina tra le fonti", "stesso comunicato")
                          or (p == "titoli simili" and y.get("comunicati"))), None)
            if certo:
                print(f"unisci_notizie: tolta la nostra notizia nuova {i}: è lo stesso fatto di {certo[0].get('id')}, "
                      f"appena pubblicata dal main ({certo[1]})", file=sys.stderr)
                continue
            for y, p in uguali:
                if p:
                    print(f"unisci_notizie: ATTENZIONE, la nostra notizia nuova {i} e {y.get('id')} (dal main) hanno i "
                          "titoli molto simili: se sono lo stesso fatto, al prossimo giro uniscile", file=sys.stderr)
            out.append(x)
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
