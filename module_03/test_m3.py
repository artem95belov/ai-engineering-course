"""
Тесты Модуля 3 (занятия 5-6). Работают БЕЗ загрузки модели и без обращения
к сети: ответы модели в тестах заменены заглушками.

Запуск из папки module_03:
    pytest test_m3.py -v

На starter-файлах часть тестов падает — это нормально: они закрываются
по мере выполнения TODO. После правильного решения все должны стать зелёными.
"""

import json
import re
from pathlib import Path

import pytest

from corpus_loader import CORPUS_DIR, load_documents, load_records
from generate_corpus import REGISTRY, extract_json_array, validate_equipment_id
from ingestion import build_chunks, chunk_id, chunk_text
from parse_documents import clean_text, has_text_layer

TEXT = "".join(f"Предложение номер {i}. " for i in range(1, 41))  # ~800 символов
REGISTRY_IDS = {item["id"] for item in REGISTRY}
QUESTIONS = json.loads(
    (Path(__file__).parent / "data" / "questions.json").read_text(encoding="utf-8")
)["questions"]


# ---------------------------------------------------------------- корпус
def test_corpus_loads():
    docs = load_documents()
    assert len(docs) >= 20, ("в корпусе должно быть минимум 20 документов "
                             "(4 спарсенных + карточки + инциденты + регламенты)")


def test_every_doc_has_metadata():
    """Без метаданных нельзя ни отфильтровать поиск, ни сослаться на источник."""
    for doc in load_documents():
        assert doc["doc_id"], "документ без doc_id"
        assert doc["type"], f"{doc['doc_id']}: нет типа документа"
        assert doc["title"], f"{doc['doc_id']}: нет заголовка"
        assert doc["records"], f"{doc['doc_id']}: нет ни одной записи"


def test_doc_ids_are_unique():
    ids = [d["doc_id"] for d in load_documents()]
    assert len(ids) == len(set(ids)), f"дубли doc_id: {ids}"


def test_corpus_has_all_required_types():
    """Корпус занятия 5: публичные нормы + три типа сгенерированных документов."""
    types = {d["type"] for d in load_documents()}
    for required in ["нормативный документ", "карточка оборудования",
                     "журнал инцидентов", "регламент"]:
        assert required in types, f"в корпусе нет документа типа «{required}»"


def test_equipment_ids_from_registry():
    """Идентификаторы проверяем не «по виду», а по реестру (см. М2):
    единого формата кодов оборудования в промышленности не существует."""
    for doc in load_documents():
        for eq in doc["equipment"]:
            assert eq in REGISTRY_IDS, (
                f"{doc['doc_id']}: оборудование «{eq}» отсутствует в реестре")


def test_every_record_can_be_cited():
    """У каждой записи есть страница или раздел.

    Запись, на которую нельзя сослаться, бесполезна: ответ ассистента
    «где-то в ГОСТе» инженер проверить не сможет.
    """
    for rec in load_records():
        assert rec["page"] is not None or rec["section"], (
            f"{rec['doc_id']}: запись без page и без section")


def test_corpus_files_are_human_readable():
    """Кириллица в файлах корпуса — буквами, а не \\uXXXX.

    Иначе корпус нельзя ни прочитать глазами, ни посмотреть в git,
    что именно изменилось после пересборки.
    """
    for path in sorted(CORPUS_DIR.glob("*.json")):
        raw = path.read_text(encoding="utf-8")
        assert "\\u04" not in raw, f"{path.name}: кириллица экранирована — нужен ensure_ascii=False"
        assert '\n  "doc_id"' in raw, f"{path.name}: файл записан без отступов (indent=2)"


# ---------------------------------------------------------------- метаданные
def test_dates_are_normalized():
    """Дата — ГГГГ-ММ-ДД или год. Модель возвращает их в четырёх разных
    форматах, и если не привести к одному, сравнить даты будет нечем."""
    for doc in load_documents():
        if doc["date"]:
            assert re.fullmatch(r"\d{4}(-\d{2}-\d{2})?", doc["date"]), (
                f"{doc['doc_id']}: дата «{doc['date']}» не приведена к виду ГГГГ-ММ-ДД")


