"""The bus and the clock (docs/nodes_design_zh.md, step 1): nodes talk through messages and
do not know each other."""

from datetime import date, datetime

import pytest

from fish.bus import Bus, BusError
from fish.clock import Clock, day_of
from fish.msgs import DayEnded, HeSaid, SheSaid, TimePassed

T = datetime(2026, 10, 28, 18, 0)


def test_a_message_reaches_every_subscriber_of_its_topic_in_order():
    bus, got = Bus(), []
    bus.subscribe(HeSaid, lambda m: got.append(("memory", m.text)))
    bus.subscribe(HeSaid, lambda m: got.append(("mood", m.text)))
    bus.subscribe(SheSaid, lambda m: got.append(("screen", m.text)))
    bus.publish(HeSaid("在吗", T, "wechat"))
    assert got == [("memory", "在吗"), ("mood", "在吗")]
    bus.publish(SheSaid("在", T, "wechat"))
    assert got[-1] == ("screen", "在")


def test_nobody_listening_is_fine_and_a_topic_must_be_a_message_class():
    Bus().publish(HeSaid("在吗", T, "wechat"))
    with pytest.raises(TypeError):
        Bus().subscribe("he_said", print)  # type: ignore[arg-type]


def test_one_broken_node_does_not_silence_the_others():
    bus, got = Bus(), []

    def broken(m):
        raise RuntimeError("screen unplugged")

    bus.subscribe(SheSaid, broken)
    bus.subscribe(SheSaid, lambda m: got.append(m.text))
    with pytest.raises(BusError) as e:  # tests see the failure...
        bus.publish(SheSaid("在", T, "wechat"))
    assert got == ["在"] and "broken" in str(e.value)
    logged = []
    bus.on_error = lambda m, h, err: logged.append(str(err))  # ...the running service logs it
    bus.publish(SheSaid("还在", T, "wechat"))
    assert got == ["在", "还在"] and logged == ["screen unplugged"]


def test_messages_are_frozen():
    m = HeSaid("在吗", T, "wechat")
    with pytest.raises(Exception):
        m.text = "改了"  # type: ignore[misc]


def test_her_day_runs_from_half_past_three():
    assert day_of(datetime(2026, 10, 29, 1, 0)) == date(2026, 10, 28)
    assert day_of(datetime(2026, 10, 29, 3, 30)) == date(2026, 10, 29)


def test_the_clock_ticks_and_ends_days_once_each_even_after_a_long_sleep():
    bus, got = Bus(), []
    bus.subscribe(TimePassed, lambda m: got.append(("tick", m.now.strftime("%d %H:%M"))))
    bus.subscribe(DayEnded, lambda m: got.append(("day", m.day.isoformat())))
    clock = Clock(bus)
    clock.tick(datetime(2026, 10, 28, 23, 0))
    clock.tick(datetime(2026, 10, 29, 3, 0))
    clock.tick(datetime(2026, 10, 29, 3, 0))  # the same moment again: nothing new
    clock.tick(datetime(2026, 10, 29, 4, 0))  # 03:30 crossed: the 28th is over
    clock.tick(datetime(2026, 10, 31, 9, 0))  # the laptop slept two nights
    assert got == [("tick", "28 23:00"), ("tick", "29 03:00"), ("tick", "29 04:00"), ("day", "2026-10-28"),
                   ("tick", "31 09:00"), ("day", "2026-10-29"), ("day", "2026-10-30")]
