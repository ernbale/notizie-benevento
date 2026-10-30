#!/bin/bash
# Sul Mac di casa, ogni notte alle 3:30 (launchd, ~/Library/LaunchAgents/it.notiziebenevento.backup-server.plist; se il
# Mac dorme, parte appena si sveglia): copia dal server Aruba quello che non sta nel repository. Dal piano del trasloco
# («backup notturno di conf/stati»), fatto il 30 ott 2026 (lui: «fai tutto»).
# La seconda copia è sul K12 (192.168.50.120), che è sempre acceso (lui, 30 ott 2026, sul Mac che può essere spento:
# «fai una doppia copia sul k12», «devono essere indipendenti ma identiche»): stesso programma (copiato in
# ~/backup_server_aruba.sh), stessa ora (3:30, dal suo cron), stessa cartella, ognuna dal server per conto suo; sul K12
# con la sua chiave ~/.ssh/nb_backup_aruba (BACKUP_CHIAVE).
# Cosa si copia:
#   ~/nb-fonti      programmi, impostazioni con le password, stati, registri, archivio delle fonti
#   ~/sito-stato    cosa è già uscito sui social, l'interruttore ACCESO, lo stato della diretta dei gol
#   ~/.config/nb    i segreti della pubblicazione
#   ~/finto-github  l'archivio delle fonti (il suo «origin»)
#   gli script della home, /etc/caddy, i cron (crontab di ernesto e /etc/cron.d/nb-giri)
# Restano fuori i giri (utente redazione: il loro registro non si legge da ernesto) e le chiavi ssh (si rifanno).
# In ~/Backup_casa/server-aruba/AAAA-MM-GG, una cartella per notte, le ultime 14: i file uguali alla notte prima non
# occupano altro spazio (--link-dest). Registro: ~/Backup_casa/server-aruba/backup.log.
set -u
SERVER=ernesto@195.231.64.238
DEST=${BACKUP_DEST:-$HOME/Backup_casa/server-aruba}
OGGI=$(date +%Y-%m-%d)
NUOVA=$DEST/$OGGI.parziale
SSH="ssh -i ${BACKUP_CHIAVE:-$HOME/.ssh/nb_server_ed25519} -o IdentitiesOnly=yes -o BatchMode=yes -o ConnectTimeout=30 -o StrictHostKeyChecking=accept-new"
mkdir -p "$DEST" && chmod 700 "$DEST"
exec >> "$DEST/backup.log" 2>&1
quando() { date '+%d/%m %H:%M:%S'; }
[ -d "$DEST/$OGGI" ] && { echo "$(quando) già fatto oggi"; exit 0; }
ULTIMA=$(ls -1d "$DEST"/20??-??-?? 2>/dev/null | sort | tail -1)
rm -rf "$NUOVA"
mkdir -p "$NUOVA"
errori=0

# una cartella del server in una cartella del backup, coi file uguali presi dalla notte prima
copia() {
  local da=$1 a=$2
  if rsync -a --delete -e "$SSH" ${ULTIMA:+--link-dest="$ULTIMA/$a"} "$SERVER:$da/" "$NUOVA/$a/"; then
    return 0
  fi
  echo "$(quando) NON copiato: $da"
  errori=$((errori + 1))
}
copia nb-fonti nb-fonti
copia sito-stato sito-stato
copia .config/nb config-nb
copia finto-github finto-github
copia /etc/caddy etc-caddy
mkdir -p "$NUOVA/script"
$SSH "$SERVER" 'tar cf - pubblica_server.sh pubblica_se_serve.sh curiosita_alle_12.sh gol_server.sh' | tar xf - -C "$NUOVA/script" \
  || { echo "$(quando) NON copiati: gli script"; errori=$((errori + 1)); }
$SSH "$SERVER" 'crontab -l; echo "==== /etc/cron.d/nb-giri"; cat /etc/cron.d/nb-giri' > "$NUOVA/cron.txt" \
  || { echo "$(quando) NON copiati: i cron"; errori=$((errori + 1)); }

if [ "$errori" -gt 0 ]; then
  echo "$(quando) backup NON riuscito ($errori errori): resta quello di prima, si riprova la notte dopo"
  rm -rf "$NUOVA"
  exit 1
fi
mv "$NUOVA" "$DEST/$OGGI"
ls -1d "$DEST"/20??-??-?? | sort -r | tail -n +15 | while read -r vecchia; do rm -rf "$vecchia"; done
echo "$(quando) backup fatto: $OGGI ($(du -sh "$DEST/$OGGI" | cut -f1))"
