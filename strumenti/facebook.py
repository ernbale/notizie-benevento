#!/usr/bin/env python3
"""Pubblica sulla Pagina Facebook (facebook.com/notiziebenevento) le notizie nuove, una alla volta.

Lo esegue GitHub dopo ogni pubblicazione del sito (a ogni giro dell'agente e ogni ora), così la pagina della
notizia e la sua scheda sono già online quando Facebook le legge.

- Dal 26 ott 2026 ogni notizia esce come post con la foto, come su Instagram (voluto dal proprietario: «non mi piace il
  link diretto alla nostra pagina su Facebook», «come le crei su Instagram mi piacciono di più», «fallo su Facebook
  come Instagram»): la scheda img/ig/<id>.jpg di pagine.immagine_ig (testata, foto, sezione e titolo grande), sotto
  il titolo, la sintesi e «Leggi tutto: <link>»; con le foto mandate col comunicato, quelle (foto_inviate). Niente più
  post con l'anteprima del link. Se la scheda non c'è, l'immagine di anteprima della pagina (img/n/<id>.png); se
  Facebook rifiuta la foto, il solo testo, sempre con «Leggi tutto».

- Le notizie dei comunicati arrivati per posta («subito», giro lampo) escono appena ci sono, senza pausa né tetto.
- Una notizia ogni PAUSA_MINUTI (20), senza tetto al giorno, solo dalle 6 fino al giro delle 22 compreso: senza
  raffiche che sembrano spam (scelte del proprietario: 23 ott 2026 50 minuti e 20 al giorno; 24 ott «aumenta i limiti»
  → 25 minuti e 35; 26 ott, dopo la raffica delle 15:17 senza nessun limite, «nessun tetto ma distanziati almeno ogni
  15/20 minuti, i comunicati vengono pubblicati tutti»). Il Pi fa partire la pubblicazione alle :00, :20 e :40
  (curiosita_via.py --giro), così c'è sempre un'occasione ogni 20 minuti. Dalle 23 alle 24 solo le allerte
  arancioni o rosse (allerta_seria): è il giro della sera prima di un'allerta arancione o rossa, con le scuole chiuse
  per domani. La gialla alle 23 no (scelta del proprietario, 23 ott 2026: vale per Facebook, Telegram e Instagram).
- Dalle RIEPILOGO_DALLE il riepilogo della giornata («Il Sannio oggi»): la copertina di Instagram (pagine.py) con le
  notizie più importanti di oggi e i loro link, una volta; dopo le notizie continuano a uscire, una ogni PAUSA_MINUTI.
- Sceglie la prima della classifica dei social tra le notizie delle ultime 12 ore non ancora pubblicate (e gli avvisi
  ancora in vigore degli ultimi GIORNI_AVVISI giorni): vedi CLASSIFICA qui sotto.
- Cosa è già uscito lo legge dalla Pagina stessa (i link dei post): niente file da tenere nel repository. Se Facebook
  non risponde alla lettura non pubblica niente, per non fare doppioni.
- La chiave è il «token della Pagina» nel segreto FB_PAGE_TOKEN di GitHub; senza chiave non fa niente.
  Il repository è pubblico: nei log si stampano solo gli esiti, mai la chiave.

Uso:  FB_PAGE_TOKEN=… python3 strumenti/facebook.py [--sito .] [--stato FILE]
      FB_SUBITO=2 …   (lanciato a mano da GitHub: 2 notizie adesso, senza aspettare la pausa tra un post e l'altro)
      python3 strumenti/facebook.py --prova      (dice cosa pubblicherebbe, senza chiave e senza toccare Facebook)
"""
import argparse
import datetime as dt
import http.client
import json
import os
import re
import socket
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

