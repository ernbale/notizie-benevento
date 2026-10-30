# Notizie Benevento

Report automatico delle notizie di Benevento e provincia, confrontate tra i giornali locali.
Una notizia compare solo se la riportano almeno due testate diverse oppure una fonte ufficiale.
Le notizie appartengono ai giornali citati: qui ci sono solo un riassunto breve e i link agli articoli originali.

Sito: https://notiziebenevento.it (notiziebenevento.com rimanda qui)

Dal 30 ottobre 2026 il sito, le fonti lette «da casa», la posta e i giri della redazione automatica girano sul server
Aruba (prima erano su GitHub Pages, sul Raspberry Pi di casa e nel cloud di Claude): dove qui sotto si legge «il Pi di
casa» ora è il server. GitHub Pages resta come copia di riserva. La pubblicazione è `strumenti/pubblica_server.sh`
(gli stessi passi di `.github/workflows/pubblica.yml`), i giri sono in `strumenti/server/`, la diretta dei gol del
Benevento è `strumenti/gol_server.sh` (prima `.github/workflows/gol.yml`).

## Come è fatto

- `notizie.json`: le notizie degli ultimi 3 giorni, gli avvisi ancora in vigore, gli approfondimenti attivi.
- `archivio/AAAA-MM.json`: le notizie più vecchie, complete di articolo e fonti. Non si cancellano, e il sito continua a
  elencarle: home 50 per pagina, sezioni e zone 20, con i numeri delle pagine (dal 28 ott 2026).
- `strumenti/sparite.py`: a ogni pubblicazione rimette quello che il sito mostrava e nel repository manca (una notizia
  non sparisce mai; a ogni giro lo fa anche `archivia.py` contro l'ultimo salvataggio).
- `archivio/indice.json`: elenco leggero di tutto l'archivio, per la ricerca e per i link già condivisi.
- `strumenti/archivia.py`: controlla `notizie.json` (anche niente date nel futuro) e sposta in archivio; non scrive niente se trova un errore.
- `strumenti/meteo.py`: previsioni da 8 modelli → `meteo.json` (lo esegue GitHub ogni ora); con `--paesi` le stesse per
  i paesi, a turno ogni 6 ore → `meteo-paesi/<paese>.json` (la pagina `meteo.html?paese=<paese>`).
- `strumenti/meteo_comuni.py`: il meteo di ognuno dei 78 Comuni (Open-Meteo, coordinate in
  `strumenti/comuni_coordinate.json`) → `meteo-comuni.json`, per la colonna di destra delle pagine dei Comuni.
- `strumenti/guardia_medica.py`: le postazioni della guardia medica dal sito dell'ASL Benevento →
  `strumenti/guardia_medica.json` (a mano sul Mac); sul Pi ogni mattina `--controlla` avvisa se l'ASL le cambia.
- `strumenti/strade_luoghi.py`: dove sono le strade chiuse (le legge nel titolo e nel luogo delle notizie con
  «traffico», le cerca una volta sola su OpenStreetMap) → `strade-luoghi.json`, per i tondi della mappa di
  /strade-chiuse/ (lib/leaflet-1.9.4). Gira a ogni pubblicazione, prima di pagine.py.
- `CONTRIBUTI.md`, `contributi_locali.json`, `contributi_esclusi.json`: l'agente dei contributi (routine di ogni mattina)
  e quello che scrive: i contributi che il catalogo non ha e le schede del catalogo chiuse o sbagliate.
- `strumenti/contributi.py`: i contributi e i bandi per il Sannio → `contributi.json` (pagina `/agevolazioni/`, «Contributi» fino al 28 ott 2026): il catalogo del
  Ministero lo scarica il Pi di casa e lo manda alla pubblicazione, che lo unisce a `contributi_locali.json` (lo scrive l'agente).
- `strumenti/farmacie.py`: le farmacie di turno di Benevento città dal PDF mensile di Federfarma Benevento →
  `farmacie.json` (pagina `/farmacie-di-turno/`, dal 29 ott 2026), con i telefoni dall'elenco delle farmacie della stessa
  Federfarma: lo legge il Pi di casa e lo manda alla pubblicazione
  quando cambia, come i carburanti. La pagina `/servizi/` raccoglie farmacie, strade e scuole chiuse, carburanti, meteo,
  avvisi, agevolazioni e Comuni (voce «Servizi» del menu). `strumenti/farmacie_paesi.py`: i turni dei paesi dai PDF
  dell'Ordine dei Farmacisti, zona per zona. pagine.py scrive `farmacie-fasce.json` (gli orari di adesso per la pagina,
  i Comuni e il riquadro della prima pagina); non va nel repository.
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
