
from argparse import Namespace
from abc import ABC, abstractmethod
from http.client import BadStatusLine
from logging import ERROR
from multiprocessing import Process
from multiprocessing.managers import SyncManager
from random import choice
from sys import platform
from time import sleep, time as time_now

from bs4 import BeautifulSoup
from http_request_randomizer.requests.proxy.ProxyObject import Protocol
from pyppeteer import errors as pyppeteer_errors
from requests import get as get_request
from websockets.exceptions import ConnectionClosedError

from .proxy_utils import (
    RequestProxyCustom, ProxyObjectCustom, SpysProxyParser, ensure_custom_proxy_objects
)
from .utils import write_pckl, read_pckl, code_ok, script_dir

# enable sharing of ProxyObject between multiprocessing workers
SyncManager.register('ProxyObject', ProxyObjectCustom)


class _ProxyRequesterBase(ABC):

    reset_errors = (ConnectionClosedError,)
    if 'win' not in platform:
        from asyncio.streams import IncompleteReadError
        reset_errors += (
            IncompleteReadError,
            # Error,  # too general
        )

    _caught_errors = (
        pyppeteer_errors.TimeoutError,
        BadStatusLine,
        pyppeteer_errors.NetworkError,
        ConnectionResetError,
    )

    _page_catches = [
        'PROXY_CONNECTION_FAILED', 'TUNNEL_CONNECTION_FAILED', 'EMPTY_RESPONSE',
        'ERR_TIMED_OUT', 'CONNECTION_TIMED_OUT', 'CONNECTION_RESET',
        'SSL_PROTOCOL_ERROR', 'CONNECTION_CLOSED'
    ]

    _response_status: int = None
    _error_msg = None
    _skip_url = None

    browser = None

    @abstractmethod
    def eval_browser(self, url, selector, **kwargs):
        pass

    def _prepare_eval(self, url, refresh, *_args):
        if self.browser is None:
            # make browser if it does not exist
            self._setup_browser()

        if self._url != url:
            self._navigate(url)
        elif refresh:
            self._reload()

    @property
    @abstractmethod
    def _url(self):
        pass

    @abstractmethod
    def _setup_browser(self, proxy=None):
        pass

    @abstractmethod
    def _navigate(self, url):
        pass

    @abstractmethod
    def _reload(self):
        pass

    @abstractmethod
    def quit(self):
        pass

    @abstractmethod
    def _reset_browser(self):
        pass

    def _quit_with_exception(self, e):
        self.quit()
        raise e


