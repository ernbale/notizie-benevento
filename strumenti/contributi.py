#!/usr/bin/env python3
"""I contributi e i bandi per Benevento e il Sannio → contributi.json (pagina /contributi/).

Voluti dal proprietario il 28 ott 2026: «tutto quello che riesci a trovare che vada bene per BN e provincia… statali,
europei, per tutti, click day… pagina fatta estremamente bene, estremamente facile da consultare». Il nome è
«Contributi» e non «Bandi» perché i bandi di concorso avranno una sezione loro (lui: «la teniamo in cantiere»).

Fonti:
- il Catalogo degli incentivi del Ministero delle Imprese e del Made in Italy (incentivi.gov.it, dati aperti IODL 2.0):
  si tengono quelli validi in Campania e vivi (scadenza futura, o senza scadenza ma aggiornati nell'ultimo anno; il
  catalogo ha schede «senza scadenza» ferme dal 2023 e chiuse da tempo), tolti quelli di altre province (Comuni fuori dal
  Sannio, altre Camere di Commercio, Ischia…). Testi, importi e date sono quelli della scheda ufficiale: niente si
  inventa. Il sito del Ministero non risponde ai server di GitHub (prova del 28 ott 2026, come per i carburanti): il
  catalogo lo scarica il Pi di casa (--scarica --manda, dal cron) e lo passa alla pubblicazione (pubblica.yml, campo
  «contributi»), solo quando è cambiato;
- contributi_locali.json: quelli che il catalogo non ha (Stato per le famiglie, Regione, Camera di Commercio, Invitalia,
  fondazioni, Unione europea, Comuni, click day), scritti dall'agente dei contributi che gira una volta al giorno
  (CONTRIBUTI.md; lui, 28 ott 2026: «devi creare un agente che una volta al giorno scova i contributi, sovvenzioni»);
  qui si controllano e quelli fatti male si scartano;
- contributi_esclusi.json: le schede del catalogo che l'agente ha trovato chiuse o sbagliate sul sito ufficiale (il
  catalogo a volte le dà aperte per mesi): non si mostrano.
I contributi dei Comuni li prende la pagina anche da notizie.json, ma solo le notizie con "contributo" (AGENTE.md): il
28 ott 2026 la pagina prendeva tutti gli avvisi «Domande e bandi» e c'erano loculi, lampade votive e scrutatori (lui:
«se li leggi aiuti sovvenzioni contributi non c'è nulla, anzi il contrario, quasi tutti il Comune chiede soldi»).
Quelli scaduti da meno di GIORNI_SCADUTI restano con "scaduto": true, perché la loro pagina non sparisca di colpo da
Google; poi escono.

Uso:  python3 strumenti/contributi.py --scarica --uscita contributi-catalogo.json [--manda ~/nb-fonti/github.conf]  (Pi)
      python3 strumenti/contributi.py --pubblica [--catalogo contributi-catalogo.json] [--prima contributi-prima.json]
                                      [--uscita contributi.json]                                      (pubblicazione)
"""
import argparse
import base64
import datetime as dt
import gzip
import hashlib
import json
import os
import re
import sys
import unicodedata
import urllib.parse
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from meteo import COMUNI_BN   # noqa: E402

SITO = "https://notiziebenevento.it"
REPO = "ernbale/notizie-benevento"
UA = "notiziebenevento.it (contributi; redazione@notiziebenevento.it)"
CATALOGO = "https://www.incentivi.gov.it/solr/coredrupal/select"
CAMPI = ("zs_nid,zs_title,zs_url,zs_field_link,zs_field_subject_grant,zs_field_open_date,zs_field_close_date,"
         "zs_field_close_date_descriptor,ds_last_update,zm_field_regions_value,zm_field_subject_type_value,"
         "zm_field_activity_sector_value,"
         "zm_field_scopes_value,zm_field_support_form_value,zm_field_support_grant_type_min_max,zs_field_budget_allocation,"
         "tum_X3b_it_body_ft")
GIORNI_SCADUTI = 60        # i scaduti restano (segnati) per non togliere di colpo le pagine a Google
GIORNI_SENZA_SCADENZA = 365   # senza scadenza: vivo solo se la scheda è stata aggiornata nell'ultimo anno
MINIMO_CATALOGO = 20       # meno di così dal catalogo vuol dire che qualcosa non va: si tiene quello di prima

