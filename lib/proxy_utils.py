
from abc import ABC, abstractmethod
from distutils.sysconfig import get_python_lib
from enum import Enum
from logging import StreamHandler, getLogger
from os.path import join
from re import compile, search, findall
from random import choice
from time import time
from typing import Union

from bs4 import BeautifulSoup
from fake_useragent import UserAgent
from http_request_randomizer.requests.parsers.FreeProxyParser import FreeProxyParser
from http_request_randomizer.requests.parsers.PremProxyParser import PremProxyParser
from http_request_randomizer.requests.parsers.UrlParser import UrlParser
from http_request_randomizer.requests.parsers.js.UnPacker import JsUnPacker
from http_request_randomizer.requests.proxy.ProxyObject import Protocol
from http_request_randomizer.requests.proxy.ProxyObject import ProxyObject
from http_request_randomizer.requests.proxy.requestProxy import RequestProxy
from http_request_randomizer.requests.useragent.userAgent import UserAgentManager
from quickjs import Function as FunctionJS
from requests import get as get_request, post as post_request
from requests.exceptions import ReadTimeout

handler = StreamHandler()
logger = getLogger(__name__)

from .utils import read_pckl, write_pckl, script_dir

# logging.getLogger().setLevel(logging.WARNING)

# User agent pickle file
ua_pckl_file_name = 'ua.pckl'


class ProxyObjectCustom(ProxyObject):
    import_retries = 0
    successful_eval = []

    def __init__(
            self,
            *args,
            country=None,
            protocols=None,
            tunnel=False,
            latency=None,
            uptime=None
    ):
        super().__init__(*args, country=country, protocols=protocols, tunnel=tunnel)
        self.latency = latency
        self.uptime = uptime

    def __str__(self):
        return self.str()

    def to_str(self):
        return f"Address: {self.get_address()} | Src: {self.source} | | " \
               f"Country: {self.country} | Anonymity: {self.anonymity_level} | " \
               f"Protoc: {self.protocols} | Tunnel: {self.tunnel} | " \
               f"Latency: {self.latency} | Uptime: {self.uptime}"

    def str(self):
        return f"{self.get_address()} | {self.country} | {self.source}"

    def get(self, attr):
        """ Required for registering as multiprocessing object.
            (object.attribute ~getter does not work)
        """
        return getattr(self, attr)

    def set(self, attr, val):
        """ Required for registering as multiprocessing object.
            (object.attribute = attribute ~setter does not work)
        """
        setattr(self, attr, val)


def ensure_custom_proxy_objects(dict_in):
    for pr_addr, p in dict_in.items():
        if not isinstance(p, ProxyObjectCustom):
            args = (p.source, p.ip, p.port, p.anonymity_level)
            kwargs = {
                'country': p.country,
                'protocols': p.protocols,
                'tunnel': p.tunnel,
                'latency': p.latency if hasattr(p, 'latency') else None,
                'uptime': p.uptime if hasattr(p, 'uptime') else None
            }
            dict_in[pr_addr] = ProxyObjectCustom(*args, **kwargs)

        else:
            dict_in[pr_addr] = p

    return dict_in


def _get_recent_common_user_agent(
        n=1,
        os_str='windows',
        browser='chrome',
        timeout=5,  # Request timeout in [seconds]
        age_thres=5,  # Refreshes user agent if existing check is more than [days] old
):
    ua_pckl_file = script_dir.joinpath(ua_pckl_file_name)

    if (
            not ua_pckl_file.exists()
            or time() - ua_pckl_file.stat().st_ctime > age_thres * 3600 * 24
    ):
        url = 'https://developers.whatismybrowser.com'
        response = get_request(
            f'{url}/useragents/explore/operating_system_name/{os_str}/', timeout=timeout
        )
        if not response.ok:
            return getattr(UserAgent(), browser)

        tbody = BeautifulSoup(response.content, "html.parser").find("tbody")
        uas = []
        for tr in tbody.find_all('tr'):
            tds = tr.find_all('td')
            if browser in tds[1].text.lower() and tds[-1].text == 'Very common':
                uas.append(tds[0].find('a', href=True).text)
                if len(uas) == n:
                    break

        if uas:
            out = uas[0] if n == 1 else uas
            write_pckl(ua_pckl_file, out)

        else:
            ua_generator = UserAgent()
            uas = [getattr(ua_generator, browser) for _ in range(n)]

        return uas[0] if n == 1 else uas

    else:
        logger.debug(f'Reading user agent from file ..')
        return read_pckl(ua_pckl_file)


