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
- Instagram: stessa chiave (instagram_basic): follower, post, «mi piace» e commenti.
- Telegram: dalla pagina pubblica del canale (t.me/s/…): iscritti e visualizzazioni di ogni messaggio.
- Puntualità: dalle API di GitHub (GH_TOKEN): quanto ci mette ogni giro ad andare online, giri mancati,
  pubblicazioni annullate o rilanciate, sentinelle rosse.
- Comunicati per posta: quanti ne arrivano, dal diario dei giri.

Il file è cifrato con la parola d'ordine (AES-GCM, chiave da PBKDF2-SHA256): chi trova l'indirizzo vede solo
numeri illeggibili; la pagina statistiche/index.html lo apre nel browser con la stessa parola.
Niente numeri nei log di GitHub (il repository è pubblico): si stampano solo gli esiti.

Uso:  CLOUDFLARE_API_TOKEN=… STATISTICHE_PAROLA=… FB_PAGE_TOKEN=… GH_TOKEN=… python3 strumenti/statistiche.py [--sito .]
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


def dati_prima(sito_online, parola):
    """Il dati.json già pubblicato, decifrato: da lì si riprendono i follower e gli iscritti dei giorni passati
    (Facebook, Instagram e Telegram danno solo il numero di adesso)."""
    if not parola:
        return {}
    try:
        from cryptography.hazmat.primitives import hashes
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
        from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
        with urllib.request.urlopen(sito_online + "/statistiche/dati.json", timeout=30) as r:
            b = json.load(r)
        k = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=base64.b64decode(b["sale"]),
                       iterations=b["iterazioni"]).derive(parola.encode())
        return json.loads(AESGCM(k).decrypt(base64.b64decode(b["iv"]), base64.b64decode(b["dati"]), None))
    except Exception:
        return {}


def storico_aggiornato(prima, oggi, valore, campo):
    """Lo storico giorno per giorno (ultimi 90): quello di prima più il numero di oggi."""
    st = {x["data"]: x[campo] for x in prima or [] if isinstance(x, dict) and x.get("data")}
    if valore is not None:
        st[oggi.isoformat()] = valore
    return [{"data": k, campo: v} for k, v in sorted(st.items())][-90:]


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
    storico = storico_aggiornato(storico_prima, oggi, follower, "follower")
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


# ---------- Instagram (l'account aziendale collegato alla Pagina) ----------
def instagram(token, adesso, storico_prima):
    """Con la stessa chiave della Pagina (permesso instagram_basic): follower, post, «mi piace» e commenti.
    Persone raggiunte e visualizzazioni vorrebbero instagram_manage_insights: si provano, se non rispondono niente."""
    if not token:
        return {"stato": "da collegare", "messaggio": "Manca la chiave della Pagina (FB_PAGE_TOKEN)."}
    fz = fuso()
    acc = (fb_get("me", token, fields="instagram_business_account{id,username,followers_count,media_count}")
           .get("instagram_business_account"))
    if not acc:
        return {"stato": "da collegare", "messaggio": "Alla Pagina non è collegato nessun account Instagram (o la chiave non ha instagram_basic)."}
    oggi = adesso.astimezone(fz).date()
    dal = dt.datetime.combine(oggi - dt.timedelta(days=GIORNI - 1), dt.time(0), fz)
    post = []
    r = fb_get(f"{acc['id']}/media", token, fields="caption,timestamp,like_count,comments_count,permalink", limit=100)
    for _ in range(10):
        vecchi = False
        for x in r.get("data", []):
            t = dt.datetime.strptime(x["timestamp"], "%Y-%m-%dT%H:%M:%S%z").astimezone(fz)
            if t < dal:
                vecchi = True
                continue
            cap = x.get("caption") or ""
            m = re.search(r"notiziebenevento\.it(/notizia/[a-z0-9-]+/)", cap)
            mp, cm = x.get("like_count"), x.get("comments_count")
            post.append({"quando": t.isoformat(timespec="minutes"), "titolo": cap.split("\n")[0][:160],
                         "link": x.get("permalink"), "notizia": m.group(1) if m else "", "mi_piace": mp,
                         "commenti": cm, "interazioni": (mp or 0) + (cm or 0)})
        url = (r.get("paging") or {}).get("next")
        if vecchi or not url:
            break
        r = fb_get(url, token)
    per_giorno = collections.OrderedDict(((oggi - dt.timedelta(days=GIORNI - 1 - i)).isoformat(), [0, 0])
                                         for i in range(GIORNI))
    for x in post:
        g = per_giorno.get(x["quando"][:10])
        if g is not None:
            g[0] += 1; g[1] += x["interazioni"]
    meta = {}
    for nome in ("reach", "views", "profile_views"):
        try:
            j = fb_get(f"{acc['id']}/insights", token, metric=nome, period="day", metric_type="total_value",
                       since=int(dal.timestamp()), until=int(adesso.timestamp()))
            v = ((j.get("data") or [{}])[0].get("total_value") or {}).get("value")
            if isinstance(v, (int, float)):
                meta[nome] = v
        except RuntimeError:
            continue
    return {"stato": "ok", "profilo": f"https://www.instagram.com/{acc.get('username')}/", "nome": acc.get("username"),
            "follower": acc.get("followers_count"), "post_totali": acc.get("media_count"),
            "storico": storico_aggiornato(storico_prima, oggi, acc.get("followers_count"), "follower"),
            "giorni": [{"data": k, "post": v[0], "interazioni": v[1]} for k, v in per_giorno.items()],
            "post": sorted(post, key=lambda x: x["quando"], reverse=True), "meta": meta}


