#!/usr/bin/env python3
"""Il testo degli allegati delle mail dei comunicati. Lo usano fonti_casa.py (la posta letta dal Pi ogni 5 minuti) e
posta_web.py (la scheda «Posta» delle statistiche).

Voluto dal proprietario il 26 ott 2026, dopo il comunicato del San Pio delle 12:12 perso perché era solo in un .doc
(il Word vecchio) che il Pi non leggeva: «copri tutti i casi possibili per leggere allegati», «anche un OCR per
scansioni». Si legge:
- PDF (pdftotext); quelli senza testo (le scansioni) con l'OCR, pagina per pagina;
- Word .docx e .doc, Excel .xlsx e .xls, PowerPoint .pptx e .ppt, LibreOffice .odt .ods .odp, RTF, Pages, Numbers e
  Keynote (col loro PDF di anteprima), testo semplice (.txt .csv .ics) e pagine HTML. Il formato si riconosce dai
  primi byte, non dal nome: un .doc può essere un .docx o un RTF rinominato;
- dentro gli allegati che ne contengono altri: zip, 7z, rar, tar e gz (col programma 7z), i .p7m firmati (openssl),
  il winmail.dat di Outlook, le mail inoltrate come allegato (.eml, e .msg di Outlook); anche le immagini dentro i
  documenti Word, Excel, PowerPoint e LibreOffice;
- le immagini grandi (locandine, scansioni in JPG o TIFF, le foto HEIC degli iPhone) le salva fonti_casa.py per
  l'agente, che le guarda; i TIFF (i fax e le scansioni) passano sempre dall'OCR, le altre immagini solo quando il
  testo della mail e dei documenti è poco (il comunicato potrebbe essere tutto lì).
Quello che proprio non si legge (un video, un archivio con la password, una scansione quando l'OCR non c'è) finisce
in «non_letti» col perché: il giro lampo non può scartare quel comunicato, lo mette in sospeso e la sentinella avvisa
(COMUNICATI.md). I link a file da scaricare (Google Drive, WeTransfer, Dropbox…) finiscono in «link_file»: li apre
l'agente.

Programmi sul Pi: pdftotext, pdftoppm e pdfinfo (poppler), openssl, 7z, tesseract con l'italiano (l'OCR, installato
dal proprietario); Pillow e pillow-heif in ~/nb-fonti/venv-img. Se uno manca, quel caso va in «non_letti» e il resto
si legge lo stesso.

Prova:  python3 allegati.py FILE…        (cosa si legge di ogni file: testo, cosa no, immagini; con l'OCR)
        python3 allegati.py --mail FILE.eml
"""
import base64
import collections
import datetime as dt
import email
import email.header
import email.message
import email.utils
import hashlib
import itertools
import html
import io
import json
import os
import re
import shutil
import struct
import subprocess
import sys
import tempfile
import time
import zipfile

CARTELLA = os.path.expanduser("~/nb-fonti")
VENV_IMG = os.path.join(CARTELLA, "venv-img", "bin", "python3")
PROFONDITA_MAX = 3      # allegati dentro allegati (uno zip in una mail inoltrata in un .p7m…): più giù non si scende
FILE_MAX = 60           # file aperti al massimo da una mail, archivi compresi
BYTE_MAX = 80_000_000   # byte al massimo da una mail, archivi scompattati compresi (contro gli archivi «bomba»)
OCR_SECONDI = 50        # tempo di OCR per giro: il cron dà 120 secondi a tutta la lettura della posta
OCR_PAGINE = 10         # pagine di una scansione lette con l'OCR
OCR_DPI = 300
OCR_CACHE = os.path.join(CARTELLA, "ocr")   # le pagine già lette con l'OCR (fuori dall'archivio): un giro riprende
OCR_CACHE_GIORNI = 10                        # dove si è fermato l'altro
OCR_PAROLE_MIN = 15     # un'immagine (non una scansione) passa solo con almeno tante parole lette bene…
OCR_FIDUCIA_MIN = 70    # …e con una fiducia media dell'OCR almeno così (le foto danno parole a caso)
TESTO_POCO = 600        # caratteri di testo della mail e dei documenti: sotto, anche le immagini passano dall'OCR
IMMAGINE_MIN = 60_000   # byte: sotto sono loghi e firme (come fonti_casa.py)
PDF_PAGINE_MAX = 2      # un PDF più lungo è un documento, non una locandina: la prima pagina diventa immagine solo così
PDF_SCANSIONE_PAGINE = 4   # di una scansione lunga le prime pagine diventano immagini, per l'agente

TESTO_FILE = (".txt", ".text", ".csv", ".tsv", ".md", ".ics", ".vcs")
HTML_FILE = (".html", ".htm", ".xhtml")
IMMAGINE_FILE = (".jpg", ".jpeg", ".jpe", ".jfif", ".png", ".gif", ".webp", ".bmp", ".tif", ".tiff", ".heic", ".heif")
MEDIA_FILE = (".mp4", ".m4v", ".mov", ".avi", ".mkv", ".wmv", ".webm", ".3gp", ".mpg", ".mpeg", ".mp3", ".m4a", ".wav",
              ".ogg", ".oga", ".opus", ".aac", ".amr", ".flac", ".wma")
# non sono documenti: firme, biglietti da visita, dati dei protocolli, programmi (mai aperti)
IGNORA_FILE = (".p7s", ".vcf", ".asc", ".sig", ".gpg", ".pgp", ".xml", ".json", ".css", ".js", ".exe", ".bat", ".cmd",
               ".com", ".scr", ".vbs", ".jar", ".msi", ".ps1", ".lnk", ".iso", ".img", ".apk", ".dll", ".ttf", ".otf",
               ".woff", ".woff2")
DOCUMENTI_SCRITTI = (".pdf", ".docx", ".docm", ".dotx", ".dotm", ".doc", ".dot", ".odt", ".ott", ".fodt", ".rtf",
                     ".xlsx", ".xlsm", ".xls", ".ods", ".pptx", ".ppsx", ".pptm", ".ppt", ".pps", ".odp", ".pages",
                     ".numbers", ".key") + TESTO_FILE + HTML_FILE   # quelli di cui testo_documento legge il testo
MIME_ESTENSIONE = {
    "application/pdf": ".pdf", "application/msword": ".doc", "application/rtf": ".rtf", "text/rtf": ".rtf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
    "application/vnd.oasis.opendocument.text": ".odt", "application/vnd.oasis.opendocument.spreadsheet": ".ods",
    "application/vnd.oasis.opendocument.presentation": ".odp", "application/vnd.ms-excel": ".xls",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": ".xlsx", "application/vnd.ms-powerpoint": ".ppt",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation": ".pptx", "application/zip": ".zip",
    "application/x-zip-compressed": ".zip", "application/x-7z-compressed": ".7z", "application/x-rar-compressed": ".rar",
    "application/vnd.rar": ".rar", "application/gzip": ".gz", "application/x-tar": ".tar", "application/ms-tnef": ".dat",
    "application/vnd.ms-tnef": ".dat", "application/pkcs7-mime": ".p7m", "application/x-pkcs7-mime": ".p7m",
    "application/pkcs7-signature": ".p7s", "application/x-pkcs7-signature": ".p7s", "text/calendar": ".ics",
    "text/csv": ".csv", "text/plain": ".txt", "text/html": ".html", "message/rfc822": ".eml",
    "application/vnd.ms-outlook": ".msg", "image/jpeg": ".jpg", "image/png": ".png", "image/gif": ".gif",
    "image/webp": ".webp", "image/tiff": ".tif", "image/heic": ".heic", "image/heif": ".heif", "image/bmp": ".bmp",
    "text/vcard": ".vcf", "text/x-vcard": ".vcf", "application/xml": ".xml", "text/xml": ".xml"}
# un link a un file da scaricare (il comunicato a volte è lì): lo apre l'agente
LINK_FILE = re.compile(r"https?://(?:drive\.google\.com|docs\.google\.com|(?:www\.)?dropbox\.com|dl\.dropboxusercontent\.com|"
                       r"(?:www\.)?wetransfer\.com|we\.tl|onedrive\.live\.com|1drv\.ms|[a-z0-9-]+\.sharepoint\.com|"
                       r"mega\.nz|(?:www\.)?icloud\.com|(?:www\.)?mediafire\.com|(?:www\.)?swisstransfer\.com|"
                       r"(?:www\.)?filemail\.com|(?:www\.)?smash\.gg|fromsmash\.com|(?:www\.)?jumbomail\.me)/[^\s<>\"')\]]+", re.I)
SEGNAPOSTO = re.compile(r"^(fare clic per|clic per|click to|modifica stili del testo|second level|third level|fourth "
                        r"level|fifth level|secondo livello|terzo livello|quarto livello|quinto livello)", re.I)

Foglia = collections.namedtuple("Foglia", "nome dati dentro problema tipo")   # un file da leggere (o perché no)


# ---------------------------------------------------------------- la mail

def nome_allegato(parte):
    """Il nome di un allegato, anche quando il programma di posta lo scrive codificato: «=?utf-8?Q?comunicato_stampa_-_
    ADOTTATO.docx?=» della Pro Loco di Fragneto Monforte, 25 ott 2026 (così non si capiva che era un .docx)."""
    nome = parte.get_filename() or ""
    if "=?" in nome:
        try:
            nome = str(email.header.make_header(email.header.decode_header(nome)))
        except (ValueError, LookupError, UnicodeDecodeError):
            pass
    return nome.strip()


