"""Worst-case generation budget for one chat request.

Prices are integer micro-USD per million tokens. Prompt tokens are estimated
conservatively from characters; output is reserved at max_tokens. The cap is a
hard pre-call guardrail, not an exact bill: actual provider cost is still read
from the response and recorded separately.
"""
from dataclasses import dataclass
import math
from typing import Optional


class BudgetExceededError(RuntimeError):
    error_code = "budget_exceeded"


@dataclass
class RequestBudget:
    cap_micros: int
    input_micros_per_mtok: int
    output_micros_per_mtok: int
    reserved_micros: int = 0

    @property
    def enabled(self) -> bool:
        return self.cap_micros > 0 and self.input_micros_per_mtok > 0 and self.output_micros_per_mtok > 0

    def _prompt_cost(self, prompt_chars: int) -> int:
        # 3 chars/token plus a 20% safety margin; summarization and the final
        # answer use the same reservation pool.
        tokens = math.ceil(max(0, prompt_chars) / 3 * 1.2)
        return math.ceil(tokens * self.input_micros_per_mtok / 1_000_000)

    def reserve_output(self, prompt_chars: int, requested_max_tokens: int) -> int:
        if not self.enabled:
            return requested_max_tokens
        remaining = self.cap_micros - self.reserved_micros
        prompt_cost = self._prompt_cost(prompt_chars)
        if prompt_cost >= remaining:
            raise BudgetExceededError("Request budget cannot cover the prompt.")
        affordable = (remaining - prompt_cost) * 1_000_000 // self.output_micros_per_mtok
        allowed = min(requested_max_tokens, int(affordable))
        if allowed < 32:
            raise BudgetExceededError("Request budget cannot cover a useful answer.")
        self.reserved_micros += prompt_cost + math.ceil(
            allowed * self.output_micros_per_mtok / 1_000_000,
        )
        return allowed


def budget_for(config, route) -> Optional[RequestBudget]:
    cap = getattr(config, "request_cost_cap_micros", 0)
    if not cap:
        return None
    budget = RequestBudget(
        cap_micros=cap,
        input_micros_per_mtok=route.input_micros_per_mtok,
        output_micros_per_mtok=route.output_micros_per_mtok,
    )
    return budget if budget.enabled else None
