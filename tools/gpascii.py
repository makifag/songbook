"""Разбор ASCII-табов в стиле экспорта Guitar Pro (gametabs.net) -> alphaTex.

Формат: над каждой системой из N струн идёт строка длительностей
(W H Q E S T, точка = с точкой), буква стоит в той же колонке, что и нота.
Над ней может быть строка триолей `|-3-|`. Внутри строк струн:
цифры — лад (двузначный лад может заканчиваться на колонке буквы),
L — лига с предыдущей нотой, x — глушёная, (5) — призрачная,
h/p — легато, S или / \\ — слайд, ~ — вибрато, * и o — знаки повтора.

Ничего не угадывается: каждая цифра в строках струн должна попасть в
какую-то долю, иначе файл считается непонятым и конвертация отклоняется.
"""
import json
import re
import sys

DUR = {"W": 1, "H": 2, "Q": 4, "E": 8, "S": 16, "T": 32}
TICKS = {1: 3840, 2: 1920, 4: 960, 8: 480, 16: 240, 32: 120, 64: 60}
NOTE_IDX = {"c": 0, "d": 2, "e": 4, "f": 5, "g": 7, "a": 9, "b": 11}

RHYTHM_LINE = re.compile(r"^\s*(?:(?:[WHQEST]\.{0,2}|\d+x)\s+)*[WHQEST]\.{0,2}\s*$")
TUPLET_MARK = re.compile(r"\|-+(\d)-+\|")
STRING_LINE = re.compile(r"^(\s*)([A-Ga-g][#b]?)?(\s*\|*[-\d|LxhpbsSrPo*()~<>/\\gt. ]*)$")


class NotUnderstood(Exception):
    pass


def is_string_line(line):
    m = STRING_LINE.match(line)
    if not m:
        return False
    body = m.group(3)
    inner = line.strip()
    if re.fullmatch(r"(?:\|-+\d-+\|\s*)+", inner):
        return False  # строка триолей
    # строка струны — сплошная: без длинных пробелов внутри (иначе это строка триолей/пометок)
    return body.count("-") >= 6 and "|" in line and "   " not in inner


def tuning_from_labels(labels):
    """['E','B','G','D','A','E'] сверху вниз -> ['e4','b3',...]; строится снизу:
    нижняя струна во 2-й октаве, каждая следующая — ближайшая такая нота выше."""
    pitches = []
    prev = None
    for lab in reversed(labels):
        name = lab[0].lower()
        acc = 1 if lab[1:] == "#" else -1 if lab[1:] == "b" else 0
        base = NOTE_IDX[name] + acc
        if prev is None:
            p = 12 * 3 + base  # октава 2 (C2 = 36)
        else:
            p = 12 * 3 + base
            while p <= prev:
                p += 12
        pitches.append(p)
        prev = p
    names = ["c", "c#", "d", "d#", "e", "f", "f#", "g", "g#", "a", "a#", "b"]
    out = [f"{names[p % 12]}{p // 12 - 1}" for p in reversed(pitches)]
    return out, list(reversed(pitches))


def find_systems(lines, n_strings=6):
    """-> список (rhythm_idx, tuplet_idx|None, [idx строк струн])."""
    systems = []
    i = 0
    while i < len(lines):
        if is_string_line(lines[i]):
            j = i
            block = []
            while j < len(lines):
                if is_string_line(lines[j]):
                    block.append(j)
                    j += 1
                elif not lines[j].strip() and j + 1 < len(lines) and is_string_line(lines[j + 1]) and block:
                    j += 1  # некоторые табы разрежены пустыми строками между струнами
                else:
                    break
            if len(block) != n_strings:
                raise NotUnderstood(f"строка {i + 1}: система из {len(block)} струн")
            k = i - 1
            while k >= 0 and not lines[k].strip():
                k -= 1
            # между ритмом и струнами иногда стоит строка с пометками (^, mf)
            r = k
            if r >= 0 and not RHYTHM_LINE.match(lines[r]) and r - 1 >= 0 and RHYTHM_LINE.match(lines[r - 1]):
                r -= 1
            if r < 0 or not RHYTHM_LINE.match(lines[r]):
                raise NotUnderstood(f"строка {i + 1}: нет строки длительностей над системой")
            t = r - 1
            while t >= 0 and not lines[t].strip():
                t -= 1
            tup = t if t >= 0 and TUPLET_MARK.search(lines[t]) and not is_string_line(lines[t]) and not RHYTHM_LINE.match(lines[t]) else None
            systems.append((r, tup, block))
            i = j
        else:
            i += 1
    return systems


