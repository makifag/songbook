"""Перевод всех песен из songbook/raw/*.txt в структурные форматы.

  табы     -> formats/{slug}.atex   (alphaTex: ноты, ритм, строй)
  аккорды  -> formats/{slug}.cho    (ChordPro: аккорды внутри строк)

Каждый результат проверяется, в formats/ попадает только прошедшее:
  - alphaTex разбирается обратно самим alphaTab (node), и каждая нота
    сравнивается с исходным ASCII по такту, позиции, ладу и высоте звука;
  - ChordPro раскладывается обратно в "аккорды над текстом" и сравнивается
    с оригиналом посимвольно.
Что не прошло — остаётся текстом (страница покажет исходник), причина в
formats/status.json.

  python tools/convert_all.py          # нужен node и `npm install` в корне
"""
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

import gpascii  # noqa: E402
import chords2chordpro  # noqa: E402

RAW = ROOT / "songbook" / "raw"
OUT = ROOT / "formats"

# Табы без строки длительностей. Ноты берутся из таба, ритм восстанавливается
# (tools/gridtab.py): по равномерной сетке, по расстояниям или из formats/rhythm/{slug}.txt.
STD = "e4 b3 g3 d3 a2 e2"
GRID_TABS = {
    # ритм читается по сетке: 2 символа = восьмая, размер 12/8 (сверено по всему табу)
    "undertale-home": {"tuning": "d4 a3 g3 d3 a2 d2", "cps": 2, "offset": 1, "ts": (12, 8), "tempo": 120},
    # экспорт Guitar Pro без строки длительностей: 3 символа на долю, доля = восьмая
    # ultimate-guitar (с 2026-10-21): 2 символа = восьмая, такт 8 восьмых; последняя
    # строка набрана шире (3 символа на восьмую) — приводим к общей сетке
    "minecraft-wet-hands": {"tuning": STD, "cps": 2, "offset": 1, "ts": (4, 4), "tempo": 70,
                            "respace": {"from": (3, 2), "to": (2, 1), "width": 17}},
    # небрежный таб без сетки, сдвоенные цифры ("0-23-5") — отдельные ноты
    "lil-gator-game-forest-main": {"tuning": STD, "cps": None, "split_digits": True, "tempo": 100},
    # ритм размечен руками по мелодии (formats/rhythm/), 6/8
    "traditional-greensleeves": {"tuning": STD, "rhythm": True, "tempo": 90, "prefer": (6, 8)},
}
GRID_NOTE = {
    "undertale-home": "ритм по сетке таба",
    "minecraft-wet-hands": "ритм по сетке таба (в исходнике нет длительностей): восьмые, 4/4",
    "lil-gator-game-forest-main": "ритм приблизительный — по расстояниям между нотами",
    "traditional-greensleeves": "ритм размечен вручную по мелодии",
}


def song_list():
    """slug/title/artist/kind: скачанные песни — из songbook/songs.json (пишет build.py),
    добавленные руками — из manual_entries.json."""
    songs = json.loads((ROOT / "songbook" / "songs.json").read_text(encoding="utf-8"))
    for e in json.loads((ROOT / "manual_entries.json").read_text(encoding="utf-8")):
        songs.append({"slug": e["slug"], "title": e["title"], "artist": e["artist"], "kind": e["kind"]})
    return songs


def midi_of(name):
    idx = {"c": 0, "d": 2, "e": 4, "f": 5, "g": 7, "a": 9, "b": 11}
    m = re.fullmatch(r"([a-g])(#|b)?(-?\d)", name.lower())
    return 12 * (int(m.group(3)) + 1) + idx[m.group(1)] + {"#": 1, "b": -1}.get(m.group(2), 0)


def respace(text, rule):
    """Такты, набранные с другим шагом сетки, переложить на общий: каждая цифра
    обязана стоять ровно в узле старой сетки, иначе отказ (ничего не угадываем)."""
    (fc, fo), (tc, to), width = rule["from"], rule["to"], rule["width"]
    out = []
    for line in text.splitlines():
        m = re.match(r"^([eBGDAE]\|)(.*)$", line)
        if not m:
            out.append(line); continue
        cells = m.group(2).rstrip("|").split("|")
        fixed = []
        for cell in cells:
            if len(cell) == width:
                fixed.append(cell); continue
            new = ["-"] * width
            for t in re.finditer(r"\d+", cell):
                slot, rem = divmod(t.start() - fo, fc)
                col = to + slot * tc
                if rem or col + len(t.group()) > width:
                    raise ValueError(f"цифра вне сетки при перекладке: {cell!r}")
                new[col:col + len(t.group())] = t.group()
            fixed.append("".join(new))
        out.append(m.group(1) + "|".join(fixed) + "|")
    return "\n".join(out)


