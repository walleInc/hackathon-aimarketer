"""Детерминированный провайдер без внешних вызовов — для разработки и тестов."""
import json

from .base import LLMResult

class StubProvider:
    async def complete(self, system: str, messages: list[dict], json_mode: bool = False) -> LLMResult:
        last = messages[-1]["content"] if messages else ""
        if "MARKETING_WORKSPACE" in system:
            context = json.loads(last)
            sources = context.get("sources", [])
            kind = context["task"]
            data = {"summary": "Демонстрационный анализ. Для содержательных выводов подключите AI-провайдера и соберите данные.",
                    "findings": [{"title": s["title"], "detail": "Источник найден. Содержание требует проверки аналитиком.", "source_urls": [s["url"]]} for s in sources[:5]],
                    "actions": ["Собрать сопоставимые измерения публикаций через 48 часов."],
                    "limitations": ["Демонстрационный AI-провайдер: рекомендации не являются результатом исследования рынка."]}
            if kind == "hypotheses":
                data["hypotheses"] = [{"title": "Проверить подачу с вопросом аудитории", "evidence": f"В выборке {context['analytics']['sample_size']} публикаций. Эффект ещё не проверен.",
                    "action": "Подготовить два сопоставимых поста одной рубрики, один завершить вопросом.", "metric": "Реакции / просмотры через 48 часов",
                    "success": "Цель эксперимента: рост доли реакций. При малой выборке зафиксировать недостаток данных.", "duration_days": 14}]
            if kind == "strategy":
                data.update(goals=["Накопить измеримые результаты продвижения"], audiences=["Уточнить сегменты по знаниям компании"],
                    positioning="Проект: опираться на подтверждённые преимущества компании", channels=["Telegram"],
                    rubrics=["Продукт", "Экспертные советы", "Вопросы аудитории"], kpis=["Просмотры и доля реакций через 48 часов"])
            if kind == "plan":
                data["plan"] = [{"topic": f"Тема дня {i}: полезный материал о компании", "format": "Текст и изображение", "rubric": "Экспертные советы",
                    "rationale": "Демонстрационное предложение; факты взять из базы знаний", "day": i} for i in range(1, 8)]
            return LLMResult(text=json.dumps(data, ensure_ascii=False), tokens=100)
        if "ПРОВЕРКА_БРЕНДА" in last:
            return LLMResult(text=json.dumps({"ok": True, "issues": [], "fixed_text": ""}))
        from ..agent import _explicit_creation_request
        if json_mode and _explicit_creation_request(last):
            payload = {
                "action": "create_post",
                "platform": "telegram",
                "post_text": f"Тестовая публикация по запросу: {last}",
                "headline": "Тестовая публикация",
                "card_text": last[:120],
                "image_prompt": last,
                "reply": "Подготовил материал, отправил на согласование.",
            }
        elif json_mode:
            payload = {"action": "reply", "reply": f"Принято: {last}"}
        else:  # переписывание поста по комментарию
            return LLMResult(text=f"{last} (доработано)")
        return LLMResult(text=json.dumps(payload, ensure_ascii=False))

    async def generate_image(self, prompt: str, reference: bytes | None = None) -> str | None:
        return None
