"""
Mock tours & attractions adapter (stands in for Viator / GetYourGuide).
Replace search() with a real provider call when you go live.
"""
from __future__ import annotations

import asyncio
import random

from adapters.base import ProviderAdapter
from models.schemas import NormalizedResult, SearchIntent

# (tour name, base price in INR, duration in minutes)
_TOURS = [
    ("City heritage walking tour", 900, 180),
    ("Local food trail", 1500, 150),
    ("Sunset sightseeing experience", 2200, 210),
    ("Full-day guided excursion", 3500, 480),
]


class MockToursAdapter(ProviderAdapter):
    provider_name = "tours_mock"

    async def search(self, intent: SearchIntent) -> list[NormalizedResult]:
        await asyncio.sleep(random.uniform(0.2, 0.8))
        return [
            NormalizedResult(
                provider=self.provider_name,
                vertical="tour",
                title=f"{name} in {intent.destination}",
                price=round(price * random.uniform(0.9, 1.2), 2),
                duration_minutes=minutes,
                rating=round(random.uniform(3.9, 4.9), 1),
            )
            for name, price, minutes in _TOURS
        ]
