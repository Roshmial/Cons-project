# Hermes Web MVP — пакет документации

## 1. Краткий вывод

Текущий MVP приведён к рабочей схеме с раздельными сервисами:
- frontend;
- backend API;
- Hermes API Server как внутренний агентный downstream.

Главное изменение этой итерации: backend больше не работает в mock-режиме по умолчанию, а подключён к реальному Hermes API Server.

## 2. Текущая архитектура

Подробная версия находится в файле `ARCHITECTURE.md`.

Коротко:
- frontend знает только backend API;
- backend владеет аккаунтами, сессиями, чатами, feedback и персонализацией;
- Hermes вызывается из backend через OpenAI-совместимый API;
- пользовательский контекст формируется приложением, а не общей памятью Hermes.

Канонический контур:
`Browser -> Frontend -> Backend API -> Hermes API Server`

## 3. Что обновлено в реализации

В коде закреплено следующее:
- включён Hermes API Server в gateway;
- backend подключён к `http://127.0.0.1:8642/v1`;
- backend использует bearer key для доступа к Hermes API Server;
- в meta assistant messages фиксируются `mode`, `downstream`, `hermes_model`, `usage` и personalization preview;
- `run_backend_service.sh` по умолчанию запускает backend в режиме `hermes-api`.

## 4. Инструкция по работе с frontend

Полная инструкция находится в `docs/FRONTEND_GUIDE.md`.

Короткая версия:
- открыть `http://127.0.0.1:8793`;
- войти под demo-учёткой;
- использовать список чатов, экран диалога и профиль;
- для admin доступны health, users, threads, events.

Demo-учётки:
- `misha@demo.local / demo123`
- `admin@demo.local / demo123`

## 5. Инструкция по развёртыванию backend и frontend

Полная инструкция находится в `docs/DEPLOYMENT_GUIDE.md`.

Короткая версия:
1. убедиться, что Hermes gateway работает;
2. убедиться, что включён API Server;
3. запустить backend: `./run_backend_service.sh`;
4. запустить frontend: `./run_frontend_service.sh`;
5. открыть frontend в браузере.

Локальные адреса:
- frontend: `http://127.0.0.1:8793`
- backend: `http://127.0.0.1:8791`
- Hermes API Server: `http://127.0.0.1:8642/v1`

## 6. Сценарий тестирования

Полная версия находится в `docs/TESTING_SCENARIO.md`.

Обязательный приёмочный минимум:
- login/logout;
- session restore;
- профиль пользователя;
- create/rename/archive thread;
- отправка сообщения;
- реальный assistant reply через Hermes API Server;
- feedback;
- admin health/users/threads/events.

Критерий успеха по интеграции:
- assistant response должен приходить с `mode=hermes-api`;
- assistant response должен приходить с `downstream=hermes-api-server`.

## 7. Что важно зафиксировать

Факты:
- локальный Hermes API Server поднят и отвечает;
- backend подключён к нему реально;
- frontend и backend разнесены по сервисам;
- архитектурная документация приведена к актуальному состоянию MVP.

Интерпретация:
- MVP теперь отражает правильную прикладную границу между веб-контуром и Hermes runtime;
- следующий шаг — не переписывать контур, а усиливать эксплуатационную часть.

Рекомендуемое дальнейшее развитие:
- reverse proxy;
- PostgreSQL вместо SQLite;
- бэкапы и мониторинг;
- отдельный Hermes profile для web runtime при необходимости.
