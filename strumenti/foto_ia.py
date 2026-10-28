#!/usr/bin/env python3
"""Le foto fatte apposta con GPT Image: oggi solo per la curiosità del giorno.

Il 28 ott 2026 per qualche ora valeva per tutte le notizie e le storie senza foto; poi lui ha chiarito che era un
malinteso («intendevo solo la storia del giorno», «era stato un malinteso, per il momento bastano»): le 31 foto fatte
quel giorno restano (img/ia, --segna), ma le nuove si fanno solo per le curiosità. Le sue parole di allora:
«regola tutte foto, se non la trovi ne crei una perfetta cinematografica con gpt», «anche le altre storie se manca la foto e le future», «devono rappresentare bene la scena raccontata se create
con gpt», «devi aggiustare anche sui social». Prima si cerca una foto vera (locandina, foto inviate col comunicato),
poi un tema adatto di img/temi; se non c'è, la foto la faceva l'IA dalla scena che l'agente descriveva nel campo
"scena" (oggi questo vale solo per le curiosità: da_fare(..., notizie_e_storie=False)). Anche per la cronaca. Le persone nella foto sono inventate, quindi ci possono stare (lui, stesso giorno: «sono persone
inventate puoi mettere tutto»); mai una persona vera o famosa.

- `--genera`: fa le foto che mancano (notizie della prima pagina e approfondimenti con "scena", senza foto vera e senza
  tema), le salva in img/ia/<id>.jpg (1200 px) e img/ia/<id>-m.jpg (768 px) e le manda nel repository con un commit
  a parte, su una copia (worktree) di main: notizie.json non si tocca, lo scrivono i giri. Serve il segreto
  OPENAI_API_KEY di GitHub; senza, non fa niente. Al massimo MASSIMO_PER_GIRO foto a pubblicazione.
- anche la foto della curiosità del giorno (curiosita.json), quando su Commons non c'è quella del protagonista
  (CURIOSITA.md, «La foto»: "immagine" con "ia": true e "scena"): va in img/curiosita/<slug>.jpg (lui, 28 ott 2026,
  sulla curiosità uscita senza foto: «la storia che è uscita oggi non ha foto… se non la trovi ne crei una»).
- `--segna`: mette "foto_ia" ("img/ia/<id>") nelle notizie e negli approfondimenti che hanno la foto, nella copia che
  si pubblica (notizie.json e archivio): il sito e le schede dei social la mostrano.
Lo esegue la pubblicazione (pubblica.yml) prima delle pagine: così la scheda di Instagram e Facebook ha già la foto.
"""
import argparse
import base64
import datetime as dt
import glob
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request

RADICE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CART = os.path.join(RADICE, "img", "ia")
MODELLO, MISURA = "gpt-image-2.5-sunburst", "1536x1024"
QUALITA = {"notizia": "medium", "approfondimento": "high", "curiosita": "high"}   # storie e curiosità sono poche
MASSIMO_PER_GIRO = 8      # un errore non deve mai far partire centinaia di foto (e di spesa)
INSIEME = 4               # foto chieste nello stesso momento
# come img/temi (strumenti/foto_temi.py, «un pochino più cinematografiche», 27 ott 2026), ma la scena è quella della notizia
CORNICE = ("Photograph illustrating {cosa} for a local news website in southern Italy, province of Benevento "
           "(Sannio). The scene: {scena}. Cinematic realistic photo, like a still from an Italian film: soft directional "
           "light, natural but rich color grading, gentle film grain, shallow depth of field, 35mm lens. Believable and "
           "sober, no exaggerated colors, no lens flares. Any people are fictional, with natural believable faces: never "
           "a real or famous person. No gore, no blood. No text, no writing, no logos, no license plates.")
ID = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")


def ha_foto_vera(x):
    return bool(x.get("locandina") or x.get("foto_inviate"))


def ha_tema(x):
    return bool(x.get("immagine")) and x.get("categoria") != "cronaca"


