"""ntfy.sh push notifier.

Posts notifications to a ntfy topic so the user's phone (with the ntfy app
subscribed to that topic) receives a real push notification — works with
the browser closed, the Mac asleep, and the phone screen locked.

ntfy is open source and the public broker (https://ntfy.sh) is free for
personal use. The "secret" is the topic name — anyone who knows the topic
can subscribe and receive messages. Use a long random string treated as
a password. Self-host the server if you need stricter privacy.

Docs: https://docs.ntfy.sh/publish/
"""

from __future__ import annotations

import logging
from typing import Iterable

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

logger = logging.getLogger(__name__)

DEFAULT_SERVER = "https://ntfy.sh"


class NtfyNotifier:
    """Async client. `topic` empty/None = disabled (push() is a no-op)."""

    def __init__(
        self,
        topic: str | None,
        *,
        server: str = DEFAULT_SERVER,
        click_url: str | None = None,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._topic = (topic or "").strip()
        self._server = server.rstrip("/")
        self._click_url = click_url
        self._client = client or httpx.AsyncClient(timeout=10.0)

    @property
    def enabled(self) -> bool:
        return bool(self._topic)

    async def close(self) -> None:
        await self._client.aclose()

    async def push(
        self,
        *,
        title: str,
        message: str,
        priority: int = 3,
        tags: Iterable[str] = (),
        click_url: str | None = None,
    ) -> bool:
        """Send a notification. Returns True on success, False otherwise.

        Never raises — failures are logged and swallowed because we never
        want a 3rd-party push outage to break the tick loop.
        """
        if not self.enabled:
            return False
        try:
            return await self._send(
                title=title,
                message=message,
                priority=priority,
                tags=tags,
                click_url=click_url,
            )
        except Exception:
            logger.exception("ntfy.sh push failed for topic %s", self._topic)
            return False

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(min=1, max=8),
        reraise=True,
    )
    async def _send(
        self,
        *,
        title: str,
        message: str,
        priority: int,
        tags: Iterable[str],
        click_url: str | None,
    ) -> bool:
        # ntfy reads the body as the notification message and sticks metadata
        # into request headers. Header values must be ASCII; we URL-encode
        # non-ASCII titles to keep emoji safe (ntfy decodes them client-side).
        headers: dict[str, str] = {
            "Title": _ascii_safe(title),
            "Priority": str(max(1, min(5, priority))),
        }
        tag_csv = ",".join(t.strip() for t in tags if t and t.strip())
        if tag_csv:
            headers["Tags"] = tag_csv
        target = click_url or self._click_url
        if target:
            headers["Click"] = target

        url = f"{self._server}/{self._topic}"
        response = await self._client.post(url, content=message.encode("utf-8"), headers=headers)
        if response.status_code >= 400:
            logger.warning(
                "ntfy.sh returned HTTP %s for topic %s: %s",
                response.status_code,
                self._topic,
                response.text[:200],
            )
            return False
        return True


def _ascii_safe(text: str) -> str:
    """ntfy expects headers in latin-1/ASCII. Replace non-ASCII with `?` since
    the body (which CAN be UTF-8) already carries the rich content."""
    return text.encode("ascii", errors="replace").decode("ascii")
