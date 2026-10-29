#!/usr/bin/env python3
"""Previsioni meteo per Benevento messe insieme da 8 modelli meteo indipendenti → meteo.json.

Per ogni ora si prende la MEDIANA dei modelli (il valore di mezzo: un modello che sbaglia da solo non sposta
il risultato); la probabilità di pioggia è la quota di modelli che prevede pioggia in quell'ora o in quel giorno.
Dati: Open-Meteo (modelli dei servizi meteo nazionali, licenza CC BY 4.0) e Copernicus CAMS (aria e pollini).

Uso:  python3 strumenti/meteo.py [--uscita meteo.json]
Esce con codice 1 senza scrivere niente se i dati non arrivano o non tornano.
"""
import argparse
import datetime as dt
import json
import math
import os
import re
import statistics
import sys
import time
import urllib.parse
import urllib.request

LUOGO = {"nome": "Benevento", "lat": 41.1305, "lon": 14.7826}
FUSO = "Europe/Rome"
GIORNI = 10

MODELLI = [
    {"id": "ecmwf_ifs", "nome": "ECMWF", "ente": "Centro europeo per le previsioni meteo"},
    {"id": "icon_seamless", "nome": "ICON", "ente": "Servizio meteo tedesco (DWD)"},
    {"id": "italia_meteo_arpae_icon_2i", "nome": "ICON-2I", "ente": "ItaliaMeteo e Arpae, alta definizione (2 km)"},
    {"id": "meteofrance_seamless", "nome": "Météo-France", "ente": "Servizio meteo francese (Arpège e Arome)"},
    {"id": "ukmo_seamless", "nome": "Met Office", "ente": "Servizio meteo del Regno Unito"},
    {"id": "gfs_seamless", "nome": "GFS", "ente": "Servizio meteo degli Stati Uniti (NOAA)"},
    {"id": "gem_seamless", "nome": "GEM", "ente": "Servizio meteo del Canada"},
    {"id": "jma_seamless", "nome": "JMA", "ente": "Servizio meteo del Giappone"},
]
VAR_MODELLI = ["temperature_2m", "precipitation", "snowfall", "weather_code", "cloud_cover",
               "wind_speed_10m", "wind_direction_10m", "wind_gusts_10m", "relative_humidity_2m", "dew_point_2m",
               "pressure_msl"]
POLLINI = {"alder_pollen": "ontano", "birch_pollen": "betulla", "grass_pollen": "graminacee",
           "mugwort_pollen": "artemisia", "olive_pollen": "olivo", "ragweed_pollen": "ambrosia"}
PIOGGIA_ORA = 0.1    # mm in un'ora per dire «piove» per un modello
PIOGGIA_GIORNO = 1.0  # mm in un giorno


def scarica(url, tentativi=3):
    for i in range(tentativi):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "notizie-benevento meteo (github.com/ernbale)"})
            with urllib.request.urlopen(req, timeout=40) as r:
                d = json.load(r)
            if d.get("error"):
                raise RuntimeError(d.get("reason"))
            return d
        except Exception as e:
            print(f"tentativo {i + 1}: {e}", file=sys.stderr)
            time.sleep(5 * (i + 1))
    raise RuntimeError("dati non disponibili: " + url.split("?")[0])


def url(base, **p):
    return base + "?" + urllib.parse.urlencode(p, safe=",")


def mediana(v):
    v = [x for x in v if x is not None]
    return round(statistics.median(v), 1) if v else None


