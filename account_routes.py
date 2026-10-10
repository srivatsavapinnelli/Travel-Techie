"""
Account endpoints: /api/auth/* (sign up, log in, log out, who am I, claim guest bookings)
and /api/me/* (my trips: bookings + saved plans). Logged-in requests send
    Authorization: Bearer <token>
"""
from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel

from db import accounts, bookings_store

router = APIRouter(prefix="/api")


class RegisterBody(BaseModel):
    name: str = ""
    email: str = ""
    password: str = ""


class LoginBody(BaseModel):
    email: str = ""
    password: str = ""


class ClaimBody(BaseModel):
    guest_client_id: str = ""


class SavePlanBody(BaseModel):
    kind: str
    title: str = ""
    destination: str = ""
    payload: dict[str, Any]


def _token_from(authorization: Optional[str]) -> str:
    if authorization and authorization.lower().startswith("bearer "):
        return authorization[7:].strip()
    return ""


def current_user(authorization: Optional[str] = Header(default=None)) -> dict:
    token = _token_from(authorization)
    if not token:
        raise HTTPException(status_code=401, detail="Please log in to continue.")
    user = accounts.user_for_token(token)
    if not user:
        raise HTTPException(status_code=401, detail="Your session has expired. Please log in again.")
    return user


def _public(user: dict) -> dict:
    return {k: user[k] for k in ("name", "email", "client_id", "created_at")}


@router.post("/auth/register")
async def register(body: RegisterBody):
    problem = accounts.validate_signup(body.name, body.email, body.password)
    if problem:
        raise HTTPException(status_code=400, detail=problem)
    try:
        user = accounts.create_user(body.name, body.email, body.password)
    except accounts.EmailTaken:
        raise HTTPException(status_code=409, detail="An account with this email already exists. Try logging in.")
    return {"data": {"token": accounts.create_session(user["id"]), "user": _public(user)}}


@router.post("/auth/login")
async def login(body: LoginBody):
    if not body.email.strip() or not body.password:
        raise HTTPException(status_code=400, detail="Please enter your email and password.")
    try:
        user = accounts.authenticate(body.email, body.password)
    except accounts.LockedOut as e:
        raise HTTPException(status_code=429, detail=str(e))
    except accounts.BadCredentials:
        raise HTTPException(status_code=401, detail="Incorrect email or password.")
    return {"data": {"token": accounts.create_session(user["id"]), "user": _public(user)}}


@router.post("/auth/logout")
async def logout(authorization: Optional[str] = Header(default=None)):
    token = _token_from(authorization)
    if token:
        accounts.delete_session(token)
    return {"data": {"ok": True}}


@router.get("/auth/me")
async def me(user: dict = Depends(current_user)):
    return {"data": _public(user)}


@router.post("/auth/claim")
async def claim_guest_bookings(body: ClaimBody, user: dict = Depends(current_user)):
    """After logging in: bookings made in this browser as a guest move into the account."""
    moved = bookings_store.move_bookings(body.guest_client_id, user["client_id"]) if body.guest_client_id else 0
    return {"data": {"moved": moved}}


@router.get("/me/trips")
async def my_trips(user: dict = Depends(current_user)):
    bookings = [b.model_dump() for b in bookings_store.list_bookings(user["client_id"])]
    return {"data": {"bookings": bookings, "plans": accounts.list_plans(user["id"])}}


@router.post("/me/plans")
async def save_plan(body: SavePlanBody, user: dict = Depends(current_user)):
    try:
        plan = accounts.save_plan(user["id"], body.kind, body.title, body.destination, body.payload)
    except accounts.PlanLimit:
        raise HTTPException(status_code=409, detail="You've reached the limit of 100 saved plans. Delete one to save another.")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"data": plan}


@router.get("/me/plans/{plan_id}")
async def get_plan(plan_id: str, user: dict = Depends(current_user)):
    plan = accounts.get_plan(user["id"], plan_id)
    if not plan:
        raise HTTPException(status_code=404, detail="Plan not found.")
    return {"data": plan}


@router.delete("/me/plans/{plan_id}")
async def delete_plan(plan_id: str, user: dict = Depends(current_user)):
    if not accounts.delete_plan(user["id"], plan_id):
        raise HTTPException(status_code=404, detail="Plan not found.")
    return {"data": {"ok": True}}