SITO = "https://notiziebenevento.it"
PAGINA = "Notizie Benevento"
GRAPH = "https://graph.facebook.com"
PAUSA_MINUTI = 20
ORE_FINESTRA = 12
# La classifica dei social, decisa col proprietario il 26 ott 2026 («creare una classifica con criterio e pubblicare il
# giusto»; fino ad allora contavano solo il numero di fonti e l'ora, e lo sciopero EAV è rimasto in coda per ore):
# l'importanza da 1 a 5 che scrive l'agente (AGENTE.md, «L'importanza per i social»: Benevento Calcio sempre 5,
# politica 4, la cronaca dei paesi come quella della città), più un po' per la fonte ufficiale, per Benevento città e
# per i giornali che la riportano; si dimezza ogni 12 ore, ma un avviso ancora in vigore no. Su Facebook escono quelle
# da SOGLIA_FB in su; i comunicati arrivati per posta («subito») escono tutti, comunque. Dal 27 ott 2026 Instagram
# pubblica le stesse notizie di Facebook, subito dopo (l'«Agente Social», instagram.da_facebook; lui: «instagram e
# facebook in sincronia», «sì 3 in su, fallo»): prima Instagram aveva la sua soglia, 4.
# Delle notizie dei paesi che non sono cronaca e valgono 3 ne esce al massimo una ogni PAESI_MINUTI (lui: «non vorrei
# invasioni di notizie solo di paesi»).
SOGLIA_FB = SOGLIA_IG = 3
PAESI_MINUTI = 60
GIORNI_AVVISI = 3
AVVISI_VECCHI = False   # vedi candidate()
# cosa è già uscito si legge dai post degli ultimi GIORNI_MEMORIA giorni, a pagine da 100 (fino al 26 ott 2026 solo gli
# ultimi 50 post, cioè un giorno nei giorni pieni: una notizia di due giorni prima aggiornata oggi usciva di nuovo,
# 5 doppioni tra il 25 e il 26 ott)
GIORNI_MEMORIA = 5
USCITE_FILE = "facebook-uscite.json"   # quello che c'è sulla Pagina, scritto a ogni giro per instagram.py (accanto a --stato)
PAGINE_MAX = 8


def tutti_i_post(percorso, token, campi, adesso, quando):
    """I post di una Pagina (o di un account Instagram) degli ultimi GIORNI_MEMORIA giorni, pagina per pagina.
    quando(post) dà l'ora del post."""
    out, dopo = [], None
    for _ in range(PAGINE_MAX):
        r = chiama("GET", percorso, token, {"fields": campi, "limit": 100, **({"after": dopo} if dopo else {})})
        dati = r.get("data") or []
        out += dati
        dopo = ((r.get("paging") or {}).get("cursors") or {}).get("after")
        if not dati or not dopo or not (r.get("paging") or {}).get("next") \
                or adesso - quando(dati[-1]) > dt.timedelta(days=GIORNI_MEMORIA):
            break
    return out
AREA_VASTA = re.compile(r"^(sannio|provincia|campania|linea|linee|valle)\b|provincia|,| e |/", re.I)
RIEPILOGO_DALLE = 20   # il riepilogo della giornata, su Facebook e su Instagram (dalle 20: voluto dal proprietario)
RIEPILOGO_PAUSA = 30   # minuti dall'ultimo post
TITOLO_RIEPILOGO = "Il Sannio oggi"
DALLE, ALLE = 6, 23   # dalle 6 fino al giro delle 22 compreso (ALLE è l'ora in cui si smette)
AGG = "🔴 Aggiornamento · "   # come su Telegram
AGG_USCITO = "\0aggiornamento"
# Meta che dice «troppe richieste» (al programma, alla Pagina, all'account): insistere allunga il blocco. Successo il
# 26 ott 2026 alle 15:17: 16 post arretrati insieme e Instagram fermato da Meta (instagram.py si ferma un'ora).
LIMITE_META = re.compile(r"\(codice (4|17|32|613|80001|80002|80004|80005|80006|80008|80014)\)")
# quanto del limite dell'ora di Meta abbiamo usato, in percentuale: Meta lo scrive in ogni risposta (x-app-usage per il
# programma, x-business-use-case-usage per la Pagina e l'account Instagram). Si stampa alla fine di ogni programma:
# il 27 ott 2026 «troppe richieste» due volte in una mattina, e senza questi numeri non si sapeva chi chiamasse di più.
USO_META = {}   # tra i titoli già usciti di una notizia: il suo «Aggiornamento» è già uscito


def fuso():
    try:
        from zoneinfo import ZoneInfo
        return ZoneInfo("Europe/Rome")
    except Exception:
        return dt.timezone(dt.timedelta(hours=1))


def quando(n, adesso):
    """L'ora di pubblicazione; con la sola data, come fa il sito: a metà tra mezzanotte e adesso, non oltre mezzogiorno."""
    p = str(n.get("pubblicato") or "")
    if re.match(r"^\d{4}-\d{2}-\d{2}$", p):
        mezzanotte = dt.datetime.fromisoformat(p + "T00:00:00").replace(tzinfo=fuso())
        return min(mezzanotte + dt.timedelta(hours=12), mezzanotte + max(adesso - mezzanotte, dt.timedelta(0)) / 2)
    try:
        t = dt.datetime.fromisoformat(p)
        return t if t.tzinfo else t.replace(tzinfo=fuso())
    except ValueError:
        return None


