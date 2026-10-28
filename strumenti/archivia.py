#!/usr/bin/env python3
"""Controlla notizie.json e sposta in archivio le notizie uscite dalla prima pagina.

Nessuna notizia viene mai cancellata:
- in prima pagina restano le notizie di oggi e dei 2 giorni prima, gli avvisi ufficiali ancora in vigore
  (`in_vigore_fino`) e le notizie collegate a un approfondimento attivo;
- le altre passano in archivio/AAAA-MM.json (mese di `pubblicato`), con l'articolo completo;
- un approfondimento passa in archivio quando ha `"archiviato": true` o non è aggiornato da più di 7 giorni;
- archivio/indice.json si rifà ogni volta da tutti i mesi (serve alla ricerca e ai link vecchi).

Uso:  python3 strumenti/archivia.py --giro     (l'agente, a fine giro) in più controlla il registro delle fonti
                                               /tmp/fonti.txt e mette in `aggiornato` l'ora di adesso
      python3 strumenti/archivia.py            controlla, archivia e scrive i file
      python3 strumenti/archivia.py --prova    controlla e dice cosa farebbe, senza scrivere
      python3 strumenti/archivia.py --oggi 2026-10-25   (solo per le prove)
Esce con codice 1, senza scrivere niente, se trova un errore.
Alla fine stampa una riga «CAMBIATO: <file>» per ogni file da pubblicare.
"""
import argparse
import datetime as dt
import glob
import hashlib
import json
import os
import re
import subprocess
import sys

CAT = {"strade", "avvisi", "cronaca", "meteo", "politica", "sport", "eventi", "cultura", "altro"}
SPORT = {"calcio", "calcio_a_5", "basket", "pallavolo", "rugby", "scherma", "atletica", "tennis", "ciclismo", "nuoto", "altro"}
UNA_FONTE_CAT = ("cronaca", "strade", "avvisi", "cultura", "altro", "politica", "sport")   # regola 2 (politica dal 22 ott 2026, con la regola 9)
ZONE = {"benevento", "telesina", "caudina", "fortore", "provincia"}
# La zona di ogni Comune del Sannio (28 ott 2026, lui: «migliora il filtro Benevento città perché compaiono anche altri
# comuni»): la mette il programma dal luogo della notizia (zona_dal_luogo), non l'agente. «benevento» è solo la città;
# «provincia» (nel menu «Altri comuni») sono i paesi intorno a Benevento.
ZONA_COMUNE = {c.lower(): z for z, cc in {
    "benevento": ["Benevento"],
    "telesina": ["Amorosi", "Castelvenere", "Cerreto Sannita", "Cusano Mutri", "Dugenta", "Faicchio",
        "Frasso Telesino", "Guardia Sanframondi", "Melizzano", "Paupisi", "Pietraroja", "Puglianello",
        "San Lorenzello", "San Lorenzo Maggiore", "San Lupo", "San Salvatore Telesino", "Solopaca", "Telese Terme"],
    "caudina": ["Airola", "Arpaia", "Bonea", "Bucciano", "Campoli del Monte Taburno", "Durazzano", "Forchia",
        "Limatola", "Moiano", "Montesarchio", "Pannarano", "Paolisi", "Sant'Agata de' Goti", "Tocco Caudio"],
    "fortore": ["Baselice", "Campolattaro", "Casalduni", "Castelfranco in Miscano", "Castelpagano",
        "Castelvetere in Val Fortore", "Circello", "Colle Sannita", "Foiano di Val Fortore", "Fragneto l'Abate",
        "Fragneto Monforte", "Ginestra degli Schiavoni", "Molinara", "Montefalcone di Val Fortore", "Morcone",
        "Pontelandolfo", "Reino", "San Bartolomeo in Galdo", "San Giorgio La Molara", "San Marco dei Cavoti",
        "Santa Croce del Sannio", "Sassinoro"],
    "provincia": ["Apice", "Apollosa", "Arpaise", "Buonalbergo", "Calvi", "Castelpoto", "Cautano", "Ceppaloni",
        "Foglianise", "Paduli", "Pago Veiano", "Pesco Sannita", "Pietrelcina", "Ponte", "San Giorgio del Sannio",
        "San Leucio del Sannio", "San Martino Sannita", "San Nazzaro", "San Nicola Manfredi",
        "Sant'Angelo a Cupolo", "Sant'Arcangelo Trimonte", "Torrecuso", "Vitulano"],
}.items() for c in cc}
ZONA_COMUNE["sant'agata dei goti"] = "caudina"
STATI = {"confermata", "ufficiale", "una_fonte"}
TRAFFICO = {"chiusa", "blocchi", "senso_unico", "ristretta", "bus"}   # la pagina «Strade chiuse» (pagine.py)
# le testate che da sole bastano per la cronaca (regola 2 di AGENTE.md), scritte senza spazi né maiuscole
AUTOREVOLI = {"ilmattino", "ilsannioquotidiano", "ntr24", "ottopagine", "anteprima24", "labtv", "cronachedelsannio",
              "beneventonews24", "tv7benevento"}
VIETATE = ["choc", "shock", "incredibile", "ecco cosa", "non crederai", "!", "?"]
# dire che un dato manca, in una notizia che viene da un comunicato per email (controlla)
NON_DETTO = re.compile(r"\bnon (?:è|e'|viene|vengono|sono|è stat[oa]|sono stat[ie]) (?:ancora )?(?:indicat|specificat|"
                       r"precisat|res[oi] not|dett|comunicat|scritt)\w*|\b(?:il|nel) comunicato non (?:dice|indica|"
                       r"specifica|precisa|riporta|parla)\w*|\bnon si sa\b|\bnon è dato sapere|\bnon (?:è|sono) not[oi]\b",
                       re.I)
ISO = re.compile(r"^\d{4}-\d{2}-\d{2}(T\d{2}:\d{2}(:\d{2})?[+-]\d{2}:\d{2})?$")
GIORNO = re.compile(r"^\d{4}-\d{2}-\d{2}$")
GIORNI_PRIMA_PAGINA = 3      # oggi + i 2 giorni prima
GIORNI_APPROFONDIMENTO = 7
# eventi del calendario (eventi.json)
TIPI_EVENTO = {"teatro", "danza", "concerto", "lirica", "mostra", "museo", "cinema", "libro", "sagra", "festa", "mercatino",
               "natale", "carnevale", "altro"}
TEMA_TIPO = {"teatro": "teatro", "danza": "danza", "concerto": "concerto", "lirica": "musica-classica", "mostra": "mostra",
             "museo": "museo", "cinema": "cinema", "sagra": "sagra", "festa": "luminarie", "mercatino": "mercato",
             "natale": "natale", "carnevale": "carnevale", "libro": "libri"}
ORA = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")
# «orari» deve dire le ore (o almeno il momento del giorno): con i soli giorni la pagina ripeteva «Quando» (25 ott 2026,
# Presepe di Casali di Faicchio: «Orari: 26 e 27 dicembre 2026, 2 e 3 gennaio 2027»)
ORE_IN_ORARI = re.compile(r"\b(?:ore|alle|dalle|dall['’]|fino alle|entro le)\s*\d{1,2}\b|\b\d{1,2}[:.]\d\d\b|mattin|pomerigg|"
                          r"\bser[ae]\b|serat|nott|pranzo|cena|appuntament|apertur|chiusur|tutto il giorno|orario continuato",
                          re.I)
# Le locandine arrivate per posta (voluto dal proprietario il 25 ott 2026: «se mandano locandine noi le dobbiamo usare,
# in questo caso niente immagini AI»): l'agente scrive "locandina": "<id del comunicato>/<n>", cioè il file
# allegati/<id>/<n>.jpg dell'archivio delle fonti (comunicati.json, «immagini»); risolvi_locandine() lo copia in
# img/locandine/ del sito e il campo diventa il percorso.
BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # la cartella del sito (--cartella nelle prove)
LOCANDINA = re.compile(r"^img/locandine/[a-z0-9-]+\.jpg$")
RIF_LOCANDINA = re.compile(r"^(?:posta:)?([A-Za-z0-9_-]+)/(\d+)$")
# Le foto arrivate per posta (voluto dal proprietario il 25 ott 2026: «se mandano foto usale», «anche più foto se ci
# sono»): "foto_inviate": ["<id del comunicato>/<n>", …] e "foto_da" (chi le ha mandate) nella notizia. La prima va in
# alto al posto della foto fatta con l'IA (se c'è la locandina, in alto va lei e le foto tutte sotto), le altre in fondo
# all'articolo; sui social escono anche loro (instagram.py, facebook.py). risolvi_locandine() le copia in img/locandine/.
FOTO_MAX = 10
GIORNI_EVENTI = 60           # un evento finito da più di 60 giorni passa in archivio/eventi-AAAA-MM.json


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


MESI = {m: i + 1 for i, m in enumerate(["gennaio", "febbraio", "marzo", "aprile", "maggio", "giugno", "luglio", "agosto",
                                        "settembre", "ottobre", "novembre", "dicembre"])}
NOMI_MESI = "|".join(MESI)
# l'ora di un momento scritto a parole («21 ottobre, mattina»): serve solo a metterlo in ordine
MOMENTI = [("notte", "23:30"), ("alba", "06:00"), ("tarda mattinata", "11:30"), ("mattin", "09:00"),
           ("mezzogiorno", "12:00"), ("pomeriggio", "15:00"), ("sera", "20:00")]
QUANDO = re.compile(r"^\d{4}-\d{2}-\d{2}(T\d{2}:\d{2})?$")


# Il registro delle fonti del giro (/tmp/fonti.txt, una riga «nome | letta / non raggiungibile / vuota | novità»):
# con --giro archivia.py non chiude il giro se manca una fonte (22 ott 2026: un giro l'aveva saltato).
FONTI_GIRO = [  # (nome da scrivere nel registro, pezzi che lo riconoscono anche scritto in altro modo)
    ("Comune di Benevento", ["comunedibenevento", "comunebenevento"]), ("Provincia di Benevento", ["provincia"]),
    ("ANAS", ["anas"]), ("INGV", ["ingv"]), ("San Marco dei Cavoti", ["sanmarco"]), ("ASL Benevento", ["asl"]),
    ("Ospedale San Pio", ["sanpio"]), ("Alto Calore", ["altocalore"]), ("GESESA", ["gesesa"]),
    ("Prefettura", ["prefettura"]), ("Questura", ["questura"]), ("EAV", ["eav"]), ("AIR Campania", ["aircampania"]),
    ("RFI", ["rfi"]), ("Albo pretorio Benevento", ["albo"]), ("Regione Campania", ["regione"]),
    ("Ottopagine", ["ottopagine"]), ("Il Sannio Quotidiano", ["sannioquotidiano"]), ("NTR24", ["ntr24"]),
    ("Lab TV", ["labtv"]), ("Cronache del Sannio", ["cronachedelsannio", "sannionews24"]), ("Fremondoweb", ["fremondo"]),
    ("Gazzetta di Benevento", ["gazzetta"]), ("Anteprima24", ["anteprima"]), ("InfoSannio", ["infosannio"]),
    ("Benevento Giornale", ["beneventogiornale"]), ("BeneventoNews24", ["beneventonews"]), ("Il Mattino", ["mattino"]),
    ("TV7 Benevento", ["tv7"]), ("Il Caudino", ["caudino"]),
]


