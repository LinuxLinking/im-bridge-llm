from bridge.state import State, fingerprint


def test_fingerprint_is_stable_and_order_sensitive():
    assert fingerprint("12:00", "hi") == fingerprint("12:00", "hi")
    assert fingerprint("12:00", "hi") != fingerprint("12:01", "hi")
    assert fingerprint("12:00", "hi") != fingerprint("hi", "12:00")


def test_processed_and_failed_are_tracked(tmp_path):
    p = str(tmp_path / "state.json")
    s = State.load(p)
    s.mark_processed("群A", "fp1")
    s.mark_failed("群A", "fp2")
    s.save(p)

    s2 = State.load(p)
    assert "fp1" in s2.processed("群A")
    assert "fp2" in s2.failed("群A")
    assert "fp2" not in s2.processed("群A")


def test_processed_list_is_capped(tmp_path):
    s = State()
    for i in range(80):
        s.mark_processed("群A", "fp%d" % i)
    assert len(s.processed("群A")) == 50
    assert "fp79" in s.processed("群A")


def test_missing_state_file_loads_empty(tmp_path):
    s = State.load(str(tmp_path / "nope.json"))
    assert s.to_dict() == {}
    assert s.fingerprint_of("群A") == ""
