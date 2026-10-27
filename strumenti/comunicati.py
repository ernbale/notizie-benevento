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

Dal 25 ott 2026 (lui: «dobbiamo recuperare qualche minuto, dobbiamo arrivare prima») arrivano qui anche gli articoli
nuovi dei siti ufficiali (società sportive, Comune e Provincia di Benevento, ASL, acqua, trasporti): li trova il Pi ogni 5
minuti (strumenti/ufficiali.py, file ufficiali.json dell'archivio) e hanno `tipo` = «sito», il `link` della pagina e un
id che comincia con «u». Si trattano come i comunicati (stessi esiti, stesso comunicati_visti.json); in più qui si
controlla che la notizia pubblicata citi quel link tra le fonti, e per tutte che una notizia nuova non citi una pagina
già citata da una notizia della prima pagina (sarebbe un doppione: va «gia_nel_sito»).

Il file per --unisci:
{"notizie": [ {una notizia completa come in AGENTE.md, «comunicati»: ["id del comunicato"]} ],
 "eventi": [ {un evento completo come in AGENTE.md} ],   (facoltativo)
 "esiti": [ {"comunicato": "id", "esito": "pubblicato", "notizia": "id della notizia nuova"},
            {"comunicato": "id", "esito": "gia_nel_sito", "notizia": "id della notizia che c'è già"},
            {"comunicato": "id", "esito": "gia_nel_sito", "notizia": "id", "foto_inviate": ["id/1", "id/2"],
             "foto_da": "chi firma il comunicato"},   (le foto o la locandina della mail sulla notizia che c'è già)
            {"comunicato": "id", "esito": "scartato", "motivo": "perché non si pubblica"},
            {"comunicato": "id", "esito": "sospeso", "motivo": "cosa non si legge e perché non basta il resto"} ]}
«sospeso» (dal 26 ott 2026, dopo il comunicato del San Pio perso perché era solo in un .doc): un comunicato con
«allegati_non_letti» (il Pi non è riuscito a leggerli, strumenti/allegati.py) che senza quegli allegati non si può
scrivere. Non si scarta: resta in sospeso, la sentinella del Pi avvisa il proprietario finché qualcuno non lo sistema, e
quando il Pi riesce a rileggerlo (riletto) torna da solo tra quelli da fare. Un comunicato con allegati non letti si può
scartare solo se si capisce anche senza (fuori provincia, pubblicità…): "senza_allegati": "perché basta il resto".
Con «pubblicato» i prezzi, le percentuali, gli orari e le date del testo del comunicato devono stare nella notizia o nel
suo evento (dati_mancanti, dal 26 ott 2026); uno che al lettore proprio non serve va nell'esito con il perché:
"tralasciati": {"18 ottobre": "è il giorno della riunione di prima, non dell'evento"}.
Ogni comunicato di --da-fare deve avere il suo esito. Il motivo resta nel resoconto del giro: comunicati_visti.json
(pubblico) tiene solo id, esito, notizia e ora. Con «gia_nel_sito» la notizia della prima pagina prende «subito» (Facebook
e Instagram la pubblicano adesso, se non c'è già) e l'id del comunicato in «comunicati»; con "locandina", "foto_inviate"
e "foto_da" nell'esito anche le immagini della mail (voluto dal proprietario il 25 ott 2026: «se mandano foto usale»,
«anche più foto se ci sono», «avevamo detto comunicati da pubblicare subito»).

Dal 26 ott 2026 escono subito solo i comunicati delle fonti ufficiali (lui: «la pubblicazione dei comunicati
istantanea solo da fonti ufficiali, un tizio che manda qualcosa dobbiamo valutarla»): quelli con "fonte": "da_valutare"
(fonti_casa.fonte_mittente) qui non ci sono finché il proprietario non li approva nella scheda Posta ("valutato":
"pubblica").

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
ESITI = ("pubblicato", "gia_nel_sito", "scartato", "sospeso")
ORE_SIMILI = 3   # una notizia nuova si confronta coi titoli delle notizie uscite nelle ultime 3 ore
IMMAGINI = {"locandina", "foto_inviate", "foto_da"}   # con «gia_nel_sito» si aggiungono alla notizia che c'è già
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


def comunicati(nome="comunicati.json"):
    """Un file dell'archivio di casa (accanto al sito, o in /home/user nel cloud): comunicati.json (la posta) o
    ufficiali.json (gli articoli dei siti ufficiali, strumenti/ufficiali.py)."""
    for base in (os.environ.get("NB_FONTI_ARCHIVIO") or G.FONTI_CASA, "/home/user/notizie-benevento-fonti"):
        d = leggi(os.path.join(base, nome), None)
        if isinstance(d, dict):
            return d
    return {}


def tutte_le_voci():
    """I comunicati per posta e, dal 25 ott 2026, gli articoli nuovi dei siti ufficiali (`tipo` = «sito»)."""
    return [v for nome in ("comunicati.json", "ufficiali.json") for v in comunicati(nome).get("voci") or []
            if isinstance(v, dict)]


def con_percorso(u):
    """L'indirizzo di una pagina (con un percorso dopo il dominio), normalizzato: la homepage di un sito non conta."""
    n = G.norma_url(u)
    return n if re.match(r"^https?://", str(u or "").strip(), re.I) and "/" in n else ""


def link_di(n):
    """Gli indirizzi di pagina che una notizia cita tra le fonti (prima pagina e articolo)."""
    return {con_percorso(f.get("url")) for f in (n.get("fonti") or []) + ((n.get("articolo") or {}).get("fonti") or [])
            if isinstance(f, dict)} - {""}


def quando_di(n):
    """L'ultima volta che una notizia è uscita o cambiata (pubblicato o il suo «aggiornamento»), con il fuso; None se
    non si sa (le notizie vecchie hanno solo il giorno)."""
    out = None
    for s in (n.get("pubblicato"), ((n.get("articolo") or {}).get("aggiornamento") or {}).get("quando")):
        try:
            t = dt.datetime.fromisoformat(str(s))
        except ValueError:
            continue
        if t.tzinfo and (out is None or t > out):
            out = t
    return out


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


def in_attesa(v):
    """Un comunicato di un mittente non ufficiale che il proprietario non ha ancora approvato (fonti_casa.fonte_mittente:
    «"fonte": "da_valutare"», dal 26 ott 2026), o che ha deciso di non pubblicare: qui non si tratta."""
    return v.get("fonte") == "da_valutare" and v.get("valutato") != "pubblica"


def ripreso(v, visti):
    """Un comunicato in sospeso che il Pi ha riletto e ora legge tutto: torna da fare."""
    return (visti.get(v.get("id")) or {}).get("esito") == "sospeso" and bool(v.get("riletto")) \
        and not v.get("allegati_non_letti")


def da_fare(adesso):
    c, u = comunicati(), comunicati("ufficiali.json")
    visti = leggi(FILE, {}).get("visti") or {}
    limite = (adesso - dt.timedelta(days=GIORNI_DA_FARE)).isoformat()
    voci = [v for v in tutte_le_voci() if v.get("id") and (v["id"] not in visti or ripreso(v, visti))
            and (v.get("arrivata") or v.get("data") or "") >= limite and not in_attesa(v)]
    notizie = leggi(NOTIZIE, {}).get("notizie") or []
    citati = G.citati()
    print(f"Ora: {adesso:%Y-%m-%d %H:%M}")
    print(f"Casella comunicati@: ultimo controllo del Pi {c.get('controllato') or 'mai'} · {c.get('esito') or '?'}")
    print(f"Siti ufficiali: ultimo controllo del Pi {u.get('controllato') or 'mai'} · {u.get('esito') or '?'}")
    print(f"Comunicati da trattare: {len(voci)}")
    for v in voci:
        if v.get("tipo") == "sito":
            print(f"\n[{v['id']}] ARTICOLO DEL SITO UFFICIALE di {v.get('mittente')}: uscito {v.get('data')}, visto dal "
                  f"Pi {v.get('arrivata')}\n  link (è la fonte da citare): {v.get('link')}")
            print(f"  titolo: {v.get('titolo')}")
            gia = citati.get(G.norma_url(v.get("link") or ""))
            if gia:
                print(f"  GIÀ SUL SITO, STESSO LINK: la notizia {gia} cita già questo articolo → «gia_nel_sito»")
        else:
            print(f"\n[{v['id']}] arrivato {v.get('arrivata') or v.get('data')} · da {v.get('mittente')} "
                  f"(dominio {v.get('dominio')})" + (f" · allegati: {', '.join(v['allegati'])}" if v.get("allegati") else ""))
            print(f"  oggetto: {v.get('titolo')}")
            if v.get("fonte") == "da_valutare" and v.get("valutato") == "pubblica":
                print(f"  APPROVATO DAL PROPRIETARIO: mittente non ufficiale ({v.get('fonte_perche')}), l'ha letto lui nella "
                      "scheda Posta e vuole che esca: trattalo come gli altri (le regole di sempre valgono)")
            if ripreso(v, visti):
                print("  ERA IN SOSPESO: adesso il Pi ha letto gli allegati che mancavano (riletto "
                      f"{str(v.get('riletto'))[:16]}): trattalo come nuovo")
            if v.get("allegati_non_letti"):
                print("  ALLEGATI NON LETTI dal Pi: " + "; ".join(v["allegati_non_letti"]) + "\n    Se il testo della mail, "
                      "gli altri allegati e le immagini non bastano per l'articolo, l'esito è «sospeso» (non «scartato»): "
                      "COMUNICATI.md, punto 3")
            if v.get("link_file"):
                print("  LINK A FILE nel testo (il comunicato può essere lì: aprili con WebFetch): " + ", ".join(v["link_file"]))
            if v.get("testo_tagliato"):
                print(f"  TESTO TAGLIATO: qui sotto ci sono i primi caratteri di {v['testo_tagliato']}")
        for n in simili(v, notizie, adesso):
            print(f"  POSSIBILE STESSO FATTO già sul sito: {n['id']} · {n.get('pubblicato', '')[:16]} · {n.get('titolo')}")
        for k, im in enumerate(v.get("immagini") or [], 1):   # le locandine: guardale (Read) prima di usarle
            print(f"  immagine {v['id']}/{k}: {os.path.join(A.archivio_fonti() or '', im.get('file', ''))} "
                  f"({im.get('da')}, {im.get('larghezza')}×{im.get('altezza')})")
        print(("  testo del feed (può essere solo l'inizio: leggi la pagina intera dal link):\n    "
               if v.get("tipo") == "sito" else "  testo:\n    ") + str(v.get("testo") or "").strip().replace("\n", "\n    "))
    print("\n" + (f"DA FARE: {len(voci)} comunicati" if voci else "NIENTE DA FARE: nessun comunicato nuovo"))


def scegli_foto_nuova(n, notizie):
    """La versione della foto del tema per la sola notizia nuova: la meno usata in prima pagina (le altre non si
    toccano, le sistema il giro di ogni ora)."""
    v = A.versioni_foto(n.get("immagine") or "") if n.get("categoria") != "cronaca" else []
    n.pop("foto", None)
    if v:
        usate = [x.get("foto") for x in notizie]
        n["foto"] = min(v, key=lambda x: (usate.count(x), hashlib.md5((n["id"] + x).encode()).hexdigest()))


# La prova al contrario fatta dal programma (voluta dal proprietario il 26 ott 2026: «nessuna figuraccia nel nostro
# articolo»): i dati che si riconoscono da soli nel testo del comunicato (prezzi, percentuali, orari, date) devono
# stare nella notizia o nel suo evento. La locandina è un'immagine e qui non si legge: quella la guarda il revisore
# (COMUNICATI.md, punto 4).
MESI = ("gennaio", "febbraio", "marzo", "aprile", "maggio", "giugno", "luglio", "agosto", "settembre", "ottobre",
        "novembre", "dicembre")
NON_TESTO = {"id", "url", "link", "foto", "immagine", "locandina", "foto_inviate", "comunicati", "fonti"}


def numero(s):
    if re.fullmatch(r"\d{1,3}(\.\d{3})+(,\d+)?", s):   # 1.500 è mille e cinquecento
        s = s.replace(".", "")
    return float(s.replace(",", "."))


def dati_del_testo(t, nostro=False):
    """{chiave confrontabile: come è scritto} dei prezzi, delle percentuali, degli orari e delle date di un testo.
    Con nostro=True (il nostro articolo) gli orari si riconoscono anche scritti a parole («dalle 19», «a mezzogiorno»)."""
    t = str(t or "").lower().replace(" ", " ")
    # «10 mila 800 euro» sono 10.800 euro, non 800 (26 ott 2026: falso allarme sul bonus luce e gas del Comune)
    t = re.sub(r"\b(\d{1,3})\s+mila\s+(\d{1,3})\b", lambda m: str(int(m.group(1)) * 1000 + int(m.group(2))), t)
    t = re.sub(r"\b(\d{1,3})\s+mila\b", lambda m: str(int(m.group(1)) * 1000), t)
    out = {}
    for m in re.finditer(r"€\s*(\d[\d.,]*\d|\d)|\b(\d[\d.,]*\d|\d)\s*(?:€|euro\b)", t):
        out.setdefault(("prezzo", numero(m.group(1) or m.group(2))), m.group(0).strip())
    for m in re.finditer(r"\b(\d+(?:[.,]\d+)?)\s*(?:%|per\s*cento\b)", t):
        out.setdefault(("percentuale", numero(m.group(1))), m.group(0).strip())
    for m in re.finditer(r"\b([01]?\d|2[0-4])[:.]([0-5]\d)\b(?![.,]\d)", t):
        out.setdefault(("ora", int(m.group(1)) % 24, int(m.group(2))), m.group(0))
    parola = r"\b(?:ore|alle|dalle|le|entro le|fino alle|verso le)" if nostro else r"\bore"
    for m in re.finditer(parola + r"\s+([01]?\d|2[0-4])\b(?![:.]\d)", t):
        out.setdefault(("ora", int(m.group(1)) % 24, 0), m.group(0))
    if nostro:
        out.update({("ora", 12, 0): "mezzogiorno"} if "mezzogiorno" in t else {})
        out.update({("ora", 0, 0): "mezzanotte"} if "mezzanotte" in t else {})
    for m in re.finditer(r"\b([0-3]?\d)(?:°|º)?\s+(" + "|".join(MESI) + r")\b", t):
        out.setdefault(("data", int(m.group(1)), MESI.index(m.group(2)) + 1), m.group(0))
    for m in re.finditer(r"\b([0-3]?\d)/([01]?\d)(?:/(?:\d{4}|\d{2}))?\b", t):
        if 1 <= int(m.group(1)) <= 31 and 1 <= int(m.group(2)) <= 12:
            out.setdefault(("data", int(m.group(1)), int(m.group(2))), m.group(0))
    for m in re.finditer(r"\b\d{4}-([01]\d)-([0-3]\d)\b", t):   # le date dei campi dell'evento
        out.setdefault(("data", int(m.group(2)), int(m.group(1))), m.group(0))
    return out


def testi(x):
    """Tutti i testi che il lettore vede di una notizia o di un evento (non gli indirizzi, gli id e i nomi delle fonti)."""
    if isinstance(x, str):
        return [x]
    if isinstance(x, list):
        return [s for y in x for s in testi(y)]
    if isinstance(x, dict):
        return [s for k, y in x.items() if k not in NON_TESTO for s in testi(y)]
    return []


CITAZIONE = re.compile(r"^(?:(?:da|from):?\s.*notiziebenevento\.it|(?:il giorno|on)\s.*(?:ha scritto|wrote):?\s*$|"
                       r"-{2,}\s*(?:messaggio originale|original message))", re.I | re.M)


def senza_citazione(t):
    """Il testo di una risposta senza la nostra mail citata sotto (conta solo quello che hanno scritto loro)."""
    m = CITAZIONE.search(t)
    return t[:m.start()] if m else t


OCR = re.compile(r"^\[(?:allegato|immagine) [^\n]*lett[oa] con l'OCR[^\n]*\]\n.*?(?=^\[|\Z)", re.M | re.S)


def senza_ocr(t):
    """Il testo senza le parti lette con l'OCR (strumenti/allegati.py): possono avere numeri letti male."""
    return OCR.sub("", t)


def dati_mancanti(voce, n, eventi, tralasciati):
    """Come sono scritti nel comunicato i dati che nella notizia e nei suoi eventi non ci sono. Il giorno in cui è
    arrivato il comunicato (la data in fondo alla lettera) non conta; quelli in «tralasciati» dell'esito nemmeno."""
    nostri = {}
    for s in testi(n) + testi(eventi) + list(tralasciati):
        nostri.update(dati_del_testo(s, nostro=True))
    try:
        giorno = dt.date.fromisoformat(str(voce.get("arrivata") or voce.get("data") or "")[:10])
        nostri[("data", giorno.day, giorno.month)] = ""
    except ValueError:
        pass
    suoi = dati_del_testo(str(voce.get("titolo") or "") + "\n" + senza_ocr(senza_citazione(str(voce.get("testo") or ""))))
    return [scritto for k, scritto in suoi.items() if k not in nostri]


def unisci(d, visti, entrata, voci, adesso, err):
    """Mette le notizie nuove in testa a d e gli esiti in visti. Restituisce i titoli pubblicati."""
    nuove = entrata.get("notizie") or []
    esiti = entrata.get("esiti") or []
    if not isinstance(nuove, list) or not isinstance(esiti, list):
        err.append("«notizie» ed «esiti» devono essere elenchi")
        return []
    ids_voci = {v["id"] for v in voci if v.get("id")}
    per_voce = {v["id"]: v for v in voci if v.get("id")}
    attuali = {n.get("id") for n in d.get("notizie", []) + d.get("approfondimenti", [])}
    prima = {n.get("id"): n for n in d.get("notizie", [])}
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
        elif in_attesa(per_voce[cid]):
            err.append(f"{w}: è di un mittente non ufficiale che il proprietario deve ancora valutare (o ha scartato): "
                       "non si tratta qui")
        elif es == "pubblicato":
            if e.get("notizia") not in per_id:
                err.append(f"{w}: la notizia {e.get('notizia')!r} non è tra le «notizie» del file")
            else:
                pubblicate.add(e["notizia"])
                per_id[e["notizia"]].setdefault("comunicati", [])
                if cid not in per_id[e["notizia"]]["comunicati"]:
                    per_id[e["notizia"]]["comunicati"].append(cid)
                link = con_percorso(per_voce[cid].get("link")) if per_voce[cid].get("tipo") == "sito" else ""
                if link and link not in link_di(per_id[e["notizia"]]):
                    err.append(f"{w}: è un articolo del sito di {per_voce[cid].get('mittente')}: mettilo tra le fonti "
                               f"della notizia col suo link ({per_voce[cid].get('link')})")
                tral = e.get("tralasciati") or {}
                if not isinstance(tral, dict) or any(len(str(m or "").strip()) < 10 for m in tral.values()):
                    err.append(f"{w}: «tralasciati» è {{\"il dato come è scritto nel comunicato\": \"perché al lettore "
                               "non serve\"}, con un perché vero")
                elif per_voce[cid].get("tipo") != "sito":
                    eventi = [x for x in entrata.get("eventi") or [] if isinstance(x, dict)
                              and x.get("notizia") == e["notizia"]]
                    manca = dati_mancanti(per_voce[cid], per_id[e["notizia"]], eventi, tral)
                    if manca:
                        err.append(f"{w}: nel comunicato c'è {', '.join('«' + x + '»' for x in manca)} e nella notizia "
                                   "(e nel suo evento) no. Rileggi il comunicato: se serve al lettore aggiungilo, "
                                   "scritto uguale e legato alla cosa giusta; se proprio non serve (una data passata, "
                                   "un orario della conferenza stampa) scrivi nell'esito \"tralasciati\": "
                                   "{\"<il dato>\": \"perché\"} (COMUNICATI.md, punto 4)")
        elif es == "gia_nel_sito" and e.get("notizia") not in attuali | in_archivio:
            err.append(f"{w}: la notizia {e.get('notizia')!r} non c'è né in prima pagina né in archivio")
        elif es == "gia_nel_sito" and IMMAGINI & e.keys() and e.get("notizia") not in prima:
            err.append(f"{w}: la notizia {e.get('notizia')!r} è in archivio: le foto si aggiungono solo in prima pagina")
        if es != "gia_nel_sito" and IMMAGINI & e.keys():
            err.append(f"{w}: locandina e foto vanno nella notizia («notizie»); nell'esito solo con «gia_nel_sito»")
        elif es in ("scartato", "sospeso") and len(str(e.get("motivo") or "").strip()) < 10:
            err.append(f"{w}: scrivi il «motivo» (serve al resoconto)")
        elif (es == "scartato" and per_voce[cid].get("allegati_non_letti")
              and len(str(e.get("senza_allegati") or "").strip()) < 10):
            # il San Pio, 26 ott 2026: scartato perché il testo era in un .doc che il Pi non leggeva, e nessuno l'ha più visto
            err.append(f"{w}: il Pi non ha letto {'; '.join(per_voce[cid]['allegati_non_letti'])}. Se il comunicato senza "
                       "quegli allegati non si capisce l'esito è «sospeso» (la sentinella avvisa il proprietario); "
                       "si scarta solo se basta il resto, col perché in \"senza_allegati\"")
        elif es == "sospeso" and not per_voce[cid].get("allegati_non_letti"):
            err.append(f"{w}: «sospeso» è solo per i comunicati con allegati che il Pi non ha letto")
    for i in per_id:
        if i not in pubblicate:
            err.append(f"{i}: notizia senza un comunicato con esito «pubblicato» che la indichi")
    # niente doppioni: una notizia nuova che cita la stessa pagina di una notizia della prima pagina è lo stesso fatto
    # (25 ott 2026: col giro di ogni ora che legge gli stessi siti ufficiali)
    gia = {}
    for n in d.get("notizie", []):
        for l in link_di(n):
            gia.setdefault(l, n.get("id"))
    for i, n in per_id.items():
        doppi = sorted({gia[l] for l in link_di(n) if l in gia})
        if doppi:
            err.append(f"{i}: cita una pagina che è già nella notizia {', '.join(doppi)}: è lo stesso fatto, usa "
                       "«gia_nel_sito» con quella notizia (o togli quel link se è proprio un altro fatto)")
    # niente doppioni anche senza lo stesso link (27 ott 2026, lui: «nessun doppione importantissimo»): dal 27 ott il
    # Benevento Calcio non aspetta il giro di ogni ora (comunicati_lampo.SENZA_ATTESA), e il giro di ogni ora potrebbe
    # aver appena scritto lo stesso fatto partendo da un giornale. Una notizia nuova col titolo che sembra lo stesso fatto
    # (giornali.stesso_fatto) di una notizia uscita nelle ultime ORE_SIMILI ore va confermata: «gia_nel_sito» con quella,
    # o "non_doppione_di": ["id"] nella notizia nuova se è davvero un altro fatto (il campo poi si toglie)
    recenti = [x for x in d.get("notizie", []) if (quando_di(x) or dt.datetime.min.replace(tzinfo=dt.timezone.utc))
               >= adesso - dt.timedelta(hours=ORE_SIMILI)]
    for i, n in per_id.items():
        conferma = n.pop("non_doppione_di", None)
        if conferma is not None and not (isinstance(conferma, list) and all(isinstance(x, str) for x in conferma)):
            err.append(f"{i}: «non_doppione_di» è un elenco di id di notizie")
            conferma = []
        pn = G.parole(n.get("titolo", ""))
        for x in recenti:
            if x.get("id") != i and x.get("id") not in (conferma or []) and G.stesso_fatto(pn, G.parole(x.get("titolo", ""))):
                err.append(f"{i}: sembra lo stesso fatto di {x.get('id')}, uscita da poco («{str(x.get('titolo'))[:90]}»). "
                           f"Se è lo stesso fatto usa «gia_nel_sito» con quella; se è davvero un altro fatto scrivi nella "
                           f"notizia nuova \"non_doppione_di\": [\"{x.get('id')}\"]")
    if err:
        return []
    # l'articolo di un sito ufficiale: la fonte col suo link è la fonte ufficiale, il sito mostra lei (26 ott 2026,
    # pagine.vista_ufficiale); qui si segna anche se l'agente se ne è dimenticato
    for e in esiti:
        voce = per_voce.get(e.get("comunicato")) or {}
        link = con_percorso(voce.get("link")) if e.get("esito") == "pubblicato" and voce.get("tipo") == "sito" else ""
        n = per_id.get(e.get("notizia")) if link else None
        for f in ((n.get("fonti") or []) + ((n.get("articolo") or {}).get("fonti") or [])) if n else []:
            if isinstance(f, dict) and con_percorso(f.get("url")) == link:
                f["ufficiale"] = True
    for n in reversed(nuove):
        n["subito"] = True
        n.setdefault("pubblicato", adesso.isoformat(timespec="seconds"))
        scegli_foto_nuova(n, d.get("notizie", []))
        d["notizie"].insert(0, n)
    # un comunicato su una notizia che c'è già: è ufficiale, esce subito anche sui social se non c'è ancora uscita
    # (lui, 25 ott 2026: «avevamo detto comunicati da pubblicare subito»), con la locandina e le foto della mail
    altre = []
    for e in esiti:
        n = prima.get(e.get("notizia")) if e["esito"] == "gia_nel_sito" else None
        if n is None:
            continue
        n["subito"] = True
        n.setdefault("comunicati", [])
        if e["comunicato"] not in n["comunicati"]:
            n["comunicati"].append(e["comunicato"])
        if IMMAGINI & e.keys():
            n.update({k: copy.deepcopy(e[k]) for k in IMMAGINI if k in e})
            altre.append(f"foto del comunicato su {n['id']}")
    ora = adesso.isoformat(timespec="minutes")
    for e in esiti:
        visti[e["comunicato"]] = {k: v for k, v in {"esito": e["esito"], "notizia": e.get("notizia"), "quando": ora}.items() if v}
    return [n.get("titolo", "") for n in nuove] + altre


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
    voci = tutte_le_voci()
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
