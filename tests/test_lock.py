import pytest

from journal_featured import lock


def test_lock_excludes_second_holder(tmp_path):
    path = tmp_path / "run.lock"
    assert not lock.is_held(path)
    with lock.hold(path):
        assert lock.is_held(path)
        with pytest.raises(lock.Busy):
            with lock.hold(path):
                pass
    assert not lock.is_held(path)
