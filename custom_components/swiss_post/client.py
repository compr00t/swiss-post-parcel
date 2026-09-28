"""Swiss Post API Client supporting both refresh_token and session cookies."""

import http.cookiejar
import json
import logging
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Callable, Dict, List, Optional, Tuple, Union

from .models import Shipment

_LOGGER = logging.getLogger(__name__)


class SwissPostAuthError(Exception):
    """Raised when authentication fails or token cannot be refreshed."""
    pass


class SwissPostAPIError(Exception):
    """Raised when an API endpoint returns an error."""
    pass


class SwissPostClient:
    """Client for Swiss Post with OAuth token refresh and session handling."""

    BASE_URL = "https://service.post.ch"
    DEFAULT_USER_AGENT = (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36"
    )

    def __init__(
        self,
        account_name: str = "Personal",
        refresh_token: Optional[str] = None,
        session_cookies: Optional[str] = None,
        client_id: str = "ch.post.it.app",
        client_secret: Optional[str] = None,
        token_endpoint: str = "https://api.post.ch/OAuth/token",
        on_token_refreshed: Optional[Callable[[Dict[str, Any]], None]] = None,
        timeout: int = 20,
    ):
        self.account_name = account_name
        self.refresh_token = refresh_token
        self.client_id = client_id
        self.client_secret = client_secret
        self.token_endpoint = token_endpoint
        self.on_token_refreshed = on_token_refreshed
        self.timeout = timeout
        self.access_token: Optional[str] = None
        self.token_expiry: float = 0

        self.cookie_jar = http.cookiejar.CookieJar()
        self.cookie_header_str = ""
        self.opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(self.cookie_jar)
        )

        if session_cookies:
            self.set_cookies_from_header(session_cookies)

    def set_cookies_from_header(self, header_str: str) -> None:
        """Store cookie header and populate CookieJar."""
        if not header_str:
            return
        if header_str.lower().startswith("cookie:"):
            header_str = header_str[7:].strip()
        self.cookie_header_str = header_str

        for part in header_str.split(";"):
            part = part.strip()
            if "=" in part:
                name, val = part.split("=", 1)
                cookie = http.cookiejar.Cookie(
                    version=0,
                    name=name.strip(),
                    value=val.strip(),
                    port=None,
                    port_specified=False,
                    domain=".post.ch",
                    domain_specified=True,
                    domain_initial_dot=True,
                    path="/",
                    path_specified=True,
                    secure=True,
                    expires=None,
                    discard=True,
                    comment=None,
                    comment_url=None,
                    rest={},
                )
                self.cookie_jar.set_cookie(cookie)

    def refresh_access_token(self) -> bool:
        """Refresh access token using the stored refresh_token."""
        if not self.refresh_token:
            return False

        _LOGGER.debug("[%s] Refreshing access token via %s", self.account_name, self.token_endpoint)
        payload = {
            "grant_type": "refresh_token",
            "client_id": self.client_id,
            "refresh_token": self.refresh_token,
        }
        if self.client_secret:
            payload["client_secret"] = self.client_secret

        body_data = urllib.parse.urlencode(payload).encode("utf-8")
        req = urllib.request.Request(
            self.token_endpoint,
            data=body_data,
            headers={
                "User-Agent": self.DEFAULT_USER_AGENT,
                "Content-Type": "application/x-www-form-urlencoded",
                "Accept": "application/json",
            },
            method="POST",
        )

        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                resp_data = json.loads(resp.read().decode("utf-8"))
                new_access_token = resp_data.get("access_token")
                new_refresh_token = resp_data.get("refresh_token") or self.refresh_token
                expires_in = resp_data.get("expires_in", 3600)

                if new_access_token:
                    self.access_token = new_access_token
                    self.refresh_token = new_refresh_token
                    self.token_expiry = time.time() + float(expires_in) - 60  # 1 min margin

                    _LOGGER.info("[%s] Successfully refreshed access token (expires in %ss)", self.account_name, expires_in)

                    # If token rotated or updated, notify Home Assistant to save it
                    if self.on_token_refreshed:
                        self.on_token_refreshed({
                            "refresh_token": self.refresh_token,
                            "access_token": self.access_token,
                            "expires_at": self.token_expiry,
                        })
                    return True
        except urllib.error.HTTPError as e:
            err_text = e.read().decode("utf-8", errors="replace") if e.fp else ""
            _LOGGER.error("[%s] Token refresh failed HTTP %s: %s", self.account_name, e.code, err_text)
            raise SwissPostAuthError(f"Token refresh failed: HTTP {e.code} - {err_text}") from e
        except Exception as e:
            _LOGGER.error("[%s] Error during token refresh: %s", self.account_name, e)
            raise SwissPostAuthError(f"Error refreshing token: {e}") from e

        return False

    def _ensure_authenticated(self) -> None:
        """Ensure token is valid if using refresh_token."""
        if self.refresh_token and (not self.access_token or time.time() >= self.token_expiry):
            self.refresh_access_token()

    def _request(
        self,
        endpoint: str,
        method: str = "GET",
        data: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
        retry_auth: bool = True,
    ) -> Any:
        """Execute request with automatic retry on token expiration."""
        self._ensure_authenticated()

        url = urllib.parse.urljoin(self.BASE_URL, endpoint)
        req_headers = {
            "User-Agent": self.DEFAULT_USER_AGENT,
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "de-CH,de;q=0.9,en;q=0.8",
            "Referer": f"{self.BASE_URL}/ekp-web/",
            "Origin": self.BASE_URL,
        }

        if self.access_token:
            req_headers["Authorization"] = f"Bearer {self.access_token}"

        if self.cookie_header_str:
            req_headers["Cookie"] = self.cookie_header_str

        if headers:
            req_headers.update(headers)

        body = None
        if data is not None:
            body = json.dumps(data).encode("utf-8")
            req_headers["Content-Type"] = "application/json;charset=UTF-8"

        req = urllib.request.Request(url, data=body, headers=req_headers, method=method)

        try:
            with self.opener.open(req, timeout=self.timeout) as response:
                content_type = response.headers.get("Content-Type", "")
                raw_bytes = response.read()
                raw_text = raw_bytes.decode("utf-8", errors="replace")

                # Check if redirected to login page
                if "meta http-equiv=\"refresh\"" in raw_text or "account.post.ch/idp" in raw_text:
                    if retry_auth and self.refresh_token:
                        _LOGGER.debug("[%s] Session expired, attempting token refresh...", self.account_name)
                        self.refresh_access_token()
                        return self._request(endpoint, method, data, headers, retry_auth=False)
                    raise SwissPostAuthError(f"[{self.account_name}] Session expired or invalid.")

                if "application/json" in content_type or raw_text.startswith(("{", "[", '"')):
                    try:
                        return json.loads(raw_text)
                    except json.JSONDecodeError:
                        return raw_text
                return raw_text

        except urllib.error.HTTPError as e:
            if e.code in (401, 403):
                if retry_auth and self.refresh_token:
                    _LOGGER.debug("[%s] HTTP %s, retrying after token refresh...", self.account_name, e.code)
                    self.refresh_access_token()
                    return self._request(endpoint, method, data, headers, retry_auth=False)
                raise SwissPostAuthError(f"[{self.account_name}] Authentication failed (HTTP {e.code}).") from e
            err_body = e.read().decode("utf-8", errors="replace") if e.fp else ""
            raise SwissPostAPIError(f"HTTP {e.code} error: {err_body}") from e
        except urllib.error.URLError as e:
            raise SwissPostAPIError(f"Network error connecting to {url}: {e.reason}") from e

    def get_user_info(self) -> Dict[str, Any]:
        """Fetch user profile and verify authentication."""
        data = self._request("/ekp-web/api/user")
        if not isinstance(data, dict):
            raise SwissPostAPIError(f"Invalid user response: {data}")
        if data.get("anonymous") is True:
            # If we have a refresh token, try refreshing once
            if self.refresh_token:
                self.refresh_access_token()
                data = self._request("/ekp-web/api/user")
            if data.get("anonymous") is True:
                raise SwissPostAuthError(f"[{self.account_name}] Unauthenticated session.")
        return data

    def get_all_shipments(self, max_wait_seconds: int = 30) -> List[Shipment]:
        """Query and poll all consignments for this account."""
        user_info = self.get_user_info()
        user_id = user_info.get("userIdentifier")
        if not user_id:
            raise SwissPostAuthError(f"[{self.account_name}] userIdentifier missing.")

        init_res = self._request(f"/ekp-web/secure/api/shipment/mine/user/{user_id}")
        if not init_res:
            return []

        result_id = init_res.get("id") or init_res.get("resultId") if isinstance(init_res, dict) else init_res
        result_id = str(result_id).strip("\"'")

        start_time = time.time()
        poll_interval = 1.0
        retries = 0

        while time.time() - start_time < max_wait_seconds:
            result_data = self._request(f"/ekp-web/secure/api/shipment/mine/result/{result_id}")
            if isinstance(result_data, dict):
                status = result_data.get("status")
                if status == "DONE":
                    raw_items = result_data.get("shipments") or []
                    return [Shipment.from_api_dict(s, account_name=self.account_name) for s in raw_items]
                if status in ("FAILED", "ERROR"):
                    raise SwissPostAPIError(f"Shipment query failed: {result_data}")
            retries += 1
            if retries > 3:
                poll_interval = 2.0
            time.sleep(poll_interval)

        raise SwissPostAPIError(f"[{self.account_name}] Query timed out after {max_wait_seconds}s.")

    def get_parcels(self) -> Tuple[List[Shipment], List[Shipment]]:
        """Return (upcoming_parcels, past_parcels) filtered for parcels."""
        all_shipments = self.get_all_shipments()
        parcels = [s for s in all_shipments if s.is_parcel]

        upcoming = [s for s in parcels if not s.is_delivered]
        past = [s for s in parcels if s.is_delivered]

        upcoming.sort(
            key=lambda s: s.calculated_delivery_date or s.last_event_date or s.sending_date or 0
        )
        past.sort(
            key=lambda s: s.delivery_date or s.last_event_date or 0,
            reverse=True
        )
        return upcoming, past
