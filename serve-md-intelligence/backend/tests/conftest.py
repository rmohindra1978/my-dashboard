from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.app.data.warehouse import warehouse
from backend.app.main import create_app
from backend.app.registry import load_default_financial_assumptions, load_default_score_config
from pipelines.build import build


@pytest.fixture(scope="session")
def sample_warehouse(tmp_path_factory: pytest.TempPathFactory) -> Path:
    path = tmp_path_factory.mktemp("wh") / "sample.duckdb"
    build([], sample=True, warehouse_path=path)
    return path


@pytest.fixture()
def con(sample_warehouse: Path):
    with warehouse(sample_warehouse, read_only=False) as c:
        yield c


@pytest.fixture()
def client(sample_warehouse: Path) -> TestClient:
    return TestClient(create_app(sample_warehouse))


@pytest.fixture()
def score_config():
    return load_default_score_config().model_copy(deep=True)


@pytest.fixture()
def assumptions():
    return load_default_financial_assumptions().model_copy(deep=True)
