"""
Тесты Задания 4. Проверяют поведение fallback БЕЗ обращения к API
(настоящие вызовы подменяются заглушками — токены не тратятся).

Запуск из папки module_01:
    pytest test_m1.py -v

Пока ask_llm не дописан (TODO 5), тест fallback будет падать — это нормально.
После правильной реализации все 3 теста должны стать зелёными.
"""

import llm_client


def fake_answer(text: str) -> dict:
    """Ответ-заглушка в том же формате, что возвращают call_gigachat/call_huggingface."""
    return {
        "answer": text,
        "prompt_tokens": 10,
        "completion_tokens": 20,
        "total_tokens": 30,
        "finish_reason": "stop",
    }


def test_primary_used_when_gigachat_ok(monkeypatch):
    """Если GigaChat работает — отвечает именно он, резерв не трогаем."""
    monkeypatch.setattr(llm_client, "call_gigachat", lambda q: fake_answer("основной ответ"))

    def hf_must_not_be_called(question):
        raise AssertionError("HuggingFace не должен вызываться, пока GigaChat работает")

    monkeypatch.setattr(llm_client, "call_huggingface", hf_must_not_be_called)

    result, provider, latency = llm_client.ask_llm("любой вопрос")

    assert provider == "GigaChat"
    assert result["answer"] == "основной ответ"
    assert isinstance(latency, float)


def test_fallback_switches_to_huggingface(monkeypatch):
    """Если GigaChat упал — ответ должен прийти от HuggingFace, а не исключение."""

    def broken_gigachat(question):
        raise RuntimeError("503 Service Unavailable (тест)")

    monkeypatch.setattr(llm_client, "call_gigachat", broken_gigachat)
    monkeypatch.setattr(llm_client, "call_huggingface", lambda q: fake_answer("резервный ответ"))

    result, provider, latency = llm_client.ask_llm("любой вопрос")

    assert provider == "HuggingFace"
    assert result["answer"] == "резервный ответ"
    assert isinstance(latency, float)


def test_invalid_key_triggers_fallback(monkeypatch):
    """Неверный ключ (401) — это тоже повод уйти на резерв, а не упасть."""

    def unauthorized(question):
        raise ValueError("401 Unauthorized: неверный GIGACHAT_CREDENTIALS")

    monkeypatch.setattr(llm_client, "call_gigachat", unauthorized)
    monkeypatch.setattr(llm_client, "call_huggingface", lambda q: fake_answer("резервный ответ"))

    result, provider, _ = llm_client.ask_llm("любой вопрос")

    assert provider == "HuggingFace"
    assert result["total_tokens"] == 30
