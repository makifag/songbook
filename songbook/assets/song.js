// Песенник: отрисовка страницы песни по её формату.
//   chordpro — свой рендер аккордов над текстом + транспонирование
//   alphatex — alphaTab: ноты + таб + проигрывание
//   gp       — файл Guitar Pro, тоже через alphaTab
//   text     — как было: моноширинный текст с подгонкой по ширине
(function () {
  "use strict";
  var $ = function (s, el) { return (el || document).querySelector(s); };
  var esc = function (s) {
    return String(s).replace(/[&<>"]/g, function (c) { return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]; });
  };
  var srcEl = $("#song-src");
  var format = srcEl.dataset.format;
  var src = srcEl.textContent.replace(/^\n/, "").replace(/<\\\/script/g, "</script");
  var view = $("#view");
  var controls = $("#controls");
  var VENDOR = new URL("../vendor/alphatab/", location.href).href;

  // ---------- ChordPro ----------
  var NOTES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "Bb", "B"];
  var IDX = { C: 0, "C#": 1, Db: 1, D: 2, "D#": 3, Eb: 3, E: 4, F: 5, "F#": 6, Gb: 6, G: 7, "G#": 8, Ab: 8, A: 9, "A#": 10, Bb: 10, B: 11, H: 11 };
  function transposeChord(ch, n) {
    if (!n) return ch;
    // только корень и бас (после /); позиции вида (III) и значки не трогаем
    return ch.replace(/^([A-H])(#|b)?|\/([A-H])(#|b)?/g, function (m, r, acc, br, bacc) {
      var root = r || br, a = r ? acc : bacc;
      var i = IDX[root + (a || "")];
      if (i === undefined) return m;
      return (br ? "/" : "") + NOTES[(i + n + 120) % 12];
    });
  }
  function parseChordPro(text) {
    var meta = {}, blocks = [], env = null, cur = blocks;
    text.split(/\r?\n/).forEach(function (raw) {
      var d = /^\{\s*([\w_]+)\s*(?::\s*(.*?))?\s*\}$/.exec(raw.trim());
      if (d) {
        var key = d[1], val = d[2];
        if (/^(title|t|artist|key|capo|tempo|time)$/.test(key)) { meta[key === "t" ? "title" : key] = val; return; }
        if (/^(start_of_|so)(chorus|c|tab|t|verse|v)$/.test(key)) {
          var type = /chorus|^soc$/.test(key) ? "chorus" : /tab|^sot$/.test(key) ? "tab" : "verse";
          env = { type: type, label: val || (type === "chorus" ? "Припев" : ""), lines: [] };
          blocks.push(env); cur = env.lines; return;
        }
        if (/^(end_of_|eo)/.test(key)) { env = null; cur = blocks; return; }
        if (key === "comment" || key === "c") { cur.push({ type: "label", text: val }); }
        return;
      }
      if (env && env.type === "tab") { cur.push({ type: "tabline", text: raw }); return; }
      if (!raw.trim()) { cur.push({ type: "blank" }); return; }
      var segs = [], re = /\[([^\]]+)\]/g, last = 0, m, pending = "";
      while ((m = re.exec(raw))) {
        var txt = raw.slice(last, m.index);
        if (segs.length || txt) segs.push({ c: pending, t: txt });
        pending = m[1]; last = re.lastIndex;
      }
      segs.push({ c: pending, t: raw.slice(last) });
      var withChords = segs.some(function (s) { return s.c; });
      var lyric = segs.map(function (s) { return s.t; }).join("").trim();
      cur.push({ type: "line", segs: segs, withChords: withChords, inst: withChords && /^[|\s]*$/.test(lyric) });
    });
    return { meta: meta, blocks: blocks };
  }
  function renderLine(l, n) {
    if (l.type === "blank") return '<div class="blank"></div>';
    if (l.type === "label") return '<div class="label">' + esc(l.text) + "</div>";
    if (l.inst) {
      return '<div class="instrow">' + l.segs.filter(function (s) { return s.c; }).map(function (s) {
        return s.c === "|" ? '<span class="bar">|</span>' : '<span class="c">' + esc(transposeChord(s.c, n)) + "</span>";
      }).join("") + "</div>";
    }
    var parts = [];
    l.segs.forEach(function (s) {
      var words = s.t.split(/(?<=\s)(?=\S)/);
      parts.push({ c: s.c, t: words[0] || "" });
      words.slice(1).forEach(function (w) { parts.push({ c: "", t: w }); });
    });
    return '<div class="line' + (l.withChords ? "" : " nochords") + '">' + parts.map(function (p) {
      return '<span class="seg"><span class="c">' + (p.c ? esc(transposeChord(p.c, n)) : "") +
        '</span><span class="t">' + (p.t === "" ? " " : esc(p.t)) + "</span></span>";
    }).join("") + "</div>";
  }
  function renderChordPro(doc, n) {
    var out = [];
    doc.blocks.forEach(function (b) {
      if (b.type === "tab") {
        var body = b.lines.map(function (l) { return l.text; }).join("\n").replace(/\n+$/, "");
        out.push((b.label ? '<div class="label">' + esc(b.label) + "</div>" : "") + '<pre class="tab">' + esc(body) + "</pre>");
      } else if (b.type === "chorus" || b.type === "verse") {
        out.push('<div class="' + b.type + '">' + (b.label ? '<div class="label">' + esc(b.label) + "</div>" : "") +
          b.lines.map(function (l) { return renderLine(l, n); }).join("") + "</div>");
      } else out.push(renderLine(b, n));
    });
    return out.join("").replace(/^(<div class="blank"><\/div>)+/, "");
  }
  function showChordPro() {
    var doc = parseChordPro(src), n = 0;
    controls.innerHTML = '<button type="button" id="tdown">− тон</button>' +
      '<span class="status">тональность <b class="val" id="tval">0</b></span>' +
      '<button type="button" id="tup">+ тон</button>';
    view.innerHTML = '<div class="cp" id="cp"></div>';
    function draw() { $("#cp").innerHTML = renderChordPro(doc, n); $("#tval").textContent = n > 0 ? "+" + n : n; }
    $("#tdown").onclick = function () { n -= 1; if (n < -5) n += 12; draw(); };
    $("#tup").onclick = function () { n += 1; if (n > 6) n -= 12; draw(); };
    draw();
  }

  // ---------- alphaTab ----------
  function cssVar(name) { return getComputedStyle(document.documentElement).getPropertyValue(name).trim(); }
  function showAlphaTab(loadFn) {
    var notes = /^\/\*\n?([\s\S]*?)\n?\*\//.exec(src);
    controls.innerHTML =
      '<button type="button" class="primary" id="play" disabled>Загрузка звука…</button>' +
      '<button type="button" id="stop" disabled>Стоп</button>' +
      '<label for="speed">темп <input type="range" id="speed" min="40" max="120" step="5" value="100"><span class="val" id="speedv">100%</span></label>' +
      '<label for="metro"><input type="checkbox" id="metro"> метроном</label>' +
      '<label for="loopc"><input type="checkbox" id="loopc"> по кругу</label>';
    view.innerHTML = (format === "alphatex" && notes && notes[1].trim() ? '<p class="notes">' + esc(notes[1].trim()) + "</p>" : "") +
      '<div class="loading" id="at-loading">Рисую…</div><div id="at-host"><div id="at"></div></div>';
    var narrow = window.innerWidth < 600;
    var api = new alphaTab.AlphaTabApi($("#at"), {
      core: { fontDirectory: VENDOR + "font/", scriptFile: VENDOR + "alphaTab.min.js" },
      display: {
        scale: narrow ? 0.72 : 0.95, staveProfile: "Tab",
        resources: {
          mainGlyphColor: cssVar("--ink"), secondaryGlyphColor: cssVar("--muted"), staffLineColor: cssVar("--rule"),
          barSeparatorColor: cssVar("--muted"), barNumberColor: cssVar("--accent"), scoreInfoColor: cssVar("--ink"),
        },
      },
      // только таб: без нотного стана, ритм — штилями под табом; без подписей дорожки и строя
      notation: {
        rhythmMode: "ShowWithBars",
        elements: { scoreTitle: false, scoreSubTitle: false, scoreArtist: false, scoreAlbum: false, scoreWords: false,
          scoreMusic: false, scoreWordsAndMusic: false, scoreCopyright: false, trackNames: false, guitarTuning: false,
          effectDynamics: false },
      },
      player: { playerMode: "EnabledSynthesizer", soundFont: VENDOR + "soundfont/sonivox.sf2", enableCursor: true, enableUserInteraction: true, scrollMode: "OffScreen" },
    });
    // ключ "TAB" в начале строк не нужен — убираем глиф из готового SVG
    api.renderFinished.on(function () {
      var l = $("#at-loading"); if (l) l.remove();
    });
    // alphaTab дорисовывает строки по мере прокрутки, поэтому следим за SVG постоянно
    var TAB_CLEF = "\uE06D";
    new MutationObserver(function () {
      document.querySelectorAll("#at svg text").forEach(function (t) {
        if (t.textContent.indexOf(TAB_CLEF) !== -1) t.remove();
      });
    }).observe($("#at"), { childList: true, subtree: true });
    loadFn(api);
    var play = $("#play");
    api.soundFontLoad.on(function (e) { play.textContent = "Звук " + Math.round((e.loaded / e.total) * 100) + "%"; });
    api.playerReady.on(function () { play.disabled = false; $("#stop").disabled = false; play.textContent = "▶ Играть"; });
    api.playerStateChanged.on(function (e) { play.textContent = e.state === 1 ? "❚❚ Пауза" : "▶ Играть"; });
    play.onclick = function () { api.playPause(); };
    $("#stop").onclick = function () { api.stop(); };
    $("#speed").oninput = function (e) { api.playbackSpeed = e.target.value / 100; $("#speedv").textContent = e.target.value + "%"; };
    $("#metro").onchange = function (e) { api.metronomeVolume = e.target.checked ? 1 : 0; };
    $("#loopc").onchange = function (e) { api.isLooping = e.target.checked; };
    api.error.on(function (e) {
      view.insertAdjacentHTML("afterbegin", '<p class="notes">Не получилось отрисовать: ' + esc(e && e.message || e) + "</p>");
    });
  }

  // ---------- текст как есть ----------
  function showText() {
    controls.innerHTML = '<button type="button" id="fontDec" title="Меньше">A−</button>' +
      '<button type="button" id="fontReset" title="По ширине">по ширине</button>' +
      '<button type="button" id="fontInc" title="Больше">A+</button>';
    view.innerHTML = '<pre class="text" id="body"></pre>';
    var pre = $("#body"), base = 14, size = base;
    pre.textContent = src;
    function apply() { pre.style.fontSize = size + "px"; }
    function fit() {
      size = base; apply();
      for (var g = 0; pre.scrollWidth > pre.clientWidth && size > 6 && g < 60; g++) { size -= 0.5; apply(); }
    }
    fit();
    window.addEventListener("resize", fit);
    $("#fontDec").onclick = function () { size = Math.max(size - 1, 6); apply(); };
    $("#fontInc").onclick = function () { size = Math.min(size + 1, 32); apply(); };
    $("#fontReset").onclick = fit;
  }

  try {
    if (format === "chordpro") showChordPro();
    else if (format === "alphatex") showAlphaTab(function (api) { api.tex(src); });
    else if (format === "gp") showAlphaTab(function (api) { api.load(new URL(srcEl.dataset.file, location.href).href); });
    else showText();
  } catch (e) {
    view.innerHTML = '<p class="notes">Ошибка отрисовки: ' + esc(e.message) + "</p>";
  }
})();
