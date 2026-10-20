# Notizie Benevento

Report automatico delle notizie di Benevento e provincia, confrontate tra i giornali locali.
Una notizia compare solo se la riportano almeno due testate diverse oppure una fonte ufficiale.
Le notizie appartengono ai giornali citati: qui ci sono solo un riassunto breve e i link agli articoli originali.

Sito: https://notiziebenevento.it (notiziebenevento.com rimanda qui)

## Come è fatto

- `notizie.json`: la prima pagina (ultimi 3 giorni, avvisi ancora in vigore, approfondimenti attivi).
- `archivio/AAAA-MM.json`: le notizie uscite dalla prima pagina, complete di articolo e fonti. Non si cancellano.
- `archivio/indice.json`: elenco leggero di tutto l'archivio, per la ricerca e per i link già condivisi.
- `strumenti/archivia.py`: controlla `notizie.json` (anche niente date nel futuro) e sposta in archivio; non scrive niente se trova un errore.
- `strumenti/meteo.py`: previsioni da 8 modelli → `meteo.json` (lo esegue GitHub ogni ora).
- `strumenti/pagine.py`: a ogni pubblicazione fa una pagina vera per ogni notizia (`/notizia/<id>/`, anche archiviate),
  le pagine delle sezioni e delle zone, l'immagine di anteprima di ogni notizia, `sitemap.xml`, `sitemap-notizie.xml`
  (Google News), `feed.xml` (RSS) e avvisa Bing con IndexNow. Niente di questo va nel repository.
- `404.html`: se la pagina di una notizia manca, apre la notizia nella prima pagina.
- L'agente (routine Claude ogni 2 ore, 6-22) pubblica con git, in un solo commit; GitHub Actions ripubblica il sito.
- `AGENTE.md`: le istruzioni dell'agente che aggiorna il sito.

Lo storico di GitHub conserva in più ogni versione di ogni file.
