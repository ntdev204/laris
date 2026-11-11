import os
import ssl
import stat

import pytest

from serverdata import tls


def test_create_self_signed_then_discover(tmp_path):
    folder = str(tmp_path / "tls")
    assert tls.discover(folder) == ("", "")
    cert, key = tls.create_self_signed(folder, ["localhost", "10.0.0.5"], days=30)
    assert stat.S_IMODE(os.stat(key).st_mode) == 0o600
    assert tls.discover(folder) == (str(cert), str(key))
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(cert, key)  # the pair is valid and matches
    with pytest.raises(FileExistsError):
        tls.create_self_signed(folder, ["localhost"])
    tls.create_self_signed(folder, ["localhost"], force=True)