def testo_html(frammento, massimo=10**7):
    """Il testo di una pagina HTML, una riga per paragrafo (come fonti_casa.testo)."""
    s = re.sub(r"<(script|style|nav|svg|form)[^>]*>.*?</\1>", " ", frammento, flags=re.S | re.I)
    s = re.sub(r"<(br|/p|/h\d|/li|/div|/tr)[^>]*>", "\n", s, flags=re.I)
    s = html.unescape(re.sub(r"<[^>]+>", " ", s))
    righe = [r.strip() for r in re.sub(r"[ \t\xa0]+", " ", s).split("\n")]
    return "\n".join(r for r in righe if r)[:massimo]


def testo_byte(dati, codifica=None):
    """Byte di testo in str: con la codifica dichiarata quella (come prima: i caratteri sbagliati diventano «�»); senza,
    UTF-8 (anche col BOM o in UTF-16) e se non lo è Windows-1252."""
    if codifica:
        try:
            return dati.decode(codifica, "replace")
        except LookupError:   # una codifica che non esiste («unknown-8bit»): si prova senza
            pass
    if dati[:2] in (b"\xff\xfe", b"\xfe\xff"):
        return dati.decode("utf-16", "replace")
    try:
        return dati.decode("utf-8-sig")
    except UnicodeDecodeError:
        return dati.decode("cp1252", "replace")


def _parti(m, radice=True):
    """Le parti finali di una mail, come m.walk(), ma una mail allegata (message/rfc822) resta un pezzo solo."""
    if not radice and m.get_content_type() in ("message/rfc822", "message/global"):
        yield m
    elif m.is_multipart():
        for p in m.get_payload():
            if isinstance(p, email.message.Message):
                yield from _parti(p, False)
    else:
        yield m


def _e_allegato(p):
    """Una parte che non è il testo della mail: ha un nome, o non è testo semplice né HTML."""
    return bool(nome_allegato(p)) or p.get_content_type() not in ("text/plain", "text/html")


def corpo_mail(m):
    """Il testo scritto nella mail: tra due versioni dello stesso testo (alternative) quella semplice se non è vuota, se
    no l'HTML ripulito; più pezzi di testo di seguito (Apple Mail spezza il testo intorno alle immagini) tutti, in
    ordine. Gli allegati e le mail allegate no."""
    if m.get_content_type() in ("message/rfc822", "message/global"):
        return ""
    if m.is_multipart():
        figli = [p for p in m.get_payload() if isinstance(p, email.message.Message)]
        if m.get_content_subtype() == "alternative":
            semplici = [t for t in (corpo_mail(p) for p in figli if p.get_content_type() == "text/plain") if t.strip()]
            altri = [t for t in (corpo_mail(p) for p in figli) if t.strip()]
            return (semplici or altri or [""])[-1]
        return "\n\n".join(t for t in (corpo_mail(p) for p in figli if p.is_multipart() or not _e_allegato(p))
                           if t.strip())
    if _e_allegato(m):
        return ""
    t = testo_byte(m.get_payload(decode=True) or b"", m.get_content_charset())
    return testo_html(t) if m.get_content_type() == "text/html" else t


def _intestazione(x):
    try:
        return str(email.header.make_header(email.header.decode_header(x or "")))
    except (ValueError, LookupError, UnicodeDecodeError):
        return str(x or "")


def _testo_mail_allegata(interna):
    """Il testo di una mail inoltrata come allegato: mittente (nome e dominio, mai l'indirizzo: come fonti_casa.py),
    data, oggetto e testo."""
    nome, indirizzo = email.utils.parseaddr(_intestazione(interna.get("From")))
    chi = f"{nome or indirizzo.split('@')[0]} (@{indirizzo.rsplit('@', 1)[-1]})" if indirizzo else nome
    righe = [f"Da: {chi}" if chi else "", f"Data: {interna.get('Date')}" if interna.get("Date") else "",
             f"Oggetto: {_intestazione(interna.get('Subject'))}"]
    return "\n".join(r for r in righe if r) + "\n\n" + corpo_mail(interna).strip()


# ---------------------------------------------------------------- che cos'è un file

def _estensione(nome):
    n = (nome or "").lower().strip()
    return n[n.rfind("."):] if "." in n else ""


def genere(dati, nome="", mime=""):
    """Che cos'è un file, dai primi byte e poi dal nome (o dal tipo MIME se non ha nome): pdf, ole (Word, Excel,
    PowerPoint vecchi), msg, rtf, docx, xlsx, pptx, odf, iwork, zip, archivio, p7m, tnef, eml, testo, html, immagine,
    media, ignora o sconosciuto."""
    est = _estensione(nome) or MIME_ESTENSIONE.get((mime or "").lower(), "")
    if est in IGNORA_FILE and est != ".xml":
        return "ignora"
    if dati[:5] == b"%PDF-":
        return "pdf"
    if dati[:8] == OLE:
        try:
            nomi = _flussi_ole(dati, solo_nomi=True)
        except Exception:
            return "sconosciuto"
        return "msg" if any(n.startswith("__substg1.0_") for n in nomi) else "ole"
    if dati[:5] == b"{\\rtf":
        return "rtf"
    if dati[:4] in (b"PK\x03\x04", b"PK\x05\x06", b"PK\x07\x08"):
        try:
            with zipfile.ZipFile(io.BytesIO(dati)) as z:
                nomi = set(z.namelist())
                tipo = z.read("mimetype")[:80].decode("ascii", "replace") if "mimetype" in nomi else ""
        except (zipfile.BadZipFile, OSError, ValueError, RuntimeError, NotImplementedError):
            return "zip"
        if "word/document.xml" in nomi:
            return "docx"
        if "xl/workbook.xml" in nomi:
            return "xlsx"
        if "ppt/presentation.xml" in nomi:
            return "pptx"
        if "content.xml" in nomi and (tipo.startswith("application/vnd.oasis") or not tipo):
            return "odf"
        if any(n.startswith(("QuickLook/", "Index/", "preview")) for n in nomi) and est in (".pages", ".numbers", ".key", ""):
            return "iwork"
        return "zip"
    if (dati[:6] == b"7z\xbc\xaf\x27\x1c" or dati[:7] == b"Rar!\x1a\x07\x00" or dati[:8] == b"Rar!\x1a\x07\x01\x00"
            or dati[:2] == b"\x1f\x8b" or dati[:6] == b"\xfd7zXZ\x00" or dati[:3] == b"BZh" or dati[257:262] == b"ustar"):
        return "archivio"
    if dati[:4] == b"\x78\x9f\x3e\x22":
        return "tnef"
    if (dati[:3] == b"\xff\xd8\xff" or dati[:8] == b"\x89PNG\r\n\x1a\n" or dati[:4] in (b"GIF8", b"II*\x00", b"MM\x00*")
            or (dati[:4] == b"RIFF" and dati[8:12] == b"WEBP") or (dati[:2] == b"BM" and est == ".bmp")
            or dati[4:12] in (b"ftypheic", b"ftypheix", b"ftyphevc", b"ftypheim", b"ftypheis", b"ftypmif1", b"ftypmsf1")):
        return "immagine"
    if (dati[4:8] == b"ftyp" or dati[:3] == b"ID3" or dati[:4] == b"OggS" or dati[:4] == b"\x1aE\xdf\xa3"
            or (dati[:4] == b"RIFF" and dati[8:12] in (b"WAVE", b"AVI ")) or dati[:2] in (b"\xff\xfb", b"\xff\xf3")
            or est in MEDIA_FILE):
        return "media"
    if est in (".p7m", ".p7c") or (dati[:1] == b"\x30" and b"\x06\x09\x2a\x86\x48\x86\xf7\x0d\x01\x07\x02" in dati[:64]):
        return "p7m"
    if b"%PDF-" in dati[:1024]:   # qualche PDF ha dei byte prima dell'intestazione
        return "pdf"
    if est == ".dat" and (nome or "").lower().startswith("winmail"):
        return "tnef"
    if est in (".eml", ".mht", ".mhtml") or (mime or "").lower() == "message/rfc822":
        return "eml"
    if est in HTML_FILE:
        return "html"
    if est in TESTO_FILE:
        return "testo"
    if est in IMMAGINE_FILE:
        return "immagine"
    if est in IGNORA_FILE:
        return "ignora"
    if not est and (mime or "").lower().startswith("text/"):
        return "html" if "html" in mime.lower() else "testo"
    return "sconosciuto"


def _e_tiff(dati):
    return dati[:4] in (b"II*\x00", b"MM\x00*")


def _e_heic(dati):
    return dati[4:12] in (b"ftypheic", b"ftypheix", b"ftyphevc", b"ftypheim", b"ftypheis", b"ftypmif1", b"ftypmsf1")


# ---------------------------------------------------------------- tutti i file di una mail, anche dentro gli altri

def foglie(m):
    """Ogni file allegato a una mail, anche dentro gli allegati che ne contengono altri (zip, 7z, rar, .p7m, winmail.dat,
    mail inoltrate .eml e .msg): Foglia(nome, dati, dentro, problema, tipo). «dentro» è dove sta («archivio.zip ›
    cartella»), «problema» perché non si è potuto aprire, tipo «mail» per il testo di una mail inoltrata."""
    conto = {"file": 0, "byte": 0}
    yield from _foglie_mail(m, "", 0, conto)


def _dove(dentro, nome):
    return f"{dentro} › {nome}" if dentro else nome


