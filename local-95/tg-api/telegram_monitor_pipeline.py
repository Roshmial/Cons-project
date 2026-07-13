import csv
import json
import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple
from urllib.parse import urlparse

import yaml

from tg_instance_paths import (
    BASE_DIR,
    CACHE_DOCS_DIR,
    POINTER_PATH,
    RAW_LOGS_DIR,
    REPORTS_DIR,
    ensure_runtime_dirs,
)

MSK = timezone(timedelta(hours=3))

FIXED_TYPES: Sequence[str] = (
    "исследование",
    "мероприятие",
    "кейс",
    "партнерство",
    "продукт/решение",
    "реклама услуг",
    "корпоративная новость",
    "интервью/комментарий",
    "вакансия",
    "обзор рынка",
    "аналитика",
    "требует уточнения",
)

TYPE_WEIGHTS = {
    "исследование": 9.0,
    "кейс": 8.5,
    "аналитика": 8.0,
    "продукт/решение": 7.8,
    "реклама услуг": 6.9,
    "партнерство": 7.4,
    "мероприятие": 6.6,
    "интервью/комментарий": 6.2,
    "корпоративная новость": 5.8,
    "обзор рынка": 7.4,
    "вакансия": 4.5,
    "требует уточнения": 3.5,
}

TYPE_RULES: Dict[str, Sequence[str]] = {
    "исследование": (
        r"\bисследован", r"\bопрос", r"\bbenchmark", r"\bбенчмарк",
        r"\bреспондент", r"\bвыводы", r"\bотчет", r"\bwhite paper",
        r"\bскачайт[еь].*исследован", r"\bрезультат[ыов].*опрос", r"\bданные исследования",
        r"\bhrd\b", r"\bdex\b", r"employee experience", r"\bex\b",
    ),
    "мероприятие": (
        r"\bвебинар", r"\bконференц", r"\bсаммит", r"\bфорум", r"\bэфир",
        r"\bвыступит", r"\bрегистрац", r"\bдата[:\s]", r"\bмероприят",
        r"\bтрансляц", r"\bпрям[ао]й эфир", r"\bподключайт",
        r"\bсесси", r"\bзаседани", r"\bонлайн\b", r"\bпрямое включение",
        r"\bприглашаем вас на вебинар", r"\bвыступил на", r"\bдоклад",
        r"\bпровел[аи]? программу повышения квалификации", r"\bлекции были посвящены",
        r"\bна международной премии", r"\bна форуме", r"\bподкаст",
        r"\bконкурс", r"\bприем[а]? заявок", r"\bучастия в .* конкурсе",
        r"\bкругл[ао]м стол[еа]", r"\bсобрал[аи]? в узком кругу", r"\bвечер с лидерами",
    ),
    "кейс": (
        r"\bкейс", r"\bвнедр", r"\bреализ", r"\bавтоматизац",
        r"\bдля клиента", r"\bзапущено", r"\bмикросервис", r"\bинтеграц",
        r"\bкейс коллег", r"\bперевели .* на отечественн",
        r"\bпомогла реализовать", r"\bзавершили первый этап", r"\bобновления ит-инфраструктуры банка",
    ),
    "партнерство": (
        r"\bпартнерств", r"\bсотрудничеств", r"\bподписанн?ые соглашени",
        r"\bсовместно с", r"\bобъявили о начале сотрудничества",
        r"\bофициально объявили о начале", r"\bразвитии сотрудничества",
        r"\bстратегическ[а-я ]*партнерств", r"\bбизнес-партнер", r"\bполучил статус бизнес-партнера",
        r"\bзаключили соглашение", r"\bподписали соглашение", r"\bкупил[аи]? \d+%",
    ),
    "продукт/решение": (
        r"\bплатформ", r"\bрешени", r"\bсервис", r"\bпродукт", r"\bсистема",
        r"\bфункционал", r"\bмодуль", r"\bрелиз", r"\bзапуск сервиса",
        r"\bпо подписке", r"\bготовую среду", r"\bпредустановлен[ыо]",
        r"\bтест-драйв", r"\bдемо-верси", r"\bon-premise", r"\bшлюз безопасности",
        r"\bgenerator\b", r"\bносимое устройство", r"\bзапустил в продажу",
    ),
    "реклама услуг": (
        r"\bмы можем помочь", r"\bобращайтесь к (нам|специалистам)",
        r"\bобратитесь к (нам|специалистам)", r"\bсвяжитесь с нами",
        r"\bоставьте заявку", r"\bнаши специалисты помогут",
        r"\bпоможем (внедрить|реализовать|запустить|автоматизировать|настроить)",
        r"\bузнайте больше об экспертизе", r"\bготовы помочь",
        r"\bобсудить ваш проект", r"\bза консультацией", r"\bзакажите консультацию",
        r"\bузнать больше об услугах", r"\bэкспертные консультации",
        r"\bполучить консультацию", r"\bобсудим задачи бизнеса",
    ),
    "корпоративная новость": (
        r"\bсовет директор", r"\bдивиденд", r"\bрейтинг", r"\braex",
        r"\bгодовой отчет", r"\bвыручк", r"\bфинансов", r"\bназначен",
        r"\bпоздравля[ею]т", r"\bс праздником", r"\bфотоотчет", r"\bнаграждени",
        r"\bдети наших сотрудников", r"\bакадеми[яи] бизнеса",
        r"\bс днем российского предпринимательства",
        r"\bвсе самое важное за", r"\bтрадиционный дайджест новостей", r"_дайджест",
        r"\bпобедител", r"\bпреми[яие]\b", r"\bторжественн[а-я ]*церемони",
        r"\bвключен[аоы]? в перечень", r"\bполучил статус", r"\bзаняв ведущие позиции",
        r"\bмассово увольняет", r"\bуволил руководителей", r"\bуволилась вся команда",
        r"\bпризнан банкротом", r"\bушел из жизни", r"\bс днем эколога",
    ),
    "интервью/комментарий": (
        r"\bинтервью", r"\bпрокомментир", r"\bкомментир", r"\bрассказал",
        r"\bподелился мнением", r"\bэксперт .* отметил",
        r"\bобсудил[аи]? с", r"\bв комментарии", r"\bв сми", r"\bкомментируют новости",
        r"\bполное интервью", r"\bблиц-опрос", r"\bэксперт выделяет", r"\bсчитает, что",
        r"— о работе с заказчиками", r"\bэксперт отмечает",
        r"\bдиректор по развитию бизнеса .* — о работе с заказчиками",
        r"\bэксперт выделяет три отраслевые особенности",
        r"\bоб этом рассказал", r"\bпо его словам", r"\bэксперт подчеркнул",
        r"\bрассказал, как", r"\bделится впечатлениями от участия",
        r"\bтезисы сессии", r"\bключевые тезисы", r"\bпоговорим мы об",
    ),
    "вакансия": (
        r"\bваканси", r"\bищем", r"\bприсоединяйся к команде", r"\bjob",
        r"\bhh\.ru", r"\bоткрыта позиция", r"\bстажировк", r"\bрезюме",
        r"\bрекрутер", r"\bоффер", r"\bтестовое задание",
    ),
    "обзор рынка": (
        r"\bрынок", r"\bотрасл", r"\bландшафт", r"\bтренд", r"\bперспектив",
        r"\bm&a", r"\bслияни", r"\bпоглощени",
        r"\bобзор новостей", r"\bдайджест новостей", r"\bиндустриальн[ыо]й дайджест",
        r"\bеженедельн[ыо]м индустриальн[ыо]м дайджесте",
        r"\bаналитика и тренды ит-рынка", r"\bежемесячн[ыо]й обзор новостей",
        r"\bэти и другие новости в выпуске", r"\bглавное за месяц", r"\bглавные новости за месяц",
        r"\bустановил[ао]? правила", r"\bутвердило правила", r"\bпринял стандарт",
        r"\bготовится оценивать", r"\bопубликованы эксплойты", r"\bизменения законодательства",
        r"\bкибербезопасност[ьи].*оператор", r"\bудостоверяющий центр", r"\bдля работы с долгами по налогам",
        r"\bчто это значит для представителей бизнеса", r"\bглавный акционер", r"\bвозглавил компанию",
    ),
    "аналитика": (
        r"\bразбор", r"\bаналитик", r"\bобъясняем", r"\bпочему", r"\bчто происходит",
        r"\bкомментарий", r"\bбарьер", r"\bподход", r"\bриски",
        r"\bосновные причины", r"\bостается одним из самых сложных", r"\bоценила соответствие",
        r"\bчто мешает", r"\bпо данным", r"\bпадает более чем",
        r"\bнесколько инсайдов", r"\bэкономической эффективности", r"\bчистую прибыль",
        r"\bконец эпохи", r"\bчто сегодня .* ждет", r"\bбарьеры и пути роста",
        r"\bновая рациональность покупателей", r"\bрациональность покупателей", r"\bглавный результат трех лет",
        r"\bобзор tadviser", r"\bоб опыте\b", r"\bкак импортозаместить\b",
    ),
}

