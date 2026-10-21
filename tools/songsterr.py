"""Songsterr → alphaTex.

У songsterr ноты лежат JSON-ом с точными длительностями (не ASCII), поэтому
ритм не восстанавливается, а переносится как есть. Скачанная партия хранится в
manual_assets/songsterr/{slug}.json — сборка сеть не трогает.

  python tools/songsterr.py fetch <slug> <songId> [part]   — скачать партию

Формат партии (version 5): measures[] → voices[] → beats[] → notes[];
струна 0 — верхняя (тонкая), tuning — midi сверху вниз, duration — [n, d]
от целой (уже с точкой и триолью), type — основание длительности.
"""
import gzip
import json
import sys
import urllib.request
from fractions import Fraction
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STORE = ROOT / "manual_assets" / "songsterr"
CDN = "https://dqsljvtekg760.cloudfront.net"
NAMES = ["c", "c#", "d", "d#", "e", "f", "f#", "g", "g#", "a", "a#", "b"]
SLIDE = {"legato": "sl", "shift": "ss", "downwards": "sod", "upwards": "sou",
         "intoFromBelow": "sib", "intoFromAbove": "sia"}


class NotUnderstood(Exception):
    pass


def _get(url):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (songbook)"})
    raw = urllib.request.urlopen(req, timeout=30).read()
    return raw if raw[:2] != b"\x1f\x8b" else gzip.decompress(raw)


def fetch(slug, song_id, part=None):
    meta = json.loads(_get(f"https://www.songsterr.com/api/meta/{song_id}"))
    if part is None:
        part = meta.get("popularTrackGuitar", meta.get("defaultTrack", 0))
    data = json.loads(_get(f"{CDN}/{song_id}/{meta['revisionId']}/{meta['image']}/{part}.json"))
    data["_meta"] = {"songId": song_id, "revisionId": meta["revisionId"], "part": part,
                     "artist": meta["artist"], "title": meta["title"],
                     "url": f"https://www.songsterr.com/a/wsa/-tab-s{song_id}"}
    STORE.mkdir(parents=True, exist_ok=True)
    (STORE / f"{slug}.json").write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return data


def tuning_names(midi):
    return [f"{NAMES[m % 12]}{m // 12 - 1}" for m in midi]


def _dur(beat):
    t = beat["type"]
    if t not in (1, 2, 4, 8, 16, 32, 64):
        raise NotUnderstood(f"длительность type={t}")
    fx = []
    dots = beat.get("dots", 1 if beat.get("dotted") else 0)
    fx += ["d"] if dots == 1 else ["dd"] if dots == 2 else []
    tu = beat.get("tuplet")
    if tu:
        fx.append(f"tu {tu}")
    # проверка: длительность из type/точек/триоли = duration songsterr
    expect = Fraction(1, t) * (Fraction(3, 2) if dots == 1 else Fraction(7, 4) if dots == 2 else 1)
    if tu:
        expect *= Fraction({3: 2, 5: 4, 6: 4, 7: 4}.get(tu, tu - 1), tu)
    n, d = beat["duration"]
    if expect != Fraction(n, d):
        raise NotUnderstood(f"длительность {n}/{d} не сходится с type={t} точки={dots} tuplet={tu}")
    return str(t), fx, Fraction(n, d)


def to_alphatex(part, title, artist):
    """→ (alphaTex, events, строй со звучанием капо — midi сверху вниз, заметки)"""
    tuning = part["tuning"]
    nstr = len(tuning)
    tempos = {a["measure"]: a["bpm"] for a in (part.get("automations") or {}).get("tempo", [])}
    head = [f'\\title "{title}"', f'\\artist "{artist}"', f"\\tempo {tempos.get(1, 90)}", ".",
            '\\track "Guitar"', "\\staff {tabs}", "\\tuning " + " ".join(tuning_names(tuning))]
    if part.get("capo"):
        head.append(f"\\capo {part['capo']}")
    bars, events, notes_out = [], [], []
    cur_sig = None
    for bi, m in enumerate(part["measures"]):
        voices = [v for v in m["voices"] if any(not b.get("rest") for b in v["beats"])]
        if len(voices) > 1:
            raise NotUnderstood(f"такт {bi + 1}: несколько голосов")
        toks = []
        sig = tuple(m["signature"]) if "signature" in m else cur_sig
        if sig != cur_sig:
            toks.append(f"\\ts {sig[0]} {sig[1]}")
            cur_sig = sig
        if bi > 0 and (bi + 1) in tempos:
            toks.append(f"\\tempo {tempos[bi + 1]}")
        if m.get("repeatStart"):
            toks.append("\\ro")
        if m.get("repeat"):
            toks.append(f"\\rc {m['repeat']}")
        if m.get("alternateEnding"):
            toks.append("\\ae (" + " ".join(str(x) for x in m["alternateEnding"]) + ")")
        pos = Fraction(0)
        beats = (voices[0] if voices else m["voices"][0])["beats"]
        for b in beats:
            dur, bfx, length = _dur(b)
            played = [n for n in b.get("notes", []) if not n.get("rest")]
            if b.get("rest") or not played:
                tok = "r"
            else:
                parts = []
                for n in played:
                    s = n["string"] + 1  # alphaTex: 1 — верхняя струна
                    if not 1 <= s <= nstr:
                        raise NotUnderstood(f"такт {bi + 1}: струна {n['string']}")
                    fret = "-" if n.get("tie") else "x" if n.get("dead") else str(n["fret"])
                    fx = []
                    if n.get("hp"):
                        fx.append("h")
                    if n.get("slide"):
                        if n["slide"] not in SLIDE:
                            raise NotUnderstood(f"слайд {n['slide']}")
                        fx.append(SLIDE[n["slide"]])
                    if n.get("harmonic"):
                        fx.append("nh" if n["harmonic"] == "natural" else "ah")
                    if n.get("leftHandVibrato") or n.get("vibrato"):
                        fx.append("v")
                    parts.append(f"{fret}.{s}" + ("{" + " ".join(fx) + "}" if fx else ""))
                    if not n.get("tie") and not n.get("dead"):
                        events.append({"bar": bi, "tick": int(pos * 3840), "string": s, "fret": n["fret"]})
                tok = parts[0] if len(parts) == 1 else "(" + " ".join(parts) + ")"
            toks.append(f"{tok}.{dur}" + ("{" + " ".join(bfx) + "}" if bfx else ""))
            pos += length
        if cur_sig and pos != Fraction(cur_sig[0], cur_sig[1]):
            notes_out.append(f"такт {bi + 1}: длина {pos} при размере {cur_sig[0]}/{cur_sig[1]}")
        bars.append(" ".join(toks) + " |")
    # для сверки — реальный звук: лады у songsterr от капо, alphaTab высоту считает с капо
    sounding = [t + (part.get("capo") or 0) for t in tuning]
    return "\n".join(head) + "\n" + "\n".join(bars) + "\n", events, sounding, notes_out


if __name__ == "__main__":
    if len(sys.argv) >= 4 and sys.argv[1] == "fetch":
        d = fetch(sys.argv[2], int(sys.argv[3]), int(sys.argv[4]) if len(sys.argv) > 4 else None)
        print(d["_meta"], "measures", len(d["measures"]))
    else:
        print(__doc__)
