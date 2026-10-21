#!/usr/bin/env python3
"""Offline songbook builder. See ТЗ.md. Usage: python build.py [--refetch]"""
import argparse
import hashlib
import html as html_mod
import json
import random
import re
import sys
import time
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup

ROOT = Path(__file__).parent
CACHE_DIR = ROOT / "cache"
OUT_DIR = ROOT / "songbook"
SONGS_DIR = OUT_DIR / "songs"
RAW_DIR = OUT_DIR / "raw"
REPORTS_DIR = OUT_DIR / "reports"
SOURCES_FILE = ROOT / "sources.json"
MANUAL_FILE = ROOT / "manual_entries.json"
ZIP_FILE = ROOT / "songbook.zip"
FORMATS_DIR = ROOT / "formats"          # .atex/.cho из tools/convert_all.py (проверенные)
ASSETS_SRC = ROOT / "assets"            # общий css/js страниц песен
VENDOR_SRC = ROOT / "vendor"            # alphaTab (движок нот/табов + шрифт + звук)
SONGS_META = OUT_DIR / "songs.json"     # метаданные песен — для сборки без сети (--offline)
GP_EXT = (".gp", ".gp3", ".gp4", ".gp5", ".gpx")
CACHE_MAX_AGE_SECONDS = 30 * 86400

# gametabs.net reshuffles game/song slugs over time; these bookmarks drifted since capture.
# Verified by hand against live /games/{game} listings (2026-07-30).
URL_OVERRIDES = {
    "https://gametabs.net/tabs/neverhood/southern-front-porch-whistler":
        "https://gametabs.net/tabs/the-neverhood/southern-front-porch-whistler",
    "https://gametabs.net/tabs/elder-scrolls-v-skyrim/sons-skyrim":
        "https://gametabs.net/tabs/the-elder-scrolls-v-skyrim/sons-of-skyrim",
    "https://gametabs.net/tabs/elder-scrolls-iii-morrowind/call-of-magic-main-theme":
        "https://gametabs.net/tabs/the-elder-scrolls-iii-morrowind/call-of-magic-main-theme",
    "https://gametabs.net/tabs/warcraft-ii-tides-darkness/human-theme":
        "https://gametabs.net/tabs/warcraft-ii-tides-of-darkness/human-theme",
    "https://gametabs.net/tabs/undertale/sans-0":
        "https://gametabs.net/tabs/undertale/sans",
    "https://gametabs.net/tabs/cave-story/heros-end-0":
        "https://gametabs.net/tabs/cave-story/heros-end",
    "https://gametabs.net/tabs/final-fantasy-vi/terras-theme-1":
        "https://gametabs.net/tabs/final-fantasy-vi/terras-theme-3",
    "https://gametabs.net/tabs/final-fantasy-vi/kefkas-theme-1":
        "https://gametabs.net/tabs/final-fantasy-vi/kefkas-theme",
}

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/124.0 Safari/537.36",
    "Accept-Language": "ru,en;q=0.8",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

_last_request_time = {}


class FetchError(Exception):
    pass


class Gone(Exception):
    """404/410 - resource permanently unavailable, no point retrying."""


def cache_path_for(key):
    h = hashlib.sha1(key.encode("utf-8")).hexdigest()
    return CACHE_DIR / f"{h}.html"


def polite_get(url, refetch=False, cache_key=None, max_retries=3, base_backoff=2, min_delay=1, max_delay=3):
    """GET url with disk cache, per-domain rate limit, retry w/ backoff.
    Returns response text. Raises Gone on 404/410, FetchError otherwise."""
    cache_key = cache_key or url
    cpath = cache_path_for(cache_key)
    if cpath.exists() and not refetch:
        age = time.time() - cpath.stat().st_mtime
        if age < CACHE_MAX_AGE_SECONDS:
            return cpath.read_text(encoding="utf-8", errors="replace")

    domain = urlparse(url).netloc
    last = _last_request_time.get(domain, 0)
    delay = random.uniform(min_delay, max_delay)
    elapsed = time.time() - last
    if elapsed < delay:
        time.sleep(delay - elapsed)

    last_err = None
    for attempt in range(max_retries):
        try:
            r = requests.get(url, headers=HEADERS, timeout=25)
            _last_request_time[domain] = time.time()
            if r.status_code == 200:
                r.encoding = r.encoding or "utf-8"
                text = r.text
                cpath.write_text(text, encoding="utf-8")
                return text
            if r.status_code in (404, 410):
                raise Gone(f"HTTP {r.status_code}")
            last_err = f"HTTP {r.status_code}"
        except Gone:
            raise
        except requests.RequestException as e:
            last_err = str(e)
        if attempt < max_retries - 1:
            time.sleep((2 ** attempt) * base_backoff)
    raise FetchError(f"{url}: {last_err}")


