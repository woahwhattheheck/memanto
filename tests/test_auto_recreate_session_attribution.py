"""Regression coverage for activity attribution after session recreation."""

from datetime import timedelta
from unittest.mock import MagicMock, patch

from fastapi import Request, Response

from memanto.app.models.session import Session
from memanto.app.routes.auth_deps import _maybe_auto_recreate_session
from memanto.app.utils.client_identity import get_memanto_session, set_memanto_session
from memanto.app.utils.temporal_helpers import utc_now


def _request() -> Request:
    return Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/api/v2/agents/dev/remember",
            "headers": [(b"host", b"localhost:8000")],
            "scheme": "http",
            "server": ("localhost", 8000),
            "client": ("127.0.0.1", 50000),
        }
    )


def test_auto_recreated_session_is_bound_for_activity_logging() -> None:
    """The first operation after recreation belongs to the replacement session."""
    now = utc_now()
    recreated = Session(
        session_id="session-recreated",
        session_token="replacement-token",
        agent_id="dev",
        namespace="memanto_agent_dev",
        started_at=now,
        expires_at=now + timedelta(hours=8),
    )
    service = MagicMock()
    service.check_and_auto_recreate.return_value = recreated

    set_memanto_session(None)
    try:
        with (
            patch(
                "memanto.app.routes.auth_deps.require_management_access",
                return_value="management-key",
            ),
            patch(
                "memanto.app.routes.auth_deps.get_session_service",
                return_value=service,
            ),
        ):
            result = _maybe_auto_recreate_session(
                request=_request(),
                response=Response(),
                session_token="expired-token",
                x_session_token=None,
                session_cookie=None,
                authorization=None,
                x_api_key=None,
            )

        assert result is recreated
        assert get_memanto_session() == "session-recreated"
        service.check_and_auto_recreate.assert_called_once_with("expired-token")
    finally:
        set_memanto_session(None)
