// Песенник: то, что хозяин меняет с сайта (Worker + D1, см. worker/index.js).
// Читать может любой; менять — только с ключом хозяина. Ключ задаётся один раз
// ссылкой вида …/#key=XXXX (или «ключ» внизу главной) и хранится в localStorage.
// Без сети (zip, офлайн) всё это просто не показывается.
(function () {
  "use strict";
  var KEY = "songbook.ownerKey";
  var store = {
    get: function (k) { try { return localStorage.getItem(k) || ""; } catch (e) { return ""; } },
    set: function (k, v) { try { if (v) localStorage.setItem(k, v); else localStorage.removeItem(k); } catch (e) {} },
  };
  var m = /^#key=([^&]+)/.exec(location.hash);
  if (m) {
    store.set(KEY, decodeURIComponent(m[1]));
    history.replaceState(null, "", location.pathname + location.search);
  }
  var root = new URL(document.currentScript.src.replace(/assets\/owner\.js.*$/, ""), location.href);
  function api(path) { return new URL("api/" + path, root).href; }

  var SB = {
    state: { hidden: [], marks: {}, wish: [] },
    owner: false,
    online: false,
    listeners: [],
    on: function (fn) { this.listeners.push(fn); if (this.loaded) fn(this.state); },
    emit: function () { var s = this.state; this.listeners.forEach(function (fn) { fn(s); }); },
    key: function () { return store.get(KEY); },
    setKey: function (k) {
      store.set(KEY, k);
      return this.check();
    },
    check: function () {
      var self = this, k = this.key();
      if (!k) { self.owner = false; return Promise.resolve(false); }
      return fetch(api("check"), { headers: { "x-key": k }, cache: "no-store" })
        .then(function (r) { self.owner = r.ok; return r.ok; })
        .catch(function () { self.owner = false; return false; });
    },
    load: function () {
      var self = this;
      return Promise.all([
        fetch(api("state"), { cache: "no-store" }).then(function (r) { if (!r.ok) throw new Error(r.status); return r.json(); }),
        this.check(),
      ]).then(function (res) {
        self.state = res[0]; self.online = true; self.loaded = true; self.emit();
      }).catch(function () { self.loaded = true; self.emit(); });
    },
    post: function (path, body) {
      var self = this;
      return fetch(api(path), {
        method: "POST", headers: { "content-type": "application/json", "x-key": this.key() }, body: JSON.stringify(body),
      }).then(function (r) {
        return r.json().then(function (j) {
          if (!r.ok) throw new Error(j.error || r.status);
          self.state = j; self.emit(); return j;
        });
      }).catch(function (e) { alert("Не сохранилось: " + e.message); self.emit(); throw e; });
    },
    isHidden: function (slug) { return this.state.hidden.indexOf(slug) !== -1; },
    mark: function (slug) { return this.state.marks[slug] || { d: 0, f: 0 }; },
  };

  // ---- отметки: знакомство (фазы луны) и сложность (столбики, как сигнал) ----
  var MOON = ["○", "◔", "◑", "◕", "●"];
  var FAM = ["не играл", "разбираю", "играю по табу", "почти наизусть", "наизусть"];
  var DIFF = ["сложность не отмечена", "легко", "средне", "трудно", "вызов"];
  function bars(d) {
    var s = '<span class="sig" aria-hidden="true">';
    for (var i = 1; i <= 4; i++) s += '<i class="' + (i <= d ? "on" : "") + '" style="height:' + (i * 25) + '%"></i>';
    return s + "</span>";
  }
  SB.MOON = MOON; SB.FAM = FAM; SB.DIFF = DIFF; SB.bars = bars;

  // значки отметок; хозяину — кнопки, которые по касанию перебирают уровни
  SB.marksEl = function (slug) {
    var box = document.createElement("span");
    box.className = "marks";
    function draw() {
      var mk = SB.mark(slug), tag = SB.owner ? "button" : "span";
      box.innerHTML =
        "<" + tag + ' class="mk fam f' + mk.f + '" title="знакомство: ' + FAM[mk.f] + '"' + (SB.owner ? ' type="button"' : "") + ">" +
        '<span class="moon">' + MOON[mk.f] + "</span></" + tag + ">" +
        "<" + tag + ' class="mk diff d' + mk.d + '" title="' + (mk.d ? "сложность: " : "") + DIFF[mk.d] + '"' + (SB.owner ? ' type="button"' : "") + ">" +
        bars(mk.d) + "</" + tag + ">";
      box.hidden = !SB.owner && !mk.d && !mk.f;
      if (!SB.owner) return;
      var b = box.querySelectorAll("button");
      b[0].onclick = function (e) { e.preventDefault(); e.stopPropagation(); bump("f"); };
      b[1].onclick = function (e) { e.preventDefault(); e.stopPropagation(); bump("d"); };
    }
    function bump(k) {
      var mk = SB.mark(slug), next = { d: mk.d, f: mk.f };
      next[k] = (mk[k] + 1) % 5;
      SB.state.marks[slug] = next; draw(); // сразу на экране, сервер догонит
      var body = { slug: slug }; body[k] = next[k];
      SB.post("mark", body);
    }
    draw();
    box.redraw = draw;
    return box;
  };

  // ---- страница песни: отметки под заголовком, «убрать из песенника» внизу ----
  function songPage() {
    var src = document.getElementById("song-src");
    if (!src) return;
    var slug = decodeURIComponent(location.pathname.split("/").pop().replace(/\.html$/, ""));
    var head = document.querySelector(".head > div");
    var marks = SB.marksEl(slug);
    head.appendChild(marks);
    var banner = document.createElement("p");
    banner.className = "gone"; banner.hidden = true;
    document.querySelector(".sheet").insertBefore(banner, document.querySelector(".sheet").firstChild);
    var foot = document.createElement("p");
    foot.className = "owner-foot"; foot.hidden = true;
    foot.innerHTML = '<button type="button" class="linkish">убрать из песенника</button>';
    document.querySelector(".sheet").appendChild(foot);
    foot.firstChild.onclick = function () {
      if (confirm("Убрать «" + document.querySelector("h1").textContent + "» из песенника? Вернуть можно на главной, внизу.")) {
        SB.post("hide", { slug: slug, hidden: true }).then(function () { location.href = "../index.html"; });
      }
    };
    SB.on(function () {
      marks.redraw();
      foot.hidden = !SB.owner || SB.isHidden(slug);
      var gone = SB.isHidden(slug);
      banner.hidden = !gone;
      if (gone) {
        banner.innerHTML = "Эта песня убрана из песенника. " + (SB.owner ? '<button type="button" class="linkish">вернуть</button>' : "");
        var b = banner.querySelector("button");
        if (b) b.onclick = function () { SB.post("hide", { slug: slug, hidden: false }); };
      }
    });
  }

  window.SB = SB;
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", function () { songPage(); SB.load(); });
  else { songPage(); SB.load(); }
})();
