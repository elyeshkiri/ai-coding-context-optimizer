"""Example module used to demo skeleton compression."""

import json
from typing import Any


MAX_ITEMS = 100


class OrderService:
    def __init__(self, repo: Any) -> None:
        self.repo = repo

    def create(self, payload: dict) -> dict:
        if not payload.get("sku"):
            raise ValueError("sku required")
        # lots of body the model does not need during navigation
        raw = json.dumps(payload)
        stored = self.repo.save(raw)
        return {"id": stored, "ok": True}

    async def list_open(self) -> list[dict]:
        rows = await self.repo.query("open")
        return rows[:MAX_ITEMS]


def helper(x: int) -> int:
    total = 0
    for i in range(x):
        total += i
    return total