# «Chi sei?»: le chiavi dei filtri della pagina (CHI_CONTR in index.html e pagine.py) dai tipi di beneficiario del
# catalogo e, per le imprese, dai settori (lui, 28 ott 2026: «i filtri… non solo famiglie ma imprese, commercianti,
# artigiani ecc.»; come il vecchio Cacciatore di Contributi, dal campo «settore di attività» del catalogo)
CHI = {"cittadino": "Famiglie e cittadini", "giovani": "Giovani e studenti", "commercio": "Commercianti",
       "artigiano": "Artigiani", "agricoltura": "Agricoltori e agroalimentare", "turismo": "Turismo, bar e ristoranti",
       "impresa": "Tutte le imprese", "nuova": "Chi apre un'attività", "professionista": "Professionisti e partite IVA",
       "associazione": "Associazioni e terzo settore", "ente": "Comuni, scuole ed enti"}
SETTORI = {"Commercio": "commercio", "Artigianato": "artigiano", "Agricoltura, silvicoltura e pesca": "agricoltura",
           "Agroalimentare": "agricoltura", "Turismo": "turismo", "Ristorazione": "turismo", "Alberghiero": "turismo"}
# «Da chi?» (lui, 28 ott 2026: «fondi europei, statali, Confindustria, Confartigianato, Camera di Commercio, Regione,
# Comuni e altro che neanche so»): chi mette o gestisce i soldi; i fondi europei gestiti da Stato o Regione hanno anche
# «europa»
DA = {"europa": "Unione europea", "stato": "Stato", "regione": "Regione Campania", "camera": "Camera di Commercio",
      "comune": "Comuni", "provincia": "Provincia di Benevento", "categoria": "Associazioni di categoria",
      "altri": "Fondazioni e altri"}
DA_ENTE = [(r"Commissione europea|Unione europea|EISMEA|EACEA", "europa"), (r"Camera di Commercio|CCIAA", "camera"),
           (r"Regione Campania|Campania|ADISURC", "regione"), (r"^Comun[ei]\b|Ambito", "comune"),
           (r"Provincia di Benevento", "provincia"),
           (r"Confidi|Confindustria|Confartigianato|\bCNA\b|Confcommercio|Coldiretti|Confagricoltura|Confesercenti", "categoria"),
           (r"Minister|Presidenza del Consiglio|Dipartimento|Agenzia (delle Entrate|per |ICE|Nazionale)|INPS|INAIL|Invitalia|"
            r"SIMEST|GSE|Gestore dei Servizi|Credito Sportivo|CNR|Consiglio Nazionale|ISMEA|Cassa depositi|ENEA|"
            r"Mediocredito|Consap|ARERA", "stato")]
FONDI_UE = re.compile(r"\bFESR\b|\bFSE\b|FSE\+|\bPNRR\b|Next ?Generation|\bPN [A-Z]|\bPR [A-Z]|FEASR|FEAMPA|Interreg|"
                      r"fondi europei|Horizon|Erasmus|\b21[-/]27\b|2021[-/ ]2027", re.I)   # «Unione europea» no: «mano d'opera dell'Unione europea»
# «Che aiuto?»: la forma dell'aiuto
AIUTO = {"fondo": "Soldi a fondo perduto", "bonus": "Bonus, assegni e buoni", "prestito": "Prestito agevolato",
         "garanzia": "Garanzia sul prestito", "fiscale": "Sconto fiscale"}
FORME_AIUTO = {"Contributo/Fondo perduto": "fondo", "Agevolazione fiscale": "fiscale", "Prestito/Anticipo rimborsabile": "prestito",
               "Interventi a garanzia": "garanzia", "Riduzione dei contributi di previdenza sociale": "fiscale"}
CHI_CATALOGO = [(r"^Impresa da costituire", "nuova"), (r"^(Impresa|Consorzio|Rete d'impresa|Istituto finanziario)", "impresa"),
                (r"^Professionista", "professionista"), (r"Associazioni|Cooperative|Terzo settore", "associazione"),
                (r"^(Ente Pubblico|Università)", "ente"), (r"^(Cittadino|Persona fisica)", "cittadino")]
