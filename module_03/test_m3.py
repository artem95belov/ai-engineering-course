"""
Тесты Модуля 3 (занятия 5-6). Работают БЕЗ загрузки модели и без обращения
к сети: ответы модели в тестах заменены заглушками.

Запуск из папки module_03:
    pytest test_m3.py -v

На starter-файлах часть тестов падает — это нормально: они закрываются
по мере выполнения TODO. После правильного решения все должны стать зелёными.
"""

import json

import pytest

from corpus_loader import load_corpus
from generate_corpus import REGISTRY, extract_json_array, validate_equipment_id
from ingestion import chunk_text
from parse_documents import clean_text, has_text_layer

TEXT = "".join(f"Предложение номер {i}. " for i in range(1, 41))  # ~800 символов
REGISTRY_IDS = {item["id"] for item in REGISTRY}


# ---------------------------------------------------------------- корпус
def test_corpus_loads():
    docs = load_corpus()
    assert len(docs) >= 20, ("в корпусе должно быть минимум 20 документов "
                             "(4 спарсенных + карточки + инциденты + регламенты)")


def test_every_doc_has_metadata():
    """Без метаданных нельзя ни отфильтровать поиск, ни сослаться на источник."""
    for doc in load_corpus():
        assert doc["doc_id"], f"{doc['source']}: нет doc_id"
        assert doc["type"], f"{doc['source']}: нет типа документа"
        assert doc["title"], f"{doc['source']}: нет заголовка"
        assert doc["text"], f"{doc['source']}: пустой текст"


def test_doc_ids_are_unique():
    ids = [d["doc_id"] for d in load_corpus()]
    assert len(ids) == len(set(ids)), f"дубли doc_id: {ids}"


def test_corpus_has_all_required_types():
    """Корпус занятия 5: публичные нормы + три типа сгенерированных документов."""
    types = {d["type"] for d in load_corpus()}
    for required in ["нормативный документ", "карточка оборудования",
                     "журнал инцидентов", "регламент"]:
        assert required in types, f"в корпусе нет документа типа «{required}»"


def test_equipment_ids_from_registry():
    """Идентификаторы проверяем не «по виду», а по реестру (см. М2):
    единого формата кодов оборудования в промышленности не существует."""
    for doc in load_corpus():
        for eq in doc["equipment"]:
            assert eq in REGISTRY_IDS, (
                f"{doc['doc_id']}: оборудование «{eq}» отсутствует в реестре")


# ---------------------------------------------------------------- парсер (TODO 1-2)
def test_clean_text_collapses_spaces():
    """pypdf оставляет цепочки пробелов — в корпус они попадать не должны."""
    assert clean_text("Насос   мембранный\t НМ-205") == "Насос мембранный НМ-205"


def test_clean_text_collapses_blank_lines():
    """Стопка пустых строк схлопывается до одной границы абзаца."""
    assert clean_text("Раздел 1.\n\n\n\n\nРаздел 2.") == "Раздел 1.\n\nРаздел 2."


def test_text_layer_accepted():
    """Нормальный документ: тысячи символов на страницу."""
    assert has_text_layer("х" * 10_000, pages=5) is True


def test_scan_is_rejected():
    """Скан: pypdf вытаскивает от силы номера страниц."""
    assert has_text_layer("стр. 1  стр. 2", pages=5) is False


def test_zero_pages_rejected():
    assert has_text_layer("", pages=0) is False


# ---------------------------------------------------------------- генератор (TODO 3-4)
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


def test_overlap_really_overlaps():
    """Соседние чанки должны пересекаться — иначе предложение на границе потеряется."""
    chunks = chunk_text(TEXT, size=200, overlap=50)
    tail = chunks[0][-50:]
    assert tail in chunks[1], "нахлёста нет: конец первого чанка не входит во второй"


def test_no_text_is_lost():
    """Ни один символ не должен пропасть при нарезке."""
    chunks = chunk_text(TEXT, size=200, overlap=50)
    assert chunks[0].startswith(TEXT[:20])
    assert TEXT.rstrip()[-20:] in chunks[-1]


def test_zero_overlap_works():
    chunks = chunk_text(TEXT, size=200, overlap=0)
    assert len(chunks) > 1
    assert "".join(chunks) == TEXT


def test_overlap_bigger_than_size_is_rejected():
    """overlap >= size даёт нулевой шаг и вечный цикл. Такое надо ловить."""
    with pytest.raises(ValueError):
        chunk_text(TEXT, size=100, overlap=100)


def test_short_text_stays_one_chunk():
    chunks = chunk_text("Короткий текст.", size=400, overlap=100)
    assert len(chunks) == 1
