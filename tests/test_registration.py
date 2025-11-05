def test_register_new():
    from NeuroKit.registration import register
    state = register("test", 9999)
    assert state["status"] == "New"
