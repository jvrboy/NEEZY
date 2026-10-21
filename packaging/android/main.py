"""Android entry point. Buildozer runs this file as the app's main module.

The staged build tree (see stage.py) has neezy_mobile/, neezy_backend/ and the
vendored pure-Python packages next to this file.
"""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

# Android's Python has no system CA bundle. websocket-client needs one for wss://
_CACERT = os.path.join(HERE, "certifi", "cacert.pem")
if os.path.exists(_CACERT):
    os.environ.setdefault("SSL_CERT_FILE", _CACERT)

from neezy_mobile.main import NeezyApp  # noqa: E402

NeezyApp().run()
