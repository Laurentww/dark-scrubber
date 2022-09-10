
from abc import ABC, abstractmethod
from asyncio import get_event_loop
from datetime import datetime
from distutils.sysconfig import get_python_lib
from json import loads as load_json
from logging import getLogger, WARNING
from os import remove, makedirs
from os.path import split, join
from pathlib import Path
from random import randint
from re import sub
from shutil import rmtree
from stat import S_IXOTH, S_IXGRP, S_IXUSR
from sys import platform
from time import time as time_now, sleep
from typing import Union
from urllib.parse import urlsplit
from zipfile import ZipFile

from pyppeteer import launch as pyppeteer_launch, errors as pyppeteer_errors
from pyppeteer.browser import Browser as PyppeteerBrowser
from pyppeteer.chromium_downloader import (
    download_zip, REVISION, DOWNLOADS_FOLDER, current_platform, windowsArchive
)
from pyppeteer_stealth import stealth
from requests import get as get_request
from selenium.common.exceptions import NoSuchElementException, NoSuchWindowException
from selenium.webdriver import Firefox, Chrome, FirefoxOptions, DesiredCapabilities
from selenium.webdriver.common.by import By
from selenium.webdriver.support.expected_conditions import visibility_of_element_located
from seleniumwire.webdriver import Firefox as FireFoxWire
from webdriver_manager.firefox import GeckoDriverManager

from .proxy import ProxyRequester
from .utils import (
    make_printable, kill_firefox_proc, kill_proc_recursive, write_pckl, read_pckl,
    script_dir, main_path, shared_subfolder_name
)

getLogger().setLevel(WARNING)


class Browser(ProxyRequester, ABC):

    _viewport = {'width': 1920, 'height': 1040}  # for headful (GUI) operation

    # Browser age limits for updating browser
    _browser_age_thr = {'min': 0.25, 'max': 4}  # [months]

    _chrome_window_arg = f'--window-size={_viewport["width"]},{_viewport["height"]}'
    _chrome_viewport_arg = {'defaultViewport': _viewport}

    _main_browser_subfolder = (shared_subfolder_name, 'browsers')

    _version_getter_base_url = 'https://registry.npmmirror.com/-/binary/'
    _ver_file_name = 'versions.pckl'

    # Placeholders
    page = None
    _driver_path = None
    browser: Union[Firefox, PyppeteerBrowser, None] = None

    def __init__(self, logger, mailer, config, timeout=30):
        super().__init__(mailer, logger, config)

        self._timeout = timeout
        self._headless = config.headless
        self._class_name = config.class_name
        self.is_binary = config.is_binary

        self._versions_pckl_file = self._base_browser_path.joinpath(self._ver_file_name)

    @abstractmethod
    def _send_keys(self, selector, text):
        pass

    @abstractmethod
    def _until_html_finished_loading(self):
        pass

    @property
    @abstractmethod
    def _browser_subfolder_name(self) -> tuple:
        pass

    @property
    def _base_browser_path(self):
        return main_path().joinpath(
            *(self._main_browser_subfolder + self._browser_subfolder_name)
        )

    def _eval_browser(self, *args, **kwargs):
        if self._driver_too_old:
            self._setup_browser() if self.browser is None else self._reset_browser()
        super()._eval_browser(*args, **kwargs)

    @property
    @abstractmethod
    def _version_getter_browser_str(self):
        pass

    @property
    def _version_getter_url_full(self):
        return self._version_getter_base_url + self._version_getter_browser_str

    @property
    @abstractmethod
    def _version_getter_url(self):
        pass

    def _latest_browser_online(self):
        if (
            not self._versions_pckl_file.is_file()
            or time_now() - self._versions_pckl_file.stat().st_ctime
            > self._browser_age_thr['min'] * 3600 * 24 * 30
        ):
            makedirs(self._versions_pckl_file.parent, exist_ok=True)
            write_pckl(self._versions_pckl_file, self._request_versions())

        # Select newest revision number from selected
        newest = sorted(read_pckl(self._versions_pckl_file), key=lambda x: x['age'])[0]

        return self._parse_version_dict(newest)

    @staticmethod
    @abstractmethod
    def _parse_version_dict(v_dict):
        pass

    @property
    def _driver_too_old(self):
        return (
            self._driver_path is None
            or not Path(self._driver_path).is_file()
            or time_now() - Path(self._driver_path).stat().st_ctime
            > self._browser_age_thr['min'] * 3600 * 24 * 30
        )

    def _request_versions(self, timeout=10):
        # Get list of possible Chromium revision numbers from internet
        url = self._version_getter_url
        self._logger.info(f'Requesting {url} for current chromium version numbers')
        response = get_request(url, timeout=timeout)
        versions = []
        latest = None
        if response.ok:
            now_date = datetime.now()
            for row in load_json(response.content):
                version = row['name'][:-1]
                date = row['date']
                age = now_date - datetime.strptime(date, self._version_date_fmt)
                age = age.total_seconds() / (3600 * 24 * 30)
                version_dict = {'age': age, 'version': version, 'date': date}
                # Select revision numbers within `self.chrome_age_thres`
                if self._browser_age_thr['min'] < age < self._browser_age_thr['max']:
                    versions += [version_dict]
                if latest is None or latest['age'] > version_dict['age']:
                    latest = version_dict
        else:
            self._logger.warning(f"Pyppeteer Chromium updater url failed: {url}")

        if not versions and latest is not None:
            versions = [latest]

        return versions

    @property
    @abstractmethod
    def _version_date_fmt(self):
        pass


