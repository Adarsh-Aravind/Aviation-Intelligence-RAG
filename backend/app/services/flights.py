"""Live flights over India and its neighbours for the frontend's decorative background.

One background thread polls OpenSky for aircraft positions inside a fixed box around India and looks up each
flight's origin and destination on adsbdb (cached per callsign). The result is a small in-memory snapshot
served by ``GET /api/flights``. Polling is demand-driven: it only runs while someone has requested
flights recently, so an idle server makes no outbound calls.
"""

from __future__ import annotations

import logging
import math
import re
import threading
import time
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime

import httpx

from app.config import Settings

logger = logging.getLogger(__name__)

# India plus the Arabian Sea, Bay of Bengal and neighbours. Larger than 400 sq deg, so each OpenSky
# call costs 4 credits.
REGION = {"lamin": -2.0, "lomin": 60.0, "lamax": 40.0, "lomax": 100.0}

OPENSKY_STATES_URL = "https://opensky-network.org/api/states/all"
OPENSKY_TOKEN_URL = (
    "https://auth.opensky-network.org/auth/realms/opensky-network/protocol/openid-connect/token"  # noqa: S105
)
ADSBDB_CALLSIGN_URL = "https://api.adsbdb.com/v0/callsign/{}"
USER_AGENT = "aviation-intelligence-rag/0.1 (+https://github.com/Adarsh-Aravind/Aviation-Intelligence-RAG)"

ANON_INTERVAL_S = 900  # 400 credits/day anonymous -> 100 calls/day
AUTH_INTERVAL_S = 120  # 4000 credits/day with an account -> 1000 calls/day
DEMAND_WINDOW_S = 600  # keep polling this long after the last /api/flights request
STALE_AFTER_S = 1800  # never serve positions older than this
ERROR_RETRY_S = 60

MIN_ALTITUDE_M = 6000  # cruising airliners only
MIN_SPEED_MS = 150
CALLSIGN_RE = re.compile(r"^[A-Z]{3}\d[A-Z0-9]{0,4}$")  # airline ICAO callsigns (adsbdb knows these)

CELL_DEG = 5  # spread picks across 5x5 degree cells so routes don't bunch over one area
CANDIDATES = 120
MAX_LOOKUPS_PER_CYCLE = 80
ROUTE_TTL_S = 12 * 3600
ROUTE_CACHE_MAX = 5000
EARTH_RADIUS_KM = 6371.0


@dataclass(frozen=True)
class Airport:
    iata: str
    lat: float
    lon: float


@dataclass(frozen=True)
class Route:
    origin: Airport
    destination: Airport


@dataclass(frozen=True)
class Aircraft:
    callsign: str
    lat: float
    lon: float
    track: float
    velocity: float


class RateLimited(Exception):
    def __init__(self, retry_after: float):
        super().__init__(f"rate limited for {retry_after:.0f}s")
        self.retry_after = retry_after


# ----------------------------------------------------------------------------- pure helpers
def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * EARTH_RADIUS_KM * math.asin(min(1.0, math.sqrt(a)))


def parse_states(states: list[list] | None) -> list[Aircraft]:
    """OpenSky state vectors -> cruising airliners. Index layout per the OpenSky REST docs."""
    out: list[Aircraft] = []
    for s in states or []:
        try:
            callsign = (s[1] or "").strip().upper()
            lon, lat, alt, on_ground, velocity, track = s[5], s[6], s[7], s[8], s[9], s[10]
        except (IndexError, TypeError):
            continue
        if not CALLSIGN_RE.match(callsign) or on_ground:
            continue
        if None in (lat, lon, alt, velocity, track):
            continue
        if alt < MIN_ALTITUDE_M or velocity < MIN_SPEED_MS:
            continue
        out.append(Aircraft(callsign, float(lat), float(lon), float(track), float(velocity)))
    return out


