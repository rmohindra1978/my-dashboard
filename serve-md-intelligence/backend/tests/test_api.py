from __future__ import annotations

from backend.app.registry import load_default_financial_assumptions, load_default_score_config


def test_health(client):
    r = client.get("/api/health")
    assert r.status_code == 200
    body = r.json()
    assert body["geo_units"] == 27 and body["metric_rows"] > 800


def test_search_resolves_city_zip_county(client):
    assert client.get("/api/search", params={"q": "Phoenix"}).json()[0]["display"] == "Phoenix, AZ"
    assert client.get("/api/search", params={"q": "85004"}).json()[0]["geo_level"] == "zcta"
    hits = client.get("/api/search", params={"q": "Maricopa County, AZ"}).json()
    assert hits[0]["geo_id"] == "04013"
    assert client.get("/api/search", params={"q": "zzzzzz"}).json() == []


def test_market_profile_panels(client):
    r = client.get("/api/markets/county/04013")
    assert r.status_code == 200
    p = r.json()
    assert p["geo"]["name"] == "Maricopa County"
    assert {x["pillar"] for x in p["panels"]} == {
        "medicare_demand",
        "demographics_growth",
        "competition_supply",
        "health_need",
        "economics_cost",
    }
    assert p["score"]["score"] is not None and p["score"]["rank"] == 1
    assert len(p["related"]) == 3  # ZCTAs in Maricopa
    z = client.get("/api/markets/zcta/85004").json()
    assert z["parent_county"]["geo_id"] == "04013"
    assert client.get("/api/markets/county/00000").status_code == 404


def test_rank_and_filters_and_csv(client):
    r = client.post("/api/rank", json={"geo_level": "county", "limit": 5}).json()
    assert r["total"] == 12 and len(r["rows"]) == 5 and r["rows"][0]["rank"] == 1
    assert r["rows"][0]["score"] >= r["rows"][1]["score"]
    fl = client.post(
        "/api/rank",
        json={
            "geo_level": "county",
            "states": ["AZ"],
            "filters": [{"metric_id": "pct_65_plus", "op": "gte", "value": 0}],
        },
    ).json()
    assert fl["total"] == 5 and all(x["state_abbr"] == "AZ" for x in fl["rows"])
    csv = client.post("/api/rank/export.csv", json={"geo_level": "county"})
    assert csv.status_code == 200 and csv.text.count("\n") == 13


def test_rank_with_adhoc_config(client):
    cfg = load_default_score_config().model_dump(mode="json")
    for p in cfg["pillars"].values():
        p["weight"] = 0
    cfg["pillars"]["economics_cost"]["weight"] = 1
    r = client.post("/api/rank", json={"geo_level": "county", "config": cfg, "limit": 12}).json()
    for row in r["rows"]:
        econ = next(p for p in row["pillar_scores"] if p["pillar"] == "economics_cost")
        assert abs(row["score"] - econ["score"]) < 1e-6


def test_score_config_versioning(client):
    cfg = load_default_score_config().model_dump(mode="json")
    cfg.update({"id": "aggressive", "name": "Aggressive growth"})
    cfg["pillars"]["demographics_growth"]["weight"] = 50
    v1 = client.post("/api/score/configs", json=cfg).json()
    v2 = client.post("/api/score/configs", json=cfg).json()
    assert (v1["version"], v2["version"]) == (1, 2)
    assert client.get("/api/score/configs/aggressive").json()["version"] == 2
    assert client.get("/api/score/configs/aggressive", params={"version": 1}).json()["version"] == 1
    assert {c["id"] for c in client.get("/api/score/configs").json()} >= {"default", "aggressive"}
    cfg["metric_weights"] = {"not_a_metric": 1}
    assert client.post("/api/score/configs", json=cfg).status_code == 422


def test_explain(client):
    r = client.post("/api/score/explain", json={"geo_level": "county", "geo_id": "04019"})
    assert r.status_code == 200 and len(r.json()["contributions"]) > 20


def test_map_layer_falls_back_to_points(client):
    r = client.get("/api/map/county")
    assert r.status_code == 200
    fc = r.json()
    assert fc["type"] == "FeatureCollection" and len(fc["features"]) == 12
    assert fc["features"][0]["properties"]["score"] is not None


def test_map_layer_accepts_adhoc_config_and_state_filter(client, score_config):
    cfg = score_config.model_dump(mode="json")
    cfg["pillars"]["medicare_demand"]["weight"] = 100
    for pid in cfg["pillars"]:
        if pid != "medicare_demand":
            cfg["pillars"][pid]["weight"] = 0
    r = client.post("/api/map/county", json={"config": cfg, "states": ["AZ"]})
    assert r.status_code == 200
    fc = r.json()
    assert fc["features"] and all(f["properties"]["state_abbr"] == "AZ" for f in fc["features"])
    baseline = client.get("/api/map/county?states=AZ").json()
    by_id = {f["id"]: f["properties"]["score"] for f in baseline["features"]}
    assert any(abs(f["properties"]["score"] - by_id[f["id"]]) > 1e-6 for f in fc["features"])


def test_financial_endpoints(client):
    d = client.get("/api/financial/defaults").json()
    assert d["patients"]["panel_cap_per_provider"] == 800
    r = client.post("/api/financial/run", json=d).json()
    assert len(r["annual"]) == 5 and r["irr_pct"] is not None
    bad = dict(d)
    bad["patients"] = {**d["patients"], "annual_churn_pct": 150}
    assert client.post("/api/financial/run", json=bad).status_code == 422
    s = client.post(
        "/api/financial/sensitivity",
        json={"assumptions": d, "variable_x": "patients.new_patients_per_month", "values_x": [40, 65, 90]},
    ).json()
    assert len(s["grid"][0]) == 3


def test_scenario_crud(client):
    a = load_default_financial_assumptions().model_dump(mode="json")
    body = {"id": "x", "name": "Phoenix pilot", "geo_level": "county", "geo_id": "04013", "assumptions": a}
    r = client.put("/api/financial/scenarios/phoenix", json=body)
    assert r.status_code == 200 and r.json()["id"] == "phoenix"
    assert client.get("/api/financial/scenarios/phoenix").json()["name"] == "Phoenix pilot"
    assert any(s["id"] == "phoenix" for s in client.get("/api/financial/scenarios").json())
    assert client.delete("/api/financial/scenarios/phoenix").status_code == 204
    assert client.get("/api/financial/scenarios/phoenix").status_code == 404


def test_metrics_registry_endpoint(client):
    r = client.get("/api/meta/metrics").json()
    assert len(r["metrics"]) >= 40 and "acs5" in r["sources"]
    assert len(client.get("/api/meta/states").json()) == 5
