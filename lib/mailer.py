
from abc import ABC, abstractmethod
from difflib import ndiff
from email.mime.image import MIMEImage
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formatdate, formataddr
from io import BytesIO
from smtplib import SMTP
from textwrap import dedent
from typing import Union
from urllib.parse import urlsplit, urlparse
# from urllib.request import urlopen
from warnings import filterwarnings

from PIL import Image
from requests import get as get_url
from requests.exceptions import InvalidSchema, MissingSchema

from config_base import ConfigBase
from .utils import main_path, shared_subfolder_name, script_dir

filterwarnings(action="ignore", message="LANCZOS is deprecated", module='Pillow')


class Mailer(ABC):

    mail_html_template_file = 'mail-html-template.html'

    htmls_subfolder = 'htmls'
    htmls_subfolders = (shared_subfolder_name, htmls_subfolder)

    # Quality value of images sent in email  ~reduces email size
    quality_val: int = 90

    resize_img_width: int = 0

    _color_dict = {'-': 'red', '+': 'green'}
    # _color_dict = {'+': 'red', '-': 'green'}
    _color_dict_reversed = {value: key for key, value in _color_dict.items()}
    _color_hex_map = {'green': '#02b539', 'red': '#f05e32'}

    # Placeholders
    url: str = None
    msg: Union[MIMEText, MIMEMultipart] = None
    msg_html: str = None

    def __init__(self, logger, config: ConfigBase, debug: bool):
        self.logger = logger
        self.config = config
        self.debug = debug

        self.addr = config.mail_info['addr']
        self.pw = config.mail_info['app_pw']

        with open(self._shared_html_folder(self.mail_html_template_file), 'r') as rf:
            self.msg_html_base = rf.read()

    def _send_email(self, subject_suffix=''):

        self.msg['Subject'] = f"{self.config.class_name} {subject_suffix}"
        self.msg['From'] = formataddr((f"{self.config.class_name} Listener", self.addr))
        self.msg['To'] = self.addr
        self.msg['Date'] = formatdate()

        if self.debug:
            self.logger.debug(f"Sending mail:\n\n{self.msg.as_string()}")

        else:
            server = SMTP(host="smtp.gmail.com:587")
            server.starttls()
            server.login(self.addr, self.pw)
            server.sendmail(self.addr, self.addr.split(", "), self.msg.as_string())
            server.quit()

    def send_startup(self):
        self._send_startstop('started')

    def send_shutdown(self):
        self._send_startstop('stopped')

    def _send_startstop(self, startstop_str):
        self.msg = MIMEText(
            mail_template_text %
            f'{self.config.class_name} update listener daemon has {startstop_str}'
        )
        self._send_email(subject_suffix=f"Scraper {startstop_str.title()}")

    def send_error(self, url, error, selector, error_msg=None):
        if error_msg is None:
            error_msg = (
                f"Site scraping error: \n{ensure_short_url(url)}, {selector}\n\n{error}"
            )

        self.msg = MIMEText(mail_template_text % error_msg)
        self._send_email()
        self.logger.error('Sent site scraping error mail')

    @abstractmethod
    def _make_msg(self, *args, **kwargs):
        """ Defines the email message body in `self.msg`

        must also set `self.msg_html`
        """
        pass

    def _make_msg_html(self, body_text):
        msg_html = self.msg_html_base.replace('{url}', self.url)
        msg_html = msg_html.replace('{class}', self.config.class_name)
        msg_html = msg_html.replace('sample_text', body_text)
        msg_html = msg_html.replace('\n', '<br>')
        return msg_html

    def send_update(self, url, *args, **kwargs):

        self.url = url

        self.msg = MIMEMultipart('related')
        msgAlternative = MIMEMultipart('alternative')
        self.msg.attach(msgAlternative)

        self._make_msg(*args, **kwargs)

        msgAlternative.attach(MIMEText(self.msg_html, 'html'))

        # # debug html
        # with open(main_path('msg_html.html'), 'w') as wf:
        #     wf.write(self.msg_html)

        self._send_email()
        self.logger.info(f'Sent updated site mail {self._second_lvl_dom}')

    @property
    def _second_lvl_dom(self):
        d_str = str(urlsplit(self.url).netloc.rsplit('.', 1)[0]).split('.')[-1].title()
        return "| " + d_str if d_str else ""

    def _local_html_folder(self, f):
        return script_dir.joinpath(self.htmls_subfolder).joinpath(f)

    def _shared_html_folder(self, f, cur_file=None):
        return main_path(cur_file=cur_file).joinpath(*self.htmls_subfolders).joinpath(f)

    def _inline_img(self, image_url, cid, msg_html: str = None, img_width: int = None):
        """ Appends an image onto `self.msg` """

        url_fmt = str(urlparse(image_url).path.split('.')[-1])
        fmt = {'jpg': 'jpeg'}.get(url_fmt, url_fmt)

        memf = BytesIO()
        try:
            # img = Image.open(urlopen(image_url)).save(memf, fmt)
            img = Image.open(BytesIO(get_url(image_url).content))
        except (InvalidSchema, MissingSchema):
            return msg_html

        img_width = img_width or self.resize_img_width
        assert img_width

        if msg_html:
            msg_html += f'<img src="cid:{cid}" width={img_width} height=auto ><br>'

        img = self._resize_img(img, img_width)
        img.save(memf, fmt, quality=self.quality_val)

        msg_image = MIMEImage(memf.getvalue())

        msg_image.add_header('Content-ID', f'<{cid}>')
        msg_image.add_header('Content-Disposition', 'inline', filename=f'{cid}.{fmt}')
        self.msg.attach(msg_image)

        return msg_html

    def _resize_img(self, img, img_width: int = None):
        img_width = int(img_width or self.resize_img_width)
        return img.resize(
            (img_width, int(img.size[1] * (img_width / img.size[0]))), Image.LANCZOS
        )

    def _parse_color(self, i, s, diff_res, color_str, color_bg=True):
        color_str = self._color_dict[color_str]
        color_sign = self._color_dict_reversed[color_str]

        color_change_str = 'style="background-color:' if color_bg else 'color="'
        color_hex = self._color_hex_map[color_str] if color_bg else color_str

        # start and end of list edge cases
        if i == 0:
            return f'<font {color_change_str}{color_hex}">' + s
        elif i + 1 == len(diff_res):
            return s + '</font>'

        elif diff_res[i - 1][0] != color_sign and diff_res[i + 1][0] == color_sign:
            return f'<font {color_change_str}{color_hex}">' + s
        elif diff_res[i + 1][0] != color_sign:
            return s + '</font>'

        return s

    def _get_diff_html(self, old_str, new_str):
        """ Returns html text of the difference between `old_str` and `new_str`.
        New parts are marked in green and removed parts in red.
        """
        html_diff = ''
        diff = [i for i in ndiff(old_str, new_str)]
        for i, s in enumerate(diff):
            diff_i = s[-1] if s[0] == ' ' else self._parse_color(i, s[-1], diff, s[0])
            html_diff += diff_i

        html_diff = html_diff.strip().strip('\n').strip()

        return html_diff


def ensure_short_url(url):
    if len(url) > 50:
        url_parts = urlsplit(url)
        url = f'<a href="{url}">{url_parts.hostname}{url_parts.path}</a>'
    return url


mail_template_text = dedent((
    """
    Hi,
    
    %s
    
    
    Regards,
    Yourself 
    """
).lstrip('\n'))
