#!/usr/bin/env python3
"""Fa la chiave della Pagina Facebook che non scade e la mette nel segreto FB_PAGE_TOKEN di GitHub.

Si lancia una volta sola, dal Terminale del Mac (serve `gh` collegato a GitHub):

    python3 ~/notizie-benevento/strumenti/facebook_chiave.py

Chiede l'ID dell'app, la sua chiave segreta e il token utente del Graph API Explorer (con i permessi
pages_show_list, pages_read_engagement, pages_manage_posts, read_insights e pages_read_user_content: gli ultimi
due servono alle statistiche, chi vede i post e i commenti; per Instagram anche instagram_basic e
instagram_content_publish). Poi:
  token utente breve → token utente lungo (60 giorni) → token della Pagina, che da un token lungo non scade
  → controlla nome della Pagina, permessi e scadenza → lo salva in GitHub.
Le chiavi non si vedono mentre si incollano e non si stampano mai: a schermo solo gli esiti.
Da rifare solo se Facebook la invalida (per esempio se cambi la password di Facebook).
"""
import getpass
import json
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request

GRAPH = "https://graph.facebook.com"
PAGINA = "Notizie Benevento"
REPO = "ernbale/notizie-benevento"
PERMESSI = {"pages_show_list", "pages_read_engagement", "pages_manage_posts", "read_insights",
            "pages_read_user_content"}
INSTAGRAM = {"instagram_basic", "instagram_content_publish"}   # per strumenti/instagram.py (facoltativi)


def get(percorso, **par):
    url = f"{GRAPH}/{percorso}?{urllib.parse.urlencode(par)}"
    try:
        with urllib.request.urlopen(url, timeout=30) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        try:
            msg = json.load(e).get("error", {}).get("message", "")
        except ValueError:
            msg = ""
        sys.exit(f"\nFacebook ha risposto con un errore {e.code}: {msg}")


def main():
    print("Chiave della Pagina Facebook → segreto FB_PAGE_TOKEN di GitHub\n")
    app_id = input("1) ID dell'app (numero in alto nella dashboard dell'app): ").strip()
    segreto = getpass.getpass("2) Chiave segreta dell'app (non si vede mentre la incolli): ").strip()
    breve = getpass.getpass("3) Token utente del Graph API Explorer (non si vede): ").strip()
    if not (app_id.isdigit() and segreto and breve):
        sys.exit("Manca qualcosa: rilancia e incolla tutti e tre.")

    lungo = get("oauth/access_token", grant_type="fb_exchange_token", client_id=app_id,
                client_secret=segreto, fb_exchange_token=breve).get("access_token")
    if not lungo:
        sys.exit("Facebook non ha allungato il token utente.")
    print("✓ token utente allungato")

    pagine = get("me/accounts", fields="id,name,access_token", access_token=lungo).get("data", [])
    pag = next((p for p in pagine if p.get("name") == PAGINA), None)
    if not pag:
        sys.exit(f"La Pagina «{PAGINA}» non è nell'elenco: nel Graph API Explorer va scelta e autorizzata.")
    token = pag["access_token"]

    info = get("debug_token", input_token=token, access_token=f"{app_id}|{segreto}").get("data", {})
    mancano = PERMESSI - set(info.get("scopes", []))
    if mancano:
        sys.exit("Al token mancano questi permessi: " + ", ".join(sorted(mancano)) + ". Rifai il token nel Graph API Explorer.")
    scade = info.get("expires_at", 1)
    print(f"✓ token della Pagina «{pag['name']}», permessi a posto, scadenza: "
          + ("mai" if scade == 0 else "ATTENZIONE, scade"))
    if INSTAGRAM <= set(info.get("scopes", [])):
        ig = get(pag["id"] if "id" in pag else "me", fields="instagram_business_account{username}",
                 access_token=token).get("instagram_business_account")
        print(f"✓ Instagram: account @{ig['username']} collegato alla Pagina" if ig else
              "✗ Instagram: permessi a posto, ma alla Pagina non è collegato nessun account Instagram professionale")
    else:
        print("- Instagram: permessi non chiesti (" + ", ".join(sorted(INSTAGRAM)) + "): su Instagram non si pubblica")
    if scade != 0:
        sys.exit("Il token scade: qualcosa non è andato, non lo salvo.")

    r = subprocess.run(["gh", "secret", "set", "FB_PAGE_TOKEN", "-R", REPO], input=token, text=True,
                       capture_output=True)
    if r.returncode:
        sys.exit("GitHub non ha salvato il segreto: " + (r.stderr or "").strip())
    print(f"✓ salvato nel segreto FB_PAGE_TOKEN di {REPO}")
    print("\nFatto. Dal prossimo aggiornamento del sito (entro un'ora) parte la prima notizia sulla Pagina.")


if __name__ == "__main__":
    main()