class RequestProxyCustom(RequestProxy):
    def __init__(  # noqa
            self,
            web_proxy_list: list = None,
            sustain=False,
            timeout=5,
            protocol=Protocol.HTTP,
            log_level=0
    ):
        self.logger = getLogger()
        self.logger.addHandler(handler)
        self.logger.setLevel(log_level)
        self.userAgent = UserAgentManager(
            file=join(
                get_python_lib(),
                'http_request_randomizer', 'requests', 'data', 'user_agents.txt'
            )
        )

        parsers = list([])
        parsers.append(_FreeProxyParser(
            'FreeProxy', 'https://free-proxy-list.net', timeout=timeout
        ))
        parsers.append(_PremProxyParser(
            'PremProxy', 'https://premproxy.com', timeout=timeout
        ))
        parsers.append(_FreeProxyParser(
            'SslProxy', 'https://www.sslproxies.org', timeout=timeout
        ))

        self.logger.debug("=== Initialized Proxy Parsers ===")
        for i in range(len(parsers)):
            self.logger.debug(f"\t {parsers[i].__str__()}")
        self.logger.debug("=================================")

        self.sustain = sustain
        self.parsers = parsers
        self.proxy_list = web_proxy_list or []
        for parser in parsers:
            try:
                size = len(self.proxy_list)
                self.proxy_list += parser.parse_proxyList()
                self.logger.debug(
                    f'Added {len(self.proxy_list)-size} proxies from {parser.id}'
                )
            except ReadTimeout:
                self.logger.warning(f"Proxy Parser: '{parser.url}' TimedOut!")
        self.logger.debug(f'Total proxies = {len(self.proxy_list)}')
        # filtering the list of available proxies according to user preferences
        self.proxy_list = [p for p in self.proxy_list if protocol in p.protocols]
        self.logger.debug(f'Filtered proxies = {len(self.proxy_list)}')
        self.current_proxy = self.randomize_proxy()


class ProxyParserBase(FreeProxyParser, ABC):
    soup = None
    base_url = None
    country_list = None
    curr_proxy_list = None

    def __init__(self, *args, **kwargs):
        if 'country_list' in kwargs:
            self.country_list = [
                co_map[country] for country in kwargs.pop('country_list')
            ]
        super().__init__(*args, **kwargs)

    def init_js_unpacker(self):
        if self.soup is None:
            response = self._get()
            # Could not parse provider page - Let user know
            if not response.ok:
                logger.warning(f"Proxy Provider url failed: {self.get_url()}")
                return None
            content = response.content
            self.soup = BeautifulSoup(content, "html.parser")

        # js file contains the values for the ports
        for script in self.soup.findAll('script'):
            try:
                if '/js/' in script.get('src'):
                    return JsUnPackerCustom(self.base_url + script.get('src'))
            except TypeError:
                pass
        return None

    def _get(self, url: str = None, data: dict = None):
        getter = get_request if data is None else post_request
        return getter(
            url or self.get_url(),
            timeout=self.timeout,
            headers={'User-Agent': _get_recent_common_user_agent()},
        )

    @abstractmethod
    def _parse_proxyList(self):
        pass

    def parse_proxyList(self):
        self.curr_proxy_list = []
        try:
            self._parse_proxyList()
        except AttributeError as e:
            logger.error(f"Provider {self.id} failed with Attribute error: {e}")
        except KeyError as e:
            logger.error(f"Provider {self.id} failed with Key error: {e}")
        except Exception as e:
            logger.error(f"Provider {self.id} failed with Unknown error: {e}")

        return self.curr_proxy_list

    def _handle_dataset_proxy(self, proxy_in: Union[list, ProxyObject, zip]):
        if not isinstance(proxy_in, list):
            proxy_in = [proxy_in]

        for proxy_i in proxy_in:
            self.__handle_dataset_proxy(proxy_i)

    def __handle_dataset_proxy(self, proxy_in):
        if isinstance(proxy_in, ProxyObject):
            proxy = proxy_in
        else:
            proxy = self._create_proxy_object(proxy_in)

        # Make sure it is a Valid Proxy Address
        if proxy is not None and UrlParser.valid_ip_port(proxy.get_address()):
            self.curr_proxy_list.append(proxy)
        else:
            logger.debug(f"Proxy Invalid: {proxy}")

    @abstractmethod
    def _create_proxy_object(self, proxy_in):
        pass


