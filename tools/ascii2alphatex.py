"""ASCII-таб с равномерной сеткой -> alphaTex.

Пилотный конвертер для табов, где ритм закодирован расстоянием между
символами (как у gametabs-экспортов из Guitar Pro: одна позиция сетки =
фиксированная длительность). Ритм восстанавливается так: каждая доля длится
до следующей атаки в такте; длительность, которую нельзя записать одной
нотой, добивается паузами.

Выход — alphaTex + JSON-список событий (такт, слот, струна, лад) для сверки.
Использование:
    python tools/ascii2alphatex.py SRC.txt --tuning "d4 a3 g3 d3 a2 d2" \
        --chars-per-slot 2 --offset 1 --ts 12/8 --slot 8 --tempo 120 \
        --title Home --artist "Toby Fox" -o out.atex --events out.json
"""
import argparse
import json
import re

STRING_LINE = re.compile(r"^\s*([A-Ga-g][#b]?)\s*\|+(.*)$")

# длительность в слотах -> (значение alphaTex, точка); slot_value — какая
# нота соответствует одному слоту (8 = восьмая)
def dur_table(slot_value):
    table = {}
    for base in (1, 2, 4, 8, 16, 32):
        slots = slot_value / base
        if slots >= 1 and slots == int(slots):
            table[int(slots)] = (base, False)
            dotted = slots * 1.5
            if dotted == int(dotted):
                table.setdefault(int(dotted), (base, True))
    return table


def split_fill(n, table):
    """Разбить n слотов на минимальное число записываемых длительностей."""
    out = []
    while n > 0:
        best = max(k for k in table if k <= n)
        out.append(table[best])
        n -= best
    return out


def parse_systems(text, n_strings):
    lines = text.splitlines()
    systems, i = [], 0
    while i < len(lines):
        block = []
        while i < len(lines) and STRING_LINE.match(lines[i]) and len(block) < n_strings:
            block.append(STRING_LINE.match(lines[i]).group(2))
            i += 1
        if len(block) == n_strings:
            systems.append(block)
        elif not block:
            i += 1
    return systems


def bars_of(system):
    per_string = [s.rstrip().rstrip("|").split("|") for s in system]
    n = len(per_string[0])
    assert all(len(p) == n for p in per_string), "разное число тактов по струнам"
    return [[p[b] for p in per_string] for b in range(n)]


def bar_events(bar, cps, offset):
    """-> {slot: [(string_no, fret)]}, string_no 1 = верхняя строка ASCII."""
    width = len(bar[0])
    events = {}
    for idx, line in enumerate(bar):
        for m in re.finditer(r"\d+", line):
            pos = m.start() - offset
            if pos % cps:
                raise ValueError(f"нота вне сетки: '{line}' pos {m.start()}")
            events.setdefault(pos // cps, []).append((idx + 1, int(m.group())))
    slots = (width - offset + cps - 1) // cps
    return events, slots


def fmt_dur(base, dotted):
    return f"{base}" + ("{d}" if dotted else "")


def convert(args):
    text = open(args.src, encoding="utf-8").read()
    tuning = args.tuning.split()
    systems = parse_systems(text, len(tuning))
    table = dur_table(args.slot)
    ts_num, ts_den = map(int, args.ts.split("/"))
    bar_slots = ts_num * args.slot // ts_den

    out_bars, log = [], []
    bar_no = 0
    for system in systems:
        for bar in bars_of(system):
            events, _ = bar_events(bar, args.chars_per_slot, args.offset)
            onsets = sorted(events)
            if onsets and onsets[-1] >= bar_slots:
                raise ValueError(f"такт {bar_no + 1}: атака за пределами размера")
            tokens = []
            # пауза до первой атаки
            first = onsets[0] if onsets else bar_slots
            for b, d in split_fill(first, table):
                tokens.append(f"r.{fmt_dur(b, d)}")
            for k, slot in enumerate(onsets):
                nxt = onsets[k + 1] if k + 1 < len(onsets) else bar_slots
                parts = split_fill(nxt - slot, table)
                notes = sorted(events[slot], key=lambda n: n[0])
                body = " ".join(f"{f}.{s}" for s, f in notes)
                head = f"({body})" if len(notes) > 1 else body
                b, d = parts[0]
                tokens.append(f"{head}.{fmt_dur(b, d)}")
                for b, d in parts[1:]:
                    tokens.append(f"r.{fmt_dur(b, d)}")
                for s, f in notes:
                    log.append({"bar": bar_no, "slot": slot, "string": s, "fret": f})
            out_bars.append(" ".join(tokens))
            bar_no += 1

    head = [
        f'\\title "{args.title}"',
        f'\\artist "{args.artist}"' if args.artist else None,
        f"\\tempo {args.tempo}",
        ".",
        f'\\track "{args.track}"',
        "\\staff {score tabs}",
        f"\\tuning {' '.join(tuning)}",
        f"\\ts {ts_num} {ts_den}",
    ]
    head = [h for h in head if h]
    body = "\n".join(f"{b} |" for b in out_bars)
    atex = "\n".join(head) + "\n" + body.rstrip(" |") + "\n"
    open(args.out, "w", encoding="utf-8").write(atex)
    meta = {"tuning": tuning, "slot": args.slot, "bar_slots": bar_slots, "events": log}
    open(args.events, "w", encoding="utf-8").write(json.dumps(meta))
    print(f"{bar_no} тактов, {len(log)} нот -> {args.out}")


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("src")
    p.add_argument("--tuning", required=True, help="сверху вниз как в ASCII, напр. 'e4 b3 g3 d3 a2 e2'")
    p.add_argument("--chars-per-slot", type=int, default=2)
    p.add_argument("--offset", type=int, default=1, help="позиция первого слота внутри такта")
    p.add_argument("--ts", default="4/4")
    p.add_argument("--slot", type=int, default=8, help="длительность одного слота (8 = восьмая)")
    p.add_argument("--tempo", type=int, default=100)
    p.add_argument("--title", required=True)
    p.add_argument("--artist", default="")
    p.add_argument("--track", default="Guitar")
    p.add_argument("-o", "--out", required=True)
    p.add_argument("--events", required=True)
    convert(p.parse_args())
