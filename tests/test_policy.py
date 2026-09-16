from datetime import datetime, timedelta, timezone

from token_saver.policy import Advice, advise, idle_gaps, reminder
from token_saver.sessions import Report, Turn


def _ts(minutes: int) -> str:
    base = datetime(2026, 1, 1, tzinfo=timezone.utc)
    return (base + timedelta(minutes=minutes)).isoformat()


def test_idle_gaps_mixed_timezone_does_not_crash():
    turns = [
        Turn(session="s", created=0, read=0, timestamp="2026-01-01T00:00:00"),
        Turn(session="s", created=0, read=0, timestamp="2026-01-01T00:40:00Z"),
    ]
    gaps = idle_gaps(turns, minutes=15)
    assert len(gaps) == 1


def test_idle_gaps_detects_long_pause():
    turns = [
        Turn(session="s", created=0, read=0, timestamp=_ts(0)),
        Turn(session="s", created=0, read=0, timestamp=_ts(40)),
    ]
    gaps = idle_gaps(turns, minutes=15)
    assert len(gaps) == 1
    assert gaps[0][2] == 40


def test_advise_flags_reprime():
    report = Report()
    report.turns.append(Turn(session="s", created=80_000, read=1_000, timestamp=_ts(0)))
    report.turns.append(Turn(session="s", created=80_000, read=1_000, timestamp=_ts(40)))
    report.usage["cache_creation_input_tokens"] = 80_000
    kinds = {a.kind for a in advise(report)}
    assert "clear" in kinds


def test_reminder_empty_when_clean():
    assert reminder(Report()) == ""


def test_advice_dataclass():
    a = Advice("ok", "fine")
    assert a.tokens_at_stake == 0


def test_reminder_only_when_tokens_at_stake():
    report = Report()
    report.turns.append(Turn(session="s", created=80_000, read=1_000, timestamp=_ts(0)))
    report.turns.append(Turn(session="s", created=80_000, read=1_000, timestamp=_ts(40)))
    report.usage["cache_creation_input_tokens"] = 80_000
    text = reminder(report)
    assert text.startswith("token-saver: clear")
    assert "/clear" in text


def test_nudge_silent_when_no_churn(tmp_path):
    from token_saver.policy import user_nudge
    assert user_nudge(tmp_path, "start over from scratch") == ""