class SeleniumFireFox(Browser, ABC):

    # Typing
    browser: Union[Firefox, FireFoxWire]

    # unix_geckodriver_path = '/usr/local/bin/geckodriver'

    _browser_subfolder_name = ('firefox',)
    _version_getter_browser_str = 'geckodriver'

    _version_date_fmt = "%Y-%m-%dT%H:%M:%SZ"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self._distinguish_key = f"-customkeyid{randint(1111123, 8999999)}"

        self.cookie_file_path = script_dir.joinpath('firefox_cookies.pckl')
        self._cookies_loaded = False

        self._browser_manager = GeckoDriverManager(path=str(self._base_browser_path))

        if self._config.use_proxy:
            self._logger.warning(
                'When using proxies, the Selenium-wire library is used instead of '
                'regular Selenium due to the ability of obtaining request status codes.'
                ' Be advised that Selenium-wire is greatly slower ..'
            )

    def _navigate(self, url):
        self._logger.debug(f"Navigating to {make_printable(url)} ..")
        self.browser.get(url)
        self._until_html_finished_loading()
        self._response_status = self._status_code

    def _save_html(self, source_file_name="source.html"):
        with open(script_dir.joinpath(source_file_name), "w") as f:
            f.write(self.browser.page_source)

    def _remove_element(self, element):
        self.browser.execute_script(
            "arguments[0].parentNode.removeChild(arguments[0]);", element
        )

    def _setup_browser(self, proxy=None):

        # self.session_folder = script_dir.joinpath('firefox_session')

        opts = FirefoxOptions()
        opts.add_argument('--binary')
        # opts.add_argument(f"user-data-dir={self.session_folder}")
        opts.headless = self._headless

        opts.add_argument(self._distinguish_key)

        capabilities = DesiredCapabilities.FIREFOX
        # capabilities['goog:loggingPrefs'] = {'performance': 'ALL'}

        self._logger.info('Setting up FireFox browser ..')
        self._logger.debug(f'Browser id: {self._distinguish_key}')

        proxy = proxy or self.proxy_cur
        if proxy:
            proxy_address = proxy.get_address()
            capabilities['proxy'] = {
                "proxyType": "MANUAL",
                "httpProxy": proxy_address,
                # "ftpProxy": proxy_address,
                "sslProxy": proxy_address,
                'socksProxy': proxy_address,
                # 'socksUsername': '',
                # 'socksPassword': '',
            }

        # Remove possibly old firefox driver versions
        versions = self._browser_versions_on_disk
        if len(versions) > 1:
            for version in sorted(versions, reverse=True)[1:]:
                rmtree(self._versions_path.joinpath(str(version)))

        _get_browser = lambda: (FireFoxWire if self._config.use_proxy else Firefox)(
            executable_path=self._driver_path,
            proxy=proxy,
            # service_args=['hide_console'],
            options=opts,
            desired_capabilities=capabilities,
            # seleniumwire_options={'disable_capture': True}  # Don't intercept requests
        )

        try:
            _ver_online = self._latest_browser_online()
            if not versions or versions[0] < _ver_online:
                self._driver_path = self._browser_manager.install()
            else:
                driver_folder = self._versions_path.joinpath(str(versions[0]))
                for driver_file in driver_folder.iterdir():
                    if driver_file.stem == self._version_getter_browser_str:
                        self._driver_path = str(driver_file)
                    else:
                        remove(driver_file)  # remove possibly existing .zip files
            self.browser = _get_browser()

        except PermissionError as error:
            # Driver executable probably in use by previous process, kill that process
            self._driver_path = error.filename
            self._logger.error(
                'Driver executable probably in use by previous process, '
                'killing this process ..'
            )
            kill_firefox_proc(split(self._driver_path)[-1])

            self.browser = _get_browser()

        # if isinstance(self.browser, Chrome):
        #     # Obfuscate being a webdriver
        #     self.browser.execute_cdp_cmd("Page.addScriptToEvaluateOnNewDocument", {
        #         "source": """
        #         Object.defineProperty(navigator, 'webdriver', {
        #           get: () => undefined
        #         })"""})

        self.browser.set_window_size(**self._viewport)

    @staticmethod
    def _parse_version_dict(v_dict):
        version = v_dict['version'][1:]
        if version[-2:] == '.0':
            return version[:-2]
        return version

    @property
    def _browser_versions_on_disk(self):
        self._versions_path = Path(
            self._browser_manager.driver_cache._drivers_directory,  # noqa
            self._browser_manager.driver.get_name(),
            self._browser_manager.driver.get_os_type()
        )

        if not self._versions_path.is_dir():
            return []

        return [int(i.name) for i in self._versions_path.iterdir() if i.name.isdigit()]

    @property
    def _browser_needs_updating(self):
        latest_json = self._latest_browser_online()
        latest_browser_on_disk = sorted(self._browser_versions_on_disk, reverse=True)[0]
        return (
            latest_browser_on_disk != latest_json
            or self.browser is None
            or self._driver_too_old
        )

    def quit(self):
        if self.browser is not None:
            self._logger.debug('Killing FireFox browser processes ..')
            kill_firefox_proc(match_terms=self._distinguish_key)
            # kill_proc_recursive(self.browser.get_pid()
            self.browser.close()

    def _reset_browser(self):
        self.quit()
        self._setup_browser()

    def _reload(self):
        self.browser.refresh()

    @property
    def _version_getter_url(self):
        return self._version_getter_url_full

    @property
    def _url(self):
        return self.browser.current_url

    def _in_page(self, selector, _timeout=30):
        try:
            return visibility_of_element_located((
                By.CSS_SELECTOR, selector
            ))(self.browser)
        except NoSuchElementException:
            return False
        # Wait(self.browser, timeout).until(
        #     visibility_of_element_located((By.XPATH, selector))
        # )

    def _send_keys(self, selector, text, css=True):
        if css:
            element = self.browser.find_element_by_css_selector(selector)
        else:
            element = self.browser.find_element_by_xpath(f'//input[@name="{selector}"]')
        element.send_keys(text)

    def _until_html_finished_loading(
            self,
            timeout=30,  # seconds
            raise_error=False,
            stable_n_thres=4,
    ):
        stable_n = 0
        t_start = time_now()
        while time_now() - t_start <= timeout:
            try:
                ready_state = self.browser.execute_script("return document.readyState")
                if ready_state == "complete":
                    stable_n += 1
                else:
                    stable_n = 0

                if stable_n == stable_n_thres:
                    self._logger.debug(f"Finished loading {make_printable(self._url)}")
                    return

            except NoSuchWindowException:
                self.browser.switch_to.default_content()
                stable_n = 0

            sleep(0.1)

        if raise_error:
            raise TimeoutError(f"Loading of page took more than {timeout} seconds ...")

    def _load_cookies(self, url):
        self.browser.get("://".join(urlsplit(url)[:2]))
        self._until_html_finished_loading()

        self._logger.debug('Loading cookies ..')
        netloc = urlsplit(self._url).netloc
        for cookie in read_pckl(self.cookie_file_path):
            if cookie['domain'] in netloc:
                self.browser.add_cookie(cookie)

        self._cookies_loaded = True

    def _save_cookies(self):
        self._logger.debug('Saving cookies ..')
        write_pckl(self.cookie_file_path, self.browser.get_cookies())

    @property
    def _status_code_chrome(self):
        assert isinstance(self.browser, Chrome)
        for entry in self.browser.get_log('performance'):
            for k, v in entry.items():
                if k == 'message' and 'status' in v:
                    for mk, mv in load_json(v)['message']['params'].items():
                        if mk == 'response' and mv['url'] == self._url:
                            return mv['status']

    @property
    def _status_code(self):
        if self._config.use_proxy:
            # Uses selenium-wire library  (=very slow)
            for request in reversed(self.browser.requests):
                if request.response and self._url in request.url:
                    return request.response.status_code
            return None

        return 200  # success response code; code not important if not using proxy


