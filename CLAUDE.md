# Notizie Benevento: come si lavora col proprietario

**Se sei una routine (il giro di ogni ora, il giro lampo, le curiosità): questo file non è per te.** Segui solo il
tuo file di istruzioni (AGENTE.md, COMUNICATI.md, CURIOSITA.md) e quello che dice il messaggio che ti avvia.

Questo file è per le sessioni di lavoro col proprietario, da qualsiasi posto (PC del negozio, Mac di casa,
claude.ai/code dal telefono): qui c'è quello che serve per riprendere il lavoro senza la memoria del singolo computer.

## Il proprietario
- ⛔ **Regola fondamentale: mai il suo nome e cognome, né la sua email,** in niente di pubblico: commit, file del repo,
  sito, social, mail (lui, 26 ott 2026: «assolutamente nessun nome e cognome», «regola fondamentale nessun nome e
  cognome mio»). I commit si firmano `Claude <noreply@anthropic.com>`: dove git non ha un'identità, usa
  `git -c user.name=Claude -c user.email=noreply@anthropic.com commit …`. Il 26 ott la storia del repo è stata
  riscritta per toglierli: non rimetterli.
- Rispondi **sempre in italiano**. Scrive veloce, con refusi, spesso con uno screenshot: capisci cosa intende.
- Lavori grossi: prima il progetto, poi il codice. Ritocchi: diretti.
- Le regole che chiede per l'agente vanno nei file delle istruzioni (AGENTE.md, COMUNICATI.md), **con la data e le sue
  parole tra «»**, come quelle che ci sono già. Se una regola si può controllare con un programma, metti anche il
  controllo in `strumenti/archivia.py` (vale per tutti i giri) o in `strumenti/comunicati.py` (solo il giro lampo).

## Come è fatto
- Sito statico su GitHub Pages; `README.md` dice cosa fa ogni file. Le notizie sono in `notizie.json` (prima pagina)
  e `archivio/AAAA-MM.json`; gli eventi in `eventi.json`.
- Archivio privato delle fonti: repo `ernbale/notizie-benevento-fonti` (comunicati.json = la casella
  comunicati@notiziebenevento.it, ufficiali.json, allegati/). Lo riempie il Pi di casa ogni 5 minuti.
- Routine cloud (claude.ai/code → Routine): «agente (ogni ora)», «giro lampo (chiusure e comunicati)» (lo avvia il Pi
  appena arriva un comunicato; ha anche lo strumento Agent per il revisore), «curiosità (rifornimento del lunedì)».
- Ogni push su main fa partire la Action «Pubblica il sito» (`.github/workflows/pubblica.yml`): pagine, Telegram,
  Facebook, Instagram. Ci mette circa 2 minuti.

## Correggere una notizia a mano
1. `git pull --rebase` (le routine pubblicano spesso: rifallo anche subito prima del push).
2. Modifica `notizie.json` (o l'archivio) con uno script che rilegge e riscrive il JSON con l'indentazione di 1
   spazio: niente modifiche a mano del file intero. Esempio: `articolo.non_si_sa = []` toglie «Cosa non si sa ancora».
3. Controlla: `python3 -c "import sys,json; sys.path.insert(0,'strumenti'); import archivia as A; d=json.load(open('notizie.json', encoding='utf-8')); e,a=[],[]; A.controlla(d,e,a); print(e or 'OK')"`.
4. Commit e push. Il messaggio **non** deve cominciare con «Comunicato delle » o «Notizie delle »: sono quelli dei
   giri e la Action li tratta in modo diverso.
5. Aspetta la Action (`gh run watch`) e controlla la pagina online (`https://notiziebenevento.it/notizia/<id>/`).

Dopo una modifica a `strumenti/`: `python3 -m py_compile` sui file toccati e una prova sui dati veri (come al punto 3),
prima del push. Un errore in `archivia.py` ferma il giro di ogni ora.

## Controllare le sentinelle da qualsiasi posto
Il Pi di casa (vedetta, fonti, posta in diretta, giro lampo, sentinella) è solo nella LAN di casa, ma lascia tracce
che si leggono da ovunque:
- **Il Pi è vivo?** Nel repo ernbale/notizie-benevento-fonti il commit «Fonti lette da casa alle HH:MM» arriva ogni 5
  minuti; in ogni file `controllato` ed `esito` (chiusure.json: «Comuni 73/78 · albi 57/57…», ufficiali.json: «23 fonti
  su 23»).
- **Il sito è al passo?** `GH_TOKEN="$(gh auth token)" python3 strumenti/sentinella.py --prova` (non tocca niente).
- **Allarmi del Pi**: le esecuzioni in rosso di `.github/workflows/sentinella.yml` lanciate a mano (workflow_dispatch)
  sono gli avvisi del Pi: `gh run view <id> --log | grep AVVISO_PI`.
- La posta in diretta (posta_diretta.py) e le risposte di cortesia (risposte.py) da fuori non si vedono: solo dal Pi.

## Social: mai raffiche né doppioni (regola del proprietario dal 26 ott 2026)
Il 26 ott 2026 sono usciti 16 post Facebook in un minuto (tolti i limiti, è partita tutta la coda arretrata) e 5
doppioni (la memoria di cosa era già uscito copriva un giorno solo; una foto rimandata dopo una risposta persa). Lui:
«non deve mai più capitare». Quindi, prima di toccare `strumenti/facebook.py` o `strumenti/instagram.py`:
- simula sui dati veri cosa uscirebbe alla **prima** pubblicazione e nelle ore dopo (`--prova`): mai più di 1-2 post
  insieme;
- tutto ciò che allarga chi può uscire deve stare dentro i giorni che `gia_pubblicate` legge (`GIORNI_MEMORIA`);
- un invio con risposta incerta non si ripete (`riprova`);
- dopo il primo giro vero guarda la Pagina e il profilo Instagram veri (i log non bastano) e cerca doppioni.
Oggi: una notizia ogni 20 minuti, nessun tetto, comunicati subito, classifica con `importanza` 1-5 (AGENTE.md). Un
aggiornamento col titolo diverso non è un doppione. Per togliere un post da Facebook: «Sposta nell'archivio»; su
Instagram lo toglie lui dall'app.

## Comunicati: subito solo le fonti ufficiali (dal 26 ott 2026)
Escono subito solo quelli di enti pubblici, PEC e mittenti fidati (`~/nb-fonti/mittenti_fidati.json` sul Pi). Gli altri
hanno `"fonte": "da_valutare"`: al proprietario arriva un avviso (WhatsApp ed email) e decide lui nella scheda Posta
delle statistiche («Pubblica», «Pubblica e fidati del mittente», «Non pubblicare»). Non pubblicarli a mano senza il suo
sì. Le regole sono in COMUNICATI.md.

## Facebook
Un post uscito senza immagine (l'anteprima della notizia è stata rinominata dopo il post): sulla Pagina, menu «…» del
post → «Aggiorna l'allegato della condivisione» → Salva. Non toccare il sito per questo.