class _FreeProxyParser(ProxyParserBase):
    def _parse_proxyList(self):
        response = self._get()
        if not response.ok:
            logger.warning(f"Proxy Provider url failed: {self.get_url()}")
            return []

        content = response.content
        soup = BeautifulSoup(content, "html.parser")
        table = soup.find("table", {"class": "table table-striped table-bordered"})

        # The first tr contains the field names.
        headings = [th.get_text() for th in table.find("tr").find_all("th")]

        datasets = []
        for row in table.find_all("tr")[1:-1]:
            dataset = zip(headings, (td.get_text() for td in row.find_all("td")))
            if dataset:
                datasets.append(dataset)

        self._handle_dataset_proxy(datasets)

    def _create_proxy_object(self, proxy_in):
        return self.create_proxy_object(proxy_in)


class SpysProxyParser(_FreeProxyParser):

    base_url = 'https://spys.one/free-proxy-list/'

    driver = None
    parse_f_str = 'parse_func'

    def __init__(self, mailer, logger_main, country_list, timeout=None):
        super().__init__(
            'SpysOne', self.base_url, timeout=timeout, country_list=country_list
        )
        self.mailer = mailer
        self.logger = logger_main
        self.timeout = timeout

        self.country_cur = None

    def parse_proxyList(self):
        self.curr_proxy_list = []
        for country in self.country_list:
            self.country_cur = country
            self._parse_proxyList()
        return self.curr_proxy_list

    def _parse_proxyList(self):
        web_url = self.base_url + self.country_cur
        try:
            data = {
                'xx00': '',
                'xpp': '5',  # 500 rows
                'xf1': '4',  # HIA
                'xf2': '0',
                'xf4': '0',
                'xf5': '0'
            }
            response = self._get(web_url, data=data)

            if not response.ok:
                self.logger.warning(f"Proxy Provider url failed: {web_url}")
                return []

            soup = BeautifulSoup(response.content, "html.parser")

            js_function = self._get_port_js_function(soup)

            table = soup.find_all("table")[2]

            # The first tr contains the field names.
            headings = [th.text for th in table.find_all("tr")[2]]

            datasets = []
            for row in table.find_all("tr")[3:-1]:
                if row.text:
                    tds = row.find_all("td")
                    js_arg = search('\((.*?)\)$', tds[0].find('script').string).group(1)
                    dataset = list(zip(
                        headings,
                        (td.text + ('' if i > 0 else js_function(js_arg))
                         for i, td in enumerate(tds) if i != 7)
                    ))
                    if dataset:
                        datasets.append(dataset)

            self._handle_dataset_proxy(datasets)

        except (AttributeError, KeyError, Exception) as e:
            self.logger.warning(e)

    def _get_port_js_function(self, soup):
        s = soup.find('script', attrs={"type": "text/javascript"}, text=compile("eval"))
        js_unpacker = JsUnPackerCustom(script=s.string)
        js_function_str = f"""
            function {self.parse_f_str}(a){{
            {js_unpacker.unpacked}
            return eval(a)
            }}
        """
        return FunctionJS(self.parse_f_str, js_function_str)

    def _create_proxy_object(self, dataset):
        ip = ""
        port = None
        anonymity = _AnonymityLevelCustom.UNKNOWN
        country = None
        latency = None
        uptime = None
        protocols = []

        for field in dataset:
            if field[0] == 'Proxy address:port':
                [ip, port] = field[1].strip().split(':')

                if not UrlParser.valid_ip(ip):
                    # logger.debug(f"IP with Invalid format: {ip}")
                    return None

            elif field[0] == 'Anonymity*':
                anonymity = _AnonymityLevelCustom.get(field[1].strip())

            elif field[0] == 'Country (city/region)':
                country = field[1].strip().split()[0]

            elif field[0] == 'Proxy type':
                protocols.append({
                    'https': Protocol.HTTPS,
                    'http': Protocol.HTTP,
                    'socks4': Protocol.SOCS4,
                    'socks5': Protocol.SOCS5,
                }[field[1].split()[0].strip().lower()])

            elif field[0] == 'Latency**':
                latency = float(field[1].strip())

            elif field[0] == 'Uptime' and 'new' not in field[1]:
                uptime = float(field[1].split()[0][:-1])/100

        return ProxyObjectCustom(
            self.id, ip, port, anonymity,
            country=country, protocols=protocols, latency=latency, uptime=uptime
        )


