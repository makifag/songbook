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

- `sources.json` — вход: список из 51 источника (`title_raw, url_norm, domain,
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

- `formats/{slug}.atex` — **alphaTex** (табы): ноты, ритм, строй. Рисует и
  проигрывает **alphaTab** (`vendor/alphatab/`, 1.8.4, копия из npm).
  Показываем **только таб**: без нотного стана, без ключа TAB, ритм — штилями
  под табом (`assets/song.js`).
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
- `tools/gridtab.py` — табы без строки длительностей: ритм по равномерной
  сетке (Home, Wet Hands), по расстояниям между нотами (Lil Gator — ритм
  приблизительный) или из ручной разметки `formats/rhythm/{slug}.txt`
  (Greensleeves: строка на такт, `4 8 8. 16 8`). Настройки — `GRID_TABS` в
  `convert_all.py`.
- `tools/chords2chordpro.py` — аккорды над текстом → ChordPro; понимает
  `[Куплет]:Am ...`, `Припев:<таб>текст`, `(1)` номера куплетов, аккорды на
  дефисах `----D----G`, позиции `G(III)`, текст «через строку», аккорды,
  отделённые от строки пустой строкой.

Сборка без сети: `python build.py --offline` пересобирает страницы из
`songbook/raw/*.txt` + `songbook/songs.json` (метаданные, пишет обычная
сборка), отчёт не трогает. Порядок после правки форматов:
`python tools/convert_all.py && python build.py --offline`.

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
  `git push origin main && npx wrangler deploy`.

## Осознанно не делать (см. ТЗ.md)

- ChordPro делаем только с посимвольной обратной проверкой — без неё позиции
  аккордов съезжают незаметно.
- Не логиниться на amdm/vk силой. gametabs `.gp5`/`.mid` — только если в
  конфиге когда-нибудь появится session-cookie (сейчас нет, и это ок).
