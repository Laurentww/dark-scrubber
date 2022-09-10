
from distutils.sysconfig import get_config_var, get_python_lib
from glob import glob
from os import remove
from os.path import splitext
from pathlib import Path
from shutil import rmtree
from typing import Iterable, List

cur_dir = Path(__file__).parent
pyinstaller_path = Path(get_config_var('srcdir')).joinpath('pyinstaller')


def prune_python_environment():
    _remove_pckgs = [
        ('lxml', 'etree.*.pyd'),
        ('lxml', 'objectify.*.pyd'),
        ('PIL', '_imagingft.*.pyd'),
        ('PIL', '_webp.*.pyd'),
        ('zstandard', 'cffi.*.pyd'),
    ]

    lib_path = get_python_lib()
    for file_tuple in _remove_pckgs:
        for file_path in glob(str(Path(lib_path).joinpath(*file_tuple))):
            remove_f(Path(file_path))


def remove_f(item: Path):
    if item.exists():
        (rmtree if item.is_dir() else remove)(item)


def _flatten(lst):

    """ Flattens Python lists

    Contents of lists will be merged, e.g: [[...],[...]] -> [...]

    Parameters
    ----------
    lst : Iterable
        Can contain lists or other types

    Returns
    -------
    ret_list : List
        flattened `lst`

    """

    if not isinstance(lst, Iterable):
        return lst

    ret_lst = []
    for i in lst:
        ret_lst += i

    return ret_lst


def insert_suffix(name, x):

    """ Helper function to add a suffix to a file before the file type indicator

    Agnostic of .'s in the directory names

    Parameters
    ----------
    name : str
        Name or full path of file

    x : str | int
        suffix to be added to file

    Returns
    -------
    str
        suffixed `name`


    Examples
    --------
    >>> insert_suffix('/full/path/with.points/name.dat', 'suff1')
    '/full/path/with.points/name_suff1.dat'

    """
    if x:
        prefix = '_' if str(x)[0] != '_' else ''
        return (prefix + str(x)).join(splitext(name))

    return name


def merge_recursive(a, b):
    for key in b:
        if key in a:
            if isinstance(a[key], dict) and isinstance(b[key], dict):
                merge_recursive(a[key], b[key])
            elif a[key] != b[key]:
                a[key] = a[key] + b[key]
        else:
            a[key] = b[key]
    return a
