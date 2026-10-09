"""Grounded answer generation with Claude's search-result citations (streaming)."""

from __future__ import annotations

import logging
from collections.abc import Iterator
from datetime import date
from typing import Any

from hansard.config import Settings
from hansard.rag.prompts import system_prompt, user_instruction
from hansard.rag.sources import Source

log = logging.getLogger(__name__)

FALLBACK_BETA = "server-side-fallback-2026-07-01"


def make_client():
    import anthropic

    return anthropic.Anthropic()


def usage_dict(usage: Any) -> dict[str, int]:
    if usage is None:
        return {"input_tokens": 0, "output_tokens": 0, "cache_read_tokens": 0}
    return {
        "input_tokens": int(getattr(usage, "input_tokens", 0) or 0)
        + int(getattr(usage, "cache_creation_input_tokens", 0) or 0),
        "output_tokens": int(getattr(usage, "output_tokens", 0) or 0),
        "cache_read_tokens": int(getattr(usage, "cache_read_input_tokens", 0) or 0),
    }


def _block_to_dict(block: Any) -> dict[str, Any] | None:
    if getattr(block, "type", None) != "text":
        return None
    cites = []
    for c in getattr(block, "citations", None) or []:
        cites.append({
            "type": getattr(c, "type", None),
            "cited_text": getattr(c, "cited_text", ""),
            "search_result_index": getattr(c, "search_result_index", None),
            "source": getattr(c, "source", None),
        })
    return {"text": block.text, "citations": cites}


class Answerer:
    def __init__(self, settings: Settings, client=None):
        self.settings = settings
        self.client = client or make_client()
        self.use_fallbacks = bool(settings.answer.get("use_fallbacks", True))

    def stream(self, question: str, sources: list[Source], mode: str = "summary", plan_note: str = "",
               history: list[dict[str, str]] | None = None, today: date | None = None) -> Iterator[dict[str, Any]]:
        """Yield {"type": "text", "text"}, {"type": "citation", ...} events, then {"type": "final", ...}."""
        cfg = self.settings.answer
        history_note = ""
        if history:
            history_note = "Earlier in this conversation (for context only; cite only the search results below):\n" + \
                "\n".join(f"Q: {h['question']}\nA (summary): {h.get('answer', '')[:600]}" for h in history[-3:])
        content: list[dict[str, Any]] = [s.search_result() for s in sources]
        content.append({"type": "text", "text": user_instruction(question, mode, plan_note, history_note)})
        effort = cfg.get("comprehensive_effort" if mode == "comprehensive" else "summary_effort", "medium")
        kwargs: dict[str, Any] = {
            "model": cfg.get("model", "claude-opus-5-5"),
            "max_tokens": int(cfg.get("max_tokens", 16000)),
            "system": system_prompt(today or date.today()),
            "messages": [{"role": "user", "content": content}],
            "output_config": {"effort": effort},
        }
        try:
            yield from self._run(kwargs, fallbacks=self.use_fallbacks)
        except Exception as exc:  # the fallback beta may be unavailable on some accounts/platforms
            import anthropic

            if self.use_fallbacks and isinstance(exc, anthropic.BadRequestError) and "fallback" in str(exc).lower():
                log.warning("server-side fallbacks rejected; retrying without them")
                self.use_fallbacks = False
                yield from self._run(kwargs, fallbacks=False)
            else:
                raise

    def _run(self, kwargs: dict[str, Any], fallbacks: bool) -> Iterator[dict[str, Any]]:
        if fallbacks:
            ctx = self.client.beta.messages.stream(**kwargs, betas=[FALLBACK_BETA], fallbacks="default")
        else:
            ctx = self.client.messages.stream(**kwargs)
        with ctx as stream:
            for event in stream:
                if event.type != "content_block_delta":
                    continue
                d = event.delta
                if d.type == "text_delta":
                    yield {"type": "text", "text": d.text}
                elif d.type == "citations_delta":
                    c = d.citation
                    yield {"type": "citation", "search_result_index": getattr(c, "search_result_index", None),
                           "cited_text": getattr(c, "cited_text", "")}
            msg = stream.get_final_message()
        blocks = [b for b in (_block_to_dict(x) for x in msg.content) if b]
        yield {
            "type": "final",
            "blocks": blocks,
            "stop_reason": msg.stop_reason,
            "model": msg.model,
            "usage": usage_dict(msg.usage),
        }
