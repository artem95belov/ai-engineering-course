"""
Модуль 3, Занятие 5 — парсинг публичных нормативных документов.

RAG-система отвечает по документам, а не по памяти модели. Значит, первый шаг —
собрать корпус: скачать реальные нормативные документы (ФНП, ГОСТ, регламенты)
и вытащить из них текст.

PDF бывают двух видов:
  - с текстовым слоем — текст можно извлечь программно;
  - скан без текстового слоя — там только картинки страниц. Такие файлы мы
    ОТБРАКОВЫВАЕМ с понятным сообщением (распознавание сканов — OCR — отдельная
    задача, в этом задании её нет).

ТВОЯ РАБОТА: TODO 1 (SOURCES), TODO 2 (clean_text), TODO 3 (has_text_layer).

Два режима запуска (из папки module_03):
    python parse_documents.py                  # скачать источники из SOURCES по URL
    python parse_documents.py --local <папка>  # обработать PDF из локальной папки
                                               # (если сайты недоступны — PDF раздаёт
                                               # преподаватель)

Результат: файлы data/corpus/ext_*.md с метаданными (frontmatter) и текстом.
"""

import argparse
import re
import sys
import urllib.parse
from pathlib import Path

import requests
from pypdf import PdfReader

# Из длинного документа берём не больше 50 страниц: для учебного корпуса
# этого достаточно, а индексация не растягивается на часы.
MAX_PAGES = 50

# Если на страницу приходится меньше этого числа символов, текстового слоя
# в PDF скорее всего нет (это скан) — файл отбраковываем.
MIN_CHARS_PER_PAGE = 200

BASE_DIR = Path(__file__).parent
DOWNLOAD_DIR = BASE_DIR / "data" / "downloads"
CORPUS_DIR = BASE_DIR / "data" / "corpus"

# ====================================================================
#  ИСТОЧНИКИ КОРПУСА — TODO 1
# ====================================================================
# TODO 1: сейчас заполнена только первая запись — это образец.
# Заполни три остальные. Все значения есть в задании, в таблице
# «Источники корпуса» — переноси оттуда, выдумывать ничего не надо.
#
# Из чего состоит запись и почему поля важны:
#   url    — ПРЯМАЯ ссылка на файл PDF. Если ссылка ведёт на страницу
#            просмотрщика правовой базы, скачается HTML, и парсер его не
#            возьмёт: PdfReader упадёт на первом же байте;
#   file   — под каким именем PDF ляжет в data/downloads. По этому же имени
#            собирается имя файла корпуса: ext_fnp461.pdf -> ext_fnp461.md;
#   doc_id — идентификатор документа в корпусе. Обязан быть уникальным:
#            именно им ассистент потом ссылается на источник ответа;
#   type   — тип документа. По нему в Занятии 6 фильтруется поиск, поэтому
#            у всех публичных норм он одинаковый: «нормативный документ»;
#   title  — человекочитаемое название: попадёт в метаданные и в выдачу поиска.
#
# doc_id, type и title — это и есть метаданные корпуса. Мы кладём в базу не
# голый текст, а текст с паспортом: без него нельзя ни отфильтровать поиск,
# ни сослаться на источник.
# --------------------------------------------------------------------
SOURCES = [
    {
        "url": ("http://mos.gosnadzor.ru/about/documents/"
                "Приказ РТН № 461 от 26.11.2020.pdf"),
        "file": "ext_fnp461.pdf",
        "doc_id": "EXT-FNP-461",
        "type": "нормативный документ",
        "title": "ФНП: Правила безопасности при работе с подъёмными сооружениями "
                 "(приказ Ростехнадзора № 461)",
    },
    {
        "url": "https://files.stroyinf.ru/Data/784/78426.pdf",
        "file": "ext_gost32601.pdf",
        "doc_id": "EXT-GOST-32601",
        "type": "нормативный документ",
        "title": "ГОСТ 32601-2022: Насосы центробежные для нефтяной, "
                 "нефтехимической и газовой промышленности",
    },
    {
        "url": "https://gostbank.metaltorg.ru/data/norms_/jr/12.pdf",
        "file": "ext_reglament_truboprovody.pdf",
        "doc_id": "EXT-REGL-TRUB",
        "type": "нормативный документ",
        "title": "Регламент технического обслуживания и ремонта "
                 "технологических трубопроводов",
    },
    {
        "url": "https://www.perco.ru/download/documentation/rus/Reglament-TO.pdf",
        "file": "ext_reglament_to.pdf",
        "doc_id": "EXT-REGL-TO",
        "type": "нормативный документ",
        "title": "Регламент технического обслуживания оборудования (PERCo)",
    },
]

# Поля записи источника — по ним проверяется, что TODO 1 сделан.
SOURCE_FIELDS = ("url", "file", "doc_id", "type", "title")


