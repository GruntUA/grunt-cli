# Grunt CLI — Roadmap: фічі з Frappe, яких не вистачає

## 1. Bench — повноцінний оркестратор (ПРІОРИТЕТ)
**Статус:** В розробці

Frappe Bench — менеджер мультисайтовості. Один інстанс обслуговує десятки сайтів
з різними БД, доменами, версіями апок.

### Що потрібно:
- [ ] `grunt bench init <name>` — створює bench-структуру:
  ```
  my-bench/
  ├── apps/
  │   └── grunt/          ← фреймворк (один на всі сайти)
  ├── sites/
  │   ├── site1.local/
  │   │   ├── grunt.site
  │   │   ├── .env
  │   │   └── grunt.db
  │   └── site2.local/
  │       ├── grunt.site
  │       ├── .env
  │       └── grunt.db
  ├── .venv/              ← спільний venv
  ├── .node/              ← спільний Node.js
  └── Procfile            ← запуск всіх процесів
  ```
- [ ] `grunt new-site <name>` — створює новий сайт у bench/sites/
- [ ] `grunt drop-site <name>` — видаляє сайт
- [ ] `grunt use <site>` — перемикає поточний сайт (зберігає в bench/sites/currentsite.txt)
- [ ] `grunt site list` — працює і без bench (для flat-структури теж)
- [ ] `grunt serve` — у bench-режимі обслуговує всі сайти через один процес
- [ ] `grunt install` — зберігається як спрощений варіант (flat site, без bench)
- [ ] Мультисайтовий routing у FastAPI (site resolution по Host header)

---

## 2. Server Scripts / Client Scripts
Можливість писати Python/JS скрипти прямо з браузера, без деплою.
Наприклад: "при збереженні документа — перерахувати суму".
У Ґрунт є hook system, але він вимагає коду в файлах.

---

## 3. Virtual DocType
DocType без таблиці в БД — дані з зовнішнього API, файлу чи сервісу.
Виглядає як звичайний DocType, але під капотом — адаптер.

---

## 4. Document Naming Series
Гнучка нумерація: `INV-2026-00001`, `HR-.YYYY.-.####` —
лічильники, префікси, фінансові роки. У Ґрунт є autoname, але простіший.

---

## 5. Print Format Designer
Візуальний конструктор друкованих форм (drag-drop) + Jinja шаблони.
Ґрунт має print renderer, але без візуального дизайнера.

---

## 6. Web Portal / Website Builder
Публічний сайт "з коробки" — блог, сторінки, web forms
для зовнішніх користувачів. Ґрунт — тільки desk.

---

## 7. Data Import / Export UI
Повноцінний інтерфейс імпорту з маппінгом колонок, попереднім переглядом,
обробкою помилок рядок-за-рядком.

---

## 8. Автоматичні Link-графи та Dashboard
Автоматично показує пов'язані документи:
"У цього Контрагента — 15 Договорів, 3 Рахунки".
Connections panel + auto-generated dashboard counts.

**Статус:** частково. Панель «Зв'язки» з лічильниками й прев'ю вже є:
`DocType.links` (`DocTypeLink`, `grunt/metadata/doctype.py:214`) →
`grunt.document.connections.get_connections` → `DocConnections.vue`.
Бракує решти Frappe Form Dashboard
(див. https://discuss.frappe.io/t/how-to-guide-frappe-form-dashboards/135642).

### Що потрібно: `frm.dashboard` (клієнтський API форми)
Нова область `FormDashboard.vue` над полями форми (у `FormRenderer.vue`, поруч із
`DocConnections`), стан якої керується з Client Script через `frm.dashboard`
(додати в `FormProxy`, `frontend/src/core/scripting/executor.ts`, за зразком
`toggle_sidebar` → `_sidebar_hidden`: скрипт пише в реактивний стан, компонент рендерить).
Стан скидається при кожному `refresh` документа (як у Frappe `frm.dashboard.reset()`).

- [ ] `set_headline(html, color?)` / `clear_headline()` — банер-повідомлення над формою
      (аналог `set_intro`); HTML санітизувати (DOMPurify), колір із палітри status_indicators.
- [ ] `add_indicator(label, color)` — рядок stat-бейджів («Оплачено: 12 000 ₴» зеленим).
- [ ] `add_progress(title, percent | [{title, width, progress_class}], message?)` —
      progress-бари (кілька сегментів, як у Frappe).
- [ ] `render_graph({ data: {labels, datasets}, type, colors })` — перевикористати
      `frontend/src/core/charts.ts` / віджет `dashboard/widgets/Chart`.
- [ ] `render_heatmap({ data: {dataPoints, start, end} })` — перевикористати
      `dashboard/widgets/Heatmap`.
- [ ] `add_section(body_html, label?, css_class?, hidden?)` / `clear_section(name)` —
      довільна HTML-секція.
- [ ] `set_badge_count(link_doctype, open_count, count)` — перекрити лічильник
      чипа в `DocConnections` (для нестандартних підрахунків).
- [ ] `show()` / `hide()` / `reset()`; `add_comment(text, alert_class, permanent)` —
      тимчасове alert-повідомлення (скидається на refresh, якщо не `permanent`).
- [ ] Типи в `FormProxy` + приклади в JSDoc; розділ у skill `grunt-dev` (Client Scripts).

### Що потрібно: декларативний (серверний) бік
- [ ] **Internal links** — зв'язки «вперед» з табличної частини цього документа
      (напр. Рахунок → Замовлення через `items.sales_order`). Новий режим у
      `DocTypeLink` (`direction: "internal"`, `table_fieldname` + `link_fieldname` на
      дочірньому типі) і гілка в `connections.py`; зараз сервіс уміє лише backlinks.
- [ ] **Open count** — другий лічильник «відкритих» (не submitted/не закритих)
      документів у чипі, як у Frappe (`open_count / count`). Умова — через
      `status_field` пов'язаного DocType або фільтр у `DocTypeLink.open_filters`.
- [ ] **Heatmap активності** — `DocType.dashboard_heatmap: bool` (+ `heatmap_message`):
      кількість подій ActivityLog по днях за рік для документа; endpoint у
      `connections.py`, рендер тим самим Heatmap-віджетом.
- [ ] **Python-хук `get_dashboard_data(doc)`** у контролері — повертає
      indicators/progress/headline з сервера (для логіки, якої не порахувати на клієнті);
      `FormDashboard.vue` мерджить їх зі станом `frm.dashboard`.
- [ ] Тести: `tests/test_connections.py` (internal links, open_count, heatmap),
      vitest для `frm.dashboard` (стан + reset на refresh).

---

## 9. Background Jobs UI
Перегляд черги завдань, статусів, логів, retry — прямо з desk.

---

## 10. Patch System (міграції даних)
Окрім Alembic-міграцій схеми — система одноразових скриптів
для міграції даних між версіями.
