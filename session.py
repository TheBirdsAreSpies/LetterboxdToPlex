import requests
import re
import json


class Session:
    LOGIN_URL = "https://letterboxd.com/user/login.do"
    MAIN_PAGE_URL = "https://letterboxd.com/"

    _csrf = None
    _cookies = None
    _is_logged_in = False

    def __init__(self, username: str, password: str, use_2fa_code):
        if username is None or password is None:
            raise Exception("Username or password not set.")

        self.sign_in(username, password, use_2fa_code)

    def sign_in(self, username, password, use_2fa_code):
        session = requests.Session()

        # Simulate initial GET request to obtain CSRF token and cookies from the main page
        initial_response = session.get(self.MAIN_PAGE_URL)
        if initial_response.status_code != 200:
            raise Exception(f"Failed to load main page: {initial_response.status_code}")
        self._csrf = session.cookies['com.xk72.webparts.csrf']

        auth_code = ""
        if use_2fa_code:
            auth_code = input("Enter 2FA code: ")

        data = {
            "__csrf": self._csrf,
            "authenticationCode": auth_code,
            "username": username,
            "password": password
        }

        response = session.post(self.LOGIN_URL, data=data)
        if response.status_code == 200:
            response_data = json.loads(response.text)
            self._is_logged_in = response_data.get('result') == 'success'
            self._cookies = session.cookies
        else:
            raise Exception(f"Was not able to create a session: {response.status_code}")

    def _build_headers(self):
        # we have to build a cookies string because setting the param per request does not work somehow
        cookies = f'com.xk72.webparts.csrf={self._csrf};'
        for cookie in self._cookies:
            cookies = cookies + f'{cookie.name}={cookie.value}; '

        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:109.0) Gecko/20100101 Firefox/118.0",
            "Accept": "*/*",
            "Accept-Language": "de,en-US;q=0.7,en;q=0.3",
            "Accept-Encoding": "gzip, deflate, br",
            "Referer": "https://letterboxd.com/",
            "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
            "X-Requested-With": "XMLHttpRequest",
            "Origin": "https://letterboxd.com",
            "Cookie": cookies
        }

        return headers

    def download_export_data(self, file_name='letterboxd_export.zip'):
        url = 'https://letterboxd.com/data/export/'

        if not self._is_logged_in:
            raise Exception('You have to log in to download your export data.')

        try:
            headers = self._build_headers()
            response = requests.get(url, headers=headers)

            if response.status_code == 200:
                data = response.content
                if 'html' in str(data):
                    raise Exception('User not signed in')

                with open(file_name, 'wb') as file:
                    file.write(data)
            else:
                print("Error while downloading data")

        except requests.exceptions.RequestException as e:
            print(f"Unable to get web request: {e}")
