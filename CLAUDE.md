# Песенник (offline songbook)

Оффлайн-песенник из закладок: `build.py` скачивает табы/аккорды с 8 доменов,
вычищает от обвязки сайтов и собирает статический сайт `songbook/` с поиском
и фильтром. Полное ТЗ — [ТЗ.md](ТЗ.md).

## Запуск

```bash
pip install -r requirements.txt
python build.py            # обычный прогон — кэш не трогает, если моложе 30 дней
python build.py --refetch  # принудительно перекачать всё заново
```

Один вход (`sources.json`) → один выход (`songbook/` + `songbook.zip`).
Прогон идемпотентен: без `--refetch` второй запуск не делает сетевых
запросов вообще (все ответы лежат в `cache/{sha1(url)}.html`, не в гите).

## Структура

- `sources.json` — вход: список из 51 источника (Home с 2026-10-21 — с Songsterr,
  в `manual_entries.json`) (`title_raw, url_norm, domain,
  artist, work, handler, status, note`). `status`: `live` / `dead_wayback`
  (тянуть из Wayback) / `manual` (в отчёт, не качать).
- `build.py` — весь пайплайн в одном файле: fetch+cache → handler-specific
  extractor → рендер `songs/{slug}.html` + `raw/{slug}.txt` → `index.html` →
  `report.html` → `songbook.zip`.
- `URL_OVERRIDES` в начале `build.py` — вручную сверенные замены для
  gametabs.net-ссылок, у которых слаг игры/песни уехал с момента, когда
  делались закладки (сайт периодически переименовывает `/games/{slug}`).
  Если в отчёте снова появится gap с `HTTP 404` на gametabs — почти всегда
  проблема тут: ищи текущий слаг через `https://gametabs.net/games/{game}`
  (пагинация `?page=N`, по 50 табов на страницу) и добавляй в словарь.
- `songbook/reports/` — архив прошлых `report.html` (создаётся автоматически
  при каждом прогоне, текущий отчёт остаётся `report.html` в корне).

## Форматы хранения и отображение

**Табы текстом не показываем вообще** (решение владельца) — каждый таб
переводится в alphaTex. Исключение — вставки табов внутри песен с аккордами
(блоки `{start_of_tab}` в ChordPro).

- `formats/{slug}.atex` — **alphaTex** (табы): ноты, ритм, строй. alphaTab
  (`vendor/alphatab/`, 1.8.4, копия из npm) разбирает его в модель и играет звук
  (рисует за кадром один такт — без этого не грузит плеер). **Сам таб рисует
  `assets/tabview.js`** (SVG по модели alphaTab):
  - время линейное, масштаб (px на тик) один на песню — по медианному такту;
    одинаковые такты одной ширины, в строке их одинаковое число. Плотный такт
    (редкая триоль, тридцатьвторые) не расширяется — ноты раздвигаются внутри;
  - размер такта — мелко (≈ цифры лада) на узком поле слева; новый размер — новая строка (кроме затакта в
    начале). Если размер меняется чаще раза на 6 тактов (Lil Gator, Wet Hands) —
    строки не рвутся, смена подписана мелко над тактом;
  - над табом мелкие буквы длительностей (W H Q E S T, `.` — точка, `3` — триоль),
    кнопка «длит.»; масштаб `− +`, «тактов в строке» — в `localStorage`;
  - курсор: `playerPositionChanged` → `api.tickCache.findBeat()`; клик по табу —
    перемотка. Наверху только название, плей/стоп, темп, масштаб; сведения о
    табе — под «ещё».
- `formats/{slug}.cho` — **ChordPro** (песни с аккордами): `[Am]текст`, свой
  рендер + транспонирование.
- `.gp5` из `manual_entries.json` — alphaTab грузит файл Guitar Pro напрямую.

`formats/` генерирует `python tools/convert_all.py` (нужен `npm install` —
alphaTab для проверки). Ноты проверяются всегда: alphaTex разбирается обратно
самим alphaTab и каждая нота сверяется с ASCII (такт, позиция, лад, высота
звука); ChordPro раскладывается обратно в "аккорды над текстом" посимвольно.
Всё, что конвертер поправил или достроил, пишется в `formats/status.json`
(`notes`) и показывается на странице песни строкой «при переводе: …».

