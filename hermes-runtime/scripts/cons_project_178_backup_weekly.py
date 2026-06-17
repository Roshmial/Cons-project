from pathlib import Path
import shutil
import subprocess
from datetime import datetime, timezone

PROJECT = Path('/home/hermes/workspace/hermes-web-mvp-react-8793')
TG_API = Path('/home/hermes/workspace/TG-API')
BACKUP = Path('/home/hermes/workspace/cons-github-backup-178')
SYSTEMD_USER = Path('/home/hermes/.config/systemd/user')
HERMES_HOME = Path('/home/hermes/.hermes')
BRANCH = 'standalone-178'
REMOTE_URL = 'git@github.com:Roshmial/Cons-project.git'

PROJECT_ROOT_FILES = [
    'README.md', 'RUNTIME-RUNBOOK.md', 'REACT_MIGRATION_STATUS.md', 'package.json', 'package-lock.json',
    'vite.config.js', 'docker-compose.yml', 'run_backend_service.sh', 'run_frontend_react_service.sh',
    'run_frontend_service.sh', 'run_copilotkit_runtime_service.sh'
]
PROJECT_DIRS = ['services', 'deploy/package', 'scripts', 'docs']
EXCLUDE_DIR_NAMES = {'node_modules', '.venv', '__pycache__', '.pytest_cache', '.mypy_cache', '.ruff_cache', '.cache', 'dist', '.git'}
EXCLUDE_FILE_SUFFIXES = {'.pyc', '.pyo', '.log', '.sqlite', '.sqlite3', '.duckdb', '.db', '.wal', '.shm', '.tgz'}
EXCLUDE_FILE_NAMES = {'.env', '.env.local', '.env.production', '.env.development'}
SYSTEMD_FILES = [
    'hermes-web-backend-8791.service', 'hermes-web-backend-8791-public.service',
    'hermes-web-frontend-8793.service', 'hermes-web-copilotkit-8794.service', 'tg-api.service', 'hermes-gateway.service'
]
SYSTEMD_DROPINS = [('hermes-web-backend-8791.service.d', 'public-bind.conf'), ('hermes-web-backend-8791.service.d', 'timeout.conf')]
TG_API_EXCLUDE_DIR_NAMES = {
    'node_modules', '.venv', '__pycache__', '.pytest_cache', '.mypy_cache', '.ruff_cache', '.cache', '.git',
    'session', 'runtime', 'raw_logs', 'archive', 'exports', 'reports', 'analytics'
}
TG_API_EXCLUDE_FILE_SUFFIXES = {'.pyc', '.pyo', '.log', '.sqlite', '.sqlite3', '.duckdb', '.db', '.wal', '.shm', '.session', '.jsonl', '.html'}
TG_API_EXCLUDE_FILE_NAMES = {
    '.env', 'private-profile.env', 'auth_link_state.json', 'api_server.log',
    '.tg-monitor-profile-name', '.tg-monitor-config-name', '.tg-monitor-instance-id',
    'tg-since-id-it_consulting.json'
}
TG_API_EXCLUDE_PREFIXES = ('telegram_channel_analytics_', 'history-')
HERMES_SCRIPT_EXCLUDE_SUFFIXES = {'.pyc', '.pyo', '.log'}


def run(cmd, *, check=True, capture_output=True, text=True):
    return subprocess.run(cmd, check=check, capture_output=capture_output, text=text)


def ensure_repo() -> None:
    BACKUP.mkdir(parents=True, exist_ok=True)
    if not (BACKUP / '.git').exists():
        run(['git', 'init', '-b', BRANCH, str(BACKUP)])
    remote = subprocess.run(['git', '-C', str(BACKUP), 'remote', 'get-url', 'origin'], capture_output=True, text=True)
    if remote.returncode != 0:
        run(['git', '-C', str(BACKUP), 'remote', 'add', 'origin', REMOTE_URL])


def reset_tree() -> None:
    for name in ['project', 'tg-api', 'runtime-systemd', 'hermes-runtime']:
        target = BACKUP / name
        if target.exists():
            shutil.rmtree(target)
        target.mkdir(parents=True, exist_ok=True)


def should_keep_project(rel: Path) -> bool:
    if any(part in EXCLUDE_DIR_NAMES for part in rel.parts):
        return False
    if rel.name in EXCLUDE_FILE_NAMES:
        return False
    if any(rel.name.endswith(s) for s in EXCLUDE_FILE_SUFFIXES):
        return False
    norm = '/' + '/'.join(rel.parts) + '/'
    if '/services/backend/data/' in norm:
        return False
    return True