def unfilled_sources() -> list:
    """Номера записей SOURCES (с единицы), в которых остались пустые поля."""
    return [i for i, s in enumerate(SOURCES, 1)
            if any(not str(s.get(f, "")).strip() for f in SOURCE_FIELDS)]


# ====================================================================
#  СКАЧИВАНИЕ
# ====================================================================

def download(url: str, dest: Path) -> bool:
    """Скачивает файл по URL. Возвращает True при успехе.

    Тонкости, ради которых функция длиннее одной строки:
      - в URL бывают русские буквы и пробелы — их надо закодировать;
      - у части госсайтов сертификаты не из стандартных корневых центров,
        поэтому при ошибке SSL пробуем ещё раз без проверки сертификата
        (для публичных документов это допустимо);
      - сайт может быть недоступен — тогда честно сообщаем и идём дальше.
    """
    if dest.exists() and dest.stat().st_size > 0:
        print(f"    уже скачан: {dest.name} ({dest.stat().st_size // 1024} КБ)")
        return True

    safe_url = urllib.parse.quote(url, safe=":/%?&=")
    headers = {"User-Agent": "Mozilla/5.0 (learning-project; corpus-builder)"}

    for verify in (True, False):
        try:
            resp = requests.get(safe_url, headers=headers, timeout=60, verify=verify)
            resp.raise_for_status()
            dest.write_bytes(resp.content)
            note = "" if verify else "  (сертификат сайта не проверялся)"
            print(f"    скачан: {dest.name} ({len(resp.content) // 1024} КБ){note}")
            return True
        except requests.exceptions.SSLError:
            if verify:
                continue  # вторая попытка — без проверки сертификата
            print(f"    ОШИБКА SSL: {url}")
            return False
        except requests.exceptions.RequestException as e:
            print(f"    НЕ СКАЧАЛСЯ: {url}\n    причина: {e}")
            return False
    return False


# ====================================================================
#  ИЗВЛЕЧЕНИЕ ТЕКСТА — TODO 2 и TODO 3
# ====================================================================

def clean_text(text: str) -> str:
    """Приводит извлечённый из PDF текст в порядок.

    TODO 2: сейчас функция возвращает текст как есть — это заглушка.
    После pypdf в тексте остаётся мусор: цепочки пробелов внутри строк
    и стопки пустых строк. В векторную базу такой текст класть нельзя —
    мусор попадёт в эмбеддинги и в чанки.

    Что сделать (модуль re уже импортирован):
      1. Разбить текст на строки (text.splitlines()).
      2. В каждой строке схлопнуть последовательности пробелов и табов
         в один пробел: re.sub(r"[ \\t]+", " ", line) — и обрезать края .strip().
      3. Склеить строки обратно через "\\n".
      4. Три и больше переводов строки подряд заменить на два:
         re.sub(r"\\n{3,}", "\\n\\n", ...) — это сохранит границы абзацев.
      5. Обрезать края всего текста .strip() и вернуть.
    """
    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in text.splitlines()]
    cleaned = "\n".join(lines)
    return re.sub(r"\n{3,}", "\n\n", cleaned).strip()


def extract_text(pdf_path: Path) -> tuple:
    """Извлекает текст из PDF (не больше MAX_PAGES страниц).

    Возвращает (текст, число_обработанных_страниц, всего_страниц).
    Если текстового слоя нет — возвращает ("", ...): решение об отбраковке
    принимает вызывающий код.
    """
    reader = PdfReader(str(pdf_path))
    total = len(reader.pages)
    pages = reader.pages[:MAX_PAGES]

    chunks = []
    for page in pages:
        # extraction_mode="layout" сохраняет пробелы между словами:
        # обычный режим на многих русских PDF рвёт каждое слово на свою строку.
        chunks.append(page.extract_text(extraction_mode="layout") or "")

    return clean_text("\n\n".join(chunks)), len(pages), total


def has_text_layer(text: str, pages: int) -> bool:
    """Скан или настоящий текст?

    TODO 3: сейчас функция всем отвечает «текст есть» — это заглушка.
    Скан-PDF она пропустит в корпус, и в базе окажется пустой документ.

    Идея проверки: у настоящего текста на страницу приходятся тысячи
    символов, у скана pypdf вытаскивает от силы номера страниц.
    Порог уже подобран — константа MIN_CHARS_PER_PAGE (200).

    Что сделать:
      1. Если страниц 0 — текстового слоя точно нет, вернуть False.
      2. Посчитать, сколько символов приходится на страницу: len(text) / pages.
      3. Вернуть True, если символов на страницу не меньше MIN_CHARS_PER_PAGE.
    """
    return pages > 0 and len(text) / pages >= MIN_CHARS_PER_PAGE


# ====================================================================
#  СБОРКА ФАЙЛА КОРПУСА
# ====================================================================