# ---------- transliteration / slugs ----------

_CYR2LAT = {
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "yo",
    "ж": "zh", "з": "z", "и": "i", "й": "y", "к": "k", "л": "l", "м": "m",
    "н": "n", "о": "o", "п": "p", "р": "r", "с": "s", "т": "t", "у": "u",
    "ф": "f", "х": "h", "ц": "ts", "ч": "ch", "ш": "sh", "щ": "sch", "ъ": "",
    "ы": "y", "ь": "", "э": "e", "ю": "yu", "я": "ya",
}


def translit(s):
    return "".join(_CYR2LAT.get(ch, ch) for ch in s.lower())


def slugify(s):
    s = translit(s or "")
    s = re.sub(r"[^a-z0-9]+", "-", s)
    return s.strip("-") or "item"


_used_slugs = set()


def make_slug(src):
    artist = src.get("artist") or ""
    work = src.get("work") or src.get("title_raw") or ""
    base = slugify(f"{artist}-{work}" if artist else work)
    slug = base
    n = 2
    while slug in _used_slugs:
        slug = f"{base}-{n}"
        n += 1
    _used_slugs.add(slug)
    return slug


# ---------- handlers: html/json -> {title, artist, kind, meta, body} ----------

def extract_gametabs(text, src):
    soup = BeautifulSoup(text, "lxml")
    title_el = soup.find(id="tab-page-tab-name")
    title = title_el.get_text(strip=True) if title_el else src["title_raw"]
    game_el = soup.select_one("#tab-page-title-section h3")
    game = game_el.get_text(strip=True) if game_el else (src.get("artist") or "")
    pre = soup.find("pre", id="tab-text-view-text")
    if not pre:
        raise ValueError("tab-text-view-text not found")
    body = pre.get_text()
    meta = {}
    for p in soup.select("#tab-page-top-section p"):
        txt = p.get_text(" ", strip=True)
        for label in ("Composer", "Style", "Instrument", "Tuning", "Platform"):
            if txt.startswith(label + ":"):
                meta[label.lower()] = txt.split(":", 1)[1].strip()
    author_el = soup.select_one(".user-username-username")
    if author_el:
        meta["arranger"] = author_el.get_text(strip=True).lstrip("@")
    if not body.strip():
        raise ValueError("empty tab body")
    return {"title": title, "artist": game, "kind": "tab", "meta": meta, "body": body}


def extract_amdm(text, src):
    soup = BeautifulSoup(text, "lxml")
    h1 = soup.find("h1", itemtype=re.compile("MusicRecording")) or soup.find(
        "div", itemtype=re.compile("MusicRecording")
    )
    if not h1:
        h1 = soup.find("h1")
    artist_el = h1.find(itemprop="byArtist") if h1 else None
    name_el = h1.find(itemprop="name") if h1 else None
    artist = artist_el.get_text(strip=True) if artist_el else (src.get("artist") or "")
    title = name_el.get_text(strip=True) if name_el else src["title_raw"]
    pre = soup.find("pre", itemprop="chordsBlock")
    if not pre:
        raise ValueError("chordsBlock not found")
    body = pre.get_text()
    if not body.strip():
        raise ValueError("empty chords body")
    meta = {}
    m = re.search(r"[Кк]апо[:\s]*([^\n]{1,20})", body)
    if m:
        meta["capo"] = m.group(1).strip()
    return {"title": title, "artist": artist, "kind": "chords", "meta": meta, "body": body}


def extract_generic_chords(text, src):
    """gitaristu.ru — same pre[itemprop=chordsBlock] pattern as amdm."""
    soup = BeautifulSoup(text, "lxml")
    pre = soup.find("pre", itemprop="chordsBlock")
    if not pre:
        raise ValueError("chordsBlock not found")
    body = pre.get_text()
    if not body.strip():
        raise ValueError("empty chords body")
    title_tag = soup.find("title")
    title_text = title_tag.get_text(strip=True) if title_tag else src["title_raw"]
    title_text = re.sub(r"^Аккорды\s+", "", title_text)
    title_text = re.split(r",\s*(?:табы|аккорды)", title_text)[0]
    artist = src.get("artist") or ""
    song = title_text
    if " - " in title_text:
        artist_part, song_part = title_text.split(" - ", 1)
        artist = artist or artist_part.strip()
        song = song_part.strip()
    return {"title": song, "artist": artist, "kind": "chords", "meta": {}, "body": body}


