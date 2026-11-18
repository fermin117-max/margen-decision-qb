"""Pruebas de la API con datos reales (tarda ~1 min por la carga inicial).

Uso: .venv\\Scripts\\python.exe -m pytest backend/test_api.py -q
"""
import pytest
from fastapi.testclient import TestClient

from backend import main, service as sv

# Valores de la última validación (validate_pressure, versión 2).
EXPECTED = {"pressure_before_throw": 1707, "pressure_after_throw": 1780, "simultaneous_pressure_and_throw": 485,
            "pressure_not_observed_censored": 3610, "not_applicable_no_throw": 950, "not_applicable_no_snap": 24,
            "not_applicable_no_qb_or_rushers": 1}


@pytest.fixture(scope="module")
def client():
    with TestClient(main.app) as c:
        assert sv.STORE.wait(600), sv.STORE.error
        yield c


def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200 and r.json() == {"status": "ok"}


def test_summary_matches_validation(client):
    d = client.get("/api/summary").json()
    assert d["total_jugadas"] == 8557 and d["suma_categorias"] == 8557
    cats = {c["categoria"]: c["jugadas"] for c in d["categorias"]}
    for k, v in EXPECTED.items():
        assert cats[k] == v, k
    assert d["presion_antes_del_lanzamiento"] == 1707 and d["censuradas"] == 3610
    assert d["sin_lanzamiento"] == 950 and d["sin_snap"] == 24 and d["sin_pass_rushers"] == 1
    assert d["margen_exacto"]["n"] == 1707 + 1780 + 485
    assert d["margen_exacto"]["max"] <= 0.5
    assert d["tiempo_hasta_presion_s"]["n"] == 4742
    assert abs(sum(c["porcentaje"] for c in d["categorias"]) - 100) < 0.05


def test_censored_never_in_exact(client):
    t = sv.STORE.plays
    cen = t[t["margin_category"] == "pressure_not_observed_censored"]
    assert cen["decision_margin_s"].isna().all() and not cen["margin_is_exact"].any()
    d = client.get("/api/plays", params={"margin_category": "pressure_not_observed_censored", "limit": 1000}).json()
    assert d["total"] == 3610 and d["margen_exacto"]["n"] == 0
    assert all(p["decision_margin_s"] is None and p["observed_margin_lower_bound_s"] is not None
               for p in d["jugadas"])


def test_quarterbacks(client):
    d = client.get("/api/quarterbacks").json()
    rows = d["quarterbacks"]
    assert sum(r["jugadas_analizadas"] for r in rows) == 8557
    assert sum(r["margenes_exactos"] for r in rows) == 3972
    assert all(r["margen_exacto_mediana_s"] is None for r in rows if not r["muestra_suficiente"])
    ranked = client.get("/api/quarterbacks", params={"sort_by": "mediana"}).json()["quarterbacks"]
    flags = [r["muestra_suficiente"] for r in ranked]
    assert flags == sorted(flags, reverse=True)  # suficientes primero
    qid = max(rows, key=lambda r: r["jugadas_analizadas"])["nfl_id"]
    det = client.get(f"/api/quarterbacks/{qid}").json()
    for k in ("formacion", "cobertura", "down", "distancia_por_avanzar", "resultado"):
        assert sum(x["jugadas"] for x in det["desgloses"][k]) == det["resumen"]["jugadas"]
    assert client.get("/api/quarterbacks/1").status_code == 404


def test_defenders(client):
    d = client.get("/api/defenders").json()
    rows = d["defensores"]
    assert sum(r["jugadas_como_pass_rusher"] for r in rows) == 36362
    assert sum(r["primero_en_llegar"] for r in rows) >= 4742  # empates cuentan para cada defensor


def test_breakdowns_and_histogram(client):
    b = client.get("/api/breakdowns").json()
    assert sum(r["jugadas"] for r in b["formacion"]) + 0 <= 8557
    assert sum(r["margenes_exactos"] for r in b["formacion"]) <= 3972
    h = client.get("/api/summary").json()["histograma_margen_exacto"]
    assert sum(x["jugadas"] for x in h) == 3972 and max(x["margen_s"] for x in h) <= 0.4


def test_plays_filters_and_detail(client):
    f = client.get("/api/filters").json()
    assert {c["valor"] for c in f["categorias_margen"]} == set(sv.MARGIN_CATEGORIES)
    qb = f["quarterbacks"][0]["nfl_id"]
    r = client.get("/api/plays", params={"qb_id": qb, "limit": 5}).json()
    assert r["total"] == f["quarterbacks"][0]["jugadas"] and all(p["qb_nflId"] == qb for p in r["jugadas"])
    for opt_key, param in (("formaciones", "formation"), ("coberturas", "coverage"), ("downs", "down")):
        o = f[opt_key][0]
        assert client.get("/api/plays", params={param: o["valor"], "limit": 1}).json()["total"] == o["jugadas"]
    out = client.get("/api/plays", params={"outcome": "sack", "limit": 1}).json()
    assert out["total"] == 543
    dfd = f["defensores"][0]
    r = client.get("/api/plays", params={"defender_id": dfd["nfl_id"], "limit": 1000}).json()
    assert r["total"] == dfd["jugadas_como_pass_rusher"]
    p = r["jugadas"][0]
    det = client.get(f"/api/plays/{p['gameId']}/{p['playId']}").json()
    assert det["gameId"] == p["gameId"] and any(x["nflId"] == dfd["nfl_id"] for x in det["pass_rushers"])
    assert client.get("/api/plays/1/1").status_code == 404
    assert client.get("/api/plays", params={"margin_category": "otra"}).status_code == 422