# «Per cosa?»: le chiavi dei temi (TEMI in index.html) dagli ambiti del catalogo
TEMI = {"figli": "Figli e famiglia", "scuola": "Scuola e studio", "casa": "Casa, affitto e bollette",
        "lavoro": "Lavoro e assunzioni", "investire": "Investire", "aprire": "Aprire un'attività", "digitale": "Digitale", "energia": "Energia e ambiente",
        "innovazione": "Innovazione e ricerca", "export": "Export", "credito": "Credito e liquidità",
        "giovani-donne": "Giovani e donne", "crisi": "Imprese in difficoltà", "sociale": "Sociale",
        "cultura": "Cultura e spettacolo"}
TEMI_CATALOGO = {"Sostegno investimenti": "investire", "Start up/Sviluppo d'impresa": "aprire", "Digitalizzazione": "digitale",
                 "Transizione ecologica": "energia", "Innovazione e ricerca": "innovazione",
                 "Internazionalizzazione": "export", "Sostegno liquidità": "credito",
                 "Imprenditoria giovanile": "giovani-donne", "Imprenditoria femminile": "giovani-donne",
                 "Crisi d'impresa": "crisi", "Inclusione sociale": "sociale",
                 "Formazione (lavoro, occupazione, riqualificazione professionale dei lavoratori)": "lavoro"}
CULTURA = re.compile(r"\bteatr|cinema|spettacol|editoria|musica|librar|\bmuse|culturale|audiovisiv|film\b", re.I)
FORME = {"Contributo/Fondo perduto": "Contributo a fondo perduto", "Agevolazione fiscale": "Credito d'imposta o sconto fiscale",
         "Prestito/Anticipo rimborsabile": "Prestito agevolato", "Capitale di rischio": "Investimento nel capitale",
         "Interventi a garanzia": "Garanzia sul prestito",
         "Riduzione dei contributi di previdenza sociale": "Sconto sui contributi previdenziali"}
DOVE = ("sannio", "campania", "sud", "italia", "europa")
ALTRE_REGIONI = re.compile(r"Ischia|Lucan|Valle D.Aosta|Calabria|Sicilia|Sardegna|Puglia|Basilicata|Lazio|Molise|Abruzzo|"
                           r"Toscana|Lombardia|Veneto|Piemonte|Liguria|Marche|Umbria|Friuli|Trentino|Emilia|Alto Adige", re.I)
ALTRA_PROVINCIA = re.compile(r"provincia di (Avellino|Salerno|Napoli|Caserta)\b|\b(Avellino|Salerno|Napoli|Caserta)\b", re.I)
SANNIO_ENTE = re.compile(r"Irpinia Sannio|Provincia di Benevento|\bGAL\b|Gruppo di Azione Locale", re.I)
# schede del catalogo segnate «tutte le regioni» ma che nel testo valgono solo per altre (es. il Fondo
# deindustrializzazione 2026: «territori industriali del Lazio e delle Marche»)
REGIONI_NEL_TESTO = re.compile(r"\b(Lazio|Marche|Lombardia|Piemonte|Veneto|Toscana|Emilia[- ]Romagna|Liguria|Friuli|Trentino|"
                               r"Alto Adige|Umbria|Abruzzo|Molise|Puglia|Basilicata|Calabria|Sicilia|Sardegna|Valle d.Aosta)\b")
ANCHE_NOI = re.compile(r"Campania|Mezzogiorno|\bSud\b|Meridion|tutt[eo] (le regioni|il territorio)|territorio nazionale|"
                       r"Benevento|Sannio|\bZES\b", re.I)
SEZIONI = {"cos'è": "cose", "cos’è": "cose", "a chi si rivolge": "a_chi", "cosa prevede": "cosa_prevede"}
LIMITI = {"cose": 420, "a_chi": 600, "cosa_prevede": 1100}
GIORNO = re.compile(r"^\d{4}-\d{2}-\d{2}$")
QUANDO = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}$")
COMUNI = {c.lower(): c for c in COMUNI_BN}


def oggi_roma():
    from zoneinfo import ZoneInfo
    return dt.datetime.now(ZoneInfo("Europe/Rome")).date()


