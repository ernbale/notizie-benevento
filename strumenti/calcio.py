#!/usr/bin/env python3
"""Il Benevento Calcio per il sito: calendario, risultati, classifica della Serie B e la giornata in corso, in
calcio.json. Lo usano la pagina calcio/ (strumenti/pagine.py) e il riquadro in prima pagina; durante le partite la
diretta la legge poi la pagina stessa, ogni 15 secondi, dalla stessa fonte.

Fonte: i dati pubblici di ESPN (site.api.espn.com: gratuiti, senza chiave, non ufficiali; scelta del proprietario,
24 ott 2026). Confrontati con Google il 24 ott 2026 (Arezzo-Benevento 0-3 e classifica): identici.
- Le partite di tutte e 20 le squadre (calendario e risultati di ognuna): la classifica la calcoliamo noi dai risultati,
  così in diretta si aggiunge la partita in corso senza contarla due volte. Si confronta con quella di ESPN: se non
  coincide (una partita a tavolino, una penalizzazione) vale quella di ESPN e lo si scrive.
- La giornata: le partite giocate tra la partita del Benevento di prima e quella dopo (ogni squadra una volta); se la
  giornata dell'ultima partita del Benevento non è finita (gli altri giocano la domenica) si mostra quella.
- I loghi delle squadre, piccoli, in img/calcio/<id>.png: si scaricano solo quelli che mancano.

Uso:  python3 strumenti/calcio.py [--sito .]
"""
import argparse
import datetime as dt
import io
import json
import os
import sys
import time
import urllib.request

ESPN = "https://site.api.espn.com/apis/site/v2/sports/soccer/ita.2"
CLASSIFICA = "https://site.api.espn.com/apis/v2/sports/soccer/ita.2/standings"
BENEVENTO = "4059"
CAMPIONATO = "Serie B"
LOGO_PX = 96
# i nomi come li scrivono i giornali italiani (ESPN ne scrive alcuni all'inglese)
NOMI = {"Hellas Verona": "Verona", "US Avellino": "Avellino", "Sudtirol": "Südtirol"}


def fuso():
    try:
        from zoneinfo import ZoneInfo
        return ZoneInfo("Europe/Rome")
    except Exception:
        return dt.timezone(dt.timedelta(hours=1))


def leggi(url):
    for attesa in (3, 10, None):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "notiziebenevento.it"})
            with urllib.request.urlopen(req, timeout=20) as r:
                return json.load(r)
        except Exception as e:
            if attesa is None:
                raise RuntimeError(f"{url.split('/ita.2')[-1]}: {e}") from None
            time.sleep(attesa)


def gol(x):
    s = x.get("score")
    s = s.get("displayValue") if isinstance(s, dict) else s
    return int(s) if str(s or "").isdigit() else None


def partita(e):
    """Una partita come serve al sito. stato: pre (da giocare), in (in corso), post (finita), rinviata."""
    c = e["competitions"][0]
    casa = next(x for x in c["competitors"] if x["homeAway"] == "home")
    fuori = next(x for x in c["competitors"] if x["homeAway"] == "away")
    st = c.get("status") or e.get("status") or {}
    tipo = st.get("type") or {}
    nome = tipo.get("name", "")
    stato = ("rinviata" if nome in ("STATUS_POSTPONED", "STATUS_CANCELED", "STATUS_ABANDONED", "STATUS_SUSPENDED")
             else tipo.get("state") or "pre")
    quando = dt.datetime.fromisoformat(e["date"].replace("Z", "+00:00")).astimezone(fuso())
    p = {"id": e["id"], "quando": quando.isoformat(timespec="minutes"),
         "ora_certa": bool(e.get("timeValid", True)) and "TBD" not in tipo.get("shortDetail", ""),
         "casa": casa["team"]["id"], "fuori": fuori["team"]["id"], "stato": stato}
    if stato in ("in", "post"):
        p["gol_casa"], p["gol_fuori"] = gol(casa), gol(fuori)
    if stato == "in":
        p["minuto"] = st.get("displayClock") or tipo.get("shortDetail")
    stadio = (c.get("venue") or {}).get("fullName")
    if stadio:
        p["stadio"] = stadio
    return p


