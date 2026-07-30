"""
Модуль 3, Задание 9 — подготовка корпуса: чанкинг и ingestion.

В Задании 8 мы клали в базу документ целиком. Это работает на пяти документах
и разваливается на реальном корпусе: регламент на 20 страниц превращается в один
вектор, и «средний смысл всего регламента» не близок ни к одному конкретному вопросу.

Поэтому документы режут на чанки — куски по несколько абзацев. Тогда вопрос
«какая периодичность ТО у компрессора» попадает точно в тот кусок, где про это
написано, а не в документ вообще.

Два параметра решают всё:
  CHUNK_SIZE — размер куска. Слишком большой — смысл размывается.
               Слишком маленький — ответ разрывается пополам.
  OVERLAP    — нахлёст между кусками. Нужен, чтобы предложение, попавшее на границу,
               не потерялось: оно войдёт и в конец одного чанка, и в начало следующего.

ТВОЯ РАБОТА: TODO 1 (написать chunk_text) и TODO 2 (подобрать параметры).

Запуск (из папки module_03):
    python ingestion.py
"""

import argparse
import json
from pathlib import Path

from qdrant_client import QdrantClient
from qdrant_client.models import Distance, PointStruct, VectorParams
from sentence_transformers import SentenceTransformer

from corpus_loader import load_corpus
from qdrant_connect import DASHBOARD_URL, make_client

MODEL_NAME = "paraphrase-multilingual-MiniLM-L12-v2"
DB_PATH = Path(__file__).parent / "qdrant_chunks"
COLLECTION = "promtech_chunks"
QUESTIONS = json.loads(
    (Path(__file__).parent / "data" / "questions.json").read_text(encoding="utf-8")
)["questions"]


# ====================================================================
#  НАСТРОЙКИ СТУДЕНТА
# ====================================================================

# TODO 2: подбери параметры так, чтобы поиск по контрольным вопросам попадал
# в нужный документ. Прогони несколько комбинаций и запиши результаты:
#   (400, 0)   — без нахлёста, куски рвут предложения
#   (400, 100) — с нахлёстом
#   (1000, 200) — крупные куски
CHUNK_SIZE = 600
OVERLAP = 150


# ====================================================================
#  TODO 1 — ЗДЕСЬ ТЫ ПИШЕШЬ КОД
# ====================================================================

def chunk_text(text: str, size: int, overlap: int) -> list:
    """Режет текст на куски по `size` символов с нахлёстом `overlap`.

    TODO 1: сейчас функция возвращает весь текст одним куском — это заглушка.
    Нужно реализовать нарезку.

    Как это работает: идём по тексту окном длиной size, каждый следующий кусок
    начинается не там, где кончился предыдущий, а на overlap символов раньше.

        текст:  [-------------------------------------------]
        чанк 1: [----------]
        чанк 2:        [----------]
        чанк 3:               [----------]
                       ^^^^ нахлёст

    Алгоритм:
      1. start = 0, chunks = []
      2. Пока start < len(text):
           - взять кусок text[start : start + size], добавить в chunks
           - сдвинуть start на (size - overlap)
      3. Вернуть chunks

    Осторожно с двумя вещами:
      - если overlap >= size, шаг станет нулевым или отрицательным -> вечный цикл.
        Проверь это в начале и брось ValueError.
      - последний кусок может быть коротким — это нормально, его тоже возвращаем.
      - пустые куски (одни пробелы) возвращать не нужно.
    """
    if overlap >= size:
        raise ValueError(
            f"overlap ({overlap}) должен быть меньше size ({size}): "
            f"иначе шаг окна нулевой и нарезка зациклится"
        )

    chunks = []
    step = size - overlap
    start = 0

    while start < len(text):
        piece = text[start:start + size]
        if piece.strip():
            chunks.append(piece)
        start += step

    return chunks


# ====================================================================
#  КОД НИЖЕ УЖЕ РАБОТАЕТ — менять не нужно
# ====================================================================

def build_chunk_index(client: QdrantClient, model: SentenceTransformer) -> tuple:
    """Режет весь корпус на чанки и индексирует их."""
    docs = load_corpus()

    if client.collection_exists(COLLECTION):
        client.delete_collection(COLLECTION)
    client.create_collection(
        collection_name=COLLECTION,
        vectors_config=VectorParams(
            size=model.get_embedding_dimension(),
            distance=Distance.COSINE,
        ),
    )

    points = []
    for doc in docs:
        chunks = chunk_text(doc["text"], CHUNK_SIZE, OVERLAP)
        for j, chunk in enumerate(chunks):
            points.append(PointStruct(
                id=len(points),
                vector=model.encode(chunk).tolist(),
                payload={
                    "doc_id": doc["doc_id"],
                    "type": doc["type"],
                    "title": doc["title"],
                    "chunk_no": j,
                    "text": chunk,
                },
            ))

    client.upsert(collection_name=COLLECTION, points=points)
    return len(docs), len(points)


def check_questions(client, model) -> tuple:
    """Прогоняет контрольные вопросы и смотрит, находится ли нужный документ."""
    print("\n" + "=" * 88)
    print("КОНТРОЛЬНЫЕ ВОПРОСЫ")
    print("=" * 88)

    hit, total = 0, 0
    width = max(len(q["question"]) for q in QUESTIONS)
    for q in QUESTIONS:
        found = client.query_points(
            collection_name=COLLECTION,
            query=model.encode(q["question"]).tolist(),
            limit=3,
        ).points
        top_docs = [p.payload["doc_id"] for p in found]
        best = found[0].score if found else 0.0

        if q["in_corpus"]:
            total += 1
            ok = any(d in q["expected"] for d in top_docs)
            hit += ok
            mark = "OK" if ok else " X"
            print(f"  {mark}  {q['question']:<{width}} score={best:.3f}")
            print(f"      нашли: {', '.join(top_docs)}   ждали: {', '.join(q['expected'])}")
        else:
            print(f"  ??  {q['question']:<{width}} score={best:.3f}  <- вопроса нет в базе")
            print(f"      нашли: {', '.join(top_docs)}   (ответа быть НЕ должно)")

    print(f"\n  Попаданий по вопросам из базы: {hit}/{total}")
    return hit, total


def main():
    args = argparse.ArgumentParser(description="Чанкинг и загрузка корпуса в Qdrant")
    args.add_argument("--embedded", action="store_true",
                      help="резервный режим без Docker (база в локальной папке)")
    args = args.parse_args()

    client = make_client(args.embedded, DB_PATH)
    print("Загружаю модель...")
    model = SentenceTransformer(MODEL_NAME)

    try:
        docs, chunks = build_chunk_index(client, model)
        print(f"\nCHUNK_SIZE={CHUNK_SIZE}, OVERLAP={OVERLAP}")
        print(f"Документов: {docs}  ->  чанков: {chunks}")
        if not args.embedded:
            print(f"Коллекция «{COLLECTION}» видна в веб-интерфейсе: {DASHBOARD_URL}")

        if chunks == docs:
            print("\n  chunk_text пока возвращает документ целиком (TODO 1 не сделан).")
            print("  Чанков ровно столько же, сколько документов — нарезки не произошло.")

        check_questions(client, model)
    finally:
        client.close()


if __name__ == "__main__":
    main()