def _protect_subline_spacing(text):
    """bs4 collapses runs of literal spaces in text nodes to a single space.
    mychords positions chords via literal spaces inside <span class="subline">,
    which itself nests <span class="b-accord__symbol"> tags - so the matching
    close tag can't be found with a non-greedy regex, we need balanced scanning.
    Swap runs of 2+ spaces for NBSP (preserved verbatim by bs4) before parsing."""
    marker = '<span class="subline">'
    out = []
    i = 0
    while True:
        idx = text.find(marker, i)
        if idx == -1:
            out.append(text[i:])
            break
        out.append(text[i:idx])
        pos = idx + len(marker)
        depth = 1
        while depth > 0:
            next_open = text.find("<span", pos)
            next_close = text.find("</span>", pos)
            if next_close == -1:
                break
            if next_open != -1 and next_open < next_close:
                depth += 1
                pos = next_open + 5
            else:
                depth -= 1
                pos = next_close + 7
        inner = text[idx + len(marker):pos - 7]
        inner = re.sub(r"  +", lambda sp: "\xa0" * len(sp.group()), inner)
        out.append(marker + inner + "</span>")
        i = pos
    return "".join(out)


def extract_mychords(text, src):
    text = _protect_subline_spacing(text)
    soup = BeautifulSoup(text, "lxml")
    meta_name = soup.find("meta", itemprop="name")
    full_title = meta_name["content"].strip() if meta_name and meta_name.get("content") else src["title_raw"]
    artist, _, song = full_title.partition(" - ")
    if not song:
        artist, song = (src.get("artist") or ""), full_title
    lyrics = soup.select_one(".w-words__text[itemprop=text]")
    if not lyrics:
        lyrics = soup.select_one("[itemprop=lyrics]")
    if not lyrics:
        raise ValueError("lyrics block not found")
    lines = []
    for child in lyrics.find_all(recursive=False):
        classes = child.get("class", []) or []
        if "pline" in classes:
            sublines = child.select(".subline")
            if len(sublines) >= 2:
                chord_line = sublines[0].get_text()
                lyric_line = sublines[1].get_text()
                if chord_line.strip():
                    lines.append(chord_line)
                lines.append(lyric_line)
            elif sublines:
                lines.append(sublines[0].get_text())
        elif "single-line" in classes:
            lines.append(child.get_text())
        else:
            txt = child.get_text()
            if txt.strip() == "":
                lines.append("")
            else:
                lines.append(txt)
    body = "\n".join(lines).replace("\xa0", " ")
    if not body.strip():
        raise ValueError("empty lyrics body")
    return {"title": song.strip(), "artist": artist.strip(), "kind": "chords", "meta": {}, "body": body}


def extract_ultimateguitar(text, src):
    m = re.search(r'class="js-store"\s+data-content="([^"]+)"', text)
    if not m:
        raise ValueError("js-store data-content not found")
    data = json.loads(html_mod.unescape(m.group(1)))
    page_data = data["store"]["page"]["data"]
    wiki_tab = page_data["tab_view"]["wiki_tab"]
    content = wiki_tab["content"].replace("\r\n", "\n")
    content = re.sub(r"\[/?tab\]", "", content)
    content = re.sub(r"\[/?ch\]", "", content)
    tabinfo = page_data.get("tab", {})
    title = tabinfo.get("song_name") or src["title_raw"]
    artist = tabinfo.get("artist_name") or (src.get("artist") or "")
    meta = {}
    if tabinfo.get("tonality_name"):
        meta["key"] = tabinfo["tonality_name"]
    if tabinfo.get("difficulty"):
        meta["difficulty"] = tabinfo["difficulty"]
    body = content.strip("\n")
    if not body.strip():
        raise ValueError("empty UG content")
    return {"title": title, "artist": artist, "kind": "tab", "meta": meta, "body": body}


HANDLERS = {
    "gametabs_ascii": extract_gametabs,
    "amdm_chords": extract_amdm,
    "generic_chords": extract_generic_chords,
    "mychords_chords": extract_mychords,
    "ultimateguitar_json": extract_ultimateguitar,
}


# ---------- per-source processing ----------

WAYBACK_MAX_SNAPSHOTS_TRIED = 40


