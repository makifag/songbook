// Песенник: главная — поиск, фильтры, вкладки сложности, «хочу найти», убранные.
(function () {
  "use strict";
  var LABEL = { alphatex: "таб", gp: "таб", chordpro: "аккорды", text: "текст" };
  var $ = function (id) { return document.getElementById(id); };
  var list = $("list"), q = $("q"), kindFilter = $("kindFilter"), artistFilter = $("artistFilter"), famFilter = $("famFilter");
  var diff = ""; // "" — все, "0" — не отмечена, "1".."4"
  var esc = function (s) { return String(s).replace(/[&<>"]/g, function (c) { return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]; }); };

  Array.from(new Set(SONGS.map(function (s) { return s.artist; }))).filter(Boolean).sort().forEach(function (a) {
    var o = document.createElement("option"); o.value = a; o.textContent = a; artistFilter.appendChild(o);
  });
  SB.FAM.forEach(function (name, i) {
    var o = document.createElement("option"); o.value = String(i); o.textContent = SB.MOON[i] + " " + name; famFilter.appendChild(o);
  });

  // вкладки сложности
  var tabs = $("diffTabs");
  [["", "все"], ["1", "легко"], ["2", "средне"], ["3", "трудно"], ["4", "вызов"], ["0", "не отмечены"]].forEach(function (t) {
    var b = document.createElement("button");
    b.type = "button"; b.setAttribute("role", "tab"); b.dataset.d = t[0];
    b.innerHTML = (t[0] && t[0] !== "0" ? SB.bars(+t[0]) : "") + "<span>" + t[1] + "</span>";
    b.onclick = function () { diff = t[0]; render(); };
    tabs.appendChild(b);
  });

  function norm(s) { return (s || "").toLowerCase(); }
  function render() {
    var query = norm(q.value), kind = kindFilter.value, artist = artistFilter.value, fam = famFilter.value;
    tabs.querySelectorAll("button").forEach(function (b) { b.setAttribute("aria-selected", String(b.dataset.d === diff)); });
    var shown = SONGS.filter(function (s) { return !SB.isHidden(s.slug); });
    var filtered = shown.filter(function (s) {
      var mk = SB.mark(s.slug);
      if (kind && s.kind !== kind) return false;
      if (artist && s.artist !== artist) return false;
      if (fam && mk.f !== +fam) return false;
      if (diff && mk.d !== +diff) return false;
      return !query || norm(s.title).indexOf(query) !== -1 || norm(s.artist).indexOf(query) !== -1;
    });
    list.innerHTML = "";
    filtered.forEach(function (s) {
      var li = document.createElement("li"), a = document.createElement("a");
      a.href = "songs/" + s.slug + ".html";
      a.innerHTML = '<span class="t">' + esc(s.title) + '</span><span class="a">' + esc(s.artist) + "</span>";
      var f = document.createElement("span"); f.className = "f " + s.format; f.textContent = LABEL[s.format] || s.format;
      li.appendChild(a); li.appendChild(SB.marksEl(s.slug)); li.appendChild(f);
      list.appendChild(li);
    });
    $("count").textContent = filtered.length + " из " + shown.length;
    // доступно только когда есть связь с сервером
    tabs.hidden = famFilter.hidden = !SB.online;
    renderWish(); renderGone();
  }

  function renderWish() {
    var box = $("wish"), w = SB.state.wish || [];
    box.hidden = !SB.owner; // личный список — только хозяину
    $("wishN").textContent = w.length ? "(" + w.length + ")" : "";
    $("wishForm").hidden = !SB.owner;
    $("wishList").innerHTML = w.map(function (it) {
      var link = it.url ? ' <a href="' + esc(it.url) + '" target="_blank" rel="noopener">' + esc(it.url.replace(/^https?:\/\/(www\.)?/, "").slice(0, 48)) + "</a>" : "";
      return "<li><span>" + esc(it.text) + link + "</span>" +
        (SB.owner ? '<button type="button" class="linkish" data-del="' + it.id + '" title="Убрать из списка">✕</button>' : "") + "</li>";
    }).join("");
    $("wishList").querySelectorAll("[data-del]").forEach(function (b) {
      b.onclick = function () { if (confirm("Убрать из списка?")) SB.post("wish", { del: +b.dataset.del }); };
    });
  }
  $("wishForm").onsubmit = function (e) {
    e.preventDefault();
    var text = $("wishText").value.trim(), url = $("wishUrl").value.trim();
    if (!text && !url) return;
    SB.post("wish", { add: { text: text, url: url } }).then(function () { $("wishText").value = ""; $("wishUrl").value = ""; });
  };
  try { if (localStorage.getItem("songbook.wishOpen") !== "0") $("wish").open = true; } catch (e) { $("wish").open = true; }
  $("wish").addEventListener("toggle", function () { try { localStorage.setItem("songbook.wishOpen", this.open ? "1" : "0"); } catch (e) {} });

  function renderGone() {
    var gone = SONGS.filter(function (s) { return SB.isHidden(s.slug); });
    $("goneBox").hidden = !SB.owner || !gone.length;
    $("goneN").textContent = "(" + gone.length + ")";
    $("goneList").innerHTML = gone.map(function (s) {
      return '<li><a href="songs/' + s.slug + '.html">' + esc(s.title) + '</a> <span class="a">' + esc(s.artist) + "</span> " +
        '<button type="button" class="linkish" data-slug="' + s.slug + '">вернуть</button></li>';
    }).join("");
    $("goneList").querySelectorAll("[data-slug]").forEach(function (b) {
      b.onclick = function () { SB.post("hide", { slug: b.dataset.slug, hidden: false }); };
    });
  }

  $("keyBtn").onclick = function () {
    var k = prompt(SB.owner ? "Ключ хозяина задан. Новый ключ (пусто — выйти):" : "Ключ хозяина:", "");
    if (k === null) return;
    SB.setKey(k.trim()).then(function (ok) {
      if (k.trim() && !ok) alert("Ключ не подошёл");
      render();
    });
  };

  q.addEventListener("input", render);
  kindFilter.addEventListener("change", render);
  artistFilter.addEventListener("change", render);
  famFilter.addEventListener("change", render);
  SB.on(render);
  render();
})();
