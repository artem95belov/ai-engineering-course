"""
Модуль 6, Занятие 11 — базовый MCP-сервер: интерфейс к системам и инструменты.

ТВОЯ РАБОТА: TODO 1 (NEW_EQUIPMENT — заполнить учебную запись оборудования),
TODO 2 (get_equipment_status — инструмент чтения статуса оборудования),
TODO 3 (create_incident — инструмент создания заявки на инцидент).

Что такое MCP в двух словах: это протокол, по которому LLM-хост (например,
чат-ассистент) обращается не напрямую к вашей базе/API, а к отдельному
MCP-серверу. Сервер публикует:
  - tools     — действия с чёткой схемой аргументов (что вызвать, с какими
                параметрами, что вернётся);
  - resources — данные для чтения по URI, без вызова инструмента;
  - prompts   — заготовки промптов (в этом занятии не используем).
Хост видит только эти три интерфейса и ничего не знает о внутреннем
устройстве систем ПромТеха — в этом и есть смысл MCP как безопасного
адаптера: LLM не получает прямой доступ к боевой системе, а работает
через контролируемый и журналируемый набор инструментов.

ВАЖНО: этот файл — сам MCP-сервер, а не обычный скрипт. Если запустить его
напрямую (python mcp_server_basic.py), он не выведет ничего в консоль и
«зависнет» — это нормально, сервер ждёт сообщений по протоколу MCP на
stdin. Чтобы увидеть сервер в работе, запусти:

    python mcp_client_demo.py

Скрипт поднимет этот файл как подпроцесс (stdio) и станет MCP-хостом:
ты пишешь обычную фразу («статус PUMP-07»), GigaChat сам выбирает tool
из каталога сервера и вызывает его по протоколу MCP.

Разделение read/write: get_equipment_status ничего не меняет в системе —
его можно вызывать сколько угодно раз (идемпотентная операция чтения).
create_incident каждый раз создаёт новую заявку — операция с побочным
эффектом, поэтому у неё есть дополнительная проверка прав (параметр role).
"""

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

from mcp.server.mcpserver import MCPServer

BASE_DIR = Path(__file__).parent
EQUIPMENT_PATH = BASE_DIR / "data" / "equipment_registry.json"
INCIDENTS_PATH = BASE_DIR / "data" / "incidents.json"
AUDIT_LOG_PATH = BASE_DIR / "data" / "audit_log.jsonl"

# Роли, которым разрешено создавать инциденты (write-инструмент).
# "viewer" — только чтение, дефолт нарочно "безопасный": если вызывающий
# не передал роль явно, он получит отказ на create_incident, а не заявку.
ALLOWED_TO_CREATE_INCIDENT = {"engineer", "admin"}
ALLOWED_PRIORITIES = {"low", "medium", "high", "critical"}


# ====================================================================
#  TODO 1 — учебная запись оборудования
# ====================================================================
#
# В боевой системе ПромТеха это оборудование уже стоит на учёте, но в
# нашем учебном реестре (data/equipment_registry.json) его пока нет —
# заполни карточку по описанию ниже и запись подключится к общему
# реестру при старте сервера.
#
# Описание для карточки:
#   Транспортёрная лента ТЛ-9, установлена в цехе дробления,
#   сейчас в работе, дата последнего технического обслуживания — 10
#   февраля 2026 года (формат даты — как в остальных записях реестра,
#   "YYYY-MM-DD").
#
# Сейчас три поля ниже — заглушки None: замени их на значения из описания.
NEW_EQUIPMENT = {
    "id": "CONV-09",
    "name": "Транспортёрная лента ТЛ-9",
    "type": "конвейер",
    "location": "Цех дробления",
    "status": "в работе",
    "last_service_date": "2026-02-10",
}


# ====================================================================
#  ИНФРАСТРУКТУРА (дано, менять не нужно)
# ====================================================================

class CorporateSystemUnavailable(Exception):
    """Имитация отказа боевой системы ПромТеха (сценарий outage, занятие 12)."""


# Переключатель сбоя «боевой» системы. Сам по себе действует только внутри
# того процесса, где его выставили. mcp_client_demo.py поднимает сервер
# отдельным процессом — поэтому shift_review_m12.py включает сбой через
# файл data/simulate_outage.flag, а сервер читает его при каждом вызове.
SIMULATE_OUTAGE = False
OUTAGE_FLAG_PATH = BASE_DIR / "data" / "simulate_outage.flag"


def outage_is_on() -> bool:
    return SIMULATE_OUTAGE or OUTAGE_FLAG_PATH.exists()


