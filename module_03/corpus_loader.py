"""
Загрузчик учебного корпуса ПромТеха. Менять не нужно.

Каждый документ корпуса начинается с блока метаданных (frontmatter):

    ---
    doc_id: REG-TO-04
    type: регламент
    equipment: [КМ-101, НМ-205]
    version: 4.2
    ---

Метаданные — не украшение. По ним потом фильтруется поиск («только регламенты»,
«только по КМ-101») и по ним же студент понимает, ОТКУДА пришёл ответ.
"""

from pathlib import Path

import yaml

CORPUS_DIR = Path(__file__).parent / "data" / "corpus"


def parse_document(path: Path) -> dict:
    """Разбирает один файл корпуса на метаданные и текст."""
    raw = path.read_text(encoding="utf-8")

    if not raw.startswith("---"):
        raise ValueError(f"{path.name}: нет блока метаданных в начале файла")

    _, frontmatter, text = raw.split("---", 2)
    meta = yaml.safe_load(frontmatter)

    return {
        "doc_id": meta["doc_id"],
        "type": meta["type"],
        "title": meta["title"],
        "equipment": meta.get("equipment", []),
        "version": str(meta.get("version", "")),
        "date": str(meta.get("date", "")),
        "source": path.name,
        "text": text.strip(),
    }


def load_corpus() -> list:
    """Возвращает список всех документов корпуса."""
    files = sorted(CORPUS_DIR.glob("*.md"))
    if not files:
        raise FileNotFoundError(f"Корпус пуст: в {CORPUS_DIR} нет файлов .md")
    return [parse_document(f) for f in files]


if __name__ == "__main__":
    docs = load_corpus()
    print(f"Документов в корпусе: {len(docs)}\n")
    for d in docs:
        equipment = ", ".join(d["equipment"]) if d["equipment"] else "—"
        print(f"  {d['doc_id']:<15} {d['type']:<20} {len(d['text']):>5} симв.  [{equipment}]")
