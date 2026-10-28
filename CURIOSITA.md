# Curiosità del Sannio: come si scrivono

Una al giorno alle 12 su Telegram, Facebook, Instagram e sul sito (strumenti/curiosita_social.py, strumenti/pagine.py).
Voluta dal proprietario il 24 ott 2026: «una curiosità, una storia, un fatto del passato, un detto, una storiella, una
superstizione, una leggenda… di Benevento», «andare avanti all'infinito», «nessun fallimento, nessuna storia scritta
male, perfezione», «usa l'agente più intelligente che abbiamo».

Stanno tutte in `curiosita.json` (anche quelle già uscite: servono a non ripetersi). Il controllo automatico è
`python3 strumenti/curiosita_controlla.py`: va passato prima di ogni commit.

## La regola che non si discute: niente di inventato

- Ogni fatto, data, nome, numero, citazione o detto deve stare in almeno una fonte seria che è stata APERTA e letta:
  Wikipedia in italiano (solo i punti con una nota), Treccani, siti di musei, Soprintendenza, Comuni, Provincia, UNESCO,
  università, diocesi, Pro Loco ufficiali, libri su Google Libri o Internet Archive. Meglio due fonti indipendenti
  (attenzione: un sito che copia Wikipedia non è una seconda fonte).
- Se le fonti non concordano, si scrive la versione più sicura o si dice che non concordano. Mai arrotondare per fare
  effetto.
- Le leggende si raccontano come leggende («si racconta che…», «secondo la tradizione…»), mai come fatti.
- Detti in dialetto: solo se trovati scritti in una fonte (raccolte di proverbi, dizionari dialettali, studi), con la
  grafia della fonte e la traduzione.
- Citazioni tra virgolette solo se sono nella fonte parola per parola.
- Niente politica, niente persone viventi, niente cronaca nera recente, niente religione in tono polemico, niente che
  possa offendere un paese o una comunità.
- Il testo è scritto con parole nostre: niente copia-incolla (al massimo poche parole citate tra virgolette).

## Il testo

- Italiano semplice e caldo, come raccontato da uno del posto; niente tono da guida turistica, niente punti esclamativi
  a raffica, niente emoji.
- Titolo: al massimo 70 caratteri. Testo: 500-900 caratteri in 2-3 paragrafi brevi (separati da una riga vuota), più
  l'ultima riga: una domanda breve per i commenti, sempre diversa («Da voi come si racconta?»). Sul sito l'ultima riga
  non si vede.
- La prima frase deve far venire voglia di leggere.

## Gli argomenti

Vanno alternati: leggenda, storia, detto, superstizione, tradizione, cibo (`cibo`), paese della provincia (`paese`),
«accadde oggi» (`accadde oggi`, solo con giorno e mese esatti e verificati, e la `data` deve essere proprio quel
giorno). Non solo Benevento città: i 78 Comuni della provincia. Mai due volte lo stesso argomento: prima di scrivere
si leggono tutti i titoli e i testi già in `curiosita.json`.

## La foto

