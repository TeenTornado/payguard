"""Unit tests for the cross-process chaos sentinel."""
from __future__ import annotations

import pytest

from payguard.shared.chaos import ChaosState, read_chaos, set_chaos, write_chaos


@pytest.fixture(autouse=True)
def isolated_sentinel(monkeypatch, tmp_path):
    monkeypatch.setenv("PAYGUARD_CHAOS_FILE", str(tmp_path / "chaos.json"))
    write_chaos(ChaosState())
    yield
    write_chaos(ChaosState())


def test_missing_file_defaults_to_all_off():
    assert read_chaos() == ChaosState(llm=False, gateway=False)


def test_partial_update_leaves_other_switch_untouched():
    set_chaos(gateway=True)
    assert read_chaos() == ChaosState(llm=False, gateway=True)
    set_chaos(llm=True)  # must not clear gateway
    assert read_chaos() == ChaosState(llm=True, gateway=True)


def test_clearing_all_removes_the_file(tmp_path):
    from payguard.shared.chaos import chaos_path

    set_chaos(llm=True)
    assert chaos_path().exists()
    write_chaos(ChaosState())
    assert not chaos_path().exists()


def test_corrupt_file_reads_as_all_off():
    from payguard.shared.chaos import chaos_path

    chaos_path().write_text("{not valid json", encoding="utf-8")
    assert read_chaos() == ChaosState()
