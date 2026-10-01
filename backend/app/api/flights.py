from fastapi import APIRouter, Depends

from app.api.deps import get_container
from app.container import Container
from app.models.schemas import FlightsResponse
from app.security import require_api_key

router = APIRouter(tags=["flights"])


@router.get("/flights", response_model=FlightsResponse, dependencies=[Depends(require_api_key)])
def flights(container: Container = Depends(get_container)) -> FlightsResponse:
    """Live flights over India for the decorative background. Empty when the feed is off or not ready."""
    feed = container.flights
    if feed is None:
        return FlightsResponse(flights=[])
    feed.touch()
    return FlightsResponse.model_validate(feed.snapshot())
