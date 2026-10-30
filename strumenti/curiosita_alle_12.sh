#!/bin/bash
# Sul server Aruba, dal cron alle 12:00 precise (30 ott 2026; lui, sulla curiosità uscita alle 12:02 perché la
# pubblicazione delle 12 si è intoppata col giro di ogni ora: «se si intoppa con il giro fai 11:59»): manda sui social
# solo la curiosità del Sannio (strumenti/curiosita_social.py), senza ricostruire il sito. La pagina della curiosità è
# già online: il sito lo ha ricostruito la pubblicazione chiesta alle 11:55 (strumenti/pagine.py, PRIMA_CURIOSITA).
# Lavora sulla copia pubblicata (/srv/notiziebenevento), che una pubblicazione in corso non sta rifacendo; lo stesso
# lucchetto della pubblicazione normale (che dopo trova la curiosità già uscita e non la rimanda): mai due insieme.
export TZ=UTC LANG=C.UTF-8 PATH="$HOME/venv-sito/bin:$PATH"
[ -f "$HOME/sito-stato/ACCESO" ] || exit 0   # i social li fa il server solo se il sito vero è lui
for s in TELEGRAM_TOKEN FB_PAGE_TOKEN; do
  export "$s=$(cat "$HOME/.config/nb/segreti/$s")"
done
cd /srv/notiziebenevento || exit 1
echo "$(date -u '+%d/%m %H:%M:%S') curiosità alle 12"
exec /usr/bin/flock -w 120 /tmp/nb_curiosita_social.lock \
  python3 strumenti/curiosita_social.py --stato "$HOME/sito-stato/social/curiosita.json"
