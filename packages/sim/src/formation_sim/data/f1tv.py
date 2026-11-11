"""F1TV sign-in and access checks for FastF1.

Two separate gates sit in front of Formula 1's timing archive
(``livetiming.formula1.com/static``):

1. **IP block.** F1's CDN answers 403 to datacenter/cloud IP ranges (GitHub Actions,
   most VPS hosts) before it looks at any token. Signing in doesn't help, only a
   residential connection does.
2. **F1TV token.** Since mid-October 2026 everything else gets 401 without an F1TV
   Access (or higher) token. FastF1 >= 3.9 signs in on demand, from ``F1_USERNAME`` /
   ``F1_PASSWORD`` when set or with a terminal prompt when interactive, and caches the
   token on disk for about four days.

The catch is that FastF1 hides both failures. It logs a warning and carries on, so
the session comes back empty and the problem resurfaces as "No data for this
session!" or a ``DataNotLoadedError``, which reads like F1 hasn't published the race.
:func:`raise_if_access_problem` turns that into an explicit :class:`F1AccessError`
with the fix spelled out. Callers run it only after a load came back empty, so cached
sessions never trigger a sign-in or a network request.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime, timezone

import requests
from fastf1.exceptions import F1AuthError
from fastf1.internals import f1account

ENV_USERNAME = "F1_USERNAME"
ENV_PASSWORD = "F1_PASSWORD"

ARCHIVE_URL = "https://livetiming.formula1.com/static"

HOW_TO_SIGN_IN = (
    "Fix: run `formation-data f1tv login` to sign in interactively, or set "
    f"{ENV_USERNAME} and {ENV_PASSWORD} in the environment so unattended jobs can sign "
    "in on their own. An F1TV Access (or higher) subscription is required."
)


class F1AccessError(RuntimeError):
    """FastF1 can't reach F1's timing archive from here. A setup problem, not a
    missing race: every uncached session would fail the same way, so stop the run."""

    summary = "FastF1 can't access F1's timing archive"


class F1TVAuthError(F1AccessError):
    """No valid F1TV token: the sign-in failed, or F1 rejected the token."""

    summary = "FastF1 couldn't sign in to F1TV"

    def __init__(self, reason: str):
        self.reason = reason
        super().__init__(
            "F1TV sign-in required. Formula 1's timing archive only serves data to "
            f"signed-in F1TV accounts, and FastF1 could not sign in: {reason}\n"
            f"{HOW_TO_SIGN_IN}"
        )


class F1BlockedIPError(F1AccessError):
    """F1's CDN refused the request (403) even though FastF1 has a valid token."""

    summary = "F1 is blocking this machine's IP address"

    def __init__(self):
        super().__init__(
            "Formula 1's timing archive refused the request with 403 Forbidden even though "
            "FastF1 has a valid F1TV token. F1's CDN does this to datacenter and cloud IP "
            "ranges (GitHub Actions, most VPS hosts), and signing in can't get around it.\n"
            "Fix: run FastF1 jobs from a home or residential connection, such as the "
            "MacBook via scripts/run-data-job.sh. If this machine already is on one, "
            "check the account's F1TV subscription with `formation-data f1tv status`."
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
    try:
        f1account.get_token(force_renew=True, method=method)
    except F1AuthError as exc:
        raise F1TVAuthError(str(exc)) from exc
    _reset()
    status = token_status()
    assert status is not None  # get_token just stored one
    return status


def sign_out() -> None:
    f1account.clear_token()
    _reset()


# Remembered for the rest of the process. A run that hits many uncached sessions
# reports the same problem each time instead of re-prompting for credentials or
# re-probing the archive.
_known_failure: str | None = None
_checked_access: dict[int, F1AccessError | None] = {}


def _reset() -> None:
    global _known_failure
    _known_failure = None
    _checked_access.clear()


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


def probe_archive(season: int) -> int | None:
    """HTTP status of the season's archive index fetched with the stored token,
    or None if the request didn't complete. Bypasses FastF1, so its cache and rate
    limiter aren't involved."""
    token = f1account.token_manager.get_stored()
    headers = {"Authorization": token.authorization_header} if token else {}
    try:
        resp = requests.get(f"{ARCHIVE_URL}/{season}/Index.json", headers=headers, timeout=15)
    except requests.RequestException:
        return None
    resp.close()
    return resp.status_code


def access_problem(season: int) -> F1AccessError | None:
    """Why FastF1 can't fetch `season` from F1's archive, or None if it can.

    - no usable token -> :class:`F1TVAuthError` (from the sign-in's own error)
    - token sent, 403 -> :class:`F1BlockedIPError` (CDN IP block)
    - token sent, 401 -> :class:`F1TVAuthError` (F1 rejected the token)
    - anything else (200, 404, network error) -> None: the archive is reachable, so an
      empty session really is missing or unpublished.
    """
    reason = auth_problem()
    if reason is not None:
        return F1TVAuthError(reason)
    if season not in _checked_access:
        status = probe_archive(season)
        if status == 403:
            problem: F1AccessError | None = F1BlockedIPError()
        elif status == 401:
            problem = F1TVAuthError(
                "Formula 1 rejected the token (401). The account may not have an active "
                "F1TV Access (or higher) subscription."
            )
        else:
            problem = None
        _checked_access[season] = problem
    return _checked_access[season]


def raise_if_access_problem(season: int) -> None:
    """Raise :class:`F1AccessError` if FastF1 can't reach F1's archive for `season`.

    Call this after a session load came back without data. It tells "this machine
    can't get the data" apart from "F1 hasn't published this session yet".
    """
    problem = access_problem(season)
    if problem is not None:
        raise problem