# ---------- Telegram (il canale t.me/notiziebenevento) ----------
TG_WEB = "https://t.me/s/notiziebenevento"


def numero_tg(t):
    """«1.2K» → 1200 (Telegram scrive così iscritti e visualizzazioni)."""
    t = (t or "").strip().replace(",", ".").replace(" ", "")
    molt = {"K": 1000, "M": 1000000}.get(t[-1:].upper(), 1)
    try:
        return int(round(float(t[:-1] if molt > 1 else t) * molt))
    except ValueError:
        return None


def telegram(adesso, storico_prima):
    """Dalla pagina pubblica del canale (niente chiave): iscritti e, messaggio per messaggio, quante volte è stato
    visto. Si va indietro pagina per pagina fino a 30 giorni fa."""
    import html as H
    fz = fuso()
    oggi = adesso.astimezone(fz).date()
    dal = dt.datetime.combine(oggi - dt.timedelta(days=GIORNI - 1), dt.time(0), fz)
    messaggi, iscritti, prima_id = {}, None, None
    for _ in range(20):
        req = urllib.request.Request(TG_WEB + (f"?before={prima_id}" if prima_id else ""),
                                     headers={"User-Agent": "Mozilla/5.0 (notiziebenevento.it)", "Accept-Language": "en"})
        with urllib.request.urlopen(req, timeout=30) as r:
            pagina = r.read().decode("utf-8", "replace")
        if iscritti is None:
            m = re.search(r'counter_value">([^<]+)</span>\s*<span class="counter_type">subscriber', pagina)
            iscritti = numero_tg(m.group(1)) if m else None
        ids, piu_vecchio = [], None
        for b in re.split(r'(?=<div class="tgme_widget_message_wrap)', pagina)[1:]:
            mid, t = re.search(r'data-post="[^"/]+/(\d+)"', b), re.search(r'<time[^>]*datetime="([^"]+)"', b)
            if not mid or not t:
                continue
            mid, t = int(mid.group(1)), dt.datetime.fromisoformat(t.group(1)).astimezone(fz)
            ids.append(mid)
            piu_vecchio = min(piu_vecchio, t) if piu_vecchio else t
            v = re.search(r'tgme_widget_message_views">([^<]+)<', b)
            if not v or t < dal:   # i messaggi di servizio (canale creato, foto) non hanno visualizzazioni
                continue
            tx = re.search(r'tgme_widget_message_text[^>]*>(.*?)</div>', b, re.S)
            testo = H.unescape(re.sub(r"<[^>]+>", " ", re.sub(r"<br\s*/?>", "\n", tx.group(1)))) if tx else ""
            no = re.search(r"notiziebenevento\.it(/notizia/[a-z0-9-]+/)", b)
            messaggi[mid] = {"quando": t.isoformat(timespec="minutes"),
                             "titolo": re.sub(r"\s+", " ", testo.strip().split("\n")[0]).strip()[:160],
                             "link": f"https://t.me/notiziebenevento/{mid}", "notizia": no.group(1) if no else "",
                             "aggiornamento": testo.lstrip().startswith("🔴"), "viste": numero_tg(v.group(1))}
        if not ids or min(ids) <= 1 or (piu_vecchio and piu_vecchio < dal):
            break
        prima_id = min(ids)
    per_giorno = collections.OrderedDict(((oggi - dt.timedelta(days=GIORNI - 1 - i)).isoformat(), [0, 0])
                                         for i in range(GIORNI))
    for x in messaggi.values():
        g = per_giorno.get(x["quando"][:10])
        if g is not None:
            g[0] += 1; g[1] += x["viste"] or 0
    return {"stato": "ok", "canale": "https://t.me/notiziebenevento", "iscritti": iscritti,
            "storico": storico_aggiornato(storico_prima, oggi, iscritti, "iscritti"),
            "giorni": [{"data": k, "messaggi": v[0], "viste": v[1]} for k, v in per_giorno.items()],
            "messaggi": sorted(messaggi.values(), key=lambda x: x["quando"], reverse=True)}