def handle_wayback(src, refetch):
    """amdm removed these under a rightsholder takedown; the *newest* wayback
    snapshot mirrors the takedown notice too, not the original page. Walk the
    CDX index backwards from most recent until a snapshot with real chords is found."""
    cdx_url = "http://web.archive.org/cdx/search/cdx?" + "&".join([
        "url=" + requests.utils.quote(src["url_norm"], safe=""),
        "output=json",
        "filter=statuscode:200",
    ])
    try:
        cdx_text = polite_get(
            cdx_url, refetch=refetch,
            cache_key=f"wayback-cdx-{src['url_norm']}",
            max_retries=5, base_backoff=5, min_delay=2, max_delay=4,
        )
        rows = json.loads(cdx_text)[1:]
    except (FetchError, json.JSONDecodeError) as e:
        return {"result": "gap", "src": src, "reason": f"wayback CDX: {e}"}
    if not rows:
        return {"result": "gap", "src": src, "reason": "no wayback snapshots found"}
    rows.sort(key=lambda row: row[1], reverse=True)

    last_err = "no snapshot with chords content found"
    for row in rows[:WAYBACK_MAX_SNAPSHOTS_TRIED]:
        ts = row[1]
        snap_url = f"http://web.archive.org/web/{ts}id_/{src['url_norm']}"
        try:
            snap_html = polite_get(snap_url, refetch=refetch, max_retries=4, base_backoff=4, min_delay=1.5, max_delay=3)
            extracted = extract_amdm(snap_html, src)
        except (FetchError, Gone, ValueError) as e:
            last_err = str(e)
            continue
        extracted["meta"]["wayback_snapshot"] = f"http://web.archive.org/web/{ts}/{src['url_norm']}"
        return {"result": "wayback", "src": src, "data": extracted}
    return {"result": "gap", "src": src, "reason": f"wayback: {last_err}"}


def handle_manual_vk_pdf(src, refetch):
    """Try direct doc download; only for the Segovia PDF entry."""
    try:
        domain = urlparse(src["url_norm"]).netloc
        last = _last_request_time.get(domain, 0)
        delay = random.uniform(1, 3)
        elapsed = time.time() - last
        if elapsed < delay:
            time.sleep(delay - elapsed)
        r = requests.get(src["url_norm"], headers=HEADERS, timeout=25, allow_redirects=True)
        _last_request_time[domain] = time.time()
        if r.status_code == 200 and r.content[:4] == b"%PDF":
            RAW_DIR.mkdir(parents=True, exist_ok=True)
            slug = make_slug(src)
            (RAW_DIR / f"{slug}.pdf").write_bytes(r.content)
            return {"result": "manual", "src": src, "note": src.get("note", "") + f" (PDF скачан в raw/{slug}.pdf)"}
    except requests.RequestException:
        pass
    return {"result": "manual", "src": src}


def process_source(src, refetch):
    status = src["status"]
    handler = src["handler"]

    if status == "manual" or handler in ("songsterr_api", "manual_search"):
        return {"result": "manual", "src": src}

    if handler == "manual_vk":
        if "doc-" in src["url_norm"] and "vk.com" in src["url_norm"]:
            return handle_manual_vk_pdf(src, refetch)
        return {"result": "manual", "src": src}

    if status == "dead_wayback":
        return handle_wayback(src, refetch)

    # status == live
    fn = HANDLERS.get(handler)
    if not fn:
        return {"result": "gap", "src": src, "reason": f"no handler for {handler}"}
    fetch_url = URL_OVERRIDES.get(src["url_norm"], src["url_norm"])
    try:
        text = polite_get(fetch_url, refetch=refetch)
    except Gone as e:
        return {"result": "gap", "src": src, "reason": f"источник удалён: {e}"}
    except FetchError as e:
        return {"result": "gap", "src": src, "reason": str(e)}
    try:
        extracted = fn(text, src)
    except Exception as e:
        return {"result": "gap", "src": src, "reason": f"extract error: {e}"}
    return {"result": "ok", "src": src, "data": extracted}


# ---------- output rendering ----------

SONG_TEMPLATE = """<!doctype html>
<html lang="ru"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<title>{title_esc} — {artist_esc}</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500;600&family=Literata:opsz,wght@7..72,400;7..72,600&display=swap">
<link rel="stylesheet" href="../assets/song.css">
</head><body>
<div class="wrap">
<nav class="top"><a href="../index.html">&larr; все песни</a></nav>
<main class="sheet">
<div class="head"><div><h1>{title_esc}</h1><div class="by">{artist_esc}</div></div>
<div class="meta">{chips_html}</div></div>
{notes_html}{downloads_html}<div class="controls" id="controls"></div>
<div id="view"></div>
{source_html}
</main>
</div>
<script type="text/plain" id="song-src" data-format="{fmt}" data-file="{file_attr}">
{src_text}</script>
{alphatab_tag}<script src="../assets/song.js"></script>
<script src="../assets/owner.js"></script>
</body></html>
"""