def controlla_registro(percorso, err, giornali=None):
    def norma(x):
        import unicodedata
        x = unicodedata.normalize("NFKD", x).encode("ascii", "ignore").decode().lower()
        return re.sub(r"[^a-z0-9]", "", x)
    try:
        with open(percorso, encoding="utf-8") as f:
            righe = [r.strip() for r in f if r.strip()]
        if giornali and os.path.exists(giornali):   # le righe dei giornali le scrive strumenti/giornali.py
            with open(giornali, encoding="utf-8") as f:
                righe += [r.strip() for r in f if r.strip()]
    except OSError:
        err.append(f"manca il registro delle fonti {percorso}: scrivi una riga per fonte, «nome | letta / non "
                   "raggiungibile / vuota | cosa c'era di nuovo» (i nomi sono in AGENTE.md, «Il registro delle fonti»)")
        return
    voci = []
    for r in righe:
        pezzi = [x.strip() for x in r.split("|")]
        if len(pezzi) < 2:
            continue
        voci.append((norma(pezzi[0]), pezzi[1].lower(), r.lower()))
        stato = pezzi[1].lower()
        if norma(pezzi[0]).startswith("ricerca"):
            continue
        if not stato.startswith(("letta", "non raggiungibile", "vuota")):
            err.append(f"registro delle fonti: stato {pezzi[1]!r} per {pezzi[0]!r} (scrivi letta, non raggiungibile o vuota)")
        elif stato.startswith("non raggiungibile") and not any(k in r.lower() for k in ("riprov", "copia di casa ferma")):
            err.append(f"registro delle fonti: {pezzi[0]!r} non raggiungibile senza secondo tentativo: riprova con un altro "
                       "indirizzo (home, sezione, feed, http) e scrivi «riprovato con …»")
    mancano = [nome for nome, pezzi in FONTI_GIRO if not any(any(p in v[0] for p in pezzi) for v in voci)]
    if mancano:
        err.append(f"registro delle fonti: {'manca 1 fonte' if len(mancano) == 1 else f'mancano {len(mancano)} fonti'}: "
                   f"{', '.join(mancano)}. Leggile e aggiungi una riga per ognuna, col nome scritto così")
    ricerche = sum(v[0].startswith("ricerca") for v in voci)
    if ricerche < 6:   # 22 ott 2026: il giro di prova ne aveva fatte 4 su 6
        err.append(f"registro delle fonti: {ricerche} ricerche mirate, ne servono almeno 6 (4 per le notizie, comprese le "
                   "storie in corso, e 2 per gli eventi): fai quelle che mancano e scrivi per ognuna «Ricerca: parole "
                   "cercate | fatta | cosa ha trovato»")
    comuni = any("comuni" in v[0] for v in voci) or sum(v[0].startswith("comune") for v in voci) >= 19
    if not comuni:
        err.append("registro delle fonti: manca la riga dei Comuni (file comuni.json da casa, oppure i 19 Comuni a mano, "
                   "una riga per Comune)")


GIORNI_DIARIO = 14   # il diario dei giri resta 14 giorni (diario/AAAA-MM-GG.json, cifrato)


def leggi_diario(percorso, err):
    """Il diario del giro scritto dall'agente (/tmp/diario.json): riassunto, notizie scartate e perché, dubbi."""
    try:
        with open(percorso, encoding="utf-8") as f:
            g = json.load(f)
    except OSError:
        err.append(f"manca il diario del giro {percorso}: scrivi riassunto, scartate (fatto, fonti, motivo) e dubbi "
                   "(AGENTE.md, «Il diario del giro»)")
        return None
    except ValueError as e:
        err.append(f"il diario del giro {percorso} non è un JSON valido: {e}")
        return None
    if not isinstance(g, dict) or vuoto(g.get("riassunto")):
        err.append("diario del giro: manca il «riassunto»")
        return None
    if not isinstance(g.get("scartate"), list):
        err.append("diario del giro: «scartate» deve essere un elenco, anche vuoto []")
    else:
        for x in g["scartate"]:
            if not isinstance(x, dict) or vuoto(x.get("fatto")) or vuoto(x.get("motivo")):
                err.append(f"diario del giro: ogni scartata vuole «fatto» e «motivo» ({str(x)[:80]})")
    return g


def righe_registro(percorso, giornali=None):
    """Il registro delle fonti diviso in fonti e ricerche, per il diario."""
    fonti, ricerche, righe = [], [], []
    for p in (giornali, percorso):
        try:
            with open(p, encoding="utf-8") as f:
                righe += f.read().splitlines()
        except (OSError, TypeError):
            pass
    for r in righe:
        p = [x.strip() for x in r.split("|")]
        if len(p) < 2:
            continue
        if p[0].lower().startswith("ricerca"):
            ricerche.append({"cosa": re.sub(r"^ricerca\w*\s*:?\s*", "", p[0], flags=re.I), "trovato": " | ".join(p[2:])})
        else:
            fonti.append({"nome": p[0], "stato": p[1], "novita": " | ".join(p[2:])})
    return fonti, ricerche


ESITI = ("nuova", "aggiornata", "presente", "evento", "scartata", "chiusure")   # chiusure: le fa il giro Chiusure
MOTIVI = {   # gli unici motivi per non pubblicare un fatto dei giornali (22 ott 2026: «episodio minore» non vale)
    "fuori_provincia": "fuori provincia",
    "vecchia": "fatto vecchio o già passato",
    "una_fonte_non_autorevole": "una sola testata non autorevole, nessuna conferma",
    "politica_senza_effetti": "politica senza effetti per la gente (regola 9)",
    "pubblicita": "pubblicità o promozione",
    "non_notizia": "non è una notizia per il sito (opinione, rubrica, ricorrenza, telegiornale)",
    "voce_non_confermata": "voce o indiscrezione non confermata (anche calciomercato)",
    "non_leggibile": "l'articolo non si apre",
    "allerta_gialla": "allerta gialla senza chiusure (la mostra la pagina Meteo)",   # 23 ott 2026, scelta del proprietario
    "atto_interno": "atto interno del Comune, che alla gente non serve (turni, nomine, gare, liquidazioni)",   # 23 ott
}
# una notizia che è solo un'allerta gialla (la gialla non si pubblica; le chiusure per la gialla sì)
GIALLA = re.compile(r"\bgiall[ae]\b", re.I)
PIU_ALTA = re.compile(r"\b(arancion[ei]|ross[ae])\b", re.I)
# una notizia che è una chiusura decisa da un Comune (le pubblica il giro Chiusure, strumenti/chiusure.py)
CHIUSURA = re.compile(r"scuol\w*\s+chius|chius[aeiou]\w*\s+(?:(?:le|i|gli|dei|delle|degli|il|la)\s+)?(?:scuol|plessi|"
                      r"istitut\w*\s+scolastic|parc(?:o|hi)\b|vill[ae]\s+comunal|cimiter)|sospensione\s+(?:delle\s+)?attivit[àa]\s+"
                      r"didattic|niente\s+scuola\b|stop\s+alle\s+lezioni|lezioni\s+sospese", re.I)
CHIUSURE = re.compile(r"chius|scuol|parch|cimiter|sospes|ordinanz|sgombr|evacu|allag|frana|crollo|danni", re.I)


def controlla_decisioni(giro, percorso, d, prima, tutti_gli_id, ev, err):
    """Una decisione per ogni fatto nuovo dei giornali (elenco di strumenti/giornali.py): niente sparisce in silenzio."""
    try:
        with open(percorso, encoding="utf-8") as f:
            titoli = json.load(f)
    except OSError:
        err.append(f"manca l'elenco degli articoli nuovi {percorso}: all'inizio del giro esegui "
                   "`python3 strumenti/giornali.py` (AGENTE.md, «L'elenco degli articoli nuovi»)")
        return None
    except ValueError as e:
        err.append(f"l'elenco degli articoli nuovi {percorso} non è un JSON valido: {e}")
        return None
    dec = giro.get("decisioni")
    if not isinstance(dec, dict):
        err.append("diario del giro: manca «decisioni», una per ogni fatto dell'elenco dei giornali (G1, G2…), anche {} "
                   "se l'elenco è vuoto")
        return titoli
    gruppi = {g["id"]: g for g in titoli.get("gruppi", [])}
    mancano = [g for g in gruppi if g not in dec]
    if mancano:
        err.append(f"diario del giro: manca la decisione per {len(mancano)} fatti dei giornali ({', '.join(mancano[:20])}"
                   f"{'…' if len(mancano) > 20 else ''}): per ognuno «nuova», «aggiornata», «presente», «evento» o "
                   "«scartata» col motivo (AGENTE.md, «L'elenco degli articoli nuovi»)")
    vecchie = {n.get("id"): n for n in (prima or {}).get("notizie", []) + (prima or {}).get("approfondimenti", [])}
    attuali = {n.get("id"): n for n in d.get("notizie", []) + d.get("approfondimenti", [])}
    eventi = {x.get("id") for x in (ev or {}).get("eventi", [])}
    uguale = lambda a, b: json.dumps(a, sort_keys=True, ensure_ascii=False) == json.dumps(b, sort_keys=True, ensure_ascii=False)
    quarantena = in_quarantena()
    for gid, x in dec.items():
        w = f"decisione {gid}"
        if gid not in gruppi:
            err.append(f"{w}: nell'elenco dei giornali non c'è {gid}")
            continue
        if not isinstance(x, dict) or x.get("esito") not in ESITI:
            err.append(f"{w}: «esito» deve essere uno di {', '.join(ESITI)}")
            continue
        e, nid = x["esito"], x.get("notizia")
        if ("notizia", nid) in quarantena or (e == "evento" and ("evento", x.get("evento")) in quarantena):
            continue   # è in quarantena: la decisione vale, la voce torna al giro dopo
        if e in ("nuova", "aggiornata", "presente"):
            if nid not in tutti_gli_id:
                err.append(f"{w}: «notizia» {nid!r} non esiste (scrivi l'id della notizia)")
            elif e == "nuova" and (nid not in attuali or (prima is not None and nid in vecchie)):
                err.append(f"{w}: {nid} non è nuova in questo giro: scrivi «aggiornata» o «presente»")
            elif e == "aggiornata" and nid not in attuali:
                err.append(f"{w}: {nid} è in archivio: un fatto nuovo va in una notizia della prima pagina")
            elif e == "aggiornata" and prima is not None and nid not in vecchie:
                err.append(f"{w}: {nid} è nata in questo giro: scrivi «nuova»")
            elif e == "aggiornata" and prima is not None and uguale(vecchie[nid], attuali[nid]):
                err.append(f"{w}: dici «aggiornata» ma {nid} non è cambiata: aggiungi il fatto nuovo (paragrafo del "
                           "giorno, fonte) oppure scrivi «presente» se non c'è niente di nuovo")
        elif e == "evento" and x.get("evento") not in eventi:
            err.append(f"{w}: «evento» {x.get('evento')!r} non è in eventi.json")
        elif e == "scartata" and x.get("motivo") not in MOTIVI:
            err.append(f"{w}: «motivo» deve essere uno di: {', '.join(MOTIVI)} (un fatto locale vero con una fonte "
                       "autorevole non si scarta: esce, anche se piccolo)")
        elif e == "scartata" and gruppi[gid].get("comunicati") and len(str(x.get("nota") or "").strip()) < 15:
            err.append(f"{w}: c'è un comunicato arrivato per email ({', '.join(gruppi[gid]['comunicati'])}): scrivi in "
                       "«nota» cosa diceva e perché non si pubblica (AGENTE.md, «Comunicati arrivati per posta»)")
        elif e == "scartata" and gruppi[gid].get("comuni") and len(str(x.get("nota") or "").strip()) < 15:
            err.append(f"{w}: è un avviso di {', '.join(gruppi[gid]['comuni'])}: scrivi in «nota» cosa diceva e perché "
                       "alla gente non serve (AGENTE.md, «I siti dei Comuni»: quello che serve a chi ci abita si pubblica)")
    return titoli


