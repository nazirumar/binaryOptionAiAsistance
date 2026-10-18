"""MT5 connection lifecycle: initialize, health-check, retry/backoff, shutdown.

The manager is deliberately free of database access so it can be unit-tested
with a fake gateway. Callers (tasks, worker, views) are responsible for
persisting health events. Credentials are never logged.
"""

from __future__ import annotations

import logging
import os
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from apps.market_data.constants import ConnectionState
from apps.market_data.services.exceptions import (
    MT5ConnectionError,
    MT5UnavailableError,
)
from apps.market_data.services.mt5_client import MT5Gateway

logger = logging.getLogger(__name__)


def mask_account(login: int | str | None) -> str:
    """Mask an account login for display/logging (never reveal in full)."""
    if login is None or login == "":
        return ""
    text = str(login)
    if len(text) <= 3:
        return "*" * len(text)
    return "*" * (len(text) - 2) + text[-2:]


def resolve_secret(credential_ref: str) -> str:
    """Resolve a secret from the environment by reference name."""
    if not credential_ref:
        return ""
    return os.environ.get(credential_ref, "")


@dataclass(slots=True, frozen=True)
class ConnectionConfig:
    """Connection parameters. The password lives only in memory."""

    path: str = ""
    login: int = 0
    password: str = field(default="", repr=False)
    server: str = ""
    timeout_ms: int = 60000
    portable: bool = False

    @classmethod
    def from_settings(cls) -> ConnectionConfig:
        from django.conf import settings

        return cls(
            path=settings.MT5_TERMINAL_PATH,
            login=settings.MT5_LOGIN,
            password=settings.MT5_PASSWORD,
            server=settings.MT5_SERVER,
            timeout_ms=settings.MT5_TIMEOUT_MS,
            portable=settings.MT5_PORTABLE,
        )

    @classmethod
    def from_profile(cls, profile: Any) -> ConnectionConfig:
        """Build a config from an :class:`MT5ConnectionProfile`-like object."""
        from django.conf import settings

        password = resolve_secret(getattr(profile, "credential_ref", "") or "")
        if not password:
            password = settings.MT5_PASSWORD
        return cls(
            path=getattr(profile, "terminal_path", "") or settings.MT5_TERMINAL_PATH,
            login=getattr(profile, "login", 0) or settings.MT5_LOGIN,
            password=password,
            server=getattr(profile, "server", "") or settings.MT5_SERVER,
            timeout_ms=settings.MT5_TIMEOUT_MS,
            portable=settings.MT5_PORTABLE,
        )


@dataclass(slots=True, frozen=True)
class ConnectionHealth:
    state: str
    connected: bool
    terminal_name: str = ""
    server: str = ""
    masked_login: str = ""
    company: str = ""
    build: int | None = None
    error_code: int | None = None
    error_message: str = ""

    @property
    def is_healthy(self) -> bool:
        return self.connected and self.state == ConnectionState.CONNECTED


class MT5ConnectionManager:
    """Owns an :class:`MT5Gateway` connection with bounded retry/backoff."""

    def __init__(
        self,
        client: MT5Gateway,
        config: ConnectionConfig | None = None,
        *,
        max_retries: int | None = None,
        backoff_seconds: float | None = None,
        backoff_max_seconds: float | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        from django.conf import settings

        self.client = client
        self.config = config or ConnectionConfig.from_settings()
        self.max_retries = max_retries if max_retries is not None else settings.MT5_MAX_RETRIES
        self.backoff_seconds = (
            backoff_seconds if backoff_seconds is not None else settings.MT5_RETRY_BACKOFF_SECONDS
        )
        self.backoff_max_seconds = (
            backoff_max_seconds
            if backoff_max_seconds is not None
            else settings.MT5_RETRY_BACKOFF_MAX_SECONDS
        )
        self._sleep = sleep
        self._connected = False

    # -- lifecycle ----------------------------------------------------------
    @property
    def is_connected(self) -> bool:
        return self._connected

    def connect(self) -> bool:
        """Initialize the terminal with bounded retries and exponential backoff."""
        last_message = ""
        attempts = max(1, self.max_retries)
        for attempt in range(1, attempts + 1):
            try:
                ok = self.client.initialize(
                    path=self.config.path,
                    login=self.config.login,
                    password=self.config.password,
                    server=self.config.server,
                    timeout_ms=self.config.timeout_ms,
                    portable=self.config.portable,
                )
            except MT5UnavailableError:
                raise
            except Exception as exc:
                ok = False
                last_message = f"{type(exc).__name__}: {exc}"

            if ok and self.client.terminal_info() is not None:
                self._connected = True
                logger.info(
                    "mt5.connect.success",
                    extra={"attempt": attempt, "server": self.config.server},
                )
                return True

            code, message = self.client.last_error()
            last_message = message or last_message
            logger.warning(
                "mt5.connect.attempt_failed",
                extra={"attempt": attempt, "error_code": code, "error": last_message},
            )
            if attempt < attempts:
                delay = min(
                    self.backoff_seconds * (2 ** (attempt - 1)),
                    self.backoff_max_seconds,
                )
                self._sleep(delay)

        self._connected = False
        raise MT5ConnectionError(
            f"Could not connect to MetaTrader 5 after {attempts} attempt(s): {last_message}"
        )

    def ensure_connected(self) -> bool:
        if self._connected and self.client.terminal_info() is not None:
            return True
        return self.connect()

    def disconnect(self) -> None:
        try:
            self.client.shutdown()
        except Exception as exc:
            logger.warning("mt5.disconnect.error", extra={"error": type(exc).__name__})
        finally:
            self._connected = False
            logger.info("mt5.disconnect.complete")

    # -- health -------------------------------------------------------------
    def health_check(self) -> ConnectionHealth:
        if not self._connected:
            return ConnectionHealth(state=ConnectionState.DISCONNECTED, connected=False)

        terminal = self.client.terminal_info()
        if terminal is None:
            code, message = self.client.last_error()
            self._connected = False
            return ConnectionHealth(
                state=ConnectionState.ERROR,
                connected=False,
                error_code=code,
                error_message=message,
            )

        account = self.client.account_info()
        error_code, error_message = self.client.last_error()
        return ConnectionHealth(
            state=ConnectionState.CONNECTED if terminal.connected else ConnectionState.DISCONNECTED,
            connected=bool(terminal.connected),
            terminal_name=terminal.name,
            server=(account.server if account else "") or self.config.server,
            masked_login=mask_account(account.login if account else self.config.login),
            company=(account.company if account else "") or terminal.company,
            build=terminal.build,
            error_code=error_code,
            error_message=error_message,
        )

    # -- context manager ----------------------------------------------------
    def __enter__(self) -> MT5ConnectionManager:
        self.connect()
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.disconnect()

    def __repr__(self) -> str:  # pragma: no cover - debug helper
        return (
            f"<MT5ConnectionManager server={self.config.server!r} "
            f"login={mask_account(self.config.login)!r} connected={self._connected}>"
        )
