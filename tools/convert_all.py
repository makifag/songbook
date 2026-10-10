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

# Табы без строки длительностей, у которых ритм однозначно читается по сетке
# (одна позиция = фиксированная длительность). Параметры подобраны руками.
GRID_TABS = {
    "undertale-home": {"tuning": "d4 a3 g3 d3 a2 d2", "chars_per_slot": 2, "offset": 1,
                       "ts": (12, 8), "slot": 8, "tempo": 120},
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


def convert_grid(text, song, cfg):
    """Сеточный таб (как Home) — тот же алгоритм, что в ascii2alphatex.py."""
    import ascii2alphatex as a2a
    tuning = cfg["tuning"].split()
    systems = a2a.parse_systems(text, len(tuning))
    table = a2a.dur_table(cfg["slot"])
    bar_slots = cfg["ts"][0] * cfg["slot"] // cfg["ts"][1]
    slot_ticks = 3840 // cfg["slot"]
    bars, events = [], []
    for system in systems:
        for bar in a2a.bars_of(system):
            ev, _ = a2a.bar_events(bar, cfg["chars_per_slot"], cfg["offset"])
            onsets = sorted(ev)
            toks = [f"r.{a2a.fmt_dur(b, d)}" for b, d in a2a.split_fill(onsets[0] if onsets else bar_slots, table)]
            for k, slot in enumerate(onsets):
                nxt = onsets[k + 1] if k + 1 < len(onsets) else bar_slots
                parts = a2a.split_fill(nxt - slot, table)
                notes = sorted(ev[slot])
                body = " ".join(f"{f}.{s}" for s, f in notes)
                head = f"({body})" if len(notes) > 1 else body
                toks.append(f"{head}.{a2a.fmt_dur(*parts[0])}")
                toks += [f"r.{a2a.fmt_dur(b, d)}" for b, d in parts[1:]]
                for s, f in notes:
                    events.append({"bar": len(bars), "tick": slot * slot_ticks, "string": s, "fret": f})
            bars.append(" ".join(toks))
    head = [f'\\title "{song["title"]}"', f'\\artist "{song["artist"]}"', f"\\tempo {cfg['tempo']}", ".",
            '\\track "Guitar"', "\\staff {score tabs}", f"\\tuning {' '.join(tuning)}",
            f"\\ts {cfg['ts'][0]} {cfg['ts'][1]}"]
    tex = "\n".join(head) + "\n" + " |\n".join(bars) + "\n"
    return tex, events, [midi_of(t) for t in tuning]


def esc_tex(s):
    return s.replace("\\", "").replace('"', "'")


def main():
    OUT.mkdir(exist_ok=True)
    songs = song_list()
    status, jobs, pending = {}, [], {}

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
        try:
            if slug in GRID_TABS:
                tex, events, tuning = convert_grid(text, song, GRID_TABS[slug])
            else:
                parsed = gpascii.parse(text)
                tempo, ts = gpascii.header_info(text)
                tex, events = gpascii.to_alphatex(parsed, esc_tex(song["title"]), esc_tex(song["artist"]), tempo or 90, ts)
                tuning = parsed["pitches"]
                pre = gpascii.preamble(text)
                if pre:
                    # комментарий автора таба — в начало файла, alphaTex понимает /* */
                    tex = "/*\n" + pre.replace("*/", "* /") + "\n*/\n" + tex
        except gpascii.NotUnderstood as e:
            status[slug] = {"format": None, "reason": f"таб не разобран: {e}"}
            continue
        jobs.append({"id": slug, "tex": tex, "tuning": tuning, "events": events})
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
    print(f"переведено {len(ok)} из {len(status)}")
    for s, v in sorted(status.items()):
        if not v["format"]:
            print(f"  текстом: {s}: {v['reason']}")


if __name__ == "__main__":
    main()
