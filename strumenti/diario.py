#!/usr/bin/env python3
"""Il diario dell'agente: cosa ha fatto a ogni giro (fonti lette, notizie nuove e aggiornate, notizie scartate e perché,
dubbi). Lo mostra la pagina privata delle statistiche, nella scheda «Dietro le quinte».

Il repository è pubblico, il diario no: dentro ci sono anche fatti scartati perché non verificati. archivia.py --giro lo
cifra con la chiave pubblica qui accanto (diario_chiave_pubblica.json) e lo aggiunge a diario/AAAA-MM-GG.json; solo GitHub,
che ha la chiave privata nel segreto DIARIO_CHIAVE, lo decifra (statistiche.py) e lo mette nelle statistiche, cifrate
con la parola d'ordine. Per cifrare basta la libreria standard (nel cloud dell'agente non si installa niente): RSA-OAEP
con SHA-256 per la chiave del giro, SHA-256 a contatore e HMAC per il testo.
"""
import base64
import hashlib
import hmac
import json
import os
import secrets

CHIAVE_PUBBLICA = os.path.join(os.path.dirname(os.path.abspath(__file__)), "diario_chiave_pubblica.json")


def _mgf1(seme, lung):
    out, c = b"", 0
    while len(out) < lung:
        out += hashlib.sha256(seme + c.to_bytes(4, "big")).digest()
        c += 1
    return out[:lung]


def _oaep(msg, n, e):
    """RSA-OAEP con SHA-256 ed etichetta vuota (RFC 8017), come lo decifra la libreria cryptography."""
    k = (n.bit_length() + 7) // 8
    db = hashlib.sha256(b"").digest() + b"\x00" * (k - len(msg) - 66) + b"\x01" + msg
    seme = secrets.token_bytes(32)
    mdb = bytes(a ^ b for a, b in zip(db, _mgf1(seme, k - 33)))
    mseme = bytes(a ^ b for a, b in zip(seme, _mgf1(mdb, 32)))
    return pow(int.from_bytes(b"\x00" + mseme + mdb, "big"), e, n).to_bytes(k, "big")


def _flusso(chiave, nonce, dati):
    out = bytearray()
    for i in range(0, len(dati), 32):
        blocco = hashlib.sha256(chiave + nonce + (i // 32).to_bytes(8, "big")).digest()
        out += bytes(a ^ b for a, b in zip(dati[i:i + 32], blocco))
    return bytes(out)


def _mac(chiave, nonce, testo):
    return hmac.new(hashlib.sha256(b"mac" + chiave).digest(), nonce + testo, "sha256").digest()


def cifra(voce):
    with open(CHIAVE_PUBBLICA, encoding="utf-8") as f:
        pub = json.load(f)
    chiave, nonce = secrets.token_bytes(32), secrets.token_bytes(16)
    testo = _flusso(chiave, nonce, json.dumps(voce, ensure_ascii=False).encode())
    b64 = lambda x: base64.b64encode(x).decode()
    return {"chiave": b64(_oaep(chiave, int(pub["n"], 16), int(pub["e"], 16))), "nonce": b64(nonce),
            "testo": b64(testo), "mac": b64(_mac(chiave, nonce, testo))}


def decifra(busta, privata):
    """privata: la chiave RSA caricata con la libreria cryptography (dal segreto DIARIO_CHIAVE)."""
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import padding
    d = lambda k: base64.b64decode(busta[k])
    chiave = privata.decrypt(d("chiave"), padding.OAEP(mgf=padding.MGF1(hashes.SHA256()), algorithm=hashes.SHA256(),
                                                       label=None))
    nonce, testo = d("nonce"), d("testo")
    if not hmac.compare_digest(_mac(chiave, nonce, testo), d("mac")):
        raise ValueError("diario alterato")
    return json.loads(_flusso(chiave, nonce, testo))