FORMAT_LABEL = {"alphatex": "таб", "chordpro": "аккорды", "gp": "таб · Guitar Pro", "text": "текст"}


def format_notes(slug):
    """Пометки конвертера (восстановленный ритм, поправленные ноты) — показываем на странице."""
    path = FORMATS_DIR / "status.json"
    if not path.exists():
        return []
    return json.loads(path.read_text(encoding="utf-8")).get(slug, {}).get("notes", [])


def _script_safe(text):
    """Текст внутри <script type=text/plain>: экранируем только закрывающий тег."""
    return text.replace("</script", "<\\/script")


def song_format(slug, downloads=None):
    """-> (format, содержимое для страницы, файл для data-file)."""
    atex = FORMATS_DIR / f"{slug}.atex"
    cho = FORMATS_DIR / f"{slug}.cho"
    if atex.exists():
        return "alphatex", atex.read_text(encoding="utf-8"), ""
    if cho.exists():
        return "chordpro", cho.read_text(encoding="utf-8"), ""
    for _, href in downloads or []:
        if href.lower().endswith(GP_EXT):
            return "gp", "", href
    return "text", None, ""


def render_song_html(slug, title, artist, kind, meta, body, downloads=None):
    fmt, content, file_attr = song_format(slug, downloads)
    if content is None:
        content = body
    chips = [FORMAT_LABEL[fmt]]
    notes = [f"при переводе: {n}" for n in format_notes(slug)]
    for k, v in meta.items():
        v = str(v)
        if k == "источник" or len(v) > 40:
            notes.append(f"{k}: {v}")
        else:
            chips.append(f"{k}: {v}")
    chips_html = "".join(f"<span>{html_mod.escape(c)}</span>" for c in chips)
    notes_html = f'<p class="notes">{html_mod.escape(chr(10).join(notes))}</p>\n' if notes else ""
    downloads_html = ""
    if downloads:
        links = " · ".join(f'<a href="{html_mod.escape(href)}">{html_mod.escape(label)}</a>' for label, href in downloads)
        downloads_html = f'<p class="downloads">{links}</p>\n'
    source_html = ""
    if fmt == "chordpro":  # табы текстом не показываем
        source_html = (
            '<details class="src"><summary>Исходный текст с сайта</summary>'
            f'<pre class="rawtxt">{html_mod.escape(body)}</pre></details>'
        )
    return SONG_TEMPLATE.format(
        title_esc=html_mod.escape(title),
        artist_esc=html_mod.escape(artist),
        chips_html=chips_html,
        notes_html=notes_html,
        downloads_html=downloads_html,
        source_html=source_html,
        fmt=fmt,
        file_attr=html_mod.escape(file_attr),
        src_text=_script_safe(content),
        alphatab_tag='<script src="../vendor/alphatab/alphaTab.min.js"></script>\n<script src="../assets/tabview.js"></script>\n' if fmt in ("alphatex", "gp") else "",
    )


def kind_ru(kind):
    return {"tab": "таб", "chords": "аккорды"}.get(kind, kind)