class ProxyRequester(_ProxyRequesterBase, ABC):

    filenames = Namespace(
        tested='plist_tested.pckl',
        imported='plist_imported.pckl'
    )

    _tested_proxies = Namespace(
        file=filenames.tested,
        data=Namespace(
            working={},
            broken={},
        )
    )
    _imported_proxies = Namespace(
        file=filenames.imported,
        data=None,
        data_mp=None,
    )

    proxies = Namespace(
        working=None,
        broken=None,
    )

    proxy_cur: ProxyObjectCustom
    proxy_cur = None

    def __init__(self, mailer, logger, config):
        self._mailer = mailer
        self._logger = logger
        self._config = config

        self._caught_errors += self.reset_errors

        self._use_proxy = config.use_proxy

        self.__test_urls = None

        if self._use_proxy:
            self._working_proxy_limits = Namespace(**config.working_proxy_limits)
            self._ban_policy = Namespace(**config.ban_policy)

            self._imported_proxies.file = script_dir.joinpath(
                self._imported_proxies.file
            )
            self._tested_proxies.file = script_dir.joinpath(self._tested_proxies.file)

            self._spys_parser = SpysProxyParser(
                self._mailer, self._logger, config.src_countries, timeout=10
            )

            self._manager = SyncManager()  # Multiprocess shared variable manager
            self._manager.start()
            self.proxies.working = self._manager.dict()
            self.proxies.broken = self._manager.dict()
            self._imported_proxies.data_mp = self._manager.dict()
            self._mp_jobs = self._manager.dict()
            self._mp_jobs['jobs_finished'] = self._manager.Value('i', 0)
            self._mp_jobs['testing'] = self._manager.Value('i', 0)
            if self._tested_proxies.file.exists():
                self._tested_proxies.data = read_pckl(self._tested_proxies.file)
                self._conv_proxy_dict_to_mp(
                    self._tested_proxies.data.working, self.proxies.working
                )
                self._conv_proxy_dict_to_mp(
                    self._tested_proxies.data.broken, self.proxies.broken
                )

                self._logger.debug(
                    f'Loaded {len(self.proxies.working)} working proxies '
                    f'({len(self.proxies.broken)} broken) '
                    f'from file: {self._tested_proxies.file}'
                )

    def eval(self, url, selector):
        if self._use_proxy:
            while True:
                self._set_random_proxy()
                self._eval_proxied_browser(url, selector=selector)
                if self._proxy_successful():
                    break

        else:
            self._eval_browser(url, selector)

    def _eval_proxied_browser(self, url, selector, last_retry=False):
        error_msg, self._response_status = '', 512

        if self.browser and url == self._skip_url:
            return

        if self._skip_url:
            self._skip_url = None  # Reset

        try:
            self._eval_browser(url, selector)

        # Catch known proxy errors
        except (TimeoutError,) as e:
            error_msg = e.msg

        except IndexError as e:
            if last_retry:
                raise e
            self._reload()
            return self._eval_proxied_browser(url, selector, last_retry=True)

        except pyppeteer_errors.PageError as e:
            if any(map(str(e).__contains__, self._page_catches)):
                error_msg = str(e)
            else:
                self._quit_with_exception(e)

        except self._caught_errors as e:
            error_msg = str(e)

            if isinstance(e, self.reset_errors):
                self._reset_browser()
            elif isinstance(e, pyppeteer_errors.TimeoutError):
                # self._reset_browser()
                self._skip_url = self._url

        except Exception as e:
            self._quit_with_exception(e)

        if error_msg:
            self._logger.info("Caught Exception:", error_msg)

        if self._use_proxy is not None:
            self.quit()

        self._error_msg = error_msg.strip('\n')

    def _eval_browser(self, url, selector, refresh=True):
        self._prepare_eval(url, refresh)
        self.eval_browser(url, selector)

    def _prepare_eval(self, url, refresh, *_args):
        if self._use_proxy:
            # proxy given; make new browser and use stealth
            self.browser = None
            self._setup_browser()
            self._stealth_callback()

        super()._prepare_eval(url, refresh)

    def _stealth_callback(self):
        pass

    def _proxy_successful(self):
        # self._logger.debug(f'Scraped:\n{text.encode("utf8")}\n')

        proxy_failed = self._error_msg or not code_ok(self._response_status)
        eval_hist = self.proxy_cur.get('successful_eval')
        eval_hist += [0 if proxy_failed else 1]
        for _ in range(len(eval_hist) - self._ban_policy.last_n):
            eval_hist.pop(0)

        working_ratio = sum(eval_hist) / len(eval_hist)
        if proxy_failed:
            wr_ok = self.proxies.broken < self._ban_policy.working_ratio
            if len(eval_hist) >= self._ban_policy.min_n and wr_ok:
                p_address = self.proxy_cur.get_address()
                self.proxies.broken[p_address] = self.proxies.working.pop(p_address)
                self._logger.debug(
                    f"{self._error_msg} - "
                    f"Removed Straggling proxy: {self.proxy_cur.str()} - "
                    f"History: {eval_hist}"
                )

                self._tested_proxies.data.broken[p_address] = \
                    self._tested_proxies.data.working.pop(p_address)
                self._write_tested_proxies_file()

            else:
                self._logger.debug(
                    f"{self._error_msg} - Proxy failed; {self.proxy_cur.str()} - "
                    f"History: {eval_hist} - Ratio {working_ratio:1.3f}"
                )

        return not proxy_failed

    def _set_random_proxy(self):
        self._update_proxy_list()

        self.proxy_cur = choice(list(self.proxies.working.values()))
        self._logger.debug(f"Using proxy: {self.proxy_cur.str()}")

    def _update_proxy_list(self):
        if self._mp_jobs['testing'].value == 0:
            # kill_chromedriver_proc()  # kill inactive browsers

            if len(self.proxies.working) < self._working_proxy_limits.lower:
                self._dispatch_proxy_updater()

        while len(self.proxies.working) < self._working_proxy_limits.lower:
            self._logger.info(
                'Not enough working proxies, sleeping for %d seconds' %
                self._working_proxy_limits.timeout
            )
            sleep(self._working_proxy_limits.timeout)

    def _dispatch_proxy_updater(self):
        self._mp_jobs['testing'].value = 1
        self._logger.info('Updating proxy list')
        self._import_proxy_list()
        jobs = []
        for i in range(self._config.n_test_workers):
            p = Process(target=self._update_proxy_worker)
            jobs.append(p)
            p.daemon = True
            p.start()

        return jobs

    def _update_proxy_worker(self):
        while len(self._imported_proxies.data_mp) != 0:
            if len(self.proxies.working) >= self._working_proxy_limits.upper:
                break

            proxy_addr = choice(list(self._imported_proxies.data_mp.keys()))
            proxy = self._imported_proxies.data_mp.pop(proxy_addr)

            if proxy_addr in [
                addr for state in ['broken', 'working']
                for d_i in [self._tested_proxies, self.proxies]
                for addr in d_i[state].keys()
            ]:
                continue

            if proxy.get('import_retries').value < self._config.import_retries:
                if self._proxy_works(proxy):
                    self.proxies.working[proxy_addr] = proxy
                    self._logger.debug(f'Found working proxy: {proxy.str()}')

                    self._write_tested_proxies_file(from_disk=True)

                else:
                    proxy.get('import_retries').value += 1

            else:
                self.proxies.broken[proxy_addr] = proxy
                self._logger.debug(f'Broken proxy: {proxy.str()}')

                self._write_tested_proxies_file(from_disk=True)

            sleep(0.5)

        self._mp_jobs['jobs_finished'].value += 1
        if self._mp_jobs['jobs_finished'].value != self._config.n_test_workers:
            return

        self._logger.info(
            'Proxy list updated; %d good, %d bad' %
            (len(self.proxies.working), len(self.proxies.broken))
        )

        if len(self.proxies.working) < self._working_proxy_limits.lower:
            self._mailer.send(
                text='Proxy list just updated; only %d working proxies left' %
                     len(self.proxies.working)
            )

        # Reset counter
        self._mp_jobs['jobs_finished'].value = 0
        self._mp_jobs['testing'].value = 0

    def __import_proxy_list(self):
        # SOCS5: empty list. Duration ~150s
        req_proxy = RequestProxyCustom(log_level=ERROR, protocol=Protocol.HTTPS)

        proxy_list = [
            p for p in req_proxy.proxy_list if
            p.anonymity_level.value == 3 and p.country in self._config.src_countries
        ]
        # proxy_list = []

        # Add list from spys.one/free-proxy-list
        spys_proxies = self._spys_parser.parse_proxyList()
        proxy_list += [
            p for p in spys_proxies
            if p.anonymity_level.value == 3  # elite proxies
            and p.protocols[0].value in [2, 4]  # [HTTPS, SOCKS5]
        ]

        # Filter for unique ip:port addresses
        # ~maybe do elitist selection based on latency+uptime?
        imported_proxies = {p.get_address(): p for p in proxy_list}

        self._imported_proxies.data = ensure_custom_proxy_objects(imported_proxies)

    def _import_proxy_list(self):
        """ Reads from existing file if file is younger than age_thres [seconds] """

        file_valid = self._imported_proxies.file.exists() and (
                time_now() - self._imported_proxies.file.stat().st_atime
                < self._config.import_file_age_thres
        )
        if file_valid:
            self._imported_proxies.data = read_pckl(self._imported_proxies.file)
            self._logger.debug(
                f'{len(self._imported_proxies.data)} Proxies imported from file on disk'
            )

        else:
            self.__import_proxy_list()
            self._logger.debug(
                f'{len(self._imported_proxies.data)} Proxies imported from web'
            )

            if self._imported_proxies.file.exists():
                self._imported_proxies.data.update(
                    read_pckl(self._imported_proxies.file)
                )

            write_pckl(self._imported_proxies.file, self._imported_proxies.data)

        self._conv_proxy_dict_to_mp(
            self._imported_proxies.data, self._imported_proxies.data_mp
        )

    def _conv_proxy_dict_to_mp(self, dict_in, dict_out=None, reverse=False):
        # Convert proxies to multiprocessing object
        dict_out = {} if dict_out is None else dict_out

        for p in dict_in.values():
            dict_out[p.get_address()] = self.conv_proxy_to_mp(p, reverse)

        return dict_out

    def conv_proxy_to_mp(self, p, reverse):
        """ Needed because pickling multiprocessing AutoProxy objects not possible
                - multiprocessing AutoProxy objects tied to instance of SyncManager()
        """
        args_ = (
            p.get(attr)
            for attr in ['source', 'ip', 'port', 'anonymity_level']
        )
        kwargs = {
            attr: p.get(attr)
            for attr in ['country', 'protocols', 'tunnel', 'latency', 'uptime']
        }
        proxy_object = ProxyObjectCustom if reverse else self._manager.ProxyObject

        p_mp = proxy_object(*tuple(args_), **kwargs)
        if reverse:
            p_mp.import_retries = p.get('import_retries').value
            p_mp.successful_eval = list(p.get('successful_eval'))
        else:
            p_mp.set('import_retries', self._manager.Value('i', 0))
            p_mp.set('successful_eval', self._manager.list())

        return p_mp

    def _proxy_works(self, proxy):
        self._eval_proxied_browser(choice(self._test_urls), proxy)
        return code_ok(self._response_status)

    def _write_tested_proxies_file(self, from_disk=False):

        if from_disk:
            file_age_seconds = time_now() - self._imported_proxies.file.stat().st_atime
            if file_age_seconds < self._config.tested_proxy_file_age_thres:
                return
            tested_proxies = read_pckl(self._tested_proxies.file)

        else:
            tested_proxies = self._tested_proxies.data

            # Update with possibly externally updated tested proxy file
            # (Allows for running proxy_updater when main.py is already running)
            if self._tested_proxies.file.exists():
                tested_proxies = _combine_pdicts(
                    tested_proxies,
                    read_pckl(self._tested_proxies.file),
                    preference='broken',
                )

        # Update tested proxy data
        for status in ['working', 'broken']:
            for proxy_addr, p in self.proxies[status].items():
                if proxy_addr not in tested_proxies[status]:
                    tested_proxies[status][proxy_addr] = self.conv_proxy_to_mp(
                        p, reverse=True
                    )

        # Write tested proxy file
        self._logger.debug(
            f'Writing {self._tested_proxies.file}; '
            f'{len(tested_proxies.working)} working, '
            f'{len(tested_proxies.broken)} broken'
        )
        write_pckl(self._tested_proxies.file, tested_proxies)

    @property
    def _test_urls(self, timeout=30):
        if self.__test_urls is None:
            response = get_request('https://uroulette.com/', timeout=timeout)
            if not response.ok:
                raise ValueError('Could not obtain a list of random websites, exiting.')

            tbody = BeautifulSoup(response.content, "html.parser").find("table")

            urls = []
            for href in tbody.find_all('p'):
                a = href.find('a')
                if (
                        a is not None
                        and hasattr(a, 'attrs')
                        and 'href' in a.attrs
                        and 'http' in a.attrs['href']
                        and a.attrs['href'] not in urls
                ):
                    urls.append(a.attrs['href'])

            if not urls:
                raise ValueError('Could not obtain a list of random websites, exiting.')

            self.__test_urls = urls

        return self.__test_urls


def _combine_pdicts(*args, preference='working'):
    """ Combines proxy dictionaries
    If preference=='working':
        Keeps proxy as working if it exists in both broken and working list
    Elif preference=='broken':
        Keeps proxy as broken if it exists in both broken and working list
    """

    pdicts_list = list(args)
    first, second = (
        ('working', 'broken') if preference == 'working' else ('broken', 'working')
    )

    dict_first = {
        proxy_address: proxy
        for pdict_i in pdicts_list for proxy_address, proxy in pdict_i[first].items()
    }
    dict_second = {
        proxy_address: proxy
        for pdict_i in pdicts_list for proxy_address, proxy in pdict_i[second].items()
        if proxy_address not in dict_first
    }

    return Namespace(first=dict_first, second=dict_second)