def percepita(t, ur, v):
    """Temperatura percepita come la calcola il servizio meteo americano (NWS), usata anche dalle app più diffuse:
    sotto i 10° con vento l'effetto del vento (wind chill), sopra i 27° l'effetto dell'umidità (indice di calore),
    in mezzo la temperatura vera. La «apparent temperature» dei modelli (Steadman) alza la percepita con l'umidità
    anche col fresco: con la pioggia a 16° diceva 20°, mentre bagnato e fresco si sente più freddo, non più caldo."""
    if t is None:
        return None
    if t <= 10 and v is not None and v > 4.8:
        k = v ** 0.16          # vento in km/h
        return round(min(t, 13.12 + 0.6215 * t - 11.37 * k + 0.3965 * t * k), 1)
    if t >= 26.7 and ur is not None:
        f = t * 9 / 5 + 32     # le formule dell'indice di calore sono in gradi Fahrenheit
        hi = 0.5 * (f + 61 + (f - 68) * 1.2 + ur * 0.094)
        if (hi + f) / 2 >= 80:
            hi = (-42.379 + 2.04901523 * f + 10.14333127 * ur - 0.22475541 * f * ur - 6.83783e-3 * f * f
                  - 5.481717e-2 * ur * ur + 1.22874e-3 * f * f * ur + 8.5282e-4 * f * ur * ur - 1.99e-6 * f * f * ur * ur)
            if ur < 13 and f <= 112:
                hi -= (13 - ur) / 4 * ((17 - abs(f - 95)) / 17) ** 0.5
            elif ur > 85 and f <= 87:
                hi += (ur - 85) / 10 * (87 - f) / 5
        return round((hi - 32) * 5 / 9, 1)
    return t


def direzione_media(dirs, vel):
    """Media delle direzioni del vento come vettori (la mediana degli angoli non ha senso: 350° e 10° sono vicini)."""
    x = y = 0.0
    for d, s in zip(dirs, vel):
        if d is None or s is None:
            continue
        x += math.sin(math.radians(d)) * max(s, 0.1)
        y += math.cos(math.radians(d)) * max(s, 0.1)
    if x == 0 and y == 0:
        return None
    return round(math.degrees(math.atan2(x, y)) % 360)


def condizione(nuvole, prob, mm, neve, temporale, visib, temp):
    """Il tempo di un'ora in parole chiave, dal consenso dei modelli."""
    if prob is not None and prob >= 0.5:
        if temporale >= 0.4:
            return "temporale"
        if (neve or 0) > 0 or (temp is not None and temp <= 0.5):
            return "neve"
        if (mm or 0) >= 4:
            return "pioggia-forte"
        if (mm or 0) >= 1:
            return "pioggia"
        return "pioggia-debole"
    if visib is not None and visib < 1000:
        return "nebbia"
    if prob is not None and prob >= 0.25:
        return "possibili-piogge"
    if nuvole is None:
        return "nuvoloso"
    if nuvole < 20:
        return "sereno"
    if nuvole < 50:
        return "poco-nuvoloso"
    if nuvole < 85:
        return "nuvoloso"
    return "coperto"


# ---------- Allerte ufficiali: bollettino della Protezione civile + Meteoalarm, confrontati ----------
# I 78 Comuni della provincia di Benevento (elenco ISTAT): servono a dire quali Comuni del Sannio stanno in ogni zona.
COMUNI_BN = ["Airola", "Amorosi", "Apice", "Apollosa", "Arpaia", "Arpaise", "Baselice", "Benevento", "Bonea", "Bucciano", "Buonalbergo", "Calvi", "Campolattaro", "Campoli del Monte Taburno", "Casalduni", "Castelfranco in Miscano", "Castelpagano", "Castelpoto", "Castelvenere", "Castelvetere in Val Fortore", "Cautano", "Ceppaloni", "Cerreto Sannita", "Circello", "Colle Sannita", "Cusano Mutri", "Dugenta", "Durazzano", "Faicchio", "Foglianise", "Foiano di Val Fortore", "Forchia", "Fragneto Monforte", "Fragneto l'Abate", "Frasso Telesino", "Ginestra degli Schiavoni", "Guardia Sanframondi", "Limatola", "Melizzano", "Moiano", "Molinara", "Montefalcone di Val Fortore", "Montesarchio", "Morcone", "Paduli", "Pago Veiano", "Pannarano", "Paolisi", "Paupisi", "Pesco Sannita", "Pietraroja", "Pietrelcina", "Ponte", "Pontelandolfo", "Puglianello", "Reino", "San Bartolomeo in Galdo", "San Giorgio La Molara", "San Giorgio del Sannio", "San Leucio del Sannio", "San Lorenzello", "San Lorenzo Maggiore", "San Lupo", "San Marco dei Cavoti", "San Martino Sannita", "San Nazzaro", "San Nicola Manfredi", "San Salvatore Telesino", "Sant'Agata de' Goti", "Sant'Angelo a Cupolo", "Sant'Arcangelo Trimonte", "Santa Croce del Sannio", "Sassinoro", "Solopaca", "Telese Terme", "Tocco Caudio", "Torrecuso", "Vitulano"]
DPC_REPO = "pcm-dpc/DPC-Bollettini-Criticita-Idrogeologica-Idraulica"
METEOALARM = "https://feeds.meteoalarm.org/feeds/meteoalarm-legacy-atom-italy"
LIV = {"verde": 0, "gialla": 1, "arancione": 2, "rossa": 3}
TIPI_MA = {"Rain": "pioggia", "Thunderstorm": "temporali", "Wind": "vento", "Snow/Ice": "neve e ghiaccio", "Snow": "neve",
           "Flooding": "alluvioni", "Fog": "nebbia", "High-Temperature": "caldo", "Low-Temperature": "freddo",
           "Forest-Fire": "incendi", "Coastal Event": "mareggiate", "Avalanches": "valanghe"}


