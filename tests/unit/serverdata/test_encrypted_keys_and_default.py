"""Keys are stored encrypted, the built-in key is server-only, and addresses can be restricted."""

import os
import sqlite3
import stat

import pytest

from config.runtime_schemas import ServingConfig
from serverdata import ServerData, netcheck
from serverdata.crypto import SecretBox, SecretBoxError, load_master
from serverdata.keys import KeyError_

MASTER = b"another-master-secret-0123456789"


def make(tmp_path, **cfg):
    return ServerData(
        ServingConfig(data_dir=str(tmp_path / "srv"), cache_ttl_s=0.0, **cfg), tmp_path
    )


def test_secret_box_round_trip_and_tamper_detection():
    box = SecretBox(MASTER)
    blob = box.seal("lk_deadbeef_super-secret-value")
    assert b"super-secret" not in blob and box.open(blob) == "lk_deadbeef_super-secret-value"
    assert box.seal("same") != box.seal("same")  # fresh nonce every time
    for index in (3, 20, len(blob) - 1):  # nonce, ciphertext and tag are all authenticated
        broken = bytearray(blob)
        broken[index] ^= 1
        with pytest.raises(SecretBoxError):
            box.open(bytes(broken))
    with pytest.raises(SecretBoxError):
        SecretBox(b"a-different-master-secret-xyz").open(blob)
    with pytest.raises(SecretBoxError):
        box.open(b"short")
    assert box.lookup_digest("k") != SecretBox(b"a-different-master-secret-xyz").lookup_digest("k")


def test_master_secret_from_env_or_a_private_file(tmp_path):
    assert load_master("M", "", {"M": "x" * 20}) == b"x" * 20
    with pytest.raises(ValueError):
        load_master("M", "", {"M": "short"})
    path = tmp_path / "dir" / "master.secret"
    first = load_master("", str(path), {})
    assert stat.S_IMODE(path.stat().st_mode) == 0o600 and load_master("", str(path), {}) == first
    path.chmod(0o644)
    with pytest.raises(ValueError):
        load_master("", str(path), {})


def test_keys_are_stored_encrypted_and_can_be_revealed(tmp_path):
    data = make(tmp_path)
    record, key = data.keys.create("Eve", "user", None)
    raw = (tmp_path / "srv/laris-server.db").read_bytes()
    assert key.encode() not in raw and key.split("_", 2)[2].encode() not in raw
    row = (
        sqlite3.connect(tmp_path / "srv/laris-server.db")
        .execute("SELECT digest, secret_enc FROM keys")
        .fetchone()
    )
    assert row[1] and key not in row[0] and len(row[0]) == 64
    assert data.keys.reveal(record.id) == key
    assert data.keys.verify(key).id == record.id
    other = SecretBox(b"a-different-master-secret-xyz")
    data.keys.box = other  # a server restarted with the wrong master cannot read or verify anything
    assert data.keys.verify(key) is None
    with pytest.raises(KeyError_):
        data.keys.reveal(record.id)


def test_older_keys_are_upgraded_to_encrypted_storage_on_first_use(tmp_path):
    import hashlib

    data = make(tmp_path)
    record, key = data.keys.create("Old", "user", None)
    data.db.connection().execute(
        "UPDATE keys SET digest=?, secret_enc=NULL WHERE id=?",
        (hashlib.sha256(key.encode()).hexdigest(), record.id),
    )  # as stored before this change
    with pytest.raises(KeyError_):
        data.keys.reveal(record.id)
    assert data.keys.verify(key) is not None
    assert data.keys.reveal(record.id) == key