- `tools/gpascii.py` — ASCII-экспорт Guitar Pro (gametabs): строка длительностей
  `Q E S H.` над струнами, триоли `|-3-|`, `L` лига, `x`, `(5)`, форшлаг `2g3`,
  легато-цепочка `1h3p1` (доля делится между нотами). Режим `tolerance=1`:
  нота на колонку мимо буквы привязывается к соседней доле, строка
  длительностей, съехавшая целиком на 1–4 колонки в такте, сдвигается;
  лишняя короткая нота в переполненном такте становится форшлагом.
  Капо из шапки таба («Capo 2», «Guitar (Capo 3)», «Capo on the 3rd fret») —
  в `\capo` (`convert_all.py`); «капо по желанию» словами (Call of Magic) не
  берётся. Темп, если его нет в шапке, — `TEMPO_HINT` в `convert_all.py`.
- `tools/gridtab.py` — табы без строки длительностей: ритм по равномерной
  сетке (Wet Hands — с ultimate-guitar, последняя строка перекладывается
  `respace()`), по расстояниям между нотами (Lil Gator — ритм
  приблизительный) или из ручной разметки `formats/rhythm/{slug}.txt`
  (Greensleeves: строка на такт, `4 8 8. 16 8`). Настройки — `GRID_TABS` в
  `convert_all.py`.
- `tools/songsterr.py` — Songsterr → alphaTex. У songsterr ноты — JSON с точными
  длительностями (CDN `dqsljvtekg760.cloudfront.net`, gzip), ритм переносится как
  есть: точки, триоли, лиги, `h/p`, слайды, вибрато, `x`, флажолеты, повторы и
  вольты, смена темпа/размера, капо. Партия скачивается один раз
  (`python tools/songsterr.py fetch <slug> <songId> [part]`) в
  `manual_assets/songsterr/{slug}.json`, песня — запись в `manual_entries.json`
  (поле `songsterr`). Сверка — по реальному звуку с капо; у флажолетов — без
  обертона (`realValueWithoutHarmonic` в `verify_alphatex.mjs`).
- `tools/chords2chordpro.py` — аккорды над текстом → ChordPro; понимает
  `[Куплет]:Am ...`, `Припев:<таб>текст`, `(1)` номера куплетов, аккорды на
  дефисах `----D----G`, позиции `G(III)`, текст «через строку», аккорды,
  отделённые от строки пустой строкой.

Сборка без сети: `python build.py --offline` пересобирает страницы из
`songbook/raw/*.txt` + `songbook/songs.json` (метаданные, пишет обычная
сборка), отчёт не трогает. Порядок после правки форматов:
`python tools/convert_all.py && python build.py --offline`.

## Правки хозяина с сайта (Worker + D1)

Воркер `songbook` — не только статика: `worker/index.js` отдаёт `songbook/` и
маленький API на `/api/*` (`run_worker_first`), данные — в D1 `songbook`
(схема `worker/schema.sql`, таблицы `hidden`, `marks`, `wish`).

- Читать (`GET /api/state`) может любой; писать (`/api/hide`, `/api/mark`,
  `/api/wish`) — только с заголовком `x-key` = секрет `OWNER_KEY`
  (`wrangler secret put OWNER_KEY`). Хозяин задаёт ключ один раз ссылкой
  `…/#key=XXXX` или кнопкой «ключ хозяина» внизу главной (`localStorage`).
- `assets/owner.js` — клиент API (общий), значки отметок, на странице песни —
  отметки под заголовком и «убрать из песенника» внизу.
  `assets/index.js` — главная: «Хочу найти» (только хозяину), вкладки
  сложности, фильтр знакомства, «Убранные» с «вернуть».
- Отметки ставит только хозяин, касанием по значку: **знакомство** — фазы луны
  ○ ◔ ◑ ◕ ● (не играл → разбираю → по табу → почти → наизусть), **сложность** —
  столбики ▁▃▅▇ (легко / средне / трудно / вызов), 0 — не отмечено.
- «Убрать» не удаляет файлы — только прячет из списка (D1 `hidden`).
- «Хочу найти» — список хозяина (что + ссылка). Читать при заходе:
  `npx wrangler d1 execute songbook --remote --command "SELECT * FROM wish"`.
  Скрытые: `SELECT * FROM hidden`.
- Локально: `.dev.vars` с `OWNER_KEY=…`, `npx wrangler d1 execute songbook
  --local --file worker/schema.sql`, `npx wrangler dev`.
- Без сети (zip) API молчит — страницы работают как раньше, без отметок.

Таб показывает строй и капо в «ещё»; если строй не стандарт или есть капо —
ещё и строкой над табом (`showTuning` в `assets/song.js`).

## Хендлеры (по `handler` в sources.json)