CHANNEL_HINTS: Dict[str, float] = {}

MANUAL_TYPE_OVERRIDES: Dict[str, str] = {
    "https://t.me/Axenix_Ru/3233": "мероприятие",
    "https://t.me/kept_business/3323": "корпоративная новость",
    "https://t.me/Softline/3299": "обзор рынка",
    "https://t.me/Lanit_life/3763": "корпоративная новость",
    "https://t.me/kept_business/3330": "исследование",
    "https://t.me/norbit_ru/784": "кейс",
    "https://t.me/tadviser/5878": "корпоративная новость",
    "https://t.me/tadviser/5877": "продукт/решение",
    "https://t.me/tadviser/5876": "аналитика",
    "https://t.me/tadviser/5874": "обзор рынка",
    "https://t.me/tadviser/5873": "кейс",
    "https://t.me/tadviser/5871": "кейс",
    "https://t.me/tadviser/5868": "корпоративная новость",
    "https://t.me/tadviser/5867": "кейс",
    "https://t.me/tadviser/5866": "корпоративная новость",
    "https://t.me/tadviser/5862": "обзор рынка",
    "https://t.me/tadviser/5861": "обзор рынка",
    "https://t.me/tadviser/5858": "корпоративная новость",
    "https://t.me/tadviser/5857": "корпоративная новость",
    "https://t.me/tadviser/5856": "обзор рынка",
    "https://t.me/tadviser/5855": "продукт/решение",
    "https://t.me/tadviser/5853": "корпоративная новость",
    "https://t.me/tadviser/5852": "кейс",
    "https://t.me/tadviser/5848": "кейс",
    "https://t.me/tadviser/5847": "корпоративная новость",
    "https://t.me/tadviser/5845": "интервью/комментарий",
    "https://t.me/tadviser/5844": "обзор рынка",
    "https://t.me/tadviser/5880": "обзор рынка",
    "https://t.me/tadviser/5879": "кейс",
    "https://t.me/Lanit_life/3766": "кейс",
    "https://t.me/Reksoft_group/1645": "партнерство",
    "https://t.me/norbit_ru/791": "мероприятие",
    "https://t.me/tadviser/5884": "корпоративная новость",
    "https://t.me/tadviser/5881": "корпоративная новость",
    "https://t.me/b1_news/3482": "мероприятие",
    "https://t.me/kept_business/3347": "аналитика",
    "https://t.me/Reksoft_group/1649": "аналитика",
    "https://t.me/tadviser/5887": "кейс",
    "https://t.me/Axenix_Ru/3266": "аналитика",
    "https://t.me/YakovPartners/3799": "корпоративная новость",
    "https://t.me/tadviser/5890": "мероприятие",
    "https://t.me/tadviser/5896": "кейс",
    "https://t.me/b1_news/3500": "корпоративная новость",
    "https://t.me/tedo_business/4441": "кейс",
    "https://t.me/norbit_ru/793": "мероприятие",
    "https://t.me/b1_news/3501": "обзор рынка",
    "https://t.me/delret/2826": "обзор рынка",
    "https://t.me/Reksoft_group/1652": "кейс",
    "https://t.me/tadviser/5901": "обзор рынка",
    "https://t.me/tadviser/5899": "аналитика",
    "https://t.me/tadviser/5898": "аналитика",
    "https://t.me/tadviser/5897": "корпоративная новость",
    "https://t.me/tadviser/5900": "кейс",
    "https://t.me/b1_news/3474": "мероприятие",
    "https://t.me/b1_news/3477": "корпоративная новость",
    "https://t.me/tedo_business/4436": "мероприятие",
    "https://t.me/YakovPartners/3796": "аналитика",
    "https://t.me/Reksoft_group/1651": "партнерство",
    "https://t.me/Lanit_life/3810": "продукт/решение",
    "https://t.me/kept_business/3382": "аналитика",
    "https://t.me/tadviser/5991": "обзор рынка",
    "https://t.me/tadviser/5990": "обзор рынка",
    "https://t.me/tadviser/5987": "обзор рынка",
    "https://t.me/tadviser/5986": "продукт/решение",
    "https://t.me/Axenix_Ru/3375": "корпоративная новость",
    "https://t.me/k2_tech/2050": "исследование",
    "https://t.me/Lanit_life/3812": "аналитика",
    "https://t.me/YakovPartners/3818": "интервью/комментарий",
    "https://t.me/tedo_business/4452": "исследование",
    "https://t.me/kept_business/3385": "аналитика",
    "https://t.me/Reksoft_group/1687": "интервью/комментарий",
    "https://t.me/tadviser/5994": "обзор рынка",
    "https://t.me/tadviser/5993": "обзор рынка",
    "https://t.me/tadviser/5992": "обзор рынка",
    "https://t.me/b1_news/3550": "корпоративная новость",
    "https://t.me/Axenix_Ru/3387": "мероприятие",
    "https://t.me/Axenix_Ru/3386": "интервью/комментарий",
    "https://t.me/Softline/3328": "партнерство",
    "https://t.me/k2_tech/2051": "аналитика",
    "https://t.me/YakovPartners/3819": "аналитика",
    "https://t.me/Reksoft_group/1694": "мероприятие",
    "https://t.me/tadviser/5999": "обзор рынка",
    "https://t.me/tadviser/5998": "обзор рынка",
    "https://t.me/tadviser/5997": "обзор рынка",
    "https://t.me/tadviser/5996": "обзор рынка",
    "https://t.me/tadviser/5995": "обзор рынка",
    "https://t.me/tadviser/6001": "обзор рынка",
    "https://t.me/tadviser/6000": "обзор рынка",
    "https://t.me/b1_news/3552": "корпоративная новость",
    "https://t.me/Axenix_Ru/3395": "мероприятие",
    "https://t.me/k2_tech/2052": "продукт/решение",
    "https://t.me/Lanit_life/3819": "аналитика",
    "https://t.me/tadviser/6002": "обзор рынка",
    "https://t.me/b1_news/3563": "корпоративная новость",
    "https://t.me/b1_news/3556": "мероприятие",
    "https://t.me/Axenix_Ru/3405": "мероприятие",
    "https://t.me/Axenix_Ru/3399": "исследование",
    "https://t.me/Axenix_Ru/3396": "продукт/решение",
    "https://t.me/YakovPartners/3821": "аналитика",
    "https://t.me/kept_business/3388": "аналитика",
    "https://t.me/kept_business/3387": "обзор рынка",
    "https://t.me/tadviser/6005": "обзор рынка",
    "https://t.me/tadviser/6003": "обзор рынка",
    "https://t.me/Axenix_Ru/3413": "обзор рынка",
    "https://t.me/YakovPartners/3824": "аналитика",
    "https://t.me/tedo_business/4454": "исследование",
    "https://t.me/kept_business/3390": "аналитика",
    "https://t.me/Reksoft_group/1697": "интервью/комментарий",
    "https://t.me/norbit_ru/809": "кейс",
    "https://t.me/tadviser/6008": "обзор рынка",
    "https://t.me/tadviser/6007": "обзор рынка",
    "https://t.me/InnotechCompany/1254": "аналитика",
    "https://t.me/delret/2848": "исследование",
    "https://t.me/tadviser/6010": "обзор рынка",
    "https://t.me/tadviser/6009": "обзор рынка",
    "https://t.me/b1_news/3566": "интервью/комментарий",
    "https://t.me/Axenix_Ru/3431": "обзор рынка",
    "https://t.me/Axenix_Ru/3429": "исследование",
    "https://t.me/Softline/3335": "корпоративная новость",
    "https://t.me/k2_tech/2069": "интервью/комментарий",
    "https://t.me/kept_business/3392": "интервью/комментарий",
    "https://t.me/Reksoft_group/1699": "мероприятие",
    "https://t.me/tadviser/6014": "обзор рынка",
    "https://t.me/tadviser/6013": "обзор рынка",
    "https://t.me/tadviser/6012": "обзор рынка",
    "https://t.me/tadviser/6011": "обзор рынка",
    "https://t.me/Axenix_Ru/3433": "исследование",
    "https://t.me/YakovPartners/3827": "интервью/комментарий",
    "https://t.me/tedo_business/4455": "мероприятие",
    "https://t.me/tadviser/6015": "обзор рынка",
}