def _foglie_mail(m, dentro, prof, conto):
    for p in _parti(m):
        if not _e_allegato(p):
            continue
        if p.get_content_type() in ("message/rfc822", "message/global"):
            carico = p.get_payload()
            interna = carico[0] if isinstance(carico, list) and carico else \
                email.message_from_bytes(p.get_payload(decode=True) or b"")
            nome = nome_allegato(p) or f"mail allegata «{_intestazione(interna.get('Subject'))[:80]}»"
            yield from _foglie_mail_allegata(interna, nome, dentro, prof, conto)
            continue
        yield from _apri(nome_allegato(p), p.get_payload(decode=True) or b"", dentro, prof, conto, p.get_content_type())


def _foglie_mail_allegata(interna, nome, dentro, prof, conto):
    yield Foglia(nome, _testo_mail_allegata(interna).encode("utf-8"), dentro, "", "mail")
    if prof + 1 > PROFONDITA_MAX:
        yield Foglia(nome, b"", dentro, "allegati di una mail dentro troppi altri allegati: non aperti", "")
        return
    yield from _foglie_mail(interna, _dove(dentro, nome), prof + 1, conto)


def _apri(nome, dati, dentro, prof, conto, mime=""):
    conto["file"] += 1
    conto["byte"] += len(dati)
    if conto["file"] > FILE_MAX or conto["byte"] > BYTE_MAX:
        yield Foglia(nome, b"", dentro, "troppi file o troppo grandi in questa mail: non aperto", mime)
        return
    g = genere(dati, nome, mime)
    contenitore = g in ("zip", "archivio", "p7m", "tnef", "eml", "msg")
    if contenitore and prof + 1 > PROFONDITA_MAX:
        yield Foglia(nome, b"", dentro, "dentro troppi altri allegati: non aperto", mime)
        return
    dove = _dove(dentro, nome or "allegato")
    try:
        if g == "zip":
            yield from _zip(dati, dove, prof, conto)
        elif g == "archivio":
            yield from _archivio(dati, nome, dove, prof, conto)
        elif g == "p7m":
            interno = contenuto_p7m(dati)
            if interno is None:
                yield Foglia(nome, b"", dentro, "documento firmato (.p7m) che non si apre", mime)
            elif interno.lstrip()[:200].lower().startswith((b"content-type:", b"mime-version:", b"from:", b"received:")):
                yield from _foglie_mail_allegata(email.message_from_bytes(interno), nome, dentro, prof, conto)
            else:   # «comunicato.pdf.p7m» → «comunicato.pdf»
                yield from _apri(re.sub(r"\.p7[mc]$", "", nome, flags=re.I), interno, dentro, prof + 1, conto)
        elif g == "tnef":
            yield from _tnef(dati, nome, dove, prof, conto)
        elif g == "eml":
            yield from _foglie_mail_allegata(email.message_from_bytes(dati), nome, dentro, prof, conto)
        elif g == "msg":
            yield from _msg(_flussi_ole(dati), "", nome, dentro, prof, conto)
        else:
            yield Foglia(nome, dati, dentro, "", mime)
            if g in ("docx", "xlsx", "pptx", "odf"):
                yield from _immagini_ufficio(dati, dove)
    except Exception as e:   # un contenitore rotto non ferma la mail: si dice cosa
        yield Foglia(nome, b"", dentro, f"allegato rovinato o non apribile ({type(e).__name__})", mime)


def _nome_zip(info):
    """Il nome di un file in uno zip: quelli fatti con Windows senza UTF-8 Python li legge come cp437."""
    n = info.filename
    if not info.flag_bits & 0x800:
        try:
            n = n.encode("cp437").decode("utf-8")
        except (UnicodeEncodeError, UnicodeDecodeError):
            try:
                n = n.encode("cp437").decode("cp850")
            except (UnicodeEncodeError, UnicodeDecodeError):
                pass
    return n


def _inutile(percorso):
    base = os.path.basename(percorso.rstrip("/"))
    return (not base or percorso.endswith("/") or "__MACOSX/" in percorso or base.startswith("._")
            or base in (".DS_Store", "Thumbs.db", "desktop.ini"))


def _zip(dati, dove, prof, conto):
    with zipfile.ZipFile(io.BytesIO(dati)) as z:
        for info in z.infolist():
            percorso = _nome_zip(info)
            if _inutile(percorso):
                continue
            nome, cartella = os.path.basename(percorso), os.path.dirname(percorso)
            qui = _dove(dove, cartella) if cartella else dove
            if info.flag_bits & 0x1:
                yield Foglia(nome, b"", qui, "nell'archivio con la password", "")
                continue
            if info.file_size + conto["byte"] > BYTE_MAX:
                yield Foglia(nome, b"", qui, "troppo grande per aprirlo", "")
                continue
            yield from _apri(nome, z.read(info), qui, prof + 1, conto)


def _archivio(dati, nome, dove, prof, conto):
    """7z, rar, tar, gz, bz2, xz: con il programma 7z, prima l'elenco (password? troppo grande?) e poi l'estrazione."""
    sette = shutil.which("7z") or shutil.which("7zz") or shutil.which("7za")
    if not sette:
        yield Foglia(nome, b"", os.path.dirname(dove), "archivio compresso, ma sul Pi manca il programma 7z", "")
        return
    with tempfile.TemporaryDirectory() as td:
        f = os.path.join(td, "archivio" + (_estensione(nome) or ".bin"))
        with open(f, "wb") as fh:
            fh.write(dati)
        r = subprocess.run([sette, "l", "-slt", "-ba", "-pnessuna", f], capture_output=True, timeout=60)
        elenco = r.stdout.decode("utf-8", "replace")
        if r.returncode or "Wrong password" in elenco or re.search(r"^Encrypted = \+", elenco, re.M):
            yield Foglia(nome, b"", os.path.dirname(dove), "archivio con la password (o rovinato)", "")
            return
        dimensioni = [int(x) for x in re.findall(r"^Size = (\d+)", elenco, re.M)]
        if sum(dimensioni) + conto["byte"] > BYTE_MAX or len(dimensioni) > FILE_MAX:
            yield Foglia(nome, b"", os.path.dirname(dove), "archivio troppo grande per aprirlo", "")
            return
        fuori = os.path.join(td, "fuori")
        r = subprocess.run([sette, "x", "-y", "-pnessuna", f"-o{fuori}", f], capture_output=True, timeout=120)
        if r.returncode:
            yield Foglia(nome, b"", os.path.dirname(dove), "archivio che non si apre", "")
            return
        for radice, _, files in sorted(os.walk(fuori)):
            for n in sorted(files):
                percorso = os.path.relpath(os.path.join(radice, n), fuori)
                if _inutile(percorso) or os.path.islink(os.path.join(radice, n)):
                    continue
                with open(os.path.join(radice, n), "rb") as fh:
                    cartella = os.path.dirname(percorso)
                    yield from _apri(n, fh.read(), _dove(dove, cartella) if cartella else dove, prof + 1, conto)


def _immagini_ufficio(dati, dove):
    """Le immagini dentro un documento Word, Excel, PowerPoint o LibreOffice (una locandina incollata nel comunicato)."""
    with zipfile.ZipFile(io.BytesIO(dati)) as z:
        for info in z.infolist():
            if (re.match(r"^(word|xl|ppt)/media/|^Pictures/|^media/", info.filename)
                    and info.filename.lower().endswith(IMMAGINE_FILE) and info.file_size < 30_000_000):
                yield Foglia(os.path.basename(info.filename), z.read(info), dove, "", "immagine nel documento")


def contenuto_p7m(dati):
    """Il documento dentro un .p7m firmato (CAdES), con openssl; None se non si apre. La firma non si verifica: si
    legge solo il contenuto."""
    with tempfile.TemporaryDirectory() as td:
        ingresso, uscita = os.path.join(td, "a.p7m"), os.path.join(td, "a.out")
        with open(ingresso, "wb") as f:
            f.write(dati)
        for forma in ("DER", "PEM"):
            try:
                r = subprocess.run(["openssl", "cms", "-verify", "-noverify", "-binary", "-inform", forma,
                                    "-in", ingresso, "-out", uscita], capture_output=True, timeout=60)
            except (OSError, subprocess.SubprocessError):
                return None
            if r.returncode == 0 and os.path.getsize(uscita):
                with open(uscita, "rb") as f:
                    return f.read()
        if re.match(rb"^[A-Za-z0-9+/=\r\n]+$", dati[:200]):   # a volte il .p7m è in base64 senza intestazioni
            try:
                return contenuto_p7m(base64.b64decode(dati))
            except ValueError:
                pass
    return None