def livello(testo):
    t = (testo or "").upper()
    return "rossa" if "ROSSA" in t else "arancione" if "ARANCIONE" in t else "gialla" if "GIALLA" in t else "verde"


def api_github(percorso):
    h = {"Accept": "application/vnd.github+json", "User-Agent": "notizie-benevento meteo"}
    if os.environ.get("GITHUB_TOKEN"):
        h["Authorization"] = "Bearer " + os.environ["GITHUB_TOKEN"]
    with urllib.request.urlopen(urllib.request.Request("https://api.github.com" + percorso, headers=h), timeout=40) as r:
        return json.load(r)


def bollettino_dpc():
    """L'ultimo bollettino di criticità della Protezione civile: livello per zona di allerta, oggi e domani."""
    sha = api_github(f"/repos/{DPC_REPO}/commits?path=files/topojson&per_page=1")[0]["sha"]
    nomi = [re.search(r"files/topojson/(\d{8}_\d{4})_", f["filename"]) for f in api_github(f"/repos/{DPC_REPO}/commits/{sha}")["files"]]
    nome = next(m.group(1) for m in nomi if m)
    meta = scarica(f"https://raw.githubusercontent.com/{DPC_REPO}/master/files/{nome}.json")
    giorno0 = dt.date(int(nome[:4]), int(nome[4:6]), int(nome[6:8]))
    out = {"nome": meta.get("name"), "pubblicato": meta.get("date"), "giorni": {}}
    for chiave, delta in (("today", 0), ("tomorrow", 1)):
        geom = list(scarica(meta[chiave]["topo_json"])["objects"].values())[0]["geometries"]
        zone = {}
        for g in geom:
            p = g.get("properties", {})
            comuni = [c for c in p.get("Comuni", []) if c in COMUNI_BN]
            if not comuni:
                continue
            zone[p.get("Nome zona")] = {
                "livello": livello(p.get("Rappresentata nella mappa")),
                "idrogeologico": livello(p.get("Per rischio idrogeologico")),
                "idraulico": livello(p.get("Per rischio idraulico")),
                "temporali": livello(p.get("Per rischio temporali")),
                "comuni": comuni,
            }
        if sum(len(z["comuni"]) for z in zone.values()) != len(COMUNI_BN):
            raise RuntimeError("nel bollettino non ci sono tutti i Comuni del Sannio")
        out["giorni"][(giorno0 + dt.timedelta(days=delta)).isoformat()] = zone
    return out


def ora_roma(iso_utc):
    t = dt.datetime.fromisoformat(iso_utc.replace("Z", "+00:00"))
    try:
        from zoneinfo import ZoneInfo
        return t.astimezone(ZoneInfo(FUSO)).isoformat(timespec="minutes")
    except Exception:
        return t.isoformat(timespec="minutes")