def set_simulate_outage(on: bool) -> None:
    """Включает/выключает сбой и для текущего процесса, и для MCP-сервера в хосте."""
    global SIMULATE_OUTAGE
    SIMULATE_OUTAGE = bool(on)
    if on:
        OUTAGE_FLAG_PATH.parent.mkdir(parents=True, exist_ok=True)
        OUTAGE_FLAG_PATH.write_text("1", encoding="utf-8")
    elif OUTAGE_FLAG_PATH.exists():
        OUTAGE_FLAG_PATH.unlink()


def _load_equipment() -> dict:
    """Читает реестр оборудования и подмешивает учебную запись (TODO 1)."""
    registry = json.loads(EQUIPMENT_PATH.read_text(encoding="utf-8-sig"))
    by_id = {item["id"]: item for item in registry["equipment"]}
    by_id[NEW_EQUIPMENT["id"]] = NEW_EQUIPMENT
    return by_id


EQUIPMENT = _load_equipment()


def _load_incidents() -> list:
    if not INCIDENTS_PATH.exists():
        return []
    return json.loads(INCIDENTS_PATH.read_text(encoding="utf-8-sig"))


def _save_incident(incident: dict) -> None:
    incidents = _load_incidents()
    incidents.append(incident)
    INCIDENTS_PATH.write_text(
        json.dumps(incidents, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def log_action(action: str, params: dict, result: dict) -> None:
    """Журналирует каждый вызов инструмента: кто, что и с каким итогом.

    В промышленном контуре это не «для галочки» — по такому логу потом
    разбирают инциденты и проверяют, что ИИ-ассистент не вышел за рамки
    разрешённых действий. Формат — JSON Lines: одна запись — одна строка,
    удобно дописывать и удобно потом построчно прочитать при аудите.
    """
    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "action": action,
        "params": params,
        "ok": bool(result.get("ok")),
    }
    with AUDIT_LOG_PATH.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def _simulate_corporate_lookup(equipment_id: str) -> None:
    """Заглушка вызова реальной корпоративной системы ПромТеха.

    В учебном проекте статус и так лежит в локальном реестре, но в реальном
    MCP-сервере get_equipment_status обычно дергает внутренний API/БД —
    и этот вызов может упасть (сеть, сервис не отвечает, права не те).
    Этой функцией моделируем такой отказ: переменная SIMULATE_OUTAGE
    или файл data/simulate_outage.flag (его ставит shift_review_m12.py).
    """
    if outage_is_on():
        raise CorporateSystemUnavailable(
            "Корпоративная система ПромТеха недоступна (имитация сбоя)"
        )


app = MCPServer(
    name="promtech-equipment",
    instructions=(
        "Учебный MCP-сервер ПромТеха: узнать статус оборудования и "
        "зарегистрировать инцидент без прямого доступа к боевой системе."
    ),
)


@app.resource("equipment://list")
def list_equipment() -> str:
    """Ресурс: полный реестр оборудования для чтения хостом без вызова tool.

    Отличие ресурса от инструмента: инструмент — это действие с аргументами
    («покажи статус вот этого id»), ресурс — просто данные по фиксированному
    адресу (URI), которые хост может прочитать заранее, не дожидаясь вопроса
    пользователя.
    """
    return json.dumps(list(EQUIPMENT.values()), ensure_ascii=False, indent=2)


# ====================================================================
#  TODO 2 — инструмент чтения: get_equipment_status
# ====================================================================

@app.tool()
def get_equipment_status(equipment_id: str) -> dict:
    """Возвращает текущий статус оборудования по его id.

    TODO 2: сейчас всегда возвращает заглушку "не реализовано" — замени
    тело функции на реальную логику.

    Что сделать:
      1. Залогировать вызов: log_action("get_equipment_status",
         {"equipment_id": equipment_id}, result) — result нужно собрать
         до вызова log_action, поэтому логируй в самом конце, прямо перед
         return (или через промежуточную переменную result).
      2. Если equipment_id нет в EQUIPMENT — вернуть
         {"ok": False, "error": f"Оборудование {equipment_id} не найдено"}.
      3. Вызвать _simulate_corporate_lookup(equipment_id) — это и есть
         обращение к «боевой системе». Оберни вызов в try/except
         CorporateSystemUnavailable as exc и в случае ошибки верни
         {"ok": False, "error": str(exc)} — инструмент не должен падать
         с исключением наружу, он обязан вернуть предсказуемую структуру
         даже при сбое.
      4. Если всё ок — вернуть {"ok": True, **EQUIPMENT[equipment_id]}
         (или собрать словарь полей явно: equipment_id, name, status,
         location, last_service_date).

    Это инструмент только для чтения — идемпотентный, его можно вызывать
    сколько угодно раз подряд без побочных эффектов.
    """
    if equipment_id not in EQUIPMENT:
        result = {"ok": False, "error": f"Оборудование {equipment_id} не найдено"}
        log_action("get_equipment_status", {"equipment_id": equipment_id}, result)
        return result

    try:
        _simulate_corporate_lookup(equipment_id)
    except CorporateSystemUnavailable as exc:
        result = {"ok": False, "error": str(exc)}
        log_action("get_equipment_status", {"equipment_id": equipment_id}, result)
        return result

    item = EQUIPMENT[equipment_id]
    result = {
        "ok": True,
        "equipment_id": item["id"],
        "name": item["name"],
        "status": item["status"],
        "location": item["location"],
        "last_service_date": item["last_service_date"],
    }
    log_action("get_equipment_status", {"equipment_id": equipment_id}, result)
    return result


# ====================================================================
#  TODO 3 — инструмент записи: create_incident
# ====================================================================

@app.tool()
def create_incident(
    equipment_id: str,
    description: str,
    priority: str,
    role: str = "viewer",
) -> dict:
    """Создаёт заявку на инцидент по оборудованию и сохраняет её локально.

    TODO 3: сейчас всегда возвращает заглушку "не реализовано" — замени
    тело функции на реальную логику.

    Что сделать, по шагам (порядок важен — сначала права, потом входные
    данные, и только потом запись):
      1. Проверка прав: если role не в ALLOWED_TO_CREATE_INCIDENT — вернуть
         {"ok": False, "error": f"Роль {role!r} не имеет прав на создание "
         "инцидентов"}. Это и есть «права пользователя» из лекции: read-
         инструмент (get_equipment_status) доступен всем, write-инструмент
         (create_incident) — только ролям engineer/admin.
      2. Проверка оборудования: если equipment_id нет в EQUIPMENT — вернуть
         {"ok": False, "error": f"Оборудование {equipment_id} не найдено"}.
      3. Проверка параметра: если priority не в ALLOWED_PRIORITIES —
         вернуть {"ok": False, "error": f"Недопустимый приоритет {priority!r},"
         f" ожидается один из {sorted(ALLOWED_PRIORITIES)}"}.
      4. Если все проверки пройдены — собрать инцидент:
             incident = {
                 "id": uuid.uuid4().hex[:8],
                 "equipment_id": equipment_id,
                 "description": description,
                 "priority": priority,
                 "status": "open",
                 "created_at": datetime.now(timezone.utc).isoformat(),
             }
         сохранить его через _save_incident(incident) и вернуть
         {"ok": True, "incident": incident}.
      5. В любом случае (успех или отказ на любом шаге) — залогировать
         вызов через log_action("create_incident",
         {"equipment_id": equipment_id, "priority": priority, "role": role},
         result) перед return.

    В отличие от get_equipment_status, это НЕ идемпотентная операция:
    два одинаковых вызова создадут два разных инцидента с разными id.
    """
    if role not in ALLOWED_TO_CREATE_INCIDENT:
        result = {"ok": False, "error": f"Роль {role!r} не имеет прав на создание инцидентов"}
        log_action("create_incident", {"equipment_id": equipment_id, "priority": priority, "role": role}, result)
        return result

    if equipment_id not in EQUIPMENT:
        result = {"ok": False, "error": f"Оборудование {equipment_id} не найдено"}
        log_action("create_incident", {"equipment_id": equipment_id, "priority": priority, "role": role}, result)
        return result

    if priority not in ALLOWED_PRIORITIES:
        result = {
            "ok": False,
            "error": f"Недопустимый приоритет {priority!r}, ожидается один из {sorted(ALLOWED_PRIORITIES)}",
        }
        log_action("create_incident", {"equipment_id": equipment_id, "priority": priority, "role": role}, result)
        return result

    incident = {
        "id": uuid.uuid4().hex[:8],
        "equipment_id": equipment_id,
        "description": description,
        "priority": priority,
        "status": "open",
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    _save_incident(incident)
    result = {"ok": True, "incident": incident}
    log_action("create_incident", {"equipment_id": equipment_id, "priority": priority, "role": role}, result)
    return result


if __name__ == "__main__":
    app.run(transport="stdio")