def number_at(line, col):
    """Лад, накрывающий колонку col: '12' может стоять на col-1..col."""
    if col >= len(line) or not line[col].isdigit():
        return None
    a = col
    while a > 0 and line[a - 1].isdigit():
        a -= 1
    b = col
    while b + 1 < len(line) and line[b + 1].isdigit():
        b += 1
    return a, b, int(line[a:b + 1])


def parse(text, n_strings=6, tolerance=0):
    """tolerance=1: нота, съехавшая на колонку от буквы длительности (частая
    ошибка ручной правки таба), привязывается к соседней доле; счётчик в result["shifted"]."""
    lines = text.replace("\t", "    ").splitlines()
    # приписки после последней черты ("|  Repeat ad infinitum") — не часть таба
    lines = [re.sub(r"(-\|)\s+[A-Za-zА-Яа-яЁё(].*$", r"\1", l) for l in lines]
    systems = find_systems(lines, n_strings)
    if not systems:
        raise NotUnderstood("не найдено ни одной системы")
    labels = None
    for _, _, block in systems:
        labs = [STRING_LINE.match(lines[k]).group(2) for k in block]
        if all(labs):
            labels = labs
            break
    if not labels:
        labels = ["E", "B", "G", "D", "A", "E"]
    tuning, pitches = tuning_from_labels(labels)

    bars = []  # каждый такт: список долей
    shifted = [0]
    consumed_total = 0
    digits_total = 0
    for r, tup, block in systems:
        rline = lines[r]
        slines = [lines[k] for k in block]
        width = max(len(s) for s in slines)
        slines = [s.ljust(width) for s in slines]
        # колонки тактовых черт: '|' на всех струнах
        bar_cols = [c for c in range(width) if all(s[c] == "|" for s in slines)]
        digits_here = {(si, c) for si, s in enumerate(slines) for c, ch in enumerate(s) if ch.isdigit()}
        digits_total += len(digits_here)
        tuplet_spans = []
        if tup is not None:
            for m in TUPLET_MARK.finditer(lines[tup]):
                tuplet_spans.append((m.start(), m.end() - 1, int(m.group(1))))
        letters = [(m.start(), m.group(1), len(m.group(2))) for m in re.finditer(r"([WHQEST])(\.{0,2})", rline)]
        letter_cols = {c for c, _, _ in letters}
        # разбить на такты по колонкам черт
        edges = sorted(set(bar_cols) | {-1, width})
        segments = []
        for a, b in zip(edges, edges[1:]):
            if b - a > 1:
                segments.append((a, b))
        consumed = set()

        def read_bar(a, b, shift):
            """Прочитать такт; shift — сдвиг строки длительностей относительно струн."""
            used = set()
            beats = []
            n_shift = 0
            for col0, letter, dots in letters:
                col = col0 + shift
                if not (a < col < b):
                    continue
                notes, grace, chains = [], [], []
                for si, s in enumerate(slines):
                    num = number_at(s, col)
                    if not num and tolerance and not (col < len(s) and s[col] in "Lx("):
                        for dc in (1, -1):
                            c2 = col + dc
                            if c2 - shift in letter_cols or c2 < 0:
                                continue
                            cand = number_at(s, c2)
                            if cand and not any((si, x) in used for x in range(cand[0], cand[1] + 1)):
                                num = cand
                                n_shift += 1
                                break
                    ch = s[col] if col < len(s) else "-"
                    if num:
                        x0, x1, fret = num
                        used.update((si, x) for x in range(x0, x1 + 1))
                        after = s[x1 + 1] if x1 + 1 < len(s) else ""
                        before = s[x0 - 1] if x0 > 0 else ""
                        eff = []
                        if before == "g" and x0 >= 2 and s[x0 - 2].isdigit():
                            g0, g1, gfret = number_at(s, x0 - 2)
                            used.update((si, x) for x in range(g0, g1 + 1))
                            grace.append({"string": si + 1, "fret": gfret, "eff": []})
                        if before == "(" and after == ")":
                            eff.append("g")
                        # легато-цепочка внутри одной доли: 1h3p1
                        chain = []
                        x = x1
                        while x + 2 < len(s) and s[x + 1] in "hpP" and s[x + 2].isdigit():
                            c0, c1, cf = number_at(s, x + 2)
                            used.update((si, y) for y in range(c0, c1 + 1))
                            chain.append(cf)
                            x = c1
                        # трель: 1(3) вплотную после ноты (над ней "tr") — 1 с трелью до 3-го лада
                        if after == "(" and x1 + 2 < len(s) and s[x1 + 2].isdigit():
                            t0, t1, tfret = number_at(s, x1 + 2)
                            if t1 + 1 < len(s) and s[t1 + 1] == ")":
                                used.update((si, y) for y in range(t0, t1 + 1))
                                eff.append(f"tr {tfret} 16")
                        if chain:
                            eff.append("h")
                            chains.append((si + 1, chain))
                        elif after in "hpP":
                            eff.append("h")
                        elif after in "S/\\":
                            eff.append("sl")
                        elif after == "~":
                            eff.append("v")
                        notes.append({"string": si + 1, "fret": fret, "eff": eff})
                    elif ch == "(" and col + 1 < len(s) and s[col + 1].isdigit():
                        x0, x1, fret = number_at(s, col + 1)
                        used.update((si, x) for x in range(x0, x1 + 1))
                        notes.append({"string": si + 1, "fret": fret, "eff": ["g"]})
                    elif ch == "(" and s[col + 1:col + 3] == "x)":
                        notes.append({"string": si + 1, "fret": None, "dead": True, "eff": []})
                    elif ch == "x" and s[col - 1:col] == "(":
                        notes.append({"string": si + 1, "fret": None, "dead": True, "eff": []})
                    elif ch == "L":
                        notes.append({"string": si + 1, "fret": None, "tie": True, "eff": []})
                    elif ch == "x":
                        notes.append({"string": si + 1, "fret": None, "dead": True, "eff": []})
                tu = None
                for t0, t1, n in tuplet_spans:
                    if t0 <= col0 <= t1:
                        tu = n
                if grace:
                    beats.append({"dur": 16, "dots": 0, "tu": None, "notes": grace, "grace": True})
                if chains and not tu and not dots:
                    # доля делится между нотами цепочки: 2 ноты — пополам, 3 — триолью
                    k = 1 + max(len(c) for _, c in chains)
                    if k in (2, 3):
                        sub = DUR[letter] * 2
                        beats.append({"dur": sub, "dots": 0, "tu": 3 if k == 3 else None, "notes": notes})
                        for i in range(1, k):
                            nts = [{"string": st, "fret": c[i - 1], "eff": ["h"] if i < len(c) else []}
                                   for st, c in chains if len(c) >= i]
                            beats.append({"dur": sub, "dots": 0, "tu": 3 if k == 3 else None, "notes": nts})
                        continue
                beats.append({"dur": DUR[letter], "dots": dots, "tu": tu, "notes": notes})
            return beats, used, n_shift

        for a, b in segments:
            bar_digits = {(si, c) for si, c in digits_here if a < c < b}
            best = None
            # сначала как есть; если в такте осталась ничейная цифра — строка длительностей
            # могла съехать целиком (бывает у ручных правок): ищем сдвиг, при котором сходится всё
            for shift in ([0] + ([1, -1, 2, -2, 3, -3, 4, -4] if tolerance else [])):
                beats, used, n_shift = read_bar(a, b, shift)
                if bar_digits <= used:
                    best = (beats, used, n_shift + (1 if shift else 0))
                    break
                if best is None:
                    best = (beats, used, n_shift)
            beats, used, n_shift = best
            consumed |= used
            shifted[0] += n_shift
            if beats:
                bars.append(beats)
        lost = digits_here - consumed
        if lost:
            si, c = sorted(lost)[0]
            raise NotUnderstood(
                f"строка {block[si] + 1}, колонка {c + 1}: цифра без доли "
                f"({len(lost)} шт. в системе)"
            )
        consumed_total += len(consumed)
    return {"tuning": tuning, "pitches": pitches, "bars": bars, "digits": digits_total, "shifted": shifted[0]}