def tutte_le_partite(ids):
    """Le partite della stagione di tutte le squadre (risultati e calendario), senza doppioni."""
    out = {}
    for i in ids:
        for q in ("", "?fixture=true"):
            for e in leggi(f"{ESPN}/teams/{i}/schedule{q}").get("events", []):
                if (e.get("seasonType") or {}).get("name", "Regular Season") != "Regular Season":
                    continue
                p = partita(e)
                vecchia = out.get(p["id"])
                # la stessa partita vista da due squadre (o nei due elenchi): vale la più aggiornata
                ordine = {"pre": 0, "rinviata": 0, "in": 1, "post": 2}
                if not vecchia or ordine[p["stato"]] >= ordine[vecchia["stato"]]:
                    out[p["id"]] = p
    # le partite di oggi: il tabellone è il più aggiornato (il calendario di una squadra arriva in ritardo)
    for e in leggi(f"{ESPN}/scoreboard").get("events", []):
        p = partita(e)
        out[p["id"]] = p
    return sorted(out.values(), key=lambda p: (p["quando"], p["id"]))


def calcola_classifica(partite):
    t = {}
    for p in partite:
        if p["stato"] != "post" or p.get("gol_casa") is None:
            continue
        for sq, f, s in ((p["casa"], p["gol_casa"], p["gol_fuori"]), (p["fuori"], p["gol_fuori"], p["gol_casa"])):
            r = t.setdefault(sq, {"id": sq, "pg": 0, "v": 0, "n": 0, "p": 0, "gf": 0, "gs": 0, "pt": 0})
            r["pg"] += 1
            r["gf"] += f
            r["gs"] += s
            k = "v" if f > s else "n" if f == s else "p"
            r[k] += 1
            r["pt"] += {"v": 3, "n": 1, "p": 0}[k]
    return t


def classifica_espn():
    d = leggi(CLASSIFICA)
    righe = []
    for x in d["children"][0]["standings"]["entries"]:
        s = {k["name"]: k.get("value") for k in x["stats"]}
        righe.append({"id": x["team"]["id"], "pos": int(s.get("rank") or 0), "pg": int(s.get("gamesPlayed") or 0),
                      "v": int(s.get("wins") or 0), "n": int(s.get("ties") or 0), "p": int(s.get("losses") or 0),
                      "gf": int(s.get("pointsFor") or 0), "gs": int(s.get("pointsAgainst") or 0),
                      "pt": int(s.get("points") or 0)})
    return sorted(righe, key=lambda r: r["pos"])


def giornate(partite):
    """Il numero della giornata di ogni partita del Benevento (la n-esima della stagione) e le partite di ogni
    giornata: quelle tra la partita del Benevento di prima e quella dopo, a metà strada, una per squadra."""
    nostre = [p for p in partite if BENEVENTO in (p["casa"], p["fuori"])]
    t = [dt.datetime.fromisoformat(p["quando"]) for p in nostre]
    out = []
    for i, p in enumerate(nostre):
        da = t[i] - ((t[i] - t[i - 1]) / 2 if i else dt.timedelta(days=3))
        a = t[i] + ((t[i + 1] - t[i]) / 2 if i + 1 < len(t) else dt.timedelta(days=3))
        tutte, viste = [], set()
        for q in sorted(partite, key=lambda q: abs(dt.datetime.fromisoformat(q["quando"]) - t[i])):
            if da <= dt.datetime.fromisoformat(q["quando"]) < a and not {q["casa"], q["fuori"]} & viste:
                tutte.append(q)
                viste |= {q["casa"], q["fuori"]}
        out.append({"numero": i + 1, "benevento": p["id"], "partite": sorted(tutte, key=lambda q: (q["quando"], q["id"]))})
    return out


