import pytest

from openepw.harness.session_lock import SessionBusy, session_lock


def test_one_writer_per_data_root_and_thread(tmp_path):
    with session_lock(tmp_path, "console"):
        with pytest.raises(SessionBusy):
            with session_lock(tmp_path, "console"):
                pass
        with session_lock(tmp_path, "another-chat"):
            pass
    with session_lock(tmp_path, "console"):
        pass
