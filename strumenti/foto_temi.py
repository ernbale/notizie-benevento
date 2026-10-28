#!/usr/bin/env python3
"""Fa le versioni che mancano delle foto illustrative dei temi (img/temi/<tema>-<n>.jpg), così le notizie dello
stesso tema non mostrano sempre la stessa foto, sul sito e sui social.

Quante versioni (voluto dal proprietario il 22 ott 2026: «almeno 4 per ogni tema, quelle più frequenti anche di
più»; il 25 ott: «arriva a 12 € e fermati»): almeno MINIMO per ogni tema; FREQUENTI per i temi segnati «frequente»
in temi.json (quelli che ricorrono di più nei titoli dei giornali); IN_TESTA per i più usati (TESTA). Con --budget si
ferma prima di spendere di più: le foto si fanno a giri (prima una nuova per ogni tema, cominciando dai più usati,
poi la seconda…), così se il budget finisce prima tutti i temi ne hanno avute in proporzione.

Le versioni nuove sono la stessa scena del tema (o di una sua variante) con un'altra luce, un'altra stagione o
un'altra inquadratura: la frase è scritta in temi.json, nella lista «varianti» (variante i = file <tema>-<i+2>.jpg).
Le foto le fa OpenAI (gpt-image-2.5-sunburst, qualità media, 1536×1024, circa 1 centesimo l'una) con la chiave in
~/.config/openai/key, che non si stampa mai. Gira sul Mac, non su GitHub.

Uso:  python3 strumenti/foto_temi.py --scarta calcio-9 eolico-2   (una foto brutta: al suo posto va l'ultima del tema)
      python3 strumenti/foto_temi.py --prova      (dice quante foto farebbe e con quali frasi, senza spendere)
      python3 strumenti/foto_temi.py              (le fa, 6 alla volta, e aggiorna temi.json)
"""
import argparse
import base64
import io
import json
import os
import sys
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor

CART = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "img", "temi")
MINIMO, FREQUENTI, IN_TESTA = 9, 16, 24   # 27 ott 2026, lui: «crea altre varianti» (prima 9, 14, 20)
TESTA = ["teatro", "calcio", "lavori-stradali", "strada-chiusa", "treno", "scuola", "pioggia", "autobus", "ospedale",
         "rifiuti", "carburante", "camion"]
MODELLO, QUALITA, MISURA = "gpt-image-2.5-sunburst", "medium", "1536x1024"
# 27 ott 2026, lui: «se possibile foto un pochino più cinematografiche» (prima: «Realistic documentary photo, natural
# colors, 35mm lens»); restano foto vere e sobrie, niente colori finti
CORNICE = ("Editorial stock photograph for a local news website in southern Italy, province of Benevento (Sannio). "
           "{scena}. Cinematic realistic photo: soft directional light, natural but rich color grading, gentle film "
           "grain, shallow depth of field, 35mm lens, like a still from an Italian film. Believable and sober, no "
           "exaggerated colors, no lens flares. No people, no faces, no text, no logos, no license plates, no "
           "recognizable landmarks.")
# inquadratura (e luce) diverse: la stessa scena diventa un'altra foto; la sola luce non basta (22 ott: bottiglie quasi uguali)
MODI = ["a close-up detail of the main subject, shallow depth of field",
        "a wider view that shows more of the surroundings, on an overcast day",
        "seen from a different side and a higher angle, in soft morning light",
        "photographed from a low angle, at golden hour",
        "a different composition with the subject off-center, in winter under a grey sky",
        "a view from above, in bright daylight",
        "at dusk, seen from further away, with the first lights on",
        # 25 ott 2026: per raddoppiare servono più modi, se no la stessa scena torna con lo stesso modo
        "after the rain, with wet reflective surfaces, seen at eye level",
        "on a foggy early morning, with soft muted colors",
        "at night under warm street lights",
        "in summer at midday, with strong sunlight and hard shadows",
        "in spring, with fresh green around, photographed from a distance"]


def versioni(tema):
    v = [tema] if os.path.exists(os.path.join(CART, tema + ".jpg")) else []
    k = 2
    while os.path.exists(os.path.join(CART, f"{tema}-{k}.jpg")):
        v.append(f"{tema}-{k}")
        k += 1
    return v