def logo(sito, sq):
    """img/calcio/<id>.png, piccolo; si scarica solo se manca."""
    rel = f"img/calcio/{sq['id']}.png"
    path = os.path.join(sito, rel)
    if os.path.exists(path):
        return "/" + rel
    url = next((l["href"] for l in sq.get("logos", []) if l.get("href")), None)
    if not url:
        return None
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "notiziebenevento.it"}),
                                    timeout=20) as r:
            dati = r.read()
        os.makedirs(os.path.dirname(path), exist_ok=True)
        try:
            from PIL import Image
            im = Image.open(io.BytesIO(dati)).convert("RGBA")
            im.thumbnail((LOGO_PX, LOGO_PX), Image.LANCZOS)
            im.save(path, "PNG", optimize=True)
        except ImportError:
            with open(path, "wb") as f:
                f.write(dati)
        return "/" + rel
    except Exception as e:
        print(f"calcio: logo di {sq.get('displayName')} non scaricato ({e})", file=sys.stderr)
        return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sito", default=os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    a = ap.parse_args()
    adesso = dt.datetime.now(fuso())

    elenco = [t["team"] for t in leggi(f"{ESPN}/teams")["sports"][0]["leagues"][0]["teams"]]
    squadre = {}
    for t in elenco:
        nome = NOMI.get(t["displayName"], t["displayName"])
        squadre[t["id"]] = {"nome": nome, "sigla": t.get("abbreviation") or nome[:3].upper(), "logo": logo(a.sito, t)}
    if BENEVENTO not in squadre:
        raise RuntimeError("il Benevento non è tra le squadre della Serie B di ESPN: campionato cambiato?")

    partite = tutte_le_partite(squadre)
    nostra = calcola_classifica(partite)
    espn = classifica_espn()
    campi = ("pg", "v", "n", "p", "gf", "gs")
    diverse = [r["id"] for r in espn if {k: nostra.get(r["id"], {}).get(k) for k in campi} != {k: r[k] for k in campi}]
    # stesse partite ma punti diversi: una penalizzazione (Juve Stabia -4 nel 2026-27), che resta anche in diretta
    for r in espn:
        n = nostra.get(r["id"])
        if n and r["id"] not in diverse and n["pt"] != r["pt"]:
            n["penalita"] = n["pt"] - r["pt"]
            n["pt"] = r["pt"]
    # in classifica: le partite finite che la classifica qui sotto conta già; in diretta la pagina aggiunge le altre
    if diverse:
        print("calcio: la classifica calcolata non coincide con ESPN per "
              + ", ".join(squadre.get(i, {}).get("nome", i) for i in diverse) + ": uso quella di ESPN", file=sys.stderr)
        classifica = [dict(r) for r in espn]
        contate = None   # non so quali partite conta ESPN: in diretta la classifica non si muove
    else:
        classifica = [dict(nostra[r["id"]], pos=r["pos"]) for r in espn]   # l'ordine (anche a pari punti) è di ESPN
        contate = {p["id"] for p in partite if p["stato"] == "post"}

    gg = giornate(partite)
    nostre = [p for p in partite if BENEVENTO in (p["casa"], p["fuori"])]
    # la giornata da mostrare: quella dell'ultima partita del Benevento se non è finita per tutti, se no la prossima
    ultima = max((i for i, p in enumerate(nostre) if p["stato"] in ("in", "post")), default=-1)
    i = ultima if ultima >= 0 and any(q["stato"] in ("pre", "in") for q in gg[ultima]["partite"]) else ultima + 1
    i = min(max(i, 0), len(gg) - 1)
    giornata = gg[i]
    for q in giornata["partite"]:
        q["in_classifica"] = contate is not None and q["id"] in contate

    dati = {
        "aggiornato": adesso.isoformat(timespec="minutes"),
        "fonte": "ESPN",
        "campionato": CAMPIONATO,
        "benevento": BENEVENTO,
        "squadre": squadre,
        "classifica": classifica,
        "classifica_nostra": contate is not None,
        "partite": [dict(p, giornata=n + 1) for n, p in enumerate(nostre)],
        "giornata": giornata,
    }
    with open(os.path.join(a.sito, "calcio.json"), "w", encoding="utf-8") as f:
        json.dump(dati, f, ensure_ascii=False, separators=(",", ":"))
    prossima = next((p for p in nostre if p["stato"] == "pre"), None)
    pos = next((r["pos"] for r in classifica if r["id"] == BENEVENTO), "?")
    print(f"calcio: {len(partite)} partite, Benevento {pos}°, giornata {giornata['numero']} "
          f"({len(giornata['partite'])} partite)" + (f", prossima {prossima['quando'][:16]}" if prossima else "")
          + ("" if contate is not None else " · classifica di ESPN"))


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print("AVVISO calcio:", e, file=sys.stderr)
        sys.exit(1)
