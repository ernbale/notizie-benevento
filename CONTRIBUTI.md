# L'agente dei contributi (una volta al giorno)

Voluto dal proprietario il 28 ott 2026: «devi creare un agente che una volta al giorno scova i contributi,
sovvenzioni», «non solo famiglie ma imprese, commercianti, artigiani ecc.», «fondi europei, statali, Confindustria,
Confartigianato, Camera di Commercio, Regione, Comuni e altro che neanche so», «serietà, profonda attenzione». La
pagina è notiziebenevento.it/agevolazioni/ (fino al 28 ott 2026 sera «Contributi», /contributi/): tutto quello che una famiglia, un giovane, un'impresa, un'associazione o un
Comune della **provincia di Benevento** può chiedere adesso.

Da dove arriva la pagina (strumenti/contributi.py):
- il Catalogo degli incentivi del Ministero delle Imprese (lo scarica il server, fino al 30 ott 2026 il Pi di casa, quattro volte al giorno): non lo
  scrivi tu, ma lo **controlli** (punto 3);
- `contributi_locali.json`: **lo scrivi tu**, con quello che il catalogo non ha;
- `contributi_esclusi.json`: **lo scrivi tu**, con le schede del catalogo chiuse o sbagliate;
- le notizie con `"contributo"` (gli aiuti dei Comuni, li segna l'agente di ogni ora): non le rifai.

## Il giro, ogni mattina

1. `TZ=Europe/Rome date -Iseconds`, `git pull --rebase`. Leggi tutto questo file, `contributi_locali.json`,
   `contributi_esclusi.json` e la pagina com'è adesso: `curl -s https://notiziebenevento.it/contributi.json`.
2. **Ricontrolla le tue voci.** Riapri la pagina ufficiale (WebFetch) di ogni voce di `contributi_locali.json` che ha
   `controllato` di più di 7 giorni fa, o che scade nei prossimi 7 giorni, o che apre nei prossimi 7 giorni. Se è
   cambiato qualcosa (date, importi, click day) aggiornala; se è **chiusa prima del tempo** (fondi finiti, sospesa,
   graduatoria fatta) metti in `scadenza` il giorno in cui ha chiuso e in `scadenza_testo` il perché («Chiuso: fondi
   esauriti»): dal giorno dopo non si vede più. Ogni voce ricontrollata ha `controllato` di oggi. Le voci scadute non
   si cancellano: escono da sole dopo 60 giorni.
3. **Controlla il catalogo.** Ogni giorno almeno 10 schede del catalogo (`"fonte": "catalogo"` in contributi.json),
   prima quelle che scadono presto e quelle senza scadenza, a giro (non sempre le stesse: guarda le date in
   `contributi_esclusi.json` e nel tuo resoconto di ieri, `git log`). Apri il `link` ufficiale: se il bando è chiuso,
   esaurito, solo per altre province, o il link è sbagliato, mettilo in `contributi_esclusi.json` (sotto). Se il link
   del catalogo è rotto ma il bando è aperto, scrivi una voce locale giusta e metti quella del catalogo negli esclusi.
4. **Cerca quelli nuovi.** Guarda le fonti qui sotto (non tutte ogni giorno: almeno tre gruppi al giorno, a giro, e
   sempre le notizie del giorno). Per ogni contributo aperto o con apertura annunciata con data che vale per la
   provincia di Benevento e che non c'è ancora (né nel catalogo, né nelle tue voci: stesso link o stesso bando),
   scrivi una voce.
5. **Il doppio controllo.** Prima di salvare, fai rileggere ogni voce **nuova o cambiata** a un secondo agente (Agent):
   riapre la pagina ufficiale e controlla frase per frase che importi, date, ore, requisiti e link siano scritti lì.
   Quello che non torna si corregge o si toglie.
6. **La prova.** `curl -s https://notiziebenevento.it/contributi.json -o /tmp/prima.json && python3
   strumenti/contributi.py --pubblica --prima /tmp/prima.json --uscita /tmp/contributi.json`: non deve stampare
   avvisi («::warning::»). Se li stampa, correggi.
7. **Salva.** Commit e push con `git -c user.name=Claude -c user.email=noreply@anthropic.com commit -m "Contributi del
   <giorno>: <n> nuovi, <n> aggiornati, <n> esclusi"`, poi `git pull --rebase` e `git push` (riprova se un altro giro ha
   spinto nel frattempo). ⛔ Mai il nome, il cognome o l'email del proprietario, in niente. Se non è cambiato niente,
   niente commit.
8. Rispondi con un resoconto breve: cosa hai aggiunto, aggiornato, escluso e i dubbi.

## Le fonti (a giro)

- **Stato, per famiglie e giovani**: INPS (inps.it, «Prestazioni e servizi»: assegno unico, nido, nuovi nati, bonus
  mamme, assegno di inclusione, carta acquisti…), Agenzia delle Entrate (detrazioni casa, affitti), ARERA (bonus
  sociale), Ministero dell'Istruzione e del Merito, Ministero della Cultura (carte dei giovani), Dipartimento per le
  politiche giovanili, Consap.
- **Stato, per imprese**: Invitalia (Resto al Sud 2.0, Smart&Start, ON, Brevetti+, Marchi+, Disegni+, Autoimpiego,
  click day), Ministero delle Imprese (Nuova Sabatini, Transizione, ecobonus veicoli), INAIL (bandi ISI e click day),
  ISMEA, SIMEST, GSE, Ministero del Lavoro (decreto flussi, terzo settore).
- **Regione Campania**: regione.campania.it (bandi e avvisi, BURC), agricoltura.regione.campania.it (CSR 2023-2027),
  Sviluppo Campania, ADISURC (borse universitarie), UnicoCampania (abbonamenti), i fondi FESR e FSE+.
- **Camera di Commercio Irpinia Sannio**: irpiniasannio.camcom.it (bandi, voucher, fiere).
- **Associazioni di categoria** (per scoprire bandi e per i loro servizi o contributi): Confindustria Benevento,
  Confartigianato, CNA, Confcommercio, Confesercenti, Coldiretti, CIA, Confagricoltura di Benevento; i Confidi.
- **GAL del Sannio** (Taburno, Titerno e Alto Tammaro, Fortore, Partenio, Irpinia Sannio): bandi per agricoltura,
  turismo e paesi.
- **Fondazioni**: Fondazione Con il Sud, Con i Bambini, Fondo per la Repubblica Digitale, fondazioni bancarie e di
  comunità che finanziano nel Sannio.
- **Unione europea**: youth.europa.eu (DiscoverEU, Corpo europeo di solidarietà), Erasmus+ (scadenze per scuole e
  associazioni), Erasmus per giovani imprenditori, EIC, Europa creativa, CERV (gemellaggi), LIFE, AGRIP (promozione
  dei prodotti agricoli). Solo quelle davvero alla portata di chi sta qui.
- **Comuni e Provincia**: i siti del Comune di Benevento e dei Comuni, gli Ambiti sociali (B1-B5), la Provincia di
  Benevento (provincia.benevento.it, albo pretorio: lui, 28 ott 2026, «provincia ne dà?»; quel giorno non ne aveva).
  Gli aiuti dei Comuni che sono già notizie con `"contributo"` non si rifanno.
- **Per scoprire**: le notizie del giorno (notizie.json), i giornali locali, le pagine delle associazioni. La voce si
  scrive però **solo dalla pagina ufficiale** di chi dà i soldi.

## Le regole (non si discutono)

1. **Solo fonti ufficiali per i dati.** Il `link` è la pagina ufficiale dell'ente che dà i soldi (https), mai un
   giornale o un consulente. Leggila con WebFetch: non fidarti del riassunto di una ricerca.
2. **Niente di inventato.** Importi, date, ore, requisiti solo se scritti nella fonte; se un dato non c'è, il campo
   resta vuoto o null. Mai date «probabili» (anche «20 giorni dalla pubblicazione»: niente data, scrivilo in
   `scadenza_testo`).
3. **Aperto adesso**, o con apertura annunciata con data. Una misura «a sportello» va bene se la pagina ufficiale dice
   che è attiva (non chiusa, sospesa o esaurita).
4. **Vale per la provincia di Benevento** (Sannio, Campania, Sud, Italia, Unione europea).
5. **Non sono contributi**: tasse, tariffe e pagamenti; loculi e lampade votive; albi (scrutatori); concorsi, offerte
   di lavoro e incarichi (avranno la sezione Concorsi); corsi a pagamento; elenchi di beneficiari già scelti.
6. Testi in italiano semplice, da giornale locale, senza enfasi, senza «scopri», senza emoji.

## La voce (`contributi_locali.json`, `{"contributi": [ … ]}`)

```json
{"id": "slug-unico-descrittivo", "titolo": "titolo chiaro, max ~90 caratteri",
 "ente": "INPS | Regione Campania | Camera di Commercio Irpinia Sannio | Comune di …",
 "da": ["europa|stato|regione|camera|comune|provincia|categoria|altri"],
 "dove": "sannio|campania|sud|italia|europa",
 "chi": ["cittadino|giovani|commercio|artigiano|agricoltura|turismo|impresa|nuova|professionista|associazione|ente"],
 "temi": ["figli|scuola|casa|lavoro|investire|aprire|digitale|energia|innovazione|export|credito|giovani-donne|crisi|sociale|cultura"],
 "aiuto": ["fondo|bonus|prestito|garanzia|fiscale|corso"],
 "forma": "Contributo a fondo perduto", "quanto": "fino a 5.000 € (come scritto nella fonte, o \"\")",
 "apertura": "AAAA-MM-GG o null", "scadenza": "AAAA-MM-GG o null", "scadenza_testo": "frase breve o null",
 "click_day": "AAAA-MM-GGTHH:MM o null", "link": "https://… pagina ufficiale",
 "cose": "cos'è, 1-2 frasi (max 420)", "a_chi": "a chi e i requisiti (max 600)",
 "cosa_prevede": "importi, percentuali, spese (max 1100)", "come": "come si chiede (max 500)",
 "controllato": "AAAA-MM-GG di oggi"}
```
- `da`: chi mette o gestisce i soldi; i fondi europei gestiti da Stato o Regione (PNRR, FESR, FSE+, FEASR, FEAMPA, GAL)
  hanno anche `europa`; `categoria` sono Confindustria, Confartigianato, CNA, Confcommercio, Coldiretti, Confidi…;
  `altri` fondazioni, GAL, banche.
- `chi`: per un aiuto alle imprese metti sempre `impresa`, più i settori che può chiederlo: per tutte le imprese
  `commercio`, `artigiano`, `turismo` e `agricoltura` (questa solo se la fonte non esclude l'agricoltura: molti aiuti
  «de minimis» la escludono).
- `aiuto`: `fondo` soldi a fondo perduto, `bonus` bonus/assegni/buoni alle persone, `prestito`, `garanzia`, `fiscale`
  (credito d'imposta, detrazione, sconto), `corso` corsi gratuiti (lui, 30 ott 2026, alla domanda se i corsi gratuiti
  vanno nelle agevolazioni: «si»; quelli a pagamento restano fuori, punto 5).

## Gli esclusi (`contributi_esclusi.json`, `{"esclusi": [ … ]}`)

`{"id": "l'id della scheda in contributi.json", "titolo": "…", "perche": "Chiuso: graduatoria approvata il 25/09/2026
(DD 158/2026)", "fonte": "https://… dove l'hai letto", "dal": "AAAA-MM-GG"}`. Se il catalogo cambia la scheda e torna
giusta (riaperta, nuovo bando), togli la riga.
