from datetime import datetime, time, timedelta, timezone

from fastapi import APIRouter, Depends, Request

from app.deps import get_actor, owner_filter

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