def _tnef(dati, nome, dove, prof, conto):
    """winmail.dat (Outlook, «Rich Text»): il testo e gli allegati veri che ci sono dentro."""
    if dati[:4] != b"\x78\x9f\x3e\x22":
        yield Foglia(nome, b"", os.path.dirname(dove), "winmail.dat rovinato", "")
        return
    pos, corpo, allegati, attuale = 6, "", [], None
    while pos + 9 <= len(dati):
        livello, attributo, lunghezza = struct.unpack_from("<BII", dati, pos)
        valore = dati[pos + 9:pos + 9 + lunghezza]
        pos += 9 + lunghezza + 2
        ident = attributo & 0xFFFF
        if ident == 0x9002:   # attAttachRendData: comincia un allegato
            attuale = {"nome": "", "dati": b""}
            allegati.append(attuale)
        elif ident == 0x8010 and attuale is not None:   # attAttachTitle
            attuale["nome"] = valore.rstrip(b"\0").decode("cp1252", "replace")
        elif ident == 0x800F and attuale is not None:   # attAttachData
            attuale["dati"] = valore
        elif ident == 0x9005 and attuale is not None:   # attAttachment: proprietà, tra cui il nome lungo
            lungo = _tnef_nome_lungo(valore)
            if lungo:
                attuale["nome"] = lungo
        elif ident == 0x800C and livello == 1:   # attBody
            corpo = valore.rstrip(b"\0").decode("cp1252", "replace")
    if corpo.strip():
        yield Foglia(f"{nome} (testo)", corpo.encode("utf-8"), os.path.dirname(dove), "", "mail")
    for a in allegati:
        if a["dati"]:
            yield from _apri(a["nome"] or "allegato", a["dati"], dove, prof + 1, conto)


def _tnef_nome_lungo(v):
    """PR_ATTACH_LONG_FILENAME (0x3707) dalle proprietà MAPI di un allegato TNEF; '' se non c'è o non si capisce."""
    try:
        quante, pos = struct.unpack_from("<I", v, 0)[0], 4
        for _ in range(min(quante, 500)):
            tipo, ident = struct.unpack_from("<HH", v, pos)
            pos += 4
            if ident >= 0x8000:   # proprietà con nome: GUID, tipo di nome, nome
                tipo_nome = struct.unpack_from("<I", v, pos + 16)[0]
                pos += 20
                if tipo_nome == 0:
                    pos += 4
                else:
                    n = struct.unpack_from("<I", v, pos)[0]
                    pos += 4 + n + (-n % 4)
            multi = tipo & 0x1000
            base = tipo & 0x0FFF
            conta = 1
            if multi or base in (0x001E, 0x001F, 0x0102, 0x000D):
                conta = struct.unpack_from("<I", v, pos)[0]
                pos += 4
            for _ in range(conta):
                if base in (0x001E, 0x001F, 0x0102, 0x000D):
                    n = struct.unpack_from("<I", v, pos)[0]
                    dato = v[pos + 4:pos + 4 + n]
                    pos += 4 + n + (-n % 4)
                    if ident == 0x3707 and base in (0x001E, 0x001F):
                        return dato.decode("utf-16-le" if base == 0x001F else "cp1252", "replace").rstrip("\0")
                else:
                    pos += {0x0002: 4, 0x0003: 4, 0x000B: 4, 0x0004: 4, 0x0005: 8, 0x0006: 8, 0x0007: 8, 0x0014: 8,
                            0x0040: 8, 0x0048: 16}.get(base, 4)
    except struct.error:
        pass
    return ""


def _msg(fl, prefisso, nome, dentro, prof, conto):
    """Una mail di Outlook salvata (.msg, contenitore OLE): oggetto, testo e allegati, anche le mail dentro la mail."""
    def stringa(prop, dove=prefisso):
        for coda, cod in (("001F", "utf-16-le"), ("001E", "cp1252")):
            v = fl.get(f"{dove}__substg1.0_{prop}{coda}")
            if v is not None:
                return v.decode(cod, "replace").rstrip("\0")
        return ""
    corpo = stringa("1000")
    if not corpo.strip() and f"{prefisso}__substg1.0_10130102" in fl:   # solo HTML
        corpo = testo_html(testo_byte(fl[f"{prefisso}__substg1.0_10130102"]))
    chi = stringa("0C1A") or stringa("0042")
    testo = "\n".join(r for r in (f"Da: {chi}" if chi else "", f"Oggetto: {stringa('0037')}") if r) + "\n\n" + corpo.strip()
    yield Foglia(nome, testo.encode("utf-8"), dentro, "", "mail")
    if prof + 1 > PROFONDITA_MAX:
        return
    dove = _dove(dentro, nome)
    allegati = sorted({k[len(prefisso):].split("/")[0] for k in fl if k.startswith(prefisso + "__attach_version1.0_#")})
    for a in allegati:
        pa = f"{prefisso}{a}/"
        nome_a = stringa("3707", pa) or stringa("3704", pa) or stringa("3001", pa) or "allegato"
        if any(k.startswith(pa + "__substg1.0_3701000D/") for k in fl):   # una mail allegata alla mail
            yield from _msg(fl, pa + "__substg1.0_3701000D/", nome_a, dove, prof + 1, conto)
        elif pa + "__substg1.0_37010102" in fl:
            yield from _apri(nome_a, fl[pa + "__substg1.0_37010102"], dove, prof + 1, conto)


# ---------------------------------------------------------------- il testo di un documento

def testo_documento(dati, nome):
    """Il testo di un documento (un file solo, non un archivio), senza OCR: per la scheda Posta e per chi non ha tempo
    di aspettare. '' se non si legge."""
    return leggi_documento(dati, nome, ocr=False)[0]


def leggi_documento(dati, nome, ocr=False, mime=""):
    """(testo, problema, con_ocr) di un documento: problema è '' se si è letto tutto, se no il perché («scansione:
    l'OCR non è installato», «con la password»…); con_ocr è True se il testo viene dall'OCR."""
    g = genere(dati, nome, mime)
    try:
        if g == "pdf":
            return _pdf(dati, ocr)
        if g == "ole":
            return _ole(dati)
        if g == "rtf":
            return _vuoto(testo_rtf(dati), "RTF senza testo")
        if g in ("docx", "odf"):
            return _vuoto(_testo_xml_ufficio(dati), "documento senza testo (forse solo immagini)")
        if g == "xlsx":
            return _vuoto(_xlsx(dati), "foglio di calcolo vuoto")
        if g == "pptx":
            return _vuoto(_pptx(dati), "presentazione senza testo (forse solo immagini)")
        if g == "iwork":
            return _iwork(dati, ocr)
        if g == "testo":
            return _vuoto(testo_byte(dati).strip(), "file di testo vuoto")
        if g == "html":
            return _vuoto(testo_html(testo_byte(dati)), "pagina HTML vuota")
        if g == "immagine" and _e_tiff(dati):
            return _scansione_immagine(dati, ocr)
    except Exception as e:   # un documento rovinato: si dice, non si ferma niente
        return "", f"documento rovinato o non leggibile ({type(e).__name__})", False
    return "", "formato non conosciuto", False


def _vuoto(t, problema):
    return (t, "", False) if t.strip() else ("", problema, False)


_PDF = {}   # impronta del PDF → (testo, pagine): pdftotext una volta sola per giro


def _pdf_testo(dati):
    chiave = hashlib.sha1(dati).hexdigest()
    if chiave not in _PDF:
        with tempfile.TemporaryDirectory() as td:
            f = os.path.join(td, "a.pdf")
            with open(f, "wb") as fh:
                fh.write(dati)
            info = subprocess.run(["pdfinfo", f], capture_output=True, timeout=30)
            if b"Incorrect password" in info.stderr:
                _PDF[chiave] = (None, 0)
            else:
                pagine = re.search(rb"^Pages:\s+(\d+)", info.stdout, re.M)
                r = subprocess.run(["pdftotext", "-layout", f, "-"], capture_output=True, timeout=60)
                _PDF[chiave] = (r.stdout.decode("utf-8", "replace"), int(pagine[1]) if pagine else 0)
    return _PDF[chiave]


def pdf_scansione(dati):
    """True se il PDF è una scansione (quasi senza testo: meno di 40 caratteri per pagina)."""
    t, pagine = _pdf_testo(dati)
    return t is not None and len(re.sub(r"\s", "", t)) < 40 * max(pagine, 1)


def _pdf(dati, ocr):
    t, pagine = _pdf_testo(dati)
    if t is None:
        return "", "PDF con la password", False
    if not pdf_scansione(dati):
        return t, "", False
    if not ocr:
        return t.strip(), "PDF senza testo (scansione): va letto con l'OCR", False
    if not tesseract():
        return t.strip(), "PDF senza testo (scansione) e sul Pi l'OCR non è installato", False
    letto, fatte = ocr_pdf(dati, pagine)
    if fatte < min(pagine, OCR_PAGINE):
        return letto, f"scansione di {pagine} pagine: lette con l'OCR {fatte}, le altre al prossimo giro", True
    if pagine > OCR_PAGINE:
        return letto, f"scansione di {pagine} pagine: lette con l'OCR solo le prime {OCR_PAGINE}", True
    return _vuoto(letto, "scansione in cui l'OCR non trova testo")[:2] + (True,)


def _iwork(dati, ocr):
    """Pages, Numbers, Keynote: dentro c'è un PDF di anteprima (i file più vecchi) o solo una piccola immagine."""
    with zipfile.ZipFile(io.BytesIO(dati)) as z:
        for n in z.namelist():
            if n.lower().endswith(".pdf") and ("quicklook" in n.lower() or "preview" in n.lower()):
                return _pdf(z.read(n), ocr)
    return "", "file di Apple (Pages, Numbers o Keynote) senza anteprima: va esportato in PDF", False