def beat_ticks(b):
    if b.get("grace"):
        return 0
    t = TICKS[b["dur"]]
    t = t * (2 - 0.5 ** b["dots"])
    if b["tu"]:
        t = t * 2 / b["tu"] if b["tu"] == 3 else t * (4 if b["tu"] in (5, 6, 7) else 8) / b["tu"]
    return round(t)


def pick_ts(ticks, preferred):
    if preferred and preferred[0] * 3840 // preferred[1] == ticks:
        return preferred
    # такт странной длины (33/32 и т.п.) — почти всегда ошибка в самом табе
    # или в нашем чтении; честнее отказаться, чем нарисовать неверный ритм
    for den in (4, 8, 16, 32):
        unit = 3840 // den
        if ticks % unit == 0 and 1 <= ticks // unit <= 32:
            return (ticks // unit, den)
    return None


def to_alphatex(parsed, title, artist, tempo, preferred_ts=None, track="Guitar"):
    out = [f'\\title "{title}"']
    if artist:
        out.append(f'\\artist "{artist}"')
    out.append(f"\\tempo {tempo}")
    out += [".", f'\\track "{track}"', "\\staff {tabs}", f"\\tuning {' '.join(parsed['tuning'])}"]
    events = []
    repaired = parsed.setdefault("repaired_bars", [])
    cur_ts = None
    bar_lines = []
    for bi, beats in enumerate(parsed["bars"]):
        ticks = sum(beat_ticks(b) for b in beats)
        ts = pick_ts(ticks, preferred_ts)
        if ts is None and preferred_ts:
            # лишняя мелкая нота в такте (ошибка в самом табе): превращаем её в форшлаг
            excess = ticks - preferred_ts[0] * 3840 // preferred_ts[1]
            for b in beats:
                if beat_ticks(b) == excess and b["notes"] and not b.get("grace"):
                    b["grace"] = True
                    repaired.append(bi + 1)
                    ticks -= excess
                    ts = pick_ts(ticks, preferred_ts)
                    break
        if ts is None:
            raise NotUnderstood(f"такт {bi + 1}: длительность {ticks} тиков не ложится в размер")
        toks = []
        if ts != cur_ts:
            toks.append(f"\\ts {ts[0]} {ts[1]}")
            cur_ts = ts
        pos = 0
        for b in beats:
            beat_fx = []
            if b["dots"] == 1:
                beat_fx.append("d")
            elif b["dots"] == 2:
                beat_fx.append("dd")
            if b["tu"]:
                beat_fx.append(f"tu {b['tu']}")
            if b.get("grace"):
                beat_fx.append("gr")
            nts = []
            for n in b["notes"]:
                if n.get("tie"):
                    nt = f"-.{n['string']}"
                elif n.get("dead"):
                    nt = f"x.{n['string']}"
                else:
                    nt = f"{n['fret']}.{n['string']}"
                    events.append({"bar": bi, "tick": pos, "string": n["string"], "fret": n["fret"], "grace": bool(b.get("grace"))})
                fx = [e for e in n["eff"]]
                if fx:
                    nt += "{" + " ".join(fx) + "}"
                nts.append(nt)
            if not nts:
                head = "r"
            elif len(nts) == 1:
                head = nts[0]
            else:
                head = "(" + " ".join(nts) + ")"
            tok = f"{head}.{b['dur']}"
            if beat_fx:
                tok += "{" + " ".join(beat_fx) + "}"
            toks.append(tok)
            pos += beat_ticks(b)
        bar_lines.append(" ".join(toks))
    tex = "\n".join(out) + "\n" + " |\n".join(bar_lines) + "\n"
    return tex, events


def header_info(text):
    tempo = None
    m = re.search(r"(?:(\d{2,3})\s*bpm|(?:tempo|bpm|T)\s*[=:]\s*(\d{2,3}))", text, re.I)
    if m:
        tempo = int(m.group(1) or m.group(2))
    ts = None
    m = re.search(r"\b(\d{1,2})/(\d{1,2})\b(?:\s*(?:time|metrum|размер))?", text[:600], re.I)
    if m and int(m.group(2)) in (2, 4, 8, 16):
        ts = (int(m.group(1)), int(m.group(2)))
    return tempo, ts


def preamble(text):
    """Текст до первой системы (шапка с комментариями автора)."""
    lines = text.replace("\t", "    ").splitlines()
    out = []
    for line in lines:
        if is_string_line(line) or RHYTHM_LINE.match(line) and line.strip():
            break
        out.append(line.rstrip())
    return "\n".join(out).strip("\n")


if __name__ == "__main__":
    src = sys.argv[1]
    text = open(src, encoding="utf-8").read()
    p = parse(text)
    tempo, ts = header_info(text)
    tex, ev = to_alphatex(p, "T", "", tempo or 90, ts)
    print(tex[:800])
    print(len(p["bars"]), "тактов", len(ev), "нот")
