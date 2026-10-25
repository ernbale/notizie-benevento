#!/usr/bin/env python3
"""Le date ufficiali degli spettacoli che non sono ancora nel calendario degli eventi, per il giro dell'agente.

Voluto dal proprietario il 25 ott 2026 («si» a: «faccio leggere all'agente le stagioni di teatri e concerti, così
aggiunge gli spettacoli che mancano e poi tiene aggiornate le stagioni?»). Il Pi di casa legge ogni 30 minuti le
pagine ufficiali delle stagioni (Città Spettacolo, Accademia di Santa Sofia, Teatro San Marco, Solot, la biglietteria
Clappit: strumenti/fonti_casa.py, file stagioni.json dell'archivio delle fonti); qui le date da oggi in poi si
confrontano con eventi.json. Uno spettacolo c'è già se un evento dello stesso Comune, in quel giorno, ha almeno una
parola del titolo o del luogo in comune. Quelli che mancano si stampano; quelli che nel calendario non vanno (non sono
spettacoli, sono fuori tema, c'è già con un altro titolo) l'agente li scrive in eventi.json, nel campo
«stagioni_escluse» ({chiave: motivo}: il giro può cambiare solo notizie.json ed eventi.json), così non tornano a ogni
giro. Lo lancia anche giornali.py, in fondo al suo elenco. Solo libreria standard.

Uso:  python3 strumenti/stagioni.py [--fonti ../notizie-benevento-fonti/stagioni.json]
"""
import argparse
import datetime as dt
import json
import os
import re
import unicodedata

SITO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FONTI = os.path.join(os.path.dirname(SITO), "notizie-benevento-fonti", "stagioni.json")
VECCHIA = dt.timedelta(hours=3)
# parole che non distinguono uno spettacolo da un altro
VUOTE = set("""teatro teatrale comunale vittorio emmanuele emanuele benevento concerto orchestra accademia santa sofia
stagione spettacolo musical live sant auditorium della delle dello degli dalla nella sala piazza corso compagnia
company theatre presenta presentano tour con per """.split())


def parole(s):
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower()
    return {p for p in re.findall(r"[a-z0-9]+", s) if len(p) >= 4 and p not in VUOTE}


def giorni(e):
    if e.get("giorni"):
        return set(e["giorni"])
    a = dt.date.fromisoformat(e["inizio"])
    b = dt.date.fromisoformat(e.get("fine") or e["inizio"])
    return {(a + dt.timedelta(days=i)).isoformat() for i in range((b - a).days + 1)}


def chiave(v):
    return f"{v['link']}|{v['data']}"


def mancanti(fonti=FONTI, oggi=None):
    """(le voci senza evento, il file delle stagioni, le avvertenze)."""
    oggi = oggi or dt.date.today().isoformat()
    avvisi = []
    try:
        with open(fonti, encoding="utf-8") as f:
            st = json.load(f)
    except (OSError, ValueError) as e:
        return [], {}, [f"stagioni.json non si legge ({type(e).__name__}): niente confronto"]
    with open(os.path.join(SITO, "eventi.json"), encoding="utf-8") as f:
        ev = json.load(f)
    eventi, escluse = ev["eventi"], ev.get("stagioni_escluse") or {}
    controllato = st.get("controllato", "")
    try:
        if dt.datetime.now(dt.timezone.utc) - dt.datetime.fromisoformat(controllato) > VECCHIA:
            avvisi.append(f"la copia di casa è ferma dalle {controllato[11:16]} del {controllato[8:10]}/{controllato[5:7]}")
    except ValueError:
        avvisi.append("stagioni.json senza l'ora del controllo")
    for x in st.get("stagioni_non_lette") or []:
        avvisi.append(f"pagina non letta: {x}")
    per_giorno = {}
    for e in eventi:
        for g in giorni(e):
            per_giorno.setdefault((g, (e.get("comune") or "").lower()), []).append(
                (parole(e.get("titolo")) | parole(" ".join(e.get("artisti") or [])), parole(e.get("luogo"))))
    fuori = []
    for v in st.get("voci") or []:
        if v.get("data", "") < oggi or chiave(v) in escluse:
            continue
        pt, pl = parole(v.get("titolo")), parole(v.get("luogo"))
        if any(pt & t or pl & l for t, l in per_giorno.get((v["data"], (v.get("comune") or "").lower()), [])):
            continue
        fuori.append(v)
    fuori.sort(key=lambda v: (v["data"], v.get("ora", ""), v.get("fonte", "")))
    return fuori, st, avvisi


def riepilogo(fonti=FONTI):
    fuori, st, avvisi = mancanti(fonti)
    futuri = sum(v.get("data", "") >= dt.date.today().isoformat() for v in st.get("voci") or [])
    righe = [f"Stagioni di teatri e concerti (pagine ufficiali lette da casa, controllato "
             f"{st.get('controllato', '?')[11:16]}): {futuri} date da oggi in poi, {len(fuori)} senza evento in "
             "calendario" + (": aggiungile in eventi.json (le regole in AGENTE.md, «Le stagioni ufficiali»)" if fuori
                             else ".")]
    righe += [f"ATTENZIONE: {a}" for a in avvisi]
    for v in fuori:
        quando = v["data"] + (f" {v['ora']}" if v.get("ora") else f" ({v['orari']})" if v.get("orari") else "")
        righe.append(f"- {quando} · {v.get('comune', '')}, {v.get('luogo', '')} · {v.get('titolo', '')} · fonte: "
                     f"{v.get('fonte', '')}" + (f" · NOTA: {v['nota']}" if v.get("nota") else ""))
        righe.append(f"    {v.get('pagina') or v['link']}")
        righe.append(f"    chiave (per «stagioni_escluse» di eventi.json): {chiave(v)}")
    return "\n".join(righe)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--fonti", default=FONTI)
    print(riepilogo(ap.parse_args().fonti))


if __name__ == "__main__":
    main()