INDEX_TEMPLATE = """<!doctype html>
<html lang="ru"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<title>Песенник</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500;600&family=Literata:opsz,wght@7..72,400;7..72,600&display=swap">
<link rel="stylesheet" href="assets/song.css">
<style>
h1 {{ margin: 0; font: 600 clamp(1.8rem, 5vw, 2.6rem)/1.1 var(--f-text); }}
.bar {{ display: flex; flex-wrap: wrap; align-items: baseline; justify-content: space-between; gap: .5rem 1rem; }}
.bar a {{ font: 500 .8rem var(--f-mono); text-decoration: none; }}
.filters {{ display: flex; gap: .5rem; flex-wrap: wrap; padding: .6rem 0; }}
.filters input, .filters select {{ font: 1rem var(--f-text); padding: .55rem .7rem; border-radius: 6px;
  border: 0; background: var(--chip); color: var(--ink); }}
.filters input {{ flex: 1 1 14rem; min-width: 0; }}
.filters select {{ font: .85rem var(--f-mono); }}
.count {{ font: .8rem var(--f-mono); color: var(--muted); margin: 0; }}
ul.songs {{ list-style: none; margin: 0; padding: 0; }}
ul.songs li + li {{ border-top: 1px solid var(--rule); }}
ul.songs a {{ display: flex; align-items: baseline; justify-content: space-between; gap: .3rem 1rem; flex-wrap: wrap;
  padding: .7rem .2rem; color: var(--ink); text-decoration: none; }}
ul.songs a:hover .t {{ color: var(--accent); }}
.t {{ font-size: 1.05rem; }}
.a {{ color: var(--muted); font-size: .9rem; margin-left: .5rem; }}
.f {{ font: 500 .7rem/1 var(--f-mono); padding: .3rem .45rem; border-radius: 4px; background: var(--chip); color: var(--muted); white-space: nowrap; }}
.f.alphatex, .f.gp {{ color: var(--accent); }}
.f.chordpro {{ color: var(--chord); }}
</style>
</head><body>
<div class="wrap">
<div class="bar"><h1>Песенник</h1><a href="report.html">отчёт о сборке</a></div>
<details class="wish" id="wish" hidden><summary>Хочу найти <span class="n" id="wishN"></span></summary>
  <ul id="wishList"></ul>
  <form id="wishForm" hidden>
    <input id="wishText" placeholder="Что: песня, игра, мелодия…" aria-label="Что найти" maxlength="300">
    <input id="wishUrl" placeholder="Ссылка, если есть" aria-label="Ссылка" inputmode="url" maxlength="600">
    <button type="submit">добавить</button>
  </form>
</details>
<div class="filters">
  <input type="search" id="q" placeholder="Название или исполнитель" aria-label="Поиск">
  <select id="kindFilter" aria-label="Вид"><option value="">все виды</option><option value="tab">табы</option><option value="chords">аккорды</option></select>
  <select id="artistFilter" aria-label="Исполнитель"><option value="">все исполнители</option></select>
  <select id="famFilter" aria-label="Знакомство"><option value="">знакомство: любое</option></select>
  <div class="tabs" id="diffTabs" role="tablist" aria-label="Сложность"></div>
</div>
<p class="count" id="count"></p>
<ul class="songs" id="list"></ul>
<details class="gone-list" id="goneBox" hidden><summary>Убранные <span class="n" id="goneN"></span></summary><ul id="goneList"></ul></details>
<p class="keyline"><button type="button" class="linkish" id="keyBtn">ключ хозяина</button></p>
</div>
<script>var SONGS = {songs_json};</script>
<script src="assets/owner.js"></script>
<script src="assets/index.js"></script>
</body></html>
"""


REPORT_TEMPLATE = """<!doctype html>
<html lang="ru"><head>
<meta charset="utf-8">
<title>Отчёт сборки песенника</title>
<style>
:root {{ color-scheme: light dark; }}
body {{ font-family: system-ui, sans-serif; max-width: 1000px; margin: 0 auto; padding: 1.5em; }}
table {{ border-collapse: collapse; width: 100%; margin-bottom: 2em; }}
th, td {{ text-align: left; padding: 0.4em 0.6em; border-bottom: 1px solid rgba(128,128,128,0.25); font-size: 0.9em; }}
th {{ position: sticky; top: 0; background: Canvas; }}
.ok {{ color: #2e7d32; }}
.wayback {{ color: #f57f17; }}
.manual {{ color: #1565c0; }}
.gap {{ color: #c62828; }}
h2 {{ margin-top: 2em; }}
.back {{ font-size: 0.9em; }}
.history {{ margin-top: 2em; font-size: 0.9em; }}
.history ul {{ padding-left: 1.2em; }}
</style>
</head><body>
<p class="back"><a href="index.html">&larr; к песеннику</a></p>
<h1>Отчёт сборки песенника</h1>
<p>Собрано: {generated_at}</p>
<p>Всего источников: {total} — ok: {n_ok}, из Wayback: {n_wayback}, вручную: {n_manual}, gap: {n_gap}</p>
{sections}
{history}
</body></html>
"""


def render_report(results, history_html=""):
    from collections import defaultdict
    groups = defaultdict(list)
    for r in results:
        groups[r["result"]].append(r)

    def table(rows, cols):
        out = ["<table><tr>" + "".join(f"<th>{c}</th>" for c in cols) + "</tr>"]
        for row in rows:
            out.append("<tr>" + "".join(f"<td>{cell}</td>" for cell in row) + "</tr>")
        out.append("</table>")
        return "".join(out)

    sections = []
    order = [
        ("ok", "OK — извлечено", "ok"),
        ("wayback", "Из Wayback (Кино)", "wayback"),
        ("manual_added", "Добавлено вручную (контент есть)", "ok"),
        ("manual", "Вручную (не автоматизировано)", "manual"),
        ("gap", "Gap — не удалось", "gap"),
    ]
    for key, label, css in order:
        rows = groups.get(key, [])
        if not rows:
            continue
        sections.append(f'<h2 class="{css}">{label} ({len(rows)})</h2>')
        table_rows = []
        for r in rows:
            src = r["src"]
            title = src["title_raw"]
            domain = src["domain"]
            extra = r.get("reason") or r.get("note") or src.get("note") or ""
            url = src["url_norm"]
            table_rows.append((
                html_mod.escape(title),
                html_mod.escape(domain),
                f'<a href="{html_mod.escape(url)}">ссылка</a>',
                html_mod.escape(extra),
            ))
        sections.append(table(table_rows, ["Название", "Домен", "URL", "Примечание"]))

    return REPORT_TEMPLATE.format(
        generated_at=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        total=len(results),
        n_ok=len(groups.get("ok", [])) + len(groups.get("manual_added", [])),
        n_wayback=len(groups.get("wayback", [])),
        n_manual=len(groups.get("manual", [])),
        n_gap=len(groups.get("gap", [])),
        sections="\n".join(sections),
        history=history_html,
    )