def _testo_xml_ufficio(dati):
    """Il testo di un .docx (Word) o di un .odt/.ods/.odp (LibreOffice), che sono zip con dentro l'XML.
    Dal 25 ott 2026: il comunicato della Pro Loco di Fragneto Monforte era solo nel .docx e il giro lampo l'ha scartato."""
    with zipfile.ZipFile(io.BytesIO(dati)) as z:
        x = z.read("word/document.xml" if "word/document.xml" in z.namelist() else "content.xml").decode("utf-8", "replace")
    x = re.sub(r"<(w:tab|text:tab)\b[^>]*/>", "\t", x)
    x = re.sub(r"<text:s\b[^>]*/>", " ", x)
    x = re.sub(r"<(w:br|w:cr|text:line-break)\b[^>]*/>|</(w:p|text:p|text:h)>", "\n", x)
    x = html.unescape(re.sub(r"<[^>]+>", "", x))
    return re.sub(r"\n{3,}", "\n\n", re.sub(r"[ \t]+\n", "\n", x)).strip()


def _xml(z, nome):
    import xml.etree.ElementTree as ET
    return ET.fromstring(z.read(nome))


def _locale(tag):
    return tag.rsplit("}", 1)[-1]


# le date di Excel sono numeri (giorni dal 1900) con un formato da data: i formati predefiniti e quelli con d, m, y, h
DATE_EXCEL = set(range(14, 23)) | {27, 28, 29, 30, 31, 34, 35, 36, 45, 46, 47, 50, 51, 52, 53, 54, 55, 56, 57, 58}


def _formato_data(codice):
    c = re.sub(r'"[^"]*"|\[[^\]]*\]|\\.', "", codice or "").lower()
    return bool(re.search(r"[dmyh]", c)) and not re.search(r"^[#0.,%\s]*$", c)


def _numero_excel(v, data=False, dal_1904=False):
    try:
        x = float(v)
    except (TypeError, ValueError):
        return str(v or "")
    if data and 0 < x < 2958466:
        base = dt.datetime(1904, 1, 1) if dal_1904 else dt.datetime(1899, 12, 30)
        d = base + dt.timedelta(days=x)
        return d.strftime("%d/%m/%Y" if d.hour == d.minute == 0 else "%d/%m/%Y %H:%M") if x >= 1 else d.strftime("%H:%M")
    return str(int(x)) if x == int(x) else f"{x:g}".replace(".", ",")


def _xlsx(dati):
    """Il testo di un foglio Excel (.xlsx): un foglio dopo l'altro, una riga per riga, le caselle separate da tab."""
    with zipfile.ZipFile(io.BytesIO(dati)) as z:
        nomi = z.namelist()
        condivise = []
        if "xl/sharedStrings.xml" in nomi:
            for si in _xml(z, "xl/sharedStrings.xml"):
                condivise.append("".join(t.text or "" for t in si.iter() if _locale(t.tag) == "t"))
        date_stili, dal_1904 = set(), False
        if "xl/styles.xml" in nomi:
            st = _xml(z, "xl/styles.xml")
            formati = {int(f.get("numFmtId")): f.get("formatCode") for f in st.iter() if _locale(f.tag) == "numFmt"}
            for x in st.iter():
                if _locale(x.tag) == "cellXfs":
                    for k, xf in enumerate(c for c in x if _locale(c.tag) == "xf"):
                        n = int(xf.get("numFmtId") or 0)
                        if n in DATE_EXCEL or _formato_data(formati.get(n)):
                            date_stili.add(k)
        if "xl/workbook.xml" in nomi:
            dal_1904 = any(_locale(x.tag) == "workbookPr" and x.get("date1904") in ("1", "true") for x in _xml(z, "xl/workbook.xml").iter())
        fogli = sorted((n for n in nomi if re.match(r"^xl/worksheets/sheet\d+\.xml$", n)),
                       key=lambda n: int(re.search(r"(\d+)\.xml$", n)[1]))
        out = []
        for f in fogli:
            righe = []
            for r in (x for x in _xml(z, f).iter() if _locale(x.tag) == "row"):
                caselle = []
                for c in (x for x in r if _locale(x.tag) == "c"):
                    t, v = c.get("t"), next((x.text for x in c if _locale(x.tag) == "v"), None)
                    if t == "s" and v is not None:
                        caselle.append(condivise[int(v)] if int(v) < len(condivise) else "")
                    elif t == "inlineStr":
                        caselle.append("".join(x.text or "" for x in c.iter() if _locale(x.tag) == "t"))
                    elif t in ("str", "b", "e"):
                        caselle.append(v or "")
                    elif v is not None:
                        caselle.append(_numero_excel(v, int(c.get("s") or 0) in date_stili, dal_1904))
                if any(x.strip() for x in caselle):
                    righe.append("\t".join(caselle).rstrip())
            if righe:
                out.append("\n".join(righe))
    return "\n\n".join(out).strip()


def _pptx(dati):
    """Il testo di una presentazione PowerPoint (.pptx): una diapositiva dopo l'altra, un paragrafo per riga."""
    with zipfile.ZipFile(io.BytesIO(dati)) as z:
        diapositive = sorted((n for n in z.namelist() if re.match(r"^ppt/slides/slide\d+\.xml$", n)),
                             key=lambda n: int(re.search(r"(\d+)\.xml$", n)[1]))
        out = []
        for d in diapositive:
            paragrafi = []
            for p in (x for x in _xml(z, d).iter() if _locale(x.tag) == "p"):
                t = "".join(x.text or "" for x in p.iter() if _locale(x.tag) == "t").strip()
                if t:
                    paragrafi.append(t)
            if paragrafi:
                out.append("\n".join(paragrafi))
    return "\n\n".join(out).strip()


# ---------------------------------------------------------------- i formati vecchi di Office (contenitore OLE)

# Il Word vecchio (.doc, da Word 97 a Word 2003), l'Excel vecchio (.xls) e il PowerPoint vecchio (.ppt) si leggono qui,
# senza programmi in più sul Pi: sono contenitori OLE (formato pubblico di Microsoft, [MS-CFB]) con dentro i flussi del
# documento ([MS-DOC], [MS-XLS], [MS-PPT]). Anche le mail di Outlook salvate (.msg) sono contenitori OLE.
OLE = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
FINE_CATENA = 0xFFFFFFFA   # da qui in su i numeri dei settori vogliono dire «fine», «libero», «settore della FAT»…


