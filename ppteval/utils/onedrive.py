"""OneDrive client utility for ppteval."""

import logging
import os
import random
import threading
import time
from pathlib import Path

import requests
from msal import PublicClientApplication, SerializableTokenCache

try:
    # msal_extensions provides a portalocker-backed PersistedTokenCache that
    # is safe for multiple processes hitting the same cache file. Without it,
    # concurrent OneDrive clients race on MSAL's refresh-token rotation and
    # corrupt each other's state, eventually triggering a device-flow prompt
    # mid-run.
    from msal_extensions import FilePersistence, PersistedTokenCache
    _HAS_MSAL_EXTENSIONS = True
except ImportError:  # pragma: no cover - msal_extensions is in pyproject deps
    _HAS_MSAL_EXTENSIONS = False

logger = logging.getLogger(__name__)

GRAPH_API_ENDPOINT = "https://graph.microsoft.com/v1.0"

# Refresh the access token when it has this many seconds (or fewer) of life left.
_TOKEN_REFRESH_LEEWAY_SECONDS = 300

_DEFAULT_CACHE_PATH = str(Path.home() / ".ppteval" / "token_cache.bin")

# Opt-in flag for device-flow during mid-session token refresh. The default is
# NOT to surprise long-running unattended batches with a device-code prompt.
# Initial construction (when the cache is empty) still falls through to device
# flow unless the env var is explicitly set to "0".
_ALLOW_DEVICE_FLOW_ENV = "PPTEVAL_ALLOW_DEVICE_FLOW"


class OneDriveAuthRequired(RuntimeError):
    """Raised when interactive re-authentication is required mid-session.

    Catch this in driver scripts to fail fast instead of blocking on a device-
    code prompt nobody will answer. Recover with::

        python -m ppteval.utils.onedrive --login
    """


def _allow_device_flow(default: bool) -> bool:
    raw = os.getenv(_ALLOW_DEVICE_FLOW_ENV)
    if raw is None:
        return default
    return raw.strip().lower() not in ("0", "false", "no", "off", "")