def vedetta_del_giro():
    """La vedetta delle chiusure vista da questo giro (chiusure.json dell'archivio di casa): l'ultimo controllo, l'esito
    e le piste degli ultimi giorni, per la scheda «Chiusure» delle statistiche. None se il file non c'è."""
    p = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
                     "notizie-benevento-fonti", "chiusure.json")
    c = leggi(p, None)
    if not isinstance(c, dict):
        return None
    return {"controllato": c.get("controllato"), "esito": str(c.get("esito") or "")[:200], "allerta": c.get("allerta"),
            "piste": [{k: str(x.get(k) or "")[:160] for k in ("id", "comune", "fonte", "titolo", "link", "trovata")}
                      for x in (c.get("piste") or [])[-60:]]}


def casa_del_giro():
    """Le fonti lette da casa viste da questo giro (i file dell'archivio di casa accanto al sito): ultimo controllo,
    esito e, per Comuni e stagioni, quanti siti si leggono. Per la scheda «Salute» delle statistiche (dal 25 ott 2026).
    None se l'archivio non c'è."""
    cart = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
                        "notizie-benevento-fonti")
    if not os.path.isdir(cart):
        return None
    casa = []
    for p in sorted(glob.glob(os.path.join(cart, "*.json"))):
        if os.path.basename(p) == "chiusure.json":   # la vedetta: c'è già in «vedetta»
            continue
        x = leggi(p, None)
        if not isinstance(x, dict) or "controllato" not in x:
            continue
        v = {k: str(x.get(k) or "")[:200] for k in ("fonte", "controllato", "esito", "ultima_lettura_riuscita")}
        v["file"] = os.path.basename(p)
        for k in ("comuni_letti", "albi_letti"):
            if x.get(k):
                v[k] = str(x[k])
        for k in ("comuni_non_letti", "albi_non_letti", "stagioni_non_lette"):
            if x.get(k):
                v[k] = [str(y)[:80] for y in x[k]][:40]
        if x.get("stagioni_lette"):
            v["stagioni_lette"] = len(x["stagioni_lette"])
        casa.append(v)
    return casa


def comunicati_del_giro(prima, adesso):
    """I comunicati arrivati per posta dall'ultimo giro (comunicati.json dell'archivio di casa, accanto al sito):
    solo quanti, da quali domini e lo stato della casella, per le statistiche. None se il file non c'è."""
    p = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
                     "notizie-benevento-fonti", "comunicati.json")
    c = leggi(p, None)
    if not isinstance(c, dict):
        return None
    try:
        dal = dt.datetime.fromisoformat((prima or {}).get("aggiornato"))
    except (TypeError, ValueError):
        dal = adesso - dt.timedelta(hours=1)
    voci = []
    for v in c.get("voci") or []:
        try:
            if dal < dt.datetime.fromisoformat(v["data"]) <= adesso:
                voci.append(v)
        except (KeyError, TypeError, ValueError):
            continue
    return {"arrivati": len(voci), "domini": sorted({v.get("dominio") for v in voci if v.get("dominio")}),
            "casella": str(c.get("esito") or "")[:80]}


def voce_diario(giro, d, prima, vanno, registro, inizio, adesso, titoli=None, giornali=None):
    """Quello che il giro ha fatto: le notizie nuove e aggiornate le calcola il programma (confronto con l'ultima
    versione pubblicata), le scartate, i dubbi e il riassunto li scrive l'agente."""
    vecchie = {n.get("id"): n for n in (prima or {}).get("notizie", [])}
    impronta = lambda n: json.dumps({k: n.get(k) for k in ("titolo", "sintesi", "fonti", "stato", "rilevante",
                                                           "in_vigore_fino", "articolo")},
                                    ensure_ascii=False, sort_keys=True, default=str)
    nuove, aggiornate = [], []
    for n in d["notizie"]:
        v = vecchie.get(n.get("id"))
        if prima is not None and v is None:
            nuove.append({"id": n["id"], "titolo": n.get("titolo"), "stato": n.get("stato"),
                          "fonti": [f.get("nome") for f in n.get("fonti", [])]})
        elif v is not None and impronta(n) != impronta(v):
            ag = (n.get("articolo") or {}).get("aggiornamento") or {}
            vag = (v.get("articolo") or {}).get("aggiornamento") or {}
            aggiornate.append({"id": n["id"], "titolo": n.get("titolo"),
                               "aggiornamento": ag.get("testo") if ag.get("testo") != vag.get("testo") else None,
                               "fonti_nuove": sorted({f.get("nome") for f in (n.get("articolo") or {}).get("fonti", [])} -
                                                     {f.get("nome") for f in (v.get("articolo") or {}).get("fonti", [])})})
    fonti, ricerche = righe_registro(registro, giornali)
    # i fatti dei giornali scartati vanno con gli altri scartati, col motivo scritto per esteso
    scartate = list(giro.get("scartate") or [])
    esame = None
    if titoli is not None and isinstance(giro.get("decisioni"), dict):
        gruppi = {g["id"]: g for g in titoli.get("gruppi", [])}
        esame = {e: 0 for e in ESITI}
        for gid, x in giro["decisioni"].items():
            g = gruppi.get(gid)
            if not g or not isinstance(x, dict):
                continue
            esame[x.get("esito")] = esame.get(x.get("esito"), 0) + 1
            if x.get("esito") == "scartata":
                nota = x.get("nota") or ""
                scartate.append({"fatto": g.get("titolo"), "fonti": g.get("testate"),
                                 "motivo": MOTIVI.get(x.get("motivo"), x.get("motivo")) + (f": {nota}" if nota else ""),
                                 "link": (g.get("articoli") or [{}])[-1].get("url")})
        esame["fatti"] = len(gruppi)
    durata, partenza = None, adesso
    try:   # il giro si chiama con l'ora in cui è partito (09:05), così rilanciare archivia non lo conta due volte
        with open(inizio, encoding="utf-8") as f:
            t = dt.datetime.fromisoformat(f.read().strip())
        if dt.timedelta(0) <= adesso - t < dt.timedelta(hours=2):
            durata, partenza = round((adesso - t).total_seconds() / 60, 1), t.astimezone(adesso.tzinfo)
    except (OSError, ValueError, TypeError):
        pass
    return {"ora": partenza.strftime("%H:%M"), "fine": adesso.strftime("%H:%M"), "durata_min": durata,
            "riassunto": giro.get("riassunto"),
            "nuove": nuove, "aggiornate": aggiornate, "archiviate": [n["id"] for n in vanno],
            "scartate": scartate, "esame_giornali": esame, "dubbi": giro.get("dubbi") or [], "eventi": giro.get("eventi"),
            "fonti": fonti, "ricerche": ricerche, "notizie_in_prima": len(d["notizie"]) - len(vanno),
            "comunicati": comunicati_del_giro(prima, adesso), "vedetta": vedetta_del_giro(), "casa": casa_del_giro()}


def scrivi_diario(base, voce, oggi):
    """Aggiunge la voce cifrata a diario/AAAA-MM-GG.json; dice quali file scrivere e quali giorni vecchi togliere."""
    import diario
    cart = os.path.join(base, "diario")
    p = os.path.join(cart, f"{oggi.isoformat()}.json")
    giorno = leggi(p, None) or {"giorno": oggi.isoformat(), "voci": []}
    giorno["voci"] = [v for v in giorno.get("voci", []) if v.get("ora") != voce["ora"]]   # un giro rilanciato non si conta due volte
    giorno["voci"].append({"ora": voce["ora"], "busta": diario.cifra(voce)})
    soglia = (oggi - dt.timedelta(days=GIORNI_DIARIO)).isoformat()
    vecchi = [x for x in glob.glob(os.path.join(cart, "[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9].json"))
              if os.path.basename(x)[:10] < soglia]
    return (p, json.dumps(giorno, ensure_ascii=False, indent=1) + "\n"), vecchi


