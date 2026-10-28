#!/bin/sh
# Sul Pi, dal cron ogni minuto (27 ott 2026, lui: «i comunicati stampa del Benevento Calcio … da pubblicare
# istantaneamente, priorità max», «tutti 3 i social più sito»): legge solo la pagina delle notizie del Benevento Calcio
# (ufficiali.py --solo) e, se c'è un articolo nuovo, fa partire subito il giro lampo, che lo pubblica sul sito e da lì
# su Telegram, Facebook e Instagram. Col lucchetto del giro di 5 minuti (flock nel cron): mai due letture insieme.
C="$HOME/nb-fonti"   # la cartella delle fonti sul Pi (cron mette HOME)
out=$(/usr/bin/timeout 50 /usr/bin/python3 $C/sentinella/ufficiali.py --solo "Benevento Calcio" 2>&1)
[ -n "$out" ] && echo "$out" >> $C/ufficiali.log
case "$out" in
  *"nuove, archivio pubblicato"*)
    /usr/bin/flock -w 50 /tmp/nb_comunicati.lock /usr/bin/timeout 90 /usr/bin/python3 $C/sentinella/comunicati_lampo.py >> $C/comunicati.log 2>&1 ;;
esac
exit 0
