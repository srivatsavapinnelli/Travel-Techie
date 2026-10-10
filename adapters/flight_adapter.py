"""
Mock flight adapter. To go live, replace the body of search() with a real
call to Amadeus / Duffel / TravelPort and map their response fields into
NormalizedResult — the rest of the system (agents, orchestrator, BFF)
doesn't need to change.
"""
from __future__ import annotations

import asyncio
import random

from adapters.base import ProviderAdapter
from models.schemas import NormalizedResult, SearchIntent


class MockAmadeusAdapter(ProviderAdapter):
    provider_name = "amadeus_mock"

    async def search(self, intent: SearchIntent) -> list[NormalizedResult]:
        # simulate real network latency so orchestrator timeout logic is
        # actually exercised in dev
        await asyncio.sleep(random.uniform(0.2, 0.8))

        base_price = 3500 + hash(intent.destination) % 4000
        return [
            NormalizedResult(
                provider=self.provider_name,
                vertical="flight",
                title=f"{intent.origin or 'DEL'} -> {intent.destination} · Direct",
                price=round(base_price * random.uniform(0.9, 1.3), 2),
                duration_minutes=random.randint(75, 240),
                departure_time="06:15",
                arrival_time="08:40",
                rating=round(random.uniform(3.6, 4.8), 1),
            )
            for _ in range(3)
        ]