# ---------- puntualità: i giri dell'agente e le pubblicazioni su GitHub ----------
REPO = "ernbale/notizie-benevento"
ORARIO_DAL = "2026-10-22"   # da qui un giro ogni ora, dalle 6 alle 22 (il giro delle 23 pubblica solo con l'allerta)
ORE_GIRI = range(6, 23)


def gh_get(percorso, token):
    req = urllib.request.Request(f"https://api.github.com/{percorso}", headers={
        "Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json", "User-Agent": "nb-statistiche"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"GitHub {e.code}") from None


def puntualita(token, adesso, giri_prima=None):
    """Per ogni giro dell'agente (il commit «Notizie delle HH:MM»): quanto ci ha messo ad andare online (dalla spinta
    su GitHub alla fine della prima pubblicazione riuscita partita dopo), i giri mancati, le pubblicazioni annullate
    o rilanciate (dalla sentinella o a mano) e le sentinelle rosse."""
    if not token:
        return {"stato": "da collegare", "messaggio": "Manca la chiave di GitHub (GH_TOKEN) nel passo delle statistiche."}
    fz = fuso()
    oggi = adesso.astimezone(fz).date()
    dal = oggi - dt.timedelta(days=GIORNI - 1)
    iso = lambda x: dt.datetime.fromisoformat(x.replace("Z", "+00:00")).astimezone(fz)
    corse = []
    for pag in range(1, 11):
        r = gh_get(f"repos/{REPO}/actions/workflows/pubblica.yml/runs?per_page=100&page={pag}&created=%3E%3D{dal.isoformat()}", token)
        corse += r.get("workflow_runs", [])
        if len(r.get("workflow_runs", [])) < 100:
            break
    # quando il giro è andato online: la fine della prima pubblicazione riuscita partita dopo la sua spinta (l'ora
    # esatta la dà solo l'elenco dei lavori della pubblicazione: una domanda in più a GitHub, quindi i giri già
    # misurati si riprendono dal dati.json di prima e si misurano solo quelli nuovi degli ultimi 7 giorni)
    gia = {g["spinta"]: g["minuti"] for g in giri_prima or [] if isinstance(g, dict) and g.get("minuti") is not None}
    riuscite = sorted((iso(c["created_at"]), c["id"]) for c in corse
                      if c.get("status") == "completed" and c.get("conclusion") == "success")
    fine_di = {}

    def fine(id_corsa):
        if id_corsa not in fine_di:
            lavori = gh_get(f"repos/{REPO}/actions/runs/{id_corsa}/jobs", token).get("jobs", [])
            fini = [iso(x["completed_at"]) for x in lavori if x.get("completed_at")]
            fine_di[id_corsa] = max(fini) if fini else None
        return fine_di[id_corsa]
    giri = []
    for c in corse:
        m = re.match(r"Notizie delle (\d{1,2}):(\d{2})", c.get("display_title") or "")
        if c.get("event") != "push" or not m:
            continue
        spinta = iso(c["created_at"])
        chiave = spinta.isoformat(timespec="minutes")
        minuti = gia.get(chiave)
        if minuti is None and adesso - spinta < dt.timedelta(days=7):
            dopo = next((rid for t, rid in riuscite if t >= spinta - dt.timedelta(seconds=5)), None)
            online = fine(dopo) if dopo else None
            minuti = round((online - spinta).total_seconds() / 60) if online else None
        giri.append({"giorno": spinta.date().isoformat(), "ora": f"{int(m.group(1)):02d}:{m.group(2)}",
                     "spinta": chiave, "minuti": minuti})
    giri.sort(key=lambda g: g["spinta"])
    giorni = []
    for i in range(GIORNI):
        d = (dal + dt.timedelta(days=i)).isoformat()
        gg = [g for g in giri if g["giorno"] == d]
        minuti = [g["minuti"] for g in gg if g["minuti"] is not None]
        mancati = None
        if d >= ORARIO_DAL:
            fatte = {int(g["ora"][:2]) for g in gg}
            limite = adesso.astimezone(fz) - dt.timedelta(minutes=75)
            mancati = [h for h in ORE_GIRI if h not in fatte and
                       dt.datetime.combine(dt.date.fromisoformat(d), dt.time(h, 5), fz) <= limite]
        giorni.append({"data": d, "giri": len(gg), "mancati": mancati,
                       "media": round(sum(minuti) / len(minuti)) if minuti else None, "max": max(minuti) if minuti else None})
    sentinelle = gh_get(f"repos/{REPO}/actions/workflows/sentinella.yml/runs?per_page=100&created=%3E%3D{dal.isoformat()}",
                        token).get("workflow_runs", [])
    return {"stato": "ok", "giri": giri, "giorni": giorni,
            "annullate": sum(1 for c in corse if c.get("conclusion") == "cancelled"),
            "rilanciate": sum(1 for c in corse if c.get("event") == "workflow_dispatch"),
            "sentinella_rossa": sum(1 for c in sentinelle if c.get("conclusion") == "failure"),
            "sentinella_allarme": max((c["created_at"] for c in sentinelle if c.get("conclusion") == "failure"),
                                      default=None)}


def chiusure(sito, token, adesso, agente_dati):
    """La scheda «Chiusure»: le chiusure in corso (chiusure.json) con quando sono uscite sui social (il ricordo di
    chiusure_social.py, che GitHub ripristina prima di questo passo: è quello della pubblicazione precedente), le piste
    della vedetta del Pi con il loro esito (dal diario dell'ultimo giro) e le pubblicazioni del giro Chiusure (i commit
    di chiusure.json, 30 giorni)."""
    c = leggi(os.path.join(sito, "chiusure.json"), {}) or {}
    oggi = adesso.astimezone(fuso()).date().isoformat()
    social = leggi(os.environ.get("CHIUSURE_STATO") or "-", {}) or {}

    def uscite(x):
        k = f"{x['id']}@{x.get('aggiornata') or x.get('aggiunta')}"
        return {can: (social.get(can) or {}).get(k) for can in ("telegram", "facebook", "instagram")}
    tutte = c.get("chiusure") or []
    in_corso = [dict(x, uscite=uscite(x)) for x in tutte if max(x.get("giorni") or [""]) >= oggi]
    ved = next((g["vedetta"] for g in (agente_dati or {}).get("giri") or [] if isinstance(g.get("vedetta"), dict)), None)
    viste, scart = set(c.get("viste") or []), {s.get("pista"): s for s in c.get("scartate") or []}
    pubbl = {x.get("pista") for x in tutte if x.get("pista")}
    piste = []
    for p in (ved or {}).get("piste") or []:
        esito = ("pubblicata" if p["id"] in pubbl else f"scartata: {scart[p['id']].get('motivo') or ''}" if p["id"] in scart
                 else "vista" if p["id"] in viste else "in attesa")
        piste.append(dict(p, esito=esito))
    storico = []
    if token:
        dal = (adesso - dt.timedelta(days=30)).astimezone(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        for x in gh_get(f"repos/{REPO}/commits?path=chiusure.json&since={dal}&per_page=100", token):
            m = x["commit"]["message"].split("\n")[0]
            if m.startswith("Chiusure delle"):
                storico.append({"quando": x["commit"]["committer"]["date"], "messaggio": m[:200]})
    minuti = [round((dt.datetime.fromisoformat(x["aggiunta"]) - dt.datetime.fromisoformat(x["trovata"])).total_seconds() / 60)
              for x in tutte if x.get("trovata") and x.get("aggiunta")]
    return {"stato": "ok", "aggiornato": c.get("aggiornato"), "in_corso": in_corso, "piste": piste[::-1], "storico": storico,
            "minuti_vedetta_sito": minuti,
            "vedetta": {k: (ved or {}).get(k) for k in ("controllato", "esito", "allerta")} if ved else None}


def comunicati(agente_dati):
    """I comunicati arrivati per posta, dal diario dei giri (archivia.py li conta a ogni giro)."""
    giri = [g for g in (agente_dati or {}).get("giri") or [] if isinstance(g.get("comunicati"), dict)]
    if not giri:
        return {"stato": "vuoto"}
    per_giorno, domini = collections.Counter(), collections.Counter()
    for g in giri:
        per_giorno[g.get("giorno")] += g["comunicati"].get("arrivati") or 0
        for d in g["comunicati"].get("domini") or []:
            domini[d] += 1
    return {"stato": "ok", "giri": len(giri), "arrivati": sum(per_giorno.values()),
            "giorni": [{"data": k, "arrivati": v} for k, v in sorted(per_giorno.items())],
            "domini": [{"nome": k, "comunicati": v} for k, v in domini.most_common(15)],
            "casella": giri[0]["comunicati"].get("casella")}


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
    prima = dati_prima("https://" + HOST, parola)
    fb_token = os.environ.get("FB_PAGE_TOKEN", "").strip()
    try:
        dati["facebook"] = facebook(fb_token, adesso, (prima.get("facebook") or {}).get("storico"))
        # nei log (pubblici) solo l'esito e i nomi delle statistiche di Meta che rispondono, mai i numeri
        print("Facebook:", dati["facebook"]["stato"], "· statistiche Meta:", ", ".join(dati["facebook"].get("meta") or {}) or "nessuna")
    except Exception as e:
        dati["facebook"] = {"stato": "errore", "messaggio": f"Facebook non ha risposto: {e}"}
        print("AVVISO Facebook:", e, file=sys.stderr)
    # gli altri canali: stesso schema (nei log solo l'esito)
    for nome, fare in (("instagram", lambda: instagram(fb_token, adesso, (prima.get("instagram") or {}).get("storico"))),
                       ("telegram", lambda: telegram(adesso, (prima.get("telegram") or {}).get("storico"))),
                       ("puntualita", lambda: puntualita(os.environ.get("GH_TOKEN", "").strip(), adesso,
                                                      (prima.get("puntualita") or {}).get("giri")))):
        try:
            dati[nome] = fare()
            print(f"{nome.capitalize()}:", dati[nome]["stato"],
                  *(["· statistiche Meta:", ", ".join(dati[nome].get("meta") or {}) or "nessuna"]
                    if nome == "instagram" else []))
        except Exception as e:
            dati[nome] = {"stato": "errore", "messaggio": f"non ha risposto: {e}"}
            print(f"AVVISO {nome}:", e, file=sys.stderr)
    dati["comunicati"] = comunicati(dati.get("agente"))
    try:
        dati["chiusure"] = chiusure(a.sito, os.environ.get("GH_TOKEN", "").strip(), adesso, dati.get("agente"))
        print("Chiusure:", dati["chiusure"]["stato"])
    except Exception as e:
        dati["chiusure"] = {"stato": "errore", "messaggio": f"non si leggono: {e}"}
        print("AVVISO chiusure:", e, file=sys.stderr)
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