def importanza(n):
    """L'importanza da 1 a 5 (CLASSIFICA): quella scritta dall'agente; se manca, ricavata dal tipo di notizia."""
    v = n.get("importanza")
    if isinstance(v, int) and not isinstance(v, bool) and 1 <= v <= 5:
        return v
    if n.get("categoria") == "sport":
        return 5 if n.get("sport") == "calcio" and "benevento" in str(n.get("titolo") or "").lower() else 2
    if allerta_seria(n):
        return 5
    if n.get("categoria") in ("cronaca", "politica", "meteo") or n.get("rilevante"):
        return 4
    return 3


def in_citta(n):
    return str(n.get("luogo") or "").strip().lower().startswith("benevento")


def paese_minore(n):
    """Una notizia di un paese (non Benevento, non tutta la provincia) che non è cronaca e vale 3 o meno."""
    luogo = str(n.get("luogo") or "").strip()
    return (bool(luogo) and not in_citta(n) and not AREA_VASTA.search(luogo) and n.get("categoria") != "cronaca"
            and importanza(n) <= 3)


def in_vigore(n, adesso):
    return str(n.get("in_vigore_fino") or "") >= adesso.date().isoformat()


def rilievo(n, t, adesso):
    """Il punteggio della classifica dei social (CLASSIFICA)."""
    ore = max(0.0, (adesso - t).total_seconds() / 3600)
    fonti = n.get("fonti") if isinstance(n.get("fonti"), list) else [1]
    punti = importanza(n) * 20 + 5 * (n.get("stato") == "ufficiale") + 5 * in_citta(n) + 2 * min(max(len(fonti) - 1, 0), 5)
    return punti if in_vigore(n, adesso) else punti * 0.5 ** (ore / 12)


def allerta_seria(n):
    """La notizia di un'allerta arancione o rossa, l'unica che esce alle 23 su tutti i social (la gialla no)."""
    return (n.get("categoria") == "meteo" and bool(n.get("rilevante"))
            and re.search(r"\b(arancion[ei]|ross[ae])\b", n.get("titolo") or "", re.I) is not None)


def candidate(notizie, gia, adesso):
    out = []
    for n in notizie:
        t = quando(n, adesso)
        vecchia = adesso - t > dt.timedelta(hours=ORE_FINESTRA) if t else True
        # un avviso ancora in vigore resterebbe in classifica fino a GIORNI_AVVISI giorni, ma gia_pubblicate legge solo gli
        # ultimi 50 post (un giorno, nei giorni pieni): il 26 ott alle 16:08 è uscito di nuovo un avviso del 24. Spento
        # finché la lettura dei post non copre tutti quei giorni.
        if vecchia and t and in_vigore(n, adesso) and adesso - t <= dt.timedelta(days=GIORNI_AVVISI) and AVVISI_VECCHI:
            vecchia = False
        if not t or n.get("id") in gia or t > adesso or vecchia:
            continue
        if n.get("diretta_calcio"):   # l'articolo di fine partita: sui social è già uscito il «Finale» (gol.py)
            continue
        out.append((rilievo(n, t, adesso), n))
    return [n for _, n in sorted(out, key=lambda x: -x[0])]


def norma(t):
    return re.sub(r"[^0-9a-zà-ÿ]+", " ", str(t or "").lower()).strip()


def aggiornate(notizie, gia, adesso):
    """Le notizie con un «Aggiornamento» delle ultime ORE_FINESTRA ore che ne ha cambiato il titolo (il risultato dopo la
    presentazione della partita): escono ancora una volta, come «Aggiornamento» (scelta del proprietario, 24 ott 2026).
    I ritocchi che lasciano il titolo com'è restano solo su Telegram. Il titolo di prima lo segna archivia.py
    (aggiornamento.titolo_prima). gia: id → titoli già usciti; una notizia con un «Aggiornamento» già uscito non esce più,
    e una ancora da pubblicare come nuova esce come nuova, col titolo di adesso."""
    nuove = {n.get("id") for n in candidate(notizie, gia, adesso)}
    out = []
    for n in notizie:
        if n.get("diretta_calcio"):   # come in candidate()
            continue
        ag = (n.get("articolo") or {}).get("aggiornamento") or {}
        usciti = gia.get(n.get("id"), set())
        try:
            t = dt.datetime.fromisoformat(str(ag.get("quando")))
        except ValueError:
            continue
        t = t if t.tzinfo else t.replace(tzinfo=fuso())
        if (not ag.get("titolo_prima") or norma(ag["titolo_prima"]) == norma(n.get("titolo")) or n.get("id") in nuove
                or AGG_USCITO in usciti or norma(n.get("titolo")) in usciti
                or t > adesso or adesso - t > dt.timedelta(hours=ORE_FINESTRA)):
            continue
        out.append((n, t))
    return out


