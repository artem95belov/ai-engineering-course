"""
Модуль 7, Занятие 14 — проверка агентного поведения: прогон 5 сценариев.

Агент из Занятия 13 прогоняется по пяти контрольным сценариям из
data/scenarios.json: штатный, неполные данные, неверное оборудование,
вопрос вне базы, конфликтующие источники. По каждому собирается трасса:
сколько шагов, какие инструменты, было ли подтверждение, сколько токенов,
чем закончилось.

Результат — таблица в консоли и файл RESULTS.md. Последнюю колонку таблицы
(«Соответствует?») заполняешь ты сам, сверив трассу с ожиданием: оценка
агентного поведения — работа человека, автоматика даёт только факты.

Подтверждение write-действий здесь отвечает «да» автоматически (auto_confirm):
прогон должен быть повторяемым и не зависеть от того, кто сидит за клавиатурой.
Сам факт запроса подтверждения при этом попадает в трассу.

ТВОЯ РАБОТА — TODO 1-2: прогон одного сценария и сборка markdown-таблицы.
Каркас, автоподтверждение и запись файла уже готовы.

Запуск (из папки module_07):
    python agent_eval.py
"""

import json
from pathlib import Path

from tool_use_native import make_llm, run_agent

SCENARIOS_FILE = Path(__file__).parent / "data" / "scenarios.json"
RESULTS_FILE = Path(__file__).parent / "RESULTS.md"


def auto_confirm(name: str, args: dict) -> bool:
    """Автоподтверждение для повторяемого прогона. Факт запроса — в трассе."""
    print(f"  [подтверждение] {name}: авто-«да» (в бою здесь спрашивают человека)")
    return True


def short(text: str, limit: int = 120) -> str:
    """Однострочная выжимка ответа для таблицы (| сломал бы markdown)."""
    line = " ".join(str(text).split()).replace("|", "/")
    return line if len(line) <= limit else line[: limit - 1] + "…"


def run_scenario(scenario: dict, llm) -> dict:
    """Прогоняет один сценарий и собирает строку будущей таблицы.

    TODO 1. Шаги:
      * вызови run_agent(scenario["task"], llm=llm, confirm=auto_confirm) —
        он вернёт (answer, stats);
      * собери и верни словарь строки таблицы:
        {"id": scenario["id"], "name": scenario["name"],
         "expected": scenario["expected"],
         "steps": stats["steps"],
         "tools": ", ".join(stats["tools"]) or "—",
         "confirmations": stats["confirmations"],
         "tokens": stats["tokens"],
         "stop": stats["stop"],
         "answer": answer}
    Печать заголовка сценария уже сделана.
    """
    print("\n" + "#" * 70)
    print(f"# Сценарий {scenario['id']}: {scenario['name']}")
    print("#" * 70)
    answer, stats = run_agent(scenario["task"], llm=llm, confirm=auto_confirm)
    return {
        "id": scenario["id"],
        "name": scenario["name"],
        "expected": scenario["expected"],
        "steps": stats["steps"],
        "tools": ", ".join(stats["tools"]) or "—",
        "confirmations": stats["confirmations"],
        "tokens": stats["tokens"],
        "stop": stats["stop"],
        "answer": answer,
    }


def to_markdown(rows: list) -> str:
    
    lines = [
        "# Модуль 7. Результаты прогона контрольных сценариев",
        "",
        "| № | Сценарий | Шагов | Инструменты | Подтверждений | Токенов | Остановка | Ответ агента (кратко) | Соответствует? |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for r in rows:
        lines.append(
            f"| {r['id']} | {r['name']} | {r['steps']} | {r['tools']} "
            f"| {r['confirmations']} | {r['tokens']} | {r['stop']} "
            f"| {short(r['answer'])} | ? |"
        )
    lines += [
        "",
        "Колонку «Соответствует?» заполни сам: сверь трассу и ответ с ожиданием "
        "и поставь «да» или «нет» с одной строкой пояснения.",
        "",
        "## Ожидания и полные ответы",
        "",
    ]
    for r in rows:
        lines += [
            f"### Сценарий {r['id']}. {r['name']}",
            "",
            f"**Ожидание:** {r['expected']}",
            "",
            f"**Ответ агента:** {r['answer']}",
            "",
        ]
    return "\n".join(lines)


def main():
    scenarios = json.loads(SCENARIOS_FILE.read_text(encoding="utf-8"))["scenarios"]
    llm = make_llm()

    rows = [run_scenario(s, llm) for s in scenarios]

    print("\n" + "=" * 70)
    print(f"{'№':<3}{'Сценарий':<26}{'Шагов':<7}{'Подтв.':<8}{'Токенов':<9}Остановка")
    for r in rows:
        print(f"{r['id']:<3}{r['name']:<26}{r['steps']:<7}"
              f"{r['confirmations']:<8}{r['tokens']:<9}{r['stop']}")
    total = sum(r["tokens"] for r in rows)
    print(f"\nВсего токенов за прогон: {total}")

    RESULTS_FILE.write_text(to_markdown(rows), encoding="utf-8")
    print(f"Таблица записана: {RESULTS_FILE.name} — заполни колонку «Соответствует?»")


if __name__ == "__main__":
    main()
