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

---

## 9. Background Jobs UI
Перегляд черги завдань, статусів, логів, retry — прямо з desk.

---

## 10. Patch System (міграції даних)
Окрім Alembic-міграцій схеми — система одноразових скриптів
для міграції даних між версіями.
