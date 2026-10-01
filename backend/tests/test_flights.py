from datetime import datetime

import pytest

from app.services.flights import (
    STALE_AFTER_S,
    Aircraft,
    Airport,
    FlightFeed,
    Route,
    parse_route,
    parse_states,
    plausible,
    spread,
)

HKG = Airport("HKG", 22.31, 113.91)
SIN = Airport("SIN", 1.35, 103.99)
HKG_SIN = Route(HKG, SIN)


def state(callsign="CPA711", lat=12.0, lon=109.0, alt=11000.0, on_ground=False, velocity=240.0, track=200.0):
    s = [None] * 17
    s[1], s[5], s[6], s[7], s[8], s[9], s[10] = callsign, lon, lat, alt, on_ground, velocity, track
    return s


class Clock:
    def __init__(self, t=1_000_000.0):
        self.t = t

    def __call__(self):
        return self.t


def make_feed(settings, states, routes, clock=None):
    def fetch_route(cs):
        r = routes.get(cs)
        if isinstance(r, Exception):
            raise r
        return r

    calls = {"routes": 0}

    def counted(cs):
        calls["routes"] += 1
        return fetch_route(cs)

    def fetch_states():
        if isinstance(states, Exception):
            raise states
        return states

    feed = FlightFeed(settings, fetch_states=fetch_states, fetch_route=counted, clock=clock or Clock())
    return feed, calls


def test_parse_states_keeps_only_cruising_airliners():
    states = [
        state("CPA711 "),
        state("SIA22", on_ground=True),
        state("JAL5", alt=3000),
        state("ANA1", velocity=90),
        state(""),
        state("N123AB"),  # private registration, not an airline callsign
        state("THA661", lat=None),
    ]
    assert [a.callsign for a in parse_states(states)] == ["CPA711"]


def test_spread_caps_and_alternates_cells():
    clustered = [Aircraft(f"CES{i}", 31.0, 121.0, 0, 200) for i in range(10)]
    lone = [Aircraft("QFA1", -5.0, 140.0, 0, 200), Aircraft("AIC1", 20.0, 75.0, 0, 200)]
    picked = spread(clustered + lone, 4)
    assert len(picked) == 4
    assert {"QFA1", "AIC1"} <= {a.callsign for a in picked}


def test_parse_route_and_plausibility():
    payload = {
        "response": {
            "flightroute": {
                "origin": {"iata_code": "HKG", "latitude": 22.31, "longitude": 113.91},
                "destination": {"iata_code": "SIN", "latitude": 1.35, "longitude": 103.99},
            }
        }
    }
    route = parse_route(payload)
    assert route == HKG_SIN
    assert parse_route({"response": "unknown callsign"}) is None
    hkg = payload["response"]["flightroute"]["origin"]
    assert parse_route({"response": {"flightroute": {"origin": hkg, "destination": hkg}}}) is None

    on_route = Aircraft("CPA711", 12.0, 109.0, 200, 240)
    over_japan = Aircraft("CPA711", 35.0, 139.0, 200, 240)
    assert plausible(route, on_route)
    assert not plausible(route, over_japan)


def test_refresh_publishes_flights_and_caches_routes(settings):
    states = [state("CPA711"), state("JAL5", lat=35.0, lon=139.0), state("ZZZ9")]
    routes = {"CPA711": HKG_SIN, "JAL5": HKG_SIN, "ZZZ9": None}  # JAL5's route is implausible here
    feed, calls = make_feed(settings, states, routes)
    feed.refresh()
    snap = feed.snapshot()
    assert isinstance(snap["updated_at"], datetime)
    assert [f["callsign"] for f in snap["flights"]] == ["CPA711"]
    assert snap["flights"][0]["origin"] == {"iata": "HKG", "lat": 22.31, "lon": 113.91}
    assert calls["routes"] == 3

    feed.refresh()  # second cycle hits the cache, including the negative result
    assert calls["routes"] == 3


def test_failed_refresh_keeps_previous_snapshot(settings):
    feed, _ = make_feed(settings, [state("CPA711")], {"CPA711": HKG_SIN})
    feed.refresh()
    feed._fetch_states = lambda: (_ for _ in ()).throw(RuntimeError("network down"))
    with pytest.raises(RuntimeError):
        feed.refresh()
    assert len(feed.snapshot()["flights"]) == 1


def test_route_lookup_errors_are_not_cached(settings):
    routes = {"CPA711": TimeoutError("slow")}
    feed, calls = make_feed(settings, [state("CPA711")], routes)
    feed.refresh()
    assert feed.snapshot()["flights"] == []
    routes["CPA711"] = HKG_SIN
    feed.refresh()
    assert len(feed.snapshot()["flights"]) == 1
    assert calls["routes"] == 2


def test_stale_snapshot_is_not_served(settings):
    clock = Clock()
    feed, _ = make_feed(settings, [state("CPA711")], {"CPA711": HKG_SIN}, clock)
    feed.refresh()
    clock.t += STALE_AFTER_S + 1
    assert feed.snapshot() == {"updated_at": None, "flights": []}


def test_refresh_interval_depends_on_credentials(settings):
    assert FlightFeed(settings).interval == 900
    authed = settings.model_copy(update={"opensky_client_id": "id", "opensky_client_secret": "secret"})
    assert FlightFeed(authed).interval == 120


# ---------------------------------------------------------------------------------- API
def test_flights_endpoint_requires_api_key(client):
    assert client.get("/api/flights").status_code == 401


def test_flights_endpoint_without_feed(client, api_headers):
    r = client.get("/api/flights", headers=api_headers)
    assert r.status_code == 200
    assert r.json() == {"updated_at": None, "flights": []}


def test_flights_endpoint_serves_snapshot_and_marks_demand(client, fakes, settings, api_headers):
    container, _ = fakes
    feed, _ = make_feed(settings, [state("CPA711")], {"CPA711": HKG_SIN})
    feed.refresh()
    container.flights = feed
    r = client.get("/api/flights", headers=api_headers)
    assert r.status_code == 200
    body = r.json()
    assert body["updated_at"] is not None
    assert body["flights"][0]["destination"]["iata"] == "SIN"
    assert feed._last_demand > 0