def meteoalarm_campania():
    """Le allerte di Meteoalarm per la Campania (valgono per tutta la regione, non per zona)."""
    req = urllib.request.Request(METEOALARM, headers={"User-Agent": "notizie-benevento meteo"})
    with urllib.request.urlopen(req, timeout=40) as r:
        xml = r.read().decode("utf-8", "ignore")
    out = []
    for e in re.findall(r"<entry>(.*?)</entry>", xml, re.S):
        if "<cap:areaDesc>Campania</cap:areaDesc>" not in e:
            continue
        g = lambda k: (re.search(rf"<cap:{k}>([^<]*)</cap:{k}>", e) or [None, ""])[1].strip()
        if g("message_type").lower() == "cancel" or g("status").lower() not in ("", "actual"):
            continue
        ev = g("event").split()
        if len(ev) < 2:
            continue
        lv = {"yellow": "gialla", "orange": "arancione", "red": "rossa"}.get(ev[0].lower())
        if not lv:
            continue
        tipo = " ".join(ev[1:]).replace(" Warning", "")
        w = {"livello": lv, "tipo": TIPI_MA.get(tipo, tipo.lower()), "inizio": ora_roma(g("onset") or g("effective")),
             "fine": ora_roma(g("expires"))}
        if w not in out:  # il feed ripete ogni allerta (una voce per lingua)
            out.append(w)
    return out


def allerte_ufficiali(oggi):
    """Bollettino e Meteoalarm, e per oggi e domani se le due fonti concordano."""
    errori, dpc, ma = [], None, None
    try:
        dpc = bollettino_dpc()
    except Exception as e:
        errori.append(f"bollettino Protezione civile non disponibile: {e}")
    try:
        ma = meteoalarm_campania()
    except Exception as e:
        errori.append(f"Meteoalarm non disponibile: {e}")
    giorni = {}
    for d in (oggi, oggi + dt.timedelta(days=1)):
        k = d.isoformat()
        zone = (dpc or {}).get("giorni", {}).get(k)
        del_giorno = [w for w in (ma or []) if w["inizio"][:10] <= k <= w["fine"][:10]]
        idro = max((LIV[w["livello"]] for w in del_giorno if w["tipo"] in ("pioggia", "temporali", "alluvioni")), default=0)
        dpc_max = max((LIV[z["livello"]] for z in zone.values()), default=0) if zone else None
        if dpc is None and ma is None:
            nota = "Fonti ufficiali non raggiungibili: controlla gli avvisi della Regione Campania."
        elif zone is None:
            nota = ("Il bollettino della Protezione civile per questo giorno non è ancora uscito (di solito esce verso le 15-16): "
                    "per ora c'è solo Meteoalarm, che vale per tutta la Campania.")
        elif ma is None:
            nota = "Meteoalarm non raggiungibile: c'è solo il bollettino della Protezione civile."
        elif idro > dpc_max:
            nota = ("Meteoalarm dà un livello più alto per la Campania: riguarda altre zone della regione. "
                    "Per il Sannio vale il bollettino.")
        elif idro < dpc_max:
            nota = "Il bollettino della Protezione civile è più grave di Meteoalarm: vale il bollettino."
        else:
            nota = "Il bollettino della Protezione civile e Meteoalarm concordano."
        giorni[k] = {"zone": zone, "meteoalarm": del_giorno, "nota": nota}
    return {"dpc_bollettino": (dpc or {}).get("nome"), "dpc_pubblicato": (dpc or {}).get("pubblicato"),
            "giorni": giorni, "errori": errori}


class Mancano(Exception):
    """Le previsioni non si possono fare (dati che non arrivano o non tornano)."""


