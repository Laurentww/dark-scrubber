
# Dark Scrubber

## Features
- Scanning of multiple websites
- Updates sent by email 
- Anti-detection
  - Variable IP through use of proxy addresses
  - Variable check intervals
  - Usage of the [pyppeteer_stealth](https://github.com/MeiK2333/pyppeteer_stealth) package
- Packaging into standalone application using [PyInstaller](https://pyinstaller.org/en/stable/)
- Automatic update of web browser upon start and during runtime


# Installation

Tested working on Ubuntu 20.04 and Windows 10.

### Python environment
```
.. code-block:: console

   $ conda create --name site_scraper python=3.10
   $ <python> -m pip install -r requirements.txt
 ```

### Dependencies
See [requirements.txt](/requirements.txt)

<br>

# Configuration 

Main configuration is specified in [config_base.py](/config_base.py), which contains the base `Config` class.

### Template application

The [/applications/template/](/applications/template) folder contains template files and instructions for creating your own scraper.


### Sending emails

The scraper sends emails from the supplied email address to itself. For setting up the email functionality: Ensure that the `mail_info` attribute in the `Config` class contains the following attributes:
- `addr`: gmail address with working application password. See [google help](https://support.google.com/accounts/answer/185833?hl=en) for setting application passwords.
- `app_pw`: application password.


<br>

# File structure


- The `/applications/` directory contains various scraper applications:

    - [template](/applications/template): Boilerplate for creating your own scraper.

    - [PyInstaller](/applications/PyInstaller): Compiling binary executables of the programs.



<br>


- The `/lib/` directory contains python scripts for:

    - [scraper.py](/lib/scraper.py)  contains `Scraper` class.
      - Base scraper class.

    - [browser.py](/lib/browser.py)  contains `Browser`, `Puppeteer`, `SeleniumFireFox` classes.
      - Puppeteer uses Chromium, other uses the FireFox browser of the `selenium` package. 
      - `puppeteer-stealth` functionality only available when using the Puppeteer browser.

    - [proxy.py](/lib/proxy.py)  contains `ProxyRequester` class.
      - Performs proxy-related features.

    - [proxy_utils.py](/lib/proxy_utils.py)  contains proxy-utility classes.
      - Performs proxy-related features.

    - [mailer.py](/lib/mailer.py)  contains `Mailer` class.
      - Base mailer class.

    - [utils.py](/lib/utils.py)  contains shared functions.


<br>


- The `/htmls/` directory contains example .html files which are used in sending emails.





<br>


# Proxy functionality

Enable use of proxy functionality by setting `use_proxy=True` in the `Config` class.

### Features
- Scours the following websites for free proxies:
  - https://spys.one/free-proxy-list/
  - http://free-proxy-list.net
  - https://premproxy.com
  - https://www.sslproxies.org
- Assesses operating status of proxies before utilization. See `Config` class for testing parameters at [these lines](/config_base.py#L27-L59).
- Proxies can be filtered for source country. 
- Utilization of multiprocessing for retrieving and testing of new proxies to reduce time. 

<br>


# PyInstaller

Creates a standalone executable package of the scraper. Can be performed by running the `make_executable.py` script inside the application sub-folders.


- Notes: 
  - Creates an executable only compatible with the OS it is created in.
  - Run the `make_executable.py` script with `--onefile` argument to create a single executable file. Else, the packaged program folder will consist of, besides the target executable file, a collection of linked library files.
  - [UPX](https://upx.github.io/) can be used for compressing the compiled executable. Must be visible to PyInstaller by being in the `PATH` environment variable, or `--upx-dir` supplied to PyInstaller.

<br>


# Troubleshooting

When having trouble connecting on linux: 
- ensure in `/etc/hosts`: `127.0.0.1 localhost`

<br>

<br>


## Start on boot using systemctl daemon

The `/systemctl/` folder contains an example systemctl daemon configuration [file](/systemctl/example_scraper.service) which can be used to run this script automatically from boot on unix systems. The following code block displays how to enable the systemd service daemon. For more information, see the tutorial in [this link](https://www.shellhacks.com/systemd-service-file-example/).

```
.. code-block:: console

    $ /etc/systemd/system/example_scraper.service       # service file location
    $ systemctl start example_scraper                   # start service
    $ systemctl enable example_scraper                  # automatically start on boot
 ```


<br>


<br>


## Further development options
- Other methods of notification delivery integration
  - [Gotify](https://gotify.net/) / Pushbullet
  - Slack