def da_fare(d, oggi, curiosita=(), notizie_e_storie=False):
    """Le foto che mancano, come lavori {tipo, id, scena, base (il file senza .jpg)}: le curiosità; le storie e le notizie
    solo con notizie_e_storie (spento dal 28 ott 2026, lui: «era stato un malinteso, per il momento bastano»)."""
    out = []
    ieri = (oggi - dt.timedelta(days=1)).isoformat()
    for c in curiosita:   # solo da ieri in poi: quelle già uscite da giorni non si rifanno
        im = c.get("immagine") if isinstance(c.get("immagine"), dict) else {}
        if im.get("ia") and str(im.get("scena") or "").strip() and str(c.get("data") or "") >= ieri:
            out.append({"tipo": "curiosita", "id": str(c.get("slug") or ""), "scena": im["scena"],
                        "base": os.path.join(RADICE, "img", "curiosita", str(c.get("slug") or ""))})
    for ap in (d.get("approfondimenti", []) if notizie_e_storie else []):
        if not ap.get("archiviato") and not ha_foto_vera(ap) and str(ap.get("scena") or "").strip():
            out.append({"tipo": "approfondimento", "id": str(ap.get("id") or ""), "scena": ap["scena"],
                        "base": percorso(str(ap.get("id") or ""))})
    notizie = [n for n in (d.get("notizie", []) if notizie_e_storie else []) if not ha_foto_vera(n) and not ha_tema(n) and not n.get("diretta_calcio")
               and str(n.get("scena") or "").strip()]
    notizie.sort(key=lambda n: str(n.get("pubblicato") or ""), reverse=True)
    out += [{"tipo": "notizia", "id": str(n.get("id") or ""), "scena": n["scena"], "base": percorso(str(n.get("id") or ""))}
            for n in notizie]
    return [x for x in out if ID.match(x["id"]) and not os.path.exists(x["base"] + ".jpg")
            and not os.path.exists(x["base"] + ".no")]


def percorso(id_):
    return os.path.join(CART, id_)


