"""Static checks of docker/compose.yaml and the Caddyfile; no Docker daemon needed."""

import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[3]
COMPOSE = yaml.safe_load((ROOT / "docker" / "compose.yaml").read_text(encoding="utf-8"))
CADDY = (ROOT / "docker" / "Caddyfile").read_text(encoding="utf-8")
SERVICES = COMPOSE["services"]


def test_only_caddy_publishes_ports():
    assert [n for n, s in SERVICES.items() if s.get("ports")] == ["caddy"]
    assert set(SERVICES) == {"caddy", "api", "model", "postgres"}


def test_the_backend_network_is_internal_and_the_inner_services_are_only_on_it():
    assert COMPOSE["networks"]["backend"]["internal"] is True
    for name in ("api", "model", "postgres"):
        assert SERVICES[name]["networks"] == ["backend"], name
    assert set(SERVICES["caddy"]["networks"]) == {"edge", "backend"}


def test_policy_and_weights_are_read_only_mounts():
    api = SERVICES["api"]["volumes"]
    assert "../.laris:/app/.laris:ro" in api and "../LARIS.md:/app/LARIS.md:ro" in api
    assert any(v.endswith(":/models:ro") for v in SERVICES["model"]["volumes"])
    assert not any(":/app/.laris" in v and not v.endswith(":ro") for v in api)


def test_integrity_is_enforced_when_the_api_starts():
    assert SERVICES["api"]["environment"]["LARIS_PROMPTS__INTEGRITY"] == "enforce"


def test_every_secret_is_a_docker_secret_and_none_is_written_in_the_file():
    secrets = COMPOSE["secrets"]
    assert set(secrets) == {"laris_master", "laris_database_url", "laris_postgres_password"}
    assert set(SERVICES["api"]["secrets"]) == {"laris_master", "laris_database_url"}
    assert SERVICES["postgres"]["secrets"] == ["laris_postgres_password"]
    env = SERVICES["api"]["environment"]
    assert env["LARIS_SERVING__MASTER_FILE"].startswith("/run/secrets/")
    assert env["LARIS_SERVING__DATABASE_URL_FILE"].startswith("/run/secrets/")
    assert SERVICES["postgres"]["environment"]["POSTGRES_PASSWORD_FILE"].startswith("/run/secrets/")
    text = (ROOT / "docker" / "compose.yaml").read_text(encoding="utf-8")
    assert "POSTGRES_PASSWORD" not in SERVICES["postgres"]["environment"]  # only the _FILE form
    assert not re.search(r"postgres(ql)?://\w+:[^@\s]+@", text)  # no DSN with a password
    assert "docker/secrets/" in (ROOT / ".gitignore").read_text(encoding="utf-8")


def test_the_model_reserves_a_gpu_and_the_services_have_health_checks_and_hardening():
    devices = SERVICES["model"]["deploy"]["resources"]["reservations"]["devices"]
    assert devices[0]["driver"] == "nvidia" and "gpu" in devices[0]["capabilities"]
    assert "healthcheck" in SERVICES["postgres"]
    for name in ("caddy", "api", "model"):
        service = SERVICES[name]
        assert service["read_only"] is True and service["cap_drop"] == ["ALL"], name
        assert "no-new-privileges:true" in service["security_opt"], name
    assert SERVICES["api"]["depends_on"]["postgres"]["condition"] == "service_healthy"


def test_caddy_terminates_tls_flushes_sse_and_limits_bodies_and_time():
    for needed in ("flush_interval -1", "max_size", "response_header_timeout", "read_timeout",
                   "reverse_proxy api:8000", "Strict-Transport-Security",
                   "request>headers>Authorization delete"):  # fmt: skip
        assert needed in CADDY, needed
    # the API trusts only Caddy's address for X-Forwarded-For
    trusted = SERVICES["api"]["environment"]["LARIS_SERVING__TRUSTED_PROXIES"]
    assert "172.31.0.0/24" in trusted
    assert COMPOSE["networks"]["backend"]["ipam"]["config"][0]["subnet"] == "172.31.0.0/24"