class OneDriveClient:
    def __init__(
        self,
        client_id,
        tenant="consumers",
        cache_path=None,
        root_path="/Documents/PPTEval",
    ):
        self.client_id = client_id
        self.authority = f"https://login.microsoftonline.com/{tenant}"
        self.scope = ["Files.ReadWrite.All", "User.Read"]
        # Default to an absolute path so the cache survives cwd changes between processes.
        self.cache_path = cache_path or _DEFAULT_CACHE_PATH
        os.makedirs(os.path.dirname(self.cache_path) or ".", exist_ok=True)
        self.root_path = root_path.strip("/")
        # Serialize token refresh within this process. The persistence layer
        # below handles cross-process locking; this lock prevents threads in
        # the same process from concurrently calling acquire_token_silent and
        # racing on self.access_token / self._token_expires_at.
        self._token_lock = threading.RLock()
        self.token_cache = self._load_cache()
        self.app = PublicClientApplication(
            client_id=self.client_id,
            authority=self.authority,
            token_cache=self.token_cache,
        )
        self.access_token: str | None = None
        self._token_expires_at: float = 0.0
        self._account = None
        # Initial acquire is allowed to do a device flow if there's no cache,
        # since the harness can't start without a token at all.
        self._get_token(initial=True)
        self.session = requests.Session()
        self.session.headers.update(self._headers())
        # Install a refresh-aware request hook so every Graph call gets a fresh
        # token and is retried once on 401 / with backoff on 429/5xx.
        self._install_auto_refresh()

    def _load_cache(self):
        # Prefer msal_extensions.PersistedTokenCache which holds a cross-
        # process file lock around every modify(). Fall back to the bare
        # SerializableTokenCache only if msal_extensions isn't installed —
        # that path is NOT safe under multi-process concurrency.
        if _HAS_MSAL_EXTENSIONS:
            persistence = FilePersistence(self.cache_path)
            return PersistedTokenCache(persistence)
        logger.warning(
            "msal_extensions not installed; falling back to SerializableTokenCache. "
            "This is NOT safe for multi-process OneDrive clients."
        )
        cache = SerializableTokenCache()
        if os.path.exists(self.cache_path):
            with open(self.cache_path, "r") as f:
                cache.deserialize(f.read())
        return cache

    def _save_cache(self):
        # PersistedTokenCache flushes via .modify() under its own file lock,
        # so there's nothing for us to do. Only the fallback path needs an
        # explicit write.
        if _HAS_MSAL_EXTENSIONS:
            return
        if self.token_cache.has_state_changed:
            with open(self.cache_path, "w") as f:
                f.write(self.token_cache.serialize())

    def _apply_token_result(self, result):
        """Store access_token and compute expiry from an MSAL result dict."""
        if not result or "access_token" not in result:
            err = (result or {}).get("error_description") or (result or {}).get("error") or "no result"
            raise Exception(f"Failed to acquire token: {err}")
        self.access_token = result["access_token"]
        # MSAL returns expires_in (seconds). Default to 3600 if absent.
        expires_in = int(result.get("expires_in", 3600))
        self._token_expires_at = time.time() + expires_in
        self._save_cache()

    def _get_token(self, initial=False):
        with self._token_lock:
            accounts = self.app.get_accounts()
            if accounts:
                self._account = accounts[0]
                result = self.app.acquire_token_silent(self.scope, account=self._account)
                if result:
                    self._apply_token_result(result)
                    return self.access_token
                # Cached account but silent refresh failed (e.g. refresh token
                # rotated by another process, or revoked). Don't fall through
                # to device flow during a normal refresh — that would block
                # an unattended batch waiting for a human.
            allow_df = _allow_device_flow(default=initial)
            if not allow_df:
                raise OneDriveAuthRequired(
                    "OneDrive interactive re-authentication required. Run "
                    "'python -m ppteval.utils.onedrive --login' to refresh "
                    f"the cache at {self.cache_path}. (Set "
                    f"{_ALLOW_DEVICE_FLOW_ENV}=1 to opt back into "
                    "device-flow fallback.)"
                )
            flow = self.app.initiate_device_flow(scopes=self.scope)
            print(f"Go to: {flow['verification_uri']} and enter code: {flow['user_code']}")
            result = self.app.acquire_token_by_device_flow(flow)
            self._apply_token_result(result)
            self._account = (self.app.get_accounts() or [None])[0]
            return self.access_token

    def _ensure_fresh_token(self):
        """Refresh the access token if it is expired or close to expiry."""
        # Fast path: token has plenty of life left and no lock needed.
        if time.time() + _TOKEN_REFRESH_LEEWAY_SECONDS < self._token_expires_at:
            return
        with self._token_lock:
            # Re-check under lock: another thread may have just refreshed.
            if time.time() + _TOKEN_REFRESH_LEEWAY_SECONDS < self._token_expires_at:
                return
            if not self._account:
                self._account = (self.app.get_accounts() or [None])[0]
            if self._account is None:
                # No cached account; cannot silently refresh. _get_token will
                # raise OneDriveAuthRequired unless device flow is opted-in.
                self._get_token(initial=False)
            else:
                result = self.app.acquire_token_silent(self.scope, account=self._account)
                if not result:
                    # Silent refresh failed (refresh token rotated/revoked).
                    # Hand off to _get_token, which respects the device-flow
                    # opt-in. If not opted in, raises OneDriveAuthRequired.
                    self._get_token(initial=False)
                else:
                    self._apply_token_result(result)
            # Update the session header to carry the new token.
            if hasattr(self, "session"):
                self.session.headers.update(self._headers())

    def _install_auto_refresh(self):
        """Wrap session.request with token refresh + 401/429/5xx retries."""
        original_request = self.session.request
        max_throttle_retries = 4

        def request_with_refresh(method, url, **kwargs):
            self._ensure_fresh_token()
            for attempt in range(max_throttle_retries + 1):
                response = original_request(method, url, **kwargs)
                status = response.status_code
                if status == 401:
                    # Token may have just expired or been revoked; force
                    # refresh and retry once. If refresh raises
                    # OneDriveAuthRequired, propagate.
                    self._token_expires_at = 0.0
                    self._ensure_fresh_token()
                    response = original_request(method, url, **kwargs)
                    return response
                if status == 429 or 500 <= status < 600:
                    if attempt >= max_throttle_retries:
                        return response
                    # Honor Retry-After when present; else exponential
                    # backoff with jitter (1, 2, 4, 8s).
                    retry_after_hdr = response.headers.get("Retry-After")
                    if retry_after_hdr:
                        try:
                            delay = float(retry_after_hdr)
                        except ValueError:
                            delay = 2 ** attempt
                    else:
                        delay = 2 ** attempt
                    delay += random.uniform(0.0, 0.5)
                    logger.warning(
                        "Graph %s %s -> %d, retrying in %.1fs (attempt %d/%d)",
                        method, url, status, delay, attempt + 1, max_throttle_retries,
                    )
                    time.sleep(delay)
                    self._ensure_fresh_token()
                    continue
                return response
            return response

        self.session.request = request_with_refresh  # type: ignore[assignment]

    def _headers(self):
        return {"Authorization": f"Bearer {self.access_token}"}

    def _resolve_path(self, path):
        path = path.strip("/")
        if path:
            return f"{GRAPH_API_ENDPOINT}/me/drive/root:/{self.root_path}/{path}"
        else:
            return f"{GRAPH_API_ENDPOINT}/me/drive/root:/{self.root_path}"

    def list_directory(self, path=""):
        url = f"{self._resolve_path(path)}:/children"
        resp = self.session.get(url)
        resp.raise_for_status()
        return resp.json().get("value", [])

    def upload_file(self, local_path, remote_path, set_public=True):
        """
        Upload a file to OneDrive and optionally set it to public access.

        Args:
            local_path (str): Local file path
            remote_path (str): Remote file path relative to root_path
            set_public (bool): Whether to set the file to public access (default: True)

        Returns:
            dict: Upload response with optional sharing link info
        """
        with open(local_path, "rb") as f:
            url = f"{self._resolve_path(remote_path)}:/content"
            resp = self.session.put(url, data=f)
            resp.raise_for_status()
            upload_result = resp.json()

        # Set public access if requested
        if set_public:
            try:
                sharing_link = self._set_public_access(remote_path)
                upload_result["sharing_link"] = sharing_link
                print(f"File '{remote_path}' uploaded and set to public access")
            except Exception as e:
                print(f"Warning: Could not set public access for '{remote_path}': {e}")

        return upload_result

    def get_edit_link(self, file_path):
        """
        Get the edit link for a file given its path relative to the root.

        Args:
            file_path (str): Path to the file relative to self.root_path

        Returns:
            str: The edit link URL for the file

        Raises:
            Exception: If the file is not found or doesn't support editing
        """
        url = f"{self._resolve_path(file_path)}"
        resp = self.session.get(url)
        resp.raise_for_status()

        file_info = resp.json()
        file_id = file_info["id"]

        # First, try to get an existing edit link
        permissions_url = f"{GRAPH_API_ENDPOINT}/me/drive/items/{file_id}/permissions"
        response = self.session.get(permissions_url)
        if response.status_code == 200:
            permissions = response.json().get("value", [])
            for perm in permissions:
                if perm.get("link", {}).get("type") == "edit" and "/f/" not in perm["link"]["webUrl"]:
                    print(f"Edit link for file '{file_path}' already exists; returning it.")
                    return perm["link"]["webUrl"]

        print(f"Edit link for file '{file_path}' DOESN'T currently exist; creating it.")
        create_link_url = f"{GRAPH_API_ENDPOINT}/me/drive/items/{file_id}/createLink"
        data = {"type": "edit", "scope": "anonymous"}
        response = self.session.post(create_link_url, json=data)
        response.raise_for_status()

        return response.json()["link"]["webUrl"]

    def _set_public_access(self, file_path):
        """
        Set a file to have public edit access by creating a sharing link.

        Args:
            file_path (str): Path to the file relative to self.root_path

        Returns:
            str: The edit link URL
        """
        url = f"{self._resolve_path(file_path)}"
        resp = self.session.get(url)
        resp.raise_for_status()

        file_info = resp.json()
        file_id = file_info["id"]

        # First, try to get an existing edit link
        permissions_url = f"{GRAPH_API_ENDPOINT}/me/drive/items/{file_id}/permissions"
        response = self.session.get(permissions_url)
        if response.status_code == 200:
            permissions = response.json().get("value", [])
            for perm in permissions:
                if perm.get("link", {}).get("type") == "edit" and "/f/" not in perm["link"]["webUrl"]:
                    return perm["link"]["webUrl"]

        # Create new edit link
        create_link_url = f"{GRAPH_API_ENDPOINT}/me/drive/items/{file_id}/createLink"
        payload = {
            "type": "edit",
            "scope": "anonymous",
        }
        resp = self.session.post(create_link_url, json=payload)
        resp.raise_for_status()
        return resp.json()["link"]["webUrl"]

    def download_file(self, remote_path, local_dir):
        """
        Downloads a single file from OneDrive.

        Args:
            remote_path (str): Remote file path relative to root_path.
            local_dir (str): The local directory to save the file in.

        Returns:
            str: The local path of the downloaded file.
        """
        url = self._resolve_path(remote_path)
        resp = self.session.get(url)
        resp.raise_for_status()
        file_info = resp.json()

        download_url = file_info.get("@microsoft.graph.downloadUrl")
        if not download_url:
            raise ValueError(f"Could not find download URL for '{remote_path}'")

        file_resp = requests.get(download_url)
        file_resp.raise_for_status()

        os.makedirs(local_dir, exist_ok=True)
        local_file_path = os.path.join(local_dir, file_info["name"])

        with open(local_file_path, "wb") as f:
            f.write(file_resp.content)

        print(f"Downloaded '{remote_path}' to '{local_file_path}'")
        return local_file_path


