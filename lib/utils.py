
from pathlib import Path
from pickle import dump, load
from sys import argv
from urllib.parse import urlsplit, urlparse

from psutil import Process, NoSuchProcess, process_iter
from pyppeteer.network_manager import statusTexts

# logging.getLogger().setLevel(logging.WARNING)

shared_subfolder_name = 'shared'


def write_pckl(file, data):
    with open(file, "wb") as fo:
        dump(data, fo)


def read_pckl(file):
    with open(file, "rb") as file_in:
        data = load(file_in)
    return data


def _kill_catch_proc(proc: Process):
    try:
        proc.kill()
    except NoSuchProcess:
        pass


def kill_proc_recursive(proc):
    proc = Process(proc) if isinstance(proc, int) else proc

    # or parent.children() for recursive=False
    for child in proc.children(recursive=True):
        _kill_catch_proc(child)
    _kill_catch_proc(proc)


def kill_firefox_proc(match_terms=None):
    try:
        for proc in process_iter():
            p_str = proc.name().lower()
            p_matched = ('gecko' in p_str and 'driver' in p_str) \
                        or any(x in p_str for x in list(match_terms))
            if p_matched:
                kill_proc_recursive(proc)
    except Exception as e:
        print('Ignoring process killing exception:', str(e))


def kill_chromedriver_proc():
    try:
        for proc in process_iter():
            p_str = proc.name().lower()
            p_matched = ('chrome' in p_str and 'driver' in p_str) or \
                        ('chromium' in p_str and 'browser' in p_str)
            if p_matched:
                kill_proc_recursive(proc)
    except Exception as e:
        print('Ignoring process killing exception:', str(e))


def make_printable(url, thres=50):
    if len(url) > thres:
        url = ''.join(urlsplit(url)[1:3]) + '/... (shortened)'
    return f"{url}"


def code_ok(status_code: int):
    if status_code == 409:
        print("HTTP Response [409] - Possible DNS resolution error")
    elif status_code // 100 in [3, 4]:
        print(
            f'HTTP Response: [{status_code}] - {statusTexts[str(status_code)]} error'
        )
    elif status_code == 512:
        pass  # custom code; 512 not an official http status code
    elif status_code != 200:
        print(f'HTTP Response: [{str(status_code)}] - Not accepted')

    return status_code == 200


def is_uri(uri):
    try:
        result = urlparse(uri)
        return all([result.scheme, result.netloc])
    except:
        return False


def main_path(file=None, cur_file=None, relative_dir=None):
    """ Returns full or relative path to `file` inside either main folder of this
    project (default) or same folder as `cur file`.

    Parameters
    ----------
    file : str
        Target file name

    cur_file : str | Path
        Full path to other file of which `file` will be placed in same folder. If given,
        overrides main folder of this project.

    relative_dir : str | Path
        If given: Full path to which output must be relative to

    Returns
    -------
    Path
        Path to `file` in selected folder

    """

    path = Path(cur_file or __file__).parent

    if cur_file is None:
        path = path.parent

    if file is None:
        return path

    out_path = path.joinpath(file)
    if relative_dir:
        out_path = out_path.relative_to(relative_dir)
    return out_path


script_dir = Path(argv[0]).parent