def spread(aircraft: list[Aircraft], limit: int) -> list[Aircraft]:
    """Round-robin across grid cells. Deterministic, so consecutive refreshes keep the same flights."""
    cells: dict[tuple[int, int], list[Aircraft]] = {}
    for ac in sorted(aircraft, key=lambda a: a.callsign):
        cells.setdefault((math.floor(ac.lat / CELL_DEG), math.floor(ac.lon / CELL_DEG)), []).append(ac)
    queues = [cells[k] for k in sorted(cells)]
    out: list[Aircraft] = []
    depth = 0
    while len(out) < limit and any(depth < len(q) for q in queues):
        for q in queues:
            if depth < len(q):
                out.append(q[depth])
                if len(out) == limit:
                    break
        depth += 1
    return out


def _airport(data: dict | None) -> Airport | None:
    if not data or data.get("latitude") is None or data.get("longitude") is None:
        return None
    code = data.get("iata_code") or data.get("icao_code") or ""
    return Airport(code, float(data["latitude"]), float(data["longitude"]))


def parse_route(payload: dict) -> Route | None:
    """adsbdb ``/v0/callsign/<cs>`` response -> Route (None when incomplete)."""
    response = payload.get("response")
    route = response.get("flightroute") if isinstance(response, dict) else None
    if not route:
        return None
    origin, destination = _airport(route.get("origin")), _airport(route.get("destination"))
    if origin is None or destination is None:
        return None
    if (origin.lat, origin.lon) == (destination.lat, destination.lon):
        return None
    return Route(origin, destination)


def plausible(route: Route, ac: Aircraft) -> bool:
    """Callsign routes can be stale; keep only those the aircraft is actually flying along."""
    o, d = route.origin, route.destination
    total = haversine_km(o.lat, o.lon, d.lat, d.lon)
    if total < 150:
        return False
    via = haversine_km(o.lat, o.lon, ac.lat, ac.lon) + haversine_km(ac.lat, ac.lon, d.lat, d.lon)
    return via <= total * 1.15 + 300


def _flight_dict(ac: Aircraft, route: Route) -> dict:
    def airport(a: Airport) -> dict:
        return {"iata": a.iata, "lat": a.lat, "lon": a.lon}

    return {
        "callsign": ac.callsign,
        "lat": ac.lat,
        "lon": ac.lon,
        "track": ac.track,
        "velocity": ac.velocity,
        "origin": airport(route.origin),
        "destination": airport(route.destination),
    }


