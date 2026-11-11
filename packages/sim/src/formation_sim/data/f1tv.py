"""F1TV sign-in for FastF1.

Since mid-October 2026 Formula 1's timing archive (``livetiming.formula1.com/static``)
answers every request with 401 unless it carries an F1TV Access (or higher) token.
FastF1 >= 3.9 signs in on demand: from ``F1_USERNAME`` / ``F1_PASSWORD`` when set, or
with a terminal prompt when interactive. The token is cached on disk and lasts about
four days.

The catch is that when FastF1 *can't* sign in it only logs a warning and carries on
unauthenticated, so the failure resurfaces much later as "No data for this session!"
or a ``DataNotLoadedError``, which reads like F1 hasn't published the race. This module
turns that into one explicit :class:`F1TVAuthError` with the fix spelled out. Callers
check it only after a load came back empty, so cached sessions never trigger a sign-in.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime, timezone

from fastf1.exceptions import F1AuthError
from fastf1.internals import f1account

ENV_USERNAME = "F1_USERNAME"
ENV_PASSWORD = "F1_PASSWORD"

HOW_TO_FIX = (
    "Fix: run `formation-data f1tv login` to sign in interactively, or set "
    f"{ENV_USERNAME} and {ENV_PASSWORD} in the environment so unattended jobs can sign "
    "in on their own. An F1TV Access (or higher) subscription is required."
)


class F1TVAuthError(RuntimeError):
    """FastF1 needed F1's timing archive and could not get a valid F1TV token."""

    def __init__(self, reason: str):
        self.reason = reason
        super().__init__(
            "F1TV sign-in required. Formula 1's timing archive only serves data to "
            f"signed-in F1TV accounts, and FastF1 could not sign in: {reason}\n{HOW_TO_FIX}"
        )


@dataclass(frozen=True)
class TokenStatus:
    expires_at: datetime
    valid: bool
    subscription_status: str | None
    product: str | None


def credentials_in_env() -> bool:
    return bool(os.environ.get(ENV_USERNAME) and os.environ.get(ENV_PASSWORD))


def token_status() -> TokenStatus | None:
    """The stored token's state without signing in, or None if there isn't one."""
    token = f1account.token_manager.get_stored()
    if token is None:
        return None
    try:
        claims = token.claims
    except Exception:  # noqa: BLE001 - an unreadable token is just "no details"
        claims = {}
    return TokenStatus(
        expires_at=datetime.fromtimestamp(token.expires_at, tz=timezone.utc),
        valid=token.is_valid(),
        subscription_status=claims.get("SubscriptionStatus"),
        product=claims.get("SubscribedProduct"),
    )


def sign_in(method: str | None = None) -> TokenStatus:
    """Force a fresh sign-in (prompting if interactive) and return the new token's state.

    Raises :class:`F1TVAuthError` if the sign-in fails.
    """
    global _known_failure
    try:
        f1account.get_token(force_renew=True, method=method)
    except F1AuthError as exc:
        raise F1TVAuthError(str(exc)) from exc
    _known_failure = None
    status = token_status()
    assert status is not None  # get_token just stored one
    return status


def sign_out() -> None:
    f1account.clear_token()


# Remembered for the rest of the process, so a run that hits many uncached sessions
# reports the same problem each time instead of re-prompting for credentials.
_known_failure: str | None = None


def auth_problem() -> str | None:
    """Why FastF1 can't authenticate, or None if a valid token is available.

    Signs in when the stored token is missing or expired, exactly as FastF1 itself
    would, so this may prompt in an interactive terminal.
    """
    global _known_failure
    if _known_failure is not None:
        return _known_failure
    try:
        f1account.get_token()
    except F1AuthError as exc:
        _known_failure = str(exc)
        return _known_failure
    return None


def raise_if_auth_problem() -> None:
    """Raise :class:`F1TVAuthError` if FastF1 has no way to authenticate.

    Call this after a session load came back without data: it tells "you're not signed
    in" apart from "F1 hasn't published this session yet".
    """
    reason = auth_problem()
    if reason is not None:
        raise F1TVAuthError(reason)
