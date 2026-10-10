"""
Mock hotel adapter. Replace search() with a real Booking.com / Amadeus
Hotels / RateHawk call when you go live — interface stays identical.
"""
from __future__ import annotations

import asyncio
import random

from adapters.base import ProviderAdapter
from models.schemas import NormalizedResult, SearchIntent

_TIERS = [("Budget stay", 1400), ("Mid-range hotel", 3200), ("Boutique resort", 6800)]


class MockBookingAdapter(ProviderAdapter):
    provider_name = "booking_mock"

    async def search(self, intent: SearchIntent) -> list[NormalizedResult]:
        await asyncio.sleep(random.uniform(0.2, 0.8))

        return [
            NormalizedResult(
                provider=self.provider_name,
                vertical="hotel",
                title=f"{name} in {intent.destination}",
                price=round(price * random.uniform(0.9, 1.2), 2),
                rating=round(random.uniform(3.5, 4.9), 1),
                raw={"type": name},
            )
            for name, price in _TIERS
        ]