@dataclass
class ClassificationResult:
    post_type: str
    confidence: float
    matched_keywords: List[str]
    alternative_type: Optional[str]
    ambiguous: bool


def ensure_dirs() -> None:
    ensure_runtime_dirs()


def load_yaml(path: Path) -> Dict[str, Any]:
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def load_channel_priorities(config_name: str = "daily", profile_name: str = "profile_1") -> Dict[str, float]:
    config_path = BASE_DIR / f"channels_{config_name}.yml"
    if not config_path.exists() and config_name == "channels":
        config_path = BASE_DIR / "channels.yml"
    if not config_path.exists():
        return CHANNEL_HINTS.copy()

    config = load_yaml(config_path)
    profile = (config.get("profiles") or {}).get(profile_name) or {}
    priorities: Dict[str, float] = {}
    for item in profile.get("channels") or []:
        username = item.get("username")
        if not username:
            continue
        weight = item.get("digest_priority", item.get("priority_weight", 1.0))
        try:
            priorities[username] = float(weight)
        except (TypeError, ValueError):
            priorities[username] = 1.0
    return priorities


def msk_now() -> datetime:
    return datetime.now(MSK)


def parse_dt(value: str) -> datetime:
    dt = datetime.fromisoformat(value)
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def fmt_msk(value: str) -> str:
    return parse_dt(value).astimezone(MSK).strftime("%d.%m.%Y %H:%M МСК")


