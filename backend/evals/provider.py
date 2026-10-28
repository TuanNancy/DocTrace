"""Deterministic answer provider for the offline smoke evaluation.

It extracts sentences from the supplied context, preserving the context's
numeric citation IDs. It is intentionally simple: the smoke run tests prompt,
context packing, citation lookup and scoring plumbing without pretending to
measure live model quality.
"""
from __future__ import annotations

import re
from typing import AsyncIterator, Dict, List, Optional

from app.ai.document_summary import is_document_overview
from app.providers.base import ChatProvider
from app.providers.usage import ProviderCall
from evals.retrieval import coverage_terms, terms

_BLOCK = re.compile(
    r"\[(\d+)\] \[Trang (\d+)\]\n(.*?)(?=\n\n\[(?:\d+)\] \[Trang |\Z)", re.DOTALL,
)
_SENTENCE = re.compile(r"(?<=[.!?])\s+|\n+")
_REFUSALS = {
    "vi": "Tài liệu không có thông tin để trả lời câu hỏi này.",
    "en": "The document does not contain information to answer this question.",
}


def _sentences(text: str) -> list[str]:
    return [part.strip() for part in _SENTENCE.split(text) if part.strip()]


class ExtractiveProvider(ChatProvider):
    def __init__(self):
        super().__init__(api_key="", model="extractive-smoke")
        self.calls = 0

    def _answer(self, query: str, context: str, language: str) -> str:
        blocks = [
            (int(match.group(1)), int(match.group(2)), match.group(3).strip())
            for match in _BLOCK.finditer(context)
            if match.group(3).strip()
        ]
        if not blocks:
            return _REFUSALS[language]

        if is_document_overview(query):
            return " ".join(
                f"{_sentences(text)[0]} [{citation}]"
                for citation, _, text in blocks if _sentences(text)
            )

        query_terms = coverage_terms(query)
        if not query_terms:
            return _REFUSALS[language]

        candidates = []
        for citation, page, text in blocks:
            block_terms = coverage_terms(text)
            coverage = len(query_terms & block_terms) / len(query_terms)
            if coverage < 0.5:
                continue
            for sentence in _sentences(text):
                overlap = len(query_terms & set(terms(sentence)))
                if overlap:
                    candidates.append((overlap, page, citation, sentence))
        if not candidates:
            return _REFUSALS[language]

        candidates.sort(key=lambda item: (-item[0], item[1], item[2]))
        floor = max(1, candidates[0][0] * 0.5)
        chosen, seen = [], set()
        for overlap, _, citation, sentence in candidates:
            if overlap < floor or sentence in seen:
                continue
            seen.add(sentence)
            chosen.append(f"{sentence} [{citation}]")
            if len(chosen) >= 4:
                break
        return " ".join(chosen) if chosen else _REFUSALS[language]

    def _language(self, query: str) -> str:
        return "vi" if any(ord(char) > 127 for char in query) else "en"

    async def generate_completion(
        self, messages: List[Dict[str, str]], max_tokens: Optional[int] = None,
        temperature: Optional[float] = None, *, usage: Optional[ProviderCall] = None, **kwargs,
    ) -> str:
        query, context = _split_messages(messages)
        self.calls += 1
        return self._answer(query, context, self._language(query))

    async def stream_completion(
        self, messages: List[Dict[str, str]], max_tokens: Optional[int] = None,
        temperature: Optional[float] = None, *, usage: Optional[ProviderCall] = None, **kwargs,
    ) -> AsyncIterator[str]:
        yield await self.generate_completion(
            messages, max_tokens=max_tokens, temperature=temperature, usage=usage, **kwargs,
        )


def _split_messages(messages: List[Dict[str, str]]) -> tuple[str, str]:
    user = next((message.get("content", "") for message in reversed(messages)
                 if message.get("role") == "user"), "")
    marker = "\n\nQuestion: "
    if marker in user:
        context, query = user.split(marker, 1)
        if context.startswith("Context:\n"):
            context = context[len("Context:\n"):]
        return query.strip(), context.strip()
    return user.strip(), ""
