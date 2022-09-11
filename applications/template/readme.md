# Template application

Template files and instructions for facilitating the creation of custom scrapers.


<br>

# Instructions

1) Supply the url to be scraped and the selector of the website element to be scraped into the `check` dictionary in `Config`. 
   - To obtain the item selector, right-click the element in your browser and select **inspect**, then right-click the element in the inspection widget and select **copy css selector** or **copy full xpath**.


2) Ensure that the `mail_info` attribute in the `Config` class contains the following attributes:
   - `addr`: gmail address with working application password. See [google help](https://support.google.com/accounts/answer/185833?hl=en) for the steps in setting application passwords.
   - `app_pw`: application password.


3) Change the pre-supplied runtime configuration in `Config` to your needs.


4) Define how the browser obtains the text, and possible images, to be scraped in `Browser._check_update_of_url()`. Code section [here](/applications/template/browser.py#L27-L32).


5) Define how the main scraper class passes the scraped data from the browser to the mailer class in `TemplateScraper._check_update_of_url()`. Code section [here](/applications/template/main.py#L122-L127). 


6) Define how the mailer creates the email body from the received data in `Mailer._make_msg()`. Code section [here](/applications/template/mailer.py#L34-L37).


7) Run the [/template/main.py](/applications/template/main.py) script.



<br>

## File structure

- [browser.py](/applications/template/browser.py) contains browser classes utilizing either `puppeteer` (Chromium) or `selenium` (Firefox) libraries.

- [main.py](/applications/template/main.py) contains  `Config` and `TemplateScraper` class.

- [mailer.py](/applications/template/mailer.py)  contains `Mailer` class.

- [make_executable.py](/applications/template/make_executable.py)  contains `PyInstaller` class. Running this script automatically creates an executable of the program to be run as a standalone package without Python.
  - If the custom program requires use of other custom data files: The path to these must be supplied in the `PyInstaller._local_files` attribute to allow for bundling of those files with the created standalone program.
  - `--onefile` script argument: Generates a single executable file. See [/applications/PyInstaller/main.py](/applications/PyInstaller/main.py#L31-L48) for other PyInstaller options.