def chiave_momento(c, rif):
    """Quando è successo un fatto della cronologia, per metterlo in ordine: «quando» se c'è, se no dal testo di «data»
    («19 ottobre», «20 ottobre, 10:30», «notte 18-19», «21 ottobre, mattina», «ottobre 2025»). None se non si capisce.
    rif = il giorno della notizia, per l'anno (e il mese di «notte 18-19») quando non sono scritti."""
    q = str(c.get("quando") or "")
    if QUANDO.match(q):
        return q
    s = str(c.get("data") or "").lower()
    m = re.search(rf"(\d{{1,2}})(?:\s*-\s*\d{{1,2}})?\s+({NOMI_MESI})(?:\s+(\d{{4}}))?", s)
    if m:
        g, me, a = int(m[1]), MESI[m[2]], m[3]
    elif re.search(r"\bnotte\s+(\d{1,2})\s*-\s*\d{1,2}\b", s):
        g, me, a = int(re.search(r"\bnotte\s+(\d{1,2})", s)[1]), rif.month, None
    elif re.search(rf"\b({NOMI_MESI})\b", s):   # «ottobre 2025», «metà dicembre», «inizio ottobre»
        m = re.search(rf"\b({NOMI_MESI})\b(?:\s+(\d{{4}}))?", s)
        g = 15 if "metà" in s else 28 if "fine" in s else 1
        me, a = MESI[m[1]], m[2]
    else:
        return None
    try:
        giorno = dt.date(int(a) if a else rif.year, me, g)
    except ValueError:
        return None
    if not a and giorno > rif + dt.timedelta(days=120):   # «28 dicembre» in una notizia di gennaio
        giorno = giorno.replace(year=giorno.year - 1)
    ora = re.search(r"\b([01]?\d|2[0-3])[:.]([0-5]\d)\b", s)
    hh = f"{int(ora[1]):02d}:{ora[2]}" if ora else next((h for k, h in MOMENTI if k in s), None)
    return giorno.isoformat() + (f"T{hh}" if hh else "")


def ordina_cronologia(righe, rif, dove, avv):
    """Mette i fatti in ordine di tempo (21 ott 2026: l'agente aggiungeva in fondo anche fatti di giorni prima).
    Prima i giorni; dentro lo stesso giorno si mettono in ordine solo le righe con l'ora, quelle senza restano dove
    le ha messe l'agente. Una riga di cui non si capisce il giorno resta attaccata a quella prima.
    True se l'ordine è cambiato."""
    if not isinstance(righe, list) or len(righe) < 2:
        return False
    chiavi, prec = [], ""
    for c in righe:
        k = chiave_momento(c, rif) if isinstance(c, dict) else None
        if k is None:
            avv.append(f"{dove}: nei fatti non capisco il giorno di {str((c or {}).get('data'))!r}: scrivi giorno e mese "
                       "(«19 ottobre, 10:30») o aggiungi \"quando\": \"AAAA-MM-GGTHH:MM\"")
            k = prec[:10]
        chiavi.append(k)
        prec = k
    ordine = sorted(range(len(righe)), key=lambda i: (chiavi[i][:10], i))
    for g in {k[:10] for k in chiavi}:
        posti = [p for p, i in enumerate(ordine) if chiavi[i][:10] == g and len(chiavi[i]) > 10]
        for p, i in zip(posti, sorted((ordine[p] for p in posti), key=lambda i: (chiavi[i], i))):
            ordine[p] = i
    nuove = [righe[i] for i in ordine]
    if nuove == righe:
        return False
    righe[:] = nuove
    return True


def pubblicate_prima(base):
    """notizie.json com'era all'ultimo salvataggio (git HEAD), per sapere cosa è cambiato in questo giro. None se git non c'è."""
    try:
        p = subprocess.run(["git", "-C", base, "show", "HEAD:notizie.json"], capture_output=True, timeout=30)
        return json.loads(p.stdout.decode("utf-8")) if p.returncode == 0 else None
    except Exception:
        return None


def segna_aggiornamenti(d, prima, adesso, avv):
    """L'ora del riquadro «Aggiornamento» la mette il programma, non l'agente: è l'ora del giro in cui il testo è cambiato.
    Se il testo è uguale a quello già pubblicato, resta l'ora di allora."""
    vecchie = {n.get("id"): n for n in (prima or {}).get("notizie", [])}
    ora = adesso.isoformat(timespec="minutes")
    for n in d["notizie"]:
        a = n.get("articolo") or {}
        v = vecchie.get(n.get("id"))
        va = (v or {}).get("articolo") or {}
        ag = a.get("aggiornamento")
        if not ag:
            nuove_fonti = {f.get("nome") for f in a.get("fonti", [])} - {f.get("nome") for f in va.get("fonti", [])}
            if v and nuove_fonti and a.get("racconto") != va.get("racconto"):
                avv.append(f"{n.get('id')}: racconto e fonti nuove ({', '.join(sorted(map(str, nuove_fonti)))}) ma niente "
                           "«aggiornamento»: se ci sono fatti nuovi scrivi in 1-2 frasi cosa è cambiato")
            continue
        if prima is not None and v is None:
            avv.append(f"{n.get('id')}: è una notizia nuova, l'«aggiornamento» non serve: l'ho tolto")
            del a["aggiornamento"]
            continue
        vag = va.get("aggiornamento") or {}
        if vag.get("testo") == ag.get("testo") and ISO.match(str(vag.get("quando", ""))):
            ag["quando"] = vag["quando"]
            tp = vag.get("titolo_prima")
        elif prima is None and ISO.match(str(ag.get("quando", ""))) and not nel_futuro(ag["quando"], adesso):
            tp = ag.get("titolo_prima")   # senza git non so cosa c'era prima: tengo l'ora scritta
        else:
            ag["quando"] = ora
            # un cambio di titolo di poche ore fa (forse non ancora uscito sui social) resta; uno vecchio no
            try:
                recente = adesso - dt.datetime.fromisoformat(str(vag.get("quando"))) < dt.timedelta(hours=12)
            except (ValueError, TypeError):
                recente = False
            tp = (vag.get("titolo_prima") if recente else None) or (v or {}).get("titolo")
        # il titolo di prima dell'aggiornamento: se è cambiato, la notizia esce di nuovo su Facebook e Instagram
        # come «Aggiornamento» (facebook.aggiornate). Lo scrive il programma, non l'agente.
        if tp and tp != n.get("titolo"):
            ag["titolo_prima"] = tp
        else:
            ag.pop("titolo_prima", None)


def nel_futuro(iso, adesso):
    """True se una data ISO con fuso (o solo giorno) è dopo adesso + 10 minuti."""
    try:
        if GIORNO.match(iso):
            return dt.date.fromisoformat(iso) > adesso.date()
        return dt.datetime.fromisoformat(iso) > adesso + dt.timedelta(minutes=10)
    except Exception:
        return False


CART_TEMI = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "img", "temi")


def temi_foto():
    """I temi delle foto illustrative (img/temi/temi.json) che hanno davvero il file."""
    cart = CART_TEMI
    try:
        temi = json.load(open(os.path.join(cart, "temi.json"), encoding="utf-8"))
    except Exception:
        return set()
    return {t for t in temi if os.path.exists(os.path.join(cart, t + ".jpg"))}


def versioni_foto(tema):
    """Le versioni della foto di un tema: tema.jpg, tema-2.jpg, tema-3.jpg…"""
    v = [tema] if os.path.exists(os.path.join(CART_TEMI, tema + ".jpg")) else []
    k = 2
    while os.path.exists(os.path.join(CART_TEMI, f"{tema}-{k}.jpg")):
        v.append(f"{tema}-{k}")
        k += 1
    return v


def scegli_foto(notizie):
    """Il campo «foto»: quale versione della foto del tema mostrare, così in prima pagina non si ripete.
    Una versione già scelta resta, tranne quando la divide con un'altra notizia e c'è una versione libera:
    allora cambia quella della notizia più recente."""
    usate, versioni = {}, {}
    for n in notizie:
        v = versioni_foto(n.get("immagine") or "") if n.get("categoria") != "cronaca" else []
        versioni[n["id"]] = v
        if n.get("foto") in v:
            usate[n["foto"]] = usate.get(n["foto"], 0) + 1
        else:
            n.pop("foto", None)
    for n in sorted(notizie, key=lambda x: str(x.get("pubblicato", "")), reverse=True):
        v = versioni[n["id"]]
        if not v:
            continue
        f = n.get("foto")
        # a parità, una versione «a caso» ma sempre la stessa per la stessa notizia: così le versioni girano tutte
        libera = min(v, key=lambda x: (usate.get(x, 0), hashlib.md5((n["id"] + x).encode()).hexdigest()))
        if f is None or (usate[f] > 1 and usate.get(libera, 0) == 0):
            if f:
                usate[f] -= 1
            n["foto"] = libera
            usate[libera] = usate.get(libera, 0) + 1


def archivio_fonti():
    """L'archivio delle fonti lette da casa: accanto al sito, o in /home/user nel cloud."""
    for p in (os.environ.get("NB_FONTI_ARCHIVIO"), os.path.join(os.path.dirname(BASE), "notizie-benevento-fonti"),
              "/home/user/notizie-benevento-fonti"):
        if p and os.path.isdir(p):
            return p
    return None


def sorgente_locandina(rif):
    """Il file dell'archivio delle fonti indicato da "<id del comunicato>/<n>", se c'è."""
    m, fonti = RIF_LOCANDINA.match(str(rif)), archivio_fonti()
    p = m and fonti and os.path.join(fonti, "allegati", m[1], m[2] + ".jpg")
    return p if p and os.path.exists(p) else None


def _controlla_immagine(r, cosa, w, err):
    r = str(r)
    if LOCANDINA.match(r):
        if not os.path.exists(os.path.join(BASE, r)):
            err.append(f"{w}: {cosa} {r} non c'è nel sito")
    elif not sorgente_locandina(r):
        err.append(f"{w}: {cosa} {r!r}: scrivi «<id del comunicato>/<numero>» di un'immagine che c'è in "
                   "comunicati.json («immagini», file allegati/<id>/<numero>.jpg)")


def controlla_locandina(x, w, err):
    if "locandina" in x:
        _controlla_immagine(x["locandina"], "la locandina", w, err)
    if "foto_inviate" not in x and "foto_da" not in x:
        return
    f = x.get("foto_inviate")
    if not isinstance(f, list) or not 1 <= len(f) <= FOTO_MAX:
        err.append(f"{w}: «foto_inviate» è un elenco da 1 a {FOTO_MAX} foto («<id del comunicato>/<numero>»)")
        return
    if len({str(r) for r in f}) < len(f) or str(x.get("locandina")) in {str(r) for r in f}:
        err.append(f"{w}: la stessa immagine due volte (tra «foto_inviate» e «locandina»)")
    for r in f:
        _controlla_immagine(r, "la foto", w, err)
    chi = x.get("foto_da")
    if not isinstance(chi, str) or not 2 <= len(chi.strip()) <= 80:
        err.append(f"{w}: con «foto_inviate» scrivi «foto_da»: chi le ha mandate (chi firma il comunicato)")


