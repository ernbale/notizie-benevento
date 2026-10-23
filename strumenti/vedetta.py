#!/usr/bin/env python3
"""La vedetta delle chiusure: sul Pi di casa, giorno e notte, cerca le chiusure decise dai Comuni (scuole, parchi,
cimiteri…) e appena ne trova una fa partire il giro Chiusure, che la controlla e la pubblica sul sito e sui social.

Voluta dal proprietario il 23 ott 2026: «dobbiamo essere veloci, controllare i Comuni più spesso e senza limite di
orario… una strategia senza intoppi a prova di bomba». Il cron la lancia ogni 5 minuti: nei giorni di allerta (gialla
o più per oggi o domani, da meteo.json) o quando un giornale parla di scuole chiuse lavora sempre, negli altri giorni
salta un giro su due (ogni 10 minuti). Leggere tutti i Comuni prende una ventina di secondi.

Guarda:
- i siti dei Comuni (le pagine con l'elenco degli avvisi di fonti_casa.py): apre gli avvisi mai visti e, per quelli
  che sono ordinanze o avvisi, anche i PDF allegati (pdftotext);
- l'albo pretorio di Benevento (le ordinanze);
- i titoli dei giornali del Sannio (i feed di giornali.py): servono anche per i Comuni che mettono l'ordinanza solo su
  Facebook, che non si legge.
Una «pista» è un avviso o un articolo che parla di una chiusura. Le piste nuove vanno in chiusure.json dell'archivio
privato notizie-benevento-fonti, pubblicato subito (col lucchetto di fonti_casa.py, che pubblica lo stesso archivio),
e poi la vedetta fa partire il giro Chiusure con la chiave della routine (file routine.conf, 600, lo scrive
--imposta-avvio; la chiave non si stampa mai). Se l'avvio non va, riprova al giro dopo; se una pista non risulta vista
dal giro Chiusure dopo PISTA_MAX minuti (chiusure.json del sito, «viste»), lo rilancia, al massimo RILANCI volte (poi
è la sentinella a dare l'allarme). La prima volta che vede un Comune o un giornale prende solo nota di quello che c'è:
le cose vecchie non sono piste.

Uso sul Pi:  python3 ~/nb-fonti/sentinella/vedetta.py                 (dal cron, ogni 5 minuti)
             python3 ~/nb-fonti/sentinella/vedetta.py --prova         (cerca e stampa, senza scrivere né avviare)
             python3 ~/nb-fonti/sentinella/vedetta.py --imposta-avvio (una volta: chiede indirizzo e chiave della routine)
             python3 ~/nb-fonti/sentinella/vedetta.py --prova-avvio   (prova antincendio: il giro Chiusure parte in prova)
"""
import argparse
import datetime as dt
import fcntl
import getpass
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor

QUI = os.path.dirname(os.path.abspath(__file__))
CARTELLA = os.environ.get("NB_FONTI_CARTELLA") or os.path.expanduser("~/nb-fonti")
sys.path.insert(0, QUI)
sys.path.insert(1, CARTELLA)   # sul Pi fonti_casa.py sta lì; sul Mac è accanto a questo file
import fonti_casa as F   # noqa: E402
import giornali as G     # noqa: E402
from meteo import COMUNI_BN   # noqa: E402

STATO = os.path.join(CARTELLA, "vedetta.json")
CONF = os.path.join(CARTELLA, "routine.conf")
PISTE = os.path.join(F.ARCHIVIO, "chiusure.json")
LUCCHETTO = "/tmp/nb_fonti.lock"   # lo stesso del cron di fonti_casa.py: l'archivio lo pubblica uno alla volta
SITO = "https://notiziebenevento.it"
REPO = "ernbale/notizie-benevento"
GIORNI_PISTE = 3      # le piste restano nell'archivio per tanti giorni
PISTA_MAX = 25        # minuti: una pista non vista dal giro Chiusure dopo tanto si rilancia il giro
RILANCI = 3
NUOVE_MAX = 40        # avvisi dei Comuni aperti al massimo per giro
ALLERTA_ORE = 18      # un giornale che parla di scuole chiuse mette la vedetta al passo di 5 minuti per tante ore