def previsioni(luogo):
    """Le previsioni da 8 modelli per un punto (Benevento o un paese): il contenuto di meteo.json senza le allerte."""
    LUOGO = luogo   # noqa: N806 (il nome di prima: sotto si usa così)
    comune = {"latitude": LUOGO["lat"], "longitude": LUOGO["lon"], "timezone": FUSO, "forecast_days": GIORNI, "past_days": 1}

    m = scarica(url("https://api.open-meteo.com/v1/forecast", hourly=",".join(VAR_MODELLI),
                    models=",".join(x["id"] for x in MODELLI), **comune))
    b = scarica(url("https://api.open-meteo.com/v1/forecast", hourly="uv_index,visibility,is_day",
                    daily="sunrise,sunset,daylight_duration,uv_index_max", **comune))
    try:
        q = scarica(url("https://air-quality-api.open-meteo.com/v1/air-quality",
                        hourly="european_aqi,pm10,pm2_5,ozone,nitrogen_dioxide," + ",".join(POLLINI),
                        latitude=LUOGO["lat"], longitude=LUOGO["lon"], timezone=FUSO, forecast_days=5, past_days=1))
    except Exception as e:
        print("qualità dell'aria non disponibile:", e, file=sys.stderr)
        q = {"hourly": {"time": []}}

    ore = m["hourly"]["time"]
    n = len(ore)
    if n < 24 * GIORNI or b["hourly"]["time"] != ore:
        raise Mancano("le ore dei dati non tornano")

    def serie(var, mod):
        return m["hourly"].get(f"{var}_{mod}") or [None] * n

    attivi = [x for x in MODELLI if any(v is not None for v in serie("temperature_2m", x["id"]))]
    if len(attivi) < 4:
        raise Mancano(f"solo {len(attivi)} modelli con dati")
    ids = [x["id"] for x in attivi]

    o = {k: [] for k in ("temp", "perc", "pioggia", "prob", "neve", "nuvole", "vento", "dir", "raffiche", "umid",
                         "rugiada", "press", "uv", "visib", "giorno", "cond", "nmod")}
    for i in range(n):
        val = {var: [serie(var, mid)[i] for mid in ids] for var in VAR_MODELLI}
        presenti = [x for x in val["temperature_2m"] if x is not None]
        pioggie = [x for x in val["precipitation"] if x is not None]
        prob = round(sum(1 for x in pioggie if x >= PIOGGIA_ORA) / len(pioggie), 2) if pioggie else None
        codici = [x for x in val["weather_code"] if x is not None]
        temporale = sum(1 for c in codici if c >= 95) / len(codici) if codici else 0
        t = mediana(val["temperature_2m"])
        nuv = mediana(val["cloud_cover"])
        mm = mediana(val["precipitation"])
        neve = mediana(val["snowfall"])
        vis = b["hourly"]["visibility"][i]
        o["temp"].append(t)
        # percepita di ogni modello con la sua temperatura, umidità e vento, poi la mediana come per il resto
        o["perc"].append(mediana([percepita(a, b_, c) for a, b_, c in
                                  zip(val["temperature_2m"], val["relative_humidity_2m"], val["wind_speed_10m"])]))
        o["pioggia"].append(mm)
        o["prob"].append(prob)
        o["neve"].append(neve)
        o["nuvole"].append(None if nuv is None else round(nuv))
        o["vento"].append(mediana(val["wind_speed_10m"]))
        o["dir"].append(direzione_media(val["wind_direction_10m"], val["wind_speed_10m"]))
        o["raffiche"].append(mediana(val["wind_gusts_10m"]))
        o["umid"].append(None if mediana(val["relative_humidity_2m"]) is None else round(mediana(val["relative_humidity_2m"])))
        o["rugiada"].append(mediana(val["dew_point_2m"]))
        o["press"].append(None if mediana(val["pressure_msl"]) is None else round(mediana(val["pressure_msl"])))
        o["uv"].append(b["hourly"]["uv_index"][i])
        o["visib"].append(vis)
        o["giorno"].append(b["hourly"]["is_day"][i])
        o["cond"].append(condizione(nuv, prob, mm, neve, temporale, vis, t))
        o["nmod"].append(len(presenti))

    # Ogni modello per conto suo (temperatura e pioggia): per il confronto e per sommare la pioggia senza sottostimarla.
    o["temp_mod"] = {mid: serie("temperature_2m", mid) for mid in ids}
    o["pioggia_mod"] = {mid: serie("precipitation", mid) for mid in ids}

    # Aria e pollini (Copernicus): stesse ore, dove ci sono.
    qh = q["hourly"]
    pos = {t: k for k, t in enumerate(qh.get("time", []))}
    def dall_aria(var):
        v = qh.get(var) or []
        return [v[pos[t]] if t in pos and pos[t] < len(v) else None for t in ore]
    o["aqi"] = dall_aria("european_aqi")
    o["pm10"] = dall_aria("pm10")
    o["pm25"] = dall_aria("pm2_5")
    o["o3"] = dall_aria("ozone")
    o["no2"] = dall_aria("nitrogen_dioxide")
    o["pollini"] = {nome: dall_aria(var) for var, nome in POLLINI.items()}

    giorni = []
    date = sorted({t[:10] for t in ore})
    for gi, d in enumerate(date):
        idx = [i for i, t in enumerate(ore) if t[:10] == d]
        diurne = [i for i in idx if 7 <= int(ore[i][11:13]) <= 20]
        per_mod = {}
        for mid in ids:
            tt = [serie("temperature_2m", mid)[i] for i in idx]
            pp = [serie("precipitation", mid)[i] for i in idx]
            if sum(1 for x in tt if x is not None) < 20:
                continue
            per_mod[mid] = {"max": round(max(x for x in tt if x is not None), 1),
                            "min": round(min(x for x in tt if x is not None), 1),
                            "mm": round(sum(x for x in pp if x is not None), 1)}
        if not per_mod:
            continue
        massime = [v["max"] for v in per_mod.values()]
        piogge = [v["mm"] for v in per_mod.values()]
        prob = round(sum(1 for x in piogge if x >= PIOGGIA_GIORNO) / len(piogge), 2)
        scarto = round(max(massime) - min(massime), 1)
        # Accordo: quanto si discostano le massime e quanto sono divisi sulla pioggia.
        diviso = 0.3 <= prob <= 0.7
        accordo = "alto" if scarto <= 2.5 and not diviso else ("basso" if scarto > 5 or (diviso and scarto > 2.5) else "medio")
        # Con pochi modelli (giorni lontani) l'accordo non può essere «alto»: sarebbe una sicurezza finta.
        if len(per_mod) < 5 and accordo == "alto":
            accordo = "medio"
        cond_diurne = [o["cond"][i] for i in diurne]
        mm = round(statistics.median(piogge), 1)
        temp_ore = [o["temp"][i] for i in idx if o["temp"][i] is not None]
        if prob >= 0.5:
            temporale = sum(1 for c in cond_diurne if c == "temporale")
            neve = sum(1 for c in cond_diurne if c == "neve")
            cond = "temporale" if temporale >= 2 else ("neve" if neve >= 3 else ("pioggia-forte" if mm >= 15 else ("pioggia" if mm >= 3 else "pioggia-debole")))
        elif prob >= 0.25:
            cond = "possibili-piogge"
        else:
            nuv = [o["nuvole"][i] for i in diurne if o["nuvole"][i] is not None]
            media = sum(nuv) / len(nuv) if nuv else 50
            cond = "sereno" if media < 20 else "poco-nuvoloso" if media < 50 else "nuvoloso" if media < 85 else "coperto"
        bd = b["daily"]
        giorni.append({
            "data": d,
            "max": round(statistics.median(massime), 1), "min": round(statistics.median([v["min"] for v in per_mod.values()]), 1),
            "max_ore": max(temp_ore) if temp_ore else None, "min_ore": min(temp_ore) if temp_ore else None,
            "pioggia_mm": mm, "prob": prob, "cond": cond, "accordo": accordo, "scarto_max": scarto,
            "alba": bd["sunrise"][gi] if gi < len(bd["sunrise"]) else None,
            "tramonto": bd["sunset"][gi] if gi < len(bd["sunset"]) else None,
            "luce_sec": bd["daylight_duration"][gi] if gi < len(bd["daylight_duration"]) else None,
            "uv_max": bd["uv_index_max"][gi] if gi < len(bd["uv_index_max"]) else None,
            "modelli": per_mod,
        })

    if len(giorni) < GIORNI:
        raise Mancano(f"solo {len(giorni)} giorni")
    return {"aggiornato": adesso_roma().isoformat(timespec="minutes"), "luogo": LUOGO, "quota": m.get("elevation"),
            "modelli": attivi,
            "fonte": "Open-Meteo (CC BY 4.0) con i modelli dei servizi meteo nazionali; aria e pollini: Copernicus CAMS",
            "ore": {"t": ore, **o}, "giorni": giorni}