def risolvi_locandine(voci):
    """Copia in img/locandine/ le locandine e le foto («foto_inviate») indicate come "<id del comunicato>/<n>" e mette
    nel campo il percorso del sito. Un'immagine uguale già copiata (stesso contenuto) si riusa. Restituisce i file nuovi."""
    copiati = []
    cart = os.path.join(BASE, "img", "locandine")

    def nel_sito(rif, nome):
        src = sorgente_locandina(rif) if rif and not LOCANDINA.match(str(rif)) else None
        if not src:
            return rif
        with open(src, "rb") as f:
            dati = f.read()
        impronta = hashlib.sha1(dati).hexdigest()
        for q in sorted(glob.glob(os.path.join(cart, "*.jpg"))):
            with open(q, "rb") as f:
                if hashlib.sha1(f.read()).hexdigest() == impronta:
                    return "img/locandine/" + os.path.basename(q)
        os.makedirs(cart, exist_ok=True)
        k, rel = 1, f"img/locandine/{nome}.jpg"
        while os.path.exists(os.path.join(BASE, rel)):
            k += 1
            rel = f"img/locandine/{nome}-{k}.jpg"
        with open(os.path.join(BASE, rel), "wb") as f:
            f.write(dati)
        copiati.append(rel)
        return rel

    for x in voci:
        if x.get("locandina"):
            x["locandina"] = nel_sito(x["locandina"], str(x.get("id")))
        if isinstance(x.get("foto_inviate"), list):
            x["foto_inviate"] = list(dict.fromkeys(nel_sito(r, f"{x.get('id')}-foto") for r in x["foto_inviate"]))
    return copiati


PAROLE_VUOTE = {"del", "della", "dello", "dei", "degli", "delle", "di", "da", "al", "alla", "allo", "ai", "agli", "alle",
                "a", "in", "il", "lo", "la", "i", "gli", "le", "e", "con", "per", "su", "tra", "fra", "un", "una", "uno",
                "nel", "nella", "sul", "sulla", "edizione", "2026", "2027"}


def parole_titolo(t):
    return {w for w in re.findall(r"[a-zà-ù0-9]+", str(t).lower().replace("'", " ")) if w not in PAROLE_VUOTE and len(w) > 2}


def doppioni_eventi(eventi):
    """Coppie di eventi che sembrano lo stesso: stesso Comune, giorni che si toccano, titoli simili (metà delle parole
    importanti in comune). Voluto dal proprietario il 25 ott 2026 con gli eventi mandati per posta: «stai attento a non
    creare doppioni»."""
    out = []
    for i, a in enumerate(eventi):
        for b in eventi[i + 1:]:
            if str(a.get("comune")).lower() != str(b.get("comune")).lower():
                continue
            fa, fb = a.get("fine") or a.get("inizio"), b.get("fine") or b.get("inizio")
            if not (str(a.get("inizio")) <= str(fb) and str(b.get("inizio")) <= str(fa)):
                continue
            if a.get("ora") and b.get("ora") and a["ora"] != b["ora"] and a.get("inizio") == b.get("inizio") == fa == fb:
                continue   # due spettacoli dello stesso giorno a ore diverse
            pa, pb = parole_titolo(a.get("titolo")), parole_titolo(b.get("titolo"))
            if pa and pb and len(pa & pb) >= max(2, min(len(pa), len(pb)) / 2):
                out.append((a.get("id"), b.get("id")))
    return out


def controlla_eventi(ev, err):
    """Le regole di AGENTE.md («Il calendario degli eventi») su eventi.json."""
    if not isinstance(ev.get("eventi"), list):
        err.append("eventi.json: manca la lista eventi")
        return
    esc = ev.get("stagioni_escluse", {})   # le date ufficiali da non riproporre (strumenti/stagioni.py)
    if not isinstance(esc, dict) or not all(isinstance(m, str) and m.strip() for m in esc.values()):
        err.append("eventi.json: «stagioni_escluse» dev'essere {\"chiave\": \"motivo\"} (la chiave la stampa strumenti/stagioni.py)")
    temi = temi_foto()
    for x in ev["eventi"]:
        w = "evento " + str(x.get("id", "?"))
        for k in ("id", "titolo", "tipo", "inizio", "luogo", "comune", "zona", "breve", "fonti"):
            if vuoto(x.get(k)):
                err.append(f"{w}: campo vuoto o mancante {k}")
        if not re.match(r"^[a-z0-9]+(-[a-z0-9]+)*$", str(x.get("id", ""))):
            err.append(f"{w}: id non valido (solo minuscole, numeri e trattini)")
        if x.get("tipo") not in TIPI_EVENTO:
            err.append(f"{w}: tipo {x.get('tipo')!r} non ammesso ({', '.join(sorted(TIPI_EVENTO))})")
        if x.get("zona") not in ZONE:
            err.append(f"{w}: zona {x.get('zona')!r} non ammessa")
        if not GIORNO.match(str(x.get("inizio", ""))):
            err.append(f"{w}: inizio deve essere AAAA-MM-GG")
        if "fine" in x and (not GIORNO.match(str(x["fine"])) or str(x["fine"]) < str(x.get("inizio", ""))):
            err.append(f"{w}: fine deve essere AAAA-MM-GG, non prima di inizio")
        if "giorni" in x:
            gg = x["giorni"]
            if (not isinstance(gg, list) or len(gg) < 2 or not all(GIORNO.match(str(g)) for g in gg) or gg != sorted(set(gg))
                    or gg[0] != x.get("inizio") or gg[-1] != x.get("fine")):
                err.append(f"{w}: giorni deve essere l'elenco ordinato dei giorni AAAA-MM-GG, dal giorno di inizio a quello di fine")
        if "ora" in x and not ORA.match(str(x["ora"])):
            err.append(f"{w}: ora deve essere HH:MM")
        if x.get("orari") and (x.get("giorni") or not x.get("fine")) and not ORE_IN_ORARI.search(str(x["orari"])):
            err.append(f"{w}: «orari» non dice le ore, ripete solo i giorni (che la pagina mostra già in «Quando»): "
                       "se la fonte non dice le ore, togli «orari»")
        nomi_ok = lambda v: isinstance(v, list) and v and all(isinstance(y, str) and y.strip() for y in v)
        if "organizzatore" in x and not (nomi_ok(x["organizzatore"]) or isinstance(x["organizzatore"], str) and x["organizzatore"].strip()):
            err.append(f"{w}: organizzatore deve essere un nome o un elenco di nomi")
        if "artisti" in x and not nomi_ok(x["artisti"]):
            err.append(f"{w}: artisti deve essere un elenco di nomi")
        controlla_locandina(x, w, err)
        if "annullato" in x and not isinstance(x["annullato"], bool):
            err.append(f"{w}: annullato deve essere true o false")
        if x.get("immagine") and x["immagine"] not in temi:
            err.append(f"{w}: immagine {x['immagine']!r} non è un tema di img/temi/temi.json")
        nomi = [f.get("nome") for f in x.get("fonti") or []]
        if len(nomi) != len(set(nomi)):
            err.append(f"{w}: nomi ripetuti nelle fonti")
        for f in x.get("fonti") or []:
            for k in ("nome", "titolo", "url", "data"):
                if vuoto(f.get(k)):
                    err.append(f"{w}: fonte {f.get('nome')} senza {k}")
            if f.get("url") and not re.match(r"^https?://", str(f["url"])):
                err.append(f"{w}: url non valido {f['url']!r}")
        for r in x.get("descrizione") or []:
            if vuoto(r.get("testo")) or vuoto(r.get("fonti")):
                err.append(f"{w}: paragrafo della descrizione senza testo o senza fonti")
            for nm in r.get("fonti", []):
                if nm not in nomi:
                    err.append(f"{w}: la descrizione cita {nm!r} che non è nelle fonti")
    for a, b in doppioni_eventi(ev["eventi"]):
        err.append(f"eventi {a} e {b}: sembrano lo stesso evento (stesso Comune, stessi giorni, titolo simile): tienine "
                   "uno solo e aggiorna quello (date, orari, fonti, locandina)")


def primo_giorno_titolo(titolo, pubblicato):
    """Il primo giorno scritto nel titolo, AAAA-MM-GG: «chiuse dal 29 ottobre al 1° novembre» → 29 ottobre, «sabato 24
    e 31 ottobre» e «il 1° e il 2 novembre» → il primo. Non le scadenze («entro il 30», «fino al 2 novembre»). L'anno è
    quello di pubblicato (o il successivo, per gennaio scritto a dicembre). None se non c'è."""
    m = re.search(rf"(?<!fino al )(?<!entro il )(?<!entro l')\b(\d{{1,2}})°?(?:\s*(?:e|-)\s*(?:il\s+|l')?\d{{1,2}}°?)?\s+"
                  rf"({NOMI_MESI})\b",
                  str(titolo or "").lower())
    p = str(pubblicato or "")[:10]
    if not m or not GIORNO.match(p):
        return None
    anno = int(p[:4]) + (1 if MESI[m[2]] < int(p[5:7]) - 6 else 0)
    try:
        return dt.date(anno, MESI[m[2]], int(m[1])).isoformat()
    except ValueError:
        return None


def zona_dal_luogo(d, avv):
    """La zona la decide il Comune scritto nel luogo (ZONA_COMUNE): «San Giorgio del Sannio» non è «Benevento città».
    Si cambia solo se il luogo nomina Comuni di una zona sola e non tutta la provincia («Sannio», «provincia di
    Benevento», «Campania»); le trasferte («Cremona, stadio Zini») restano come le ha scritte l'agente. Se nomina Comuni
    di più zone, «Benevento città» resta solo se tra loro c'è Benevento."""
    for n in d.get("notizie", []):
        pezzi = [p.strip().replace("’", "'").lower() for p in re.split(r"[,()]| e ", str(n.get("luogo") or ""))]
        if any(p in ("sannio", "campania") or "provincia" in p for p in pezzi):
            continue
        zone = {ZONA_COMUNE[p] for p in pezzi if p in ZONA_COMUNE}
        nuova = zone.pop() if len(zone) == 1 else "provincia" if zone and n.get("zona") == "benevento" and "benevento" not in zone else None
        if nuova and n.get("zona") != nuova:
            avv.append(f"{n.get('id')}: zona {n.get('zona')!r} cambiata in {nuova!r}, dal luogo «{n.get('luogo')}»")
            n["zona"] = nuova


