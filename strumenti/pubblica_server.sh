#!/bin/bash
# Pubblica il sito dal server Aruba (dal 30 ott 2026, lui: «tutto su aruba poi github lo dismettiamo più avanti»).
# Fa gli stessi passi, nello stesso ordine, di .github/workflows/pubblica.yml: SE CAMBI UN PASSO LÌ, CAMBIALO ANCHE QUI.
#
#   pubblica_server.sh            pubblicazione vera: il sito va in /srv/notiziebenevento (lo serve Caddy). Tutto quello
#                                 che si vede fuori (social, foto fatte con l'IA, commit nel repository, avviso a Bing)
#                                 solo se esiste ~/sito-stato/ACCESO, cioè quando il sito vero è questo: si accende
#                                 quando su GitHub si spegne, mai tutti e due (doppioni, foto pagate due volte)
#   pubblica_server.sh --prova    tutto in ~/sito-prova-uscita: niente social, niente push nel repository, niente
#                                 IndexNow, niente statistiche (per confrontare le pagine con quelle di GitHub)
#
# Dove sta cosa:
#   ~/sito                  la copia del repository: a ogni pubblicazione torna uguale a origin/main (git reset e
#                           clean), tenendo solo quello che su GitHub sta nella cache (img/n, img/ig, meteo-paesi)
#   ~/sito-stato/social     cosa è già uscito sui social (su GitHub era la cache «social»)
#   ~/sito-stato/arrivi     carburanti, farmacie e contributi mandati da strumenti/carburanti.py, farmacie.py e
#                           contributi.py (su GitHub erano i campi della pubblicazione): si usano una volta sola
#   ~/.config/nb/segreti/   un file per segreto, col nome della variabile (FB_PAGE_TOKEN, TELEGRAM_TOKEN, …): su
#                           GitHub erano i «secrets»
# Una pubblicazione alla volta (come «concurrency: pages»): le altre aspettano il loro turno.
set -uo pipefail
PROVA=0
[ "${1:-}" = "--prova" ] && PROVA=1
SITO=$HOME/sito
STATO=$HOME/sito-stato
ACCESO=0
[ "$PROVA" = 0 ] && [ -f "$STATO/ACCESO" ] && ACCESO=1
if [ "$PROVA" = 1 ]; then USCITA=$HOME/sito-prova-uscita; else USCITA=/srv/notiziebenevento; fi
LIVE=https://notiziebenevento.it
CURL="curl -fsSL --max-time 30 --retry 4 --retry-all-errors --retry-delay 5"
# come la macchina di GitHub: ora UTC (i programmi fanno da sé l'ora italiana) e testo UTF-8
export TZ=UTC LANG=C.UTF-8 PATH="$HOME/venv-sito/bin:$PATH"
avviso() { echo "$(date -u '+%d/%m %H:%M:%S') AVVISO: $*"; }

exec 9>/tmp/nb_pubblica.lock
flock 9
INIZIO=$(date +%s)
INIZIO_ISO=$(date -Iseconds)
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT
mkdir -p "$STATO/social" "$STATO/arrivi" "$USCITA"

