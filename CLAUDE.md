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
Tutte · Cronaca · Politica · Sport · Calcio · (Allerte, solo con un'allerta) · Avvisi · Agevolazioni · Eventi · Cultura · Altro · zona · Comuni
(lui: «Allerte e Avvisi spostale dopo calcio», «la pagina cultura mettila dopo eventi»); sul computer su una riga sola (da 960 px).
Archivio e ricerca non stanno nel menu ma nella testata, a destra del titolo (sotto i 960 px sotto il titolo, la
casella larga): lui voleva «liberare spazio» nel menu (28 ott 2026); la testata c'è su tutte le pagine, sopra il
meteo ci sarebbero state solo in prima pagina e nelle sezioni. Data e «Aggiornato» stanno a sinistra, una sopra l'altra. «Avvisi» (categorie `strade` + `avvisi`, pagina /sezione/avvisi/)
ha preso il posto di «Strade»: in ordine di quando servono, dal 22 ottobre al 2 novembre con i cimiteri paese per
paese. La zona la ricava archivia.py dal luogo (`ZONA_COMUNE`): «Benevento città» è solo Benevento. Le colonne
a zig-zag di «Le altre notizie» le ha scelte lui (niente spazi vuoti): non riproporle riga per riga.
Politica (28 ott, lui: «fai A e B»): ci vanno anche le decisioni di sindaco, Giunta, Consiglio, Provincia e Regione;
il dibattito politico della città sta in un solo approfondimento con `"categoria": "politica"`, che la sezione
Politica mostra in cima come «La storia in corso» (AGENTE.md, «Il dibattito politico in città»).

## Le agevolazioni (pagina /agevolazioni/, dal 28 ott 2026; fino al 28 ott sera «Contributi», /contributi/)
Lui, 28 ott 2026 sera: «ho deciso di cambiare nome alla pagina Contributi in Agevolazioni… la pagina deve uscire come
/agevolazioni/». I vecchi indirizzi /contributi/ e /contributi/<id>/ portano ai nuovi (pagine.py, noindex, fuori dalla
sitemap); dentro il codice e nei file restano i nomi «contributi» (contributi.json, contributi.py, filtroCat «contributi»).
Lui: «tutto quello che riesci a trovare che vada bene per BN e provincia… estremamente facile da consultare»; nome
«Contributi» perché i bandi di concorso avranno una sezione loro («Concorsi», in cantiere). strumenti/contributi.py:
il Catalogo degli incentivi del Ministero (non risponde a GitHub: lo scarica il Pi di casa e lo manda alla
pubblicazione, campo «contributi» di pubblica.yml, come i carburanti), più contributi_locali.json e
contributi_esclusi.json (li tiene **l'agente dei contributi**, routine di ogni mattina, CONTRIBUTI.md; lui: «devi
creare un agente che una volta al giorno scova i contributi, sovvenzioni») e gli aiuti dei Comuni presi dalle notizie
con `"contributo"` (non più tutti gli avvisi «Domande e bandi»: c'erano loculi e lampade votive, lui: «quasi tutti il
Comune chiede soldi»). Filtri «Chi sei?» (famiglie, giovani, commercianti, artigiani, agricoltori, turismo, imprese…,
dai settori del catalogo come nel vecchio Cacciatore di Contributi), «Da chi?» (Unione europea, Stato, Regione, Camera
di Commercio, Comuni, associazioni di categoria, fondazioni), «Per cosa?», «Che aiuto?» e ricerca restano
nell'indirizzo (/agevolazioni/?chi=commercio&da=regione), una pagina per agevolazione (/agevolazioni/<id>/). Quando si passa
ad Aruba (lui: «da fare nel prossimo futuro… così togliamo anche il rischio che il Pi non funzioni») lo scaricamento va
lì.

## Come sono fatte le pagine (regola del proprietario, 28 ott 2026)
Lui: «dobbiamo mettere una regola di come costruire le pagine… dobbiamo uniformare e scrivere una regola». Ogni pagina
nuova la segue; se una pagina non la segue, è da sistemare.
1. **In cima a ogni pagina la testata e lo stesso menu** (index.html; meteo.html ha la copia fatta di link: se cambi
   una voce, cambiala in tutti e due). La voce della pagina è sottolineata in rosso (la sezione o la zona; Calcio sulla
   pagina Calcio; Comuni sulle pagine dei Comuni); nelle notizie e nelle pagine di servizio nessuna. Il menu non si
   nasconde mai (pagine.py non lo nasconde più nelle pagine `articolo`).
2. **Sezioni e zone** (le voci del menu, /sezione/…, /zona/…), in quest'ordine: titolo («Cronaca a Benevento e nel
   Sannio», «Altre notizie da Benevento e dal Sannio», zone «Notizie dalla Valle Telesina»; sezione e zona insieme
   «Cronaca · Valle Telesina»: titoloSezione() in index.html = gli h1 di SEZIONI in pagine.py), sia aprendo
   l'indirizzo sia dal menu; i filtri della sezione (gli sport); la striscia delle ultime 5; i riquadri della sezione
   (calendario degli eventi, appuntamenti di Cultura, storia in corso di Politica, speciale e elenchi di Avvisi:
   riquadriSezione()); le notizie con la colonna di destra. La prima pagina non ha titolo: c'è la testata.
   **20 notizie per pagina e i numeri delle pagine in fondo** (lui, 28 ott 2026: «20 con possibilità di fare altre
   pagine con i numeri sotto per continuare all'infinito, la home ok così»): prima quelle in prima pagina, poi quelle
   dell'archivio dalla più recente, fino alla più vecchia (paginaSezione, numeriPagine). Sport, zona e pagina stanno
   nell'indirizzo (/sezione/sport/?sport=basket&pagina=2). Anche la prima pagina, 50 per pagina (lui: «ci ho ripensato,
   home 50 e poi a seguire»; «mai in archivio, l'archivio serve per ricercare»): le notizie non escono mai dagli elenchi.
   **Ogni file e ogni link da index.html parte dalla radice** («/archivio/…», «/favicon.svg»): aperta una notizia senza
   ricaricare l'indirizzo diventa /notizia/<id>/ e un indirizzo relativo finisce lì sotto (28 ott 2026: «Notizia non
   trovata» dalla ricerca e icona sparita). Una modifica si prova cliccando come fa lui (ricerca, elenchi, sezioni).
3. **Notizie, eventi, approfondimenti e pagine di servizio** (Strade chiuse, Scuole chiuse, Carburanti, Calcio,
   Comuni, Chi siamo, Curiosità, Archivio, Meteo): «← Tutte le notizie» (la pagina di un contributo: «← Tutti i
   contributi»), occhiello rosso e titolo grande (.appro), e sotto il titolo **Ascolta e Condividi** (lui, 28 ott 2026:
   «deve comparire in tutte le pagine… e anche le future»). Li mette da solo azioniPagina() in index.html in ogni
   pagina che sia un <article> col suo <h1> dentro #contenuto: una pagina nuova fatta così li ha senza fare niente.

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
