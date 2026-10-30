#!/bin/bash
# Sul server Aruba, dal cron ogni minuto (30 ott 2026): fa partire strumenti/pubblica_server.sh quando su GitHub
# farebbe partire «Pubblica il sito»:
#   - c'è un commit nuovo su main (i giri, il giro lampo, le correzioni a mano)        = «on: push»
#   - sono arrivati carburanti, farmacie o contributi in ~/sito-stato/arrivi            = i campi della pubblicazione
#   - alle :12 di ogni ora (il meteo)                                                    = «schedule: 12 * * * *»
#   - alle :00, :20 e :40 dalle 6 alle 21 (una notizia sui social ogni 20 minuti, e alle 12 la curiosità), come le
#     pubblicazioni che fa partire strumenti/curiosita_via.py --giro
#   - se qualcuno ha lasciato ~/sito-stato/pubblica (la sentinella che rilancia, una prova a mano)
STATO=$HOME/sito-stato
mkdir -p "$STATO/arrivi"
perche=""
remoto=$(timeout 30 git ls-remote https://github.com/ernbale/notizie-benevento.git refs/heads/main | cut -f1)
[ -n "$remoto" ] && [ "$remoto" != "$(cat "$STATO/ultimo_sha" 2>/dev/null)" ] && perche="commit ${remoto:0:7}"
ls "$STATO"/arrivi/*.json 2>/dev/null | grep -v '\.usato\.json$' | grep -q . && perche="${perche:+$perche, }dati arrivati"
ora=$(TZ=Europe/Rome date +%-H)
min=$(date +%M)
[ "$min" = 12 ] && perche="${perche:+$perche, }le :12"
case "$min" in 00|20|40) [ "$ora" -ge 6 ] && [ "$ora" -le 21 ] && perche="${perche:+$perche, }giro dei social";; esac
[ -f "$STATO/pubblica" ] && { rm -f "$STATO/pubblica"; perche="${perche:+$perche, }richiesta"; }
[ -z "$perche" ] && exit 0
echo "$(date -u '+%d/%m %H:%M:%S') parte: $perche"
exec "$HOME/pubblica_server.sh"
