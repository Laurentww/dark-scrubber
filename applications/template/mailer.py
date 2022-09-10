
from lib.mailer import Mailer as Mailer_base


class Mailer(Mailer_base):

    # Default width in pixels of images added to mail body (using `self._inline_img()`)
    resize_img_width = None

    def _make_msg(self, *args, **kwargs):
        """ Defines the email message body and saves it into `self.msg`

        must also set `self.msg_html`

        Parameters
        ----------
        args
            optional arguments needed to set `self.msg` and `self.msg_html`

        kwargs
            optional keyword arguments needed to set `self.msg` and `self.msg_html`

        Returns
        -------
        -
        """

        text = kwargs["text"]

        ########################################
        #  * Handling of text to email body *  #
        ########################################

        # for img_idx, image_url in enumerate(kwargs["images"]):
        #     text = self._inline_img(image_url, f'img_{img_idx}', msg_html=text)

        self.msg_html = self._make_msg_html(text)