def load_manual_entries():
    """manual_entries.json holds hand-typed/hand-supplied songs the scraper
    can't reach (VK-authenticated topics, Songsterr's JS-rendered tab, a
    google search that isn't a source at all). Rendered the same way as
    scraped songs so they show up in the index/search like everything else."""
    if not MANUAL_FILE.exists():
        return []
    return json.loads(MANUAL_FILE.read_text(encoding="utf-8"))


def process_manual_entry(entry):
    downloads = None
    asset = entry.get("asset")
    if asset:
        src_path = ROOT / asset["src"]
        if not src_path.exists():
            return {"result": "gap", "src": _manual_src(entry), "reason": f"asset not found: {asset['src']}"}
        dest = RAW_DIR / asset["filename"]
        dest.write_bytes(src_path.read_bytes())
        downloads = [(asset.get("label", "Скачать"), f"../raw/{asset['filename']}")]
    return {
        "result": "manual_added",
        "src": _manual_src(entry),
        "slug": entry["slug"],
        "data": {
            "title": entry["title"], "artist": entry["artist"], "kind": entry["kind"],
            "meta": entry.get("meta", {}), "body": entry["body"], "downloads": downloads,
        },
    }


def _manual_src(entry):
    return {
        "title_raw": entry["title"],
        "domain": entry["artist"],
        "url_norm": f"songs/{entry['slug']}.html",
        "note": (entry.get("meta") or {}).get("источник", "добавлено вручную"),
    }


def archive_previous_report():
    """Move the previous report.html into reports/{timestamp}.html before overwriting it."""
    old_path = OUT_DIR / "report.html"
    if not old_path.exists():
        return
    old_text = old_path.read_text(encoding="utf-8")
    m = re.search(r"Собрано: (\d{4}-\d{2}-\d{2} \d{2}:\d{2}) UTC", old_text)
    if m:
        stamp = m.group(1).replace(" ", "_").replace(":", "")
    else:
        stamp = datetime.fromtimestamp(old_path.stat().st_mtime, tz=timezone.utc).strftime("%Y-%m-%d_%H%M")
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    dest = REPORTS_DIR / f"{stamp}.html"
    n = 2
    while dest.exists():
        dest = REPORTS_DIR / f"{stamp}-{n}.html"
        n += 1
    archived_text = old_text.replace('href="index.html"', 'href="../index.html"')
    dest.write_text(archived_text, encoding="utf-8")


def build_history_html():
    if not REPORTS_DIR.exists():
        return ""
    archived = sorted(REPORTS_DIR.glob("*.html"), reverse=True)
    if not archived:
        return ""
    items = "".join(
        f'<li><a href="reports/{f.name}">{html_mod.escape(f.stem.replace("_", " "))}</a></li>'
        for f in archived
    )
    return f'<div class="history"><h2>История сборок</h2><ul>{items}</ul></div>'


