import requests
import re
import json


class Session:
    LOGIN_URL = "https://letterboxd.com/user/login.do"

    _csrf = None
    _cookies = None
    _is_logged_in = False

    def __init__(self, username: str, password: str, use_2fa_code):
        if username is None or password is None:
            raise Exception("Username or password not set.")

        self.sign_in(username, password, use_2fa_code)

    def sign_in(self, username, password, use_2fa_code):
        # perform a request to extract csrf token
        response = requests.get(self.LOGIN_URL)
        csrf_pattern = re.compile(r'"csrf":\s*"([^"]+)"')
        match = csrf_pattern.search(response.text)

        if match:
            csrf_token = match.group(1)
            self._csrf = csrf_token
        else:
            raise Exception("was not able to extract csrf token")

        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
                          "Chrome/118.0.0.0 Safari/537.36",
            "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
            "Accept": "application/json, text/javascript, */*; q=0.01",
            "X-Requested-With": "XMLHttpRequest",
            "Origin": "https://letterboxd.com",
            "Referer": "https://letterboxd.com/",
            "Accept-Encoding": "gzip, deflate, br",
            "Accept-Language": "de,en-US;q=0.9,en;q=0.8,de-DE;q=0.7,sr;q=0.6,ko;q=0.5",
            "Cookie": f"com.xk72.webparts.csrf={csrf_token};"
        }

        auth_code = ""
        if use_2fa_code:
            auth_code = input("Enter 2FA code: ")

        data = {
            "__csrf": csrf_token,
            "authenticationCode": auth_code,
            "username": username,
            "password": password,
            "remember": True
        }

        response = requests.post(self.LOGIN_URL, headers=headers, data=data)

        if response.status_code == 200:
            response_data = json.loads(response.text)
            self._is_logged_in = response_data['result'] == 'success'
            self._cookies = response.cookies
        else:
            raise Exception('was not able to create a session')

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
