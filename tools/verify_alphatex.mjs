// Сверка: alphaTex, разобранный самим alphaTab, против нот из ASCII-оригинала.
// Сравнивает такт, позицию в такте, лад и реальную высоту звука (MIDI) —
// так ловится и сдвиг ноты, и перепутанная нумерация струн/строй.
// node tools/verify_alphatex.mjs file.atex events.json
import fs from "node:fs";
import * as alphaTab from "@coderline/alphatab";

const [, , atexPath, eventsPath] = process.argv;
const tex = fs.readFileSync(atexPath, "utf8");
const meta = JSON.parse(fs.readFileSync(eventsPath, "utf8"));

const NOTE = { c: 0, d: 2, e: 4, f: 5, g: 7, a: 9, b: 11 };
const midi = (n) => {
  const m = /^([a-g])([#b]?)(-?\d)$/i.exec(n);
  return 12 * (+m[3] + 1) + NOTE[m[1].toLowerCase()] + (m[2] === "#" ? 1 : m[2] === "b" ? -1 : 0);
};
const tuningMidi = meta.tuning.map(midi); // сверху вниз, как в ASCII

const settings = new alphaTab.Settings();
const importer = new alphaTab.importer.AlphaTexImporter();
importer.initFromString(tex, settings);
const score = importer.readScore();

const ticksPerSlot = (960 * 4) / meta.slot;
const got = [];
const bars = score.tracks[0].staves[0].bars;
bars.forEach((bar, bi) => {
  for (const beat of bar.voices[0].beats) {
    for (const note of beat.notes) {
      got.push({
        bar: bi,
        slot: beat.playbackStart / ticksPerSlot,
        fret: note.fret,
        pitch: note.realValue,
      });
    }
  }
});

const key = (e) => `${e.bar}:${e.slot}:${e.fret}:${e.pitch}`;
const expected = meta.events.map((e) => ({
  bar: e.bar, slot: e.slot, fret: e.fret, pitch: tuningMidi[e.string - 1] + e.fret,
}));
const A = new Map(), B = new Map();
for (const e of expected) A.set(key(e), (A.get(key(e)) || 0) + 1);
for (const e of got) B.set(key(e), (B.get(key(e)) || 0) + 1);
const missing = [...A].filter(([k, n]) => (B.get(k) || 0) < n).map(([k]) => k);
const extra = [...B].filter(([k, n]) => (A.get(k) || 0) < n).map(([k]) => k);

// длительность каждого такта должна совпасть с размером
const badBars = bars
  .map((b, i) => [i, b.voices[0].beats.reduce((s, x) => s + x.playbackDuration, 0)])
  .filter(([, t]) => t !== meta.bar_slots * ticksPerSlot);

console.log(`тактов: ${bars.length}, нот ожидалось: ${expected.length}, получено: ${got.length}`);
console.log(`пропало: ${missing.length}, лишних: ${extra.length}, тактов с неверной длиной: ${badBars.length}`);
if (missing.length) console.log("пропало:", missing.slice(0, 10));
if (extra.length) console.log("лишние:", extra.slice(0, 10));
if (badBars.length) console.log("такты:", badBars.slice(0, 10));
process.exit(missing.length || extra.length || badBars.length ? 1 : 0);