def latest_file(pattern: str) -> Optional[Path]:
    files = sorted(RAW_LOGS_DIR.glob(pattern), key=lambda p: p.stat().st_mtime)
    return files[-1] if files else None


def domain_label(url: str) -> str:
    host = urlparse(url).netloc.lower()
    if host.startswith("www."):
        host = host[4:]
    return host or url


def dedupe_domains(urls: Iterable[str]) -> List[Dict[str, str]]:
    seen = set()
    result = []
    for url in urls or []:
        label = domain_label(url)
        if label in seen:
            continue
        seen.add(label)
        result.append({"label": label, "url": url})
    return result


def normalize_whitespace(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def split_text_units(text: str) -> List[str]:
    text = (text or "").replace("\r", "\n")
    chunks: List[str] = []
    for block in text.split("\n"):
        line = normalize_whitespace(block)
        if not line:
            continue
        line = re.sub(r"^[•·▪◦🔹🔸▶️➖✅🟢📌📍📎👉🔥⭐️📅🤖🖥🏔🧱⚙️♻️🤍🏡🚀🍀]+\s*", "", line).strip()
        if not line:
            continue
        if len(line) > 220:
            parts = re.split(r"(?<=[\.!?])\s+", line)
            chunks.extend([normalize_whitespace(part) for part in parts if normalize_whitespace(part)])
        else:
            chunks.append(line)
    return chunks


def compress_sentence(text: str, limit: int = 180) -> str:
    text = normalize_whitespace(text)
    text = text.replace("  ", " ")
    if len(text) <= limit:
        return text
    shortened = text[: limit - 1].rsplit(" ", 1)[0].rstrip(" ,;:-")
    return f"{shortened}…"


def build_brief(text: str) -> str:
    units = split_text_units(text)
    for unit in units:
        if len(unit) >= 20:
            return compress_sentence(unit, 160)
    return compress_sentence(normalize_whitespace(text), 160)


def build_summary(text: str) -> str:
    units = split_text_units(text)
    selected: List[str] = []
    for unit in units:
        candidate = compress_sentence(unit, 190)
        if candidate and candidate not in selected:
            selected.append(candidate)
        if len(selected) == 3:
            break
    return " ".join(selected) if selected else compress_sentence(normalize_whitespace(text), 220)


def classify_message(text: str) -> ClassificationResult:
    lowered = (text or "").lower()
    scores: Dict[str, float] = defaultdict(float)
    matched: Dict[str, List[str]] = defaultdict(list)

    for post_type, patterns in TYPE_RULES.items():
        for pattern in patterns:
            hits = re.findall(pattern, lowered, flags=re.IGNORECASE)
            if not hits:
                continue
            scores[post_type] += float(len(hits))
            matched[post_type].append(pattern.replace("\\b", ""))

    if "опрос" in lowered and scores["исследование"] > 0:
        scores["исследование"] += 1.5
    if any(token in lowered for token in ("вебинар", "конферен", "форум", "саммит")):
        scores["мероприятие"] += 1.0
    if any(token in lowered for token in ("на конференции", "приглашает вас", "на стенде", "приглашаем обсудить", "на международной премии", "на форуме")):
        scores["мероприятие"] += 1.3
    if any(token in lowered for token in ("сессия", "заседание", "выступил на", "прямое включение")):
        scores["мероприятие"] += 1.2
    if any(token in lowered for token in ("подкаст", "конкурс", "прием заявок", "участие бесплатное", "регистрация обязательна")):
        scores["мероприятие"] += 1.3
    if any(token in lowered for token in ("провела программу повышения квалификации", "провели программу повышения квалификации", "лекции были посвящены")):
        scores["мероприятие"] += 1.5
    if any(token in lowered for token in ("сегодня выступим на сессии", "официальный партнёр", "официальный партнер")):
        scores["мероприятие"] += 1.2
    if any(token in lowered for token in ("внедрение", "внедрили", "реализовали", "автоматизация")):
        scores["кейс"] += 1.0
    if any(token in lowered for token in ("сотрудничеств", "соглашени")):
        scores["партнерство"] += 0.8
    if any(token in lowered for token in ("бизнес-партнера", "получил статус бизнес-партнера", "купила 26%", "заключили соглашение", "подписали соглашение")):
        scores["партнерство"] += 1.5
    if any(token in lowered for token in ("мы можем помочь", "обращайтесь к нам", "обращайтесь к специалистам", "свяжитесь с нами", "оставьте заявку", "узнайте больше об экспертизе", "узнать больше об услугах", "готовы помочь", "обсудить ваш проект", "экспертные консультации", "получить консультацию", "обсудим задачи бизнеса")):
        scores["реклама услуг"] += 1.7
    if any(token in lowered for token in ("обсудили с", "обсудила с", "в комментарии", "комментируют новости", "в сми")):
        scores["интервью/комментарий"] += 1.2
    if any(token in lowered for token in ("полное интервью", "блиц-опрос", "эксперт отмечает", "эксперт выделяет", "считает, что", "— о работе с заказчиками")):
        scores["интервью/комментарий"] += 1.5
    if any(token in lowered for token in ("эксперт выделяет три отраслевые особенности", "директор по развитию бизнеса норбит, — о работе с заказчиками")):
        scores["интервью/комментарий"] += 1.7
    if any(token in lowered for token in ("об этом рассказал", "по его словам", "эксперт подчеркнул", "рассказал, как", "делится впечатлениями от участия")):
        scores["интервью/комментарий"] += 1.3
    if any(token in lowered for token in ("поздравляет", "поздравляем", "фотоотчет", "награждения", "дети наших сотрудников")):
        scores["корпоративная новость"] += 1.2
    if any(token in lowered for token in ("с днем российского предпринимательства",)):
        scores["корпоративная новость"] += 1.7
    if any(token in lowered for token in ("победителей ежегодной", "торжественной церемонии", "премия", "премии", "победитель", "в двух номинациях")):
        scores["корпоративная новость"] += 1.5
    if any(token in lowered for token in ("it prize", "стал победителем", "победитель tadviser", "победитель сразу в двух номинациях")):
        scores["корпоративная новость"] += 1.7
    if any(token in lowered for token in ("традиционный дайджест новостей", "все самое важное за", "_дайджест")):
        scores["корпоративная новость"] += 1.6
    if any(token in lowered for token in ("включена в перечень", "получил статус", "заняв ведущие позиции", "ушел из жизни", "признан банкротом", "массово увольняет", "уволилась вся команда", "уволил руководителей", "с днем эколога")):
        scores["корпоративная новость"] += 1.7
    if any(token in lowered for token in ("обзор новостей", "дайджест новостей", "индустриальном дайджесте")):
        scores["обзор рынка"] += 1.0
    if any(token in lowered for token in ("еженедельном индустриальном дайджесте", "аналитика и тренды ит-рынка", "ежемесячный обзор новостей", "эти и другие новости в выпуске", "главное за месяц", "главные новости за месяц")):
        scores["обзор рынка"] += 1.7
    if any(token in lowered for token in ("установило правила", "утвердило правила", "принял стандарт", "готовится оценивать", "изменения законодательства", "удостоверяющий центр", "для работы с долгами по налогам", "опубликованы эксплойты")):
        scores["обзор рынка"] += 1.5
    if any(token in lowered for token in ("по подписке", "готовую среду", "предустановлены на арендованном оборудовании", "тест-драйв", "демо-версию", "шлюз безопасности", "on-premise", "запустил в продажу", "generator")):
        scores["продукт/решение"] += 1.7
    if any(token in lowered for token in ("основные причины", "остается одним из самых сложных", "оценила соответствие")):
        scores["аналитика"] += 1.0
    if any(token in lowered for token in ("что мешает", "по данным", "падает более чем")):
        scores["аналитика"] += 1.2
    if any(token in lowered for token in ("несколько инсайдов", "экономической эффективности", "чистую прибыль", "конец эпохи", "барьеры и пути роста", "новая рациональность покупателей", "главный результат трех лет")):
        scores["аналитика"] += 1.4

    if not scores:
        return ClassificationResult(
            post_type="требует уточнения",
            confidence=0.0,
            matched_keywords=[],
            alternative_type=None,
            ambiguous=True,
        )

    ranked = sorted(scores.items(), key=lambda item: item[1], reverse=True)
    top_type, top_score = ranked[0]
    alt_type = ranked[1][0] if len(ranked) > 1 else None
    alt_score = ranked[1][1] if len(ranked) > 1 else 0.0
    confidence = round(top_score / (top_score + alt_score + 1.0), 3)
    ambiguous = top_score <= 1.0 or (alt_score and (top_score - alt_score) < 1.0)
    post_type = "требует уточнения" if ambiguous else top_type

    return ClassificationResult(
        post_type=post_type,
        confidence=confidence,
        matched_keywords=matched.get(top_type, [])[:5],
        alternative_type=alt_type,
        ambiguous=ambiguous,
    )


def apply_manual_type_override(message: Dict[str, Any], classification: ClassificationResult) -> ClassificationResult:
    override_type = MANUAL_TYPE_OVERRIDES.get(message.get("original_url") or "")
    if not override_type:
        return classification
    return ClassificationResult(
        post_type=override_type,
        confidence=1.0,
        matched_keywords=["manual_override"],
        alternative_type=classification.post_type if classification.post_type != override_type else classification.alternative_type,
        ambiguous=False,
    )


def score_message(message: Dict[str, Any], classification: ClassificationResult, channel_priorities: Dict[str, float]) -> Tuple[float, List[str]]:
    post_type = classification.post_type
    text = message.get("text", "")
    metadata = message.get("metadata") or {}
    links = message.get("external_links") or []
    channel = message.get("chat") or ""

    score = TYPE_WEIGHTS.get(post_type, 4.0)
    reasons = [f"тип:{post_type}"]

    text_len = len(normalize_whitespace(text))
    if text_len >= 1200:
        score += 1.2
        reasons.append("длинный_содержательный_пост")
    elif text_len >= 600:
        score += 0.7
        reasons.append("содержательный_пост")
    elif text_len >= 250:
        score += 0.3

    if links:
        score += min(len(links), 3) * 0.15
        reasons.append("есть_внешние_ссылки")

    if metadata.get("forwards"):
        score += min(float(metadata["forwards"]) * 0.05, 0.5)
    if metadata.get("views"):
        score += min(float(metadata["views"]) / 1500.0, 0.5)
    if metadata.get("edit_date"):
        score += 0.1

    priority_weight = channel_priorities.get(channel, 1.0)
    if priority_weight != 1.0:
        score *= priority_weight
        reasons.append(f"приоритет_канала:{priority_weight:g}")

    if classification.matched_keywords:
        reasons.append("keywords:" + ",".join(classification.matched_keywords[:3]))
    if classification.ambiguous:
        reasons.append("требует_уточнения")

    return round(score, 3), reasons


def derive_rows(summary_payload: Dict[str, Any], config_name: str = "daily", profile_name: str = "profile_1") -> List[Dict[str, Any]]:
    channel_priorities = load_channel_priorities(config_name=config_name, profile_name=profile_name)
    rows: List[Dict[str, Any]] = []
    for item in summary_payload.get("messages") or []:
        text = item.get("text") or ""
        classification = classify_message(text)
        classification = apply_manual_type_override(item, classification)
        score, reasons = score_message(item, classification, channel_priorities)
        rows.append({
            "канал": item.get("chat"),
            "дата-время": fmt_msk(item.get("date")),
            "ссылка": item.get("original_url"),
            "краткое содержание": build_brief(text),
            "саммари": build_summary(text),
            "тип поста": classification.post_type,
            "_score": score,
            "_selection_reasons": reasons,
            "_classification_confidence": classification.confidence,
            "_classification_alternative": classification.alternative_type,
            "_external_links": dedupe_domains(item.get("external_links") or []),
            "_raw_text": text,
            "_id": item.get("id"),
            "_chat": item.get("chat"),
        })
    return rows


def write_csv(rows: Sequence[Dict[str, Any]], out_path: Path) -> Path:
    ensure_dirs()
    with out_path.open("w", encoding="utf-8-sig", newline="") as file_obj:
        writer = csv.writer(file_obj)
        writer.writerow(["канал", "дата-время", "ссылка", "краткое содержание", "саммари", "тип поста"])
        for row in rows:
            writer.writerow([
                row["канал"],
                row["дата-время"],
                row["ссылка"],
                row["краткое содержание"],
                row["саммари"],
                row["тип поста"],
            ])
    return out_path


def build_digest_payload(summary_path: Path, config_name: str = "daily", profile_name: str = "profile_1") -> Dict[str, Any]:
    ensure_dirs()
    payload = json.loads(summary_path.read_text(encoding="utf-8"))
    rows = derive_rows(payload, config_name=config_name, profile_name=profile_name)
    sorted_rows = sorted(rows, key=lambda row: row["_score"], reverse=True)
    report_stamp = msk_now().strftime("%Y-%m-%d_%H-%M-%S")
    csv_path = CACHE_DOCS_DIR / f"telegram_it_consulting_processed_{report_stamp}.csv"
    report_path = CACHE_DOCS_DIR / f"telegram_it_consulting_digest_payload_{report_stamp}.json"
    write_csv(rows, csv_path)

    compact_rows = []
    for row in rows:
        compact_rows.append({
            key: value for key, value in row.items() if not key.startswith("_raw")
        })

    report = {
        "generated_at": msk_now().isoformat(),
        "summary_input_path": str(summary_path),
        "raw_log": payload.get("raw_log"),
        "non_empty_messages": payload.get("non_empty_messages", len(rows)),
        "rows_total": len(rows),
        "requires_review_count": sum(1 for row in rows if row["тип поста"] == "требует уточнения"),
        "csv_path": str(csv_path),
        "rows": compact_rows,
        "top_candidates": [
            {
                "канал": row["канал"],
                "id": row["_id"],
                "дата-время": row["дата-время"],
                "ссылка": row["ссылка"],
                "краткое содержание": row["краткое содержание"],
                "саммари": row["саммари"],
                "тип поста": row["тип поста"],
                "score": row["_score"],
                "selection_reasons": row["_selection_reasons"],
                "external_links": row["_external_links"],
            }
            for row in sorted_rows[:10]
        ],
        "channels_counter": Counter(row["канал"] for row in rows),
        "types_counter": Counter(row["тип поста"] for row in rows),
    }
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    report["payload_path"] = str(report_path)
    return report


def load_latest_collection_report() -> Optional[Dict[str, Any]]:
    if POINTER_PATH.exists():
        return json.loads(POINTER_PATH.read_text(encoding="utf-8"))
    latest = latest_file("reports/collect_*.json")
    if not latest:
        return None
    return json.loads(latest.read_text(encoding="utf-8"))


def write_collection_report(report: Dict[str, Any]) -> Path:
    ensure_dirs()
    stamp = msk_now().strftime("%Y-%m-%d_%H-%M-%S")
    path = REPORTS_DIR / f"collect_{stamp}.json"
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    POINTER_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def list_recent_collection_reports(days: int = 7) -> List[Dict[str, Any]]:
    cutoff = msk_now() - timedelta(days=days)
    reports: List[Dict[str, Any]] = []
    for path in sorted(REPORTS_DIR.glob("collect_*.json"), key=lambda item: item.stat().st_mtime):
        report = json.loads(path.read_text(encoding="utf-8"))
        started_at = report.get("started_at")
        if started_at:
            dt = parse_dt(started_at).astimezone(MSK)
            if dt < cutoff:
                continue
        report["_path"] = str(path)
        reports.append(report)
    return reports


def list_recent_summary_inputs(days: int = 7) -> List[Path]:
    cutoff = msk_now() - timedelta(days=days)
    result: List[Path] = []
    for path in sorted(RAW_LOGS_DIR.glob("raw_*_summary_input.json"), key=lambda item: item.stat().st_mtime):
        dt = datetime.fromtimestamp(path.stat().st_mtime, tz=MSK)
        if dt >= cutoff:
            result.append(path)
    return result