def slug(s):
    s = unicodedata.normalize("NFKD", str(s)).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", "-", s).strip("-")


def uno(x, k):
    v = x.get(k)
    return v[0] if isinstance(v, list) and len(v) == 1 else v


def pulisci(t):
    return re.sub(r"\s+", " ", str(t or "").replace("\xa0", " ")).strip()


def taglia(t, n):
    """Al massimo n caratteri, finendo con una frase intera se si può."""
    if len(t) <= n:
        return t
    pezzo = t[:n]
    fine = max(pezzo.rfind(". "), pezzo.rfind("; "))
    return (pezzo[:fine + 1] if fine > n * 0.5 else pezzo.rsplit(" ", 1)[0] + "…").strip()


def euro(n):
    """22500 → «22.500 €», 30000000 → «30 milioni di €»."""
    if n >= 1_000_000 and n % 100_000 == 0:
        m = n / 1_000_000
        return f"{m:g} milion{'e' if m == 1 else 'i'} di €".replace(".", ",")
    return f"{n:,.0f} €".replace(",", ".")


def numeri(v):
    out = []
    for x in v if isinstance(v, list) else [v]:
        try:
            n = float(str(x).replace(",", "."))
        except (TypeError, ValueError):
            continue
        if n > 0:
            out.append(int(n))
    return out


def quanto(x):
    mm = sorted(numeri(x.get("zm_field_support_grant_type_min_max") or []))
    if len(mm) >= 2 and mm[0] < mm[-1]:
        return f"da {euro(mm[0])} a {euro(mm[-1])}"
    if mm:
        return f"fino a {euro(mm[-1])}"
    budget = numeri(uno(x, "zs_field_budget_allocation"))
    return f"stanziati in tutto {euro(budget[0])}" if budget else ""


def testi(x):
    out, chiave = {}, None
    for p in x.get("tum_X3b_it_body_ft") or []:
        p = pulisci(p)
        if p.lower() in SEZIONI:
            chiave = SEZIONI[p.lower()]
            continue
        if chiave and p:
            out[chiave] = (out.get(chiave, "") + " " + p).strip()
    return {k: taglia(v, LIMITI[k]) for k, v in out.items()}


def titolo_pulito(t, ente):
    t = pulisci(t)
    t = re.sub(r"^(Bando\s+)?(CCIAA [^-–]+|Regione Campania|Comune di [^-–]+)\s*[-–]\s*", "", t)
    return t[:1].upper() + t[1:]


