"""Свернуть одинаковые подряд идущие куски alphaTex в знаки повтора и вольты.

Звук не меняется: alphaTab проигрывает |: … :| ×N так же, как выписанное подряд.
Ничего не угадываем — сворачиваются только побуквенно одинаковые такты, и
результат проверяется разворотом обратно (unfold(fold(x)) == x), а потом
сверкой нот через alphaTab (convert_all).

Не сворачиваем:
- табы, где повторы уже есть (\\ro / \\rc);
- копию, в которой есть смена размера/темпа (\\ts, \\tempo) — повторялось бы и оно;
- кусок, первый такт которого начинается лигой (-.N): при повторе она
  привязалась бы к другой ноте.
"""
import re

MAX_BLOCK = 16
META = re.compile(r"^(\\(?:ts \d+ \d+|tempo \d+(?:\.\d+)?|ro|rc \d+|ae \([^)]*\)))\s*")
HEAD = re.compile(r"^(\\(?:title|artist|album|tempo|track|staff|tuning|capo|subtitle|music|words)\b.*|\.|/\*.*|\*/|\s*)$")


def split(tex):
    """→ (шапка, такты). Такт — текст между | без пробелов по краям."""
    lines = tex.split("\n")
    i = 0
    in_comment = False
    while i < len(lines):
        line = lines[i]
        if in_comment:
            in_comment = "*/" not in line
            i += 1
            continue
        if line.startswith("/*"):
            in_comment = "*/" not in line
            i += 1
            continue
        if HEAD.match(line) and not line.startswith("\\ts"):
            i += 1
            continue
        break
    head = "\n".join(lines[:i])
    body = "\n".join(lines[i:])
    bars = [b.strip() for b in body.split("|")]
    if bars and not bars[-1]:
        bars.pop()
    return head, bars


def parse_bar(bar):
    metas, s = [], bar
    while True:
        m = META.match(s)
        if not m:
            break
        metas.append(m.group(1))
        s = s[m.end():]
    return metas, s.strip()


def join(head, bars):
    return head + "\n" + "\n".join(f"{b} |" for b in bars) + "\n"


def fold(tex, events):
    """→ (tex, events, сообщение) или (tex, events, None), если сворачивать нечего."""
    head, bars = split(tex)
    if any(re.search(r"\\(ro|rc)\b", b) for b in bars):
        return tex, events, None
    parsed = [parse_bar(b) for b in bars]
    content = [c for _, c in parsed]
    n = len(bars)
    out, mapping, i = [], [], 0
    while i < n:
        best = None
        for L in range(1, min(MAX_BLOCK, (n - i) // 2) + 1):
            if content[i].startswith("-.") or re.match(r"^\(?-\.", content[i]):
                break
            k = 1
            while (i + (k + 1) * L <= n and content[i + k * L:i + (k + 1) * L] == content[i:i + L]
                   and not any(parsed[j][0] for j in range(i + k * L, i + (k + 1) * L))):
                k += 1
            if k >= 2:
                saved = L * (k - 1)
                if best is None or saved > best[2]:
                    best = (L, k, saved)
        # вольты: тело + концовка1, тело + концовка2 → |: тело |1. к1 :|2. к2
        volta = None
        for B in range(2, MAX_BLOCK + 1):
            for E in (1, 2):
                if E > B or i + 2 * (B + E) > n:
                    continue
                b1, e1 = i, i + B
                b2, e2 = i + B + E, i + 2 * B + E
                if (content[b1:b1 + B] == content[b2:b2 + B] and content[e1:e1 + E] != content[e2:e2 + E]
                        and not any(parsed[j][0] for j in range(b2, b2 + B))
                        and not any(parsed[j][0] for j in range(e2, e2 + E))
                        and not content[i].startswith("-.") and not re.match(r"^\(?-\.", content[e2])):
                    if volta is None or B > volta[2]:
                        volta = (B, E, B)
        if volta and (best is None or volta[2] > best[2]):
            B, E, _ = volta
            for j in range(i, i + B):
                metas = list(parsed[j][0]) + (["\\ro"] if j == i else [])
                out.append(" ".join(metas + [parsed[j][1]])); mapping.append(j)
            for j in range(i + B, i + B + E):
                metas = list(parsed[j][0]) + ["\\ae (1)"] + ([f"\\rc 2"] if j == i + B + E - 1 else [])
                out.append(" ".join(metas + [parsed[j][1]])); mapping.append(j)
            for j in range(i + 2 * B + E, i + 2 * B + 2 * E):
                metas = list(parsed[j][0]) + ["\\ae (2)"]
                out.append(" ".join(metas + [parsed[j][1]])); mapping.append(j)
            i += 2 * (B + E)
            continue
        if best:
            L, k, _ = best
            for j in range(i, i + L):
                metas = list(parsed[j][0])
                if j == i:
                    metas.append("\\ro")
                if j == i + L - 1:
                    metas.append(f"\\rc {k}")
                out.append(" ".join(metas + [parsed[j][1]]))
                mapping.append(j)
            i += k * L
        else:
            out.append(bars[i])
            mapping.append(i)
            i += 1
    if len(out) == n:
        return tex, events, None
    # проверка разворотом: свёрнутое, проигранное по повторам, = исходное
    if unfold(out) != content:
        raise ValueError("свёртка повторов не сходится с исходником при развороте")
    new_index = {orig: new for new, orig in enumerate(mapping)}
    new_events = [dict(e, bar=new_index[e["bar"]]) for e in events if e["bar"] in new_index]
    return join(head, out), new_events, f"повторы свёрнуты: {n} тактов → {len(out)}"


def unfold(bars):
    """Развернуть |: … :| ×N и вольты 1./2. обратно в список тактов (без метаданных)."""
    parsed = [parse_bar(b) for b in bars]
    res, i, start = [], 0, None
    while i < len(parsed):
        metas, c = parsed[i]
        if "\\ro" in metas:
            start = i
        if "\\ae (2)" in metas:
            res.append(c)  # вторая концовка играется после повторного тела
            i += 1
            continue
        res.append(c)
        rc = next((int(m.split()[1]) for m in metas if m.startswith("\\rc")), None)
        if rc and start is not None:
            block = [p for p in parsed[start:i + 1]]
            body = [p[1] for p in block if "\\ae (1)" not in p[0]]
            if len(body) < len(block):  # с вольтой: тело ещё раз, дальше — концовка 2
                res.extend(body)
            else:
                res.extend([p[1] for p in block] * (rc - 1))
            start = None
        i += 1
    return res
