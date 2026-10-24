/* Benevento Calcio in diretta: il riquadro in prima pagina e la pagina calcio/.
   I dati fissi (calendario, risultati, classifica, la giornata) li prepara strumenti/calcio.py in calcio.json a ogni
   pubblicazione. Durante le partite questa pagina legge la diretta da sola, ogni 15 secondi, dalla stessa fonte
   (dati pubblici di ESPN, gratuiti e senza chiave: scelta del proprietario, 24 ott 2026) e scrive la cronaca con
   parole nostre dai fatti della partita (gol, cartellini, cambi). Niente cookie, niente chiavi.
   Prova a partita finita: /calcio/?prova=<id partita>[&da=<minuto>] rigioca la partita, un minuto ogni 2 secondi. */
(function () {
  "use strict";
  var ESPN = "https://site.api.espn.com/apis/site/v2/sports/soccer/ita.2";
  var OGNI = 15000, TZ = "Europe/Rome";
  var FISSA = window.NB_PAGINA || null;
  var PAGINA = !!(FISSA && FISSA.calcio);
  // il riquadro va dove c'è la colonna di destra della prima pagina (anche nelle sezioni e nelle zone)
  var HOME = !FISSA || !!(FISSA.cat || FISSA.zona);
  if (!PAGINA && !HOME) return;

  var dati = null, live = {}, dettaglio = null, timer = null, errori = 0;
  var prova = null;   // la partita rigiocata: {id, minuto, finale}
  var q = new URLSearchParams(location.search);
  if (q.get("prova")) prova = { id: q.get("prova"), minuto: Math.max(0, +q.get("da") || 0), finale: null };

  // ---------- piccoli attrezzi ----------
  function el(tag, cls, figli) {
    var x = document.createElement(tag);
    if (cls) x.className = cls;
    (figli || []).forEach(function (f) { if (f != null) x.appendChild(typeof f === "string" ? document.createTextNode(f) : f); });
    return x;
  }
  function data(iso) { return new Date(iso); }
  function fmt(iso, opz) { return new Intl.DateTimeFormat("it-IT", Object.assign({ timeZone: TZ }, opz)).format(data(iso)); }
  function giornoRoma(d) { return new Intl.DateTimeFormat("en-CA", { timeZone: TZ }).format(d); }
  function quandoDetto(p) {
    var d = data(p.quando), ora = p.ora_certa ? fmt(p.quando, { hour: "2-digit", minute: "2-digit" }) : null;
    var oggi = giornoRoma(new Date()), g = giornoRoma(d);
    var domani = giornoRoma(new Date(Date.now() + 864e5));
    var giorno = g === oggi ? "oggi" : g === domani ? "domani" : fmt(p.quando, { weekday: "long", day: "numeric", month: "long" });
    return giorno + (ora ? (giorno === "oggi" || giorno === "domani" ? " alle " : ", ") + ora : ", orario da definire");
  }
  function traQuanto(p) {
    var m = Math.round((data(p.quando) - Date.now()) / 60000);
    if (m <= 0 || !p.ora_certa) return "";
    if (m < 60) return "tra " + m + (m === 1 ? " minuto" : " minuti");
    if (m < 24 * 60) { var h = Math.floor(m / 60); return "tra " + h + (h === 1 ? " ora" : " ore") + (m % 60 ? " e " + (m % 60) + " min" : ""); }
    var gg = Math.round(m / 1440); return "tra " + gg + (gg === 1 ? " giorno" : " giorni");
  }
  function sq(id) { return (dati && dati.squadre[id]) || { nome: "?", sigla: "?", logo: null }; }
  function logo(id, px) {
    var s = sq(id);
    if (!s.logo) return el("span", "logo-vuoto", []);
    var i = el("img", "", []);
    i.src = s.logo; i.alt = ""; i.width = px; i.height = px; i.loading = "lazy";
    return i;
  }
  // gli articoli dei nomi delle squadre: il Benevento, l'Arezzo, la Juve Stabia, lo Spezia
  var FEMMINILI = /^(juve stabia|sampdoria|cremonese|carrarese|virtus entella|reggiana|salernitana|ternana|triestina|lucchese|spal|feralpisal|pro vercelli|virtus)/i;
  function art(nome) {
    if (FEMMINILI.test(nome)) return /^[aeiou]/i.test(nome) ? "l'" : "la ";
    if (/^spezia$/i.test(nome)) return "lo ";
    return /^[aeiouàèéìòù]/i.test(nome) ? "l'" : "il ";
  }
  var PREP = { di: { "il ": "del ", "lo ": "dello ", "la ": "della ", "l'": "dell'" },
               "in": { "il ": "nel ", "lo ": "nello ", "la ": "nella ", "l'": "nell'" } };
  function con(prep, nome) { var a = art(nome); return (prep ? PREP[prep][a] : a) + nome; }
  function maiusc(s) { return s.charAt(0).toUpperCase() + s.slice(1); }

  // ---------- la partita, unendo calcio.json e la diretta ----------
  function unita(p) { return live[p.id] ? Object.assign({}, p, live[p.id]) : p; }
  function nostre() { return (dati.partite || []).map(unita); }
  function clou() {
    // la partita da mostrare: quella in corso; se no l'ultima finita da meno di 36 ore; se no la prossima
    var ps = nostre(), adesso = Date.now();
    if (prova) { var pp = ps.filter(function (p) { return p.id === prova.id; })[0]; if (pp) return pp; }
    var inCorso = ps.filter(function (p) { return p.stato === "in"; })[0];
    if (inCorso) return inCorso;
    var oggi = ps.filter(function (p) { return p.stato === "pre" && finestra(p); })[0];
    if (oggi) return oggi;
    var finite = ps.filter(function (p) { return p.stato === "post"; });
    var ultima = finite[finite.length - 1];
    if (ultima && adesso - data(ultima.quando) < 36 * 3600e3) return ultima;
    return ps.filter(function (p) { return p.stato === "pre"; })[0] || ultima || null;
  }
  // la diretta si legge da un'ora prima del calcio d'inizio a 3 ore dopo (recupero, ritardi), finché non è finita
  function finestra(p) {
    var t = data(p.quando) - Date.now();
    return p.ora_certa !== false && t < 3600e3 && t > -3 * 3600e3 && p.stato !== "rinviata" &&
      !(p.stato === "post" && t < -2.5 * 3600e3);
  }
  function serveDiretta() {
    if (prova) return true;
    if (dati.partite.some(function (p) { return finestra(unita(p)) && unita(p).stato !== "post"; })) return true;
    return PAGINA && (dati.giornata.partite || []).some(function (p) { var u = unita(p); return finestra(u) && u.stato !== "post"; });
  }

  // ---------- la diretta (ESPN) ----------
  function daEspn(e) {
    var c = e.competitions[0], st = c.status || e.status || {}, t = st.type || {};
    var casa = c.competitors.filter(function (x) { return x.homeAway === "home"; })[0];
    var fuori = c.competitors.filter(function (x) { return x.homeAway === "away"; })[0];
    var stato = /POSTPONED|CANCELED|ABANDONED|SUSPENDED/.test(t.name || "") ? "rinviata" : (t.state || "pre");
    var o = { stato: stato };
    if (stato === "in" || stato === "post") {
      o.gol_casa = +casa.score; o.gol_fuori = +fuori.score;
      o.minuto = t.name === "STATUS_HALFTIME" ? "Intervallo" : (st.displayClock || t.shortDetail || "");
      o.dettagli = c.details || [];
    }
    return o;
  }
  function leggi(url) {
    return fetch(url, { cache: "no-store" }).then(function (r) { if (!r.ok) throw new Error(r.status); return r.json(); });
  }
  function aggiorna() {
    clearTimeout(timer);
    var lavori = [];
    if (prova) lavori.push(rigioca());
    else {
      lavori.push(leggi(ESPN + "/scoreboard").then(function (j) {
        (j.events || []).forEach(function (e) { live[e.id] = daEspn(e); });
      }));
      var c = clou();
      if (PAGINA && c && finestra(c)) lavori.push(leggi(ESPN + "/summary?event=" + c.id).then(function (j) { dettaglio = j; }));
    }
    Promise.all(lavori).then(function () { errori = 0; disegnaTutto(); })
      .catch(function (e) { errori++; console.error("calcio, diretta:", e); disegnaTutto(); })
      .then(function () {
        if (serveDiretta() && !document.hidden) timer = setTimeout(aggiorna, prova ? 2000 : OGNI);
      });
  }
  document.addEventListener("visibilitychange", function () {
    if (document.hidden) clearTimeout(timer);
    else if (dati && serveDiretta()) aggiorna();
  });

  // ---------- prova: una partita finita rigiocata minuto per minuto ----------
  function rigioca() {
    var dopo = function () {
      var f = prova.finale, m = prova.minuto, sec = m * 60;
      var ke = (f.keyEvents || []).filter(function (k) { return (k.clock && k.clock.value || 0) <= sec; });
      var casaId = f.header.competitions[0].competitors.filter(function (x) { return x.homeAway === "home"; })[0].team.id;
      var gc = 0, gf = 0;
      ke.forEach(function (k) { if (k.scoringPlay) { if ((k.team || {}).id === casaId) gc++; else gf++; } });
      var finita = m >= 95;
      dettaglio = Object.assign({}, f, { keyEvents: ke, _prova: { minuto: m, finita: finita } });
      live[prova.id] = { stato: finita ? "post" : "in", gol_casa: gc, gol_fuori: gf,
                         minuto: finita ? "" : m > 45 && m < 47 ? "Intervallo" : (m > 90 ? "90'+" + (m - 90) + "'" : m + "'"),
                         dettagli: ke };
      if (!finita) prova.minuto++;
    };
    if (prova.finale) { dopo(); return Promise.resolve(); }
    return leggi(ESPN + "/summary?event=" + prova.id).then(function (j) { prova.finale = j; dopo(); });
  }

  // ---------- la cronaca con parole nostre ----------
  function cognomi() {
    var c = {};
    ((dettaglio && dettaglio.rosters) || []).forEach(function (r) {
      (r.roster || []).forEach(function (x) { var a = x.athlete || {}; if (a.id) c[a.id] = a.lastName || a.displayName; });
    });
    return c;
  }
  function chi(p, cg) {
    var a = (p && p.athlete) || {};
    if (cg[a.id]) return cg[a.id];
    var n = String(a.displayName || "").split(" ");
    return n.length > 1 ? n.slice(1).join(" ") : n[0] || "un giocatore";
  }
  // la squadra a cui va il gol. Per gli autogol non è chiaro se ESPN scrive la squadra di chi l'ha fatto o quella a
  // cui va: si sceglie il verso che fa tornare il risultato ufficiale della partita.
  function beneficiario(k, p) {
    var t = (k.team || {}).id;
    if (!/own/i.test(String((k.type || {}).text || (k.type || {}).type || ""))) return t;
    var ke = (dettaglio && dettaglio.keyEvents) || p.dettagli || [], gc = 0;
    ke.forEach(function (x) {
      if (!(x.scoringPlay || /goal/i.test((x.type || {}).text || ""))) return;
      var own = /own/i.test(String((x.type || {}).text || "")), tt = (x.team || {}).id;
      if (own) tt = tt === p.casa ? p.fuori : p.casa;
      if (tt === p.casa) gc++;
    });
    var altro = t === p.casa ? p.fuori : p.casa;
    return p.gol_casa == null || gc === p.gol_casa ? altro : t;
  }
  function righeCronaca(p) {
    var ke = (dettaglio && (dettaglio.keyEvents || [])) || [];
    if (!ke.length && p.dettagli) ke = p.dettagli;
    var cg = cognomi(), casa = sq(p.casa).nome, fuori = sq(p.fuori).nome, ben = dati.benevento;
    var ordinati = ke.slice().sort(function (a, b) {
      return ((a.period || {}).number || 0) - ((b.period || {}).number || 0) || ((a.clock || {}).value || 0) - ((b.clock || {}).value || 0);
    });
    var gc = 0, gf = 0, rossi = {}, righe = [], ht = null, secondo = false;
    righe.push({ ord: -1, min: "", testo: "Fischio d'inizio" + (p.stadio ? ", " + p.stadio : "") + ".", tipo: "fase" });
    ordinati.forEach(function (k) {
      var per = (k.period || {}).number || 1, v = (k.clock || {}).value || 0, min = (k.clock || {}).displayValue || "";
      var tipo = ((k.type || {}).type || (k.type || {}).text || "").toLowerCase(), team = (k.team || {}).id;
      var nome = sq(team).nome, part = k.participants || k.athletesInvolved || [];
      if (per >= 2 && ht === null) { ht = [gc, gf]; secondo = true; }
      var r = { ord: per * 10000 + v, min: min, tipo: "" };
      if (k.scoringPlay || /goal/.test(tipo)) {
        var autogol = /own/.test(tipo), segna = beneficiario(k, p);
        var prima = [gc, gf];
        if (segna === p.casa) gc++; else gf++;
        var mio = segna === p.casa ? gc : gf, loro = segna === p.casa ? gf : gc, nomeS = sq(segna).nome;
        var verbo = mio === 1 && loro === 0 ? "sblocca la partita" : mio === loro ? "pareggia" :
          mio - loro === 1 && (prima[0] === prima[1]) ? "porta avanti " + con("", nomeS) :
          mio - loro === 2 && loro === 0 && mio === 2 ? "raddoppia" : mio === 3 && loro === 0 ? "cala il tris" :
          mio > loro ? "allunga" : "accorcia le distanze";
        var come = /header/.test(tipo) ? " di testa" : /penalty/.test(tipo) ? " su rigore" : /free/.test(tipo) ? " su punizione" : "";
        var x = chi(part[0], cg);
        var frase = autogol ? "Autogol di " + x : x + " " + verbo + come;
        r.tipo = "gol" + (segna === ben ? " noi" : "");
        r.forte = segna === ben ? "GOL DEL BENEVENTO! " : "Gol " + con("di", nomeS) + ". ";
        r.testo = frase + ": " + casa + " " + gc + ", " + fuori + " " + gf + ".";
      } else if (/yellow/.test(tipo)) {
        r.tipo = "giallo"; r.testo = "Ammonito " + chi(part[0], cg) + " " + con("di", nome) + ".";
      } else if (/red/.test(tipo)) {
        rossi[team] = (rossi[team] || 0) + 1;
        r.tipo = "rosso";
        r.testo = "Espulso " + chi(part[0], cg) + ": " + con("", nome) + " resta in " + (rossi[team] === 1 ? "dieci" : rossi[team] === 2 ? "nove" : (11 - rossi[team])) + ".";
      } else if (/substitution/.test(tipo)) {
        r.tipo = "cambio"; r.testo = "Cambio " + con("in", nome) + ": entra " + chi(part[0], cg) + (part[1] ? ", esce " + chi(part[1], cg) : "") + ".";
      } else if (/penalty/.test(tipo) && /(miss|save)/.test(tipo)) {
        r.tipo = "rigore"; r.testo = /save/.test(tipo) ? "Rigore parato: " + chi(part[0], cg) + " " + con("di", nome) + " non segna." : chi(part[0], cg) + " " + con("di", nome) + " sbaglia un rigore.";
      } else return;
      righe.push(r);
    });
    var minuto = String(p.minuto || "");
    if (secondo || p.stato === "post" || /^(4[6-9]|[5-9]\d)'/.test(minuto) || minuto === "Intervallo") {
      if (ht === null) ht = [gc, gf];
      righe.push({ ord: 1 * 10000 + 2700 + 999, min: "45'", tipo: "fase", testo: "Fine del primo tempo: " + casa + " " + ht[0] + ", " + fuori + " " + ht[1] + "." });
      if (minuto !== "Intervallo") righe.push({ ord: 2 * 10000 + 2700, min: "46'", tipo: "fase", testo: "Comincia il secondo tempo." });
    }
    if (p.stato === "post") {
      var noi = p.casa === ben ? [p.gol_casa, p.gol_fuori] : p.fuori === ben ? [p.gol_fuori, p.gol_casa] : null;
      var esito = !noi ? "" : noi[0] > noi[1] ? " Vince il Benevento." : noi[0] === noi[1] ? " Finisce in parità." : " Sconfitta per il Benevento.";
      righe.push({ ord: 9e9, min: "", tipo: "fase fine", testo: "È finita: " + casa + " " + p.gol_casa + ", " + fuori + " " + p.gol_fuori + "." + esito });
    }
    return righe.sort(function (a, b) { return b.ord - a.ord; });
  }
  function marcatori(p, lato) {
    var ke = (dettaglio && dettaglio.keyEvents) || p.dettagli || [], cg = cognomi(), out = [];
    ke.forEach(function (k) {
      if (!(k.scoringPlay || /goal/i.test((k.type || {}).text || ""))) return;
      var segna = beneficiario(k, p);
      if (segna !== (lato === "casa" ? p.casa : p.fuori)) return;
      var t = String((k.type || {}).text || "").toLowerCase();
      out.push(chi((k.participants || k.athletesInvolved || [])[0], cg) + " " + ((k.clock || {}).displayValue || "") +
               (/own/.test(t) ? " (aut.)" : /penalty/.test(t) ? " (rig.)" : ""));
    });
    return out;
  }

  // ---------- classifica in diretta ----------
  function classifica() {
    var righe = (dati.classifica || []).map(function (r) { return Object.assign({}, r, { prima: r.pos }); });
    var per = {}; righe.forEach(function (r) { per[r.id] = r; });
    var giocano = {}, provvisoria = false;
    function conta(p, segno) {
      [[p.casa, p.gol_casa, p.gol_fuori], [p.fuori, p.gol_fuori, p.gol_casa]].forEach(function (x) {
        var r = per[x[0]]; if (!r) return;
        r.pg += segno; r.gf += segno * x[1]; r.gs += segno * x[2];
        var k = x[1] > x[2] ? "v" : x[1] === x[2] ? "n" : "p";
        r[k] += segno; r.pt += segno * (k === "v" ? 3 : k === "n" ? 1 : 0);
      });
    }
    if (dati.classifica_nostra) {
      (dati.giornata.partite || []).forEach(function (p0) {
        var p = unita(p0);
        if (prova && p.id === prova.id && p0.in_classifica && prova.finale) {
          // in prova la partita rigiocata si toglie dal risultato finale già contato e si rimette com'è al minuto
          var f = prova.finale.header.competitions[0].competitors;
          var c = f.filter(function (x) { return x.homeAway === "home"; })[0], o = f.filter(function (x) { return x.homeAway === "away"; })[0];
          conta({ casa: p.casa, fuori: p.fuori, gol_casa: +c.score, gol_fuori: +o.score }, -1);
          p0 = Object.assign({}, p0, { in_classifica: false });
        }
        if (!p0.in_classifica && (p.stato === "in" || p.stato === "post") && p.gol_casa != null) {
          conta(p, 1);
          provvisoria = true;
          if (p.stato === "in") { giocano[p.casa] = 1; giocano[p.fuori] = 1; }
        }
      });
    }
    righe.sort(function (a, b) { return b.pt - a.pt || (b.gf - b.gs) - (a.gf - a.gs) || b.gf - a.gf || a.prima - b.prima; });
    righe.forEach(function (r, i) { r.pos = i + 1; r.gioca = !!giocano[r.id]; });
    return { righe: righe, provvisoria: provvisoria };
  }

  // ---------- disegno ----------
  function statoTesto(p) {
    if (p.stato === "in") return el("span", "stato-live", [p.minuto === "Intervallo" ? "Intervallo" : "In diretta " + (p.minuto || "")]);
    if (p.stato === "post") return el("span", "stato-fine", ["Finita"]);
    if (p.stato === "rinviata") return el("span", "stato-fine", ["Rinviata"]);
    return el("span", "stato-pre", [maiusc(quandoDetto(p))]);
  }
  function risultato(p, cls) {
    if (p.stato === "in" || p.stato === "post") return el("div", cls, [p.gol_casa + " – " + p.gol_fuori]);
    return el("div", cls + " vs", [p.ora_certa ? fmt(p.quando, { hour: "2-digit", minute: "2-digit" }) : "–"]);
  }

  function riquadro() {
    if (!dati) return null;
    var p = clou();
    if (!p) return null;
    var oggi = finestra(p) || p.stato === "in";
    var box = el("a", "calcio-box" + (oggi ? " oggi" : ""), []);
    box.href = "/calcio/" + (prova ? "?prova=" + prova.id : "");
    var cl = (dati.classifica || []).filter(function (r) { return r.id === dati.benevento; })[0];
    box.appendChild(el("div", "cb-tit", ["Benevento Calcio", el("span", "", [cl ? cl.pos + "° in " + dati.campionato + " · " + cl.pt + " punti" : dati.campionato])]));
    var tm = el("div", "tab-mini", [
      el("div", "sq", [logo(p.casa, 40), sq(p.casa).nome]),
      el("div", "centro", [risultato(p, "ris"), statoTesto(p)]),
      el("div", "sq", [logo(p.fuori, 40), sq(p.fuori).nome])]);
    box.appendChild(tm);
    var riga = "";
    if (p.stato === "in" || p.stato === "post") {
      // nel riquadro l'ultimo fatto che conta: un gol, un'espulsione o la fine; se no l'ultimo fatto
      var tutte = righeCronaca(p);
      var r = tutte.filter(function (x) { return /gol|rosso|fine/.test(x.tipo); })[0] || tutte.filter(function (x) { return x.tipo.indexOf("fase") < 0; })[0];
      if (r) riga = (r.min ? r.min + " " : "") + (r.forte ? r.forte.replace(/\s+$/, " ") : "") + r.testo;
    } else {
      var tq = traQuanto(p);
      riga = (data(p.quando) - Date.now() < 36e5 * 24 * 8 && tq ? maiusc(tq) + " · " : "") + (p.casa === dati.benevento ? "in casa" : "in trasferta") + (p.stadio ? ", " + p.stadio : "");
    }
    if (riga) box.appendChild(el("p", "cb-riga", [riga]));
    if (p.stato === "pre") {
      var ult = nostre().filter(function (x) { return x.stato === "post"; }).pop();
      if (ult) box.appendChild(el("p", "cb-riga", ["Ultima: " + sq(ult.casa).nome + " " + ult.gol_casa + "–" + ult.gol_fuori + " " + sq(ult.fuori).nome]));
    }
    box.appendChild(el("span", "cb-link", [p.stato === "in" ? "Segui la diretta ›" : "Classifica, risultati e calendario ›"]));
    return box;
  }

  function tabellone(p) {
    var g = (dati.partite || []).filter(function (x) { return x.id === p.id; })[0];
    var info = dati.campionato + (g ? " · " + g.giornata + "ª giornata" : "") + " · " + fmt(p.quando, { weekday: "long", day: "numeric", month: "long" }) +
      (p.ora_certa ? ", " + fmt(p.quando, { hour: "2-digit", minute: "2-digit" }) : "") + (p.stadio ? " · " + p.stadio : "");
    function lato(id, l) {
      var m = marcatori(p, l);
      return el("div", "tb-sq", [logo(id, 72), el("div", "tb-nome", [sq(id).nome]),
        m.length ? el("ul", "tb-marcatori", m.map(function (x) { return el("li", "", [x]); })) : null]);
    }
    var centro = el("div", "tb-centro", [risultato(p, "tb-ris"), el("div", "tb-stato", [statoTesto(p)])]);
    if (p.stato === "pre") { var tq = traQuanto(p); if (tq) centro.appendChild(el("div", "tb-tra", [tq])); }
    var t = el("section", "tabellone" + (p.stato === "in" ? " in-diretta" : ""), [el("div", "tb-info", [info]),
      el("div", "tb-campo", [lato(p.casa, "casa"), centro, lato(p.fuori, "fuori")])]);
    if (errori >= 3) t.appendChild(el("p", "tb-avviso", ["Dati della diretta momentaneamente non disponibili: riprovo da solo."]));
    return t;
  }

  var STAT = [["possessionPct", "Possesso palla", "%"], ["totalShots", "Tiri"], ["shotsOnTarget", "Tiri in porta"],
              ["wonCorners", "Calci d'angolo"], ["foulsCommitted", "Falli"], ["offsides", "Fuorigioco"],
              ["yellowCards", "Ammonizioni"], ["saves", "Parate"]];
  function statistiche(p) {
    var bs = (dettaglio && dettaglio.boxscore && dettaglio.boxscore.teams) || [];
    if (bs.length < 2 || p.stato === "pre") return null;
    var per = {}; bs.forEach(function (t) { var o = {}; (t.statistics || []).forEach(function (s) { o[s.name] = parseFloat(s.displayValue); }); per[t.team.id] = o; });
    var c = per[p.casa] || {}, f = per[p.fuori] || {}, box = el("div", "statistiche", []);
    STAT.forEach(function (s) {
      var a = c[s[0]], b = f[s[0]];
      if (isNaN(a) || isNaN(b) || a == null || b == null) return;
      var suf = s[2] || "";
      if (suf === "%") { a = Math.round(a); b = 100 - a; }   // 49,5 e 50,5 non diventano 50 e 51
      var tot = a + b || 1;
      var barre = el("div", "sr-barre", [el("span", p.casa === dati.benevento ? "noi" : "", []), el("span", p.fuori === dati.benevento ? "noi" : "", [])]);
      barre.children[0].style.width = (a / tot * 100) + "%"; barre.children[1].style.width = (b / tot * 100) + "%";
      box.appendChild(el("div", "stat-riga", [el("div", "sr-nomi", [el("b", "", [Math.round(a) + suf]), s[1], el("b", "", [Math.round(b) + suf])]), barre]));
    });
    return box.children.length ? box : null;
  }

  function formazioni() {
    var rs = (dettaglio && dettaglio.rosters) || [];
    if (!rs.length || !rs.some(function (r) { return (r.roster || []).length; })) return null;
    var cg = cognomi(), entrati = {};
    ((dettaglio && dettaglio.keyEvents) || []).forEach(function (k) {
      if (/substitution/i.test((k.type || {}).text || "")) {
        var pp = k.participants || [];
        if (pp[0]) entrati[(pp[0].athlete || {}).id] = (k.clock || {}).displayValue;
        if (pp[1]) entrati["fuori" + (pp[1].athlete || {}).id] = (k.clock || {}).displayValue;
      }
    });
    var box = el("div", "formazioni", []);
    rs.slice().sort(function (a) { return a.homeAway === "home" ? -1 : 1; }).forEach(function (r) {
      var col = el("div", "fz-col", [el("h4", "", [r.team.displayName ? sq(r.team.id).nome : "", r.formation ? el("span", "", [" " + r.formation]) : null])]);
      var tit = el("ol", "fz-lista", []), pan = [];
      (r.roster || []).forEach(function (x) {
        var a = x.athlete || {}, n = cg[a.id] || a.displayName;
        if (x.starter) {
          var esce = entrati["fuori" + a.id];
          tit.appendChild(el("li", "", [el("span", "num", [x.jersey || ""]), n, esce ? el("span", "esce", [" ↓ " + esce]) : null]));
        } else if (entrati[a.id]) pan.push(n + " " + entrati[a.id]);
      });
      col.appendChild(tit);
      if (pan.length) col.appendChild(el("p", "fz-entrati", ["Entrati: " + pan.join(", ")]));
      box.appendChild(col);
    });
    return box;
  }

  function giornata() {
    var lista = el("ul", "giornata", []);
    (dati.giornata.partite || []).map(unita).forEach(function (p) {
      var dx = p.stato === "in" || p.stato === "post" ? p.gol_casa + "–" + p.gol_fuori :
        p.stato === "rinviata" ? "rinv." : (p.ora_certa ? fmt(p.quando, { weekday: "short", hour: "2-digit", minute: "2-digit" }) : "da def.");
      var ris = el("span", "r", [dx]);
      if (p.stato === "in") ris.appendChild(el("span", "min", [p.minuto === "Intervallo" ? "int." : p.minuto]));
      var noi = p.casa === dati.benevento || p.fuori === dati.benevento;
      lista.appendChild(el("li", (p.stato === "in" ? "live" : p.stato) + (noi ? " noi" : ""), [
        el("span", "c", [sq(p.casa).nome, logo(p.casa, 18)]), ris, el("span", "f", [logo(p.fuori, 18), sq(p.fuori).nome])]));
    });
    return lista;
  }

  function tabClassifica() {
    var c = classifica(), t = el("table", "classifica", []);
    t.appendChild(el("thead", "", [el("tr", "", ["", "Squadra", "Pt", "G", "V", "N", "P", "DR"].map(function (h, i) { return el("th", i === 1 ? "sq" : "", [h]); }))]));
    var tb = el("tbody", "", []), n = c.righe.length;
    c.righe.forEach(function (r) {
      var zona = r.pos <= 2 ? "zona-a" : r.pos <= 8 ? "zona-po" : r.pos >= n - 2 ? "zona-r" : r.pos >= n - 4 ? "zona-pl" : "";
      var mossa = c.provvisoria && r.pos !== r.prima ? el("span", r.pos < r.prima ? "su" : "giu", [r.pos < r.prima ? " ▲" : " ▼"]) : null;
      var dr = r.gf - r.gs;
      tb.appendChild(el("tr", (r.id === dati.benevento ? "noi " : "") + zona, [
        el("td", "pos", [String(r.pos), mossa]),
        el("td", "sq", [logo(r.id, 18), sq(r.id).nome, r.gioca ? el("span", "gioca", []) : null,
                        r.penalita ? el("span", "pen", [" (−" + r.penalita + ")"]) : null]),
        el("td", "pt", [String(r.pt)]), el("td", "", [String(r.pg)]), el("td", "", [String(r.v)]), el("td", "", [String(r.n)]),
        el("td", "", [String(r.p)]), el("td", "", [(dr > 0 ? "+" : "") + dr])]));
    });
    t.appendChild(tb);
    var box = el("div", "", [t]);
    var note = [];
    if (c.provvisoria) note.push("Classifica in diretta, con i risultati delle partite in corso: diventa ufficiale a fine giornata.");
    note.push("1ª e 2ª in Serie A, dalla 3ª all'8ª playoff, 16ª e 17ª playout, ultime tre in Serie C.");
    c.righe.forEach(function (r) { if (r.penalita) note.push(sq(r.id).nome + ": " + r.penalita + " punti di penalizzazione."); });
    box.appendChild(el("p", "nota-cl", [note.join(" ")]));
    return box;
  }

  function calendario(stato, quante) {
    var ps = nostre().filter(function (p) { return stato === "pre" ? p.stato === "pre" || p.stato === "rinviata" : p.stato === "post"; });
    ps = stato === "pre" ? ps.slice(0, quante) : ps.slice(-quante).reverse();
    var l = el("ul", "calendario", []);
    ps.forEach(function (p) {
      var noi = p.casa === dati.benevento ? [p.gol_casa, p.gol_fuori] : [p.gol_fuori, p.gol_casa];
      var esito = stato === "post" ? (noi[0] > noi[1] ? "V" : noi[0] === noi[1] ? "N" : "P") : null;
      l.appendChild(el("li", "", [
        el("span", "cal-g", [fmt(p.quando, { day: "numeric", month: "short" }), el("small", "", [p.giornata + "ª"])]),
        el("span", "cal-sq", [logo(p.casa, 20), sq(p.casa).nome, " – ", logo(p.fuori, 20), sq(p.fuori).nome]),
        stato === "post" ? el("span", "cal-r " + esito, [p.gol_casa + "–" + p.gol_fuori]) :
          el("span", "cal-r", [p.stato === "rinviata" ? "rinviata" : p.ora_certa ? fmt(p.quando, { hour: "2-digit", minute: "2-digit" }) : "da def."])]));
    });
    return l;
  }

  function aggiungi(dove, x) { if (x) dove.appendChild(x); }
  function sezione(titolo, corpo, cls) {
    if (!corpo) return null;
    return el("section", "cal-sez" + (cls ? " " + cls : ""), [el("h3", "titolo-col", titolo), corpo]);
  }

  function disegnaPagina() {
    var dove = document.getElementById("calcio-vivo");
    if (!dove) return;
    var p = clou(), sx = el("div", "", []), dx = el("div", "", []);
    if (p) sx.appendChild(tabellone(p));
    if (p && (p.stato === "in" || p.stato === "post")) {
      var cr = el("ol", "cronaca", righeCronaca(p).map(function (r) {
        return el("li", r.tipo, [el("span", "min", [r.min]), el("span", "txt", [
          r.tipo === "giallo" ? el("i", "ico giallo", []) : r.tipo === "rosso" ? el("i", "ico rosso", []) : null,
          r.forte ? el("b", "", [r.forte]) : null, r.testo])]);
      }));
      aggiungi(sx, sezione(["La cronaca", el("span", "nota-tit", [" · scritta in automatico dai fatti della partita"])], cr));
      aggiungi(sx, sezione(["Statistiche"], statistiche(p)));
      aggiungi(sx, sezione(["Formazioni"], formazioni()));
    } else if (p) {
      aggiungi(sx, sezione(["Le ultime partite"], calendario("post", 5)));
    }
    aggiungi(sx, sezione(["Prossime partite"], calendario("pre", 5)));
    var gn = dati.giornata.numero;
    aggiungi(dx, sezione([gn + "ª giornata, gli altri campi"], giornata()));
    aggiungi(dx, sezione(["Classifica " + dati.campionato], tabClassifica()));
    if (p && p.stato !== "pre") aggiungi(dx, sezione(["Ultimi risultati"], calendario("post", 5)));
    var g = el("div", "calcio-griglia", [sx, dx]);
    var fonte = el("p", "cal-fonte", ["Dati: ESPN, aggiornati in diretta ogni 15 secondi durante le partite" +
      (dati.aggiornato ? "; calendario e classifica controllati alle " + fmt(dati.aggiornato, { hour: "2-digit", minute: "2-digit" }) : "") +
      ". La cronaca è scritta in automatico dai fatti della partita (gol, cartellini, cambi). I loghi sono delle società."]);
    var scroll = window.scrollY;
    dove.replaceChildren(g, fonte);
    if (Math.abs(window.scrollY - scroll) > 2) window.scrollTo(0, scroll);
  }

  function inserisciRiquadro() {
    var lat = document.querySelector(".griglia .laterale");
    if (!lat) return;
    var vecchio = lat.querySelector(".calcio-box"), nuovo = riquadro();
    // stesso posto se non cambia giorno della partita; se no lo si toglie e lo si rimette al posto giusto
    if (vecchio && nuovo && vecchio.classList.contains("oggi") === nuovo.classList.contains("oggi")) { vecchio.replaceWith(nuovo); return; }
    if (vecchio) vecchio.remove();
    if (!nuovo) return;
    var att = document.querySelector(".menu button[aria-pressed='true']");
    var cat = att ? att.getAttribute("data-cat") : "";
    if (cat && cat !== "sport") return;
    // nel giorno della partita in alto, sotto le chiusure; gli altri giorni sotto il meteo
    var dopo = nuovo.classList.contains("oggi") ? lat.querySelector(".chiusure-box") : (lat.querySelector(".meteo-box") || lat.querySelector(".chiusure-box"));
    lat.insertBefore(nuovo, dopo ? dopo.nextSibling : lat.firstChild);
  }

  function disegnaTutto() {
    if (PAGINA) disegnaPagina();
    if (HOME) inserisciRiquadro();
  }

  // index.html lo chiama quando ridisegna la colonna di destra (cambio di sezione o di zona)
  window.NB_CALCIO = { riquadro: function () { return riquadro(); } };

  fetch("/calcio.json?t=" + Date.now(), { cache: "no-store" })
    .then(function (r) { if (!r.ok) throw new Error(r.status); return r.json(); })
    .then(function (j) {
      dati = j;
      disegnaTutto();
      var c = clou();
      if (serveDiretta()) aggiorna();
      else if (PAGINA && c && c.stato === "post") {   // la partita appena finita: cronaca, statistiche e formazioni, una volta
        leggi(ESPN + "/summary?event=" + c.id).then(function (d) { dettaglio = d; disegnaTutto(); })
          .catch(function (e) { console.error("calcio, partita finita:", e); });
      }
      else if (PAGINA) {   // la pagina lasciata aperta: si ricontrolla ogni 5 minuti se sta per cominciare una partita
        setInterval(function () { if (!timer && serveDiretta()) aggiorna(); else disegnaTutto(); }, 300000);
      }
    })
    .catch(function (e) { console.error("calcio:", e); /* la pagina resta quella scritta da pagine.py */ });
})();
