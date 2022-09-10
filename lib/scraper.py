
from abc import ABC, abstractmethod
from argparse import ArgumentParser, Namespace
from datetime import datetime as dt, timedelta
from logging import FileHandler, DEBUG, getLogger, Formatter
from logging.handlers import RotatingFileHandler
from random import normalvariate, uniform
from sys import platform, exc_info
from time import sleep, time
from typing import Type

try:
    from sys import frozen
    _is_binary = True
except ImportError:
    _is_binary = False

if 'win' not in platform:
    from signal import (
        Signals, signal, SIGINT, SIGTERM, SIGHUP, SIGCHLD, SIGQUIT, SIGILL, SIGTSTP
    )

from config_base import ConfigBase
from .browser import Browser, Puppeteer
from .mailer import Mailer
from .utils import script_dir, kill_chromedriver_proc

parser = ArgumentParser(description='DarkScrubber | Web Scraper')
parser.add_argument(
    '--kill_chrome',
    action='store_true',
    help="Kill running chromedriver process before execution of script"
)
args, _ = parser.parse_known_args()


class Scraper(ABC):

    # If debug=True: prints scraped text and mail body to logger. Does not send emails.
    debug: bool = None

    _kill_catch_str = 'This event loop is already running'

    # Flag if this script is run as a binary
    is_binary = _is_binary

    check_log_file = 'check_times.txt'

    # Placeholders
    logger = None
    check_log_path = None

    def __init__(
            self, config: Type[ConfigBase], driver: Type[Browser], mailer: Type[Mailer]
    ):
        self.config = config()
        self.config.is_binary = self.is_binary
        self.polling = Namespace(**self.config.polling)
        self.log_file = script_dir.joinpath(
            f'{self.config.class_name.replace(" ", "")}Listener.log'
        )

        self._setup_logger()
        self.mailer = mailer(self.logger, self.config, self.debug)
        self.driver = driver(self.logger, self.mailer, self.config)

        if 'win' not in platform:
            # Create a program termination signal catcher; sends email
            for signal_type in [
                SIGINT, SIGTERM, SIGHUP, SIGCHLD, SIGQUIT, SIGILL, SIGTSTP
            ]:
                # SIGSTOP and SIGKILL cannot be caught
                self.logger.debug(f'setting up {Signals(signal_type).name}')
                signal(signal_type, self._catch_shutdown)

        if isinstance(self.driver, Puppeteer) and args.kill_chrome:
            kill_chromedriver_proc()  # Kill possibly running chromedriver

    def run(self):
        self.logger.info('Started')
        self.mailer.send_startup()

        while True:
            self.logger.info(self._check_str)
            self._check_update()
            self._log_check_time()
            sleep(self._get_wait_time())

    @property
    def _check_str(self):
        return 'Performing a check' + (
            f' with {len(self.driver.proxies.working)} working proxies'
            if self.config.use_proxy else ''
        )

    @abstractmethod
    def _check_update(self):
        pass

    def _eval_browser(self, url, selector):
        try:
            self.driver.eval(url, selector)
        except (
            Exception,
            # IncompleteReadError,
        ) as scrape_error:
            if str(scrape_error) == self._kill_catch_str:  # When program is killed
                self.logger.debug(f'Caught error: {self._kill_catch_str}')
            else:
                self.mailer.send_error(
                    url,
                    error=scrape_error.with_traceback(exc_info()[2]),
                    selector=selector,
                )
                self.logger.error(str(scrape_error))

            if self.debug:
                raise scrape_error

    def _setup_logger(self, log_file=None):
        # Log file containing only check times
        self.check_log_path = script_dir.joinpath(self.check_log_file)

        # Log file for general program. Does not work properly without name
        self.logger = getLogger(self.config.class_name)
        self.logger.setLevel(DEBUG)
        for handler in self.logger.handlers:  # remove existing file handlers
            if isinstance(handler, FileHandler):
                self.logger.removeHandler(handler)

        formatter = Formatter(
            '%(asctime)s - %(levelname)s - %(message)s', datefmt='%d-%b-%y %H:%M:%S'
        )

        # fh = FileHandler(log_file, mode='w')
        rfh = RotatingFileHandler(  # noqa
            filename=self.log_file if log_file is None else log_file,
            mode='a',
            maxBytes=5 * 1024 * 1024,  # 5Mb
            backupCount=2,
            encoding='utf-8',
            delay=0
        )
        rfh.setFormatter(formatter)
        self.logger.addHandler(rfh)

    def _log_check_time(self, line_cap=100):
        if not self.check_log_path.exists():
            with open(self.check_log_path, 'w') as _:
                pass

        with open(self.check_log_path, 'r') as readfile:
            log_lines = readfile.readlines()

        log_lines.append(dt.now().strftime("%d %b %Y %H:%M:%S\n"))

        if len(log_lines) > line_cap:
            log_lines = log_lines[-line_cap:]

        with open(self.check_log_path, 'w') as readfile:
            readfile.writelines(log_lines)

    def _get_wait_time(self):
        wait_min, h_st, h_e, bds = \
            self.polling.wait_minutes, self.polling.start_h, \
            self.polling.end_h, self.polling.bds
        hour_now = dt.now().hour

        wait_hours = wait_min / 60
        if h_e < h_st:  # when end after 24:00 and end < start
            if h_e <= hour_now < h_st:
                wait_hours = h_st - hour_now
        else:
            if hour_now < h_st:
                wait_hours = h_st - hour_now + 1
            elif hour_now >= h_e:
                wait_hours = 24 + h_st - hour_now

        is_weekend = (dt.now() + timedelta(hours=wait_hours)).weekday() in [5, 6]
        if ConfigBase.sleep_over_weekend and is_weekend:
            self.logger.debug('Sleeping over weekend')
            today = now = dt.today()
            today = dt(today.year, today.month, today.day)
            time_to_end_of_week = timedelta(days=7 - now.weekday()) + today - now
            wait_hours = time_to_end_of_week.seconds/3600 + h_st

        _trunc_normal_sample = _truncnorm(0, bds / 2, [-bds, bds])
        sleep_hours_random = (wait_min/60) * _trunc_normal_sample

        sleep_seconds = int((wait_hours + sleep_hours_random) * 3600)

        self.logger.debug(
            'Sleeping for '
            f'{int(sleep_seconds/60)} minutes '
            f'{int(sleep_seconds % 60):02d} seconds'
        )

        return sleep_seconds

    def _catch_shutdown(self, signum, _frame):
        self.logger.debug(f'Sending signal {Signals(signum).name} ..')
        self.logger.info(f'Shutting down {ConfigBase.class_name} Scraper ..')
        self.mailer.send_shutdown()
        self.driver.quit()
        exit(signum)


def _truncnorm(loc, scale, bounds, timeout=5):
    """ scipy.truncnorm(), but using python builtins """
    t_start = time()
    while True:
        s = normalvariate(loc, scale)
        if bounds[0] <= s <= bounds[1]:
            return s
        if time() - t_start > timeout:
            # Revert to uniform sampling
            return uniform(*bounds)