def should_keep_tg_api(rel: Path) -> bool:
    if any(part in TG_API_EXCLUDE_DIR_NAMES for part in rel.parts):
        return False
    if rel.name in TG_API_EXCLUDE_FILE_NAMES:
        return False
    if rel.name.startswith(TG_API_EXCLUDE_PREFIXES):
        return False
    if any(rel.name.endswith(s) for s in TG_API_EXCLUDE_FILE_SUFFIXES):
        return False
    return True


def copy_project() -> None:
    target_root = BACKUP / 'project'
    for rel_name in PROJECT_ROOT_FILES:
        src = PROJECT / rel_name
        rel = Path(rel_name)
        if src.exists() and src.is_file() and should_keep_project(rel):
            dst = target_root / rel_name
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
    for rel_name in PROJECT_DIRS:
        base = PROJECT / rel_name
        if not base.exists():
            continue
        for src in base.rglob('*'):
            if src.is_dir():
                continue
            rel = src.relative_to(PROJECT)
            if not should_keep_project(rel):
                continue
            dst = target_root / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)


def copy_tg_api() -> None:
    if not TG_API.exists():
        return
    target_root = BACKUP / 'tg-api'
    for src in TG_API.rglob('*'):
        if src.is_dir():
            continue
        rel = src.relative_to(TG_API)
        if not should_keep_tg_api(rel):
            continue
        dst = target_root / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)


def copy_runtime_systemd() -> None:
    target = BACKUP / 'runtime-systemd'
    for name in SYSTEMD_FILES:
        src = SYSTEMD_USER / name
        if src.exists():
            shutil.copy2(src, target / name)
    for dirname, filename in SYSTEMD_DROPINS:
        src = SYSTEMD_USER / dirname / filename
        if src.exists():
            dst = target / dirname / filename
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)


def copy_hermes_runtime() -> None:
    target = BACKUP / 'hermes-runtime'
    for rel_name in ['config.yaml', 'cron/jobs.json']:
        src = HERMES_HOME / rel_name
        if src.exists():
            dst = target / rel_name
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
    scripts_src = HERMES_HOME / 'scripts'
    if scripts_src.exists():
        for src in scripts_src.rglob('*'):
            if src.is_dir():
                continue
            if any(src.name.endswith(s) for s in HERMES_SCRIPT_EXCLUDE_SUFFIXES):
                continue
            rel = src.relative_to(scripts_src)
            dst = target / 'scripts' / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)


