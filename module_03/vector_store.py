"""
Модуль 3, Задание 8 — локальное векторное хранилище.

В Задании 7 мы считали близость двух фраз вручную. Так можно сравнить 2 текста,
но не 10 000: считать косинус со всем корпусом на каждый запрос — слишком долго.

Векторное хранилище решает ровно эту задачу: складывает векторы, ищет ближайшие
и умеет фильтровать по метаданным («ищи только в регламентах», «только по КМ-101»).

Qdrant работает в Docker — это настоящий сервер с веб-интерфейсом
(http://localhost:6333/dashboard), в котором видно коллекции и документы.
Перед запуском подними контейнер — команда в qdrant_connect.py.
Если Docker поставить не удалось — резервный режим: python vector_store.py --embedded

ТВОЯ РАБОТА: TODO 1-3.

Запуск (из папки module_03):
    python vector_store.py
"""

import argparse
from pathlib import Path

from qdrant_client import QdrantClient
from qdrant_client.models import (
    Distance, FieldCondition, Filter, MatchValue, PointStruct, VectorParams,
)
from sentence_transformers import SentenceTransformer

from corpus_loader import load_corpus
from qdrant_connect import DASHBOARD_URL, make_client

MODEL_NAME = "paraphrase-multilingual-MiniLM-L12-v2"
DB_PATH = Path(__file__).parent / "qdrant_db"
COLLECTION = "promtech"


# ====================================================================
#  НАСТРОЙКИ СТУДЕНТА
# ====================================================================

# TODO 1: запросы, которые прогоняем по базе. Добавь минимум 2 своих.
QUERIES = [
    "что делать если лента конвейера буксует",
    "как часто обслуживать компрессор",
    "___",
]

# TODO 2: порог уверенности. Если лучший score ниже этого числа — считаем,
# что в базе ответа нет, и честно об этом говорим.
# Подбери его по результатам прогона: посмотри, какой score у осмысленных
# попаданий, а какой — у мусорных. Начни с 0.3 и подвигай.
MIN_SCORE = 0.3


# ====================================================================
#  КОД НИЖЕ УЖЕ РАБОТАЕТ, кроме одной функции — см. TODO 3
# ====================================================================

def build_index(client: QdrantClient, model: SentenceTransformer) -> int:
    """Создаёт коллекцию заново и загружает в неё документы корпуса."""
    docs = load_corpus()

    # чистый старт: старую коллекцию сносим, создаём заново
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
    for i, doc in enumerate(docs):
        vector = model.encode(doc["text"]).tolist()
        points.append(PointStruct(
            id=i,
            vector=vector,
            payload={
                "doc_id": doc["doc_id"],
                "type": doc["type"],          # регламент / инструкция / FAQ / ...
                "equipment": doc["equipment"],  # список: [КМ-101, НМ-205]
                "title": doc["title"],
                "text": doc["text"][:400],
            },
        ))

    client.upsert(collection_name=COLLECTION, points=points)
    return len(points)


def search(client, model, query: str, doc_type: str = None, limit: int = 3):
    """Ищет в базе документы, близкие к запросу.

    TODO 3: сейчас функция игнорирует фильтр doc_type и всегда ищет по всей базе.
    Нужно: если doc_type задан — искать ТОЛЬКО среди документов этого типа.

    Зачем это нужно: инженер спрашивает «что говорит регламент», и ответ из
    журнала инцидентов ему не подходит, даже если он текстуально похож.

    Что сделать:
      1. Если doc_type is None — оставить query_filter=None (как сейчас).
      2. Иначе собрать фильтр:
             Filter(must=[FieldCondition(key="type", match=MatchValue(value=doc_type))])
      3. Передать его в client.query_points(..., query_filter=...)
    """
    vector = model.encode(query).tolist()

    query_filter = None   # <- заменить на фильтр по doc_type

    result = client.query_points(
        collection_name=COLLECTION,
        query=vector,
        query_filter=query_filter,
        limit=limit,
    )
    return result.points


def show(hits, query: str):
    print(f"\n  Запрос: «{query}»")
    if not hits:
        print("    ничего не найдено")
        return
    for h in hits:
        flag = " " if h.score >= MIN_SCORE else "  (ниже порога)"
        print(f"    {h.score:5.3f}  [{h.payload['type']:<18}] {h.payload['title'][:44]}{flag}")

    if hits[0].score < MIN_SCORE:
        print(f"    -> лучший score {hits[0].score:.3f} < порога {MIN_SCORE}: "
              f"считаем, что ответа в базе НЕТ")


def main():
    args = argparse.ArgumentParser(description="Векторное хранилище ПромТеха")
    args.add_argument("--embedded", action="store_true",
                      help="резервный режим без Docker (база в локальной папке)")
    args = args.parse_args()

    if any("___" in q for q in QUERIES):
        print("Сначала добавь свои запросы (TODO 1) — там остались ___.")
        return

    client = make_client(args.embedded, DB_PATH)
    print("Загружаю модель (первый раз — несколько минут)...")
    model = SentenceTransformer(MODEL_NAME)

    try:
        count = build_index(client, model)
        print(f"Проиндексировано документов: {count}")
        if not args.embedded:
            print(f"Коллекция «{COLLECTION}» видна в веб-интерфейсе: {DASHBOARD_URL}")

        print("\n" + "=" * 78)
        print("ПОИСК ПО ВСЕЙ БАЗЕ")
        print("=" * 78)
        for q in QUERIES:
            show(search(client, model, q), q)

        print("\n" + "=" * 78)
        print("ПОИСК С ФИЛЬТРОМ: только регламенты")
        print("=" * 78)
        for q in QUERIES:
            show(search(client, model, q, doc_type="регламент"), q)

        print("\n" + "=" * 78)
        print("ВОПРОС ВНЕ БАЗЫ")
        print("=" * 78)
        show(search(client, model, "как оформить отпуск"), "как оформить отпуск")
    finally:
        client.close()


if __name__ == "__main__":
    main()