# una chiusura: luoghi (scuole, parchi, cimiteri…) chiusi o attività didattiche sospese; non le strade
LUOGHI = r"(?:scuol|plessi|istitut\w*\s+(?:scolastic|comprensiv)|edifici\w*\s+scolastic|asil|nid[oi]\b|parc(?:o|hi)\b|vill[ae]\s+comunal|" \
         r"giardin\w*\s+pubblic|cimiter|impiant\w*\s+sportiv|palestr|palazzett|mercat)"
CHIUSURA = re.compile(
    r"chius\w*\s+(?:temporane\w+\s+)?(?:(?:di|del|dei|degli|della|delle|il|lo|la|le|i|gli|tutt[ei])\s+){0,3}" + LUOGHI
    + r"|" + LUOGHI + r"\w*\s+(?:\w+\s+){0,3}?chius"
    + r"|sospension\w*\s+(?:(?:delle|della|dell')\s*)?(?:attivit[àa]\s+)?(?:didattic|scolastic|lezion)"
    + r"|attivit[àa]\s+didattic\w+\s+sospes|lezioni\s+sospes|didattica\s+a\s+distanza|niente\s+scuola\b", re.I)


def adesso_roma():
    return dt.datetime.now(F.fuso())


def leggi(p, vuoto):
    try:
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return vuoto


def scrivi(p, dati):
    with open(p + ".tmp", "w", encoding="utf-8") as f:
        json.dump(dati, f, ensure_ascii=False, indent=1)
    os.replace(p + ".tmp", p)


def parla_di_chiusura(testo):
    m = CHIUSURA.search(testo or "")
    return m.group(0) if m else None


def comune_in(testo):
    """Il Comune del Sannio nominato per primo nel testo (il nome più lungo, se uno sta dentro l'altro)."""
    trovati, testo = [], (testo or "").replace("’", "'")
    for c in COMUNI_BN:
        m = re.search(r"(?<!\w)" + re.escape(c).replace(r"\ ", r"\s+") + r"(?!\w)", testo or "", re.I)
        if m:
            trovati.append((m.start(), -len(c), c))
    return min(trovati)[2] if trovati else None


def pista(comune, fonte, titolo, link, testo, adesso, pdf=None):
    return {"id": hashlib.sha1(link.encode()).hexdigest()[:12], "comune": comune, "fonte": fonte,
            "titolo": (titolo or "")[:300], "link": link, "trovata": adesso.isoformat(timespec="seconds"),
            "testo": (testo or "")[:6000], **({"pdf": pdf} if pdf else {})}


def testo_pdf(url):
    with tempfile.NamedTemporaryFile(suffix=".pdf") as f:
        subprocess.run(["curl", "-sfL", "-m", "60", "-A", F.UA, "-o", f.name, url], check=True, capture_output=True)
        p = subprocess.run(["pdftotext", "-l", "4", "-layout", f.name, "-"], capture_output=True, timeout=60)
        return p.stdout.decode("utf-8", "replace")


