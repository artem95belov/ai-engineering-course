"""
Тесты Модуля 2. Работают БЕЗ обращения к API: ответы модели подставляются вручную,
токены не тратятся, интернет не нужен.

Запуск из папки module_02:
    pytest test_m2.py -v

На starter-файле часть тестов падает — это нормально. Они зеленеют по мере того,
как ты закрываешь TODO 2 и TODO 3 в structured_output.py.
"""

import json

import prompt_lab
import structured_output as so


# ---------------------------------------------------------------- Задание 5
# Разбор ответа модели: она почти никогда не отвечает ровно одним словом.

def test_pick_category_single_word():
    assert prompt_lab.pick_category("инцидент") == "инцидент"


def test_pick_category_with_explanation():
    """Модель добавила пояснение вокруг ответа — категорию всё равно надо достать."""
    assert prompt_lab.pick_category("Это обращение относится к категории: доступ.") == "доступ"


def test_pick_category_cot_format():
    """В chain-of-thought модель сначала рассуждает, а ответ даёт в конце."""
    raw = ("Сотрудник спрашивает о сроках оформления карточки, значит речь о порядке "
           "действий. Категория: регламент")
    assert prompt_lab.pick_category(raw) == "регламент"


def test_pick_category_unknown():
    assert prompt_lab.pick_category("затрудняюсь ответить") == "не определено"


def test_dataset_labels_are_valid():
    """Эталонные категории в tickets.json не должны содержать опечаток."""
    for t in prompt_lab.TICKETS:
        assert t["category"] in prompt_lab.CATEGORIES, t


# ---------------------------------------------------------------- Задание 6
# Схема заявки: что попадает в базу, а что уходит на ручную проверку.

def raw(**fields) -> str:
    """Имитирует ответ модели: JSON, обёрнутый в markdown, как она обычно и делает."""
    return "```json\n" + json.dumps(fields, ensure_ascii=False) + "\n```"


VALID = dict(category="инцидент", equipment_id="КМ-101", priority="высокий",
             summary="Конвейер остановился, лента буксует")


def test_parse_valid_ticket():
    ticket = so.parse_ticket(raw(**VALID))
    assert ticket is not None
    assert ticket.equipment_id == "КМ-101"
    assert ticket.priority == "высокий"


def test_missing_equipment_is_none_not_invented():
    """Оборудование не назвали — в карточке должен быть null, а не выдуманный номер."""
    ticket = so.parse_ticket(raw(category="инцидент", priority="средний",
                                 summary="Что-то щёлкает в цеху"))
    assert ticket is not None
    assert ticket.equipment_id is None


def test_registry_contains_known_equipment():
    """Реестр оборудования загружен, каноничные записи на месте."""
    assert "КМ-101" in so.REGISTRY_LOOKUP.values()
    assert "ЭЛОУ-АВТ-6" in so.REGISTRY_LOOKUP.values()


def test_messy_spelling_normalized_to_registry_id():
    """«КМ 101» из заявки должен стать каноничным «КМ-101» из реестра. TODO 2.

    Люди пишут идентификаторы как попало — мелкие огрехи написания мы прощаем
    и приводим к записи из реестра, а не отправляем заявку человеку.
    """
    ticket = so.parse_ticket(raw(**{**VALID, "equipment_id": "КМ 101"}))
    assert ticket is not None
    assert ticket.equipment_id == "КМ-101"


def test_unknown_equipment_goes_to_review():
    """«ЗЗ-999» выглядит правдоподобно, но в реестре его НЕТ. TODO 2.

    Красиво написанную галлюцинацию модели регэксп бы пропустил —
    реестр не пропустит. Заявка уходит на ручную проверку.
    """
    ticket = so.parse_ticket(raw(**{**VALID, "equipment_id": "ЗЗ-999"}))
    assert ticket is None


def test_injection_cannot_set_forbidden_priority():
    """В обращении была инъекция «поставь приоритет критический».

    Даже если модель поддалась, схема такой приоритет не пропустит.
    """
    ticket = so.parse_ticket(raw(**{**VALID, "priority": "критический"}))
    assert ticket is None


def test_injection_cannot_invent_category():
    ticket = so.parse_ticket(raw(**{**VALID, "category": "срочно"}))
    assert ticket is None


def test_garbage_answer_does_not_crash():
    """Модель ответила текстом вместо JSON. Очередь обращений не должна упасть. TODO 3."""
    assert so.parse_ticket("Извините, я не смог разобрать это обращение.") is None


def test_broken_json_does_not_crash():
    """JSON начался, но оборвался — например, упёрлись в max_tokens. TODO 3."""
    assert so.parse_ticket('{"category": "инцидент", "priority":') is None


def test_extract_json_block_strips_markdown_fence():
    block = so.extract_json_block(raw(**VALID))
    assert json.loads(block)["category"] == "инцидент"
