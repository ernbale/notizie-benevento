# Notizie Benevento

Report automatico delle notizie di Benevento e provincia, confrontate tra i giornali locali.
Una notizia compare solo se la riportano almeno due testate diverse oppure una fonte ufficiale.
Le notizie appartengono ai giornali citati: qui ci sono solo un riassunto breve e i link agli articoli originali.

Sito: https://notiziebenevento.it (notiziebenevento.com rimanda qui)

## Come è fatto

- `notizie.json`: le notizie degli ultimi 3 giorni, gli avvisi ancora in vigore, gli approfondimenti attivi.
- `archivio/AAAA-MM.json`: le notizie più vecchie, complete di articolo e fonti. Non si cancellano, e il sito continua a
  elencarle: home 50 per pagina, sezioni e zone 20, con i numeri delle pagine (dal 28 ott 2026).
- `strumenti/sparite.py`: a ogni pubblicazione rimette quello che il sito mostrava e nel repository manca (una notizia
  non sparisce mai; a ogni giro lo fa anche `archivia.py` contro l'ultimo salvataggio).
- `archivio/indice.json`: elenco leggero di tutto l'archivio, per la ricerca e per i link già condivisi.
- `strumenti/archivia.py`: controlla `notizie.json` (anche niente date nel futuro) e sposta in archivio; non scrive niente se trova un errore.
- `strumenti/meteo.py`: previsioni da 8 modelli → `meteo.json` (lo esegue GitHub ogni ora).
- `CONTRIBUTI.md`, `contributi_locali.json`, `contributi_esclusi.json`: l'agente dei contributi (routine di ogni mattina)
  e quello che scrive: i contributi che il catalogo non ha e le schede del catalogo chiuse o sbagliate.
- `strumenti/contributi.py`: i contributi e i bandi per il Sannio → `contributi.json` (pagina `/agevolazioni/`, «Contributi» fino al 28 ott 2026): il catalogo del
  Ministero lo scarica il Pi di casa e lo manda alla pubblicazione, che lo unisce a `contributi_locali.json` (lo scrive l'agente).
- `strumenti/foto_ia.py`: le foto fatte con GPT Image dalla `scena`: oggi solo per le curiosità senza foto libera su Commons
  (`img/curiosita/`); le 31 fatte il 28 ott 2026 per notizie e storie (`img/ia/`) restano. Segreto `OPENAI_API_KEY`.
- `strumenti/pagine.py`: a ogni pubblicazione fa una pagina vera per ogni notizia (`/notizia/<id>/`, anche archiviate),
  le pagine delle sezioni e delle zone, l'immagine di anteprima di ogni notizia, `sitemap.xml`, `sitemap-notizie.xml`
  (Google News), `feed.xml` (RSS) e avvisa Bing con IndexNow. Niente di questo va nel repository.
- `404.html`: se la pagina di una notizia manca, apre la notizia nella prima pagina.
- `strumenti/statistiche.py` + `statistiche/`: pagina privata con visite (Cloudflare Web Analytics), Google e numeri del giornale;
  i dati sono cifrati con la parola d'ordine (segreto `STATISTICHE_PAROLA`), non vanno nel repository.
- `strumenti/allegati.py`: il testo degli allegati delle mail dei comunicati (sul Pi, lo usano fonti_casa.py e la scheda
  Posta): PDF anche scansionati (OCR), Word, Excel, PowerPoint vecchi e nuovi, LibreOffice, RTF, testo, archivi, .p7m,
  winmail.dat, mail inoltrate; quello che non si legge va in «allegati_non_letti» (il comunicato resta in sospeso).
- `strumenti/facebook.py`: dopo ogni pubblicazione mette sulla Pagina Facebook una notizia nuova (una ogni 20 minuti,
  senza tetto al giorno, dalle 6 fino al giro delle 22; i comunicati subito), con la chiave nel segreto `FB_PAGE_TOKEN`;
  senza chiave non fa niente.
- L'agente (routine Claude ogni ora, 6-22) pubblica con git, in un solo commit; GitHub Actions ripubblica il sito.
- `AGENTE.md`: le istruzioni dell'agente che aggiorna il sito.

Lo storico di GitHub conserva in più ogni versione di ogni file.