def test_reglaments_have_version():
    """У регламента версия обязана быть: без неё Модуль 4 не отличит
    действующую редакцию от отменённой."""
    reglaments = [d for d in load_documents() if d["type"] == "регламент"]
    assert reglaments, "в корпусе нет ни одного регламента"
    for doc in reglaments:
        assert doc["version"], f"{doc['doc_id']}: не заполнена версия документа"


def test_provenance_is_recorded():
    """У каждого документа записано, из какого файла он собран."""
    for doc in load_documents():
        assert doc.get("source_file"), f"{doc['doc_id']}: нет source_file"
        assert doc.get("sha256"), f"{doc['doc_id']}: нет контрольной суммы источника"


# ---------------------------------------------------------------- парсер (TODO 2-3)
def test_clean_text_collapses_spaces():
    """pypdf оставляет цепочки пробелов — в корпус они попадать не должны."""
    assert clean_text("Насос   мембранный\t НМ-205") == "Насос мембранный НМ-205"


def test_clean_text_collapses_blank_lines():
    """Стопка пустых строк схлопывается до одной границы абзаца."""
    assert clean_text("Раздел 1.\n\n\n\n\nРаздел 2.") == "Раздел 1.\n\nРаздел 2."


def test_text_layer_accepted():
    """Нормальный документ: тысячи символов на страницу."""
    assert has_text_layer("х" * 10_000, pages=5) is True


def test_text_layer_scan_rejected():
    """Скан: pypdf вытаскивает от силы номера страниц."""
    assert has_text_layer("стр. 1  стр. 2", pages=5) is False


def test_text_layer_zero_pages_rejected():
    assert has_text_layer("", pages=0) is False


# ---------------------------------------------------------------- генератор (TODO 4-5)
def test_validate_keeps_canonical_id():
    assert validate_equipment_id("КМ-101") == "КМ-101"


def test_validate_normalizes_messy_spelling():
    """«км 101» — человеческое написание, каноничная запись — «КМ-101»."""
    assert validate_equipment_id("км 101") == "КМ-101"


def test_validate_latin_lookalikes():
    """GigaChat реально возвращал «KM-101» ЛАТИНИЦЕЙ — на глаз не отличить."""
    assert validate_equipment_id("KM-101") == "КМ-101"  # здесь K и M латинские


def test_validate_rejects_unknown_id():
    """Выдуманный моделью код красиво выглядит, но в реестре его нет."""
    assert validate_equipment_id("ЗЗ-999") is None


def test_extract_json_plain_array():
    assert extract_json_array('[{"equipment_id": "КМ-101"}]') == [
        {"equipment_id": "КМ-101"}]


def test_extract_json_fenced_array():
    """Модель любит обёртку ```json ... ``` и вступление «Вот результат:»."""
    raw = 'Вот результат:\n```json\n[{"equipment_id": "КМ-101"}]\n```'
    assert extract_json_array(raw) == [{"equipment_id": "КМ-101"}]


def test_extract_json_garbage_returns_none():
    """Не JSON — честный None: вызывающий код перегенерирует батч."""
    assert extract_json_array("Не могу выполнить запрос.") is None


# ---------------------------------------------------------------- чанкинг (TODO 1)
def test_chunking_splits_text():
    """Текст длиннее размера чанка обязан разрезаться на несколько кусков."""
    chunks = chunk_text(TEXT, size=200, overlap=50)
    assert len(chunks) > 1, "текст не разрезан — chunk_text вернул один кусок"


def test_chunk_size_respected():
    chunks = chunk_text(TEXT, size=200, overlap=50)
    for c in chunks:
        assert len(c) <= 200, f"кусок длиннее заданного размера: {len(c)}"


