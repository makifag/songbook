"""ASCII-таб без строки длительностей -> alphaTex.

Ноты (лад, струна, порядок) берутся из таба как есть. Длительности:
  - по сетке: позиция в символах / chars_per_slot = номер доли, каждая нота
    звучит до следующей атаки в такте;
  - либо из файла ритма formats/rhythm/{slug}.txt — по строке на такт,
    длительности атак через пробел (4 = четверть, 8. = восьмая с точкой,
    8t = восьмая в триоли, r8 = пауза). Это ручная разметка там, где
    сетка не отражает ритм (Greensleeves).

Сдвоенные цифры в небрежных табах ("0-23-5", "75-3") по умолчанию делятся на
отдельные ноты, кроме 10..15 (split_digits=True).
"""
import re

LABELED = re.compile(r"^\s*([A-Ga-g][#b]?)\s*\|(.*)$")
TICKS = {1: 3840, 2: 1920, 4: 960, 8: 480, 16: 240, 32: 120}


class GridError(Exception):
    pass


def tab_line(line):
    s = line.rstrip()
    if s.count("-") < 3 or "|" not in s or "   " in s.strip():
        return None
    m = LABELED.match(s)
    if m:
        return m.group(1), m.group(2)
    if re.fullmatch(r"\s*\|?[-\d|/\\hpbLx~()*a-z]+\|?", s):
        return None, s.strip()
    return None


def systems_of(text, n=6):
    lines = text.replace("\t", "    ").splitlines()
    out, i = [], 0
    while i < len(lines):
        block = []
        while i < len(lines) and tab_line(lines[i]) and len(block) < n:
            block.append(tab_line(lines[i]))
            i += 1
        if len(block) == n:
            out.append(block)
        elif not block:
            i += 1
    return out


def tokens(line, split_digits):
    """-> [(col, fret)] атаки на струне."""
    res = []
    for m in re.finditer(r"\d+", line):
        txt, c = m.group(), m.start()
        if not split_digits or len(txt) == 1:
            res.append((c, int(txt)))
            continue
        k = 0
        while k < len(txt):
            if txt[k] == "1" and k + 1 < len(txt) and txt[k + 1] in "012345" and \
                    not (k + 2 < len(txt) and txt[k + 2] in "0123456789" and txt[k + 1:k + 3] in ("10", "11", "12", "13", "14", "15")):
                res.append((c + k, int(txt[k:k + 2])))
                k += 2
            else:
                res.append((c + k, int(txt[k])))
                k += 1
    return res


def parse_dur(tok):
    m = re.fullmatch(r"(r)?(\d+)(\.?)(t?)", tok)
    if not m:
        raise GridError(f"непонятная длительность '{tok}'")
    rest, base, dot, tri = m.groups()
    base = int(base)
    t = TICKS[base] * (1.5 if dot else 1) * (2 / 3 if tri else 1)
    return {"rest": bool(rest), "dur": base, "dot": bool(dot), "tu": 3 if tri else None, "ticks": round(t)}


