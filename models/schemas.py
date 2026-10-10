"""
Shared request/response schemas.

These mirror what index.html's JS already sends and expects — see
handlePlan() and renderAIResults() in the frontend for the source of truth.
"""
from __future__ import annotations

from datetime import date
from typing import Literal, Optional

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Generic search intent — flights / hotels / trains / buses / cabs all share
# this shape. Verticals ignore the fields that don't apply to them.
# ---------------------------------------------------------------------------
class SearchIntent(BaseModel):
    origin: Optional[str] = None
    destination: str
    depart_date: date
    return_date: Optional[date] = None
    travelers: int = 1
    priority: Literal["balanced", "cheapest", "fastest"] = "balanced"


class NormalizedResult(BaseModel):
    """The common shape every provider adapter must return, regardless of
    what the provider's own API looks like. This is what makes Smart Route
    (comparing a flight to a train to a bus) possible."""
    provider: str
    vertical: Literal["flight", "hotel", "train", "bus", "cab", "tour"]
    title: str
    price: float
    currency: str = "INR"
    duration_minutes: Optional[int] = None
    departure_time: Optional[str] = None
    arrival_time: Optional[str] = None
    rating: Optional[float] = None
    raw: dict = Field(default_factory=dict)  # untouched provider payload


class BFFEnvelope(BaseModel):
    """Every BFF response uses this envelope so the frontend has one
    parsing path regardless of endpoint."""
    data: dict | list
    meta: dict = Field(default_factory=dict)
    errors: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# AI Planner — matches fd (form data) sent by handlePlan() in index.html
# ---------------------------------------------------------------------------
class PlannerRequest(BaseModel):
    startCity: str
    destination: Optional[str] = None
    budget: float
    duration: int = Field(ge=2, le=10)
    travelers: int = Field(ge=1, le=12)
    food: str = "No preference"
    hotel: str = "Mid-range hotel"
    interests: list[str] = Field(default_factory=list)


class HotelStub(BaseModel):
    name: str = ""
    type: str = ""
    price_per_night: float = 0


class ItineraryDay(BaseModel):
    day: int
    city: str
    title: str
    activities: list[str] = Field(default_factory=list)
    meals_note: str = ""
    hotel: HotelStub = HotelStub()


class BudgetBreakdown(BaseModel):
    travel: float = 0
    stay: float = 0
    food: float = 0
    activities: float = 0


class Itinerary(BaseModel):
    destination_overview: str
    budget_breakdown: BudgetBreakdown
    days: list[ItineraryDay]


class LogSpendRequest(BaseModel):
    session_id: str
    day: int
    amount: float = Field(gt=0)


# ---------------------------------------------------------------------------
# Bookings — "My Bookings" tab + the Book/Select buttons across every
# search tab now create a real record here instead of just showing a toast.
# ---------------------------------------------------------------------------
class BookingRequest(BaseModel):
    client_id: str  # generated client-side, persisted in localStorage — stands in for real auth (Phase 1 note)
    vertical: str
    title: str
    subtitle: str = ""
    price: float = 0
    currency: str = "INR"
    provider: str = ""


class BookingRecord(BookingRequest):
    booking_id: str
    status: str = "confirmed"
    created_at: str



# ---------------------------------------------------------------------------
# Live holiday orchestration + Trip Navigator
# ---------------------------------------------------------------------------
class HolidayStreamRequest(SearchIntent):
    """Same as SearchIntent plus what's needed to price a package properly."""
    rooms: int = Field(default=1, ge=1, le=5)
    nights: int = Field(default=3, ge=1, le=14)


class NavigatorRequest(BaseModel):
    destination: str = "Goa"
    budget: float = Field(ge=5000, le=1_000_000)
    nights: int = Field(default=3, ge=1, le=7)
    travelers: int = Field(default=2, ge=1, le=10)
    # Optional personalisation (all validated against the destination's data in main.py)
    must_ids: list[str] = Field(default_factory=list, max_length=30)   # places the user wants to visit
    stay_id: Optional[str] = None                                       # None = auto (best for budget)
    interests: list[str] = Field(default_factory=list, max_length=12)   # categories to favour, e.g. "beach"
    pace: Literal["relaxed", "balanced", "packed"] = "balanced"
    only_mine: bool = False                                             # True = only my places, no suggestions