def controlla_scena(x, w, err, storia=False):
    """La scena per la foto fatta con l'IA (strumenti/foto_ia.py): voluta dal proprietario il 28 ott 2026, «regola tutte
    foto, se non la trovi ne crei una perfetta cinematografica con gpt», «devono rappresentare bene la scena raccontata».
    Serve a ogni notizia della prima pagina senza foto vera (locandina, foto inviate) e senza un tema adatto (sulla
    cronaca il tema non c'è mai), e a ogni storia (approfondimento) senza foto vera."""
    s = x.get("scena")
    if s is not None and (not isinstance(s, str) or not 60 <= len(s.strip()) <= 700):
        err.append(f"{w}: «scena» è la descrizione della foto da fare con l'IA, da 60 a 700 caratteri")
        return
    vera = x.get("locandina") or x.get("foto_inviate")
    tema = not storia and x.get("immagine") and x.get("categoria") != "cronaca"
    if not vera and not tema and not s and not x.get("diretta_calcio") and not x.get("archiviato"):
        err.append(f"{w}: niente foto: scrivi «scena», la scena da fotografare con l'IA (AGENTE.md, «La foto della "
                   f"notizia»)" + ("" if storia else " o metti un tema adatto in «immagine»"))


def controlla(d, err, avv, adesso=None):
    """Le stesse regole di AGENTE.md, sul file della prima pagina. Prima mette la zona giusta (zona_dal_luogo)."""
    zona_dal_luogo(d, avv)
    for k in ("aggiornato", "giornali_letti", "notizie", "approfondimenti"):
        if k not in d:
            err.append(f"manca il campo {k}")
    if err:
        return
    if not ISO.match(str(d.get("aggiornato", ""))):
        err.append("aggiornato non è una data ISO")
    elif adesso and nel_futuro(d["aggiornato"], adesso):
        err.append(f"aggiornato è nel futuro ({d['aggiornato']}): usa l'ora vera, TZ=Europe/Rome date -Iminutes")

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
        if n.get("categoria") == "sport" and n.get("sport") not in SPORT:
            err.append(f"{w}: una notizia di sport vuole «sport», uno di: {', '.join(sorted(SPORT))}")
        if n.get("zona") not in ZONE:
            err.append(f"{w}: zona non ammessa {n.get('zona')!r}")
        if n.get("stato") not in STATI:
            err.append(f"{w}: stato non ammesso {n.get('stato')!r}")
        if not isinstance(n.get("rilevante"), bool):
            err.append(f"{w}: rilevante deve essere true o false")
        # l'importanza da 1 a 5 per la classifica dei social (AGENTE.md, dal 26 ott 2026): se manca la ricava facebook.py
        imp = n.get("importanza")
        if "importanza" in n and (isinstance(imp, bool) or not isinstance(imp, int) or not 1 <= imp <= 5):
            err.append(f"{w}: importanza deve essere un numero da 1 a 5 (AGENTE.md, «L'importanza per i social»)")
        elif "importanza" not in n and adesso and str(n.get("pubblicato", ""))[:10] == adesso.date().isoformat():
            avv.append(f"{w}: manca «importanza» (1-5, AGENTE.md «L'importanza per i social»): la ricava il programma")
        if not ISO.match(str(n.get("pubblicato", ""))):
            err.append(f"{w}: pubblicato non ISO {n.get('pubblicato')!r}")
        elif adesso and nel_futuro(n["pubblicato"], adesso):
            err.append(f"{w}: pubblicato è nel futuro ({n['pubblicato']})")
        if "in_vigore_fino" in n and not GIORNO.match(str(n.get("in_vigore_fino"))):
            err.append(f"{w}: in_vigore_fino deve essere AAAA-MM-GG")
        if "in_vigore_dal" in n and not GIORNO.match(str(n.get("in_vigore_dal"))):
            err.append(f"{w}: in_vigore_dal deve essere AAAA-MM-GG")
        elif n.get("in_vigore_dal") and str(n.get("in_vigore_fino") or "9") < n["in_vigore_dal"]:
            err.append(f"{w}: in_vigore_dal ({n['in_vigore_dal']}) è dopo in_vigore_fino ({n['in_vigore_fino']})")
        # il primo giorno scritto nel titolo e in_vigore_dal devono tornare: la pagina Avvisi mette in «Oggi» quello che
        # vale già (28 ott 2026: la sagra di Vitulano «dal 29 ottobre» risultava dal 26, il giorno in cui era uscita)
        if n.get("in_vigore_fino") and n.get("categoria") in ("avvisi", "strade") and adesso:
            pg = primo_giorno_titolo(n.get("titolo"), n.get("pubblicato"))
            if (pg and pg > adesso.date().isoformat() and pg > (n.get("in_vigore_dal") or str(n.get("pubblicato"))[:10])
                    and pg <= str(n["in_vigore_fino"])):
                avv.append(f"{w}: il titolo dice che comincia il {pg}, ma in_vigore_dal è {n.get('in_vigore_dal') or 'assente'}: "
                           "metti il primo giorno vero (la pagina Avvisi lo mostra in «Oggi» solo da quel giorno)")
        if "traffico" in n and n["traffico"] not in TRAFFICO:
            err.append(f"{w}: traffico non ammesso {n['traffico']!r}: uno di {', '.join(sorted(TRAFFICO))} "
                       "(oppure togli il campo)")
        tg = str(n.get("titolo_google") or "")
        if not tg.strip():
            avv.append(f"{w}: manca titolo_google (Google mostrerà il titolo lungo tagliato)")
        elif len(tg) > 70:
            err.append(f"{w}: titolo_google di {len(tg)} caratteri: al massimo 65")
        tit = str(n.get("titolo", ""))
        if n.get("categoria") == "meteo" and GIALLA.search(tit) and not PIU_ALTA.search(tit) and not CHIUSURE.search(tit):
            err.append(f"{w}: è solo un'allerta gialla, che non si pubblica (AGENTE.md, «Le Allerte»): togli la notizia "
                       "(nel diario `allerta_gialla`); le chiusure dei Comuni le pubblica il giro Chiusure")
        tl = (tit + " " + tg).lower()
        for b in VIETATE:
            if b in tl:
                err.append(f"{w}: titolo con {b!r}")
        nomi_prima = [f.get("nome") for f in n.get("fonti", [])]
        if len(nomi_prima) != len(set(nomi_prima)):
            err.append(f"{w}: testata ripetuta nelle fonti di prima pagina")
        for f in n.get("fonti", []):
            if vuoto(f.get("nome")) or vuoto(f.get("url")):
                err.append(f"{w}: fonte di prima pagina incompleta {f}")
        # i campi del giro lampo dei comunicati per email (strumenti/comunicati.py): non vanno toccati
        if "subito" in n and not isinstance(n["subito"], bool):
            err.append(f"{w}: «subito» è vero o falso (lo mette il giro lampo: non toccarlo)")
        # (gli id dei comunicati per email sono 12 cifre esadecimali; quelli degli articoli dei siti ufficiali, dal
        # 25 ott 2026, «u» e 11: strumenti/ufficiali.py)
        if "comunicati" in n and (not isinstance(n["comunicati"], list)
                                  or any(not re.fullmatch(r"u[0-9a-f]{11}|[0-9a-f]{12}", str(c)) for c in n["comunicati"])):
            err.append(f"{w}: «comunicati» è l'elenco degli id (12 caratteri) dei comunicati per email o degli articoli "
                       "dei siti ufficiali da cui viene")
        if n.get("stato") == "confermata":
            testate = {re.sub(r"\s*\(.*\)$", "", x or "") for x in nomi_prima}
            if len(testate) < 2:
                err.append(f"{w}: 'confermata' con meno di 2 testate")
        if n.get("stato") == "una_fonte":
            testate = {re.sub(r"[^a-z0-9]", "", re.sub(r"\s*\(.*\)$", "", x or "").lower()) for x in nomi_prima}
            if len(testate) != 1:
                err.append(f"{w}: 'una_fonte' vuole una sola testata (con due è 'confermata')")
            elif not testate <= AUTOREVOLI and not (n.get("diretta_calcio") and testate == {"espn"}):
                # l'articolo di fine partita del Benevento (strumenti/gol.py): il risultato viene dai dati di ESPN
                err.append(f"{w}: 'una_fonte' solo con una testata autorevole (regola 2), non {nomi_prima[0]!r}")
            if n.get("categoria") not in UNA_FONTE_CAT:
                err.append(f"{w}: 'una_fonte' solo per {', '.join(UNA_FONTE_CAT)} (mai allerte ed eventi)")
            if n.get("rilevante"):
                err.append(f"{w}: una notizia con una sola fonte non può essere 'rilevante'")
        controlla_locandina(n, w, err)
        if "immagine" in n:
            if n.get("categoria") == "cronaca":
                err.append(f"{w}: niente immagine sulla cronaca (togli il campo immagine)")
            elif n["immagine"] not in temi_foto():
                err.append(f"{w}: immagine {n['immagine']!r} non è un tema di img/temi/temi.json")
        controlla_scena(n, w, err)
        a = n.get("articolo") or {}
        # con un comunicato arrivato per email niente «Cosa non si sa ancora»: elencare cosa manca sembra una
        # mancanza di rispetto verso chi ce lo manda (voluto dal proprietario il 26 ott 2026)
        per_posta = any(re.fullmatch(r"[0-9a-f]{12}", str(c)) for c in n.get("comunicati") or [])
        if a.get("non_si_sa") and per_posta:
            avv.append(f"{w}: viene da un comunicato per email, «non_si_sa» non si scrive: l'ho svuotato")
            a["non_si_sa"] = []
        # e nemmeno dentro il testo: «non è indicato», «il comunicato non dice»… (lui, 26 ott 2026: «nessuna figuraccia
        # nel nostro articolo»; spesso il dato c'era, nella locandina o in un allegato)
        pezzi = [n.get("titolo"), n.get("titolo_google"), n.get("sintesi"), a.get("cosa"), (a.get("aggiornamento") or {})]
        pezzi += [p for p in a.get("racconto") or [] if isinstance(p, dict)]
        testo = " ".join(str((x.get("testo") if isinstance(x, dict) else x) or "") for x in pezzi)
        frase = NON_DETTO.search(testo) if per_posta else None
        if frase:
            err.append(f"{w}: viene da un comunicato per email e dice «{frase.group(0)}»: rileggi il comunicato, gli "
                       "allegati e la locandina; se il dato c'è scrivilo, se non c'è non dire che manca")
        if vuoto(a.get("cosa")) and vuoto(a.get("racconto")):
            err.append(f"{w}: articolo senza racconto (né cosa)")
        nomi = [f.get("nome") for f in a.get("fonti", [])]
        if not nomi:
            err.append(f"{w}: articolo.fonti vuoto")
        if len(nomi) != len(set(nomi)):
            err.append(f"{w}: nomi ripetuti in articolo.fonti")
        for f in a.get("fonti", []):
            for k in ("nome", "titolo", "url", "data"):
                if vuoto(f.get(k)):
                    err.append(f"{w}: articolo.fonti {f.get('nome')} senza {k}")
        for sez in ("racconto", "cronologia", "concordano", "divergono"):
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
                if sez == "cronologia" and "quando" in x and not QUANDO.match(str(x["quando"])):
                    err.append(f"{w}: cronologia con quando {x['quando']!r}: AAAA-MM-GG o AAAA-MM-GGTHH:MM")
        # storia di più giorni (o aggiornata): ogni paragrafo dice di che giorno è; sul sito la data sta sopra i
        # paragrafi di quel giorno, dal più recente al più vecchio
        rac = [x for x in a.get("racconto") or [] if isinstance(x, dict)]
        giorni = [str(x.get("giorno") or "") for x in rac]
        if rac and (any(giorni) or "aggiornamento" in a):
            if not all(giorni):
                err.append(f"{w}: notizia di più giorni o aggiornata: ogni paragrafo del racconto vuole «giorno» "
                           "(AAAA-MM-GG, il giorno dei fatti di quel paragrafo)")
            elif not all(re.fullmatch(r"\d{4}-\d{2}-\d{2}", g) for g in giorni):
                err.append(f"{w}: racconto con «giorno» non AAAA-MM-GG ({', '.join(giorni)})")
            elif adesso and max(giorni) > adesso.date().isoformat():
                err.append(f"{w}: racconto con «giorno» nel futuro ({max(giorni)})")
            elif giorni != sorted(giorni, reverse=True):
                err.append(f"{w}: il racconto va per giorni, dal più recente al più vecchio (ora: {' '.join(g[5:] for g in giorni)})")
        if "aggiornamento" in a:
            ag = a["aggiornamento"]
            if not isinstance(ag, dict) or vuoto(ag.get("testo")) or vuoto(ag.get("fonti")):
                err.append(f"{w}: aggiornamento vuole testo e fonti")
            else:
                for nm in ag["fonti"]:
                    if nm not in nomi:
                        err.append(f"{w}: aggiornamento cita {nm!r} che non è in articolo.fonti")
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
        controlla_scena(ap, w, err, storia=True)
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