def test_chunk_overlap_really_overlaps():
    """Соседние чанки должны пересекаться — иначе предложение на границе потеряется."""
    chunks = chunk_text(TEXT, size=200, overlap=50)
    tail = chunks[0][-50:]
    assert tail in chunks[1], "нахлёста нет: конец первого чанка не входит во второй"


def test_chunk_keeps_all_text():
    """Ни один символ не должен пропасть при нарезке."""
    chunks = chunk_text(TEXT, size=200, overlap=50)
    assert chunks[0].startswith(TEXT[:20])
    assert TEXT.rstrip()[-20:] in chunks[-1]


def test_chunk_zero_overlap_works():
    chunks = chunk_text(TEXT, size=200, overlap=0)
    assert len(chunks) > 1
    assert "".join(chunks) == TEXT


def test_chunk_overlap_bigger_than_size_rejected():
    """overlap >= size даёт нулевой шаг и вечный цикл. Такое надо ловить."""
    with pytest.raises(ValueError):
        chunk_text(TEXT, size=100, overlap=100)


def test_short_text_stays_one_chunk():
    chunks = chunk_text("Короткий текст.", size=400, overlap=100)
    assert len(chunks) == 1


# ---------------------------------------------------------------- чанк -> источник
def test_chunk_keeps_source_reference():
    """Чанк наследует doc_id и место в документе — иначе ссылку на источник
    в Модуле 4 брать будет неоткуда."""
    records = load_records()[:20]
    for chunk in build_chunks(records):
        p = chunk["payload"]
        assert p["doc_id"], "чанк без doc_id"
        assert p["page"] is not None or p["section"], (
            f"{p['doc_id']}: чанк без ссылки на страницу или раздел")


def test_chunk_id_is_stable():
    """Один и тот же чанк получает один и тот же id при каждой сборке —
    иначе повторная загрузка плодит дубликаты вместо обновления."""
    record = {"doc_id": "REGL-GEN-01", "record_no": 5,
              "page": None, "section": "5. Ремонт"}
    assert chunk_id(record, 3) == chunk_id(dict(record), 3)
    assert chunk_id(record, 3) != chunk_id(record, 4)
    # одинаковое название раздела у разных записей — не повод для совпадения id
    assert chunk_id(record, 3) != chunk_id(dict(record, record_no=7), 3)


def test_chunk_ids_are_unique():
    ids = [c["id"] for c in build_chunks(load_records())]
    assert len(ids) == len(set(ids)), "у разных чанков совпали идентификаторы"


# ---------------------------------------------------------------- контрольные вопросы
def test_questions_have_must_contain():
    """У каждого вопроса из базы указан проверяемый факт."""
    for q in QUESTIONS:
        if q["in_corpus"]:
            assert q.get("must_contain"), f"{q['id']}: не указан must_contain"
            assert q["expected"], f"{q['id']}: не указан ожидаемый документ"


def test_questions_point_to_existing_documents():
    """Каждый вопрос ссылается на документ, который в корпусе есть.

    Проверяем существование документа, а не наличие факта в нём. Факт —
    свойство ТЕКСТА, а текст у каждого свой: сгенерированный корпус пишется
    моделью заново, и она вполне может не написать про срок устранения
    неисправностей. Это не поломка — это предмет отдельного разбора в
    Занятии 6, там видно, сколько вопросов не находится и почему.
    А вот идентификаторы документов детерминированы: карточки берут id из
    реестра, инциденты нумеруются подряд, регламентов всегда три.
    """
    have = {d["doc_id"] for d in load_documents()}
    for q in QUESTIONS:
        if not q["in_corpus"]:
            continue
        assert any(d in have for d in q["expected"]), (
            f"{q['id']}: ни одного из документов {q['expected']} нет в корпусе")


def test_traps_expect_nothing():
    """У вопроса вне базы не должно быть «правильного» документа."""
    for q in QUESTIONS:
        if not q["in_corpus"]:
            assert not q["expected"], f"{q['id']}: вопрос вне базы, а expected заполнен"
            assert not q.get("must_contain"), f"{q['id']}: вопрос вне базы, а факт указан"
