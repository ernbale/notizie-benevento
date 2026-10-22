#!/usr/bin/env python3
"""I numeri per la pagina privata delle statistiche → statistiche/dati.json, cifrato (lo esegue GitHub ogni ora).

- Visite: Cloudflare Web Analytics (senza cookie: conta visite e pagine viste, non le persone), ultimi 30 giorni.
- Il sito: notizie pubblicate, sezioni, zone, giornali e fonti citati (da notizie.json e dall'archivio).
- Google: Search Console (account di servizio con permesso «Limitata», chiave nel segreto GSC_CHIAVE), ultimi 28 giorni.
- Dietro le quinte: il diario cifrato dell'agente (diario/AAAA-MM-GG.json, scritto da archivia.py --giro), decifrato
  qui con la chiave privata del segreto DIARIO_CHIAVE: giro per giro fonti, notizie nuove, aggiornate e scartate.
- Facebook: la Pagina con la chiave FB_PAGE_TOKEN (la stessa che pubblica i post): follower, post, reazioni, commenti,
  condivisioni; persone raggiunte e visualizzazioni solo se la chiave ha anche il permesso read_insights. Facebook dà
  solo i follower di adesso: quelli dei giorni prima si riprendono dal dati.json già pubblicato.

Il file è cifrato con la parola d'ordine (AES-GCM, chiave da PBKDF2-SHA256): chi trova l'indirizzo vede solo
numeri illeggibili; la pagina statistiche/index.html lo apre nel browser con la stessa parola.
Niente numeri nei log di GitHub (il repository è pubblico): si stampano solo gli esiti.

Uso:  CLOUDFLARE_API_TOKEN=… STATISTICHE_PAROLA=… FB_PAGE_TOKEN=… python3 strumenti/statistiche.py [--sito .]
      python3 strumenti/statistiche.py --in-chiaro prova.json     (prova: scrive i dati senza cifrarli)
"""
import argparse
import base64
import collections
import datetime as dt
import glob
import hashlib
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request

CF_ACCOUNT = "d76a7e4eebbfb46bb9fbd03910507063"   # l'account Cloudflare (non è un segreto: sta negli indirizzi)
HOST = "notiziebenevento.it"
GIORNI = 30
ITERAZIONI = 600000
SALE = hashlib.sha256(b"notiziebenevento.it/statistiche").digest()[:16]  # fisso: la pagina può ricordare la chiave
NOMI_CAT = {"strade": "Strade", "cronaca": "Cronaca", "politica": "Politica", "sport": "Sport", "eventi": "Eventi", "meteo": "Allerte",
            "altro": "Altro"}
NOMI_ZONA = {"benevento": "Benevento città", "telesina": "Valle Telesina", "caudina": "Valle Caudina",
             "fortore": "Fortore e Tammaro", "provincia": "Altri comuni"}
PROVENIENZA = [  # (parte del dominio di provenienza, nome da mostrare)
    ("google.", "Google"), ("bing.", "Bing"), ("duckduckgo.", "DuckDuckGo"), ("yahoo.", "Yahoo"),
    ("facebook.", "Facebook"), ("fb.", "Facebook"), ("instagram.", "Instagram"), ("t.co", "X (Twitter)"),
    ("twitter.", "X (Twitter)"), ("x.com", "X (Twitter)"), ("t.me", "Telegram"), ("telegram.", "Telegram"),
    ("whatsapp.", "WhatsApp"), ("chatgpt.", "ChatGPT"), ("openai.", "ChatGPT"), ("perplexity.", "Perplexity"),
    ("news.google", "Google News"),
]


def fuso():
    try:
        from zoneinfo import ZoneInfo
        return ZoneInfo("Europe/Rome")
    except Exception:
        return dt.timezone(dt.timedelta(hours=1))


def leggi(path, predefinito=None):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return predefinito