def write_corpus_file(meta: dict, text: str, pages: int, total: int) -> Path:
    """Пишет документ корпуса: frontmatter с метаданными + текст."""
    out = CORPUS_DIR / (Path(meta["file"]).stem + ".md")
    pages_note = f"{pages} из {total}" if total > pages else str(total)
    title = meta["title"].replace('"', "'")  # кавычки нужны: в заголовке бывает «:»
    out.write_text(
        "---\n"
        f"doc_id: {meta['doc_id']}\n"
        f"type: {meta['type']}\n"
        f'title: "{title}"\n'
        f'source: "{meta.get("url", meta["file"])}"\n'
        f"pages: {pages_note}\n"
        "---\n\n"
        f"{text}\n",
        encoding="utf-8",
    )
    return out


def process_pdf(pdf_path: Path, meta: dict) -> bool:
    """Полный цикл для одного PDF: текст -> проверка слоя -> файл корпуса."""
    try:
        text, pages, total = extract_text(pdf_path)
    except Exception as e:
        print(f"    ОТБРАКОВАН: {pdf_path.name} — файл не читается как PDF ({e})")
        return False

    if not has_text_layer(text, pages):
        print(f"    ОТБРАКОВАН: {pdf_path.name} — в PDF нет текстового слоя "
              f"(это скан: {len(text)} симв. на {pages} стр.).")
        print("    Такой файл нужно сначала распознать (OCR) — "
              "в этом задании сканы не обрабатываем.")
        return False

    out = write_corpus_file(meta, text, pages, total)
    print(f"    OK: {out.name} — {pages} стр., {len(text)} символов")
    return True


# ====================================================================
#  РЕЖИМЫ ЗАПУСКА
# ====================================================================

def run_from_urls() -> tuple:
    """Режим по умолчанию: скачать источники из SOURCES и обработать."""
    DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)
    ok, rejected = 0, 0
    for meta in SOURCES:
        print(f"\n[{meta['doc_id']}] {meta['title']}")
        pdf_path = DOWNLOAD_DIR / meta["file"]
        if not download(meta["url"], pdf_path):
            rejected += 1
            continue
        if process_pdf(pdf_path, meta):
            ok += 1
        else:
            rejected += 1
    return ok, rejected


def run_from_dir(folder: Path) -> tuple:
    """Режим --local: обработать все PDF из локальной папки."""
    pdfs = sorted(folder.glob("*.pdf"))
    if not pdfs:
        print(f"В папке {folder} нет PDF-файлов.")
        return 0, 0

    ok, rejected = 0, 0
    for i, pdf_path in enumerate(pdfs, 1):
        print(f"\n[{i}/{len(pdfs)}] {pdf_path.name}")
        # Известным файлам (совпало имя с SOURCES) оставляем их метаданные,
        # остальным — собираем метаданные из имени файла.
        meta = next(
            (s for s in SOURCES if s["file"] == pdf_path.name),
            {
                "file": pdf_path.name,
                "doc_id": f"EXT-LOCAL-{i:02d}",
                "type": "нормативный документ",
                "title": pdf_path.stem.replace("_", " ").replace("-", " "),
            },
        )
        if process_pdf(pdf_path, meta):
            ok += 1
        else:
            rejected += 1
    return ok, rejected


def main():
    parser = argparse.ArgumentParser(description="Парсинг PDF в учебный корпус")
    parser.add_argument("--local", metavar="ПАПКА",
                        help="взять PDF из локальной папки вместо скачивания")
    args = parser.parse_args()

    CORPUS_DIR.mkdir(parents=True, exist_ok=True)

    print("=" * 78)
    print(f"ПАРСИНГ ДОКУМЕНТОВ В КОРПУС (не больше {MAX_PAGES} страниц с документа)")
    print("=" * 78)

    empty = unfilled_sources()
    if empty and not args.local:
        print()
        print("TODO 1 не сделан: в списке SOURCES остались пустые поля.")
        print(f"Не заполнены записи: {', '.join(map(str, empty))} из {len(SOURCES)}.")
        print("Возьми значения из таблицы «Источники корпуса» в задании и")
        print("заполни их по образцу первой записи. Поля: "
              + ", ".join(SOURCE_FIELDS) + ".")
        sys.exit(1)

    if args.local:
        folder = Path(args.local)
        if not folder.is_dir():
            print(f"Папка не найдена: {folder}")
            sys.exit(1)
        ok, rejected = run_from_dir(folder)
    else:
        ok, rejected = run_from_urls()

    print("\n" + "=" * 78)
    print(f"ИТОГ: в корпус попало {ok}, отбраковано/не скачалось {rejected}")
    print(f"Файлы корпуса: {CORPUS_DIR}")
    print("=" * 78)


if __name__ == "__main__":
    main()