def convert_grid(text, song, cfg, slug):
    import gridtab
    if cfg.get("respace"):
        text = respace(text, cfg["respace"])
    rhythm = None
    if cfg.get("rhythm"):
        rhythm = [l for l in (OUT / "rhythm" / f"{slug}.txt").read_text(encoding="utf-8").splitlines() if l.strip()]
    tuning = cfg["tuning"].split()
    tex, events = gridtab.convert(
        text, esc_tex(song["title"]), esc_tex(song["artist"]), cfg["tempo"], tuning,
        cps=cfg.get("cps", 2), offset=cfg.get("offset", 1), ts=cfg.get("ts"),
        split_digits=cfg.get("split_digits", False), rhythm=rhythm, prefer=cfg.get("prefer"),
    )
    return tex, events, [midi_of(t) for t in tuning]


def esc_tex(s):
    return s.replace("\\", "").replace('"', "'")


def main():
    OUT.mkdir(exist_ok=True)
    songs = song_list()
    status, jobs, pending, repair_notes = {}, [], {}, {}

    for song in songs:
        slug = song["slug"]
        src = RAW / f"{slug}.txt"
        if not src.exists():
            status[slug] = {"format": None, "reason": "нет текста"}
            continue
        text = src.read_text(encoding="utf-8")
        if song["kind"] == "chords":
            res, checks = chords2chordpro.convert(text, song["title"], song["artist"])
            bad = chords2chordpro.verify(checks)
            if bad or not checks:
                status[slug] = {"format": None, "reason": f"ChordPro: не сошлось строк {bad}" if bad else "нет строк с аккордами"}
            else:
                pending[slug] = ("cho", res)
                status[slug] = {"format": "chordpro", "checked_lines": len(checks)}
            continue
        # таб
        if (ROOT / "manual_assets" / f"{slug}.gp5").exists():
            status[slug] = {"format": "gp", "note": "файл Guitar Pro, alphaTab открывает его напрямую"}
            continue
        try:
            notes = []
            if slug in GRID_TABS:
                tex, events, tuning = convert_grid(text, song, GRID_TABS[slug], slug)
                notes.append(GRID_NOTE[slug])
            else:
                parsed = gpascii.parse(text, tolerance=1)
                tempo, ts = gpascii.header_info(text)
                tex, events = gpascii.to_alphatex(parsed, esc_tex(song["title"]), esc_tex(song["artist"]), tempo or 90, ts)
                tuning = parsed["pitches"]
                if parsed["shifted"]:
                    notes.append(f"в исходнике {parsed['shifted']} нот стояли мимо своей доли — привязаны к соседней")
                if parsed.get("repaired_bars"):
                    notes.append("лишняя короткая нота в тактах " + ", ".join(map(str, parsed["repaired_bars"]))
                                 + " сделана форшлагом (в исходнике такт длиннее размера)")
                pre = gpascii.preamble(text)
                if pre:
                    # комментарий автора таба — в начало файла, alphaTex понимает /* */
                    tex = "/*\n" + pre.replace("*/", "* /") + "\n*/\n" + tex
        except (gpascii.NotUnderstood, Exception) as e:
            status[slug] = {"format": None, "reason": f"таб не разобран: {e}"}
            continue
        jobs.append({"id": slug, "tex": tex, "tuning": tuning, "events": events})
        repair_notes[slug] = notes
        pending[slug] = ("atex", tex)

    if jobs:
        job_file = OUT / ".jobs.json"
        job_file.write_text(json.dumps(jobs, ensure_ascii=False), encoding="utf-8")
        out = subprocess.run(["node", str(ROOT / "tools" / "verify_alphatex.mjs"), str(job_file)],
                             cwd=ROOT, capture_output=True, text=True)
        job_file.unlink()
        if out.returncode:
            sys.exit("verify_alphatex.mjs упал:\n" + out.stderr)
        for r in json.loads(out.stdout):
            if r["ok"]:
                status[r["id"]] = {"format": "alphatex", "bars": r["bars"], "checked_notes": r["notes"]}
                if repair_notes.get(r["id"]):
                    status[r["id"]]["notes"] = repair_notes[r["id"]]
            else:
                reason = r.get("error") or f"ноты не сошлись: пропало {r['missing']}, лишние {r['extra']}"
                status[r["id"]] = {"format": None, "reason": "alphaTab: " + reason}
                pending.pop(r["id"], None)

    for old in OUT.glob("*.atex"):
        old.unlink()
    for old in OUT.glob("*.cho"):
        old.unlink()
    for slug, (ext, content) in pending.items():
        (OUT / f"{slug}.{ext}").write_text(content, encoding="utf-8")
    (OUT / "status.json").write_text(json.dumps(status, ensure_ascii=False, indent=1, sort_keys=True), encoding="utf-8")

    ok = [s for s, v in status.items() if v["format"]]
    for s_, v in sorted(status.items()):
        for n in v.get("notes", []):
            print(f"  {s_}: {n}")
    print(f"переведено {len(ok)} из {len(status)}")
    for s, v in sorted(status.items()):
        if not v["format"]:
            print(f"  текстом: {s}: {v['reason']}")


if __name__ == "__main__":
    main()
