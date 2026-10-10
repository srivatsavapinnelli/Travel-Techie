"""
Mock transit adapter, standing in for the train / bus / cab resellers
(RailYatri/ConfirmTkt for trains, redBus, Uber/Ola). In production these
are three separate adapters behind three separate ProviderAdapter classes —
kept as one mock here for brevity. Split them when you wire real providers,
since each has very different auth and rate-limit behavior.
"""
from __future__ import annotations

import asyncio
import random

from adapters.base import ProviderAdapter
from models.schemas import NormalizedResult, SearchIntent

_MODES = [
    ("train", "AC 3-Tier · IRCTC partner", 900, 360),
    ("bus", "Volvo AC Sleeper", 650, 420),
    ("cab", "Sedan, one-way", 2800, 300),
]


class MockTransitAdapter(ProviderAdapter):
    provider_name = "transit_mock"

    async def search(self, intent: SearchIntent) -> list[NormalizedResult]:
        await asyncio.sleep(random.uniform(0.2, 0.8))

        return [
            NormalizedResult(
                provider=self.provider_name,
                vertical=mode,  # type: ignore[arg-type]
                title=f"{label} to {intent.destination}",
                price=round(price * random.uniform(0.9, 1.15), 2),
                duration_minutes=minutes,
            )
            for mode, label, price, minutes in _MODES
        ]
