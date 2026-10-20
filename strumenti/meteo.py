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
VAR_MODELLI = ["temperature_2m", "apparent_temperature", "precipitation", "snowfall", "weather_code", "cloud_cover",
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


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--uscita", default=os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "meteo.json"))
    a = ap.parse_args()
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
        print("ERRORE: le ore dei dati non tornano", file=sys.stderr)
        sys.exit(1)

    def serie(var, mod):
        return m["hourly"].get(f"{var}_{mod}") or [None] * n

    attivi = [x for x in MODELLI if any(v is not None for v in serie("temperature_2m", x["id"]))]
    if len(attivi) < 4:
        print(f"ERRORE: solo {len(attivi)} modelli con dati", file=sys.stderr)
        sys.exit(1)
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
        o["perc"].append(mediana(val["apparent_temperature"]))
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

    adesso = dt.datetime.now(dt.timezone.utc).astimezone()
    try:
        from zoneinfo import ZoneInfo
        adesso = dt.datetime.now(ZoneInfo(FUSO))
    except Exception:
        pass
    uscita = {
        "aggiornato": adesso.isoformat(timespec="minutes"),
        "luogo": LUOGO, "quota": m.get("elevation"),
        "modelli": attivi,
        "fonte": "Open-Meteo (CC BY 4.0) con i modelli dei servizi meteo nazionali; aria e pollini: Copernicus CAMS",
        "ore": {"t": ore, **o},
        "giorni": giorni,
    }
    if len(giorni) < GIORNI:
        print(f"ERRORE: solo {len(giorni)} giorni", file=sys.stderr)
        sys.exit(1)
    tmp = a.uscita + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(uscita, f, ensure_ascii=False, separators=(",", ":"))
    os.replace(tmp, a.uscita)
    print(f"OK {a.uscita}: {len(attivi)} modelli ({', '.join(x['nome'] for x in attivi)}), {n} ore, {len(giorni)} giorni")


if __name__ == "__main__":
    main()