def write_docs() -> None:
    timestamp = datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')
    (BACKUP / 'README.md').write_text(
        '# Cons project backup — standalone 178\n\n'
        'Это standalone curated backup рабочего контура на 178.104.207.89: backend/runtime, frontend 8793, CopilotKit 8794, TG-API, Hermes runtime и deploy-артефакты.\n\n'
        'Что включено:\n'
        '- `project/**` — код проекта `hermes-web-mvp-react-8793` с deploy/package, docs и scripts\n'
        '- `tg-api/**` — operational код и конфигурация TG API без runtime/state/secrets\n'
        '- `runtime-systemd/**` — user-level unit и drop-in файлы текущего live-контура\n'
        '- `hermes-runtime/**` — `config.yaml`, `cron/jobs.json`, `scripts/*`\n'
        '- root-docs по архитектуре, логике, zero-start развёртке и model fallback\n\n'
        'Что исключено:\n'
        '- `.env*`, токены, auth/session state, runtime DB\n'
        '- `services/backend/data/`, `node_modules/`, `.venv/`, build caches, logs\n'
        '- TG API `session/`, `runtime/`, `raw_logs/`, `exports/`, `reports/`, `analytics/`\n\n'
        'Назначение:\n'
        '- полноценный backup под ключ именно для standalone-контура 178\n'
        '- безопасная публикация в `Cons-project` на отдельной ветке без перезаписи combined backup с 95\n\n'
        f'Последнее обновление: {timestamp}\n', encoding='utf-8')
    (BACKUP / '.gitignore').write_text('.DS_Store\n*.pyc\n__pycache__/\n*.log\n.env\n', encoding='utf-8')
    (BACKUP / 'BACKUP_SCOPE.md').write_text(
        '# Backup scope\n\n'
        '- `project/**` — live project snapshot 178 без data/secrets/runtime мусора\n'
        '- `tg-api/**` — curated TG API snapshot 178 без state/runtime artifacts\n'
        '- `runtime-systemd/**` — systemd user units и drop-ins\n'
        '- `hermes-runtime/**` — локальный Hermes runtime layer\n\n'
        'Excluded:\n'
        '- `.env*`, auth/session state, logs, DB, caches, generated exports/analytics\n', encoding='utf-8')
    (BACKUP / 'CONTOUR_MAP.md').write_text(
        '# Contour map\n\n'
        '## Основные runtime-компоненты на 178\n\n'
        '- `8791` — backend API и основная бизнес-логика Hermes Web.\n'
        '- `8793` — frontend runtime на том же хосте.\n'
        '- `8794` — CopilotKit runtime.\n'
        '- `tg-api.service` — отдельный Telegram API / monitoring contour.\n'
        '- `hermes-gateway.service` — messaging gateway Hermes.\n\n'
        '## Логика хранения\n\n'
        '- Это standalone backup одного хоста, в отличие от combined backup 95+178.\n'
        '- Он нужен, когда требуется поднять именно сервер 178 как самодостаточный runtime-contour со всеми локальными артефактами, кроме secrets/state.\n', encoding='utf-8')
    (BACKUP / 'DEPLOYMENT_AND_BACKUP_LOGIC.md').write_text(
        '# Deployment and backup logic\n\n'
        '## Что входит в контур\n\n'
        '- Web project: backend, frontend, CopilotKit, deploy package, docs, scripts.\n'
        '- TG API contour как отдельный operational слой на том же сервере.\n'
        '- Hermes runtime layer: config, jobs, scripts, gateway/runtime units.\n\n'
        '## Почему ветка отдельная\n\n'
        '- Combined backup на 95 и standalone backup 178 решают разные задачи.\n'
        '- Поэтому standalone 178 публикуется в тот же GitHub repo, но в отдельную ветку `standalone-178`, чтобы не ломать `main`.\n\n'
        '## Что делает weekly refresh\n\n'
        '1. Пересобирает curated snapshot `project/`, `tg-api/`, `runtime-systemd/`, `hermes-runtime/`.\n'
        '2. Перегенерирует описательные документы.\n'
        '3. Делает commit и push в ветку `standalone-178`.\n', encoding='utf-8')
    (BACKUP / 'PROD_CONTOUR_ARCHITECTURE.md').write_text(
        '# Production contour architecture\n\n'
        '```\n'
        'Browser / user\n'
        '    |\n'
        '    v\n'
        '178:8793  (frontend runtime)\n'
        '    |\n'
        '    v\n'
        '178:8791  (backend API / chat / jobs / dashboard)\n'
        '    |\\\n'
        '    | +--> 178:8794 (CopilotKit runtime)\n'
        '    |\n'
        '    +--> local Hermes runtime / jobs / scripts\n'
        '\n'
        '178: TG-API\n'
        '    |\n'
        '    +--> Telegram monitoring / auth helper / digest contour\n'
        '```\n\n'
        '- Это single-host prod contour, где все runtime-компоненты живут на одной машине 178.\n'
        '- TG-API логически отдельный operational слой, но физически расположен на том же сервере и поэтому входит в backup.\n', encoding='utf-8')
    (BACKUP / 'PROD_CONTOUR_LOGIC.md').write_text(
        '# Production contour logic\n\n'
        '1. Пользователь приходит во frontend `8793`.\n'
        '2. Frontend обращается к backend `8791`.\n'
        '3. Backend обслуживает chat, jobs, dashboard и смежные runtime-пайплайны.\n'
        '4. CopilotKit runtime `8794` используется как дополнительный слой там, где он нужен.\n'
        '5. TG-API параллельно обслуживает Telegram auth/monitoring/digest сценарии.\n'
        '6. Hermes runtime layer управляет jobs/scripts/gateway поверх этого же хоста.\n', encoding='utf-8')
    (BACKUP / 'DISASTER_RECOVERY_RUNBOOK.md').write_text(
        '# Zero-start deployment runbook\n\n'
        'Это runbook для развёртки standalone-контура 178 с нуля на чистом Linux-сервере.\n\n'
        '## Минимальная шпаргалка по командам\n\n'
        '```bash\n'
        'git clone --branch standalone-178 git@github.com:Roshmial/Cons-project.git ~/cons-project-178\n'
        'cd ~/cons-project-178/project\n'
        'cp deploy/package/env/hermes-web.env.example ~/.hermes/.env   # как шаблон, затем заполнить вручную\n'
        'bash deploy/package/bootstrap-hermes-zero-server.sh\n'
        'bash deploy/package/install-project-deps.sh\n'
        'bash deploy/package/install-systemd-user.sh $(pwd)\n'
        'systemctl --user daemon-reload\n'
        'systemctl --user enable --now hermes-web-backend-8791.service\n'
        'systemctl --user enable --now hermes-web-frontend-8793.service\n'
        'systemctl --user enable --now hermes-web-copilotkit-8794.service\n'
        'bash deploy/package/verify-deployment.sh\n'
        '```\n\n'
        '## TG-API\n\n'
        '1. Развернуть каталог `tg-api/` в отдельный рабочий путь.\n'
        '2. Внести вручную `private-profile.env`, session-файлы и auth state.\n'
        '3. Проверить ручной запуск.\n'
        '4. Только потом активировать `tg-api.service` и связанные cron/jobs.\n\n'
        '## Hermes layer\n\n'
        '1. Установить Hermes: `curl -fsSL https://hermes-agent.nousresearch.com/install.sh | bash`.\n'
        '2. Восстановить `hermes-runtime/config.yaml`, `hermes-runtime/cron/jobs.json`, `hermes-runtime/scripts/*` при необходимости.\n'
        '3. Не переносить secrets/state автоматически; их нужно заполнить локально.\n'
        '4. Проверить `hermes doctor` и `hermes cron list`.\n\n'
        '## Проверка\n\n'
        '- backend `8791` отвечает\n'
        '- frontend `8793` открывается\n'
        '- CopilotKit `8794` жив\n'
        '- TG-API запускается\n'
        '- gateway/jobs не падают после включения\n', encoding='utf-8')
    (BACKUP / 'MODEL_FALLBACK_LOGIC.md').write_text(
        '# Model fallback logic\n\n'
        '## Зафиксированная конфигурация на 178\n\n'
        '- Primary provider: `openrouter`\n'
        '- Primary model: `google/gemma-4-31b-it:free`\n'
        '- В текущем `config.yaml` явная цепочка `model.fallback_models` не зафиксирована.\n'
        '- Значит для standalone 178 primary-route считается единственным подтверждённым маршрутом, пока fallback-цепочка не описана явно.\n\n'
        '## Практический вывод\n\n'
        '- Для развёртки с нуля нужно гарантировать рабочий primary route `openrouter` + `google/gemma-4-31b-it:free`.\n'
        '- Если позже будет добавлена явная fallback-цепочка, её надо фиксировать здесь и в `config.yaml` одновременно.\n'
        '- Auxiliary/local inference route в текущем подтверждённом конфиге 178 не зафиксирован, поэтому считать его обязательным по умолчанию нельзя.\n', encoding='utf-8')
    (BACKUP / 'TG_API_SCOPE.md').write_text(
        '# TG API scope\n\n'
        '## Что включено\n\n'
        '- основной Python-код и pipeline-скрипты\n'
        '- auth/web helpers\n'
        '- channel config, requirements, install/service scripts, docs\n\n'
        '## Что исключено\n\n'
        '- `session/`, `runtime/`, `raw_logs/`, `exports/`, `reports/`, `analytics/`\n'
        '- `private-profile.env`, auth/state files и generated outputs\n', encoding='utf-8')
    (BACKUP / 'HERMES_RUNTIME_SCOPE.md').write_text(
        '# Hermes runtime scope\n\n'
        '- `hermes-runtime/config.yaml` — текущая конфигурация профиля\n'
        '- `hermes-runtime/cron/jobs.json` — определения cron jobs\n'
        '- `hermes-runtime/scripts/*` — локальные automation scripts\n\n'
        'Не входят:\n'
        '- `.env`, `auth.json`, session DB, logs, runtime outputs\n', encoding='utf-8')


