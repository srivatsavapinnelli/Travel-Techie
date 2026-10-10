"""
Mock cab adapter (stands in for Uber / Ola partner APIs).
To go live, replace the body of search() with a real provider call and map
the response into NormalizedResult - nothing else in the project changes.
"""
from __future__ import annotations

import asyncio
import random

from adapters.base import ProviderAdapter
from models.schemas import NormalizedResult, SearchIntent

# (label, base price in INR, base duration in minutes)
_CAB_TYPES = [
    ("Hatchback, one-way", 2200, 320),
    ("Sedan, one-way", 2800, 300),
    ("SUV, one-way", 3900, 300),
]


class MockCabAdapter(ProviderAdapter):
    provider_name = "cab_mock"

    async def search(self, intent: SearchIntent) -> list[NormalizedResult]:
        await asyncio.sleep(random.uniform(0.2, 0.8))  # simulate network latency
        return [
            NormalizedResult(
                provider=self.provider_name,
                vertical="cab",
                title=f"{label} to {intent.destination}",
                price=round(price * random.uniform(0.9, 1.15), 2),
                duration_minutes=minutes,
                rating=round(random.uniform(3.8, 4.9), 1),
            )
            for label, price, minutes in _CAB_TYPES
        ]