# ---------------------------------------------------------------------------
# Interactive auth entrypoint:  python -m ppteval.utils.onedrive --login
# ---------------------------------------------------------------------------
def _interactive_login(client_id: str | None = None, cache_path: str | None = None) -> int:
    """Force a device-flow login and warm the on-disk cache.

    Used by the harness operator to refresh credentials before launching a
    long unattended batch. Honors CLIENT_ID and an optional override via
    --cache-path.
    """
    if client_id is None:
        client_id = os.getenv("CLIENT_ID")
    if not client_id:
        print("ERROR: CLIENT_ID env var missing.", flush=True)
        return 2
    # Opt into device flow for this one invocation only.
    os.environ[_ALLOW_DEVICE_FLOW_ENV] = "1"
    print(f"Cache: {cache_path or _DEFAULT_CACHE_PATH}", flush=True)
    client = OneDriveClient(client_id=client_id, cache_path=cache_path)
    # Touch /me to confirm the token actually works.
    resp = client.session.get(f"{GRAPH_API_ENDPOINT}/me")
    if resp.status_code != 200:
        print(f"ERROR: /me returned {resp.status_code}: {resp.text[:200]}", flush=True)
        return 1
    me = resp.json()
    print(f"OK: signed in as {me.get('userPrincipalName') or me.get('mail') or me.get('displayName')}", flush=True)
    return 0


if __name__ == "__main__":
    import argparse
    import sys

    from dotenv import load_dotenv

    load_dotenv(override=False)

    parser = argparse.ArgumentParser(description="OneDrive token cache utility.")
    sub = parser.add_subparsers(dest="cmd")
    p_login = sub.add_parser("login", help="Interactive device-flow login; warms the token cache.")
    p_login.add_argument("--client-id", default=None, help="Override CLIENT_ID env var.")
    p_login.add_argument("--cache-path", default=None, help="Override default cache path.")
    # Accept --login as a shortcut to the 'login' subcommand for symmetry with
    # other ppteval entrypoints (e.g. `python -m ppteval.utils.onedrive --login`).
    parser.add_argument("--login", action="store_true", help="Shortcut for the 'login' subcommand.")
    parser.add_argument("--client-id", default=None)
    parser.add_argument("--cache-path", default=None)

    args = parser.parse_args()
    if args.cmd == "login" or args.login:
        sys.exit(_interactive_login(client_id=args.client_id, cache_path=args.cache_path))
    parser.print_help()
    sys.exit(0)
