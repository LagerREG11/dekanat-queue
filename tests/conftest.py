import sys
from datetime import datetime, timedelta
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import db as repo
from app.web import create_app

# Дүйсенбі, 10:00 — деканат ашық уақыт
MONDAY_10 = datetime(2026, 11, 16, 10, 0, 0)


class Clock:
    """Тесттерде уақытты басқаруға арналған сағат."""

    def __init__(self, start):
        self.value = start

    def __call__(self):
        return self.value

    def advance(self, minutes):
        self.value += timedelta(minutes=minutes)


@pytest.fixture
def clock():
    return Clock(MONDAY_10)


@pytest.fixture
def conn():
    c = repo.connect(":memory:")
    repo.init_db(c)
    repo.seed(c)
    yield c
    c.close()


@pytest.fixture
def app(tmp_path, clock):
    application = create_app({
        "DATABASE": str(tmp_path / "test.db"),
        "SECRET_KEY": "test",
        "TESTING": True,
        "WTF_CSRF_DISABLED": True,
        "CHECK_HOURS": True,
        "NOW": clock,
        "RATE_LIMIT": 100,
    })
    yield application
    application.extensions["db"].close()


@pytest.fixture
def client(app):
    return app.test_client()