def piano(temi):
    """(tema, numero del file, frase) per ogni foto che manca."""
    lavoro = []
    for tema, t in temi.items():
        if not os.path.exists(os.path.join(CART, tema + ".jpg")):   # tema nuovo: prima la sua foto (file <tema>.jpg)
            lavoro.append((-1, 0, tema, 1, t["foto"]))
            continue
        ce = len(versioni(tema))
        varianti = t.get("varianti") or []
        voglio = IN_TESTA if tema in TESTA else FREQUENTI if t.get("frequente") else MINIMO
        voglio = min(voglio, t.get("massimo", voglio))   # «massimo»: un tema di scorta (fast-food: lui, 28 ott 2026, «al massimo 4»)
        if ce >= voglio:
            continue
        # le scene vere (la foto e le varianti scritte a mano, non quelle già «rifatte» con un modo), ognuna con un modo
        # che non ha ancora: prima un modo per tutte le scene, poi il successivo, così le scene si alternano
        vere = [t["foto"]] + [v for v in varianti[:max(0, ce - 1)] if not any(m in v for m in MODI)]
        gia = {t["foto"]} | set(varianti)
        nuove = [f"{sc.rstrip('.')}, {m}" for m in MODI for sc in vere if f"{sc.rstrip('.')}, {m}" not in gia]
        peso = 0 if tema in TESTA else 1 if t.get("frequente") else 2
        for i in range(voglio - ce):
            lavoro.append((i, peso, tema, ce + i + 1, nuove[i % len(nuove)]))
    return [x[2:] for x in sorted(lavoro, key=lambda x: (x[0], x[1], x[2]))]


def genera(chiave, frase):
    corpo = json.dumps({"model": MODELLO, "prompt": CORNICE.format(scena=frase), "size": MISURA,
                        "quality": QUALITA, "n": 1}).encode()
    req = urllib.request.Request("https://api.openai.com/v1/images/generations", data=corpo,
                                 headers={"Authorization": f"Bearer {chiave}", "Content-Type": "application/json"})
    for prova in range(3):
        try:
            with urllib.request.urlopen(req, timeout=300) as r:
                d = json.load(r)
            return base64.b64decode(d["data"][0]["b64_json"]), d.get("usage", {})
        except urllib.error.HTTPError as e:
            msg = e.read().decode("utf-8", "replace")[:300]
            if e.code in (400, 401, 403) or prova == 2:
                raise RuntimeError(f"OpenAI {e.code}: {msg}") from None
        except (urllib.error.URLError, TimeoutError) as e:
            if prova == 2:
                raise RuntimeError(f"OpenAI non risponde: {e}") from None


def salva(dati, tema, numero):
    from PIL import Image
    im = Image.open(io.BytesIO(dati)).convert("RGB")
    nome = tema if numero == 1 else f"{tema}-{numero}"
    im.save(os.path.join(CART, nome + ".jpg"), "JPEG", quality=82, optimize=True, progressive=True)
    m = im.resize((768, round(im.height * 768 / im.width)))
    m.save(os.path.join(CART, nome + "-m.jpg"), "JPEG", quality=80, optimize=True, progressive=True)