| handler | домен | как достаём тело |
|---|---|---|
| `gametabs_ascii` | gametabs.net | `<pre id="tab-text-view-text">`, метаданные — `<p>Composer: ...</p>` рядом |
| `amdm_chords` | amdm.ru | `<pre itemprop="chordsBlock">` — `white-space:pre` + `display:inline` для чанков аккордов, поэтому `get_text()` даёт точное выравнивание |
| `generic_chords` | gitaristu.ru | тот же паттерн `pre[itemprop=chordsBlock]`, что и amdm |
| `mychords_chords` | mychords.net | **не** `<pre>` — раскладка чанками `<div class="pline"><span class="subline">`; см. "Ловушка с пробелами" ниже |
| `ultimateguitar_json` | tabs.ultimate-guitar.com | контент не в HTML — JSON в `div.js-store[data-content]`, `store.page.data.tab_view.wiki_tab.content`, снять `[tab]`/`[ch]` |
| `manual_vk`, `songsterr_api`, `manual_search` | vk.com, songsterr.com, google.com | не автоматизируется, идёт в отчёт как `manual`. Единственное исключение — прямая `doc`-ссылка VK на PDF (Сеговия): пробуем скачать напрямую, проверяем магический байт `%PDF` |

## Wayback-фолбэк для «Кино» (amdm.ru удалил по требованию правообладателя)

`handle_wayback()` **не** использует `archive.org/wayback/available` —
у этого API агрессивный глобальный рейт-лимит (легко ловится 429 даже на
первом запросе, независимо от бэкоффа). Вместо этого:

1. `web.archive.org/cdx/search/cdx?url=...&output=json&filter=statuscode:200`
   — список всех снапшотов, без рейт-лимита.
2. Идём от самого свежего снапшота назад во времени и пробуем
   `http://web.archive.org/web/{ts}id_/{url}` (суффикс `id_` = отдать сырой
   HTML без баннера Wayback).
3. **Важно:** самые свежие снапшоты после даты удаления — это архивная копия
   самой страницы-заглушки «удалено по требованию правообладателя», не
   песня. Поэтому идём вглубь (`WAYBACK_MAX_SNAPSHOTS_TRIED = 40`), пока не
   найдём снапшот, где реально парсится `pre[itemprop=chordsBlock]`.
4. Снапшоты отдаются в Brotli (`content-encoding: br`) — без пакета `brotli`
   `requests` тихо вернёт мусор вместо ошибки. Он уже в `requirements.txt`.

## Ловушка с пробелами у bs4 (mychords_chords)

`BeautifulSoup` (4.15, оба билдера — `lxml` и `html.parser`) схлопывает
подряд идущие пробелы в текстовых узлах до одного — **кроме** содержимого
`<pre>`, которое по спецификации whitespace-preserving. У amdm/gitaristu
тело в `<pre>`, поэтому их это не касается. У mychords.net аккорды
позиционируются литеральными пробелами внутри `<span class="subline">`
(не `<pre>`), и это ломает выравнивание аккордов над словами.

Решение — `_protect_subline_spacing()`: до парсинга находит
`<span class="subline">...</span>` балансировкой скобок (обычный regex не
годится — внутри есть вложенные `<span class="b-accord__symbol">`), меняет
внутри найденного пробельные цепочки на NBSP (`\xa0`, bs4 их не трогает),
после `get_text()` конвертирует обратно в обычные пробелы.

Если добавляешь новый handler с раскладкой аккордов вне `<pre>` —
проверяй эту ловушку в первую очередь, симптом — все чанки аккордов
слипаются в один пробел.

## Деплой

- **Порядок работы:** владелец работает только через чат с Claude (облачная
  сессия Claude Code). Коммиты — прямо в `main`, без feature-веток и PR;
  деплой делает Claude сам.
- **GitHub:** `github.com/makifag/songbook` (публичный).
- **Cloudflare:** воркер `songbook`, конфиг — `wrangler.toml` (assets-only
  Worker, не Pages — `wrangler pages deploy` для новых проектов ругается и
  сам советует Workers). Сайт — https://songbook.makifag.workers.dev.
  Обновить прод:
  ```bash
  npx wrangler deploy
  ```
  `wrangler` берёт токен из `CLOUDFLARE_API_TOKEN` (задан в окружении
  облачной сессии; `wrangler whoami` покажет `makifag@gmail.com`).
- Автодеплоя по git push **нет**. Обновление —
  `git push origin main && npx wrangler deploy` (выкладывает и статику, и
  `worker/index.js` с привязкой D1).

## Осознанно не делать (см. ТЗ.md)

- ChordPro делаем только с посимвольной обратной проверкой — без неё позиции
  аккордов съезжают незаметно.
- Не логиниться на amdm/vk силой. gametabs `.gp5`/`.mid` — только если в
  конфиге когда-нибудь появится session-cookie (сейчас нет, и это ок).