def contesto(testo, frase, quanto=1500):
    """Il pezzo di testo intorno alla frase della chiusura (l'agente legge quello per primo)."""
    i = (testo or "").lower().find((frase or "").lower())
    return testo if i < 0 else testo[max(0, i - quanto // 3):i + quanto]


# ---------------------------------------------------------------- le tre fonti

def dai_comuni(stato, adesso):
    visti = stato["visti"].setdefault("comuni", {})

    def elenco(c):
        trovate = {}
        for p in c[1]:
            try:
                trovate.update(F.voci_elenco(F.scarica(p), p))
            except Exception:
                pass
        return c[0], trovate

    with ThreadPoolExecutor(8) as ex:
        elenchi = list(ex.map(elenco, [c for c in F.COMUNI if c[1]]))
    letti = sum(1 for _, t in elenchi if t)
    da_aprire = []
    for nome, trovate in elenchi:
        if not trovate:
            continue
        if nome not in visti:   # prima volta: solo nota di quello che c'è
            visti[nome] = list(trovate)
            continue
        gia = set(visti[nome])
        da_aprire += [(nome, u, t) for u, t in trovate.items() if u not in gia]

    def apri(x):
        nome, u, t = x
        try:
            b = F.scarica(u)
        except Exception:
            return x, None   # si riprova al giro dopo
        i = b.find("<h1")
        j = b.find("<footer", i if i >= 0 else 0)
        corpo = F.testo(b[i if i >= 0 else 0:j if j > 0 else len(b)])
        titolo = (corpo.split("\n")[0] if i >= 0 and corpo else "") or t or u   # come fonti_casa.dettaglio_comune
        frase = parla_di_chiusura(titolo + "\n" + corpo)
        pdf, testo = [], corpo
        if not frase and re.search(r"ordinanz|avvis|comunicat|allert|maltempo|meteo|scuol", titolo + " " + u, re.I):
            for href in re.findall(r'href="([^"]+\.pdf[^"]*)"', b, re.I)[:3]:
                url_pdf = F.assoluto(u, href)
                try:
                    tp = testo_pdf(url_pdf)
                except Exception:
                    continue
                f = parla_di_chiusura(tp)
                if f:
                    frase, testo = f, corpo + "\n\n--- PDF " + url_pdf + "\n" + contesto(tp, f, 4000)
                    pdf.append(url_pdf)
                    break
        if not frase:
            return x, False
        return x, pista(nome, "sito del Comune", titolo, u, contesto(testo, frase, 6000) if len(testo) > 6000 else testo,
                        adesso, pdf)

    trovate = []
    with ThreadPoolExecutor(6) as ex:
        for (nome, u, _), esito in ex.map(apri, da_aprire[:NUOVE_MAX]):
            if esito is None:
                continue
            visti[nome].append(u)
            visti[nome] = visti[nome][-400:]
            if esito:
                trovate.append(esito)
    return trovate, f"Comuni {letti}/{len(F.COMUNI)}"


def dall_albo(stato, adesso):
    visti = stato["visti"].setdefault("albo", [])
    prima_volta = not visti
    voci = F.albo_bn(set())
    trovate = []
    for v in voci:
        if v["link"] in visti:
            continue
        visti.append(v["link"])
        frase = parla_di_chiusura(v["titolo"])
        if frase and not prima_volta:
            trovate.append(pista("Benevento", "albo pretorio del Comune di Benevento", v["titolo"], v["link"],
                                 f"{v['titolo']}\n(ordinanza {v.get('numero_atto', '')} del {v.get('data_atto', '')}, "
                                 f"mittente {v.get('mittente', '')}: il testo è nell'atto allegato)", adesso))
    stato["visti"]["albo"] = visti[-400:]
    return trovate, f"albo {len(voci)}"


def dai_giornali(stato, adesso):
    visti = stato["visti"].setdefault("giornali", [])
    prima_volta = not visti
    trovate, letti, scuole_chiuse = [], 0, False

    def leggi_feed(t):
        nome, _, tipo, feed, _ = t
        try:
            voci = G.voci_rss(G.scarica(feed))
        except Exception:
            return nome, None
        if tipo == "wp-benevento":
            voci = [v for v in voci if "/benevento/" in v["url"]]
        return nome, voci

    with ThreadPoolExecutor(8) as ex:
        feed = list(ex.map(leggi_feed, [t for t in G.TESTATE if t[2] in ("wp", "rss", "wp-benevento")]))
    for nome, voci in feed:
        if voci is None:
            continue
        letti += 1
        for v in voci:
            if v["url"] in visti or (v["data"] and adesso - v["data"] > dt.timedelta(hours=36)):
                continue
            visti.append(v["url"])
            frase = parla_di_chiusura(v["titolo"])
            if not frase:
                continue
            scuole_chiuse = True
            if not prima_volta:
                trovate.append(pista(comune_in(v["titolo"]), f"giornale: {nome}", v["titolo"], v["url"],
                                     f"Titolo dell'articolo di {nome}: {v['titolo']}", adesso))
    stato["visti"]["giornali"] = visti[-1500:]
    if scuole_chiuse:
        stato["allerta_fino"] = (adesso + dt.timedelta(hours=ALLERTA_ORE)).isoformat(timespec="minutes")
    return trovate, f"giornali {letti}"


# ---------------------------------------------------------------- allerta, pubblicazione, avvio

def in_allerta(stato, adesso):
    if stato.get("allerta_fino") and dt.datetime.fromisoformat(stato["allerta_fino"]) > adesso:
        return "un giornale parla di scuole chiuse"
    try:
        req = urllib.request.Request(f"{SITO}/meteo.json?vedetta={int(time.time())}", headers={"User-Agent": F.UA})
        with urllib.request.urlopen(req, timeout=30) as r:
            m = json.load(r)
    except Exception:
        return "meteo.json non si legge (nel dubbio, al passo di 5 minuti)"
    livelli = ["verde", "gialla", "arancione", "rossa"]
    for g in (adesso.date(), adesso.date() + dt.timedelta(days=1)):
        x = ((m.get("allerte") or {}).get("giorni") or {}).get(g.isoformat()) or {}
        ls = [z.get("livello") for z in (x.get("zone") or {}).values()] or [w.get("livello") for w in x.get("meteoalarm") or []]
        if any(l in livelli[1:] for l in ls):
            return f"allerta {max(ls, key=lambda l: livelli.index(l) if l in livelli else 0)} per il {g:%d/%m}"
    return None


def pubblica_archivio(adesso):
    """Pubblica l'archivio delle fonti col lucchetto di fonti_casa.py (aspetta fino a 3 minuti che finisca)."""
    with open(LUCCHETTO, "a") as l:
        fine = time.time() + 180
        while True:
            try:
                fcntl.flock(l, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.time() > fine:
                    raise RuntimeError("fonti_casa.py tiene l'archivio da più di 3 minuti")
                time.sleep(3)
        try:
            F.pubblica(adesso)
        finally:
            fcntl.flock(l, fcntl.LOCK_UN)


def avvia(testo):
    """Fa partire il giro Chiusure (la routine) con la sua chiave. Restituisce l'indirizzo della sessione."""
    conf = leggi(CONF, None)
    if not conf or not conf.get("url") or not conf.get("token"):
        raise RuntimeError(f"manca la chiave della routine ({CONF}: vedetta.py --imposta-avvio)")
    req = urllib.request.Request(conf["url"], data=json.dumps({"text": testo[:60000]}).encode(), method="POST", headers={
        "Authorization": f"Bearer {conf['token']}", "anthropic-version": "2023-06-01",
        "anthropic-beta": "experimental-cc-routine-2026-04-01", "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            d = json.load(r)
    except urllib.error.HTTPError as e:   # il messaggio dell'errore, mai la chiave
        try:
            msg = (json.load(e).get("error") or {}).get("message", "")
        except ValueError:
            msg = ""
        raise RuntimeError(f"avvio rifiutato ({e.code}) {msg}".strip()) from None
    return d.get("claude_code_session_url") or d.get("type") or "avviato"


def viste_sul_sito():
    """Le piste che il giro Chiusure ha già visto (chiusure.json del sito su GitHub, «viste»)."""
    sys.path.insert(0, QUI)
    from sentinella import GitHub, leggi_chiave
    gh = GitHub(leggi_chiave(os.path.join(CARTELLA, "github.conf")))
    return set(json.loads(gh.chiama("GET", f"repos/{REPO}/contents/chiusure.json?ref=main", grezzo=True)).get("viste") or [])


def imposta_avvio():
    print("Dalla pagina della routine «Notizie Benevento – chiusure» su claude.ai: l'indirizzo dell'avvio (…/fire)")
    url = input("Indirizzo: ").strip()
    if not re.match(r"^https://api\.anthropic\.com/v1/claude_code/routines/trig_\w+/fire$", url):
        sys.exit("L'indirizzo deve essere https://api.anthropic.com/v1/claude_code/routines/trig_…/fire: niente salvato.")
    token = getpass.getpass("Chiave della routine (non si vede mentre la incolli): ").strip()
    if not token.startswith("sk-ant-"):
        sys.exit("La chiave della routine comincia con sk-ant-: niente salvato.")
    vecchio = os.umask(0o077)
    try:
        scrivi(CONF, {"url": url, "token": token})
    finally:
        os.umask(vecchio)
    os.chmod(CONF, 0o600)
    print(f"✓ salvata in {CONF}. Per provarla: python3 {os.path.abspath(__file__)} --prova-avvio")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--prova", action="store_true", help="cerca e stampa, senza scrivere né avviare")
    ap.add_argument("--sempre", action="store_true", help="lavora anche nel giro che salterebbe")
    ap.add_argument("--imposta-avvio", action="store_true")
    ap.add_argument("--prova-avvio", action="store_true")
    a = ap.parse_args()
    if a.imposta_avvio:
        return imposta_avvio()
    adesso = adesso_roma()
    ora = f"{adesso:%d/%m %H:%M}"
    if a.prova_avvio:
        print(f"{ora} prova antincendio: {avvia('PROVA ANTINCENDIO dalla vedetta del Pi: nessuna pista vera. Fai il giro in modalità prova, come dice il prompt.')}")
        return
    stato = leggi(STATO, {})
    stato.setdefault("visti", {})
    allerta = in_allerta(stato, adesso)
    if not allerta and adesso.minute % 10 >= 5 and not (a.prova or a.sempre):
        return   # niente allerta: ogni 10 minuti basta

    nuove, esiti = [], []
    for fonte in (dai_comuni, dall_albo, dai_giornali):
        try:
            p, e = fonte(stato, adesso)
            nuove += p
            esiti.append(e)
        except Exception as e:
            esiti.append(f"{fonte.__name__}: ERRORE {type(e).__name__}: {e}")
    archivio = leggi(PISTE, {})
    limite = (adesso - dt.timedelta(days=GIORNI_PISTE)).isoformat()
    piste = [p for p in archivio.get("piste") or [] if p.get("trovata", "") >= limite]
    gia = {p["id"] for p in piste}
    nuove = [p for p in {p["id"]: p for p in nuove}.values() if p["id"] not in gia]
    piste += nuove
    archivio = {"controllato": adesso.isoformat(timespec="minutes"), "esito": " · ".join(esiti),
                "allerta": allerta, "piste": piste}
    riga = f"{ora} {' · '.join(esiti)}" + (f" · {allerta}" if allerta else "")
    if a.prova:
        print(riga)
        for p in nuove:
            print(f"  PISTA {p['comune'] or '?'} · {p['fonte']} · {p['titolo'][:100]}\n        {p['link']}")
        return

    scrivi(PISTE, archivio)   # anche senza piste: «controllato» dice all'agente che la vedetta lavora
    if nuove:
        riga += f" · {len(nuove)} piste nuove ({', '.join(sorted({p['comune'] or '?' for p in nuove}))})"
        try:
            pubblica_archivio(adesso)
        except Exception as e:
            riga += f" · ERRORE nel pubblicare l'archivio: {e}"
        stato.setdefault("da_avviare", [])
        stato["da_avviare"] += [p["id"] for p in nuove]

    # le piste già avviate ma non ancora viste dal giro Chiusure: si rilancia (dopo PISTA_MAX minuti, poche volte)
    avviate = stato.setdefault("avviate", {})
    avviate = stato["avviate"] = {i: v for i, v in avviate.items() if i in {p["id"] for p in piste}}
    vecchie = [i for i, v in avviate.items() if not v.get("vista") and v.get("volte", 0) < RILANCI
               and adesso - dt.datetime.fromisoformat(v["ultima"]) > dt.timedelta(minutes=PISTA_MAX)]
    if vecchie:
        try:
            viste = viste_sul_sito()
            for i in vecchie:
                if i in viste:
                    avviate[i]["vista"] = True
                else:
                    stato.setdefault("da_avviare", []).append(i)
        except Exception as e:
            riga += f" · non leggo le piste viste dal sito ({e})"
    da = sorted(set(stato.get("da_avviare") or []))
    if da:
        per_id = {p["id"]: p for p in piste}
        testo = ("Piste nuove della vedetta del Pi: " + "; ".join(
            f"{i} ({(per_id.get(i) or {}).get('comune') or '?'}: {(per_id.get(i) or {}).get('titolo', '')[:120]})" for i in da)
                 + ". Sono in chiusure.json dell'archivio notizie-benevento-fonti: segui il prompt.")
        try:
            sessione = avvia(testo)
            for i in da:
                v = avviate.setdefault(i, {"volte": 0})
                v["volte"], v["ultima"] = v.get("volte", 0) + 1, adesso.isoformat(timespec="minutes")
            stato["da_avviare"] = []
            riga += f" · giro Chiusure avviato ({len(da)} piste): {sessione}"
        except Exception as e:
            riga += f" · AVVIO NON RIUSCITO, riprovo al giro dopo: {e}"
    stato["ultimo_giro"] = adesso.isoformat(timespec="minutes")
    scrivi(STATO, stato)
    print(riga, flush=True)


if __name__ == "__main__":
    try:
        main()
    except Exception as e:   # nel log una riga, non un traceback
        print(f"{dt.datetime.now():%d/%m %H:%M} ERRORE: {type(e).__name__}: {e}")
        sys.exit(1)
