import sys
from datetime import datetime, timedelta
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import db as repo
from app.web import create_app


def make_iin(n: int) -> str:
    """Тесттер үшін n-ші жарамды ЖСН (бақылау цифры дұрыс)."""
    from app.service import iin_control_digit
    found = -1
    for serial in range(10000):
        first11 = f"0001015{serial:04d}"
        control = iin_control_digit(first11)
        if control is not None:
            found += 1
            if found == n:
                return first11 + str(control)
    raise ValueError(n)


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