# i segreti (mai stampati); la chiave di GitHub è quella che usano già gli strumenti del server (github.conf)
for f in "$HOME"/.config/nb/segreti/*; do
  [ -f "$f" ] && export "$(basename "$f")=$(cat "$f")"
done
GH_TOKEN=$(python3 -c 'import json, os; print(json.load(open(os.path.expanduser("~/nb-fonti/github.conf")))["token"])') || GH_TOKEN=""
export GH_TOKEN GITHUB_TOKEN=$GH_TOKEN

cd "$SITO" || exit 1
git fetch -q origin main && git reset -q --hard origin/main || { avviso "repository non aggiornato"; exit 1; }
git clean -q -fdx -e /img/n/ -e /img/ig/ -e /meteo-paesi/
SHA=$(git rev-parse HEAD)
MESSAGGIO=$(git log -1 --format=%s)
echo "$(date -u '+%d/%m %H:%M:%S') pubblicazione $([ "$PROVA" = 1 ] && echo 'DI PROVA ')di ${SHA:0:7} «${MESSAGGIO:0:80}»"

# il file già pubblicato: quello servito da qui, se no quello online
pubblicato() { if [ -s "$USCITA/$1" ]; then cp "$USCITA/$1" "$2"; else $CURL "$LIVE/$1" -o "$2"; fi; }

# Nessuna notizia sparita
timeout 180 python3 strumenti/sparite.py $([ "$ACCESO" = 1 ] && echo --manda) || avviso "controllo delle notizie sparite non riuscito"

# Meteo da 8 modelli
if ! python3 strumenti/meteo.py; then
  echo "Meteo non aggiornato: tengo quello già pubblicato"
  pubblicato meteo.json meteo.json || echo "nessun meteo precedente"
fi

# Meteo dei paesi (a turno, ogni 6 ore)
timeout 360 python3 strumenti/meteo.py --paesi meteo-paesi --quanti 13 --ogni-ore 6 || avviso "meteo dei paesi non aggiornato"

# Meteo dei Comuni
if ! python3 strumenti/meteo_comuni.py --al-massimo-ogni 55; then
  avviso "meteo dei Comuni non aggiornato: tengo quello già pubblicato"
  pubblicato meteo-comuni.json meteo-comuni.json || echo "nessun meteo dei Comuni precedente"
fi

# Strade chiuse sulla mappa
timeout 180 python3 strumenti/strade_luoghi.py --al-massimo 15 --tempo 100 || true

# Prezzi dei carburanti (arrivati da strumenti/carburanti.py, o quelli già pubblicati)
if [ -s "$STATO/arrivi/carburanti.json" ] \
   && python3 -c "import json, sys; d = json.load(open(sys.argv[1])); assert len(d['impianti']) > 60 and d['classifiche']['benzina'] and d['estrazione']; print('carburanti: arrivati i prezzi del', d['estrazione'])" "$STATO/arrivi/carburanti.json"; then
  cp "$STATO/arrivi/carburanti.json" carburanti.json
  [ "$PROVA" = 0 ] && mv "$STATO/arrivi/carburanti.json" "$STATO/arrivi/carburanti.usato.json"
else
  pubblicato carburanti.json carburanti.json || echo "nessun prezzo pubblicato prima"
fi

# Turni delle farmacie (arrivati da strumenti/farmacie.py, o quelli già pubblicati)
if [ -s "$STATO/arrivi/farmacie.json" ] \
   && python3 -c "import json, sys; d = json.load(open(sys.argv[1])); assert d['diurno'] and d['notturno'] and d['firma']; print('farmacie: arrivati i turni', d['firma'], 'fino al', d['notturno'][-1]['al'])" "$STATO/arrivi/farmacie.json"; then
  cp "$STATO/arrivi/farmacie.json" farmacie.json
  [ "$PROVA" = 0 ] && mv "$STATO/arrivi/farmacie.json" "$STATO/arrivi/farmacie.usato.json"
else
  pubblicato farmacie.json farmacie.json || echo "nessun turno pubblicato prima"
fi

# Benevento Calcio (calendario, risultati e classifica di Serie B)
if ! python3 strumenti/calcio.py; then
  avviso "calcio non aggiornato: tengo quello già pubblicato"
  pubblicato calcio.json calcio.json || echo "nessun calcio pubblicato prima"
fi

# Contributi e bandi (catalogo arrivato da strumenti/contributi.py, più i contributi locali)
rm -f contributi-catalogo.json
if [ -s "$STATO/arrivi/contributi.json" ]; then
  cp "$STATO/arrivi/contributi.json" contributi-catalogo.json && echo "contributi: arrivato il catalogo"
  [ "$PROVA" = 0 ] && mv "$STATO/arrivi/contributi.json" "$STATO/arrivi/contributi.usato.json"
fi
pubblicato contributi.json contributi-prima.json || rm -f contributi-prima.json
if ! python3 strumenti/contributi.py --pubblica --catalogo contributi-catalogo.json --prima contributi-prima.json; then
  avviso "contributi non aggiornati: tengo quelli già pubblicati"
  [ -s contributi-prima.json ] && cp contributi-prima.json contributi.json
fi
rm -f contributi-catalogo.json contributi-prima.json

# Foto fatte con l'IA (curiosità): se il sito vero non è questo, solo --segna (niente foto nuove, niente commit)
if [ "$ACCESO" = 1 ]; then
  timeout 360 python3 strumenti/foto_ia.py --genera || avviso "foto IA non fatte: si riprova alla pubblicazione dopo"
fi
timeout 120 python3 strumenti/foto_ia.py --segna || avviso "foto IA non segnate"

# Pagine per Google (una per notizia), sitemap, feed e anteprime
pubblicato sitemap.xml "$TMP/sitemap-prima.xml" || true
if ! python3 strumenti/pagine.py --sitemap-prima "$TMP/sitemap-prima.xml" --indexnow "$TMP/indexnow.json"; then
  avviso "pagine non generate: il sito funziona lo stesso (404.html apre le notizie nella prima pagina)"
fi

# Statistiche private (cifrate con la parola d'ordine); per un comunicato del giro lampo si tengono quelle di meno di
# 20 minuti fa. Se il sito vero non è questo (o in prova) si prendono quelle online: rifarle vorrebbe dire leggere
# Meta, Cloudflare e Search Console due volte (e Meta frena chi chiede troppo).
if [ "$ACCESO" = 0 ]; then
  $CURL "$LIVE/statistiche/dati.json" -o statistiche/dati.json || true
else
  # il registro delle pubblicazioni del server (scritto più sotto): da lì la puntualità dei giri
  export CHIUSURE_STATO="$STATO/social/chiusure.json" PUBBLICAZIONI_SERVER="$STATO/pubblicazioni.jsonl"
  if ! { printf '%s\n' "$MESSAGGIO" | grep -q '^Comunicato delle ' && python3 strumenti/statistiche.py --tieni-pubblicate 20; }; then
    python3 strumenti/statistiche.py || avviso "statistiche non aggiornate (il sito si pubblica lo stesso)"
  fi
fi

# Togli i file interni
rm -f diario/quarantena.json

# il sito online: come l'artefatto di GitHub Pages (tutto tranne .git e .github), i file vecchi tolti alla fine
rsync -a --delete-delay --delay-updates --exclude=/.git --exclude=/.github "$SITO/" "$USCITA/"
echo "$(date -u '+%d/%m %H:%M:%S') sito $([ "$PROVA" = 1 ] && echo 'di prova ')in $USCITA ($(( $(date +%s) - INIZIO )) s)"
[ "$PROVA" = 1 ] && exit 0
echo "$SHA" > "$STATO/ultimo_sha"
# il registro delle pubblicazioni vere (statistiche: quanto ci mette un giro ad andare online), gli ultimi 5000
if [ "$ACCESO" = 1 ]; then
  python3 -c 'import json, sys; print(json.dumps({"inizio": sys.argv[1], "online": sys.argv[2], "sha": sys.argv[3], "titolo": sys.argv[4][:120]}, ensure_ascii=False))' \
    "$INIZIO_ISO" "$(date -Iseconds)" "$SHA" "$MESSAGGIO" >> "$STATO/pubblicazioni.jsonl"
  tail -n 5000 "$STATO/pubblicazioni.jsonl" > "$STATO/pubblicazioni.jsonl.tmp" && mv "$STATO/pubblicazioni.jsonl.tmp" "$STATO/pubblicazioni.jsonl"
fi

if [ "$ACCESO" = 0 ]; then
  echo "il sito vero lo fa ancora GitHub: niente social e niente avviso a Bing da qui"
  exit 0
fi

# Avvisa Bing delle pagine nuove (IndexNow)
[ -f "$TMP/indexnow.json" ] && { python3 strumenti/pagine.py --invia-indexnow "$TMP/indexnow.json" || avviso "IndexNow non ha risposto"; }
ROSSO=0 CHIUSURE=true CURIOSITA=true
# Chiusure dei Comuni sui social (a qualsiasi ora)
python3 strumenti/chiusure_social.py --stato "$STATO/social/chiusure.json" || { avviso "le chiusure dei Comuni non sono uscite su tutti i canali"; ROSSO=1; CHIUSURE=false; }
# Curiosità del Sannio (alle 12, su Telegram, Facebook e Instagram)
python3 strumenti/curiosita_social.py --stato "$STATO/social/curiosita.json" || { avviso "la curiosità del Sannio non è uscita su tutti i canali"; ROSSO=1; CURIOSITA=false; }
# l'esito per la sentinella (su GitHub era il lavoro in rosso): la prossima pubblicazione riprova da sola
printf '{"quando": "%s", "chiusure": %s, "curiosita": %s}\n' "$(date -Iseconds)" "$CHIUSURE" "$CURIOSITA" > "$STATO/ultimo_esito.json"
# Facebook (una notizia nuova sulla Pagina, se è il momento)
FB_SUBITO=0 python3 strumenti/facebook.py --stato "$STATO/social/facebook.json" || avviso "Facebook non ha pubblicato"
# Instagram (le stesse notizie di Facebook, subito dopo, e il riepilogo della sera)
python3 strumenti/instagram.py --stato "$STATO/social/instagram.json" || avviso "Instagram non ha pubblicato"
# Telegram (notizie nuove e aggiornamenti sul canale); gli arretrati se li ha chiesti la sentinella (canale muto)
TG_RECUPERA=0
[ -f "$STATO/telegram_recupera" ] && { rm -f "$STATO/telegram_recupera"; TG_RECUPERA=1; }
TG_SUBITO=0 TG_RECUPERA=$TG_RECUPERA python3 strumenti/telegram.py --stato "$STATO/social/telegram.json" || avviso "Telegram non ha pubblicato"
echo "$(date -u '+%d/%m %H:%M:%S') fine ($(( $(date +%s) - INIZIO )) s)"
exit $ROSSO
