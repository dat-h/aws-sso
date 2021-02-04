import pickle
from hashlib import sha256

from selenium import webdriver
from selenium.common.exceptions import TimeoutException, NoSuchElementException
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait


class Error(Exception):
    """Base class for SSODriver exceptions."""

    def __init__(self, msg=''):
        self.message = msg
        Exception.__init__(self, msg)

    def __repr__(self):
        return self.message

    __str__ = __repr__


class AlertMessage(Error):
    """Raised when alert frame is displayed."""
    pass

class MFACodeNeeded(Error):
    """Raised when MFA code is needed."""

    def __init__(self, mfa_form):
        Error.__init__(self, 'MFA Code needed')
        self.mfa_form = mfa_form
        self.args = (mfa_form, )


class SSODriver():
    def __init__(self, url, username, headless=True, cookie_dir=None):
        self._url = url
        self._cookie_hash = SSODriver.hash(f'{username}@{url}')
        self._cookie_file = f'{cookie_dir}/{self._cookie_hash}.pkl' if cookie_dir else None
        chrome_options = Options()
        if headless:
            chrome_options.add_argument('--headless')
        self._driver = webdriver.Chrome(chrome_options=chrome_options)
        self._driver.implicitly_wait(5)
        self._poll_frequency = 0.05

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    @staticmethod
    def hash(s):
        return sha256(s.encode()).hexdigest()

    def _load_cookies(self):
        try:
            cookies = pickle.load(open(self._cookie_file, 'rb'))
            for cookie in cookies:
                if 'expiry' in cookie:
                    del cookie['expiry']
                self._driver.add_cookie(cookie)
        except FileNotFoundError:
            pass

    def _dump_cookies(self):
        cookies = []
        exclude = ['x-amz-sso_authn']
        for cookie in self._driver.get_cookies():
            if cookie['name'] not in exclude:
                cookies.append(cookie)
        pickle.dump(cookies, open(self._cookie_file, 'wb'))

    def _find_element_by_id(self, element_id, driver=None, timeout=10):
        driver = driver or self._driver
        return WebDriverWait(driver, timeout, poll_frequency=self._poll_frequency).until(
            EC.visibility_of_element_located((By.ID, element_id))
        )

    def _find_element_by_css_selector(self, css_selector, driver=None, timeout=10):
        driver = driver or self._driver
        return WebDriverWait(driver, timeout, poll_frequency=self._poll_frequency).until(
            EC.visibility_of_element_located((By.CSS_SELECTOR, css_selector))
        )

    def _click_element_by_id(self, element_id, driver=None, timeout=10):
        element = self._find_element_by_id(element_id, driver, timeout)
        element.click()
        return element

    def refresh_token(self, username, password, restore=False):
        self.get()
        self.login(username, password)
        try:
            return self.get_token(restore)
        except TimeoutException:
            self.check_alert()
            self.check_mfa()

    def get_token(self, restore=False):
        WebDriverWait(self._driver, 1, poll_frequency=self._poll_frequency).until(
            EC.presence_of_element_located((By.TAG_NAME, 'portal-dashboard'))
        )
        self._driver.get(self._url)
        cookie = self._driver.get_cookie('x-amz-sso_authn')
        if restore:
            self._driver.back()
        return (cookie['value'], cookie['expiry'])

    def close(self):
        if self._cookie_file:
            self._dump_cookies()
        self._driver.quit()

    def get(self):
        self._driver.get(self._url)
        if self._cookie_file:
            self._load_cookies()
        return self._driver

    def login(self, username, password):
        try:
            wait = WebDriverWait(self._driver, 1, poll_frequency=self._poll_frequency).until(EC.presence_of_element_located((By.ID, 'username-input')))
            el_username = wait.find_element_by_css_selector('div.awsui-input-container > input')
            el_username.clear()
            el_username.send_keys(username)
        except (TimeoutException, NoSuchElementException):
            pass
        try:
            wait_button = WebDriverWait(self._driver, 1, poll_frequency=self._poll_frequency).until(EC.presence_of_element_located((By.ID, 'username-submit-button')))
            el_username_submit = wait_button.find_element_by_css_selector('button')
            el_username_submit.click()
        except (TimeoutException, NoSuchElementException):
            pass
        try:
            wait_password = WebDriverWait(self._driver, 1, poll_frequency=self._poll_frequency).until(EC.presence_of_element_located((By.ID, 'password-input')))
            el_password = wait_password.find_element_by_css_selector('div.awsui-input-container > input')
            el_password.clear()
            el_password.send_keys(password)
        except (TimeoutException, NoSuchElementException):
            pass
        try:
            wait_password_button = WebDriverWait(self._driver, 1, poll_frequency=self._poll_frequency).until(EC.presence_of_element_located((By.ID, 'password-submit-button')))
            el_password_submit = wait_password_button.find_element_by_css_selector('button')
            el_password_submit.click()
        except (TimeoutException, NoSuchElementException):
            pass


    def check_alert(self):
        try:
            wait = WebDriverWait(self._driver, 1, poll_frequency=self._poll_frequency)
            alert = wait.until(EC.presence_of_element_located((By.ID, 'alertFrame')))
            error = alert.find_element_by_css_selector('div.a-alert-error > div.a-box-inner > h4').text
            message = alert.find_element_by_css_selector('div.a-alert-error > div.a-box-inner > div.gwt-Label').text
            raise AlertMessage(f'{error}: {message}')
        except (TimeoutException, NoSuchElementException):
            pass

    def check_mfa(self):
        try:
            wait = WebDriverWait(self._driver, 1, poll_frequency=self._poll_frequency)
            mfa = wait.until(EC.presence_of_element_located((By.TAG_NAME, 'form')))
            raise MFACodeNeeded(mfa)
        except TimeoutException:
            pass

    def send_mfa(self, mfa_form, mfacode, trusted_device=True):
        el_mfacode = self._find_element_by_css_selector('input.awsui-input-type-number', mfa_form)
        el_signin = self._find_element_by_css_selector('button.awsui-button-variant-primary', mfa_form)

        el_mfacode.clear()
        el_mfacode.send_keys(mfacode)
        el_signin.click()
