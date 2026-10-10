"""
Every provider (Amadeus, Booking.com, redBus, Ola, ...) gets wrapped in a
class that implements this same interface. Agents and the orchestrator only
ever talk to ProviderAdapter — never to a provider's native SDK directly.

This is the single decision that makes it possible to:
  1. Swap providers without touching agent/orchestrator code
  2. Run several providers for the same vertical in parallel and merge
  3. Mock a provider in tests without spinning up real credentials
"""
from __future__ import annotations

import abc

from models.schemas import NormalizedResult, SearchIntent


class ProviderAdapter(abc.ABC):
    provider_name: str

    @abc.abstractmethod
    async def search(self, intent: SearchIntent) -> list[NormalizedResult]:
        """Call the provider and return results already normalized into
        NormalizedResult — no provider-specific shapes leak past this."""
        raise NotImplementedError

    async def health_check(self) -> bool:
        """Cheap liveness check used by the circuit breaker before a burst
        of calls. Override with a real ping when you wire a live provider."""
        return True
