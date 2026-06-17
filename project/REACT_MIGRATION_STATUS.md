# React migration status

## Что уже сделано
- Каноническое дерево для текущего React/CopilotKit-контура: `/home/hermes/workspace/hermes-web-mvp-react-8793`.
- Поднят отдельный React/Vite frontend-контур в `services/frontend-react`.
- Канонический live frontend-порт этого контура: `8793`.
- React frontend работает через текущий backend `8791` по proxy `/api`.
- Для agent/runtime сценариев используется локальный sidecar `8794`, но пользовательский вход остаётся через frontend/backend контур.
- В React-контур уже перенесены основные экраны:
  - Чаты
  - Профиль
  - Задачи
  - Управление
- Поддержаны базовые рабочие действия:
  - login/logout
  - список чатов и открытие чата
  - создание чата
  - отправка сообщения
  - загрузка новых файлов
  - повторное использование файлов из профиля
  - rename/archive чата
  - редактирование профиля
  - смена пароля
  - просмотр задач
  - запуск задачи
  - подписка/отписка
  - сохранение общего названия задачи
  - admin overview
  - admin users/threads/jobs/reference read
  - обновление chat notice
  - dashboard routing с local/global policy через backend

## Что подтверждено live
- `npm run react:build` -> OK
- React frontend доступен по `http://127.0.0.1:8793/`
- backend этого контура отвечает по `http://127.0.0.1:8791/`
- login успешен
- chat shell открывается и показывает сообщения
- profile screen открывается и показывает блоки `Основные данные`, `Краткое резюме профиля`, `Смена пароля`, `Мои файлы`
- jobs screen открывается и показывает `Список задач` + `Детали задачи`
- admin screen открывается и показывает `Пользователи`, `Чаты`, `Задачи в админском обзоре`, `Объявление в чате`, `Справочники`
- admin policy/sources block live подтверждён: экран загружает 5 верхнеуровневых источников и 6 дочерних коннекторов
- admin policy save/reload/read round-trip live подтверждён: через UI режим был переключён `global_only -> local_only`, backend вернул `PATCH 200`, повторное чтение подтвердило новое значение, затем состояние успешно восстановлено обратно
- browser console JS errors не зафиксированы в live runtime
- dashboard policy backend smoke проходит; `local_first` сам уводит общий запрос во внешний маршрут, а при неуточнённом локальном запросе чат предлагает и локальный, и внешний вариант
- policy routing подтверждён по backend-контракту:
  - `local_only` оставляет только локальные/internal источники
  - `global_only` оставляет только external/global источники
  - `local_first` разрешает оба слоя с локальным приоритетом
- canonical inventory для dashboard больше не сводится к одному Telegram digest и включает:
  - top-level: `user_attachment_dataset`, `local_dataset_registry`, `internal_connector`, `external_connector`, `web_research`
  - internal connectors: `hermes_api`, `copilotkit_runtime`, `telegram_analytics_workspace`
  - external connectors: `telegram_api`, `google_api`, `public_procurement_api`
- runtime устойчивее к кратким DuckDB lock-конфликтам: `GET /api/setup/status` больше не валит весь frontend, а auth-path ретраит краткие `duckdb` конфликты вместо случайных `500`

## Как запускать
Из каталога `/home/hermes/workspace/hermes-web-mvp-react-8793`:

```bash
./run_frontend_react_service.sh
```

или

```bash
npm run react:dev
```

Для полного канонического контура см. `RUNTIME-RUNBOOK.md`: frontend `8793`, backend `8791`, sidecar `8794`.

## Что ещё не доведено до полного parity с legacy frontend
Это уже рабочий React runtime baseline, но ещё не 100% feature parity. Остались как минимум:
- полный admin create/edit/bulk actions contour
- полный jobs create/edit modal contour
- часть мелких frontend polish/detail flows из legacy `app.js`
- отдельная каноническая React smoke-приёмка по всем сценариям

## Практический смысл текущего состояния
React migration уже можно продолжать как реальную рабочую ветку внутри канонического контура `8793/8791/8794`, не смешивая её с legacy `8790/8788` и старым промежуточным React `8792`. Но честно считать её полным завершением шага 2 пока рано: это сильная рабочая база с основными экранами и policy-routing, а не финальный feature-complete replacement.