def adesso_roma():
    try:
        from zoneinfo import ZoneInfo
        return dt.datetime.now(ZoneInfo(FUSO))
    except Exception:
        return dt.datetime.now(dt.timezone.utc).astimezone()


def scrivi(percorso, dati):
    tmp = percorso + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(dati, f, ensure_ascii=False, separators=(",", ":"))
    os.replace(tmp, percorso)


def paesi(cartella, quanti, ogni_ore):
    """Il meteo dei paesi, la stessa pagina di Benevento (meteo.html?paese=…), voluta dal proprietario il 29 ott 2026
    («quando clicchi su previsioni del tempo si dovrebbe aprire la pagina meteo del paese», «paesi ogni 6 ore sì»):
    a ogni giro i `quanti` paesi più vecchi di `ogni_ore` ore (78 paesi ogni ora supererebbero il limite gratuito di
    Open-Meteo, 10.000 richieste al giorno). Un paese che non riesce resta com'era. Le allerte le legge la pagina da
    meteo.json (sono di tutto il Sannio e cambiano più spesso)."""
    with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "comuni_coordinate.json"), encoding="utf-8") as f:
        coord = json.load(f)
    os.makedirs(cartella, exist_ok=True)
    adesso = adesso_roma()
    eta = {}
    for k in coord:
        if k == "benevento":   # Benevento ha meteo.json
            continue
        p = os.path.join(cartella, k + ".json")
        if not os.path.exists(p):   # la cache della pubblicazione si è persa: quello già sul sito, senza chiedere a Open-Meteo
            try:
                req = urllib.request.Request(f"https://notiziebenevento.it/meteo-paesi/{k}.json",
                                             headers={"User-Agent": "notizie-benevento meteo (github.com/ernbale)"})
                with urllib.request.urlopen(req, timeout=20) as r:
                    dati = r.read()
                json.loads(dati)
                with open(p, "wb") as f:
                    f.write(dati)
            except Exception:
                pass
        try:
            with open(os.path.join(cartella, k + ".json"), encoding="utf-8") as f:
                eta[k] = dt.datetime.fromisoformat(json.load(f)["aggiornato"])
        except (OSError, ValueError, KeyError):
            eta[k] = None
    vecchi = sorted((k for k, t in eta.items() if t is None or adesso - t > dt.timedelta(hours=ogni_ore)),
                    key=lambda k: eta[k].timestamp() if eta[k] else 0)
    senza = sum(1 for t in eta.values() if t is None)
    if senza > 40:   # la prima volta (o il sito senza i file): tutti, una volta sola
        quanti = len(vecchi)
    fatti = []
    for k in vecchi[:quanti]:
        try:
            scrivi(os.path.join(cartella, k + ".json"),
                   previsioni({"nome": coord[k]["nome"], "lat": coord[k]["lat"], "lon": coord[k]["lon"]}))
            fatti.append(coord[k]["nome"])
        except Exception as e:
            print(f"AVVISO: meteo di {coord[k]['nome']} non aggiornato ({type(e).__name__}: {e})", file=sys.stderr)
    print(f"meteo dei paesi: aggiornati {len(fatti)} ({', '.join(fatti) or 'nessuno'}); da aggiornare ancora "
          f"{max(0, len(vecchi) - quanti)}; senza file prima del giro {senza}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--uscita", default=os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "meteo.json"))
    ap.add_argument("--paesi", metavar="CARTELLA", help="invece di Benevento, i paesi a turno (vedi paesi())")
    ap.add_argument("--quanti", type=int, default=13)
    ap.add_argument("--ogni-ore", type=int, default=6)
    a = ap.parse_args()
    if a.paesi:
        return paesi(a.paesi, a.quanti, a.ogni_ore)
    try:
        uscita = previsioni(LUOGO)
    except Mancano as e:
        print(f"ERRORE: {e}", file=sys.stderr)
        sys.exit(1)
    allerte = allerte_ufficiali(adesso_roma().date())
    for x in allerte["errori"]:
        print("AVVISO:", x, file=sys.stderr)
    uscita = {"aggiornato": uscita["aggiornato"], "allerte": allerte, **{k: v for k, v in uscita.items() if k != "aggiornato"}}
    scrivi(a.uscita, uscita)
    print(f"OK {a.uscita}: {len(uscita['modelli'])} modelli ({', '.join(x['nome'] for x in uscita['modelli'])}), "
          f"{len(uscita['ore']['t'])} ore, {len(uscita['giorni'])} giorni")


if __name__ == "__main__":
    main()
