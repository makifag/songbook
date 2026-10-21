// Песенник: свой рисунок таба (SVG) по модели alphaTab.
// Время линейное: тик длится одинаково во всей песне, поэтому одинаковые такты
// одной ширины и в строке их одинаковое число. Размер такта — на поле слева,
// новый размер начинается с новой строки. Над табом — мелкие буквы длительностей.
// alphaTab здесь только разбирает alphaTex / Guitar Pro и играет звук.
(function () {
  "use strict";
  var NS = "http://www.w3.org/2000/svg";
  var LETTER = { "-4": "W", "-2": "W", 1: "W", 2: "H", 4: "Q", 8: "E", 16: "S", 32: "T", 64: "X", 128: "X", 256: "X" };

  function el(name, attrs, text) {
    var e = document.createElementNS(NS, name);
    for (var k in attrs) e.setAttribute(k, attrs[k]);
    if (text !== undefined) e.textContent = text;
    return e;
  }
  function r1(v) { return Math.round(v * 10) / 10; }

  function fretLabel(n) {
    if (n.isDead) return "x";
    var f = String(n.fret);
    if (n.harmonicType && n.harmonicType !== 0) return "<" + f + ">";
    if (n.isGhost || n.isTieDestination) return "(" + f + ")";
    return f;
  }
  function letterOf(b) {
    var s = (LETTER[b.duration] || "?") + new Array(b.dots + 1).join(".");
    if (b.tupletNumerator > 0 && b.tupletNumerator !== b.tupletDenominator) s += b.tupletNumerator;
    return s;
  }

  // score -> такты с долями (только первая дорожка, первый стан)
  function model(score) {
    var staff = score.tracks[0].staves[0];
    var strings = staff.stringTuning ? staff.stringTuning.tunings.length : (staff.tuning || []).length || 6;
    var bars = score.masterBars.map(function (mb, i) {
      var bar = staff.bars[i], voices = [];
      (bar ? bar.voices : []).forEach(function (v, vi) {
        var beats = v.beats.filter(function (b) { return !b.isEmpty; });
        if (beats.length) voices.push({ index: vi, beats: beats });
      });
      return { mb: mb, index: i, ticks: mb.calculateDuration(), ts: mb.timeSignatureNumerator + "/" + mb.timeSignatureDenominator, voices: voices };
    });
    return { strings: strings, bars: bars };
  }

  function TabView(host, score, opts) {
    this.host = host;
    this.m = model(score);
    this.opts = opts; // { scale, letters, barsPerRow, onSeek(beat) }
    this.beatPos = new Map(); // beat.id -> { row, x, bar }
    this.render();
    var self = this, lastW = host.clientWidth, t = 0;
    if (window.ResizeObserver) {
      new ResizeObserver(function () {
        if (host.clientWidth === lastW) return;
        lastW = host.clientWidth; clearTimeout(t); t = setTimeout(function () { self.render(); }, 120);
      }).observe(host);
    }
  }

  TabView.prototype.metrics = function () {
    var s = this.opts.scale, fs = 14 * s;
    return {
      fs: fs, cw: fs * 0.6, line: fs * 1.05, gap: fs * 0.25,
      small: Math.max(7.5, fs * 0.62), grace: fs * 0.72,
    };
  };

  TabView.prototype.width = function (b, M) {
    var w = 0;
    b.notes.forEach(function (n) { w = Math.max(w, fretLabel(n).length * M.cw); });
    if (this.opts.letters && b.voice.index === 0) w = Math.max(w, letterOf(b).length * M.small * 0.6);
    return Math.max(w, M.cw);
  };
  // сколько px на тик нужно такту: lin — чтобы при линейной раскладке ни одна
  // пара соседних долей не слиплась; sum — чтобы доли хотя бы поместились подряд
  TabView.prototype.needK = function (bar, M) {
    var self = this, o = this.edge(M), lin = 0, sum = 0;
    bar.voices.forEach(function (v) {
      var main = v.beats.filter(function (b) { return !b.graceType; }), total = o;
      for (var i = 0; i < main.length; i++) {
        var a = main[i], wa = self.width(a, M), next = main[i + 1], need, dt;
        if (next) { need = wa / 2 + self.width(next, M) / 2 + M.gap; dt = next.displayStart - a.displayStart; }
        else { need = wa / 2 + M.gap * 0.5 + o; dt = bar.ticks - a.displayStart; }
        total += need;
        if (dt > 0) lin = Math.max(lin, need / dt);
      }
      sum = Math.max(sum, total / bar.ticks);
    });
    return { lin: lin, sum: sum };
  };
  // масштаб времени на всю песню: линейный для типичного (медианного) такта; плотные такты
  // (редкая триоль, пассаж тридцатьвторыми) раздвигаются внутри себя, не меняя ширины
  TabView.prototype.minK = function (M) {
    var self = this, lins = [], sum = 0;
    this.m.bars.forEach(function (bar) {
      var n = self.needK(bar, M);
      if (n.lin) lins.push(n.lin);
      sum = Math.max(sum, n.sum);
    });
    lins.sort(function (a, b) { return a - b; });
    var q = lins.length ? lins[Math.floor(lins.length * 0.5)] : 0;
    return { k: Math.max(q, sum) || 0.05, sum: sum };
  };
  // позиции долей в такте (px от тактовой черты): линейно по времени, но соседние
  // доли раздвигаются ровно настолько, чтобы не слипнуться
  TabView.prototype.place = function (bar, w, k, M) {
    var self = this, o = this.edge(M), pos = new Map();
    bar.voices.forEach(function (v) {
      var main = v.beats.filter(function (b) { return !b.graceType; });
      var x = main.map(function (b) { return o + b.displayStart * k; });
      var d = main.map(function (b, i) { return i + 1 < main.length ? self.width(b, M) / 2 + self.width(main[i + 1], M) / 2 + M.gap : 0; });
      var lim = main.length ? w - (self.width(main[main.length - 1], M) / 2 + M.gap * 0.5 + o) : 0;
      var i;
      for (i = 1; i < x.length; i++) x[i] = Math.max(x[i], x[i - 1] + d[i - 1]);
      if (x.length && x[x.length - 1] > lim) {
        x[x.length - 1] = Math.max(lim, o);
        for (i = x.length - 2; i >= 0; i--) x[i] = Math.min(x[i], x[i + 1] - d[i]);
        if (x[0] < o) { // не влезает совсем — равномерно сжимаем
          var a = x[0], z = x[x.length - 1];
          for (i = 0; i < x.length; i++) x[i] = o + (z > a ? (x[i] - a) / (z - a) * (Math.max(lim, o) - o) : 0);
        }
      }
      main.forEach(function (b, j) { pos.set(b.id, x[j]); });
    });
    return pos;
  };
  // от тактовой черты до центра первой доли
  TabView.prototype.edge = function (M) { return M.cw * 0.75 + 1; };

  TabView.prototype.render = function () {
    var host = this.host, M = this.metrics(), o = this.edge(M), self = this;
    var bars = this.m.bars, S = this.m.strings;
    var staffH = (S - 1) * M.line, tsFs = M.fs * 0.95; // размер такта — чуть крупнее цифр лада, не больше
    var digits = 1;
    bars.forEach(function (b) { digits = Math.max(digits, String(b.mb.timeSignatureNumerator).length, String(b.mb.timeSignatureDenominator).length); });
    var gutter = Math.ceil(tsFs * 0.6 * digits + 4);
    var W = Math.max(120, host.clientWidth - gutter - 2);

    // самая частая длина такта задаёт, сколько тактов в строке
    var freq = {}, common = bars[0] ? bars[0].ticks : 3840;
    bars.forEach(function (b) { freq[b.ticks] = (freq[b.ticks] || 0) + 1; if (freq[b.ticks] > freq[common]) common = b.ticks; });
    var need = this.minK(M), kMin = need.k, bpr = this.opts.barsPerRow, n, k;
    if (bpr > 0) { n = bpr; k = W / (n * common); }
    // если до следующего такта в строке не хватает до 15% — чуть ужимаем время
    // но не так, чтобы самый плотный такт перестал вмещать свои ноты подряд
    else {
      n = Math.max(1, Math.floor(W / (kMin * common) * 1.15));
      while (n > 1 && W / (n * common) < need.sum) n--;
      k = W / (n * common);
    }

    // строки: новый размер — новая строка. Исключения: затакт в начале песни не
    // занимает строку, а если размер меняется часто (чаще раза на 6 тактов), строки
    // не рвутся — размер стоит на поле у каждой строки и мелко над тактом, где сменился
    var changes = 0;
    bars.forEach(function (b, i) { if (i && b.ts !== bars[i - 1].ts) changes++; });
    var mixed = changes * 6 > bars.length;
    var pickup = bars.length > 1 && bars[0].ts !== bars[1].ts && bars[0].ticks < bars[1].ticks;
    var rows = [], row = null;
    bars.forEach(function (b, i) {
      var w = Math.min(b.ticks * k, W), tsChange = i > 0 && b.ts !== bars[i - 1].ts;
      var force = i === 0 || (tsChange && !mixed && !(pickup && i === 1));
      if (!row || force || row.w + w > W + 0.5 || (bpr > 0 && row.bars.length >= bpr)) {
        var shown = i === 0 && pickup ? bars[1].mb : b.mb;
        row = { bars: [], w: 0, ts: force || mixed ? shown : null };
        rows.push(row);
      }
      row.bars.push({ bar: b, x: row.w, w: w, tsMark: mixed && tsChange && row.bars.length > 0 });
      row.w += w;
    });

    var letters = this.opts.letters;
    var topBand = M.small * 1.25 + (letters ? M.small * 1.15 : 0) + M.fs * 0.35;
    var rowH = topBand + staffH + M.fs * 1.25;
    var totalW = gutter + Math.max.apply(null, rows.map(function (r) { return r.w; })) + 2;
    var svg = el("svg", { class: "tv", width: r1(totalW), height: r1(rows.length * rowH), viewBox: "0 0 " + r1(totalW) + " " + r1(rows.length * rowH) });
    this.beatPos = new Map();
    this.rows = [];

    rows.forEach(function (row, ri) {
      var y0 = ri * rowH + topBand, g = el("g", { class: "row" });
      var x0 = gutter, xEnd = gutter + row.w;
      self.rows.push({ y: ri * rowH, h: rowH, y0: y0, staffH: staffH, x0: x0, bars: row.bars, k: k, o: o });
      g.appendChild(el("rect", { class: "hl", x: 0, y: r1(y0 - M.fs * 0.6), width: 0, height: r1(staffH + M.fs * 1.2), visibility: "hidden" }));
      for (var s = 0; s < S; s++) {
        g.appendChild(el("line", { class: "str", x1: x0, x2: r1(xEnd), y1: r1(y0 + s * M.line), y2: r1(y0 + s * M.line) }));
      }
      if (row.ts) {
        var cx = (gutter - 3) / 2, mid = y0 + staffH / 2;
        g.appendChild(el("text", { class: "ts", x: r1(cx), y: r1(mid - tsFs * 0.08), "font-size": r1(tsFs) }, String(row.ts.timeSignatureNumerator)));
        g.appendChild(el("text", { class: "ts", x: r1(cx), y: r1(mid + tsFs * 0.8), "font-size": r1(tsFs) }, String(row.ts.timeSignatureDenominator)));
      }
      row.bars.forEach(function (rb, bi) {
        var bx = x0 + rb.x, mb = rb.bar.mb;
        g.appendChild(el("line", { class: "bl", x1: r1(bx), x2: r1(bx), y1: y0, y2: r1(y0 + staffH) }));
        if (mb.isRepeatStart) self.repeat(g, bx, y0, M, true);
        if (mb.repeatCount > 0) {
          self.repeat(g, bx + rb.w, y0, M, false);
          if (mb.repeatCount > 2) // ×N — сколько раз играть (×2 подразумевается)
            g.appendChild(el("text", { class: "rx", x: r1(bx + rb.w - 2), y: r1(ri * rowH + M.small), "font-size": r1(M.small) }, "×" + mb.repeatCount));
        }
        var label = String(mb.index + 1) + (mb.section && mb.section.text ? "  " + mb.section.text : "");
        if (mb.alternateEndings) {
          var ends = []; for (var e = 0; e < 8; e++) if (mb.alternateEndings & (1 << e)) ends.push(e + 1);
          label += "  " + ends.join(",") + ".";
        }
        var bn = el("text", { class: "bn", x: r1(bx + 1), y: r1(ri * rowH + M.small), "font-size": r1(M.small) }, label);
        if (rb.tsMark) {
          var ts = document.createElementNS(NS, "tspan");
          ts.setAttribute("class", "tsm"); ts.textContent = "  " + rb.bar.ts;
          bn.appendChild(ts);
        }
        g.appendChild(bn);
        self.drawBar(g, rb, bx, y0, M, o, k, ri);
      });
      var last = row.bars[row.bars.length - 1];
      var endX = x0 + row.w, isEnd = last.bar.index === bars.length - 1;
      g.appendChild(el("line", { class: isEnd ? "bl end" : "bl", x1: r1(endX - (isEnd ? 1.5 : 0)), x2: r1(endX - (isEnd ? 1.5 : 0)), y1: y0, y2: r1(y0 + staffH) }));
      if (isEnd) g.appendChild(el("line", { class: "bl", x1: r1(endX - 5), x2: r1(endX - 5), y1: y0, y2: r1(y0 + staffH) }));
      svg.appendChild(g);
    });
    // дуги легато поверх чисел
    this.arcs(svg, M);
    this.cursor = el("rect", { class: "cur", x: 0, y: 0, width: 2, height: r1(staffH + M.fs * 1.2), visibility: "hidden" });
    svg.appendChild(this.cursor);
    this.M = M;
    var self2 = this;
    svg.addEventListener("click", function (ev) { self2.click(ev); });
    host.replaceChildren(svg);
    this.svg = svg;
    if (this.lastTick) this.moveCursor(this.lastTick.beat, this.lastTick.frac, false);
  };

  TabView.prototype.repeat = function (g, x, y0, M, start) {
    var S = this.m.strings, h = (S - 1) * M.line, dx = start ? 3.5 : -3.5;
    g.appendChild(el("line", { class: "bl thick", x1: r1(x + (start ? 1.5 : -1.5)), x2: r1(x + (start ? 1.5 : -1.5)), y1: y0, y2: r1(y0 + h) }));
    var mid = y0 + h / 2;
    [-M.line * 0.5, M.line * 0.5].forEach(function (d) {
      g.appendChild(el("circle", { class: "dot", cx: r1(x + dx * 2), cy: r1(mid + d), r: r1(M.fs * 0.12) }));
    });
  };

  TabView.prototype.drawBar = function (g, rb, bx, y0, M, o, k, ri) {
    var S = this.m.strings, self = this, letters = this.opts.letters, pos = this.place(rb.bar, rb.w, k, M);
    rb.bar.voices.forEach(function (v) {
      var beats = v.beats;
      beats.forEach(function (b, i) {
        var x;
        if (b.graceType) {
          // форшлаг — мелко перед своей долей
          var nx = beats.slice(i + 1).filter(function (n) { return !n.graceType; })[0];
          var base = bx + (nx ? pos.get(nx.id) : o);
          x = base - M.cw * 1.15;
        } else x = bx + pos.get(b.id);
        var bg = el("g", { class: "beat" + (b.graceType ? " grace" : "") + (b.isRest ? " rest" : "") });
        self.beatPos.set(b.id, { row: ri, x: x, bar: rb, beat: b, el: bg });
        if (letters && v.index === 0 && !b.graceType) {
          bg.appendChild(el("text", { class: "dur", x: r1(x), y: r1(y0 - M.fs * 0.55), "font-size": r1(M.small) }, letterOf(b)));
        }
        var fs = b.graceType ? M.grace : M.fs;
        b.notes.forEach(function (n) {
          var y = y0 + (S - n.string) * M.line, t = fretLabel(n), w = t.length * fs * 0.6;
          bg.appendChild(el("rect", { class: "knock", x: r1(x - w / 2 - 1), y: r1(y - fs * 0.45), width: r1(w + 2), height: r1(fs * 0.9) }));
          bg.appendChild(el("text", { class: "fret" + (n.isTieDestination || n.isGhost ? " soft" : ""), x: r1(x), y: r1(y), "font-size": r1(fs) }, t));
          if (n.slideOutType) {
            var up = n.slideTarget ? n.slideTarget.fret >= n.fret : false;
            var x1 = x + w / 2 + 1.5, x2 = x1 + M.cw * 0.9, d = M.line * 0.22;
            bg.appendChild(el("line", { class: "fx", x1: r1(x1), x2: r1(x2), y1: r1(y + (up ? d : -d)), y2: r1(y + (up ? -d : d)) }));
          }
          if (n.vibrato) bg.appendChild(el("text", { class: "vib", x: r1(x + w / 2), y: r1(y - fs * 0.5), "font-size": r1(fs * 0.8) }, "~"));
        });
        g.appendChild(bg);
      });
    });
  };

  TabView.prototype.arcs = function (svg, M) {
    var S = this.m.strings, self = this, g = el("g", { class: "arcs" });
    this.beatPos.forEach(function (p) {
      p.beat.notes.forEach(function (n) {
        var d = n.isHammerPullOrigin && n.hammerPullDestination;
        if (!d) return;
        var q = self.beatPos.get(d.beat.id);
        var row = self.rows[p.row], y = row.y0 + (S - n.string) * M.line - M.fs * 0.5;
        var x1 = p.x + M.cw * 0.25, x2 = q && q.row === p.row ? q.x - M.cw * 0.25 : row.x0 + row.bars.reduce(function (a, b) { return a + b.w; }, 0);
        var h = Math.min(M.line * 0.55, (x2 - x1) * 0.35);
        g.appendChild(el("path", { class: "arc", d: "M" + r1(x1) + " " + r1(y) + " Q" + r1((x1 + x2) / 2) + " " + r1(y - h * 2) + " " + r1(x2) + " " + r1(y) }));
        g.appendChild(el("text", { class: "hp", x: r1((x1 + x2) / 2), y: r1(y - h - M.small * 0.35), "font-size": r1(M.small * 0.85) }, d.fret < n.fret ? "p" : "h"));
      });
    });
    svg.appendChild(g);
  };

  // курсор: доля и доля пройденного в ней (0..1)
  TabView.prototype.moveCursor = function (beat, frac, scroll) {
    var p = beat && this.beatPos.get(beat.id);
    this.lastTick = beat ? { beat: beat, frac: frac } : null;
    if (this.active) this.active.classList.remove("on");
    if (this.hlRow) this.hlRow.setAttribute("visibility", "hidden");
    if (!p) { this.cursor.setAttribute("visibility", "hidden"); return; }
    var row = this.rows[p.row], M = this.M;
    var nx = beat.nextBeat && this.beatPos.get(beat.nextBeat.id);
    var x2 = nx && nx.row === p.row && nx.x > p.x ? nx.x : row.x0 + p.bar.x + p.bar.w + row.o;
    var x = p.x + (beat.graceType ? 0 : (x2 - p.x) * frac);
    this.cursor.setAttribute("x", r1(x - 1));
    this.cursor.setAttribute("y", r1(row.y0 - M.fs * 0.6));
    this.cursor.setAttribute("visibility", "visible");
    p.el.classList.add("on"); this.active = p.el;
    var hl = this.svg.children[p.row].firstChild;
    hl.setAttribute("x", r1(row.x0 + p.bar.x)); hl.setAttribute("width", r1(p.bar.w));
    hl.setAttribute("visibility", "visible"); this.hlRow = hl;
    if (scroll && this.curRow !== p.row) {
      this.curRow = p.row;
      var r = this.svg.getBoundingClientRect(), top = r.top + row.y, vh = window.innerHeight;
      if (top < vh * 0.15 || top + row.h > vh * 0.85) window.scrollTo({ top: window.scrollY + top - vh * 0.3, behavior: "smooth" });
    }
  };

  TabView.prototype.click = function (ev) {
    var r = this.svg.getBoundingClientRect(), x = ev.clientX - r.left, y = ev.clientY - r.top;
    var ri = this.rows.findIndex(function (row) { return y >= row.y && y < row.y + row.h; });
    if (ri < 0) return;
    var best = null, bd = Infinity;
    this.beatPos.forEach(function (p) {
      if (p.row !== ri || p.beat.graceType) return;
      var d = Math.abs(p.x - x);
      if (d < bd) { bd = d; best = p.beat; }
    });
    if (best && this.opts.onSeek) this.opts.onSeek(best);
  };

  TabView.prototype.set = function (patch) {
    for (var key in patch) this.opts[key] = patch[key];
    this.render();
  };

  window.TabView = TabView;
})();
