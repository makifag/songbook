// Сверка alphaTex против нот исходного ASCII, через парсер самого alphaTab.
// Сравнивает такт, позицию в такте (тики), лад и реальную высоту звука —
// ловит и сдвиг ноты, и перепутанные струны/строй, и ошибку синтаксиса.
//
//   node tools/verify_alphatex.mjs jobs.json   -> печатает JSON с результатами
// jobs.json: [{ "id", "tex", "tuning": [midi сверху вниз], "events": [{bar, tick, string, fret, grace?}] }]
import fs from "node:fs";
import * as alphaTab from "@coderline/alphatab";

const jobs = JSON.parse(fs.readFileSync(process.argv[2], "utf8"));
const results = [];

for (const job of jobs) {
  const res = { id: job.id, ok: false };
  try {
    const importer = new alphaTab.importer.AlphaTexImporter();
    importer.initFromString(job.tex, new alphaTab.Settings());
    const score = importer.readScore();
    const bars = score.tracks[0].staves[0].bars;
    const got = [];
    bars.forEach((bar, bi) => {
      const start = score.masterBars[bi].start;
      for (const beat of bar.voices[0].beats) {
        if (beat.graceType) continue;
        for (const note of beat.notes) {
          if (note.isDead || note.isTieDestination) continue;
          got.push({ bar: bi, tick: beat.playbackStart, fret: note.fret, pitch: note.realValue });
        }
      }
    });
    const exp = job.events.filter((e) => !e.grace).map((e) => ({
      bar: e.bar, tick: e.tick, fret: e.fret, pitch: job.tuning[e.string - 1] + e.fret,
    }));
    const key = (e) => `${e.bar}:${e.tick}:${e.fret}:${e.pitch}`;
    const count = (arr) => arr.reduce((m, e) => m.set(key(e), (m.get(key(e)) || 0) + 1), new Map());
    const A = count(exp), B = count(got);
    const missing = [...A].filter(([k, n]) => (B.get(k) || 0) < n).map(([k]) => k);
    const extra = [...B].filter(([k, n]) => (A.get(k) || 0) < n).map(([k]) => k);
    res.bars = bars.length;
    res.notes = exp.length;
    res.missing = missing.slice(0, 5);
    res.extra = extra.slice(0, 5);
    res.ok = !missing.length && !extra.length && exp.length > 0;
  } catch (e) {
    res.error = String(e && e.message || e).slice(0, 300);
  }
  results.push(res);
}
console.log(JSON.stringify(results));