def dal_catalogo(docs, oggi):
    """Le schede del catalogo buone per il Sannio, nella forma di contributi.json."""
    o = oggi.isoformat()
    da_scaduti = (oggi - dt.timedelta(days=GIORNI_SCADUTI)).isoformat()
    da_aggiornati = (oggi - dt.timedelta(days=GIORNI_SENZA_SCADENZA)).isoformat()
    out = []
    for x in docs:
        regioni = x.get("zm_field_regions_value") or []
        if "Campania" not in regioni:
            continue
        chiude = str(uno(x, "zs_field_close_date") or "")[:10]
        aggiornato = str(uno(x, "ds_last_update") or "")[:10]
        if (chiude and chiude < da_scaduti) or (not chiude and aggiornato < da_aggiornati):
            continue
        ente = pulisci(uno(x, "zs_field_subject_grant"))
        titolo = pulisci(uno(x, "zs_title"))
        m = re.match(r"^Comune di (.+)$", ente)
        if m and m.group(1).strip().lower() not in COMUNI:
            continue
        if re.search(r"Camera di Commercio|CCIAA", ente, re.I) and not re.search(r"Irpinia Sannio", ente, re.I):
            continue
        if ALTRE_REGIONI.search(ente) or (ALTRA_PROVINCIA.search(titolo) and not re.search(r"Benevento|Sannio", titolo, re.I)):
            continue
        tipi = x.get("zm_field_subject_type_value") or []
        chi = []
        for t in tipi:
            for rx, k in CHI_CATALOGO:
                if re.search(rx, t) and k not in chi:
                    chi.append(k)
                    break
        temi = []
        for s in x.get("zm_field_scopes_value") or []:
            k = TEMI_CATALOGO.get(s)
            if k and k not in temi:
                temi.append(k)
        if any(k in chi for k in ("impresa", "nuova")):   # i settori valgono per le imprese (anche quelle da aprire)
            for st in x.get("zm_field_activity_sector_value") or []:
                k = SETTORI.get(st)
                if k and k not in chi:
                    chi.append(k)
        if "nuova" in chi and "aprire" not in temi:
            temi.append("aprire")
        if any("prevalenza" in t or "Giovanile" in t or "Femminile" in t for t in tipi) and "giovani-donne" not in temi:
            temi.append("giovani-donne")
        if (CULTURA.search(titolo) or "Cultura" in ente) and "cultura" not in temi:
            temi.append("cultura")
        dove = ("sannio" if (SANNIO_ENTE.search(ente) or m) else "campania" if len(regioni) == 1
                else "sud" if len(regioni) <= 10 else "italia")   # poche regioni: di solito il Mezzogiorno
        nid = str(uno(x, "zs_nid") or "")
        link = str(uno(x, "zs_field_link") or "")
        if not nid or not link.startswith("http"):
            continue
        tit = titolo_pulito(titolo, ente)
        apre = str(uno(x, "zs_field_open_date") or "")[:10]
        forme = x.get("zm_field_support_form_value") or []
        voce = {"id": f"{slug(tit)[:70].rstrip('-')}-{nid}", "titolo": tit, "ente": ente, "dove": dove, "chi": chi,
                "temi": temi, "forma": " o ".join(FORME.get(f, f) for f in forme),
                "aiuto": list(dict.fromkeys(FORME_AIUTO[f] for f in forme if f in FORME_AIUTO)),
                "quanto": quanto(x), "apertura": apre if GIORNO.match(apre) else None,
                "scadenza": chiude if GIORNO.match(chiude) else None,
                "scadenza_testo": pulisci(uno(x, "zs_field_close_date_descriptor")) or None,
                "link": link, "scheda": "https://www.incentivi.gov.it" + str(uno(x, "zs_url") or ""),
                "fonte": "catalogo", "aggiornato_fonte": aggiornato or None}
        voce.update(testi(x))
        testo = " ".join(filter(None, [tit, voce.get("cose"), voce.get("a_chi"), voce.get("cosa_prevede")]))
        if REGIONI_NEL_TESTO.search(testo) and not ANCHE_NOI.search(testo):
            continue
        voce["da"] = da_di(ente, testo)
        out.append(voce)
    return out


def da_di(ente, testo):
    """«Da chi?»: chi dà i soldi, dal nome dell'ente; più «europa» se sono fondi europei (FESR, PNRR, FSE+…)."""
    out = next(([k] for rx, k in DA_ENTE if re.search(rx, ente or "", re.I)), ["altri"])
    if "europa" not in out and FONDI_UE.search(testo or ""):
        out.append("europa")
    return out


def scarica():
    q = urllib.parse.urlencode({"q": "index_id:incentivi", "wt": "json", "rows": "20000", "fl": CAMPI})
    with urllib.request.urlopen(urllib.request.Request(f"{CATALOGO}?{q}", headers={"User-Agent": UA}), timeout=120) as r:
        return json.load(r)["response"]["docs"]


def controlla_locale(v, err):
    """Un contributo scritto dall'agente (contributi_locali.json): campi giusti, date giuste, link ufficiale."""
    w = v.get("id", "?")
    for k in ("id", "titolo", "ente", "dove", "link", "cose", "controllato"):
        if not v.get(k):
            err.append(f"{w}: manca {k}")
    if not re.match(r"^[a-z0-9]+(-[a-z0-9]+)*$", str(v.get("id", ""))):
        err.append(f"{w}: id non valido")
    if v.get("dove") not in DOVE:
        err.append(f"{w}: dove deve essere uno di {', '.join(DOVE)}")
    for k in ("chi", "da", "aiuto"):
        if not v.get(k):
            err.append(f"{w}: manca {k}")
    if v.get("come") is not None and not str(v["come"]).strip():
        err.append(f"{w}: «come» vuoto")
    for k, ammessi in (("chi", CHI), ("temi", TEMI), ("da", DA), ("aiuto", AIUTO)):
        if not isinstance(v.get(k, []), list) or any(x not in ammessi for x in v.get(k, [])):
            err.append(f"{w}: {k} ammette solo {', '.join(ammessi)}")
    for k in ("apertura", "scadenza", "controllato"):
        if v.get(k) and not GIORNO.match(str(v[k])):
            err.append(f"{w}: {k} deve essere AAAA-MM-GG")
    if v.get("click_day") and not QUANDO.match(str(v["click_day"])):
        err.append(f"{w}: click_day deve essere AAAA-MM-GGTHH:MM")
    if not str(v.get("link", "")).startswith("https://"):
        err.append(f"{w}: il link deve essere quello ufficiale, https://")


