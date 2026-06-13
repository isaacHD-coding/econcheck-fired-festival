from __future__ import annotations

from harness.tools.fred import fred_search


def test_fred_search_falls_back_to_direct_series_lookup_for_explicit_series_id(
    monkeypatch,
) -> None:
    calls: list[tuple[str, dict[str, str]]] = []

    def fake_request_json(endpoint, params, *, timeout_seconds):
        calls.append((endpoint, dict(params)))
        if endpoint == "series/search":
            return {"seriess": []}
        if endpoint == "series":
            return {
                "seriess": [
                    {
                        "id": "CPIAUCSL",
                        "title": (
                            "Consumer Price Index for All Urban Consumers: "
                            "All Items in U.S. City Average"
                        ),
                        "frequency": "Monthly",
                        "units": "Index 1982-1984=100",
                        "observation_start": "1947-01-01",
                        "observation_end": "2026-05-01",
                    }
                ]
            }
        raise AssertionError(f"Unexpected endpoint: {endpoint}")

    monkeypatch.setattr("harness.tools.fred._request_json", fake_request_json)

    results = fred_search(
        "FRED CPIAUCSL Consumer Price Index for All Urban Consumers",
        api_key="test-fred-key",
    )

    assert [result.series_id for result in results] == ["CPIAUCSL"]
    assert [endpoint for endpoint, _params in calls] == ["series/search", "series"]
    assert calls[1][1]["series_id"] == "CPIAUCSL"
