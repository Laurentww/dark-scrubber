
from abc import ABC

from lib import Browser_base, Puppeteer_base, SeleniumFireFox_base


class Browser(Browser_base, ABC):
    """ Base browser class for this application. Ignore if only one browser is used """

    site_data_cur = ''


class Puppeteer(Browser, Puppeteer_base):

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Do optional initialization

    def eval_browser(self, url, selector, **kwargs):
        self._navigate(url)

        #######################################
        #  * Handling of scraped site data *  #
        #######################################

        # self._send_keys(selector, text)  # into input box defined by `selector`

        # text = await self._get_text(selector)
        # property = await self._get_property(selector, <property_str>)

        self.site_data_cur = ''


class SeleniumFireFox(Browser, SeleniumFireFox_base):

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Do optional initialization

    def eval_browser(self, url, selector, **kwargs):
        self._navigate(url)

        #######################################
        #  * Handling of scraped site data *  #
        #######################################

        # self._send_keys(selector, text)
        #
        # self._save_html(source_file_name="source.html")
        #
        # element = self.browser.find_element_by_xpath(
        #    '//a[contains(@aria-labelledby, "title")]'
        # )
        # property = element.get_attribute('href')
        # element.click()
        # text = element.text
        #
        # els = self.browser.find_elements_by_xpath('//button[@aria-label="Close"]')

        self.site_data_cur = ''