def coda(notizie, gia, adesso, soglia=SOGLIA_FB, recenti=()):
    """Le notizie nuove e gli aggiornamenti col titolo cambiato, in ordine di classifica (CLASSIFICA), solo quelli da
    soglia in su (i comunicati «subito» sempre): [(notizia, è un aggiornamento)]. Un aggiornamento conta dall'ora
    dell'aggiornamento, come in prima pagina. recenti: le notizie uscite nelle ultime PAESI_MINUTI (una di paese basta)."""
    out = [(rilievo(n, quando(n, adesso), adesso), n, False) for n in candidate(notizie, gia, adesso)]
    out += [(rilievo(n, t, adesso), n, True) for n, t in aggiornate(notizie, gia, adesso)]
    out = [x for x in out if importanza(x[1]) >= soglia or (x[1].get("subito") and not x[2])]
    if any(paese_minore(n) for n in recenti):
        out = [x for x in out if not paese_minore(x[1]) or (x[1].get("subito") and not x[2])]
    return [(n, agg) for _, n, agg in sorted(out, key=lambda x: -x[0])]


def recenti(notizie, uscite, adesso):
    """Le notizie uscite sui social nelle ultime PAESI_MINUTI (uscite: id → ora dell'ultimo post)."""
    return [n for n in notizie if n.get("id") in uscite and adesso - uscite[n["id"]] < dt.timedelta(minutes=PAESI_MINUTI)]


def messaggio(n, aggiornamento=False):
    if aggiornamento:
        return AGG + n["titolo"].strip() + "\n\n" + n["articolo"]["aggiornamento"]["testo"].strip()
    m = n["titolo"].strip() + ("\n\n" + n["sintesi"].strip() if n.get("sintesi") else "")
    if n.get("stato") == "una_fonte" and n.get("fonti"):
        m += f"\n\nPer ora lo riporta solo {n['fonti'][0].get('nome', '')}."
    return m


def testo_post(n, aggiornamento=False):
    """Il testo del post con la scheda: come messaggio(), con la nota sull'immagine fatta con l'IA quando la scheda ne ha
    una (come la didascalia di Instagram) e «Leggi tutto: <link>» in fondo (da lì gia_pubblicate() riconosce il post)."""
    m = messaggio(n, aggiornamento)
    # la foto fatta dall'IA: quella del tema o quella fatta apposta per la scena (foto_ia, strumenti/foto_ia.py)
    if not aggiornamento and (n.get("foto_ia") or (n.get("immagine") and n.get("categoria") != "cronaca")) \
            and not n.get("locandina") and not n.get("foto_inviate"):
        m += "\n\nImmagine illustrativa creata con l'intelligenza artificiale: non è una foto del fatto."
    return m + f"\n\nLeggi tutto: {SITO}/notizia/{n['id']}/"


def scheda(n):
    """L'immagine del post: la scheda di Instagram (img/ig/<id>.jpg, c'è per le notizie della prima pagina delle ultime
    48 ore) o, se manca, l'immagine di anteprima della pagina (img/n/<id>.png); None se nessuna delle due è online."""
    for u in (f"{SITO}/img/ig/{n['id']}.jpg", f"{SITO}/img/n/{n['id']}.png"):
        if online(u):
            return u
    return None


