# AI Engineering Course

Учебные проекты курса «ИИ в ПромТехе»: вызов LLM, промпт-дизайн,
структурированные ответы. Основной провайдер — GigaChat, резервный — HuggingFace.

## Установка

```bash
python -m venv .venv
.venv\Scripts\activate
pip install python-dotenv==1.0.1 gigachat==0.1.38 openai==1.35.0 pytest==8.2.2
```

Ключи — в `.env` в корне проекта (в Git не коммитится).

## Запуск

```bash
cd module_01
python llm_client.py
pytest test_m1.py -v
```

## Troubleshooting

### 'ascii' codec can't encode characters`
**Что видел:** ошибка при запуске после того, как вписал сломанный ключ.
**Почему:** в `GIGACHAT_CREDENTIALS` попали русские буквы, а ключ уходит в
HTTP-заголовок, где допустим только латинский текст.
**Что сделал:** вернул настоящий ключ (латиница + цифры). Заодно убедился, что
благодаря fallback скрипт не упал, а ответил через `[HuggingFace]`.

### `403 ... insufficient permissions to call Inference Providers` (HuggingFace)
**Что видел:** резервный провайдер не отвечал, ошибка 403.
**Почему:** токен HuggingFace создан без права на inference.
**Что сделал:** пересоздал токен — Fine-grained → Inference →
галочка «Make calls to Inference Providers».
