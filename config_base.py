
from lib.proxy_utils import co_map


class ConfigBase:

    class_name = ''  # Name given to this program; for printing purposes

    polling = {
        'start_h':       10,
        'end_h':         23,
        'wait_minutes':  20,
        'bds':           0.5,   # Bounds on wait interval
    }
    sleep_over_weekend = False

    driver = ''  # 'firefox' or 'puppeteer'
    headless = False

    # Mailing address and application password
    mail_info = {'addr': "", 'app_pw': ""}

    # dictionary containing the urls and css or xpath selectors to scrape
    check  = {}  # {`url`: [`selector`]}

    ##################
    #  Proxy Inputs  #
    ##################

    use_proxy = False

    src_countries = [  # locate proxies from these countries
        country for country in co_map.keys()
    ]

    # Page load timeout [seconds]
    timeout = 30

    # Number of spawned processes used to test for working proxies
    n_test_workers = 2

    working_proxy_limits = {
        'lower': 15,  # Number of working proxies for new proxies to be imported
        'upper': 35,  # Number of working proxies for proxy testing to be halted
        'timeout': 60  # Timeout when number of working proxies is below lower threshold
    }

    # Number of retries after which import of a proxy address is abandoned
    import_retries = 3
    ban_policy = {
        'last_n': 20,  # Previous n attempts taken into consideration
        'min_n': 5,  # minimum number of tries before proxy may be removed
        'working_ratio': 0.4  # Working/broken threshold below which proxy is removed
    }

    # Re-import proxy list if existing import is older than this [seconds]
    import_file_age_thres = 7200

    # Update tested proxy file if existing file is older than this [seconds]
    tested_proxy_file_age_thres = 1200

    def __init__(self):
        assert self.class_name
        assert self.check
        if hasattr(self, 'driver') and self.driver:
            assert self.driver in ['firefox', 'puppeteer']
