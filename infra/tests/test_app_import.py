"""The Modal app object builds with `modal` installed and no credentials.

Defining an App, an Image, a Volume, a Dict and a Secret is all local: the
handles hydrate lazily, on first use, so nothing here reaches the network.
That is worth a test, because the usual way to break it is to call something
at module scope that does need a token, and the failure then only shows up
on a machine that has one.
"""

from __future__ import annotations

import os
from pathlib import Path

import modal
import pytest


@pytest.fixture(scope="module")
def app_module(tmp_path_factory):
    """Import postgres_app with every route to a Modal credential removed."""
    missing = tmp_path_factory.mktemp("modal-home") / "absent.toml"
    saved = {
        key: os.environ.pop(key, None)
        for key in ("MODAL_TOKEN_ID", "MODAL_TOKEN_SECRET", "MODAL_PROFILE")
    }
    saved["MODAL_CONFIG_PATH"] = os.environ.get("MODAL_CONFIG_PATH")
    os.environ["MODAL_CONFIG_PATH"] = str(missing)
    try:
        import scrooge_infra.postgres_app as module

        yield module
    finally:
        for key, value in saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def test_app_exists_and_is_named(app_module):
    assert isinstance(app_module.app, modal.App)
    assert app_module.app.name == "scrooge-postgres"


@pytest.mark.parametrize("name", ["server", "supervisor", "archives"])
def test_the_three_functions_are_registered(app_module, name):
    assert isinstance(getattr(app_module, name), modal.Function)


def test_server_can_run_for_a_full_day(app_module):
    # Modal caps a Function timeout at 24 hours. Asking for more is rejected
    # at deploy time, which is a slow way to find out.
    assert app_module.MAX_TIMEOUT == 24 * 60 * 60


def test_server_is_not_preemptible(app_module):
    # A preemption costs a ten minute restore, during which every query
    # fails. Only `pg stop` and the 24 hour ceiling may end the server.
    assert app_module.NONPREEMPTIBLE is True


def test_pgdata_is_not_on_the_volume(app_module):
    # The whole persistence design rests on this. Modal Volumes are
    # documented as write-once read-many, so the heap stays on local disk
    # and only pg_dumpall output goes to the mount.
    assert not str(app_module.PGDATA).startswith(str(app_module.DUMP_DIR))
    assert app_module.PGDATA == Path("/pgdata")
    assert app_module.DUMP_DIR == Path("/dumps")


def test_handles_are_the_named_ones(app_module):
    assert app_module.volume.name == "scrooge-postgres-data"
    assert app_module.endpoint_dict.name == "scrooge-postgres-endpoint"


def test_pg_hba_and_listen_addresses_are_what_a_tunnel_needs(app_module):
    source = Path(app_module.__file__).read_text()
    assert "listen_addresses = '*'" in source
    assert "host    all       all   0.0.0.0/0    scram-sha-256" in source