# ---------- visite (Cloudflare Web Analytics) ----------
def cloudflare(token, inizio, fine):
    filtro = f'filter: {{datetime_geq: $start, datetime_lt: $end, requestHost: "{HOST}", bot: 0}}'
    def gruppo(nome, limite, ordine, dim):
        return (f"{nome}: rumPageloadEventsAdaptiveGroups(limit: {limite}, {filtro}, orderBy: [{ordine}]) "
                f"{{ count sum {{ visits }} dimensions {{ {dim} }} }}")
    q = ("query ($account: String!, $start: Time!, $end: Time!) { viewer { accounts(filter: {accountTag: $account}) { "
         + " ".join([gruppo("ore", 1000, "datetimeHour_ASC", "datetimeHour"),
                     gruppo("pagine", 100, "count_DESC", "requestPath"),
                     gruppo("da", 100, "sum_visits_DESC", "refererHost"),
                     gruppo("dispositivi", 10, "sum_visits_DESC", "deviceType"),
                     gruppo("paesi", 15, "sum_visits_DESC", "countryName"),
                     gruppo("browser", 10, "sum_visits_DESC", "userAgentBrowser"),
                     gruppo("da_paese", 300, "sum_visits_DESC", "refererHost countryName")])
         + " } } }")
    corpo = json.dumps({"query": q, "variables": {"account": CF_ACCOUNT, "start": inizio.isoformat(),
                                                  "end": fine.isoformat()}}).encode()
    req = urllib.request.Request("https://api.cloudflare.com/client/v4/graphql", data=corpo, method="POST",
                                 headers={"Authorization": "Bearer " + token, "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=60) as r:
        j = json.load(r)
    if j.get("errors"):
        raise RuntimeError("; ".join(str(x.get("message")) for x in j["errors"]))
    return j["data"]["viewer"]["accounts"][0]


def chiave_cloudflare(testo):
    """La chiave anche se nel segreto è stato incollato qualcosa in più (un'altra riga, il comando di prova di
    Cloudflare «curl … Bearer <chiave>»): le chiavi di Cloudflare sono una parola sola di 40 caratteri."""
    m = re.findall(r"[A-Za-z0-9_-]{35,}", testo or "")
    return m[0] if m else ""


def da_dove(host):
    h = (host or "").lower()
    if not h:
        return "Diretto, WhatsApp o app"
    if h.endswith(HOST):
        return None   # da un'altra pagina del sito: non è una provenienza
    for pezzo, nome in PROVENIENZA:
        if pezzo in h:
            return nome
    return h.removeprefix("www.")


def titoli_pagine(sito):
    """Percorso → titolo: le notizie (prima pagina e archivio), le sezioni, le zone."""
    t = {"/": "Prima pagina", "/meteo.html": "Meteo", "/index.html": "Prima pagina"}
    fonti = [os.path.join(sito, "notizie.json")] + glob.glob(os.path.join(sito, "archivio", "[0-9]*-[0-9]*.json"))
    for f in fonti:
        d = leggi(f, {}) or {}
        for n in d.get("notizie", []):
            if n.get("id"):
                t[f"/notizia/{n['id']}/"] = n.get("titolo") or n["id"]
        for a in d.get("approfondimenti", []):
            if a.get("id"):
                t[f"/approfondimento/{a['id']}/"] = a.get("titolo") or a["id"]
    for k, v in NOMI_CAT.items():
        t[f"/sezione/{'allerte' if k == 'meteo' else k}/"] = "Sezione " + v
    for k, v in {"benevento": "Benevento città", "valle-telesina": "Valle Telesina", "valle-caudina": "Valle Caudina",
                 "fortore": "Fortore e Tammaro", "altri-comuni": "Altri comuni"}.items():
        t[f"/zona/{k}/"] = "Zona " + v
    return t


def visite(sito, token, adesso):
    if not token:
        return {"stato": "da collegare", "messaggio": "Manca la chiave di Cloudflare (CLOUDFLARE_API_TOKEN)."}
    fz = fuso()
    oggi = adesso.astimezone(fz).date()
    inizio_locale = dt.datetime.combine(oggi - dt.timedelta(days=GIORNI - 1), dt.time(0), fz)
    # Cloudflare risponde vuoto (senza errore) se il periodo supera 8 giorni: si chiede una settimana alla volta
    # e si sommano i pezzi.
    a = {"ore": [], "pagine": [], "da": [], "dispositivi": [], "paesi": [], "browser": [], "da_paese": []}
    da, fine = inizio_locale.astimezone(dt.timezone.utc), adesso.astimezone(dt.timezone.utc)
    while da < fine:
        a_fine = min(da + dt.timedelta(days=7), fine)
        pezzo = cloudflare(token, da, a_fine)
        for k in a:
            a[k] += pezzo.get(k, [])
        da = a_fine
    for k, dim in (("pagine", "requestPath"), ("da", "refererHost"), ("dispositivi", "deviceType"),
                   ("paesi", "countryName"), ("browser", "userAgentBrowser")):
        somme = collections.OrderedDict()
        for r in a[k]:
            chiave = r["dimensions"][dim]
            t = somme.setdefault(chiave, {"count": 0, "sum": {"visits": 0}, "dimensions": {dim: chiave}})
            t["count"] += r["count"]; t["sum"]["visits"] += r["sum"]["visits"]
        a[k] = sorted(somme.values(), key=lambda r: (r["count"] if k == "pagine" else r["sum"]["visits"]), reverse=True)
    per_giorno = collections.OrderedDict(((oggi - dt.timedelta(days=GIORNI - 1 - i)).isoformat(), [0, 0])
                                         for i in range(GIORNI))
    per_ora = [[0, 0] for _ in range(24)]
    ultime24 = [0, 0]
    for r in a["ore"]:
        t = dt.datetime.fromisoformat(r["dimensions"]["datetimeHour"].replace("Z", "+00:00"))
        loc = t.astimezone(fz)
        v, p = r["sum"]["visits"], r["count"]
        g = per_giorno.get(loc.date().isoformat())
        if g is not None:
            g[0] += v; g[1] += p
        per_ora[loc.hour][0] += v; per_ora[loc.hour][1] += p
        if adesso - t <= dt.timedelta(hours=24):
            ultime24[0] += v; ultime24[1] += p
    titoli = titoli_pagine(sito)
    pagine = [{"percorso": r["dimensions"]["requestPath"], "titolo": titoli.get(r["dimensions"]["requestPath"]),
               "visite": r["sum"]["visits"], "pagine": r["count"]} for r in a["pagine"]]
    prov = collections.Counter()
    for r in a["da"]:
        nome = da_dove(r["dimensions"]["refererHost"])
        if nome:
            prov[nome] += r["sum"]["visits"]
    # chi arriva da Facebook: dall'Italia sono lettori, dall'estero quasi sempre i controlli automatici di Meta
    # sui link appena pubblicati (21 ott 2026: 72 aperture da USA, Irlanda e Svezia nel minuto del post)
    da_fb = {"italia": 0, "estero": 0}
    for r in a["da_paese"]:
        if da_dove(r["dimensions"]["refererHost"]) == "Facebook":
            da_fb["italia" if r["dimensions"]["countryName"] == "IT" else "estero"] += r["sum"]["visits"]
    nomi_disp = {"mobile": "Telefono", "desktop": "Computer", "tablet": "Tablet"}
    return {
        "stato": "ok", "da_facebook": da_fb, "giorni": [{"data": k, "visite": v[0], "pagine": v[1]} for k, v in per_giorno.items()],
        "ore": [{"ora": h, "visite": v[0], "pagine": v[1]} for h, v in enumerate(per_ora)],
        "ultime24": {"visite": ultime24[0], "pagine": ultime24[1]},
        "pagine": pagine[:40],
        "provenienza": [{"nome": k, "visite": v} for k, v in prov.most_common(12)],
        "dispositivi": [{"nome": nomi_disp.get(r["dimensions"]["deviceType"], r["dimensions"]["deviceType"] or "Altro"),
                         "visite": r["sum"]["visits"]} for r in a["dispositivi"]],
        "paesi": [{"nome": r["dimensions"]["countryName"] or "?", "visite": r["sum"]["visits"]} for r in a["paesi"]],
        "browser": [{"nome": r["dimensions"]["userAgentBrowser"] or "?", "visite": r["sum"]["visits"]} for r in a["browser"]],
    }


# ---------- Google (Search Console) ----------
GSC_SITO = "sc-domain:notiziebenevento.it"


def gsc_token(chiave):
    """Un accesso di sola lettura a Search Console con la chiave dell'account di servizio (JWT firmato RS256)."""
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import padding
    b64 = lambda b: base64.urlsafe_b64encode(b).rstrip(b"=")
    ora = int(dt.datetime.now(dt.timezone.utc).timestamp())
    testa = b64(json.dumps({"alg": "RS256", "typ": "JWT"}).encode())
    corpo = b64(json.dumps({"iss": chiave["client_email"], "scope": "https://www.googleapis.com/auth/webmasters.readonly",
                            "aud": "https://oauth2.googleapis.com/token", "iat": ora, "exp": ora + 3600}).encode())
    privata = serialization.load_pem_private_key(chiave["private_key"].encode(), password=None)
    firma = b64(privata.sign(testa + b"." + corpo, padding.PKCS1v15(), hashes.SHA256()))
    dati = urllib.parse.urlencode({"grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
                                   "assertion": (testa + b"." + corpo + b"." + firma).decode()}).encode()
    with urllib.request.urlopen(urllib.request.Request("https://oauth2.googleapis.com/token", data=dati), timeout=30) as r:
        return json.load(r)["access_token"]


def gsc_query(token, corpo):
    url = ("https://www.googleapis.com/webmasters/v3/sites/" + urllib.parse.quote(GSC_SITO, safe="")
           + "/searchAnalytics/query")
    req = urllib.request.Request(url, data=json.dumps(corpo).encode(), method="POST",
                                 headers={"Authorization": "Bearer " + token, "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.load(r).get("rows", [])
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"Search Console {e.code}: {e.read().decode(errors='ignore')[:200]}")


def google(sito, testo_chiave, adesso):
    if not testo_chiave.strip():
        return {"stato": "da collegare", "messaggio": "Manca la chiave dell'account di servizio (GSC_CHIAVE)."}
    chiave = json.loads(testo_chiave[testo_chiave.index("{"):testo_chiave.rindex("}") + 1])
    token = gsc_token(chiave)
    fine = adesso.astimezone(fuso()).date()
    inizio = fine - dt.timedelta(days=27)
    base = {"startDate": inizio.isoformat(), "endDate": fine.isoformat(), "dataState": "all"}
    def riga(r):
        return {"clic": r.get("clicks", 0), "impressioni": r.get("impressions", 0),
                "ctr": round(100 * r.get("ctr", 0), 1), "posizione": round(r.get("position", 0), 1)}
    tot = gsc_query(token, base)
    per_giorno = {r["keys"][0]: riga(r) for r in gsc_query(token, dict(base, dimensions=["date"], rowLimit=100))}
    titoli = titoli_pagine(sito)
    pagine = []
    for r in gsc_query(token, dict(base, dimensions=["page"], rowLimit=25)):
        percorso = urllib.parse.urlsplit(r["keys"][0]).path or "/"
        pagine.append(dict(riga(r), percorso=percorso, titolo=titoli.get(percorso)))
    altri = {}
    for tipo in ("discover", "googleNews"):
        try:
            t = gsc_query(token, dict(base, type=tipo))
            altri[tipo] = riga(t[0]) if t else riga({})
        except RuntimeError:
            altri[tipo] = None
    nomi_disp = {"MOBILE": "Telefono", "DESKTOP": "Computer", "TABLET": "Tablet"}
    return {
        "stato": "ok", "dal": inizio.isoformat(), "al": fine.isoformat(),
        "totali": riga(tot[0]) if tot else riga({}),
        "giorni": [dict(per_giorno.get((inizio + dt.timedelta(days=i)).isoformat(), riga({})),
                        data=(inizio + dt.timedelta(days=i)).isoformat()) for i in range(28)],
        "ricerche": [dict(riga(r), ricerca=r["keys"][0]) for r in gsc_query(token, dict(base, dimensions=["query"], rowLimit=30))],
        "pagine": pagine,
        "dispositivi": [dict(riga(r), nome=nomi_disp.get(r["keys"][0], r["keys"][0]))
                        for r in gsc_query(token, dict(base, dimensions=["device"]))],
        "discover": altri.get("discover"), "news": altri.get("googleNews"),
    }


# ---------- Facebook (la Pagina Notizie Benevento) ----------
GRAPH = "https://graph.facebook.com"
FB_PAGINA = "Notizie Benevento"
# le statistiche di Meta (persone raggiunte, visualizzazioni): servono il permesso read_insights sulla chiave; Meta
# cambia spesso i nomi, quindi si provano uno per uno e si tengono quelli che rispondono
FB_METRICHE = ["page_follows", "page_daily_follows_unique", "page_total_media_view_unique", "page_media_view",
               "page_impressions_unique", "page_post_engagements", "page_views_total"]


def fb_get(percorso, token, **par):
    url = percorso if percorso.startswith("https://") else f"{GRAPH}/{percorso}?" + urllib.parse.urlencode(dict(par, access_token=token))
    try:
        with urllib.request.urlopen(url, timeout=60) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        # il messaggio di Facebook dice cosa non va e non contiene la chiave
        try:
            err = json.load(e).get("error", {})
        except ValueError:
            err = {}
        raise RuntimeError(f"Facebook {e.code}: {err.get('message', '')}") from None


def fb_storico_prima(sito_online, parola):
    """I follower dei giorni passati, dal dati.json già pubblicato (Facebook dà solo il numero di adesso)."""
    if not parola:
        return []
    try:
        from cryptography.hazmat.primitives import hashes
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
        from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
        with urllib.request.urlopen(sito_online + "/statistiche/dati.json", timeout=30) as r:
            b = json.load(r)
        k = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=base64.b64decode(b["sale"]),
                       iterations=b["iterazioni"]).derive(parola.encode())
        vecchi = json.loads(AESGCM(k).decrypt(base64.b64decode(b["iv"]), base64.b64decode(b["dati"]), None))
        return (vecchi.get("facebook") or {}).get("storico") or []
    except Exception:
        return []


def facebook(token, adesso, storico_prima):
    if not token:
        return {"stato": "da collegare", "messaggio": "Manca la chiave della Pagina (FB_PAGE_TOKEN)."}
    fz = fuso()
    pag = fb_get("me", token, fields="name,followers_count,fan_count,link")
    if pag.get("name") != FB_PAGINA:
        raise RuntimeError(f"la chiave non è della Pagina «{FB_PAGINA}»")
    oggi = adesso.astimezone(fz).date()
    inizio = dt.datetime.combine(oggi - dt.timedelta(days=GIORNI - 1), dt.time(0), fz)
    # i post degli ultimi 30 giorni con reazioni, commenti e condivisioni
    post, url = [], None
    # commenti e reazioni vogliono il permesso pages_read_user_content: senza, si prova con meno campi
    base = "created_time,message,permalink_url,shares,attachments{unshimmed_url,url}"
    for extra in (",reactions.summary(total_count).limit(0),comments.summary(total_count).limit(0)",
                  ",reactions.summary(total_count).limit(0)", ""):
        try:
            r = fb_get("me/posts", token, fields=base + extra, limit=100, since=int(inizio.timestamp()))
            break
        except RuntimeError as e:
            if not extra or "(#10)" not in str(e):
                raise
    con_commenti, con_reazioni = "comments" in extra, "reactions" in extra
    for _ in range(10):
        for p in r.get("data", []):
            t = dt.datetime.strptime(p["created_time"], "%Y-%m-%dT%H:%M:%S%z").astimezone(fz)
            link = ""
            for a in (p.get("attachments") or {}).get("data", []):
                u = a.get("unshimmed_url") or a.get("url") or ""
                u = urllib.parse.parse_qs(urllib.parse.urlparse(u).query).get("u", [u])[0]
                m = re.search(r"notiziebenevento\.it(/notizia/[a-z0-9-]+/)", u)
                if m:
                    link = m.group(1)
            reaz = ((p.get("reactions") or {}).get("summary") or {}).get("total_count", 0) if con_reazioni else None
            comm = ((p.get("comments") or {}).get("summary") or {}).get("total_count", 0) if con_commenti else None
            cond = (p.get("shares") or {}).get("count", 0)
            post.append({"quando": t.isoformat(timespec="minutes"), "titolo": (p.get("message") or "").split("\n")[0][:160],
                         "link": p.get("permalink_url"), "notizia": link, "reazioni": reaz, "commenti": comm,
                         "condivisioni": cond, "interazioni": (reaz or 0) + (comm or 0) + cond})
        url = (r.get("paging") or {}).get("next")
        if not url:
            break
        r = fb_get(url, token)
    per_giorno = collections.OrderedDict(((oggi - dt.timedelta(days=GIORNI - 1 - i)).isoformat(), [0, 0])
                                         for i in range(GIORNI))
    for p in post:
        g = per_giorno.get(p["quando"][:10])
        if g is not None:
            g[0] += 1; g[1] += p["interazioni"]
    # i follower giorno per giorno: il numero di oggi si aggiunge a quelli salvati nei giorni prima
    follower = pag.get("followers_count")
    storico = {x["data"]: x["follower"] for x in storico_prima if isinstance(x, dict) and x.get("data")}
    if follower is not None:
        storico[oggi.isoformat()] = follower
    storico = [{"data": k, "follower": v} for k, v in sorted(storico.items())][-90:]
    # le statistiche di Meta, se la chiave ha il permesso
    meta = {}
    for nome in FB_METRICHE:
        try:
            j = fb_get("me/insights", token, metric=nome, period="day", since=int(inizio.timestamp()),
                       until=int(adesso.timestamp()))
        except RuntimeError:
            continue
        valori = (j.get("data") or [{}])[0].get("values") or []
        if valori:
            meta[nome] = [{"data": v["end_time"][:10], "valore": v.get("value") if isinstance(v.get("value"), (int, float)) else 0}
                          for v in valori]
    return {
        "stato": "ok", "pagina": pag.get("link") or "https://www.facebook.com/notiziebenevento",
        "follower": follower, "mi_piace": pag.get("fan_count"), "storico": storico,
        "giorni": [{"data": k, "post": v[0], "interazioni": v[1]} for k, v in per_giorno.items()],
        "post": sorted(post, key=lambda p: p["quando"], reverse=True),
        "meta": meta, "commenti": con_commenti, "reazioni": con_reazioni,
    }


# ---------- dietro le quinte: il diario dell'agente ----------
GIORNI_AGENTE = 4


def prossimo_giro(adesso):
    """I giri partono alle :05 dalle 6 alle 22 (ora italiana); alle 23:05 solo la sera prima di un'allerta arancione o rossa."""
    t = adesso.astimezone(fuso())
    for h in range(t.hour, 23):
        g = t.replace(hour=h, minute=5, second=0, microsecond=0)
        if h >= 6 and g > t:
            return {"ora": g.isoformat(timespec="minutes"), "nota": ""}
    domani = (t + dt.timedelta(days=1)).replace(hour=6, minute=5, second=0, microsecond=0)
    nota = "alle 23:05 c'è un giro solo se domani c'è un'allerta arancione o rossa" if t.hour < 23 else ""
    return {"ora": domani.isoformat(timespec="minutes"), "nota": nota}


def agente(sito, chiave_pem, adesso):
    if not chiave_pem.strip():
        return {"stato": "da collegare", "messaggio": "Manca la chiave del diario (segreto DIARIO_CHIAVE)."}
    from cryptography.hazmat.primitives import serialization
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import diario
    privata = serialization.load_pem_private_key(chiave_pem.encode(), password=None)
    pub = leggi(diario.CHIAVE_PUBBLICA, {}) or {}
    if int(pub.get("n", "0"), 16) != privata.public_key().public_numbers().n:
        return {"stato": "errore", "messaggio": "La chiave segreta del diario (DIARIO_CHIAVE) non è quella di "
                                                "strumenti/diario_chiave_pubblica.json: il diario non si legge."}
    giri = []
    for p in sorted(glob.glob(os.path.join(sito, "diario", "[0-9]*.json")), reverse=True)[:GIORNI_AGENTE]:
        g = leggi(p, {}) or {}
        for v in g.get("voci", []):
            try:
                x = diario.decifra(v["busta"], privata)
            except Exception as e:
                x = {"ora": v.get("ora"), "errore": f"questo giro non si legge ({type(e).__name__})"}
            x["giorno"] = g.get("giorno")
            giri.append(x)
    giri.sort(key=lambda x: (x.get("giorno") or "", x.get("ora") or ""), reverse=True)
    prima = leggi(os.path.join(sito, "notizie.json"), {}) or {}
    return {"stato": "ok", "giri": giri, "prossimo": prossimo_giro(adesso), "ultimo_giro": prima.get("aggiornato")}


# ---------- il sito: notizie e fonti ----------
def sito_numeri(sito, adesso):
    oggi = adesso.astimezone(fuso()).date()
    notizie, visti = [], set()
    for f in [os.path.join(sito, "notizie.json")] + sorted(glob.glob(os.path.join(sito, "archivio", "[0-9]*-[0-9]*.json"))):
        for n in (leggi(f, {}) or {}).get("notizie", []):
            if n.get("id") and n["id"] not in visti:
                visti.add(n["id"]); notizie.append(n)
    dal = (oggi - dt.timedelta(days=GIORNI - 1)).isoformat()
    recenti = [n for n in notizie if str(n.get("pubblicato", ""))[:10] >= dal]
    per_giorno = collections.Counter(str(n.get("pubblicato", ""))[:10] for n in recenti)
    fonti = collections.Counter()
    for n in recenti:
        for f in n.get("fonti") or []:
            if f.get("nome"):
                fonti[f["nome"]] += 1
    n_fonti = [len(n.get("fonti") or []) for n in recenti]
    prima = leggi(os.path.join(sito, "notizie.json"), {}) or {}
    return {
        "totale": len(notizie), "ultimi_giorni": len(recenti),
        "giorni": [{"data": (oggi - dt.timedelta(days=GIORNI - 1 - i)).isoformat(),
                    "notizie": per_giorno.get((oggi - dt.timedelta(days=GIORNI - 1 - i)).isoformat(), 0)} for i in range(GIORNI)],
        "sezioni": [{"nome": NOMI_CAT.get(k, k), "notizie": v} for k, v in
                    collections.Counter(n.get("categoria") for n in recenti).most_common()],
        "zone": [{"nome": NOMI_ZONA.get(k, k), "notizie": v} for k, v in
                 collections.Counter(n.get("zona") for n in recenti).most_common()],
        "fonti": [{"nome": k, "notizie": v} for k, v in fonti.most_common(20)],
        "media_fonti": round(sum(n_fonti) / len(n_fonti), 1) if n_fonti else None,
        "ufficiali": sum(1 for n in recenti if n.get("stato") == "ufficiale"),
        "rilevanti": sum(1 for n in recenti if n.get("rilevante")),
        "in_prima_pagina": len(prima.get("notizie", [])),
        "giornali_letti": prima.get("giornali_letti"), "ultimo_giro": prima.get("aggiornato"),
    }


# ---------- cifratura ----------
def cifra(dati, parola):
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
    chiave = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=SALE, iterations=ITERAZIONI).derive(parola.encode())
    iv = os.urandom(12)
    testo = json.dumps(dati, ensure_ascii=False, separators=(",", ":")).encode()
    b64 = lambda b: base64.b64encode(b).decode()
    return {"v": 1, "kdf": "PBKDF2-SHA256", "iterazioni": ITERAZIONI, "sale": b64(SALE), "iv": b64(iv),
            "dati": b64(AESGCM(chiave).encrypt(iv, testo, None))}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sito", default=os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    ap.add_argument("--in-chiaro", help="scrive i dati senza cifrarli in questo file (solo per le prove)")
    a = ap.parse_args()
    adesso = dt.datetime.now(dt.timezone.utc)
    dati = {"aggiornato": adesso.astimezone(fuso()).isoformat(timespec="minutes"), "giorni": GIORNI}
    try:
        dati["visite"] = visite(a.sito, chiave_cloudflare(os.environ.get("CLOUDFLARE_API_TOKEN", "")), adesso)
        print("Visite:", dati["visite"]["stato"])
    except Exception as e:
        dati["visite"] = {"stato": "errore", "messaggio": f"Cloudflare non ha risposto: {e}"}
        print("AVVISO visite:", e, file=sys.stderr)
    dati["sito"] = sito_numeri(a.sito, adesso)
    try:
        dati["google"] = google(a.sito, os.environ.get("GSC_CHIAVE", ""), adesso)
        print("Google:", dati["google"]["stato"])
    except Exception as e:
        dati["google"] = {"stato": "errore", "messaggio": f"Search Console non ha risposto: {e}"}
        print("AVVISO Google:", e, file=sys.stderr)
    try:
        dati["agente"] = agente(a.sito, os.environ.get("DIARIO_CHIAVE", ""), adesso)
        # nei log (pubblici) solo quanti giri, mai il contenuto
        print("Dietro le quinte:", dati["agente"]["stato"], len(dati["agente"].get("giri") or []), "giri")
    except Exception as e:
        dati["agente"] = {"stato": "errore", "messaggio": f"Il diario non si legge: {e}"}
        print("AVVISO diario:", e, file=sys.stderr)
    parola = os.environ.get("STATISTICHE_PAROLA", "")
    try:
        dati["facebook"] = facebook(os.environ.get("FB_PAGE_TOKEN", "").strip(), adesso,
                                    fb_storico_prima("https://" + HOST, parola))
        # nei log (pubblici) solo l'esito e i nomi delle statistiche di Meta che rispondono, mai i numeri
        print("Facebook:", dati["facebook"]["stato"], "· statistiche Meta:", ", ".join(dati["facebook"].get("meta") or {}) or "nessuna")
    except Exception as e:
        dati["facebook"] = {"stato": "errore", "messaggio": f"Facebook non ha risposto: {e}"}
        print("AVVISO Facebook:", e, file=sys.stderr)
    if a.in_chiaro:
        with open(a.in_chiaro, "w", encoding="utf-8") as f:
            json.dump(dati, f, ensure_ascii=False, indent=1)
        print("OK in chiaro:", a.in_chiaro)
        return
    if not parola:
        print("AVVISO: manca STATISTICHE_PAROLA, statistiche non scritte", file=sys.stderr)
        return
    uscita = os.path.join(a.sito, "statistiche", "dati.json")
    os.makedirs(os.path.dirname(uscita), exist_ok=True)
    with open(uscita, "w", encoding="utf-8") as f:
        json.dump(cifra(dati, parola), f)
    print("OK statistiche cifrate")


if __name__ == "__main__":
    main()