def cosa_breve(a):
    """Per l'indice della ricerca: «cosa», oppure il primo paragrafo del racconto."""
    if a.get("cosa"):
        return a["cosa"]
    r = a.get("racconto") or []
    return (r[0] or {}).get("testo", "") if r and isinstance(r[0], dict) else ""


def voce_indice(x, tipo, mese):
    if tipo == "notizia":
        return {"id": x["id"], "tipo": "notizia", "titolo": x.get("titolo", ""), "sintesi": x.get("sintesi", ""),
                "luogo": x.get("luogo", ""), "categoria": x.get("categoria", ""), "zona": x.get("zona", ""),
                "pubblicato": x.get("pubblicato", ""), "cosa": cosa_breve(x.get("articolo") or {}), "mese": mese}
    return {"id": x["id"], "tipo": "approfondimento", "titolo": x.get("titolo", ""), "sintesi": x.get("sommario", ""),
            "luogo": x.get("luogo", ""), "pubblicato": x.get("aggiornato", ""), "cosa": "", "mese": mese}


# La quarantena, l'ultima rete (voluta dal proprietario il 25 ott 2026: «un solo errore blocca tutto il giro»): se gli
# errori riguardano solo alcune notizie o alcuni eventi, quelli restano fuori (una notizia o un evento già pubblicati
# tornano com'erano) e il resto esce. Le versioni scartate, con i loro errori, stanno in diario/quarantena.json, che
# giornali.py mostra al giro dopo perché vengano corrette. Gli errori del giro intero (registro, diario, decisioni, id
# doppi) bloccano come prima: sono lavoro da fare, non una voce sbagliata.
QUARANTENA = os.path.join("diario", "quarantena.json")
QUARANTENA_ORE = 48   # dopo, una voce mai corretta si toglie dalla quarantena (e lo si dice)
DOPO_QUARANTENA = "ARCHIVIA_QUARANTENA"   # gli id in quarantena, per il secondo passaggio


def voce_dell_errore(e, id_notizie, id_eventi):
    """Le voci a cui si riferisce un errore: [("notizia"|"evento", id)], [("doppione", a, b)], o None se l'errore
    riguarda il giro intero."""
    if "usato più volte" in e or "doppio nell'archivio" in e:
        return None
    m = re.match(r"eventi ([a-z0-9-]+) e ([a-z0-9-]+): sembrano lo stesso evento", e)
    if m:
        return [("doppione", m[1], m[2])]
    m = re.match(r"evento ([a-z0-9-]+): ", e)
    if m and m[1] in id_eventi:
        return [("evento", m[1])]
    m = re.match(r"id '([a-z0-9-]+)' è (?:già usato|di una notizia già unita)", e) or re.match(r"([a-z0-9-]+): ", e)
    if m and m[1] in id_notizie:
        return [("notizia", m[1])]
    return None


