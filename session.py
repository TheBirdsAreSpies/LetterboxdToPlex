import requests
import re
from curl_cffi import requests as curl_requests


class Session:
    LOGIN_URL = "https://letterboxd.com/user/login.do"
    MAIN_PAGE_URL = "https://letterboxd.com/"

    _csrf = None
    _cookies = None
    _is_logged_in = False
    _scraper = None

    def __init__(self, username: str, password: str, use_2fa_code):
        if username is None or password is None:
            raise Exception("Username or password not set.")

        self.sign_in(username, password, use_2fa_code)

    def sign_in(self, username, password, use_2fa_code):
        session = curl_requests.Session()

        # Initial GET to solve Cloudflare challenge and collect cookies/CSRF
        r = session.get(
            self.MAIN_PAGE_URL,
            impersonate="chrome",
            timeout=30
        )

        if r.status_code != 200:
            raise Exception(f"Failed to load main page: {r.status_code}")

        csrf = session.cookies.get("com.xk72.webparts.csrf")
        if not csrf:
            m = re.search(r'name="__csrf"\s+value="([^"]+)"', r.text)
            if m:
                csrf = m.group(1)

        if not csrf:
            raise Exception("CSRF token not found after initial GET")

        auth_code = ""
        if use_2fa_code:
            auth_code = input("Enter 2FA code: ")

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
            "Referer": "https://letterboxd.com/",
        }

        resp = session.post(
            self.LOGIN_URL,
            data=data,
            headers=headers,
            impersonate="chrome",
            timeout=30
        )

        # Detect Cloudflare page
        body_snippet = resp.text[:800] if resp.text else ""
        if resp.status_code == 403 or "Just a moment" in body_snippet or "<title>Just a moment" in body_snippet:
            raise Exception(f"Forbidden / Cloudflare challenge detected (403). Response snippet: {body_snippet}")

        if resp.status_code != 200:
            raise Exception(f"Login failed: {resp.status_code} - {body_snippet[:300]}")

        try:
            response_data = resp.json()
        except Exception:
            raise Exception(f"Unexpected non-json response on login. Snippet: {body_snippet[:800]}")

        self._is_logged_in = response_data.get("result") == "success"
        self._cookies = session.cookies
        self._scraper = session
        self._csrf = csrf
        return self._is_logged_in

    def _build_headers(self):
        cookies_str = f'com.xk72.webparts.csrf={self._csrf};'

        if hasattr(self._cookies, 'items'):
            for name, value in self._cookies.items():
                cookies_str += f'{name}={value}; '
        else:
            for cookie in self._cookies:
                if hasattr(cookie, 'name'):
                    cookies_str += f'{cookie.name}={cookie.value}; '
                else:
                    continue

        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:109.0) Gecko/20100101 Firefox/118.0",
            "Accept": "*/*",
            "Accept-Language": "de,en-US;q=0.7,en;q=0.3",
            "Accept-Encoding": "gzip, deflate, br",
            "Referer": "https://letterboxd.com/",
            "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
            "X-Requested-With": "XMLHttpRequest",
            "Origin": "https://letterboxd.com",
            "Cookie": cookies_str
        }

        return headers


    def download_export_data(self, file_name='letterboxd_export.zip'):
        url = 'https://letterboxd.com/data/export/'

        if not self._is_logged_in or not self._scraper:
            raise Exception('You have to log in to download your export data.')

        try:
            headers = self._build_headers()
            response = self._scraper.get(
                url,
                headers=headers,
                impersonate="chrome120",
                stream=True,
                timeout=60
            )

            body_snippet = ""
            content_type = response.headers.get("Content-Type", "")
            if response.status_code == 403 or 'html' in content_type.lower():
                try:
                    body_snippet = response.text[:800]
                except Exception:
                    body_snippet = ""
                if response.status_code == 403 or "Just a moment" in body_snippet or "<title>Just a moment" in body_snippet:
                    raise Exception(f"Forbidden / Cloudflare challenge detected (403). Response snippet: {body_snippet}")

            if response.status_code != 200:
                raise Exception(f"Download failed: {response.status_code}")

            with open(file_name, 'wb') as f:
                for chunk in response.iter_content(chunk_size=8192):
                    if chunk:
                        f.write(chunk)

            return file_name

        except requests.exceptions.RequestException as e:
            raise Exception(f"Unable to get web request: {e}")
