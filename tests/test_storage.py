"""Tests for core.storage."""
from decimal import Decimal


class TestUserPosition:
    def test_get_returns_none_when_no_position(self, storage_module):
        assert storage_module.get_user_position(42) is None

    def test_set_then_get_roundtrip(self, storage_module):
        storage_module.set_user_position(42, Decimal("0.05"), Decimal("92000"))
        pos = storage_module.get_user_position(42)
        assert pos == {"size": Decimal("0.05"), "entry_price": Decimal("92000")}

    def test_set_overwrites_existing(self, storage_module):
        storage_module.set_user_position(42, Decimal("0.05"), Decimal("92000"))
        storage_module.set_user_position(42, Decimal("-0.10"), Decimal("95000"))
        pos = storage_module.get_user_position(42)
        assert pos["size"] == Decimal("-0.10")
        assert pos["entry_price"] == Decimal("95000")

    def test_clear_removes_user(self, storage_module):
        storage_module.set_user_position(42, Decimal("0.05"), Decimal("92000"))
        storage_module.clear_user_position(42)
        assert storage_module.get_user_position(42) is None

    def test_clear_nonexistent_is_noop(self, storage_module):
        storage_module.clear_user_position(999)  # should not raise

    def test_string_user_id_works(self, storage_module):
        storage_module.set_user_position("42", Decimal("0.05"), Decimal("92000"))
        pos = storage_module.get_user_position(42)
        assert pos == {"size": Decimal("0.05"), "entry_price": Decimal("92000")}

    def test_corrupted_json_returns_none(self, storage_module):
        # Write garbage to the storage file, confirm graceful handling
        storage_module.STORAGE_FILE.write_text("{not valid json")
        assert storage_module.get_user_position(42) is None


class TestRegisteredUsers:
    def test_empty_initially(self, storage_module):
        assert storage_module.get_all_users() == []

    def test_register_and_list(self, storage_module):
        storage_module.register_user(42)
        storage_module.register_user(99)
        assert set(storage_module.get_all_users()) == {42, 99}

    def test_register_dedupes(self, storage_module):
        storage_module.register_user(42)
        storage_module.register_user(42)
        assert storage_module.get_all_users() == [42]

    def test_register_accepts_string_id(self, storage_module):
        storage_module.register_user("42")
        assert storage_module.get_all_users() == [42]

    def test_corrupted_users_file_returns_empty(self, storage_module):
        storage_module.USERS_FILE.write_text("not json")
        assert storage_module.get_all_users() == []


class TestPreviousState:
    def test_get_returns_none_when_no_file(self, storage_module):
        assert storage_module.get_previous_state() is None

    def test_save_then_get_roundtrip(self, storage_module):
        state = {
            "direction": "long",
            "size": Decimal("0.5"),
            "entry_price": Decimal("90000"),
            "orders": [{"oid": "1", "side": "B", "sz": "0.05", "limitPx": "89000"}],
        }
        storage_module.save_previous_state(state)
        loaded = storage_module.get_previous_state()
        assert loaded["direction"] == "long"
        assert loaded["size"] == "0.5"  # serialized as string
        assert len(loaded["orders"]) == 1

    def test_save_strips_unknown_order_fields(self, storage_module):
        state = {
            "direction": "long",
            "size": Decimal("0.5"),
            "entry_price": Decimal("90000"),
            "orders": [{"oid": "1", "side": "B", "sz": "0.05", "limitPx": "89000",
                        "internalField": "should_be_dropped"}],
        }
        storage_module.save_previous_state(state)
        loaded = storage_module.get_previous_state()
        assert "internalField" not in loaded["orders"][0]

    def test_corrupted_prev_state_returns_none(self, storage_module):
        storage_module.PREV_STATE_FILE.write_text("{bad json")
        assert storage_module.get_previous_state() is None


class TestAtomicWrite:
    def test_atomic_write_creates_parent_dir(self, storage_module, tmp_path):
        target = tmp_path / "nested" / "deeper" / "file.json"
        storage_module._atomic_write(target, '{"k": "v"}')
        assert target.read_text() == '{"k": "v"}'

    def test_atomic_write_cleans_up_temp_on_failure(self, storage_module, tmp_path, monkeypatch):
        target = tmp_path / "file.json"
        # Force os.replace to fail
        def boom(*args, **kwargs):
            raise OSError("simulated")
        monkeypatch.setattr("core.storage.os.replace", boom)
        try:
            storage_module._atomic_write(target, "x")
        except OSError:
            pass
        # No leftover .tmp files
        leftovers = list(tmp_path.glob("*.tmp"))
        assert leftovers == []