def impronta(x):
    return hashlib.sha1(json.dumps(x, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:12]


def eventi_prima(base):
    """eventi.json com'era all'ultimo salvataggio (git HEAD), o None."""
    try:
        p = subprocess.run(["git", "-C", base, "show", "HEAD:eventi.json"], capture_output=True, timeout=30)
        return json.loads(p.stdout.decode("utf-8")) if p.returncode == 0 else None
    except Exception:
        return None


def metti_in_quarantena(err, d, ev, base):
    """Prova la quarantena: True se ha scritto tutto (il secondo passaggio ha finito con OK), False se gli errori non
    si possono isolare o se anche dopo restano errori (allora rimette i file com'erano)."""
    id_notizie = {x.get("id") for x in d.get("notizie", []) + d.get("approfondimenti", [])}
    id_eventi = {x.get("id") for x in (ev or {}).get("eventi", [])}
    prima_n, prima_e = pubblicate_prima(base) or {}, eventi_prima(base) or {}
    vecchie_e = {x.get("id"): x for x in prima_e.get("eventi", [])}
    colpe = {}
    for e in err:
        voci = voce_dell_errore(e, id_notizie, id_eventi)
        if voci is None:
            return False
        for v in voci:
            if v[0] == "doppione":   # resta fuori quello nuovo; se lo sono tutti e due, il secondo
                nuovi = [i for i in v[1:] if i not in vecchie_e]
                if not nuovi:
                    return False
                v = ("evento", nuovi[-1])
            colpe.setdefault(v, []).append(e)
    p_n, p_e, p_q = (os.path.join(base, x) for x in ("notizie.json", "eventi.json", QUARANTENA))
    originali = {}
    for p in (p_n, p_e, p_q):
        originali[p] = open(p, encoding="utf-8").read() if os.path.exists(p) else None
    q = leggi(p_q, {}) or {}
    q_voci = [x for x in q.get("voci") or [] if (x.get("tipo"), x.get("id")) not in colpe]
    adesso = dt.datetime.now(dt.timezone.utc).astimezone().isoformat(timespec="minutes")
    for (tipo, i), errori in colpe.items():
        if tipo == "notizia":
            liste = [(d["notizie"], {x.get("id"): x for x in prima_n.get("notizie", [])}),
                     (d["approfondimenti"], {x.get("id"): x for x in prima_n.get("approfondimenti", [])})]
        else:
            liste = [(ev["eventi"], vecchie_e)]
        for lista, vecchie in liste:
            k = next((n for n, x in enumerate(lista) if x.get("id") == i), None)
            if k is None:
                continue
            scartata = lista[k]
            if i in vecchie:
                lista[k] = vecchie[i]
                stato, impr = "rimessa com'era (la versione pubblicata)", impronta(vecchie[i])
            else:
                del lista[k]
                stato, impr = "tolta (era nuova)", ""
            q_voci.append({"tipo": tipo, "id": i, "quando": adesso, "stato": stato, "impronta_pubblicata": impr,
                           "errori": errori, "versione_scartata": scartata})
            print(f"QUARANTENA: {tipo} {i}: {stato}, per {len(errori)} errori: {errori[0][:160]}")
    with open(p_n, "w", encoding="utf-8") as f:
        f.write(testo_json(d))
    if ev is not None:
        with open(p_e, "w", encoding="utf-8") as f:
            f.write(testo_json(ev))
    os.makedirs(os.path.dirname(p_q), exist_ok=True)
    with open(p_q, "w", encoding="utf-8") as f:
        f.write(testo_json({"voci": q_voci}))
    ids = ",".join(f"{t_}:{i}" for t_, i in colpe)
    r = subprocess.run([sys.executable, os.path.abspath(__file__)] + sys.argv[1:], capture_output=True, text=True,
                       env=dict(os.environ, **{DOPO_QUARANTENA: ids}))
    if r.returncode == 0:
        print(r.stdout, end="")
        print(f"CAMBIATO: {QUARANTENA}")
        print("QUARANTENA: il resto è uscito. Se puoi, correggi adesso le voci in quarantena (le trovi in "
              f"{QUARANTENA}, con gli errori), rimettile e rilancia; se no restano per il giro dopo.")
        return True
    for p, testo_ in originali.items():   # anche così non va: tutto com'era, e gli errori di prima
        if testo_ is None:
            if os.path.exists(p):
                os.remove(p)
        else:
            with open(p, "w", encoding="utf-8") as f:
                f.write(testo_)
    print("QUARANTENA NON BASTA: anche senza quelle voci restano errori; rimesso tutto com'era.")
    print("\n".join("  " + x for x in r.stdout.splitlines() if x.startswith("ERRORE")))
    return False


def in_quarantena():
    """Gli id messi in quarantena dal primo passaggio: {("notizia"|"evento", id)}."""
    return {tuple(x.split(":", 1)) for x in os.environ.get(DOPO_QUARANTENA, "").split(",") if ":" in x}


def pulisci_quarantena(base, d, ev, avv):
    """Le voci in quarantena corrette e rimesse (o troppo vecchie) escono dal file. Restituisce il testo nuovo o None."""
    p_q = os.path.join(base, QUARANTENA)
    q = leggi(p_q, None)
    if not q or not q.get("voci"):
        return None
    attuali = {("notizia", x.get("id")): x for x in d.get("notizie", []) + d.get("approfondimenti", [])}
    attuali.update({("evento", x.get("id")): x for x in (ev or {}).get("eventi", [])})
    limite = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=QUARANTENA_ORE)).isoformat()
    restano = []
    for x in q["voci"]:
        cur = attuali.get((x.get("tipo"), x.get("id")))
        rifatta = cur is not None and (not x.get("impronta_pubblicata") or impronta(cur) != x["impronta_pubblicata"])
        if rifatta:
            print(f"QUARANTENA: {x['tipo']} {x['id']} corretta e rimessa: tolta dalla quarantena")
        elif str(x.get("quando")) < limite:
            avv.append(f"quarantena: {x['tipo']} {x['id']} non è mai stata corretta in {QUARANTENA_ORE} ore: tolta "
                       "dalla quarantena (la versione scartata è nella storia di git)")
        else:
            restano.append(x)
    return None if len(restano) == len(q["voci"]) else testo_json({"voci": restano})


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--prova", action="store_true", help="non scrive niente")
    ap.add_argument("--oggi", help="data AAAA-MM-GG da usare al posto di oggi (prove)")
    ap.add_argument("--giro", action="store_true", help="fine del giro dell'agente: controlla il registro delle fonti "
                    "e mette l'ora di adesso in «aggiornato»")
    ap.add_argument("--registro", default="/tmp/fonti.txt", help="il registro delle fonti del giro")
    ap.add_argument("--diario", default="/tmp/diario.json", help="il diario del giro scritto dall'agente")
    ap.add_argument("--inizio", default="/tmp/inizio_giro", help="l'ora di inizio del giro (per la durata)")
    ap.add_argument("--titoli", default="/tmp/titoli.json", help="l'elenco degli articoli nuovi (strumenti/giornali.py)")
    ap.add_argument("--registro-giornali", default="/tmp/fonti_giornali.txt",
                    help="le righe dei giornali per il registro (le scrive strumenti/giornali.py)")
    ap.add_argument("--cartella", default=os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    a = ap.parse_args()
    global BASE
    base = BASE = a.cartella
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
    adesso_roma = None
    if not a.oggi:
        try:
            from zoneinfo import ZoneInfo
            adesso_roma = dt.datetime.now(ZoneInfo("Europe/Rome"))
        except Exception:
            adesso_roma = None
    controlla(d, err, avv, adesso_roma)
    giro = None
    if a.giro:
        # le chiusure dei Comuni le pubblica il giro Chiusure (chiusure.json): una notizia in più sarebbe un doppione
        gia = {n.get("id") for n in (pubblicate_prima(base) or {}).get("notizie", [])}
        for n in d.get("notizie", []):
            if n.get("id") not in gia and CHIUSURA.search(str(n.get("titolo") or "")):
                err.append(f"{n.get('id')}: parla di una chiusura decisa da un Comune, che la pubblica il giro Chiusure "
                           "(pagina Scuole chiuse e social): togli la notizia e nel diario scrivi «chiusure» (AGENTE.md, "
                           "«Le Allerte»)")
        controlla_registro(a.registro, err, a.registro_giornali)
        giro = leggi_diario(a.diario, err)
    p_eventi = os.path.join(base, "eventi.json")
    try:
        ev = leggi(p_eventi)
    except Exception as e:
        print("ERRORE: eventi.json non è un JSON valido:", e)
        sys.exit(1)
    if ev is not None:
        controlla_eventi(ev, err)
        ev_arch = {}
        for p in sorted(glob.glob(os.path.join(cart_arch, "eventi-[0-9][0-9][0-9][0-9]-[0-9][0-9].json"))):
            ev_arch[os.path.basename(p)[7:14]] = leggi(p)
        ev_originali = {k: testo_json(v) for k, v in ev_arch.items()}
        visti_ev = {}
        for mese, m in ev_arch.items():
            for x in m.get("eventi", []):
                visti_ev.setdefault(x.get("id"), []).append("archivio " + mese)
        for x in ev.get("eventi") or []:
            visti_ev.setdefault(x.get("id"), []).append("eventi.json")
        for i, dove in visti_ev.items():
            if len(dove) > 1:
                err.append(f"evento {i!r}: id usato più volte ({', '.join(dove)}): scegline un altro")

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
    rimandi = (leggi(os.path.join(cart_arch, "rimandi.json"), {}) or {}).get("notizie") or {}
    for i in correnti:
        if i in rimandi:
            err.append(f"id {i!r} è di una notizia già unita in {rimandi[i]!r} (archivio/rimandi.json): scegline un altro")
    for vecchio, nuovo in rimandi.items():
        if nuovo not in tutti_gli_id:
            err.append(f"archivio/rimandi.json: {vecchio!r} porta a {nuovo!r}, che non esiste")
    for x in d.get("approfondimenti", []):
        for c in x.get("collegate", []):
            if c not in tutti_gli_id:
                err.append(f"{x.get('id')}: notizia collegata {c!r} non esiste")

    titoli = None
    if a.giro and giro is not None:   # una decisione per ogni fatto nuovo dei giornali (strumenti/giornali.py)
        titoli = controlla_decisioni(giro, a.titoli, d, pubblicate_prima(base), tutti_gli_id, ev, err)

    if err and not a.prova and not os.environ.get(DOPO_QUARANTENA) and metti_in_quarantena(err, d, ev, base):
        return   # il secondo passaggio, senza le voci in quarantena, ha scritto tutto e stampato OK
    if err:
        for x in avv:
            print("AVVISO:", x)
        for x in err:
            print("ERRORE:", x)
        print(f"{len(err)} ERRORI: niente è stato scritto")
        sys.exit(1)
    # le locandine arrivate per posta si copiano nel sito solo quando è tutto a posto
    locandine = [] if a.prova else risolvi_locandine(d.get("notizie", []) + ((ev or {}).get("eventi") or []))

    # L'ora dei riquadri «Aggiornamento» e i fatti in ordine di tempo: li fa il programma, così non si sbagliano.
    if a.giro:   # il sito dice a che ora è stato controllato l'ultima volta, anche quando non c'è niente di nuovo
        d["aggiornato"] = (adesso_roma or dt.datetime.now(dt.timezone.utc).astimezone()).isoformat(timespec="minutes")
    prima = pubblicate_prima(base)
    segna_aggiornamenti(d, prima, adesso_roma or dt.datetime.now(dt.timezone.utc).astimezone(), avv)
    for x in d["notizie"] + d["approfondimenti"]:
        crono = x.get("cronologia") if "sommario" in x else (x.get("articolo") or {}).get("cronologia")
        rif = dt.date.fromisoformat(str(x.get("pubblicato") or x.get("aggiornato"))[:10])
        if ordina_cronologia(crono, rif, x["id"], avv):
            print(f"FATTI MESSI IN ORDINE: {x['id']}")

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
        elif n.get("in_vigore_dal") and n["in_vigore_dal"] >= soglia_pp:   # comincia più avanti: aspetta il suo giorno
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

    scegli_foto(restano)
    if ev is not None:
        # gli eventi finiti da più di GIORNI_EVENTI giorni passano in archivio/eventi-AAAA-MM.json (mese della fine)
        soglia_ev = (oggi - dt.timedelta(days=GIORNI_EVENTI)).isoformat()
        restano_ev = []
        for x in ev["eventi"]:
            fine = x.get("fine") or x["inizio"]
            if fine < soglia_ev:
                y = dict(x, archiviato_il=oggi.isoformat())
                ev_arch.setdefault(fine[:7], {"eventi": []})["eventi"].append(y)
                print(f"ARCHIVIATO EVENTO: {x['id']} ({fine}) → archivio/eventi-{fine[:7]}.json")
            else:
                restano_ev.append(x)
        for x in restano_ev:   # con la locandina niente foto fatta con l'IA
            if not x.get("immagine") and not x.get("locandina") and TEMA_TIPO.get(x.get("tipo")) in temi_foto():
                x["immagine"] = TEMA_TIPO[x["tipo"]]
        restano_ev.sort(key=lambda x: (x["inizio"], x.get("ora") or "", x["id"]))
        scegli_foto(restano_ev)
        ev_nuovo = dict(ev, eventi=restano_ev)
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
    if ev is not None:
        for mese, m in sorted(ev_arch.items()):
            m["eventi"].sort(key=lambda x: (x["inizio"], x["id"]))
            if ev_originali.get(mese) != testo_json(m):
                da_scrivere.append((os.path.join(cart_arch, f"eventi-{mese}.json"), testo_json(m)))
        with open(p_eventi, encoding="utf-8") as f:
            if f.read() != testo_json(ev_nuovo):
                da_scrivere.append((p_eventi, testo_json(ev_nuovo)))
    # sempre nello stesso formato (indent 1): così su GitHub si vedono solo le righe cambiate davvero
    with open(p_notizie, encoding="utf-8") as f:
        if vanno or vanno_ap or f.read() != testo_json(nuovo):
            da_scrivere.append((p_notizie, testo_json(nuovo)))

    da_togliere = []
    if giro is not None:   # il diario del giro, cifrato (strumenti/diario.py)
        voce = voce_diario(giro, d, prima, vanno, a.registro, a.inizio,
                           adesso_roma or dt.datetime.now(dt.timezone.utc).astimezone(), titoli, a.registro_giornali)
        file_diario, da_togliere = scrivi_diario(base, voce, oggi)
        da_scrivere.append(file_diario)
        print(f"Diario del giro delle {voce['ora']}: {len(voce['nuove'])} nuove, {len(voce['aggiornate'])} aggiornate, "
              f"{len(voce['scartate'])} scartate")

    testo_q = pulisci_quarantena(base, nuovo, ev_nuovo if ev is not None else None, avv)
    if testo_q is not None:
        da_scrivere.append((os.path.join(base, QUARANTENA), testo_q))
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
        for p in da_togliere:
            print("CAMBIEREBBE (tolto):", os.path.relpath(p, base))
        print("PROVA: niente è stato scritto")
        return
    os.makedirs(cart_arch, exist_ok=True)
    # Prima l'archivio, poi la prima pagina: se qualcosa va storto a metà, una notizia è al massimo in due posti, mai in nessuno.
    for p, t in da_scrivere:
        os.makedirs(os.path.dirname(p), exist_ok=True)
        tmp = p + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(t)
        os.replace(tmp, p)
        print("CAMBIATO:", os.path.relpath(p, base))
    if notizie_da_segnare:
        print("CAMBIATO: notizie.json")
    for p in locandine:   # le mette lui nel commit: il giro aggiunge solo i file JSON (git add del prompt)
        subprocess.run(["git", "-C", base, "add", p], capture_output=True)
        print("CAMBIATO:", p)
    for p in da_togliere:
        os.remove(p)
        print("CAMBIATO (tolto):", os.path.relpath(p, base))
    print("OK")


if __name__ == "__main__":
    main()