# ------------------------------------------------------------------------------------- feed
class FlightFeed:
    def __init__(
        self,
        settings: Settings,
        *,
        fetch_states: Callable[[], list[list]] | None = None,
        fetch_route: Callable[[str], Route | None] | None = None,
        clock: Callable[[], float] = time.time,
    ):
        self._client_id = settings.opensky_client_id
        self._client_secret = settings.opensky_client_secret
        self.max_flights = settings.flights_max
        self.interval = AUTH_INTERVAL_S if self.authenticated else ANON_INTERVAL_S
        self._fetch_states = fetch_states or self._opensky_states
        self._fetch_route = fetch_route or self._adsbdb_route
        self._clock = clock

        self._lock = threading.Lock()
        self._flights: list[dict] = []
        self._updated_at: float | None = None
        self._last_demand = 0.0
        self._wake = threading.Event()
        self._routes: OrderedDict[str, tuple[float, Route | None]] = OrderedDict()
        self._http: httpx.Client | None = None
        self._token: tuple[str, float] | None = None

    @property
    def authenticated(self) -> bool:
        return bool(self._client_id and self._client_secret)

    # ---------------------------------------------------------------- public
    def snapshot(self) -> dict:
        with self._lock:
            fresh = self._updated_at is not None and self._clock() - self._updated_at <= STALE_AFTER_S
            return {
                "updated_at": datetime.fromtimestamp(self._updated_at, UTC) if fresh else None,
                "flights": list(self._flights) if fresh else [],
            }

    def touch(self) -> None:
        """Record demand from a visitor; wakes the poller if it was idle."""
        self._last_demand = self._clock()
        self._wake.set()

    def refresh(self) -> None:
        """One polling cycle: positions, then routes (cached), then publish."""
        aircraft = spread(parse_states(self._fetch_states()), CANDIDATES)
        flights: list[dict] = []
        lookups = 0
        for ac in aircraft:
            hit, route = self._cached_route(ac.callsign)
            if not hit:
                if lookups >= MAX_LOOKUPS_PER_CYCLE:
                    continue
                lookups += 1
                try:
                    route = self._fetch_route(ac.callsign)
                except Exception as exc:  # transient — don't cache, try again next cycle
                    logger.debug("route lookup for %s failed: %s", ac.callsign, exc)
                    continue
                self._remember_route(ac.callsign, route)
                if lookups % 15 == 0 and not self._has_flights():
                    self._publish(flights)  # first fill after startup: show something early
            if route is not None and plausible(route, ac):
                flights.append(_flight_dict(ac, route))
                if len(flights) >= self.max_flights:
                    break
        self._publish(flights)
        logger.info("flight feed: %d flights (%d new route lookups)", len(flights), lookups)

    def run(self, stop: threading.Event) -> None:
        next_poll = 0.0
        while not stop.is_set():
            now = self._clock()
            if now - self._last_demand <= DEMAND_WINDOW_S and now >= next_poll:
                try:
                    self.refresh()
                    next_poll = now + self.interval
                except RateLimited as exc:
                    logger.warning("flight feed: OpenSky %s", exc)
                    next_poll = now + max(exc.retry_after, self.interval)
                except Exception as exc:
                    logger.warning(
                        "flight feed refresh failed (%s) — keeping last snapshot", exc.__class__.__name__
                    )
                    next_poll = now + ERROR_RETRY_S
            if self._wake.wait(timeout=30):
                self._wake.clear()
        if self._http is not None:
            self._http.close()

    # ---------------------------------------------------------------- internals
    def _has_flights(self) -> bool:
        with self._lock:
            return bool(self._flights)

    def _publish(self, flights: list[dict]) -> None:
        with self._lock:
            self._flights = list(flights)
            self._updated_at = self._clock()

    def _cached_route(self, callsign: str) -> tuple[bool, Route | None]:
        entry = self._routes.get(callsign)
        if entry is None or self._clock() - entry[0] > ROUTE_TTL_S:
            return False, None
        self._routes.move_to_end(callsign)
        return True, entry[1]

    def _remember_route(self, callsign: str, route: Route | None) -> None:
        self._routes[callsign] = (self._clock(), route)
        self._routes.move_to_end(callsign)
        while len(self._routes) > ROUTE_CACHE_MAX:
            self._routes.popitem(last=False)

    def _client(self) -> httpx.Client:
        if self._http is None:
            self._http = httpx.Client(timeout=20.0, headers={"User-Agent": USER_AGENT})
        return self._http

    def _opensky_headers(self) -> dict[str, str]:
        if not self.authenticated:
            return {}
        now = self._clock()
        if self._token is None or now >= self._token[1]:
            r = self._client().post(
                OPENSKY_TOKEN_URL,
                data={
                    "grant_type": "client_credentials",
                    "client_id": self._client_id,
                    "client_secret": self._client_secret,
                },
            )
            r.raise_for_status()
            body = r.json()
            self._token = (body["access_token"], now + float(body.get("expires_in", 1800)) - 60)
        return {"Authorization": f"Bearer {self._token[0]}"}

    def _opensky_states(self) -> list[list]:
        r = self._client().get(OPENSKY_STATES_URL, params=REGION, headers=self._opensky_headers())
        if r.status_code == 429:
            raise RateLimited(float(r.headers.get("x-rate-limit-retry-after-seconds") or 3600))
        r.raise_for_status()
        return r.json().get("states") or []

    def _adsbdb_route(self, callsign: str) -> Route | None:
        r = self._client().get(ADSBDB_CALLSIGN_URL.format(callsign))
        if r.status_code == 404:
            return None  # unknown callsign — cached so we don't ask again
        r.raise_for_status()
        return parse_route(r.json())