def git(*args: str) -> str:
    return run(['git', '-C', str(BACKUP), *args]).stdout.strip()


def commit_and_push() -> str:
    status = git('status', '--short')
    if not status:
        return 'cons-github-backup-178: изменений нет, push не требуется'
    git('add', '.')
    run(['git', '-C', str(BACKUP), '-c', 'user.name=Cons Backup 178', '-c', 'user.email=cons-backup-178@local', 'commit', '-m', 'Weekly standalone 178 backup refresh'])
    branch = subprocess.run(['git', '-C', str(BACKUP), 'branch', '--show-current'], capture_output=True, text=True, check=True).stdout.strip()
    if branch != BRANCH:
        run(['git', '-C', str(BACKUP), 'checkout', '-B', BRANCH])
    push = subprocess.run(['git', '-C', str(BACKUP), 'push', '-u', 'origin', BRANCH], capture_output=True, text=True)
    head = git('log', '--oneline', '-1')
    if push.returncode != 0:
        return f'cons-github-backup-178: commit создан, но push не прошёл\n{head}\n{(push.stderr or push.stdout).strip()}'
    return f'cons-github-backup-178: обновлено и отправлено в origin/{BRANCH}\n{head}'


def main() -> None:
    ensure_repo()
    current = subprocess.run(['git', '-C', str(BACKUP), 'branch', '--show-current'], capture_output=True, text=True)
    if current.returncode == 0 and current.stdout.strip() != BRANCH:
        subprocess.run(['git', '-C', str(BACKUP), 'checkout', '-B', BRANCH], check=True, capture_output=True, text=True)
    reset_tree()
    copy_project()
    copy_tg_api()
    copy_runtime_systemd()
    copy_hermes_runtime()
    write_docs()
    print(commit_and_push())


if __name__ == '__main__':
    main()