def unisci(catalogo, locali, prima, oggi, esclusi=()):
    """contributi.json: catalogo + locali, con la data in cui ognuno è comparso e i scaduti segnati; senza le schede del
    catalogo trovate chiuse o sbagliate (contributi_esclusi.json)."""
    o = oggi.isoformat()
    esclusi = set(esclusi)
    catalogo = [x for x in catalogo if x.get("id") not in esclusi]
    da_scaduti = (oggi - dt.timedelta(days=GIORNI_SCADUTI)).isoformat()
    aggiunto = {v["id"]: v.get("aggiunto") for v in (prima or {}).get("contributi", []) if v.get("id")}
    tutti, visti = [], set()
    for v in [dict(x) for x in locali] + [dict(x) for x in catalogo]:
        if v["id"] in visti or (v.get("scadenza") and v["scadenza"] < da_scaduti):
            continue
        visti.add(v["id"])
        v.setdefault("fonte", "locale")
        v["aggiunto"] = aggiunto.get(v["id"]) or o
        v["scaduto"] = bool(v.get("scadenza") and v["scadenza"] < o)
        tutti.append(v)
    tutti.sort(key=lambda v: (v["scaduto"], v.get("scadenza") or "9999", v["titolo"]))
    return tutti


def impronta(voci):
    return hashlib.sha1(json.dumps(voci, ensure_ascii=False, sort_keys=True).encode()).hexdigest()[:12]


def manda(catalogo, chiave):
    """Fa partire la pubblicazione su GitHub col catalogo (compresso) se sul sito ce n'è uno diverso. Non più di una
    volta l'ora per lo stesso catalogo: se la pubblicazione non va, si riprova al giro dopo (come carburanti.py)."""
    imp = impronta(catalogo)
    try:
        with urllib.request.urlopen(urllib.request.Request(f"{SITO}/contributi.json", headers={"User-Agent": UA}),
                                    timeout=30) as r:
            sul_sito = (json.load(r).get("catalogo") or {}).get("impronta", "")
    except Exception:
        sul_sito = ""
    if sul_sito == imp:
        print(f"contributi: sul sito c'è già questo catalogo ({imp})")
        return
    stato_p = os.path.join(os.path.dirname(os.path.abspath(chiave)), "contributi-mandati.json")
    try:
        with open(stato_p, encoding="utf-8") as f:
            stato = json.load(f)
    except (OSError, ValueError):
        stato = {}
    if stato.get("impronta") == imp and \
            dt.datetime.now(dt.timezone.utc) - dt.datetime.fromisoformat(stato["quando"]) < dt.timedelta(minutes=60):
        print(f"contributi: catalogo {imp} già mandato alle {stato['quando'][11:16]} UTC, aspetto")
        return
    with open(chiave, encoding="utf-8") as f:
        token = json.load(f)["token"].strip()
    pacco = base64.b64encode(gzip.compress(json.dumps(catalogo, ensure_ascii=False, separators=(",", ":")).encode(), 9)).decode()
    if len(pacco) > 60000:   # GitHub accetta al massimo 65.535 caratteri in tutti i campi insieme
        raise SystemExit(f"contributi: il catalogo compresso è di {len(pacco)} caratteri, troppo per GitHub")
    req = urllib.request.Request(f"https://api.github.com/repos/{REPO}/actions/workflows/pubblica.yml/dispatches",
                                 method="POST", data=json.dumps({"ref": "main", "inputs": {"contributi": pacco}}).encode(),
                                 headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json",
                                          "X-GitHub-Api-Version": "2022-11-28", "User-Agent": "nb-contributi"})
    with urllib.request.urlopen(req, timeout=60):
        pass
    with open(stato_p, "w", encoding="utf-8") as f:
        json.dump({"impronta": imp, "quando": dt.datetime.now(dt.timezone.utc).isoformat()}, f)
    print(f"contributi: mandato alla pubblicazione il catalogo {imp} ({len(catalogo)} contributi, {len(pacco)} caratteri)")