Le foto vere: solo file di Wikimedia Commons con licenza libera (CC BY, CC BY-SA, CC0, pubblico dominio) controllata sulla pagina del
file. Meglio orizzontali e larghe almeno 900 pixel (sull'immagine dei social la foto è
1080×600). Per una foto verticale (un ritratto) il ritaglio si centra col campo `fuoco_y` di `immagine`: dove sta il
soggetto, da 0 (in alto) a 1 (in basso); senza, 0.5. Si salva in `img/curiosita/<slug>.jpg` (JPEG, lato lungo al massimo 1200, mai ingrandita). Nel campo
`credito`: «Foto: <autore> · <licenza>» oppure, per le opere antiche, «<che cos'è> · pubblico dominio». Se non c'è una
foto adatta e libera del protagonista, **la foto si fa con l'IA** (dal 28 ott 2026; lui, sulla curiosità delle janare
uscita col solo cartoncino: «la storia che è uscita oggi non ha foto, regola tutte foto, se non la trovi ne crei una
perfetta cinematografica con gpt», «deve rappresentare bene la scena raccontata»): in `immagine` metti
`"file": "/img/curiosita/<slug>.jpg"`, `"ia": true`, `"mostra"` (cosa si vedrà) e `"scena"`, la scena da fotografare,
in inglese, da 60 a 700 caratteri: **la scena raccontata** (la janara davanti alla porta con la scopa, il noce sul
fiume, il piatto sulla tavola), con i luoghi e gli oggetti di qui, cinematografica; le persone sono inventate, mai
persone vere riconoscibili (per una persona storica: di spalle, da lontano, o il suo luogo). Niente `credito` e
`pagina`: la foto la fa `strumenti/foto_ia.py` alla pubblicazione e sul sito e sui social esce con la scritta che è
fatta con l'intelligenza artificiale. Prima si cerca sempre la foto vera su Commons, come sopra. Niente nudi, niente
immagini macabre.

**La foto mostra il protagonista della storia** (il fossile, il vaso, la persona, il monumento, il piatto, la festa),
non il paese dove è successo. Il proprietario, 27 ott 2026, sulla foto aerea di Pietraroja messa al posto del fossile
di Ciro: «la foto che hai scelto sinceramente non rappresenta il dinosauro ciro il fossile»; e «controlla anche le
future». Quindi su Commons si cerca prima il protagonista (anche tra le foto della sua voce di Wikipedia e della sua
categoria su Commons), poi il resto. Il paese o il paesaggio vanno bene solo quando il protagonista è il paese stesso,
o quando del protagonista non c'è una foto libera adatta (troppo piccola, macabra, con persone riconoscibili in primo
piano): in quel caso il luogo della storia, mai una foto qualsiasi.
**E la foto è di qui**: il protagonista vero o il suo luogo, mai quadri, paesaggi od oggetti di altri posti messi solo
per fare atmosfera. Il proprietario, 27 ott 2026, su un quadro di Van Gogh proposto per un detto di Pesco Sannita:
«luna di Van Gogh cosa centra con le curiosita di benevento?».
Nel campo `mostra` di `immagine` si scrive in poche parole cosa si vede nella foto (sul sito è il testo alternativo):
deve essere il protagonista, o il luogo nei casi detti sopra.

## Il formato in curiosita.json

```json
{"slug": "parole-chiave-con-trattini", "data": "AAAA-MM-GG", "categoria": "leggenda", "luogo": "Benevento",
 "titolo": "...", "testo": "paragrafo\n\nparagrafo\n\nparagrafo\n\nDomanda per i commenti?",
 "fonti": [{"titolo": "Wikipedia – Voce", "url": "https://..."}],
 "immagine": {"file": "/img/curiosita/<slug>.jpg", "mostra": "il fossile di Ciro nella sua lastra di roccia",
              "credito": "Foto: Autore · CC BY-SA 4.0", "pagina": "https://commons.wikimedia.org/wiki/File:..."},
 "verifica": "cosa è stato controllato, su quali fonti, e i dubbi che restano"}
```

Le date sono una al giorno, senza buchi e senza doppioni, dopo l'ultima già in programma. Una curiosità già uscita
non si cambia più (sta sui social): si correggono solo errori veri, dicendolo nel commit.

## Il doppio controllo

Chi scrive non basta: ogni curiosità nuova la rilegge da capo un secondo agente, che riapre le fonti e controlla frase
per frase fatti, date, nomi, grafia dei detti, licenza della foto, italiano. Apre anche il file JPEG e guarda la foto:
se non mostra il protagonista della storia, se non è di qui o se `mostra` non dice quello che si vede, la foto si
cambia (le regole sono in «La foto»). Con la foto fatta dall'IA controlla la `scena`: deve essere la scena raccontata. Quello che non torna si corregge o si toglie; se una curiosità non regge, si
butta e se ne scrive un'altra.