class _AnonymityLevelCustom(Enum):
    """
    UNKNOWN:        The proxy anonymity capabilities are not exposed
    TRANSPARENT:    The proxy does not hide the requester's IP address.
    ANONYMOUS:      The proxy hides the requester's IP address, but adds headers to the
                    forwarded request that make it clear that the request was made using
                    a proxy.
    ELITE:          The proxy hides the requester's IP address and does not add any
                    proxy-related headers to the request.
    """

    UNKNOWN = 0   # default
    TRANSPARENT = 1, 'transparent', 'transparent proxy', 'LOW', 'NOA'
    ANONYMOUS = 2, 'anonymous', 'anonymous proxy', 'high-anonymous', 'ANM'
    ELITE = 3, 'elite', 'elite proxy', 'HIGH', 'Elite & Anonymous', 'HIA', 'A+H'

    def __new__(cls, int_value, *value_aliases):
        obj = object.__new__(cls)
        obj._value_ = int_value
        for alias in value_aliases:
            cls._value2member_map_[alias] = obj
        return obj

    @classmethod
    def get(cls, name):
        try:
            return cls(name)
        except ValueError:
            return cls.UNKNOWN


class _PremProxyParser(ProxyParserBase, PremProxyParser):

    def __init__(self, *args, **kwargs):
        PremProxyParser.__init__(self, *args, **kwargs)
        ProxyParserBase.__init__(self, *args, **kwargs)
        self.url += "/list/"

    def _parse_proxyList(self):
        # Parse all proxy pages -> format: /list/{num}.htm
        # Get the pageRange from the 'pagination' table
        page_set = self.get_pagination_set()
        logger.debug(f"Pages: {page_set}")
        # One JS unpacker per provider (not per page)
        self.js_unpacker = self.init_js_unpacker()

        for page in [choice(list(page_set))]:
            response = self._get(f"{self.get_url()}{page}")
            if not response.ok:
                # Could not parse ANY page - Let user know
                if not self.curr_proxy_list:
                    logger.warning(f"Proxy Provider url failed: {self.get_url()}")
                # Return proxies parsed so far
                return self.curr_proxy_list
            content = response.content
            soup = BeautifulSoup(content, "html.parser", from_encoding="iso-8859-1")

            table = soup.find("table", attrs={"id": "proxylistt"}).find('tbody')
            # The first tr contains the field names.
            # skip last 'Select All' row
            for row in table.find_all("tr")[:-1]:
                td_row = row.find("td")
                portKey = td_row.find('span', attrs={'class': True}).get('class')[0]
                port = self.js_unpacker.get_port(portKey)
                proxy_obj = self._create_proxy_object(row, port)
                self._handle_dataset_proxy(proxy_obj)

    def get_pagination_set(self):
        response = self._get()
        page_set = set()
        # Could not parse pagination page - Let user know
        if not response.ok:
            logger.warning(f"Proxy Provider url failed: {self.get_url()}")
            return page_set
        content = response.content
        self.soup = BeautifulSoup(content, "html.parser")
        for ultag in self.soup.find_all('ul', {'class': 'pagination'}):
            for litag in ultag.find_all('li'):
                page_ref = litag.a.get('href')
                # Skip current page '/list'
                if page_ref.endswith(('htm', 'html')):
                    page_set.add(page_ref)
                else:
                    page_set.add("")
        return page_set

    def _create_proxy_object(self, row, port):  # noqa
        for td_row in row.findAll("td"):
            if td_row.attrs['data-label'] == 'IP:port ':
                text = td_row.text.strip()
                ip = text.split(":")[0]
                if not UrlParser.valid_ip(ip):
                    logger.debug("IP with Invalid format: {}".format(ip))
                    return None
            elif td_row.attrs['data-label'] == 'Anonymity Type: ':
                anonymity = _AnonymityLevelCustom.get(td_row.text.strip())
            elif td_row.attrs['data-label'] == 'Country: ':
                country = td_row.text.strip()
            protocols = [Protocol.HTTPS]
        return ProxyObjectCustom(
            self.id, ip, port, anonymity, country=country, protocols=protocols  # noqa
        )