def scarta(temi, nome):
    """Toglie una foto scartata dal proprietario: al suo posto va l'ultima versione del tema (file e frase in
    «varianti»), così i numeri restano senza buchi. Non tocca la prima foto del tema e non sposta un'ultima versione
    già usata da una notizia o da un evento (il suo file sparirebbe)."""
    import re
    m = re.fullmatch(r"(.+)-(\d+)", nome)
    if not m or m.group(1) not in temi or not os.path.exists(os.path.join(CART, nome + ".jpg")):
        raise SystemExit(f"{nome}: non è una versione di un tema (la prima foto del tema non si scarta così)")
    tema, n = m.group(1), int(m.group(2))
    v = versioni(tema)
    ultima = v[-1]
    radice = os.path.dirname(os.path.dirname(CART))
    usata = []
    for f in ["notizie.json", "eventi.json"] + [os.path.join("archivio", x) for x in os.listdir(os.path.join(radice, "archivio"))]:
        with open(os.path.join(radice, f), encoding="utf-8") as fh:
            if f'"foto": "{ultima}"' in fh.read():
                usata.append(f)
    if ultima != nome and usata:
        raise SystemExit(f"{nome}: l'ultima versione {ultima} è usata in {', '.join(usata)}: non la sposto")
    var = temi[tema].setdefault("varianti", [])
    for suf in (".jpg", "-m.jpg"):
        if ultima == nome:
            os.remove(os.path.join(CART, nome + suf))
        else:
            os.replace(os.path.join(CART, ultima + suf), os.path.join(CART, nome + suf))
    k = int(ultima.rsplit("-", 1)[1]) - 2
    if ultima != nome and k < len(var):
        var[n - 2] = var[k]
    del var[min(k, len(var) - 1):]
    print(f"{nome} scartata" + (f": al suo posto {ultima}" if ultima != nome else "") + f"; {tema} ha {len(v) - 1} foto")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--prova", action="store_true")
    ap.add_argument("--quante", type=int, default=0, help="al massimo queste (0 = tutte)")
    ap.add_argument("--budget", type=float, default=0, help="dollari al massimo (dal consumo vero di ogni foto)")
    ap.add_argument("--scarta", nargs="+", metavar="NOME", help="foto da togliere (es. calcio-9)")
    a = ap.parse_args()
    p_temi = os.path.join(CART, "temi.json")
    with open(p_temi, encoding="utf-8") as f:
        temi = json.load(f)
    if a.scarta:
        for nome in a.scarta:
            scarta(temi, nome)
        with open(p_temi, "w", encoding="utf-8") as f:
            json.dump(temi, f, ensure_ascii=False, indent=1)
            f.write("\n")
        return
    lavoro = piano(temi)
    if a.quante:
        lavoro = lavoro[:a.quante]
    print(f"Foto da fare: {len(lavoro)} (circa {len(lavoro) * 0.0105:.2f} $)"
          + (f"; budget {a.budget:.2f} $: circa {min(len(lavoro), int(a.budget / 0.0105))}" if a.budget else ""))
    if a.prova:
        for tema, numero, frase in lavoro[:12]:
            print(f"  {tema}-{numero}: {frase}")
        return
    with open(os.path.expanduser("~/.config/openai/key"), encoding="utf-8") as f:
        chiave = f.read().strip()

    def una(x):
        tema, numero, frase = x
        try:
            dati, uso = genera(chiave, frase)
            salva(dati, tema, numero)
            return tema, numero, frase, uso, None
        except Exception as e:
            return tema, numero, frase, {}, str(e)

    # il costo vero di ogni foto dal suo consumo (listino: testo in 5 $, uscita 30 $ per milione di token); finché non
    # se ne conosce nessuna si conta 0,0115 $ l'una (22 ott: 527 foto = 5,4 $, cioè 0,0102)
    fatte, errori, token, speso = [], [], 0, 0.0
    STIMA = 0.0115
    from concurrent.futures import FIRST_COMPLETED, wait
    coda, in_volo = list(lavoro), {}
    with ThreadPoolExecutor(6) as ex:
        while coda or in_volo:
            while coda and len(in_volo) < 6 and (not a.budget or speso + STIMA * (len(in_volo) + 1) <= a.budget):
                x = coda.pop(0)
                in_volo[ex.submit(una, x)] = x
            if not in_volo:
                print(f"Budget raggiunto: speso circa {speso:.2f} $ su {a.budget:.2f} $, restano {len(coda)} foto da fare")
                break
            finite, _ = wait(in_volo, return_when=FIRST_COMPLETED)
            for fu in finite:
                in_volo.pop(fu)
                tema, numero, frase, uso, err = fu.result()
                speso += uso.get("input_tokens", 0) * 5e-6 + uso.get("output_tokens", 0) * 30e-6 if uso else 0
                if err:
                    errori.append(f"{tema}-{numero}: {err}")
                    print(f"✗ {tema}-{numero}: {err}", flush=True)
                    if "insufficient_quota" in err or "billing" in err.lower() or "limit" in err.lower():
                        coda.clear()   # credito o tetto mensile finiti: inutile continuare
                else:
                    fatte.append((tema, numero, frase))
                    token += uso.get("output_tokens", 0)
                    print(f"✓ {tema}-{numero} ({len(fatte)}/{len(lavoro)}, speso circa {speso:.2f} $)", flush=True)
    # le frasi in temi.json, in ordine di file: varianti[i] è <tema>-<i+2>.jpg (solo se non ci sono buchi)
    for tema, numero, frase in sorted(fatte):
        v = temi[tema].setdefault("varianti", [])
        if len(v) == numero - 2:
            v.append(frase)
        elif len(v) < numero - 2:
            v.extend([""] * (numero - 2 - len(v)) + [frase])
    with open(p_temi, "w", encoding="utf-8") as f:
        json.dump(temi, f, ensure_ascii=False, indent=1)
        f.write("\n")
    print(f"Fatte {len(fatte)}, errori {len(errori)}; token di uscita {token}, speso circa {speso:.2f} $ "
          "(il conto vero è sul saldo OpenAI)")
    if errori:
        sys.exit(1)


if __name__ == "__main__":
    main()
