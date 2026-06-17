# Deploy package for Hermes Web MVP

## Что это

Этот каталог — эксплуатационный пакет для переноса Hermes Web MVP на другой Linux-сервер.

Он не содержит секретов. Все чувствительные значения должны задаваться отдельно через `~/.hermes/.env` или локальные переменные окружения.

## Состав

- `env/hermes-web.env.example` — пример переменных окружения, включая параметризованный runtime и переменные для browser acceptance;
- `dependency-inventory.md` — перечень библиотек и runtime-зависимостей;
- `HERMES_ZERO_SERVER_CHECKLIST.md` — пошаговый сценарий для нового пустого Hermes-сервера;
- `bootstrap-hermes-zero-server.sh` — первичная подготовка нового сервера с Hermes;
- `install-project-deps.sh` — установка Node/Python зависимостей проекта;
- `systemd/hermes-web-backend-8791.service` — user unit backend;
- `systemd/hermes-web-frontend-8793.service` — user unit frontend;
- `systemd/hermes-web-copilotkit-8794.service` — user unit CopilotKit runtime;
- `install-systemd-user.sh` — установка unit-файлов для текущего пользователя;
- `verify-deployment.sh` — быстрая проверка поднятого контура, а при наличии acceptance-учётки ещё и UI smoke;
- `../scripts/runtime_env.sh` и `../scripts/browser_runtime_env.sh` из корня проекта используются как канонический runtime-env для acceptance-проверок.

## Как использовать

1. Скопировать проект на новый сервер.
2. Настроить `~/.hermes/.env` по примеру `env/hermes-web.env.example`.
3. Запустить `install-systemd-user.sh /абсолютный/путь/к/проекту`.
4. Выполнить `./deploy/package/verify-deployment.sh`.
5. После этого пройти пользовательский сценарий из `docs/TESTING_SCENARIO.md`.

## Что важно

- unit-файлы рассчитаны на user-level systemd;
- backend, frontend и CopilotKit runtime должны относиться к одному и тому же project root;
- нельзя смешивать frontend из одного каталога, а backend из другого — это уже приводило к ложной верификации.
