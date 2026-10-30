#!/bin/bash
# Sul server Aruba (dal 30 ott 2026, lui: «sposta le dirette su aruba»): la diretta dei gol del Benevento
# (strumenti/gol.py) per la partita $1. La fa partire strumenti/gol_via.py (dal cron ogni 5 minuti) 20 minuti prima del
# calcio d'inizio, staccata, e la rilancia se si ferma: come faceva .github/workflows/gol.yml, che resta su GitHub per le
# prove a mano.
#   - gira da una copia sua del repository (~/gol-repo): per l'articolo di fine partita gol.py la riporta a origin/main,
#     e non deve toccare ~/sito mentre si pubblica
#   - le immagini nella cartella gol-immagini del sito servito: online subito (pubblica_server.sh non la tocca)
#   - cosa è già uscito in ~/sito-stato/gol/stato.json (su GitHub era la cache «gol-»)
#   - una diretta alla volta: il lucchetto /tmp/nb_gol_diretta.lock, che gol_via.py guarda per sapere se è in corso
#   - finita bene (riassunto finale uscito, o partita rinviata): ~/sito-stato/gol/<id>.finita, e gol_via.py non la rilancia
#
#   gol_server.sh ID            la diretta vera (solo se il sito vero è questo: ~/sito-stato/ACCESO)
#   gol_server.sh ID --prova    legge la partita e scrive immagini e testi in ~/prove/gol-ID, senza pubblicare niente
#   gol_server.sh ID --correggi USCITA [ID_NOTIZIA]   rifà un'uscita già mandata (finale, intervallo, gol:1…) e la
#                               cambia sui canali (su GitHub era il modo «correggi» della Action; lo stato è qui)
set -uo pipefail
ID=${1:?manca l id della partita ESPN}
export TZ=UTC LANG=C.UTF-8 PATH="$HOME/venv-sito/bin:$PATH"
STATO=$HOME/sito-stato/gol
REPO=$HOME/gol-repo
quando() { date -u '+%d/%m %H:%M:%S'; }
mkdir -p "$STATO"
exec 8>/tmp/nb_gol_diretta.lock
flock -n 8 || { echo "$(quando) diretta $ID: ne gira già una"; exit 0; }
git -C "$REPO" fetch -q origin main && git -C "$REPO" reset -q --hard origin/main || { echo "$(quando) diretta $ID: repository non aggiornato"; exit 1; }
CORREGGI=()
case "${2:-}" in
  --prova)    exec python3 "$REPO/strumenti/gol.py" --partita "$ID" --prova "$HOME/prove/gol-$ID" ;;
  --correggi) CORREGGI=(--correggi "${3:?manca l uscita da correggere}" --articolo "${4:-}") ;;
esac
[ -f "$HOME/sito-stato/ACCESO" ] || { echo "$(quando) diretta $ID: il sito vero non è questo, niente diretta da qui"; exit 0; }
for s in TELEGRAM_TOKEN FB_PAGE_TOKEN; do
  export "$s=$(cat "$HOME/.config/nb/segreti/$s")"
done
export GOL_CARTELLA_SITO=/srv/notiziebenevento
# l'articolo di fine partita si firma come gli altri commit (mai il nome del proprietario)
export GIT_AUTHOR_NAME=Claude GIT_AUTHOR_EMAIL=noreply@anthropic.com GIT_COMMITTER_NAME=Claude GIT_COMMITTER_EMAIL=noreply@anthropic.com
echo "$(quando) diretta $ID: parte ${CORREGGI[*]}"
python3 "$REPO/strumenti/gol.py" --partita "$ID" --stato "$STATO/stato.json" "${CORREGGI[@]}"
esito=$?
echo "$(quando) diretta $ID: finita (uscita $esito)"
[ "$esito" = 0 ] && [ ${#CORREGGI[@]} = 0 ] && touch "$STATO/$ID.finita"
exit $esito
