#!/usr/bin/env python3

from argparse import ArgumentParser, Namespace
from typing import Union

from browser import SeleniumFireFox, Puppeteer
from config_base import ConfigBase
from lib.scraper import Scraper
from lib.proxy_utils import co_map
from mailer import Mailer


class Config(ConfigBase):

    class_name = 'Template Scraper'

    check = {
        # Example of default url input method for text retrieval of `xpath`
        'https://www.google.com/search?q=foo':
            {'xpath': [  # May also be a css selector string
                # Selector provided: subtitle of first search result
                '#rso > div:nth-child(3) > div > div > div:nth-child(2)'
            ]},

        # Example of url where parts of the webpage can be clicked before text retrieval
        'https://www.google.com/search?q=fooo':
            {'xpath':
                  [Namespace(
                      click=[(  # Sequence of elements to click on before scraping
                          '//*[@id="media_result_group"]/div/div/a',  # More images
                      )],
                      # Selector which contains goal text to be scraped
                      goalselector=''
                  )]
             },
    }

    polling = {
        'start_h': 10,
        'end_h': 23,
        'wait_minutes': 20,
        'bds': 0.5,  # Bounds on wait interval
    }

    driver = 'puppeteer'  # or 'puppeteer'

    sleep_over_weekend = True

    headless = False

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

    # Number of retries after which import of this proxy is abandoned
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


class TemplateScraper(Scraper):

    # If debug=True: prints scraped text and mail body to logger. Does not send emails.
    debug = False

    scraped_text_file = 'site_data.pckl'

    # Typing
    config: Config
    driver: Union[SeleniumFireFox, Puppeteer]
    mailer: Mailer

    def __init__(self):
        super().__init__(
            Config,
            SeleniumFireFox if Config.driver == 'firefox' else Puppeteer,
            Mailer,
        )

        self.check_urls = Namespace(**self.config.check)

    def _check_update(self):
        for url, url_dict in self.check_urls.items():
            self._check_update_of_url(url, url_dict)

    def _check_update_of_url(self, url, url_dict):
        for selector in url_dict['xpath']:
            self._eval_browser(url, selector)

        _site_data_cur = self.driver.site_data_cur

        #######################################
        #  * Handling of scraped site data *  #
        #######################################

        mailer_args = ()
        mailer_kwargs = {}
        self.mailer.send_update(url, *mailer_args, **mailer_kwargs)


if __name__ == '__main__':
    parser = ArgumentParser(description='Template scraper')
    # parser.add_argument('--example_arg', action='store_true', help="description")
    # args = parser.parse_args()

    TemplateScraper().run()