class JsUnPackerCustom(JsUnPacker):
    def __init__(self, js_file_url: str = None, script=None):  # noqa
        if script is None:
            logger.info(f"JS UnPacker init path: {js_file_url}")
            r = get_request(
                js_file_url, headers={'User-Agent': _get_recent_common_user_agent()}
            )
            script = r.text
        encrypted = script.strip()
        self.encrypted = '(' + encrypted.split('}(')[1][:-1]
        self.unpacked = eval('self.unpack' + self.encrypted)
        self.matches = findall(
            r".*?\('\.([a-zA-Z0-9]{1,6})'\).*?\((\d+)\)", self.unpacked
        )
        self.ports = dict((key, port) for key, port in self.matches)
        logger.debug('portmap: ' + str(self.ports))


co_map = {
    'Afghanistan': 'AF',
    'Albania': 'AL',
    'Algeria': 'DZ',
    'American Samoa': 'AS',
    'Andorra': 'AD',
    'Angola': 'AO',
    'Anguilla': 'AI',
    'Antarctica': 'AQ',
    'Antigua and Barbuda': 'AG',
    'Argentina': 'AR',
    'Armenia': 'AM',
    'Aruba': 'AW',
    'Australia': 'AU',
    'Austria': 'AT',
    'Azerbaijan': 'AZ',
    'Bahamas': 'BS',
    'Bahrain': 'BH',
    'Bangladesh': 'BD',
    'Barbados': 'BB',
    'Belarus': 'BY',
    'Belgium': 'BE',
    'Belize': 'BZ',
    'Benin': 'BJ',
    'Bermuda': 'BM',
    'Bhutan': 'BT',
    'Bolivia, Plurinational State of': 'BO',
    'Bonaire, Sint Eustatius and Saba': 'BQ',
    'Bosnia and Herzegovina': 'BA',
    'Botswana': 'BW',
    'Bouvet Island': 'BV',
    'Brazil': 'BR',
    'British Indian Ocean Territory': 'IO',
    'Brunei Darussalam': 'BN',
    'Bulgaria': 'BG',
    'Burkina Faso': 'BF',
    'Burundi': 'BI',
    'Cambodia': 'KH',
    'Cameroon': 'CM',
    'Canada': 'CA',
    'Cape Verde': 'CV',
    'Cayman Islands': 'KY',
    'Central African Republic': 'CF',
    'Chad': 'TD',
    'Chile': 'CL',
    'China': 'CN',
    'Christmas Island': 'CX',
    'Cocos (Keeling) Islands': 'CC',
    'Colombia': 'CO',
    'Comoros': 'KM',
    'Congo': 'CG',
    'Congo, the Democratic Republic of the': 'CD',
    'Cook Islands': 'CK',
    'Costa Rica': 'CR',
    'Country name': 'Code',
    'Croatia': 'HR',
    'Cuba': 'CU',
    'Curaçao': 'CW',
    'Cyprus': 'CY',
    'Czech Republic': 'CZ',
    "Côte d'Ivoire": 'CI',
    'Denmark': 'DK',
    'Djibouti': 'DJ',
    'Dominica': 'DM',
    'Dominican Republic': 'DO',
    'Ecuador': 'EC',
    'Egypt': 'EG',
    'El Salvador': 'SV',
    'Equatorial Guinea': 'GQ',
    'Eritrea': 'ER',
    'Estonia': 'EE',
    'Ethiopia': 'ET',
    'Falkland Islands (Malvinas)': 'FK',
    'Faroe Islands': 'FO',
    'Fiji': 'FJ',
    'Finland': 'FI',
    'France': 'FR',
    'French Guiana': 'GF',
    'French Polynesia': 'PF',
    'French Southern Territories': 'TF',
    'Gabon': 'GA',
    'Gambia': 'GM',
    'Georgia': 'GE',
    'Germany': 'DE',
    'Ghana': 'GH',
    'Gibraltar': 'GI',
    'Greece': 'GR',
    'Greenland': 'GL',
    'Grenada': 'GD',
    'Guadeloupe': 'GP',
    'Guam': 'GU',
    'Guatemala': 'GT',
    'Guernsey': 'GG',
    'Guinea': 'GN',
    'Guinea-Bissau': 'GW',
    'Guyana': 'GY',
    'Haiti': 'HT',
    'Heard Island and McDonald Islands': 'HM',
    'Holy See (Vatican City State)': 'VA',
    'Honduras': 'HN',
    'Hong Kong': 'HK',
    'Hungary': 'HU',
    'ISO 3166-2:GB': '(.uk)',
    'Iceland': 'IS',
    'India': 'IN',
    'Indonesia': 'ID',
    'Iran, Islamic Republic of': 'IR',
    'Iraq': 'IQ',
    'Ireland': 'IE',
    'Isle of Man': 'IM',
    'Israel': 'IL',
    'Italy': 'IT',
    'Jamaica': 'JM',
    'Japan': 'JP',
    'Jersey': 'JE',
    'Jordan': 'JO',
    'Kazakhstan': 'KZ',
    'Kenya': 'KE',
    'Kiribati': 'KI',
    "Korea, Democratic People's Republic of": 'KP',
    'Korea, Republic of': 'KR',
    'Kuwait': 'KW',
    'Kyrgyzstan': 'KG',
    "Lao People's Democratic Republic": 'LA',
    'Latvia': 'LV',
    'Lebanon': 'LB',
    'Lesotho': 'LS',
    'Liberia': 'LR',
    'Libya': 'LY',
    'Liechtenstein': 'LI',
    'Lithuania': 'LT',
    'Luxembourg': 'LU',
    'Macao': 'MO',
    'Macedonia, the former Yugoslav Republic of': 'MK',
    'Madagascar': 'MG',
    'Malawi': 'MW',
    'Malaysia': 'MY',
    'Maldives': 'MV',
    'Mali': 'ML',
    'Malta': 'MT',
    'Marshall Islands': 'MH',
    'Martinique': 'MQ',
    'Mauritania': 'MR',
    'Mauritius': 'MU',
    'Mayotte': 'YT',
    'Mexico': 'MX',
    'Micronesia, Federated States of': 'FM',
    'Moldova, Republic of': 'MD',
    'Monaco': 'MC',
    'Mongolia': 'MN',
    'Montenegro': 'ME',
    'Montserrat': 'MS',
    'Morocco': 'MA',
    'Mozambique': 'MZ',
    'Myanmar': 'MM',
    'Namibia': 'NA',
    'Nauru': 'NR',
    'Nepal': 'NP',
    'Netherlands': 'NL',
    'New Caledonia': 'NC',
    'New Zealand': 'NZ',
    'Nicaragua': 'NI',
    'Niger': 'NE',
    'Nigeria': 'NG',
    'Niue': 'NU',
    'Norfolk Island': 'NF',
    'Northern Mariana Islands': 'MP',
    'Norway': 'NO',
    'Oman': 'OM',
    'Pakistan': 'PK',
    'Palau': 'PW',
    'Palestine, State of': 'PS',
    'Panama': 'PA',
    'Papua New Guinea': 'PG',
    'Paraguay': 'PY',
    'Peru': 'PE',
    'Philippines': 'PH',
    'Pitcairn': 'PN',
    'Poland': 'PL',
    'Portugal': 'PT',
    'Puerto Rico': 'PR',
    'Qatar': 'QA',
    'Romania': 'RO',
    'Russian Federation': 'RU',
    'Rwanda': 'RW',
    'Réunion': 'RE',
    'Saint Barthélemy': 'BL',
    'Saint Helena, Ascension and Tristan da Cunha': 'SH',
    'Saint Kitts and Nevis': 'KN',
    'Saint Lucia': 'LC',
    'Saint Martin (French part)': 'MF',
    'Saint Pierre and Miquelon': 'PM',
    'Saint Vincent and the Grenadines': 'VC',
    'Samoa': 'WS',
    'San Marino': 'SM',
    'Sao Tome and Principe': 'ST',
    'Saudi Arabia': 'SA',
    'Senegal': 'SN',
    'Serbia': 'RS',
    'Seychelles': 'SC',
    'Sierra Leone': 'SL',
    'Singapore': 'SG',
    'Sint Maarten (Dutch part)': 'SX',
    'Slovakia': 'SK',
    'Slovenia': 'SI',
    'Solomon Islands': 'SB',
    'Somalia': 'SO',
    'South Africa': 'ZA',
    'South Georgia and the South Sandwich Islands': 'GS',
    'South Sudan': 'SS',
    'Spain': 'ES',
    'Sri Lanka': 'LK',
    'Sudan': 'SD',
    'Suriname': 'SR',
    'Svalbard and Jan Mayen': 'SJ',
    'Swaziland': 'SZ',
    'Sweden': 'SE',
    'Switzerland': 'CH',
    'Syrian Arab Republic': 'SY',
    'Taiwan, Province of China': 'TW',
    'Tajikistan': 'TJ',
    'Tanzania, United Republic of': 'TZ',
    'Thailand': 'TH',
    'Timor-Leste': 'TL',
    'Togo': 'TG',
    'Tokelau': 'TK',
    'Tonga': 'TO',
    'Trinidad and Tobago': 'TT',
    'Tunisia': 'TN',
    'Turkey': 'TR',
    'Turkmenistan': 'TM',
    'Turks and Caicos Islands': 'TC',
    'Tuvalu': 'TV',
    'Uganda': 'UG',
    'Ukraine': 'UA',
    'United Arab Emirates': 'AE',
    'United Kingdom': 'GB',
    'United States': 'US',
    'United States Minor Outlying Islands': 'UM',
    'Uruguay': 'UY',
    'Uzbekistan': 'UZ',
    'Vanuatu': 'VU',
    'Venezuela, Bolivarian Republic of': 'VE',
    'Viet Nam': 'VN',
    'Virgin Islands, British': 'VG',
    'Virgin Islands, U.S.': 'VI',
    'Wallis and Futuna': 'WF',
    'Western Sahara': 'EH',
    'Yemen': 'YE',
    'Zambia': 'ZM',
    'Zimbabwe': 'ZW',
    'Åland Islands': 'AX'
}