def chiama(metodo, percorso, token, dati=None):
    dati = dict(dati or {}, access_token=token)
    corpo = urllib.parse.urlencode(dati).encode()
    if metodo == "GET":
        req = urllib.request.Request(f"{GRAPH}/{percorso}?{corpo.decode()}")
    else:
        req = urllib.request.Request(f"{GRAPH}/{percorso}", data=corpo, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            nota_uso(r.headers)
            return json.load(r)
    except urllib.error.HTTPError as e:
        nota_uso(e.headers)
        # l'errore di Facebook dice cosa non va (chiave scaduta, permesso mancante…) e non contiene la chiave
        try:
            err = json.load(e).get("error", {})
            # il sottocodice e il titolo per l'utente dicono quale limite (27 ott 2026: il codice 4 da solo non bastava a
            # capire se era il limite delle chiamate o il blocco di Instagram contro lo spam); «(codice N)» resta così
            # perché LIMITE_META lo cerca
            # il messaggio per l'utente e il codice della richiesta (fbtrace_id) servono per segnalare il problema a Meta
            altro = (f" sottocodice {err['error_subcode']}" if err.get("error_subcode") else "") \
                + (f" «{err['error_user_title']}»" if err.get("error_user_title") else "") \
                + (f": «{err['error_user_msg'][:160]}»" if err.get("error_user_msg") else "") \
                + f" [{metodo} {re.sub(r'[0-9]{6,}', 'N', percorso.split('?')[0])}]" \
                + (f" traccia {err['fbtrace_id']}" if err.get("fbtrace_id") else "")
            raise RuntimeError(f"Facebook {e.code}: {err.get('message', '')} (codice {err.get('code')}){altro}") from None
        except ValueError:
            raise RuntimeError(f"Facebook {e.code}") from None


def nota_uso(intestazioni):
    """Ricorda in USO_META l'ultima percentuale del limite dell'ora che Meta scrive nella risposta (la più alta tra
    chiamate, tempo e processore)."""
    for nome, chi in (("x-app-usage", "programma"), ("x-business-use-case-usage", "pagina")):
        try:
            j = json.loads((intestazioni.get(nome) if intestazioni is not None else None) or "null")
        except ValueError:
            continue
        voci = [j] if chi == "programma" else [x for v in (j or {}).values() if isinstance(v, list) for x in v]
        p = [max(int(x.get(k) or 0) for k in ("call_count", "total_cputime", "total_time"))
             for x in voci if isinstance(x, dict)]
        if p:
            USO_META[chi] = max(p)


def uso_meta():
    """«programma 35%, pagina 4%», o «Meta non l'ha detto»."""
    return ", ".join(f"{k} {v}%" for k, v in sorted(USO_META.items())) or "Meta non l'ha detto"


def riprova(fare, cosa, lettura=False):
    """Tre tentativi (dopo 5 e 30 secondi): un errore di passaggio non deve far perdere un post. Una lettura si
    riprova sempre; un invio solo se Facebook ha risposto di no (errore HTTP) o la connessione non è nemmeno partita:
    se la risposta si è persa per strada (tempo scaduto, o Facebook che chiude la connessione senza rispondere) il post
    potrebbe essere uscito, e riprovare alla cieca farebbe un doppione. In quel caso si finisce con errore e alla volta
    dopo si ricontrolla sulla Pagina. Il 26 ott 2026 alle 15:41 «Remote end closed connection without response» era
    trattato come un no: la foto era uscita, è stata rimandata dopo 5 secondi e la notizia è uscita due volte di fila."""
    persa = (TimeoutError, socket.timeout, ConnectionError, http.client.HTTPException)   # dopo l'invio, risposta persa
    for attesa in (5, 30, None):
        try:
            return fare()
        except Exception as e:
            incerto = isinstance(e, persa) or (isinstance(e, urllib.error.URLError) and isinstance(e.reason, persa))
            # Meta che frena (LIMITE_META) non si riprova mai: insistere allunga il blocco. E un invio frenato è incerto:
            # il 27 ott 2026 Instagram ha risposto «azione bloccata» (codice 4, sottocodice 2207051) a media_publish tre
            # volte su tre, e il post era uscito ogni volta: riprovarlo dopo 5 secondi avrebbe fatto un doppione.
            frenato = bool(LIMITE_META.search(str(e)))
            incerto = incerto or (frenato and not lettura)
            if attesa is None or frenato or (incerto and not lettura):
                raise RuntimeError(f"{cosa}: {e}" + (" (forse è uscito: si ricontrolla dopo)" if incerto else "")) from None
            print(f"  {cosa}: {e} — riprovo tra {attesa} s")
            time.sleep(attesa)


def online(url):
    try:
        with urllib.request.urlopen(urllib.request.Request(url, method="HEAD"), timeout=20) as r:
            return r.status == 200
    except Exception:
        return False


def foto_con_testo(token, foto, testo, link, col_link=True):
    """Un post con la foto (se è online) e il testo; se Facebook dice di no alla foto, un post col testo e il link
    (con col_link=False il solo testo, che il link lo ha già scritto dentro: le notizie, dal 26 ott 2026). Se la foto
    è uscita non si fa mai anche l'altro post: il testo, se manca, si aggiunge al post della foto."""
    if foto and online(foto):
        r = None
        try:
            r = riprova(lambda: chiama("POST", "me/photos", token, {"url": foto, "caption": testo}), "Facebook (foto)")
        except RuntimeError as e:
            if "forse è uscito" in str(e):
                raise
            print(f"  Facebook: la foto non è passata ({e}): pubblico il post " + ("col link" if col_link else "col solo testo"))
        if r:
            pid = r.get("post_id") or f"{r.get('page_id', '')}_{r.get('id')}"
            letto = riprova(lambda: chiama("GET", pid, token, {"fields": "message"}), "Facebook (rilettura)", True)
            if not (letto.get("message") or "").strip():   # il testo deve esserci: se manca, lo si scrive nel post
                riprova(lambda: chiama("POST", pid, token, {"message": testo}), "Facebook (testo del post)")
            return
    dati = {"message": testo, "link": link} if col_link else {"message": testo}
    riprova(lambda: chiama("POST", "me/feed", token, dati), "Facebook")


def testo_riepilogo(giorno, notizie):
    m = f"{TITOLO_RIEPILOGO}, {giorno}: le notizie più importanti della giornata.\n\n"
    m += "\n\n".join(f"{i}. {n['titolo'].strip()}\n{SITO}/notizia/{n['id']}/" for i, n in enumerate(notizie, 1))
    return m + f"\n\nTutte le notizie di Benevento e del Sannio: {SITO}/"


def titoli_usciti(ids, nid, testo):
    """Segna in ids (id → titoli) il titolo di un post, la prima riga del testo; e se era un «Aggiornamento»."""
    riga = (testo or "").split("\n")[0]
    s = ids.setdefault(nid, set())
    if riga.startswith(AGG):
        s.add(AGG_USCITO)
        riga = riga[len(AGG):]
    s.add(norma(riga))


def pubblica(token, n, aggiornamento=False):
    """Il post della notizia, con la foto come su Instagram (dal 26 ott 2026): le foto inviate col comunicato
    (foto_inviate()), se no la scheda (scheda()), e il testo con «Leggi tutto». Un aggiornamento esce con la scheda di
    adesso, che ha già il titolo nuovo."""
    link = f"{SITO}/notizia/{n['id']}/"
    if n.get("foto_inviate") and not aggiornamento:
        foto_inviate(token, n, link)
        return
    foto = scheda(n)
    if not foto:
        print(f"  Facebook: la scheda di {n['id']} non è online: pubblico il solo testo")
    foto_con_testo(token, foto, testo_post(n, aggiornamento), link, col_link=False)


def foto_inviate(token, n, link):
    """Una notizia con le foto mandate col comunicato (voluto dal proprietario il 25 ott 2026: «se mandano foto usale»,
    «anche più foto se ci sono»): un post con le foto vere e il link nel testo. Con una foto è un post foto
    (foto_con_testo); con più foto si caricano senza pubblicarle e poi escono tutte insieme in un solo post."""
    testo = messaggio(n) + f"\n\n{'Le foto inviate' if len(n['foto_inviate']) > 1 else 'Foto inviata'} da " \
        f"{n.get('foto_da') or 'chi ha mandato il comunicato'}.\n\nLeggi tutto: {link}"
    foto = [f"{SITO}/{r}" for r in n["foto_inviate"][:10] if re.match(r"^img/locandine/[a-z0-9-]+\.jpg$", str(r))]
    foto = [u for u in foto if online(u)]
    if len(foto) > 1:
        try:
            ids = [riprova(lambda u=u: chiama("POST", "me/photos", token, {"url": u, "published": "false"}),
                           "Facebook (foto da unire)", True)["id"] for u in foto]
        except RuntimeError as e:   # caricate senza pubblicarle: niente doppioni a riprovare con la prima
            print(f"  Facebook: le foto non sono passate ({e}): pubblico la prima")
            ids = []
        if ids:
            dati = {"message": testo}
            dati.update({f"attached_media[{k}]": json.dumps({"media_fbid": i}) for k, i in enumerate(ids)})
            riprova(lambda: chiama("POST", "me/feed", token, dati), "Facebook (post con le foto)")
            return
    foto_con_testo(token, foto[0] if foto else None, testo, link, col_link=False)


def gia_pubblicate(token, adesso):
    """Le notizie già sulla Pagina (id → titoli usciti), quante notizie oggi (il riepilogo e le chiusure non contano),
    l'ora dell'ultima, se il riepilogo di oggi c'è già e l'ora dell'ultimo post di ogni notizia (id → ora)."""
    ora_post = lambda p: dt.datetime.strptime(p["created_time"], "%Y-%m-%dT%H:%M:%S%z").astimezone(fuso())
    post = tutti_i_post("me/posts", token, "created_time,message,attachments{unshimmed_url,url}", adesso, ora_post)
    ids, oggi, ultimo, riepilogo, uscite = {}, 0, None, False, {}
    for p in post:
        t = ora_post(p)
        testo = p.get("message") or ""
        riepilogo |= t.date() == adesso.date() and testo.startswith(TITOLO_RIEPILOGO)
        link = [a.get("unshimmed_url") or a.get("url") or "" for a in (p.get("attachments") or {}).get("data", [])]
        if testo.startswith(AGG):   # un aggiornamento uscito con l'immagine (pubblica()) ha il link nel testo
            link.append(testo)
        link += re.findall(r"Leggi tutto: (\S+)", testo)   # anche un post con le foto inviate (foto_inviate())
        for u in link:
            u = urllib.parse.parse_qs(urllib.parse.urlparse(u).query).get("u", [u])[0]  # link «l.facebook.com/l.php?u=»
            m = re.search(r"notiziebenevento\.it/notizia/([a-z0-9-]+)", u)
            if m:
                titoli_usciti(ids, m.group(1), testo)
                uscite[m.group(1)] = max(uscite.get(m.group(1), t), t)
                oggi += t.date() == adesso.date()
                ultimo = max(ultimo, t) if ultimo else t
                break
    return ids, oggi, ultimo, riepilogo, uscite


def fai_riepilogo(token, a, notizie, adesso, ultimo):
    """Il riepilogo della giornata, se è il momento: True se ha finito il lavoro di questa volta (pubblicato o da
    aspettare), False se oggi non c'è (poche notizie) e si va avanti con le notizie normali."""
    from instagram import riepilogo_pronto
    r = riepilogo_pronto(a.sito, notizie, adesso)
    if not r:
        print("Facebook: niente riepilogo oggi (poche notizie)")
        return False
    if ultimo and adesso - ultimo < dt.timedelta(minutes=RIEPILOGO_PAUSA):
        print(f"Facebook: l'ultimo post è delle {ultimo:%H:%M}, il riepilogo al prossimo giro")
        return True
    stato = {}
    if a.stato:
        try:
            with open(a.stato, encoding="utf-8") as f:
                stato = json.load(f)
        except (OSError, ValueError):
            pass
    if stato.get("riepilogo_tentato") == adesso.date().isoformat():
        # tentato prima e non visto sulla Pagina: forse è uscito senza testo. Meglio niente che due riepiloghi
        raise RuntimeError("il riepilogo di oggi è già stato tentato ma sulla Pagina non si vede: controllare a mano")
    if a.stato:
        os.makedirs(os.path.dirname(a.stato) or ".", exist_ok=True)
        with open(a.stato, "w", encoding="utf-8") as f:
            json.dump({"riepilogo_tentato": adesso.date().isoformat()}, f)
    giorno, scelte, immagini = r
    foto_con_testo(token, immagini[0], testo_riepilogo(giorno, scelte), f"{SITO}/")
    print(f"Facebook: pubblicato il riepilogo della giornata ({len(scelte)} notizie)")
    return True


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sito", default=os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    ap.add_argument("--prova", action="store_true", help="dice cosa pubblicherebbe, senza toccare Facebook")
    ap.add_argument("--stato", help="il file dove si segna il riepilogo tentato (lo conserva GitHub)")
    a = ap.parse_args()
    adesso = dt.datetime.now(fuso())
    with open(os.path.join(a.sito, "notizie.json"), encoding="utf-8") as f:
        notizie = json.load(f).get("notizie", [])

    if a.prova:
        for n, agg in coda(notizie, {}, adesso)[:40]:
            foto = "le foto inviate" if n.get("foto_inviate") and not agg else scheda(n) or "nessuna immagine: solo testo"
            print(f"- {n['id']}{' (aggiornamento)' if agg else ''} · importanza {importanza(n)}"
                  f"{' (scritta)' if n.get('importanza') else ' (ricavata)'} · punti {rilievo(n, quando(n, adesso), adesso):.0f}"
                  f"{' · paese' if paese_minore(n) else ''}\n  foto: {foto}\n  "
                  + testo_post(n, agg).replace("\n", "\n  ") + "\n")
        return

    token = os.environ.get("FB_PAGE_TOKEN", "").strip()
    if not token:
        print("Facebook: nessuna chiave (segreto FB_PAGE_TOKEN), non pubblico niente")
        return
    sera = adesso.hour == 23   # alle 23 solo le allerte arancioni o rosse: chi ha figli a scuola guarda la sera
    if not DALLE <= adesso.hour < ALLE and not sera:
        print(f"Facebook: sono le {adesso:%H:%M}, si pubblica dalle {DALLE} fino al giro delle {ALLE - 1}")
        return
    # la chiave deve essere quella della Pagina Notizie Benevento: mai pubblicare altrove (profilo, altre pagine)
    chi = chiama("GET", "me", token, {"fields": "name"}).get("name")
    if chi != PAGINA:
        raise RuntimeError(f"la chiave non è della Pagina «{PAGINA}»: non pubblico niente")
    gia, oggi, ultimo, riepilogo, uscite = gia_pubblicate(token, adesso)
    lettura = {"letto": adesso.isoformat(timespec="seconds"), "uscite": {k: v.isoformat() for k, v in uscite.items()},
               "aggiornamenti": sorted(k for k, v in gia.items() if AGG_USCITO in v)}

    def segna(n, agg=False):
        """Quello che c'è sulla Pagina, per Instagram (instagram.da_facebook): lo legge dal file invece di richiedere
        a Meta tutti i post una seconda volta (27 ott 2026: la doppia lettura ha fatto scattare «troppe richieste»)."""
        if n is not None:
            lettura["uscite"][n["id"]] = dt.datetime.now(fuso()).isoformat()
            if agg:
                lettura["aggiornamenti"] = sorted(set(lettura["aggiornamenti"]) | {n["id"]})
        if a.stato:
            os.makedirs(os.path.dirname(a.stato) or ".", exist_ok=True)
            with open(os.path.join(os.path.dirname(a.stato), USCITE_FILE), "w", encoding="utf-8") as f:
                json.dump(lettura, f)
    segna(None)
    # un comunicato ufficiale arrivato per posta (giro lampo: «subito» in notizie.json, strumenti/comunicati.py) esce
    # adesso: niente pausa, niente tetto del giorno, anche dopo il riepilogo (lui, 24 ott 2026: «pubblicazione istantanea»)
    urgenti = [] if sera else [n for n in candidate(notizie, gia, adesso) if n.get("subito")]
    for n in urgenti[:3]:
        pubblica(token, n)
        segna(n)
        oggi += 1
        print(f"Facebook: pubblicata subito {n['id']} (comunicato, {oggi} oggi)")
    if urgenti:
        return
    if not sera and not riepilogo and adesso.hour >= RIEPILOGO_DALLE and fai_riepilogo(token, a, notizie, adesso, ultimo):
        return
    subito = int(os.environ.get("FB_SUBITO") or 0)   # solo quando lo chiede il proprietario, dal pulsante di GitHub
    if not subito and ultimo and adesso - ultimo < dt.timedelta(minutes=PAUSA_MINUTI):
        print(f"Facebook: l'ultimo post è delle {ultimo:%H:%M}, aspetto")
        return
    lista = coda(notizie, gia, adesso, SOGLIA_FB, recenti(notizie, uscite, adesso))
    if sera:
        lista = [(n, False) for n in candidate(notizie, gia, adesso) if allerta_seria(n)]
        if not lista:
            print("Facebook: sono le 23, a quest'ora si pubblicano solo le allerte arancioni o rosse")
            return
    if not lista:
        print("Facebook: nessuna notizia nuova da pubblicare")
        return
    for n, agg in lista[:max(subito, 1)]:
        pubblica(token, n, agg)
        segna(n, agg)
        oggi += 1
        cosa = "pubblicato l'aggiornamento di" if agg else "pubblicata"
        print(f"Facebook: {cosa} {n['id']} ({oggi} oggi)")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print("AVVISO Facebook:", e, file=sys.stderr)
        sys.exit(1)
    finally:
        if USO_META:
            print(f"  Facebook: limite dell'ora di Meta usato: {uso_meta()}")
