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

## Il menu del sito (deciso con lui il 28 ott 2026)
Tutte · Cronaca · Politica · Sport · Calcio · (Allerte, solo con un'allerta) · Avvisi · Eventi · Altro · zona · Comuni ·
Archivio (lui: «Allerte e Avvisi spostale dopo calcio»); sul computer su una riga sola (da 960 px). «Avvisi» (categorie `strade` + `avvisi`, pagina /sezione/avvisi/)
ha preso il posto di «Strade»: in ordine di quando servono, dal 22 ottobre al 2 novembre con i cimiteri paese per
paese. La zona la ricava archivia.py dal luogo (`ZONA_COMUNE`): «Benevento città» è solo Benevento. Le colonne
a zig-zag di «Le altre notizie» le ha scelte lui (niente spazi vuoti): non riproporle riga per riga.
Politica (28 ott, lui: «fai A e B»): ci vanno anche le decisioni di sindaco, Giunta, Consiglio, Provincia e Regione;
il dibattito politico della città sta in un solo approfondimento con `"categoria": "politica"`, che la sezione
Politica mostra in cima come «La storia in corso» (AGENTE.md, «Il dibattito politico in città»).

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
Oggi: una notizia ogni 20 minuti, nessun tetto, comunicati subito, classifica con `importanza` 1-5 (AGENTE.md), da 3 in
su. Dal 27 ott l'«Agente Social»: sceglie facebook.py, Instagram pubblica le stesse notizie subito dopo e nello stesso
ordine (instagram.da_facebook; se resta indietro recupera una ogni 10 minuti; guarda il tetto di Meta dei post in 24
ore). Un
aggiornamento col titolo diverso non è un doppione. Per togliere un post da Facebook: «Sposta nell'archivio»; su
Instagram lo toglie lui dall'app.
Il limite di Meta: facebook.py, instagram.py e statistiche.py scrivono nel log «limite dell'ora di Meta usato» (le
percentuali che Meta manda in ogni risposta) e, negli errori, sottocodice e chiamata. Le statistiche rileggono Meta al
massimo una volta l'ora e mai oltre il 60% (statistiche.META_OGNI, META_TETTO). Il 27 ott Instagram ha avuto due volte
«troppe richieste» (codice 4) con l'uso di Meta basso e **il post uscito lo stesso**: dopo un errore di Meta guarda il
profilo vero prima di pensare che manchi qualcosa (instagram.py comunque rilegge Instagram e non ripubblica).
Dal 27 ott il **freno** di Instagram (instagram.SOGLIA_FRENO, lui: «ok frena»): dopo un errore di Meta su Instagram
escono solo i comunicati e le notizie da 4 in su, al massimo una l'ora, senza recuperare niente, e niente riepilogo
della sera; finisce da solo al primo post uscito senza errore e da lì Instagram segue di nuovo Facebook, senza
recuperare le notizie di prima (`freno_dal` e `segue_dal` in instagram.json, nella cache «social» di GitHub).

La diretta della partita (gol.py): un'uscita sbagliata già mandata si corregge senza post nuovi con la Action «Gol del
Benevento», modo `correggi`, campo correggi `finale <id della notizia>` (o `gol:1`, `intervallo`): rifà testo e
immagine col programma di adesso; Telegram cambia foto e testo, Facebook il testo, Instagram il testo lo cambia lui
dall'app (si stampa nel log). Fatto la prima volta il 27 ott 2026 (un rigore letto come espulsione).

## Comunicati: subito solo le fonti ufficiali (dal 26 ott 2026)
Escono subito solo quelli di enti pubblici, PEC e mittenti fidati (`~/nb-fonti/mittenti_fidati.json` sul Pi). Gli altri
hanno `"fonte": "da_valutare"`: al proprietario arriva un avviso (WhatsApp ed email) e decide lui nella scheda Posta
delle statistiche («Pubblica», «Pubblica e fidati del mittente», «Non pubblicare»). Non pubblicarli a mano senza il suo
sì. Le regole sono in COMUNICATI.md.
Dal 26 ott il Pi legge anche lo Spam di comunicati@, della PEC e di redazione@ (sola lettura): chi è ufficiale esce lo
stesso e lui riceve un avviso; gli altri sono «da valutare»; quelli di redazione@ sono sempre da valutare.

## Facebook
Un post uscito senza immagine (l'anteprima della notizia è stata rinominata dopo il post): sulla Pagina, menu «…» del
post → «Aggiorna l'allegato della condivisione» → Salva. Non toccare il sito per questo.

## Lo scrittore del giornale (dal 27 ott 2026)
Lui: «nominiamo Fable 5.1 come scrittore giornalista ufficiale del nostro giornale? da controllare ogni giorno se escono
modelli nuovi». Provato il 27 ott sul giro delle 6 dell'agente: lavoro ottimo ma 10 minuti invece di 5 e il 2% del tetto
di Fable a giro (Fable ha un tetto suo: al massimo il 50% del limite settimanale; con 19 giri al giorno finirebbe in
due giorni e mezzo e si fermerebbe tutto). Decisione sua: «ok Fable solo per le curiosità». Quindi `claude-fable-5-1`
solo per il rifornimento delle curiosità (lunedì alle 6, circa il 3% a settimana); agente orario e giro lampo su
`claude-opus-5-5`. Ogni giorno alle 9 il Pi guarda la pagina dei modelli di Anthropic (`strumenti/modelli_nuovi.py`,
log `~/nb-fonti/modelli.log`) e, se ne esce uno nuovo, lo avvisa su WhatsApp e per email: non cambia niente da solo,
prima una prova sui dati veri (durata e consumo, dalla pagina Utilizzo di claude.ai) e poi decide lui.