def _flussi_ole(dati, solo_nomi=False):
    """{percorso: byte} dei flussi di un contenitore OLE: quelli nella radice col loro nome («WordDocument»), quelli
    nelle cartelle col percorso («__attach_version1.0_#00000000/__substg1.0_37010102»)."""
    if dati[:8] != OLE:
        raise ValueError("non è un contenitore OLE")
    settore_dim, mini_dim = 1 << struct.unpack_from("<H", dati, 30)[0], 1 << struct.unpack_from("<H", dati, 32)[0]
    n_fat, cartella_da, _, soglia, minifat_da, _, difat_da, n_difat = struct.unpack_from("<8I", dati, 44)
    settore = lambda s: dati[(s + 1) * settore_dim:(s + 2) * settore_dim]

    def catena(s, tabella, leggi):   # i pezzi di un flusso, seguendo la tabella dei settori (senza giri infiniti)
        out, visti = [], set()
        while s < FINE_CATENA and s not in visti and s < len(tabella):
            visti.add(s)
            out.append(leggi(s))
            s = tabella[s]
        return b"".join(out)

    difat, s = list(struct.unpack_from("<109I", dati, 76)), difat_da
    for _ in range(min(n_difat, len(dati) // settore_dim)):   # i file grandi hanno altri settori della FAT, in una catena
        if s >= FINE_CATENA:
            break
        b = settore(s)
        difat += struct.unpack_from(f"<{settore_dim // 4 - 1}I", b, 0)
        s = struct.unpack_from("<I", b, settore_dim - 4)[0]
    fat = [x for s in difat[:n_fat] if s < FINE_CATENA for x in struct.unpack_from(f"<{settore_dim // 4}I", settore(s), 0)]
    cartella = catena(cartella_da, fat, settore)
    voci = [cartella[k:k + 128] for k in range(0, len(cartella) - 127, 128)]
    if not voci:
        raise ValueError("contenitore OLE senza elenco dei flussi")
    radice = voci[0]
    mini = minifat = None
    flussi, da_vedere, visti = {}, [(struct.unpack_from("<I", radice, 76)[0], "")], set()
    while da_vedere:   # i figli di ogni cartella sono un albero: fratelli a sinistra e a destra, figli sotto
        i, cartella_di = da_vedere.pop()
        if i >= len(voci) or i in visti:
            continue
        visti.add(i)
        v = voci[i]
        sinistra, destra, figlio = struct.unpack_from("<3I", v, 68)
        da_vedere += [(sinistra, cartella_di), (destra, cartella_di)]
        nome = v[:max(struct.unpack_from("<H", v, 64)[0] - 2, 0)].decode("utf-16-le", "replace")
        if v[66] == 1:   # una cartella: i suoi figli hanno il percorso davanti
            da_vedere.append((figlio, f"{cartella_di}{nome}/"))
            continue
        if v[66] != 2:   # 2 = flusso (5 = radice)
            continue
        if solo_nomi:
            flussi[cartella_di + nome] = b""
            continue
        inizio, dim = struct.unpack_from("<IQ", v, 116)
        if settore_dim == 512:   # nei file da 512 byte la metà alta della lunghezza può essere sporca
            dim &= 0xFFFFFFFF
        if dim < soglia:
            if mini is None:   # i flussi piccoli stanno tutti in un flusso solo, a pezzi da 64 byte
                mini = catena(struct.unpack_from("<I", radice, 116)[0], fat, settore)
                minifat_b = catena(minifat_da, fat, settore)
                minifat = struct.unpack_from(f"<{len(minifat_b) // 4}I", minifat_b, 0)
            flussi[cartella_di + nome] = catena(inizio, minifat, lambda s: mini[s * mini_dim:(s + 1) * mini_dim])[:dim]
        else:
            flussi[cartella_di + nome] = catena(inizio, fat, settore)[:dim]
    return flussi


def _ole(dati):
    fl = _flussi_ole(dati)
    if "EncryptedPackage" in fl or "EncryptionInfo" in fl:
        return "", "documento di Office con la password", False
    if "WordDocument" in fl:
        return _vuoto(testo_doc(dati, fl), "Word vecchio che non si legge (Word 6/95, o con la password)")
    if "Workbook" in fl or "Book" in fl:
        return _vuoto(_xls(fl.get("Workbook") or fl["Book"]), "Excel vecchio che non si legge (o vuoto)")
    if "PowerPoint Document" in fl:
        return _vuoto(_ppt(fl["PowerPoint Document"]), "PowerPoint vecchio senza testo (forse solo immagini)")
    return "", "documento di Office vecchio di un tipo non conosciuto", False


def testo_doc(dati, flussi=None):
    """Il testo del corpo di un Word vecchio (.doc); '' se non si legge (anche Word 6/95 e documenti con la password).
    Dal 26 ott 2026: il comunicato del San Pio delle 12:12 era solo in un .doc e il giro lampo l'ha scartato."""
    try:
        flussi = flussi or _flussi_ole(dati)
        w = flussi["WordDocument"]
        firma, versione, _, _, _, segni = struct.unpack_from("<6H", w, 0)
        if firma != 0xA5EC or versione < 0x65 or segni & 0x0100:   # non Word 97 o più nuovo, o con la password
            return ""
        tabella = flussi["1Table" if segni & 0x0200 else "0Table"]
        csw = struct.unpack_from("<H", w, 32)[0]
        cslw = struct.unpack_from("<H", w, 34 + csw * 2)[0]
        corpo = struct.unpack_from("<i", w, 36 + csw * 2 + 12)[0]   # ccpText: i caratteri del corpo (poi note, testate…)
        clx_da, clx_dim = struct.unpack_from("<II", w, 38 + csw * 2 + cslw * 4 + 33 * 8)   # fcClx, lcbClx
        clx, i = tabella[clx_da:clx_da + clx_dim], 0
        while i < len(clx) and clx[i] == 1:   # le formattazioni (Prc) prima dei pezzi: si saltano
            i += 3 + struct.unpack_from("<h", clx, i + 1)[0]
        if i >= len(clx) or clx[i] != 2:
            return ""
        dim = struct.unpack_from("<I", clx, i + 1)[0]
        n = (dim - 4) // 12
        cp = struct.unpack_from(f"<{n + 1}I", clx, i + 5)
        pezzi = []
        for k in range(n):   # ogni pezzo: in 8 bit (Windows-1252) o in 16 bit (UTF-16), in un punto di WordDocument
            fc = struct.unpack_from("<I", clx, i + 5 + 4 * (n + 1) + 8 * k + 2)[0]
            quanti = cp[k + 1] - cp[k]
            if fc & 0x40000000:
                da = (fc & 0x3FFFFFFF) // 2
                pezzi.append(w[da:da + quanti].decode("cp1252", "replace"))
            else:
                pezzi.append(w[fc:fc + 2 * quanti].decode("utf-16-le", "replace"))
        t = "".join(pezzi)[:corpo]
    except (ValueError, KeyError, IndexError, struct.error, OverflowError, MemoryError):
        return ""
    out, campi = [], []   # i campi (collegamenti, numeri di pagina): \x13 codice \x14 quello che si vede \x15
    for c in t:
        if c == "\x13":
            campi.append(False)
        elif c == "\x14" and campi:
            campi[-1] = True
        elif c == "\x15" and campi:
            campi.pop()
        elif all(campi):
            out.append(c)
    t = "".join(out).replace("\x07\x07", "\x07\n")   # nelle tabelle \x07 chiude la casella, due di fila la riga
    t = t.translate({0x0D: "\n", 0x0B: "\n", 0x0C: "\n", 0x07: "\t", 0x1E: "-", 0xA0: " "})
    t = re.sub(r"[\x00-\x08\x0e-\x1f]", "", t)   # immagini, rimandi alle note, trattini facoltativi
    return re.sub(r"\n{3,}", "\n\n", re.sub(r"[ \t]+\n", "\n", t)).strip()


def _record_biff(w):
    """I record di un flusso Excel vecchio (BIFF8): (tipo, dati)."""
    pos = 0
    while pos + 4 <= len(w):
        tipo, n = struct.unpack_from("<HH", w, pos)
        yield tipo, w[pos + 4:pos + 4 + n]
        pos += 4 + n


def _stringa_biff(seg, k, pos, cch):
    """Una stringa BIFF8 che può continuare nei record CONTINUE (seg: i pezzi): (testo, k, pos) dopo i caratteri."""
    segni = seg[k][pos]
    pos += 1
    ricco = struct.unpack_from("<H", seg[k], pos)[0] if segni & 0x08 else 0
    pos += 2 if segni & 0x08 else 0
    esteso = struct.unpack_from("<I", seg[k], pos)[0] if segni & 0x04 else 0
    pos += 4 if segni & 0x04 else 0
    testo, presi = "", 0
    while True:
        larghi = segni & 0x01
        quanti = min((len(seg[k]) - pos) // (2 if larghi else 1), cch - presi)
        pezzo = seg[k][pos:pos + quanti * (2 if larghi else 1)]
        testo += pezzo.decode("utf-16-le" if larghi else "latin-1", "replace")
        pos += len(pezzo)
        presi += quanti
        if presi >= cch:
            break
        k, pos = k + 1, 0   # la stringa continua nel record dopo, che comincia con i suoi segni (8 o 16 bit)
        segni = seg[k][0]
        pos = 1
    salta = 4 * ricco + esteso   # le formattazioni e i dati fonetici dopo i caratteri
    while salta:
        resto = len(seg[k]) - pos
        if salta <= resto:
            pos += salta
            break
        salta -= resto
        k, pos = k + 1, 0
    return testo, k, pos


def _xls(w):
    """Il testo di un Excel vecchio (.xls, BIFF8): un foglio dopo l'altro, una riga per riga, caselle separate da tab."""
    sst, formati, xf, dal_1904 = [], {}, [], False
    fogli, caselle, nel_foglio = [], {}, -1
    record = list(_record_biff(w))
    for i, (tipo, d) in enumerate(record):
        if tipo == 0x0809:   # BOF: il primo è la cartella, poi un foglio per volta
            nel_foglio += 1
            caselle = {}
            fogli.append(caselle)
        elif tipo == 0x0022 and len(d) >= 2:   # DATEMODE
            dal_1904 = struct.unpack_from("<H", d, 0)[0] == 1
        elif tipo == 0x041E and len(d) >= 5:   # FORMAT
            n, cch = struct.unpack_from("<HH", d, 0)
            formati[n] = _stringa_biff([d], 0, 4, cch)[0]
        elif tipo == 0x00E0 and len(d) >= 4:   # XF
            xf.append(struct.unpack_from("<H", d, 2)[0])
        elif tipo == 0x00FC:   # SST, con i CONTINUE che lo seguono
            seg = [d] + [x for _, x in itertools.takewhile(lambda r: r[0] == 0x003C, record[i + 1:])]
            totale = struct.unpack_from("<I", d, 4)[0]
            k, pos = 0, 8
            for _ in range(totale):
                if pos >= len(seg[k]):
                    k, pos = k + 1, 0
                if k >= len(seg):
                    break
                cch = struct.unpack_from("<H", seg[k], pos)[0]
                t, k, pos = _stringa_biff(seg, k, pos + 2, cch)
                sst.append(t)
        elif nel_foglio > 0 and len(d) >= 6:
            riga, col, stile = struct.unpack_from("<HHH", d, 0)
            data = lambda: stile < len(xf) and (xf[stile] in DATE_EXCEL or _formato_data(formati.get(xf[stile])))
            if tipo == 0x00FD and len(d) >= 10:   # LABELSST
                n = struct.unpack_from("<I", d, 6)[0]
                caselle[(riga, col)] = sst[n] if n < len(sst) else ""
            elif tipo == 0x0204 and len(d) >= 8:   # LABEL
                caselle[(riga, col)] = _stringa_biff([d], 0, 8, struct.unpack_from("<H", d, 6)[0])[0]
            elif tipo == 0x0203 and len(d) >= 14:   # NUMBER
                caselle[(riga, col)] = _numero_excel(struct.unpack_from("<d", d, 6)[0], data(), dal_1904)
            elif tipo == 0x027E and len(d) >= 10:   # RK
                caselle[(riga, col)] = _numero_excel(_rk(struct.unpack_from("<I", d, 6)[0]), data(), dal_1904)
            elif tipo == 0x00BD and len(d) >= 12:   # MULRK: più numeri di fila
                for j in range((len(d) - 6) // 6):
                    st, rk = struct.unpack_from("<HI", d, 4 + 6 * j)
                    stile = st
                    caselle[(riga, col + j)] = _numero_excel(_rk(rk), data(), dal_1904)
    out = []
    for c in fogli[1:]:
        righe = {}
        for (r, k), v in c.items():
            righe.setdefault(r, {})[k] = v
        testo = "\n".join("\t".join(cc.get(k, "") for k in range(max(cc) + 1)).rstrip() for _, cc in sorted(righe.items())
                          if any(str(x).strip() for x in cc.values()))
        if testo.strip():
            out.append(testo)
    return "\n\n".join(out).strip()


def _rk(rk):
    """Un numero RK di Excel (intero o decimale compresso in 32 bit)."""
    if rk & 0x02:   # un intero di 30 bit col segno
        x = float((rk >> 2) - (1 << 30) if rk & 0x80000000 else rk >> 2)
    else:           # i 30 bit alti di un numero decimale
        x = struct.unpack("<d", struct.pack("<Q", (rk & 0xFFFFFFFC) << 32))[0]
    return x / 100 if rk & 0x01 else x


def _ppt(w):
    """Il testo di un PowerPoint vecchio (.ppt): i testi delle diapositive (TextCharsAtom, TextBytesAtom), senza quelli
    dei modelli («Fare clic per modificare…»)."""
    out, pos, visti = [], 0, set()
    while pos + 8 <= len(w):
        versione_istanza, tipo, n = struct.unpack_from("<HHI", w, pos)
        if versione_istanza & 0x000F == 0x000F:   # un contenitore: si entra dentro
            pos += 8
            continue
        d = w[pos + 8:pos + 8 + n]
        pos += 8 + n
        if tipo == 0x0FA0:
            t = d.decode("utf-16-le", "replace")
        elif tipo == 0x0FA8:
            t = d.decode("cp1252", "replace")
        else:
            continue
        t = t.replace("\r", "\n").replace("\x0b", "\n").strip()
        if t and not SEGNAPOSTO.match(t) and t not in visti:   # lo stesso testo può stare anche nelle versioni vecchie
            visti.add(t)
            out.append(t)
    return "\n\n".join(out).strip()


# ---------------------------------------------------------------- RTF

RTF_SALTA = {"fonttbl", "colortbl", "stylesheet", "info", "pict", "object", "header", "headerl", "headerr", "headerf",
             "footer", "footerl", "footerr", "footerf", "fldinst", "themedata", "colorschememapping", "latentstyles",
             "datastore", "xmlnstbl", "listtable", "listoverridetable", "rsidtbl", "generator", "filetbl", "revtbl",
             "pgdsctbl", "shppict", "nonshppict", "xe", "tc"}   # le parti che non sono testo da leggere
RTF_SEGNI = {"par": "\n", "line": "\n", "sect": "\n", "page": "\n", "row": "\n", "tab": "\t", "cell": "\t",
             "emdash": "—", "endash": "–", "lquote": "‘", "rquote": "’", "ldblquote": "“", "rdblquote": "”", "bullet": "•"}
RTF_PEZZO = re.compile(rb"\\([a-z]{1,32})(-?\d{1,10})? ?|\\'([0-9a-f]{2})|\\([^a-z])|([{}])|([\r\n]+)|([^\\{}\r\n]+)",
                       re.I)


def testo_rtf(dati):
    """Il testo di un allegato RTF (anche un .doc che in realtà è RTF); '' se non c'è testo."""
    import codecs
    m = re.search(rb"\\ansicpg(\d{3,5})", dati[:4000])
    codifica = f"cp{int(m.group(1))}" if m else "cp1252"
    try:
        codecs.lookup(codifica)
    except LookupError:
        codifica = "cp1252"
    out, pila, salta, uc, resto = [], [], False, 1, 0   # resto: i caratteri di riserva da saltare dopo un \uN
    for parola, num, esa, simbolo, graffa, _, testo in RTF_PEZZO.findall(dati):
        if graffa:
            resto = 0
            if graffa == b"{":
                pila.append((salta, uc))
            elif pila:
                salta, uc = pila.pop()
        elif parola:
            resto = 0
            p = parola.decode("ascii").lower()
            if p in RTF_SALTA:
                salta = True
            elif p == "uc" and num:
                uc = int(num)
            elif not salta and p == "u" and num:
                out.append(chr(int(num) % 65536))   # i numeri negativi sono i caratteri sopra il 32767
                resto = uc
            elif not salta and p in RTF_SEGNI:
                out.append(RTF_SEGNI[p])
        elif esa:
            if resto:
                resto -= 1
            elif not salta:
                out.append(bytes([int(esa, 16)]).decode(codifica, "replace"))
        elif simbolo:
            resto = 0
            if simbolo == b"*":
                salta = True
            elif not salta:
                out.append({b"\\": "\\", b"{": "{", b"}": "}", b"~": " ", b"_": "-", b"\n": "\n", b"\r": "\n"}.get(simbolo, ""))
        elif testo:
            n = min(resto, len(testo))
            resto -= n
            if not salta and testo[n:]:
                out.append(testo[n:].decode(codifica, "replace"))
    t = "".join(out).encode("utf-16", "surrogatepass").decode("utf-16", "replace")   # le emoji arrivano in due \u
    return re.sub(r"\n{3,}", "\n\n", re.sub(r"[ \t]+\n", "\n", t)).strip()


# ---------------------------------------------------------------- l'OCR delle scansioni

_TESS = None
_HEIF = None
_OCR_FINO = None   # entro quando finire l'OCR di questo giro (OCR_SECONDI dal primo uso)
_OCR_FERMATO = [0]   # quante volte l'OCR si è fermato per il tempo: quella mail si riprende al giro dopo


def tesseract():
    """Il programma dell'OCR, se c'è e ha l'italiano; '' se no."""
    global _TESS
    if _TESS is None:
        exe = shutil.which("tesseract") or ""
        if exe:
            try:
                r = subprocess.run([exe, "--list-langs"], capture_output=True, timeout=30)
                exe = exe if "ita" in r.stdout.decode("utf-8", "replace").split() else ""
            except (OSError, subprocess.SubprocessError):
                exe = ""
        _TESS = exe
    return _TESS


def heif():
    """True se Pillow sul Pi apre le foto HEIC degli iPhone (pillow-heif in venv-img)."""
    global _HEIF
    if _HEIF is None:
        try:
            _HEIF = subprocess.run([VENV_IMG, "-c", "import pillow_heif"], capture_output=True, timeout=30).returncode == 0
        except (OSError, subprocess.SubprocessError):
            _HEIF = False
    return _HEIF


def lettore():
    """Cosa sanno fare i lettori adesso: se cambia (lettori nuovi, OCR installato) i comunicati con allegati non letti si
    rileggono da soli (fonti_casa.py)."""
    return f"{LETTORE}{'+ocr' if tesseract() else ''}{'+heic' if heif() else ''}{'+7z' if shutil.which('7z') else ''}"


LETTORE = 3   # sale quando i lettori migliorano


def _ocr_tempo():
    """I secondi di OCR che restano in questo giro."""
    global _OCR_FINO
    if _OCR_FINO is None:
        _OCR_FINO = time.monotonic() + OCR_SECONDI
    return _OCR_FINO - time.monotonic()


def _cache(chiave, calcola):
    """Il risultato dell'OCR di una pagina, dalla cartella OCR_CACHE se c'è già; None se il tempo del giro è finito."""
    f = os.path.join(OCR_CACHE, f"{chiave}.json")
    try:
        with open(f, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        pass
    if _ocr_tempo() <= 0:
        _OCR_FERMATO[0] += 1
        return None
    r = calcola()
    if r is not None:
        try:
            os.makedirs(OCR_CACHE, exist_ok=True)
            with open(f, "w", encoding="utf-8") as fh:
                json.dump(r, fh, ensure_ascii=False)
        except OSError:
            pass
    return r


def pulisci_cache():
    """Via le pagine lette con l'OCR più di OCR_CACHE_GIORNI fa."""
    limite = time.time() - OCR_CACHE_GIORNI * 86400
    for n in os.listdir(OCR_CACHE) if os.path.isdir(OCR_CACHE) else []:
        try:
            if os.path.getmtime(os.path.join(OCR_CACHE, n)) < limite:
                os.remove(os.path.join(OCR_CACHE, n))
        except OSError:
            pass


def ocr_png(percorso):
    """{testo, fiducia, parole} di un'immagine (PNG) letta con tesseract in italiano."""
    r = subprocess.run([tesseract(), percorso, "stdout", "-l", "ita", "tsv"], capture_output=True,
                       timeout=max(20, min(120, _ocr_tempo() + 20)))
    righe, fiducia = {}, []
    for riga in r.stdout.decode("utf-8", "replace").splitlines()[1:]:
        c = riga.split("\t")
        if len(c) < 12 or c[0] != "5" or not c[11].strip():
            continue
        try:
            k = float(c[10])
        except ValueError:
            continue
        if k < 0:
            continue
        fiducia.append(k)
        righe.setdefault((int(c[2]), int(c[3]), int(c[4])), []).append(c[11].strip())
    out, prima = [], None
    for (blocco, paragrafo, _), parole in sorted(righe.items()):
        if prima and prima != (blocco, paragrafo):
            out.append("")
        out.append(" ".join(parole))
        prima = (blocco, paragrafo)
    return {"testo": "\n".join(out).strip(), "fiducia": sum(fiducia) / len(fiducia) if fiducia else 0,
            "parole": len(fiducia)}


def ocr_pdf(dati, pagine):
    """(testo, pagine lette) di una scansione in PDF: una pagina per volta, fino a OCR_PAGINE e al tempo del giro."""
    impronta = hashlib.sha1(dati).hexdigest()
    testi, fatte = [], 0
    with tempfile.TemporaryDirectory() as td:
        f = os.path.join(td, "a.pdf")
        with open(f, "wb") as fh:
            fh.write(dati)
        for k in range(1, min(pagine, OCR_PAGINE) + 1):
            def calcola(k=k):
                png = os.path.join(td, f"p{k}")
                subprocess.run(["pdftoppm", "-r", str(OCR_DPI), "-gray", "-png", "-f", str(k), "-l", str(k), "-singlefile",
                                f, png], check=True, capture_output=True, timeout=60)
                return ocr_png(png + ".png")
            r = _cache(f"{impronta}-{k}", calcola)
            if r is None:
                break
            fatte += 1
            if r["testo"]:
                testi.append(r["testo"] if pagine == 1 else f"(pagina {k})\n{r['testo']}")
    return "\n\n".join(testi).strip(), fatte


# l'immagine in PNG grigi (anche HEIC, WEBP, i TIFF di più pagine), girata come la foto: le pagine in argv[1]
IN_PNG = ("import io, sys\nfrom PIL import Image, ImageOps, ImageSequence\n"
          "try:\n    from pillow_heif import register_heif_opener; register_heif_opener()\nexcept ImportError:\n    pass\n"
          "im = Image.open(io.BytesIO(sys.stdin.buffer.read()))\nn = 0\n"
          f"for k, f in enumerate(ImageSequence.Iterator(im)):\n    if k >= {OCR_PAGINE}: break\n"
          "    ImageOps.exif_transpose(f).convert('L').save(f'{sys.argv[1]}-{k + 1}.png'); n += 1\n"
          "print(n)\n")


def ocr_immagine(dati):
    """[{testo, fiducia, parole}] delle pagine di un'immagine (una sola, o più per i TIFF) lette con l'OCR; [] se il
    tempo del giro è finito o l'immagine non si apre."""
    impronta = hashlib.sha1(dati).hexdigest()
    with tempfile.TemporaryDirectory() as td:
        pagine = None
        out = []
        for k in range(1, OCR_PAGINE + 1):
            def calcola(k=k):
                nonlocal pagine
                if pagine is None:
                    r = subprocess.run([VENV_IMG, "-c", IN_PNG, os.path.join(td, "p")], input=dati, capture_output=True,
                                       timeout=120)
                    pagine = int(r.stdout.strip() or 0) if r.returncode == 0 else 0
                if k > pagine:
                    return {"testo": "", "fiducia": 0, "parole": 0, "fine": True}
                return ocr_png(os.path.join(td, f"p-{k}.png"))
            r = _cache(f"{impronta}-i{k}", calcola)
            if r is None or r.get("fine"):
                break
            out.append(r)
        return out


def _scansione_immagine(dati, ocr):
    """Un TIFF (fax, scansione): sempre con l'OCR."""
    if not ocr:
        return "", "scansione in TIFF: va letta con l'OCR", False
    if not tesseract():
        return "", "scansione in TIFF e sul Pi l'OCR non è installato", False
    pagine = ocr_immagine(dati)
    if not pagine:
        return "", "scansione in TIFF non ancora letta con l'OCR (al prossimo giro) o che non si apre", False
    t = "\n\n".join(p["testo"] for p in pagine if p["testo"])
    return _vuoto(t, "scansione in cui l'OCR non trova testo")[:2] + (True,)


# ---------------------------------------------------------------- tutto insieme

def mostra(f):
    """Come si chiama un file per chi legge: il nome e dove sta."""
    nome = f.nome or f"allegato senza nome ({f.tipo or 'tipo sconosciuto'})"
    return f"{nome} (in {f.dentro})" if f.dentro else nome


def leggi_mail(m, ocr=True):
    """Tutto quello che si legge di una mail: {testo (la mail e i documenti allegati, ognuno col suo «[allegato …]»),
    allegati (i nomi), non_letti («nome: perché»), link_file, ocr (se si è usato), da_finire (l'OCR si è fermato per il
    tempo del giro: la mail va riletta al giro dopo)}."""
    fermato = _OCR_FERMATO[0]
    corpo = corpo_mail(m).strip()
    allegati = [n for n in (nome_allegato(p) for p in _parti(m)) if n]
    documenti, non_letti, immagini, con_ocr = [], [], [], False
    for f in foglie(m):
        if f.problema:
            non_letti.append(f"{mostra(f)}: {f.problema}")
            continue
        if f.tipo == "mail":
            documenti.append(f"[{f.nome}{' — in ' + f.dentro if f.dentro else ''}]\n{f.dati.decode('utf-8', 'replace').strip()}")
            continue
        g = genere(f.dati, f.nome, f.tipo)
        if g == "immagine" and not _e_tiff(f.dati):
            if _e_heic(f.dati) and not heif():
                non_letti.append(f"{mostra(f)}: foto HEIC (iPhone) che il Pi non sa aprire")
            elif len(f.dati) >= IMMAGINE_MIN:
                immagini.append(f)
            continue
        if g == "media":
            non_letti.append(f"{mostra(f)}: video o audio, non si guarda né si ascolta")
            continue
        if g in ("ignora",) or (f.tipo == "immagine nel documento"):
            continue
        if g == "sconosciuto":
            non_letti.append(f"{mostra(f)}: formato che il Pi non conosce")
            continue
        t, problema, letto_ocr = leggi_documento(f.dati, f.nome, ocr, f.tipo)
        con_ocr |= letto_ocr
        if t.strip():
            nota = ": letto con l'OCR, può contenere errori" if letto_ocr else ""
            documenti.append(f"[allegato {mostra(f)}{nota}]\n{t.strip()}")
        if problema:
            non_letti.append(f"{mostra(f)}: {problema}")
    poco = len(corpo) + sum(len(d) for d in documenti) < TESTO_POCO
    if ocr and poco and immagini and tesseract():   # il comunicato potrebbe essere tutto nelle immagini
        for f in immagini:
            pagine = ocr_immagine(f.dati)
            buone = [p for p in pagine if p["parole"] >= OCR_PAROLE_MIN and p["fiducia"] >= OCR_FIDUCIA_MIN]
            if buone:
                con_ocr = True
                documenti.append(f"[immagine {mostra(f)}: letta con l'OCR, può contenere errori]\n"
                                 + "\n\n".join(p["testo"] for p in buone))
    testo = re.sub(r"\n{3,}", "\n\n", (corpo + "\n\n" + "\n\n".join(documenti)).strip())
    link = list(dict.fromkeys(u.rstrip(".,;:") for u in LINK_FILE.findall(testo)))
    return {"testo": testo, "allegati": allegati, "non_letti": list(dict.fromkeys(non_letti)), "link_file": link,
            "ocr": con_ocr, "da_finire": _OCR_FERMATO[0] > fermato}


def immagini_della_mail(m):
    """Le immagini da salvare per l'agente, in ordine: (da dove viene, byte). Le immagini grandi (anche dentro gli
    archivi e i documenti), la prima pagina dei PDF corti (le locandine) e le prime pagine delle scansioni in PDF."""
    for f in foglie(m):
        if f.problema or f.tipo == "mail":
            continue
        g = genere(f.dati, f.nome, f.tipo)
        da = mostra(f) if f.nome else ("immagine nel testo della mail" if not f.dentro else mostra(f))
        if g == "immagine" and len(f.dati) >= IMMAGINE_MIN:
            yield da, f.dati
        elif g == "pdf":
            try:
                t, pagine = _pdf_testo(f.dati)
            except (OSError, subprocess.SubprocessError):
                continue
            if t is None or not pagine:
                continue
            quante = min(pagine, PDF_SCANSIONE_PAGINE) if pdf_scansione(f.dati) else int(pagine <= PDF_PAGINE_MAX)
            for k in range(1, quante + 1):
                with tempfile.TemporaryDirectory() as td:
                    pdf = os.path.join(td, "a.pdf")
                    with open(pdf, "wb") as fh:
                        fh.write(f.dati)
                    try:
                        subprocess.run(["pdftoppm", "-png", "-r", "150", "-f", str(k), "-l", str(k), "-singlefile", pdf,
                                        os.path.join(td, "p")], check=True, capture_output=True, timeout=60)
                    except (OSError, subprocess.SubprocessError):
                        break
                    with open(os.path.join(td, "p.png"), "rb") as fh:
                        yield (da if quante == 1 else f"{da}, pagina {k}"), fh.read()


def main():
    import argparse
    ap = argparse.ArgumentParser(description="Cosa si legge di un allegato (prova a mano)")
    ap.add_argument("file", nargs="+")
    ap.add_argument("--mail", action="store_true", help="i file sono mail intere (.eml)")
    ap.add_argument("--senza-ocr", action="store_true")
    a = ap.parse_args()
    for p in a.file:
        with open(p, "rb") as fh:
            dati = fh.read()
        if a.mail:
            r = leggi_mail(email.message_from_bytes(dati), not a.senza_ocr)
            print(f"=== {p}\n{r['testo']}\n--- non letti: {r['non_letti']}\n--- link: {r['link_file']}\n"
                  f"--- immagini: {[d for d, _ in immagini_della_mail(email.message_from_bytes(dati))]}")
            continue
        m = email.message.EmailMessage()
        m.set_content("")
        m.add_attachment(dati, maintype="application", subtype="octet-stream", filename=os.path.basename(p))
        r = leggi_mail(m, not a.senza_ocr)
        print(f"=== {p} ({genere(dati, p)})\n{r['testo'][:3000]}\n--- non letti: {r['non_letti']}")


if __name__ == "__main__":
    main()
