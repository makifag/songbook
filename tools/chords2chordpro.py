"""Аккорды-над-текстом -> ChordPro, со сверкой позиций.

Строка из одних аккордов, за которой идёт строка текста, сливается в одну:
каждый аккорд вставляется в текст перед буквой, над которой он стоял.
Сверка: из полученного ChordPro заново восстанавливается пара
"строка аккордов / строка текста" и сравнивается с оригиналом посимвольно
(с точностью до хвостовых пробелов).

Блоки ASCII-таба (строки вида `e---0---|`) уходят в {start_of_tab}.
Подписи секций (`Припев:`, `Соло:` ...) превращаются в директивы.
"""
import argparse
import re
import sys

CHORD = r"[A-H](?:#|b)?(?:m|maj|min|dim|aug|sus)?\d*(?:sus\d|add\d|maj\d)?(?:/[A-H](?:#|b)?)?(?:\([IVX]+\))?"
# строка аккордов: аккорды плюс служебные значки ("|", "*", "x2", "}x2")
_TOK = rf"(?:{CHORD}|\||\*|\}}?x\d|\(x\d\))"
CHORD_LINE = re.compile(rf"^\s*(?:{CHORD})(?:\s+{_TOK})*\s*$|^\s*(?:{_TOK}\s+)+(?:{CHORD})(?:\s+{_TOK})*\s*$")
TAB_LINE = re.compile(r"^\s*[A-Ga-g][#b]?\s*\|?-[-\d|hpbrsx/\\~()]*\|?\s*$")
# подпись секции: с начала строки, короткая, без запятых ("Припев:", "Вступление: Am | C")
LABEL = re.compile(r"^([А-ЯЁA-Z][^:,.!?]{1,20}):\s*(.*)$")

SECTIONS = {
    "припев": ("start_of_chorus", "end_of_chorus"),
    "соло": ("start_of_tab", "end_of_tab"),
    "под припев": ("start_of_tab", "end_of_tab"),
}


def merge(chords, lyric):
    """Вставить аккорды из chords в lyric по позициям."""
    width = max(len(chords), len(lyric))
    lyric = lyric.ljust(width)
    out, last = [], 0
    for m in re.finditer(r"\S+", chords):
        out.append(lyric[last:m.start()])
        out.append(f"[{m.group()}]")
        last = m.start()
    out.append(lyric[last:])
    return "".join(out).rstrip()


def split_back(line):
    """Обратная операция: ChordPro-строка -> (аккорды, текст)."""
    chords, lyric = [], []
    col = 0
    for part in re.split(r"(\[[^\]]+\])", line):
        if part.startswith("["):
            name = part[1:-1]
            # если предыдущий аккорд налезает — оригинал так быть не мог
            pad = col - len("".join(chords))
            if pad < 0:
                raise ValueError(f"аккорды налезают: {line}")
            chords.append(" " * pad + name)
        else:
            lyric.append(part)
            col += len(part)
    return "".join(chords).rstrip(), "".join(lyric).rstrip()


DASH_CHORDS = re.compile(rf"^[-\s]*(?:{CHORD}[-\s]*)+$")


def normalize(lines):
    """Свести местные варианты к "строка аккордов над строкой текста",
    не сдвигая колонки:
      "[Куплет]:G(III)    Em"  -> "Куплет:" + строка аккордов с отступом
      "-------D--------G"      -> дефисы-заполнители превращаются в пробелы
    """
    out = []
    for line in lines:
        m = re.match(r"^\[([^\]]{1,30})\]:?", line)
        if m:
            out.append(f"{m.group(1)}:")
            rest = line[m.end():]
            if rest.strip():
                # аккорды, прилепленные к метке, на деле относятся к началу строки
                out.append(rest)
            continue
        if "-" in line and DASH_CHORDS.match(line) and re.search(CHORD, line):
            line = line.replace("-", " ")
        out.append(line)
    return out


def convert(text, title, artist):
    lines = normalize(text.replace("\r", "").expandtabs(8).splitlines())
    out = [f"{{title: {title}}}", f"{{artist: {artist}}}", ""]
    checks = []
    open_env = None
    i = 0

    def close():
        nonlocal open_env
        if open_env:
            out.append(f"{{{open_env}}}")
            open_env = None

    while i < len(lines):
        line = lines[i]
        stripped = line.strip()
        lab = LABEL.match(line)
        if lab and not CHORD_LINE.match(line):
            name, rest = lab.group(1).strip(), lab.group(2).strip()
            close()
            env = SECTIONS.get(name.lower())
            if rest:  # "Вступление: Am | C | G | F" — инструментальная строка
                out.append(f"{{comment: {name}}}")
                out.append(" ".join(f"[{t}]" if re.fullmatch(CHORD, t) else t for t in rest.split()))
            elif env:
                out.append(f"{{{env[0]}: {name}}}")
                open_env = env[1]
            else:
                out.append(f"{{comment: {name}}}")
            i += 1
            continue
        if TAB_LINE.match(line):
            if open_env != "end_of_tab":
                close()
                out.append("{start_of_tab}")
                open_env = "end_of_tab"
            out.append(line.rstrip())
            i += 1
            continue
        if open_env == "end_of_tab" and stripped:
            close()
        if not stripped:
            if open_env == "end_of_chorus":
                close()
            elif open_env == "end_of_tab":
                out.append("")
                i += 1
                continue
            out.append("")
            i += 1
            continue
        if CHORD_LINE.match(line):
            nxt = lines[i + 1] if i + 1 < len(lines) else ""
            if nxt.strip() and not CHORD_LINE.match(nxt) and not LABEL.match(nxt):
                merged = merge(line.rstrip(), nxt.rstrip())
                checks.append((line.rstrip(), nxt.rstrip(), merged))
                out.append(merged)
                i += 2
                continue
            out.append(" ".join(f"[{c}]" for c in line.split()))
            i += 1
            continue
        out.append(line.rstrip())
        i += 1
    close()
    # схлопнуть повторные пустые строки
    res = re.sub(r"\n{3,}", "\n\n", "\n".join(out)).strip() + "\n"
    res = re.sub(r"\n+(\{end_of_\w+\})", r"\n\1", res)
    return res, checks


def verify(checks):
    bad = 0
    for chords, lyric, merged in checks:
        c2, l2 = split_back(merged)
        if c2 != chords.rstrip() or l2 != lyric.rstrip():
            bad += 1
            print("НЕ СОШЛОСЬ:\n  было:  ", repr(chords), repr(lyric), "\n  стало:", repr(c2), repr(l2))
    return bad


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("src")
    p.add_argument("--title", required=True)
    p.add_argument("--artist", required=True)
    p.add_argument("-o", "--out", required=True)
    a = p.parse_args()
    res, checks = convert(open(a.src, encoding="utf-8").read(), a.title, a.artist)
    bad = verify(checks)
    open(a.out, "w", encoding="utf-8").write(res)
    print(f"строк с аккордами: {len(checks)}, не сошлось: {bad} -> {a.out}")
    sys.exit(1 if bad else 0)
