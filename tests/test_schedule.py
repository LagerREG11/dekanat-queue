"""Жұмыс кестесі, үзілістер және рөл құқықтары (service.py)."""
from datetime import datetime, time

import pytest

from app import service as ql


def test_default_breaks_close_reception():
    assert ql.is_open(datetime(2026, 11, 16, 11, 5)) is False      # 11:00-11:15 үзіліс
    assert ql.current_pause(datetime(2026, 11, 16, 11, 5)) == "break"
    assert ql.current_pause(datetime(2026, 11, 16, 13, 30)) == "lunch"
    assert ql.current_pause(datetime(2026, 11, 16, 10, 0)) is None
    assert ql.is_open(datetime(2026, 11, 16, 11, 15)) is True       # үзіліс аяқталды


def test_build_schedule_ok():
    s = ql.build_schedule("08:30", "17:00", "12:30", "13:30", "10:30-10:40; 15:00-15:10", ["0", "1", "5"])
    assert s.open_at == time(8, 30) and s.close_at == time(17, 0)
    assert s.breaks == ((time(10, 30), time(10, 40)), (time(15, 0), time(15, 10)))
    assert s.workdays == (0, 1, 5)


def test_build_schedule_without_lunch_and_breaks():
    s = ql.build_schedule("09:00", "13:00", "", "", "", [5])
    assert s.lunch_from is None and s.breaks == ()
    assert ql.is_open(datetime(2026, 11, 21, 12, 0), s) is True     # сенбі
    assert ql.is_open(datetime(2026, 11, 16, 12, 0), s) is False    # дүйсенбі жұмыс күні емес


MANY_BREAKS = "10:00-10:01, 10:02-10:03, 10:04-10:05, 10:06-10:07, 10:08-10:09, 11:00-11:01"


@pytest.mark.parametrize("args,err", [
    (("18:00", "09:00", "", "", "", [0]), "err_hours_order"),
    (("09:00", "09:00", "", "", "", [0]), "err_hours_order"),
    (("9", "18:00", "", "", "", [0]), "err_time"),
    (("25:00", "18:00", "", "", "", [0]), "err_time"),
    (("09:00", "18:00", "13:00", "", "", [0]), "err_time"),
    (("09:00", "18:00", "08:00", "09:30", "", [0]), "err_lunch"),
    (("09:00", "18:00", "14:00", "13:00", "", [0]), "err_lunch"),
    (("09:00", "18:00", "", "", "08:00-08:10", [0]), "err_break"),
    (("09:00", "18:00", "", "", "10:00-11:30", [0]), "err_break_long"),
    (("09:00", "18:00", "13:00", "14:00", "13:30-13:40", [0]), "err_break_overlap"),
    (("09:00", "18:00", "", "", "10:00-10:20, 10:10-10:30", [0]), "err_break_overlap"),
    (("09:00", "18:00", "", "", "10:00", [0]), "err_time"),
    (("09:00", "18:00", "", "", MANY_BREAKS, [0]), "err_breaks_many"),
    (("09:00", "18:00", "", "", "", []), "err_workdays"),
    (("09:00", "18:00", "", "", "", ["7", "x"]), "err_workdays"),
])
def test_build_schedule_errors(args, err):
    with pytest.raises(ql.QueueError) as e:
        ql.build_schedule(*args)
    assert e.value.code == err


def test_schedule_roundtrip():
    s = ql.build_schedule("09:00", "18:00", "13:00", "14:00", "11:00-11:15", [0, 1, 2, 3, 4])
    assert ql.schedule_from_dict(ql.schedule_to_dict(s)) == s
    assert ql.schedule_to_dict(s)["breaks"] == "11:00-11:15"


@pytest.mark.parametrize("actor,target,new,ok", [
    (ql.ADMIN, ql.ADMIN, None, True),
    (ql.ADMIN, ql.STUDENT, ql.ADMIN, True),
    (ql.DEKANAT, ql.STUDENT, None, True),      # декан студентті, орынбасарды басқарады
    (ql.DEKANAT, ql.DEPUTY, ql.DEKANAT, True),
    (ql.DEKANAT, ql.ADMIN, None, False),       # администраторды өзгерте алмайды
    (ql.DEKANAT, ql.STUDENT, ql.ADMIN, False),  # администратор рөлін бере алмайды
    (ql.DEPUTY, ql.STUDENT, ql.DEPUTY, True),
    (ql.DEPUTY, ql.DEPUTY, None, True),
    (ql.DEPUTY, ql.DEKANAT, None, False),      # деканның аккаунтын өзгерте алмайды
    (ql.DEPUTY, ql.ADMIN, None, False),
    (ql.DEPUTY, ql.STUDENT, ql.DEKANAT, False),  # декан рөлін бере алмайды
    (ql.STUDENT, ql.STUDENT, None, False),
])
def test_can_manage_user(actor, target, new, ok):
    assert ql.can_manage_user(actor, target, new) is ok
