import os
# Legacy engine/UI tests intentionally exercise local/demo mode. Security tests
# explicitly enable the production authentication boundary per test.
os.environ.setdefault("DRIFTGUARD_REQUIRE_AUTH", "0")

# starlette's TestClient touches a deprecated anyio alias at import time (third-party,
# not ours). Import it once with only that message ignored so `pytest -W error` can
# collect; every other warning still raises.
import warnings
with warnings.catch_warnings():
    warnings.filterwarnings("ignore", message="The anyio.abc.BlockingPortal alias is deprecated",
                            category=DeprecationWarning)
    import starlette.testclient  # noqa: F401