def leggi(p):
    try:
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError, TypeError):
        return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--scarica", action="store_true", help="scarica il catalogo del Ministero (solo dall'Italia: il Pi)")
    ap.add_argument("--manda", help="(con --scarica) github.conf: manda il catalogo alla pubblicazione se è cambiato")
    ap.add_argument("--pubblica", action="store_true", help="unisce catalogo e contributi locali in contributi.json")
    ap.add_argument("--catalogo", help="(con --pubblica) il catalogo arrivato dal Pi; se manca, quello già pubblicato")
    ap.add_argument("--prima", help="(con --pubblica) contributi.json già pubblicato")
    ap.add_argument("--locali", default=os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                                     "contributi_locali.json"))
    ap.add_argument("--esclusi", default=os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                                      "contributi_esclusi.json"))
    ap.add_argument("--uscita", default="contributi.json")
    a = ap.parse_args()
    oggi = oggi_roma()
    if a.scarica:
        catalogo = dal_catalogo(scarica(), oggi)
        if len(catalogo) < MINIMO_CATALOGO:
            raise SystemExit(f"contributi: solo {len(catalogo)} contributi dal catalogo, non scrivo niente")
        with open(a.uscita, "w", encoding="utf-8") as f:
            json.dump(catalogo, f, ensure_ascii=False, indent=1)
        print(f"contributi: {len(catalogo)} dal catalogo per il Sannio ({sum(not v.get('scadenza') or v['scadenza'] >= oggi.isoformat() for v in catalogo)} aperti)")
        if a.manda:
            manda(catalogo, a.manda)
        return
    if not a.pubblica:
        ap.error("serve --scarica o --pubblica")
    prima = leggi(a.prima) if a.prima else None
    nuovo = leggi(a.catalogo) if a.catalogo else None
    if isinstance(nuovo, list) and len(nuovo) >= MINIMO_CATALOGO:
        catalogo, info = nuovo, {"impronta": impronta(nuovo), "arrivato": dt.datetime.now(dt.timezone.utc).isoformat(timespec="minutes")}
    else:
        catalogo = [v for v in (prima or {}).get("contributi", []) if v.get("fonte") == "catalogo"]
        info = (prima or {}).get("catalogo") or {}
    err = []
    locali = []
    for v in ((leggi(a.locali) or {}).get("contributi") or []):
        e = []
        controlla_locale(v, e)
        if e:
            err += e
        else:
            locali.append(v)
    for e in err:
        print("::warning::contributi_locali.json:", e)
    esclusi = [x.get("id") for x in ((leggi(a.esclusi) or {}).get("esclusi") or []) if isinstance(x, dict) and x.get("id")]
    for v in catalogo:   # il catalogo arrivato prima di «da» e «aiuto» (o già pubblicato): si completano qui
        if "da" not in v:
            v["da"] = da_di(v.get("ente"), " ".join(filter(None, [v.get("titolo"), v.get("cose"), v.get("cosa_prevede")])))
        if "aiuto" not in v:
            v["aiuto"] = list(dict.fromkeys(k for f, k in ((FORME.get(g, g), k) for g, k in FORME_AIUTO.items())
                                            if f in (v.get("forma") or "")))
    tutti = unisci(catalogo, locali, prima, oggi, esclusi)
    from zoneinfo import ZoneInfo
    da = dt.datetime.now(ZoneInfo("Europe/Rome")).isoformat(timespec="minutes")
    with open(a.uscita, "w", encoding="utf-8") as f:
        json.dump({"aggiornato": da, "catalogo": info, "esclusi": len(esclusi), "contributi": tutti}, f, ensure_ascii=False,
                  separators=(",", ":"))
    aperti = sum(not v["scaduto"] for v in tutti)
    print(f"contributi: {aperti} aperti ({len(catalogo)} dal catalogo, {len(locali)} locali)")


if __name__ == "__main__":
    main()