def zip_songbook():
    if ZIP_FILE.exists():
        ZIP_FILE.unlink()
    with zipfile.ZipFile(ZIP_FILE, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in OUT_DIR.rglob("*"):
            if f.is_file():
                zf.write(f, arcname=str(Path("songbook") / f.relative_to(OUT_DIR)))


def copy_static():
    """Общий css/js и alphaTab — в собранный сайт."""
    import shutil
    for src_dir, name in ((ASSETS_SRC, "assets"), (VENDOR_SRC, "vendor")):
        dest = OUT_DIR / name
        if dest.exists():
            shutil.rmtree(dest)
        shutil.copytree(src_dir, dest)


def write_song(slug, data, downloads=None):
    song_html = render_song_html(
        slug, data["title"], data["artist"], data["kind"], data["meta"], data["body"], downloads=downloads,
    )
    (SONGS_DIR / f"{slug}.html").write_text(song_html, encoding="utf-8")
    (RAW_DIR / f"{slug}.txt").write_text(data["body"], encoding="utf-8")
    return song_format(slug, downloads)[0]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--refetch", action="store_true", help="force re-download, ignore cache age")
    parser.add_argument("--offline", action="store_true",
                        help="без сети: пересобрать страницы из songbook/raw + songs.json (отчёт не трогается)")
    args = parser.parse_args()

    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    SONGS_DIR.mkdir(parents=True, exist_ok=True)
    RAW_DIR.mkdir(parents=True, exist_ok=True)

    sources = json.loads(SOURCES_FILE.read_text(encoding="utf-8"))
    results = []
    songs_for_index = []
    known = {}
    if args.offline:
        if not SONGS_META.exists():
            sys.exit("Нет songbook/songs.json — сначала нужна обычная сборка с сетью.")
        known = {s["slug"]: s for s in json.loads(SONGS_META.read_text(encoding="utf-8"))}

    for i, src in enumerate(sources, 1):
        if args.offline:
            slug = make_slug(src)
            entry = known.get(slug)
            raw = RAW_DIR / f"{slug}.txt"
            if not entry or not raw.exists():
                continue
            data = {"title": entry["title"], "artist": entry["artist"], "kind": entry["kind"],
                    "meta": entry.get("meta", {}), "body": raw.read_text(encoding="utf-8")}
            r = {"result": "ok", "src": src, "data": data}
        else:
            print(f"[{i}/{len(sources)}] {src['title_raw']} ({src['handler']}, {src['status']})", file=sys.stderr)
            r = process_source(src, refetch=args.refetch)
        results.append(r)
        if r["result"] in ("ok", "wayback"):
            data = r["data"]
            slug = make_slug(src) if not args.offline else slug
            fmt = write_song(slug, data)
            songs_for_index.append({
                "slug": slug, "title": data["title"], "artist": data["artist"], "kind": data["kind"],
                "domain": src["domain"], "meta": data["meta"], "format": fmt,
            })
            r["slug"] = slug

    manual_entries = load_manual_entries()
    for entry in manual_entries:
        print(f"[manual] {entry['title']} ({entry['artist']})", file=sys.stderr)
        _used_slugs.add(entry["slug"])
        r = process_manual_entry(entry)
        results.append(r)
        if r["result"] == "manual_added":
            data = r["data"]
            slug = r["slug"]
            fmt = write_song(slug, data, downloads=data.get("downloads"))
            songs_for_index.append({
                "slug": slug, "title": data["title"], "artist": data["artist"], "kind": data["kind"],
                "domain": r["src"]["domain"], "meta": data["meta"], "format": fmt, "manual": True,
            })

    copy_static()
    index_songs = [{k: s[k] for k in ("slug", "title", "artist", "kind", "domain", "format")} for s in songs_for_index]
    index_html = INDEX_TEMPLATE.format(songs_json=json.dumps(index_songs, ensure_ascii=False))
    (OUT_DIR / "index.html").write_text(index_html, encoding="utf-8")
    SONGS_META.write_text(json.dumps([s for s in songs_for_index if not s.get("manual")], ensure_ascii=False, indent=1),
                          encoding="utf-8")

    if not args.offline:
        archive_previous_report()
        report_html = render_report(results, history_html=build_history_html())
        (OUT_DIR / "report.html").write_text(report_html, encoding="utf-8")

    zip_songbook()

    from collections import Counter
    fmts = Counter(s["format"] for s in songs_for_index)
    print("\nФорматы: " + ", ".join(f"{k} {v}" for k, v in sorted(fmts.items())), file=sys.stderr)
    if args.offline:
        print(f"Офлайн-пересборка: {len(songs_for_index)} песен", file=sys.stderr)
        return
    n_ok = sum(1 for r in results if r["result"] == "ok")
    n_wb = sum(1 for r in results if r["result"] == "wayback")
    n_added = sum(1 for r in results if r["result"] == "manual_added")
    n_manual = sum(1 for r in results if r["result"] == "manual")
    n_gap = sum(1 for r in results if r["result"] == "gap")
    print(f"\nГотово: {n_ok} ok, {n_wb} wayback, {n_added} добавлено вручную, {n_manual} manual, {n_gap} gap", file=sys.stderr)
    print(f"songbook/ -> {OUT_DIR}", file=sys.stderr)
    print(f"zip -> {ZIP_FILE}", file=sys.stderr)
    if n_gap:
        print("Есть gap-и — смотри songbook/report.html", file=sys.stderr)


if __name__ == "__main__":
    main()