def convert(text, title, artist, tempo, tuning, cps=2, offset=1, slot=8, ts=None,
            split_digits=False, rhythm=None, pad_end=None, prefer=None):
    """tuning: alphaTex-имена сверху вниз. ts: фиксированный размер (n, d) или None —
    тогда размер такта = его ширина в долях. rhythm: список строк длительностей."""
    pad_end = offset if pad_end is None else pad_end
    systems = systems_of(text, len(tuning))
    if not systems:
        raise GridError("таб не найден")
    slot_ticks = 3840 // slot
    bars_tex, events = [], []
    bar_no = 0
    cur_ts = None
    for system in systems:
        bodies = [body.rstrip() for _, body in system]
        per_string = [b.rstrip("|").lstrip("|").split("|") for b in bodies]
        nb = len(per_string[0])
        if any(len(p) != nb for p in per_string):
            # на какой-то струне пропущена тактовая черта: режем все струны по чертам
            # той струны, где их больше всего (колонки у ASCII-таба общие)
            ref = max(bodies, key=lambda b: b.count("|"))
            cuts = [i for i, ch in enumerate(ref) if ch == "|"]
            width = max(len(b) for b in bodies)
            per_string = []
            for b in bodies:
                b = b.ljust(width, "-")
                cells = [b[x + 1:y] for x, y in zip(cuts, cuts[1:] + [width])]
                per_string.append([c for c in cells])
            per_string = [[c for c, r in zip(p, per_string[0])] for p in per_string]
            # пустые хвосты после последней черты убираем
            while per_string[0] and all(not p[-1].strip("-") for p in per_string) and len(per_string[0][-1]) <= 1:
                for p in per_string:
                    p.pop()
            nb = len(per_string[0])
        for b in range(nb):
            cells = [p[b] for p in per_string]
            width = max(len(c) for c in cells)
            onsets = {}
            for si, cell in enumerate(cells):
                for col, fret in tokens(cell, split_digits):
                    onsets.setdefault(col, []).append((si + 1, fret))
            cols = sorted(onsets)
            toks = []
            if rhythm is None and cps is None and not cols:
                # пустой такт (в небрежных табах — с подписью "rest"): целая пауза
                toks.append("r.1")
                ticks = 3840
                bar_ts = ts or (4, 4)
                if bar_ts != cur_ts:
                    toks.insert(0, f"\\ts {bar_ts[0]} {bar_ts[1]}")
                    cur_ts = bar_ts
                bars_tex.append(" ".join(toks))
                bar_no += 1
                continue
            if rhythm is not None:
                if bar_no >= len(rhythm):
                    raise GridError(f"в файле ритма нет строки для такта {bar_no + 1}")
                durs = [parse_dur(t) for t in rhythm[bar_no].split()]
                sounding = [d for d in durs if not d["rest"]]
                if len(sounding) != len(cols):
                    raise GridError(f"такт {bar_no + 1}: атак в табе {len(cols)}, в ритме {len(sounding)}")
                ticks = sum(d["ticks"] for d in durs)
                pos, k = 0, 0
                for d in durs:
                    fx = []
                    if d["dot"]:
                        fx.append("d")
                    if d["tu"]:
                        fx.append("tu 3")
                    suffix = f".{d['dur']}" + ("{" + " ".join(fx) + "}" if fx else "")
                    if d["rest"]:
                        toks.append("r" + suffix)
                    else:
                        notes = sorted(onsets[cols[k]])
                        body = " ".join(f"{f}.{s}" for s, f in notes)
                        toks.append((f"({body})" if len(notes) > 1 else body) + suffix)
                        for s, f in notes:
                            events.append({"bar": bar_no, "tick": pos, "string": s, "fret": f})
                        k += 1
                    pos += d["ticks"]
            elif cps is None:
                # "по расстояниям": небрежный таб без сетки; промежуток до 2 символов — восьмая,
                # длиннее — пропорционально (round(gap/2) восьмых)
                slot_of, acc = [], 0
                for k, c in enumerate(cols):
                    slot_of.append(acc)
                    gap = (cols[k + 1] if k + 1 < len(cols) else width) - c
                    acc += max(1, round(gap / 2))
                slots_in_bar = max(acc, 1)
                ticks = slots_in_bar * slot_ticks
            else:
                slots_in_bar = ts[0] * slot // ts[1] if ts else max(1, round((width - offset - pad_end) / cps))
                ticks = slots_in_bar * slot_ticks
                slot_of = [round((c - offset) / cps) for c in cols]
            if rhythm is None:
                first = slot_of[0] if cols else slots_in_bar
                toks += fill(first, slot, rest=True)
                for k, c in enumerate(cols):
                    s0 = slot_of[k]
                    s1 = slot_of[k + 1] if k + 1 < len(cols) else slots_in_bar
                    if s1 <= s0:
                        raise GridError(f"такт {bar_no + 1}: две атаки в одной доле")
                    parts = fill(s1 - s0, slot)
                    notes = sorted(onsets[c])
                    body = " ".join(f"{f}.{s}" for s, f in notes)
                    toks.append((f"({body})" if len(notes) > 1 else body) + parts[0])
                    toks += ["r" + p for p in parts[1:]]
                    for s, f in notes:
                        events.append({"bar": bar_no, "tick": s0 * slot_ticks, "string": s, "fret": f})
            bar_ts = ts or (prefer if prefer and ticks == prefer[0] * 3840 // prefer[1] else meter_of(ticks))
            if bar_ts is None:
                raise GridError(f"такт {bar_no + 1}: длина {ticks} не ложится в размер")
            if ts and ticks != ts[0] * 3840 // ts[1]:
                raise GridError(f"такт {bar_no + 1}: длина не равна размеру {ts[0]}/{ts[1]}")
            if bar_ts != cur_ts:
                toks.insert(0, f"\\ts {bar_ts[0]} {bar_ts[1]}")
                cur_ts = bar_ts
            bars_tex.append(" ".join(toks))
            bar_no += 1
    head = [f'\\title "{title}"', f'\\artist "{artist}"' if artist else None, f"\\tempo {tempo}", ".",
            '\\track "Guitar"', "\\staff {tabs}", f"\\tuning {' '.join(tuning)}"]
    tex = "\n".join(h for h in head if h) + "\n" + " |\n".join(bars_tex) + "\n"
    return tex, events


def meter_of(ticks):
    for den in (4, 8, 16):
        unit = 3840 // den
        if ticks % unit == 0 and 1 <= ticks // unit <= 32:
            return (ticks // unit, den)
    return None


def fill(n, slot, rest=False):
    """n долей по 1/slot -> суффиксы длительностей (.4, .8{d} ...), минимальным числом нот."""
    table = {}
    for base in (1, 2, 4, 8, 16, 32):
        k = slot / base
        if k >= 1 and k == int(k):
            table[int(k)] = f".{base}"
            if k * 1.5 == int(k * 1.5):
                table.setdefault(int(k * 1.5), f".{base}{{d}}")
    out = []
    while n > 0:
        best = max(k for k in table if k <= n)
        out.append(table[best])
        n -= best
    return ["r" + p for p in out] if rest else out