def test_default_key_exists_once_with_every_permission_unlimited_and_server_only(tmp_path):
    data = make(tmp_path)
    assert data.keys.default_key() is None
    key = data.ensure_default_key()
    assert key and data.ensure_default_key() is None  # created once only
    record = data.keys.default_key()
    assert record.builtin and record.token_limit is None and record.allowed_ips == ("@server",)
    assert data.keys.effective_permissions(record) >= set(data.known_permissions)
    assert {
        "chat",
        "keys.manage",
        "reasoning.read",
        "usage.read",
    } <= data.keys.effective_permissions(record)
    assert data.keys.reveal(record.id) == key
    # usable from this machine, from nowhere else
    assert data.auth.authenticate(key, "127.0.0.1") is not None
    assert data.auth.authenticate(key, "::1") is not None
    assert data.auth.authenticate(key, "::ffff:127.0.0.1") is not None
    own = sorted(str(a) for a in data.own() if not a.is_loopback)
    for address in own:
        assert data.auth.authenticate(key, address) is not None
    assert data.auth.authenticate(key, "203.0.113.9") is None  # looks like an unknown key
    assert data.auth.authenticate(key, None) is None
    assert data.auth.authenticate(key + "x", "127.0.0.1") is None


def test_the_server_finds_its_own_addresses_and_honours_extras():
    found = netcheck.own_addresses(["198.51.100.4"])
    assert netcheck.parse("198.51.100.4") in found
    assert netcheck.parse("::ffff:10.1.2.3") == netcheck.parse("10.1.2.3")
    assert netcheck.parse("not-an-ip") is None


def test_address_rules():
    nobody = lambda: set()  # noqa: E731
    assert netcheck.allowed("8.8.8.8", [], nobody)  # no rule: any address
    assert netcheck.allowed("10.2.3.4", ["10.0.0.0/8"], nobody)
    assert not netcheck.allowed("11.2.3.4", ["10.0.0.0/8"], nobody)
    assert netcheck.allowed("203.0.113.7", ["203.0.113.7"], nobody)
    assert netcheck.allowed("127.0.0.1", ["@server"], nobody)
    assert netcheck.allowed("192.0.2.5", ["@server"], lambda: {netcheck.parse("192.0.2.5")})
    assert not netcheck.allowed("192.0.2.6", ["@server"], lambda: {netcheck.parse("192.0.2.5")})
    assert not netcheck.allowed("garbage", ["10.0.0.0/8"], nobody)


def test_other_keys_can_be_limited_to_addresses(tmp_path):
    data = make(tmp_path)
    record, key = data.keys.create("Office", "user", None, allowed_ips=["203.0.113.0/24"])
    assert data.auth.authenticate(key, "203.0.113.50") is not None
    assert data.auth.authenticate(key, "198.51.100.1") is None
    data.keys.set_allowed_ips(record.id, [])
    assert data.auth.authenticate(key, "198.51.100.1") is not None
    with pytest.raises(KeyError_):
        data.keys.create("Bad", "user", None, allowed_ips=["not-a-cidr"])


def test_key_commands_reveal_and_ip(tmp_path, monkeypatch, capsys):
    from cli.main import main

    monkeypatch.chdir(tmp_path)
    assert main(["keys", "create", "--label", "A", "--allow-ip", "10.0.0.0/8"]) == 0
    out = capsys.readouterr().out
    key = out.split("shown once, give it to the user): ")[1].split()[0]
    key_id = key.split("_")[1]
    assert "from 10.0.0.0/8" in out
    assert main(["keys", "reveal", key_id]) == 0 and capsys.readouterr().out.strip() == key
    assert main(["keys", "ip", key_id, "--clear"]) == 0 and "from" not in capsys.readouterr().out
    assert main(["keys", "ip", key_id, "--allow", "@server"]) == 0
    assert main(["keys", "ip", key_id, "--allow", "bogus"]) == 2
    assert main(["keys", "reveal", "default"]) == 2  # created when the server first starts
    assert os.environ["LARIS_SERVER_MASTER"]


def test_aes_gcm_is_current_and_legacy_blobs_still_open():
    box = SecretBox(MASTER)
    assert box.seal("x")[:1] == b"\x02" and not box.needs_upgrade(box.seal("x"))
    legacy = box._seal_legacy("lk_old_value")
    assert box.needs_upgrade(legacy) and box.open(legacy) == "lk_old_value"