def genera_una(chiave, x, tipo):
    """Il JPEG grande e quello medio della foto, o None se OpenAI la rifiuta (si segna, per non riprovarci ogni ora)."""
    from PIL import Image
    cosa = "a story about the history and folk traditions of Benevento" if tipo == "curiosita" else "a news story"
    prompt = CORNICE.format(cosa=cosa, scena=str(x["scena"]).strip().rstrip("."))
    corpo = json.dumps({"model": MODELLO, "prompt": prompt, "size": MISURA, "quality": QUALITA[tipo], "n": 1}).encode()
    req = urllib.request.Request("https://api.openai.com/v1/images/generations", data=corpo, method="POST",
                                 headers={"Authorization": f"Bearer {chiave}", "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=240) as r:
            dati = json.load(r)
    except urllib.error.HTTPError as e:
        testo = e.read().decode(errors="ignore")[:300]
        if e.code == 400 and re.search(r"safety|moderation|content_policy|rejected", testo, re.I):
            print(f"::warning::foto IA di {x['id']}: OpenAI rifiuta la scena ({testo[:160]}); la notizia resta senza")
            return None
        raise
    im = Image.open(io.BytesIO(base64.b64decode(dati["data"][0]["b64_json"]))).convert("RGB")
    g = im.resize((1200, round(im.height * 1200 / im.width)), Image.LANCZOS)
    m = im.resize((768, round(im.height * 768 / im.width)), Image.LANCZOS)
    out = []
    for img, suf, q in ((g, ".jpg", 80), (m, "-m.jpg", 78)):
        b = io.BytesIO()
        img.save(b, "JPEG", quality=q, optimize=True, progressive=True)
        out.append((suf, b.getvalue()))
    return out


def git(*a, cwd=RADICE, check=True):
    return subprocess.run(["git", *a], cwd=cwd, check=check, capture_output=True, text=True)


def manda(file_rel, ids):
    """Un commit con le foto nuove sopra l'ultimo main, su una copia a parte (worktree): la cartella della
    pubblicazione resta com'è. Solo file nuovi, quindi niente conflitti coi giri; se un giro spinge nel frattempo, si
    riprova."""
    msg = "Foto illustrative fatte con l'IA: " + ", ".join(ids)
    for prova in range(4):
        git("fetch", "-q", "origin", "main")
        wt = tempfile.mkdtemp(prefix="foto-ia-")
        git("worktree", "add", "-q", "--detach", wt, "origin/main")
        try:
            for f in file_rel:
                os.makedirs(os.path.dirname(os.path.join(wt, f)), exist_ok=True)
                shutil.copyfile(os.path.join(RADICE, f), os.path.join(wt, f))
            git("add", "--", *file_rel, cwd=wt)
            git("-c", "user.name=Claude", "-c", "user.email=noreply@anthropic.com", "commit", "-q", "-m",
                msg[:300], cwd=wt)
            if git("push", "-q", "origin", "HEAD:main", cwd=wt, check=False).returncode == 0:
                print(f"foto IA: {len(ids)} nel repository")
                return True
        finally:
            git("worktree", "remove", "--force", wt, check=False)
        time.sleep(5 * (prova + 1))
    print("::warning::foto IA: non riesco a mandarle nel repository (si pubblicano lo stesso, si rifanno al giro dopo)")
    return False


def genera(file_notizie, oggi):
    chiave = os.environ.get("OPENAI_API_KEY", "").strip()
    with open(file_notizie, encoding="utf-8") as f:
        d = json.load(f)
    try:
        with open(os.path.join(RADICE, "curiosita.json"), encoding="utf-8") as f:
            curiosita = json.load(f).get("curiosita") or []
    except (OSError, ValueError):
        curiosita = []
    lista = da_fare(d, oggi, curiosita)
    if not lista:
        print("foto IA: nessuna da fare")
        return
    if not chiave:
        print(f"::warning::foto IA: {len(lista)} da fare ma manca il segreto OPENAI_API_KEY: "
              + ", ".join(x["id"] for x in lista[:MASSIMO_PER_GIRO]))
        return
    os.makedirs(CART, exist_ok=True)
    nuovi, ids = [], []

    def una(x):
        try:
            return x, genera_una(chiave, x, x["tipo"])
        except Exception as e:   # un errore di rete o di credito non deve fermare la pubblicazione
            print(f"::warning::foto IA di {x['id']}: {type(e).__name__} {str(e)[:200]}")
            return x, False

    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(INSIEME) as ex:   # una foto ci mette 30-40 secondi: insieme, la pubblicazione non aspetta
        fatte = list(ex.map(una, lista[:MASSIMO_PER_GIRO]))
    for x, pezzi in fatte:
        if pezzi is False:
            continue
        if pezzi is None:
            p = x["base"] + ".no"
            open(p, "w").close()
            nuovi.append(os.path.relpath(p, RADICE))
            continue
        for suf, b in pezzi:
            if x["tipo"] == "curiosita" and suf != ".jpg":
                continue   # la curiosità ha un file solo (CURIOSITA.md: lato lungo al massimo 1200)
            with open(x["base"] + suf, "wb") as f:
                f.write(b)
            nuovi.append(os.path.relpath(x["base"] + suf, RADICE))
        ids.append(x["id"])
        print(f"foto IA: {x['tipo']} {x['id']} ({QUALITA[x['tipo']]})")
    if len(lista) > MASSIMO_PER_GIRO:
        print(f"foto IA: altre {len(lista) - MASSIMO_PER_GIRO} al prossimo giro")
    if nuovi:
        manda(nuovi, ids or ["(scene rifiutate)"])


def segna(file_notizie):
    """"foto_ia" in tutte le voci che hanno la foto (prima pagina e archivio), nella copia che si pubblica."""
    quante = 0
    mesi = [p for p in glob.glob(os.path.join(RADICE, "archivio", "*.json")) if re.match(r"^\d{4}-\d{2}\.json$", os.path.basename(p))]
    for p in [file_notizie] + sorted(mesi):
        try:
            with open(p, encoding="utf-8") as f:
                d = json.load(f)
        except (OSError, ValueError):
            continue
        if not isinstance(d, dict):
            continue
        cambiato = False
        voci = [x for k in ("notizie", "approfondimenti") if isinstance(d.get(k), list) for x in d[k]]
        for x in voci:
            if not isinstance(x, dict) or not ID.match(str(x.get("id", ""))):
                continue
            c = os.path.exists(percorso(x["id"]) + ".jpg") and os.path.exists(percorso(x["id"]) + "-m.jpg")
            if c and x.get("foto_ia") != "img/ia/" + x["id"]:
                x["foto_ia"] = "img/ia/" + x["id"]
                cambiato = True
                quante += 1
            elif not c and "foto_ia" in x:
                del x["foto_ia"]
                cambiato = True
        if cambiato:
            with open(p, "w", encoding="utf-8") as f:
                json.dump(d, f, ensure_ascii=False, indent=1)
    print(f"foto IA: segnate {quante}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--genera", action="store_true")
    ap.add_argument("--segna", action="store_true")
    ap.add_argument("--notizie", default=os.path.join(RADICE, "notizie.json"))
    a = ap.parse_args()
    from zoneinfo import ZoneInfo
    oggi = dt.datetime.now(ZoneInfo("Europe/Rome")).date()
    if a.genera:
        genera(a.notizie, oggi)
    if a.segna:
        segna(a.notizie)
    if not (a.genera or a.segna):
        ap.error("serve --genera e/o --segna")


if __name__ == "__main__":
    sys.exit(main())