def _chromiumExecutable(downloads_folder=None, version=None):
    # From pyppeteer.chromium_downloader.py l.48
    downloads_folder = downloads_folder or DOWNLOADS_FOLDER
    version = str(version) if version else REVISION
    return {
        'linux': join(downloads_folder, version, 'chrome-linux', 'chrome'),
        'mac': join(downloads_folder, version, 'chrome-mac', 'Chromium.app', 'Contents', 'MacOS', 'Chromium'),  # noqa
        'win32': join(downloads_folder, version, windowsArchive, 'chrome.exe'),
        'win64': join(downloads_folder, version, windowsArchive, 'chrome.exe'),
    }[current_platform()]


class Puppeteer(Browser, ABC):

    _browser_subfolder_name = ('chromium',)
    _version_getter_browser_str = 'chromium-browser-snapshots'

    _version_date_fmt = "%Y-%m-%dT%H:%M:%S.%fZ"

    async def __navigate(self, url):
        response = await self.page.goto(url, {'timeout': self._timeout * 1000})
        await self._until_html_finished_loading(stable_n_thres=2)
        self._response_status = response.status

    def _navigate(self, url):
        get_event_loop().run_until_complete(self.__navigate(url))

    async def __reset_browser(self):
        await self._quit()
        await self.__setup_browser()

    def _reset_browser(self):
        get_event_loop().run_until_complete(self.__reset_browser())

    async def _click_through(self, instructions):
        for instruction in instructions:
            if not await self._select_option_by_text(*instruction):
                return False
        return True

    async def _in_page(self, selector, check_visibility=False):
        try:
            element = await self.page.querySelector(selector)
            if element is None:
                return False

            elif not check_visibility:
                return True

            return await element.isIntersectingViewport()

        except pyppeteer_errors.ElementHandleError:
            return False

    async def __stealth_callback(self):
        await stealth(self.page)

    def _stealth_callback(self):
        get_event_loop().run_until_complete(self.__stealth_callback())

    async def _send_keys(self, selector, text):
        await self.page.focus(selector)
        await self.page.type(selector, text)

    @property
    def _url(self):
        return self.page.url

    @staticmethod
    def _is_xpath(check_str):
        return '@id' in check_str or '>' not in check_str

    async def _until_html_finished_loading(
            self,
            timeout=30,  # seconds
            check_interval_msecs=100,
            stable_n_thres=4,
            raise_error=False,
    ):
        html_size_prev = 0
        stable_n = 0
        t_start = time_now()
        while time_now() - t_start <= timeout:
            html_size_cur = len(await self.page.content())
            # self._logger.debug(f'last: {html_size_prev} <> curr: {html_size_cur}')

            if html_size_prev != 0 and html_size_cur == html_size_prev:
                stable_n += 1
            else:
                stable_n = 0

            if stable_n == stable_n_thres:
                self._logger.debug(f"Finished loading '{self.page.url}' ...")
                return

            html_size_prev = html_size_cur
            await self.page.waitFor(check_interval_msecs)

        if raise_error:
            raise TimeoutError(f"Loading of page took more than {timeout} seconds ...")

    async def __setup_browser(self, proxy=None):
        proxy_arg = (
            f'--proxy-server={(proxy or self.proxy_cur).get_address()}'
            if self._use_proxy else ''
        )
        headful_kwargs, window_arg = (
            ({}, '') if self._headless
            else (self._chrome_viewport_arg, self._chrome_window_arg)
        )

        self._ensure_driver_updated()

        self.browser = await pyppeteer_launch(
            {'ignoreDefaultArgs': ['--enable-automation']},
            ignoreHTTPSErrors=True,
            executablePath=self.driver_path,
            headless=self._headless,
            **headful_kwargs,
            args=[proxy_arg, window_arg]
        )
        self.page = await self.browser.newPage()

    def _setup_browser(self, proxy=None):
        get_event_loop().run_until_complete(self.__setup_browser(proxy))

    def _ensure_driver_updated(self):
        version = self._latest_browser_online()
        self.driver_path = _chromiumExecutable(self._base_browser_path, version)
        driver_path = Path(self.driver_path)

        if not driver_path.exists():
            # Replace Chromium version in pyppeteer configuration file
            key = "__chromium_revision__"
            version_file_path = Path(
                main_path() if self.is_binary else get_python_lib(),
                'pyppeteer', '__init__.py'
            )
            with open(version_file_path, 'r') as f:
                version_file_new = sub(
                    f"{key}.*?=.*?'[0-9]*'", f"{key} = '{version}'", f.read()
                )
            with open(version_file_path, 'w') as f:
                f.write(version_file_new)

            for existing_chrome_path in self._base_browser_path.iterdir():
                if existing_chrome_path.is_dir():
                    rmtree(existing_chrome_path)

            # Download and extract new Chromium version
            self._logger.info(f'Downloading Chromium revision {version}')
            zip_path = self._base_browser_path.joinpath(version)
            if zip_path.is_dir():
                rmtree(zip_path)
            makedirs(zip_path)
            selected_get = get_request(f"{self._version_getter_url}{version}/")
            with ZipFile(download_zip(load_json(selected_get.content)[0]['url'])) as zf:
                zf.extractall(str(zip_path))
            driver_path.chmod(driver_path.stat().st_mode | S_IXOTH | S_IXGRP | S_IXUSR)
            self._logger.info(f'Chromium extracted to: {driver_path}')

    @property
    def _version_getter_url(self):
        src = {'win32': 'Win_x64', 'linux': 'Linux_x64'}.get(platform, platform)
        return f'{self._version_getter_url_full}/{src}/'

    @staticmethod
    def _parse_version_dict(v_dict):
        return v_dict['version']

    async def __reload(self):
        await self.page.evaluate('() => {location.reload(true);}')

    def _reload(self):
        get_event_loop().run_until_complete(self.__reload())

    async def _quit(self):
        if self.browser is not None:
            self._logger.debug('Quitting browser ..')
            kill_proc_recursive(self.browser.process.pid)
            await self.browser.close()

    def quit(self):
        get_event_loop().run_until_complete(self._quit())

    async def _until_out_of_page(self, selector, check_visibility=True, timeout=0.2):
        while await self._in_page(selector, check_visibility=check_visibility):
            sleep(timeout)

    async def _get_property(self, selector, prop_str):
        return await (
            self._get_xpath_property if self._is_xpath(selector)
            else self._get_selector_property
        )(selector, prop_str)  # noqa

    async def _get_text(self, selector: str, retries=1):
        counter = 0
        while True:
            try:
                return await self.__get_text(selector)
            except IndexError as e:
                if counter >= retries:
                    raise e
                counter += 1

    async def __get_text(self, selector: str):
        return await (
            self._get_xpath_text if self._is_xpath(selector)
            else self._get_selector_text
        )(selector)  # noqa

    async def _get_xpath_text(self, xpath: str):
        return await self._get_xpath_property(xpath, 'textContent')

    async def _xpath_elem(self, xpath):
        return await self.page.xpath(xpath)

    async def _get_xpath_property(self, xpath, prop_str):
        if len(await self._xpath_elem(xpath)) == 0:
            await self._until_html_finished_loading()
        prop_str = await (await self._xpath_elem(xpath))[0].getProperty(prop_str)
        return prop_str._remoteObject['value']  # noqa

    async def _get_selector_text(self, selector):
        return await self.page.querySelectorEval(selector, 'el => el.textContent')

    async def _get_selector_property(self, selector, prop_str):
        if isinstance(selector, str):
            element = await self.page.querySelector(selector)
        else:
            element = selector
        return await (await element.getProperty(prop_str)).jsonValue()

    async def _select_option_by_text(self, selector, text, attr_str='text'):
        assert not self._is_xpath(selector), \
            'Click-through selector is an xpath, needs to be css, closing ...'
        dropdown_element = await self.page.querySelector(selector)
        option_value = await dropdown_element.querySelectorAllEval(
            'option', f'options => options.find(o => o.{attr_str} === "{text}")?.value'
        )
        if option_value:
            await self.page.select(selector, option_value)
            await self._until_html_finished_loading(stable_n_thres=2)
            return True
        return False
