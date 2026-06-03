import re
import time
import random
from typing import Optional

from curl_cffi import requests as curl_requests

try:
    import cloudscraper
except Exception:
    cloudscraper = None


class CloudflareChallengeError(Exception):
    def __init__(self, message, retry_after_seconds=None):
        super().__init__(message)
        self.retry_after_seconds = retry_after_seconds


class Session:
    LOGIN_URL = "https://letterboxd.com/user/login.do"
    MAIN_PAGE_URL = "https://letterboxd.com/"
    SIGN_IN_PAGE_URL = "https://letterboxd.com/sign-in/"
    EXPORT_URL = "https://letterboxd.com/data/export/"

    LOGIN_TIMEOUT_SECONDS = 30
    DOWNLOAD_TIMEOUT_SECONDS = 60
    RESPONSE_SNIPPET_LENGTH = 800

    LOGIN_IMPERSONATES = ("chrome", "chrome120", "edge101")
    DOWNLOAD_IMPERSONATES = LOGIN_IMPERSONATES

    MAX_LOGIN_ATTEMPTS = 4
    MAX_DOWNLOAD_ATTEMPTS = 4
    BASE_RETRY_SECONDS = 2
    MAX_RETRY_SECONDS = 20

    _CHALLENGE_MARKERS = (
        "Just a moment",
        "<title>Just a moment",
    )

    _RETRYABLE_LOGIN_ERROR_MARKERS = (
        "The form on this page had expired and could not be accepted",
        "form on this page had expired",
        "form had expired",
        "csrf token not found",
        "unexpected non-json response on login",
    )

    def __init__(self, username: str, password: str, use_2fa_code):
        if not username or not password:
            raise Exception("Username or password not set.")

        self._csrf = None
        self._is_logged_in = False
        self._scraper = None

        self.sign_in(username, password, use_2fa_code)

    @staticmethod
    def _response_snippet(response, max_length=RESPONSE_SNIPPET_LENGTH):
        try:
            return response.text[:max_length] if response.text else ""
        except Exception:
            return ""

    def _is_cloudflare_challenge(self, response, body_snippet: Optional[str] = None):
        snippet = body_snippet if body_snippet is not None else self._response_snippet(response)
        if response.status_code in (403, 429):
            return True
        return any(marker in snippet for marker in self._CHALLENGE_MARKERS)

    def _raise_if_cloudflare_challenge(self, response):
        body_snippet = self._response_snippet(response)
        if self._is_cloudflare_challenge(response, body_snippet):
            retry_after = response.headers.get("Retry-After") if hasattr(response, "headers") else None
            retry_after_seconds = None
            if retry_after:
                try:
                    retry_after_seconds = int(str(retry_after).strip())
                except Exception:
                    retry_after_seconds = None

            cf_ray = response.headers.get("cf-ray") if hasattr(response, "headers") else None
            status = getattr(response, "status_code", "?")
            detail = f"Cloudflare challenge detected ({status})"
            if cf_ray:
                detail += f", cf-ray={cf_ray}"
            detail += f". Response snippet: {body_snippet}"
            raise CloudflareChallengeError(detail, retry_after_seconds=retry_after_seconds)

    @classmethod
    def _retry_delay_seconds(cls, attempt, retry_after_seconds=None):
        if retry_after_seconds is not None and retry_after_seconds > 0:
            return min(retry_after_seconds, cls.MAX_RETRY_SECONDS)

        base = min(cls.BASE_RETRY_SECONDS * (2 ** (attempt - 1)), cls.MAX_RETRY_SECONDS)
        jitter = random.uniform(0, 0.5)
        return base + jitter

    def _create_session(self):
        session = curl_requests.Session()
        session.headers.update({
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9,de;q=0.8",
            "Referer": self.MAIN_PAGE_URL,
        })
        return session

    def _create_cloudscraper_session(self):
        if cloudscraper is None:
            raise Exception("Automatic Cloudflare solving requires the optional 'cloudscraper' dependency.")

        session = cloudscraper.create_scraper(browser={
            "browser": "chrome",
            "platform": "windows",
            "mobile": False,
        })
        session.headers.update({
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9,de;q=0.8",
            "Referer": self.MAIN_PAGE_URL,
        })
        return session

    @staticmethod
    def _request(session, method_name, url, impersonate=None, **kwargs):
        method = getattr(session, method_name)
        if impersonate is not None:
            try:
                return method(url, impersonate=impersonate, **kwargs)
            except TypeError as exc:
                if "impersonate" not in str(exc):
                    raise
        return method(url, **kwargs)

    def _copy_cookies(self, source_session, target_session):
        try:
            for cookie in source_session.cookies:
                target_session.cookies.set(cookie.name, cookie.value, domain=cookie.domain, path=cookie.path)
        except Exception:
            pass

    def _switch_to_cloudscraper(self):
        if self._scraper is not None and getattr(self._scraper, "__class__", None) is not None:
            module_name = self._scraper.__class__.__module__
            if module_name.startswith("cloudscraper"):
                return self._scraper

        browser_session = self._create_cloudscraper_session()
        if self._scraper is not None:
            self._copy_cookies(self._scraper, browser_session)

        self._scraper = browser_session
        return self._scraper

    def _request_with_cloudflare_recovery(self, session, method_name, url, impersonate=None, **kwargs):
        response = self._request(session, method_name, url, impersonate=impersonate, **kwargs)
        if self._is_cloudflare_challenge(response):
            browser_session = self._switch_to_cloudscraper()
            response = self._request(browser_session, method_name, url, **kwargs)

        self._raise_if_cloudflare_challenge(response)
        return response

    @classmethod
    def _is_retryable_login_error(cls, exc):
        message = str(exc).lower()
        return any(marker in message for marker in cls._RETRYABLE_LOGIN_ERROR_MARKERS)

    def _bootstrap_login(self, session, impersonate):
        bootstrap_errors = []

        for url in (self.SIGN_IN_PAGE_URL, self.MAIN_PAGE_URL):
            try:
                response = self._request_with_cloudflare_recovery(
                    session,
                    "get",
                    url,
                    impersonate=impersonate,
                    timeout=self.LOGIN_TIMEOUT_SECONDS,
                )
                session = self._scraper or session
            except Exception as exc:
                bootstrap_errors.append(f"{url}: {exc}")
                continue

            if response.status_code != 200:
                bootstrap_errors.append(f"{url}: unexpected status {response.status_code}")
                continue

            csrf = self._extract_csrf_token(response.text, session.cookies)
            if csrf:
                return csrf

            bootstrap_errors.append(f"{url}: CSRF token not found")

        raise Exception(
            "Failed to initialize Letterboxd sign-in page. "
            + "; ".join(bootstrap_errors)
        )

    @staticmethod
    def _extract_csrf_token(response_text, cookie_jar):
        csrf = cookie_jar.get("com.xk72.webparts.csrf")
        if csrf:
            return csrf

        match = re.search(r'name="__csrf"\s+value="([^"]+)"', response_text)
        if match:
            return match.group(1)

        return None

    def sign_in(self, username, password, use_2fa_code):
        auth_code = ""
        if use_2fa_code:
            auth_code = input("Enter 2FA code: ")

        last_error = None
        attempts_used = 0

        for attempt in range(1, self.MAX_LOGIN_ATTEMPTS + 1):
            attempts_used = attempt
            impersonate = self.LOGIN_IMPERSONATES[(attempt - 1) % len(self.LOGIN_IMPERSONATES)]
            session = self._create_session()

            try:
                csrf = self._bootstrap_login(session, impersonate)
                session = self._scraper or session

                data = {
                    "__csrf": csrf,
                    "authenticationCode": auth_code,
                    "username": username,
                    "password": password,
                    "remember": "true"
                }

                headers = {
                    "Accept": "application/json, text/javascript, */*; q=0.01",
                    "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
                    "X-Requested-With": "XMLHttpRequest",
                    "Origin": "https://letterboxd.com",
                    "Referer": self.SIGN_IN_PAGE_URL,
                }

                resp = self._request_with_cloudflare_recovery(
                    session,
                    "post",
                    self.LOGIN_URL,
                    impersonate=impersonate,
                    data=data,
                    headers=headers,
                    timeout=self.LOGIN_TIMEOUT_SECONDS,
                )
                body_snippet = self._response_snippet(resp)

                if resp.status_code != 200:
                    raise Exception(f"Login failed: {resp.status_code} - {body_snippet[:300]}")

                try:
                    response_data = resp.json()
                except Exception:
                    raise Exception(f"Unexpected non-json response on login. Snippet: {body_snippet[:800]}")

                self._is_logged_in = response_data.get("result") == "success"
                if not self._is_logged_in:
                    messages = response_data.get("messages") or []
                    raise Exception("Login failed: " + ("; ".join(messages) if messages else "Unknown authentication error"))

                self._scraper = session
                self._csrf = response_data.get("csrf") or csrf
                return self._is_logged_in

            except CloudflareChallengeError as exc:
                last_error = exc
                if attempt == self.MAX_LOGIN_ATTEMPTS:
                    break
                time.sleep(self._retry_delay_seconds(attempt, exc.retry_after_seconds))
                continue
            except Exception as exc:
                last_error = exc
                if self._is_retryable_login_error(exc) and attempt < self.MAX_LOGIN_ATTEMPTS:
                    time.sleep(self._retry_delay_seconds(attempt))
                    continue
                break

        raise Exception(f"Login failed after {attempts_used} attempt(s): {last_error}")


    def download_export_data(self, file_name='letterboxd_export.zip'):
        if not self._is_logged_in or not self._scraper:
            raise Exception('You have to log in to download your export data.')

        last_error = None
        attempts_used = 0

        for attempt in range(1, self.MAX_DOWNLOAD_ATTEMPTS + 1):
            attempts_used = attempt
            impersonate = self.DOWNLOAD_IMPERSONATES[(attempt - 1) % len(self.DOWNLOAD_IMPERSONATES)]
            try:
                response = self._request_with_cloudflare_recovery(
                    self._scraper,
                    "get",
                    self.EXPORT_URL,
                    impersonate=impersonate,
                    headers={"Referer": self.MAIN_PAGE_URL},
                    stream=True,
                    timeout=self.DOWNLOAD_TIMEOUT_SECONDS
                )


                if response.status_code != 200:
                    raise Exception(f"Download failed: {response.status_code}")

                content_type = response.headers.get("Content-Type", "")
                if "html" in content_type.lower():
                    body_snippet = self._response_snippet(response)
                    raise Exception(
                        "Download failed: received HTML page instead of export archive. "
                        f"Response snippet: {body_snippet}"
                    )

                with open(file_name, 'wb') as f:
                    for chunk in response.iter_content(chunk_size=8192):
                        if chunk:
                            f.write(chunk)

                return file_name

            except CloudflareChallengeError as exc:
                last_error = exc
                if attempt == self.MAX_DOWNLOAD_ATTEMPTS:
                    break
                time.sleep(self._retry_delay_seconds(attempt, exc.retry_after_seconds))
                continue
            except Exception as exc:
                last_error = exc
                break

        raise Exception(f"Unable to get web request after {attempts_used} attempt(s): {last_error}")
