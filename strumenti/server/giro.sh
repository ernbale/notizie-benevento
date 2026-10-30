#!/bin/bash
# Un giro di Notizie Benevento sul server Aruba (dal 30 ott 2026), al posto delle routine nel cloud di Claude, che
# partivano anche 23 minuti dopo l'ora (lui: «il giro se possibile a ora precisa»). Stesse istruzioni, stesso modello,
# stessi strumenti della routine; cambia solo dove gira.
#
# Lo lancia systemd (nb-giro@<tipo>-<id>.service, utente redazione, /tmp privata), che a sua volta lo fa partire
# /usr/local/bin/nb-giro <tipo> [testo] (dal cron per gli orari fissi, dagli strumenti del server per il giro lampo).
# L'utente redazione non legge niente di ernesto (posta, social, chiavi): i giri leggono pagine di chiunque, e un testo
# scritto apposta non deve poter arrivare alle chiavi.
#
# Ogni giro ha la sua copia del sito e delle fonti (git worktree, ~7 s), come nel cloud: due giri insieme (l'orario e
# un lampo) non si pestano i piedi. Il ramo della copia segue main e `git push` va lì (push.default=upstream
# nella configurazione di git di redazione): le istruzioni delle curiosità e dei contributi dicono solo «git pull --rebase»
# e «git push». Le istruzioni sono in /usr/local/lib/nb-giri/prompt/<tipo>.txt (il testo della
# routine); il testo di avvio, se c'è, va dopo, come faceva la routine.
set -uo pipefail
ISTANZA=$1
TIPO=${ISTANZA%%-*}
CASA=/home/redazione
case "$TIPO" in
  agente)     MODELLO=claude-opus-5-5;  STRUMENTI="Bash,Read,Write,Edit,Glob,Grep,WebFetch,WebSearch" ;;
  lampo)      MODELLO=claude-opus-5-5;  STRUMENTI="Bash,Read,Write,Edit,Glob,Grep,WebFetch,WebSearch,Agent" ;;
  contributi) MODELLO=claude-opus-5-5;  STRUMENTI="Bash,Read,Write,Edit,Glob,Grep,WebFetch,WebSearch,Agent" ;;
  curiosita)  MODELLO=claude-fable-5-1; STRUMENTI="Bash,Read,Write,Edit,Glob,Grep,WebFetch,WebSearch,Agent" ;;
  *) echo "giro sconosciuto: $TIPO"; exit 2 ;;
esac
mkdir -p "$CASA/lucchetti" "$CASA/esiti" "$CASA/giri"
riga() { echo "$(date -u '+%d/%m %H:%M:%S') $ISTANZA $*" | tee -a "$CASA/giri.log"; }

# un solo giro alla volta per tipo, tranne il lampo (nel cloud ogni avvio era una sessione a sé)
if [ "$TIPO" != lampo ]; then
  exec 9>"$CASA/lucchetti/$TIPO.lock"
  flock -n 9 || { riga "saltato: c'è già un giro $TIPO in corso"; exit 0; }
fi
TESTO=""
[ -f "/var/lib/nb-giri/$ISTANZA.txt" ] && TESTO=$(cat "/var/lib/nb-giri/$ISTANZA.txt") && rm -f "/var/lib/nb-giri/$ISTANZA.txt"
PROMPT=$(cat "/usr/local/lib/nb-giri/prompt/$TIPO.txt") || { riga "mancano le istruzioni"; exit 2; }
[ -n "$TESTO" ] && PROMPT="$PROMPT"$'\n\n'"$TESTO"

W=$CASA/giri/$ISTANZA
pulisci() {
  git -C "$CASA/notizie-benevento" worktree remove --force "$W/notizie-benevento" 2>/dev/null
  git -C "$CASA/notizie-benevento" branch -q -D "giro-$ISTANZA" 2>/dev/null
  git -C "$CASA/notizie-benevento-fonti" worktree remove --force "$W/notizie-benevento-fonti" 2>/dev/null
  rm -rf "$W"
}
trap pulisci EXIT
INIZIO=$(date +%s)
# le copie, sotto lucchetto: fetch e worktree sulla stessa copia madre non vanno fatti da due giri insieme
if ! (
  flock 8
  git -C "$CASA/notizie-benevento" fetch -q origin main &&
  git -C "$CASA/notizie-benevento" worktree add -q -b "giro-$ISTANZA" "$W/notizie-benevento" origin/main &&
  git -C "$W/notizie-benevento" branch -q --set-upstream-to=origin/main &&
  git -C "$CASA/notizie-benevento-fonti" fetch -q origin main &&
  git -C "$CASA/notizie-benevento-fonti" worktree add -q --detach "$W/notizie-benevento-fonti" origin/main
) 8>"$CASA/lucchetti/copie.lock"; then
  riga "ERRORE: copie del sito e delle fonti non pronte"
  exit 1
fi
riga "parte ($MODELLO, copie pronte in $(( $(date +%s) - INIZIO )) s)"

cd "$W/notizie-benevento" || exit 1
timeout 50m claude -p "$PROMPT" --model "$MODELLO" --tools "$STRUMENTI" --permission-mode bypassPermissions \
  --add-dir "$W/notizie-benevento-fonti" --add-dir /tmp --strict-mcp-config --no-session-persistence \
  --output-format json > "$CASA/esiti/$ISTANZA.json" 2> "$CASA/esiti/$ISTANZA.err"
USCITA=$?
RIASSUNTO=$(python3 - "$CASA/esiti/$ISTANZA.json" <<'FINE'
import json, sys
try:
    d = json.load(open(sys.argv[1], encoding="utf-8"))
except Exception as e:
    print(f"esito illeggibile ({type(e).__name__})")
else:
    r = " ".join(str(d.get("result") or "").split())
    print(f"{'ERRORE ' if d.get('is_error') else ''}{d.get('num_turns', '?')} turni, {d.get('duration_ms', 0) // 1000} s: {r[:300]}")
FINE
)
riga "finito (uscita $USCITA, $(( $(date +%s) - INIZIO )) s): $RIASSUNTO"
exit $USCITA
