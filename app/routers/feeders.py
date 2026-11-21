from datetime import datetime, time, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from app.deps import admin_only, get_actor, owner_filter

router = APIRouter(prefix="/feeders", tags=["feeders"])


@router.get("")
async def list_feeders(request: Request, actor: dict = Depends(get_actor)):
    cols = request.app.state.cols

    # الأبقار التابعة للـ Admin الحالي
    profiles = [
        p async for p in cols.profiles.find(
            owner_filter(actor), {"_id": 1, "cow_id": 1}
        )
    ]
    cow_ids = {
        str(value)
        for p in profiles
        for value in (p.get("_id"), p.get("cow_id"))
        if value is not None
    }

    # زيارات اليوم من daily_summaries
    today = datetime.now(timezone.utc).date()
    start = datetime.combine(today, time.min, tzinfo=timezone.utc)
    end = start + timedelta(days=1)

    daily_filter = {"date": {"$gte": start, "$lt": end}}
    if cow_ids:
        daily_filter["$or"] = [
            {"cow_id": {"$in": list(cow_ids)}},
            {"rfid": {"$in": list(cow_ids)}},
        ]
    else:
        daily_filter["cow_id"] = "__no_cows__"

    visits_today = 0
    visited_cows = set()
    async for row in cols.daily.find(daily_filter):
        visits_today += int(row.get("visits", 0) or 0)
        if int(row.get("visits", 0) or 0) > 0:
            visited_cows.add(str(row.get("cow_id") or row.get("rfid")))

    result = []
    async for feeder in cols.feeders.find(owner_filter(actor)).sort("name", 1):
        capacity = int(feeder.get("capacity_g", 0) or 0)
        quantity = int(feeder.get("current_quantity_g", 0) or 0)
        result.append({
            "id": str(feeder["_id"]),
            "name": feeder.get("name", "Mangeoire"),
            "capacity_g": capacity,
            "current_quantity_g": quantity,
            "last_refill_at": feeder.get("last_refill_at"),
            "online": bool(feeder.get("online", False)),
            "visits_today": visits_today,
            "cows_today": len(visited_cows),
        })

    return result


class RefillIn(BaseModel):
    quantity_g: int = Field(gt=0, le=1_000_000)


@router.post("/{feeder_id}/refill")
async def refill_feeder(feeder_id: str, body: RefillIn, request: Request,
                        admin: dict = Depends(admin_only)):
    """Ajoute de l'aliment disponible dans la mangeoire (sans dépasser la capacité)."""
    feeders = request.app.state.cols.feeders
    flt = {"_id": feeder_id, **owner_filter(admin)}
    feeder = await feeders.find_one(flt)
    if feeder is None:
        raise HTTPException(404, "Feeder not found")
    capacity = int(feeder.get("capacity_g", 0) or 0)
    quantity = int(feeder.get("current_quantity_g", 0) or 0)
    new_quantity = quantity + body.quantity_g
    if capacity > 0 and new_quantity > capacity:
        free_kg = max(capacity - quantity, 0) / 1000
        raise HTTPException(400, f"Exceeds capacity: only {free_kg:.1f} kg of space left")
    now = datetime.now(timezone.utc)
    await feeders.update_one(flt, {"$set": {"current_quantity_g": new_quantity,
                                            "last_refill_at": now}})
    return {"id": feeder_id, "current_quantity_g": new_quantity,
            "capacity_g": capacity, "last_refill_at": now}
