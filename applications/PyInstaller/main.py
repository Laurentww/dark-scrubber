
from abc import ABC, abstractmethod
from argparse import ArgumentParser
from distutils.sysconfig import get_python_lib
from os import remove, sep, getcwd, chdir, makedirs
from pathlib import Path
from shutil import copytree, copyfile, SameFileError, rmtree, ignore_patterns
from sys import argv
from time import sleep
from typing import Union, Type

# Ensure that the working directory is the main program directory
_main_dir = Path(getcwd())
while not _main_dir.joinpath('requirements.txt').is_file():
    if not hasattr(_main_dir, 'parents'):
        raise RuntimeError(
            f'{Path(argv[0]).name} must be located in a sub folder of this project'
        )
    _main_dir = _main_dir.parent
    chdir(_main_dir)

import PyInstaller.__main__ as pyinstaller
from PyInstaller.building.makespec import main as make_spec

from lib.utils import main_path
from lib.proxy_utils import ua_pckl_file_name
from lib.proxy import ProxyRequester
from lib.mailer import Mailer
from .utils import prune_python_environment, insert_suffix, merge_recursive, remove_f

parser = ArgumentParser(
    description='Script to generate an executable of the Python program.'
)
parser.add_argument('--spec', type=str, help="PyInstaller spec file")
parser.add_argument('--dist_name', type=str, help="Rename dist folder to")
parser.add_argument(
    '--onefile', action='store_true', help="Compile into one executable file"
)
parser.add_argument(
    '--nosession', action='store_true', help="Do not copy existing browser session"
)
parser.add_argument(
    '--prune_python_env',
    action='store_true',
    help=
    "Make Python environment smaller by deleting unused files. "
    "Reduces application size."
)

_global_files = {
    sep.join(Mailer.htmls_subfolders): [],  # copy all files in /shared/htmls/*
}
_local_files_default = {
    'main': [ua_pckl_file_name] + list(ProxyRequester.filenames.values())
}


class PyInstallerBase(ABC):

    _target_dir: Union[Path, None] = None
    _copy_browser_session: bool = False

    _app_name_suffix = 'scraper'

    _icons_subfolder_name = 'icons'
    _icon_file_name = 'scraper2.ico'

    def __init__(self, installer_args):
        self._args = installer_args

        self._script_caller = Path(argv[0])
        self._target_dir = self._script_caller.parent

        self._dist_folder_path = self._target_dir.joinpath((
                self._args.dist_name
                or insert_suffix('dist', 'onefile' if self._args.onefile else '')
        ))
        self._build_folder_path = self._target_dir.joinpath(insert_suffix(
            'build', 'onefile' if self._args.onefile else ''
        ))

    def run(self):

        if self._args.prune_python_env:
            prune_python_environment()

        # Remove possible pre-existing PyInstaller dist folder
        prev_dist_folder = self._target_dir.joinpath(self._dist_folder_path)
        while prev_dist_folder.is_dir():
            try:
                rmtree(prev_dist_folder)
                break
            except PermissionError:
                print(
                    'Got permission error while deleting ' +
                    str(prev_dist_folder.relative_to(_main_dir)) +
                    ', trying again ..'
                )
                sleep(1)

        # Generate PyInstaller .spec file
        _script_caller_filename = str(self._script_caller.name)
        _pyinstaller_script_path = _main_dir.joinpath(_script_caller_filename)

        copyfile(self._script_caller, _pyinstaller_script_path)

        _icon_path_full = (
            Path(__file__).parent.joinpath(self._icons_subfolder_name)
            .relative_to(_main_dir).joinpath(self._icon_file_name)
        )
        datas = (
                self._handle_copy_files(_global_files)
                + self._handle_copy_files()
                + [(str(_icon_path_full), self._icons_subfolder_name)]
        )
        make_spec(
            [_script_caller_filename],
            name=self._app_name,
            onefile=self._args.onefile,
            # console=False,
            # debug=['imports'],  # or ['all']
            python_options=['-OO'],  # python runtime options for script  ~has no effect
            upx=True,
            # pathex=[],  # additional paths to look for dependencies
            # specpath=str(self._target_dir),
            datas=datas,
            icon_file=_icon_path_full,
            # resources=[],
            # hiddenimports=['pyppeteer'],  # does require hookspath to be set
            # collect_submodules=['pyppeteer'],  # does not work
            # hookspath=[],
            # excludes=[],
        )
        _spec_basename = f"{self._app_name}.spec"
        _spec_filepath = _main_dir.joinpath(_spec_basename)   # must be in main dir

        # Main script and spec file must be located in main dir
        assert _main_dir.joinpath(_script_caller_filename).is_file()
        assert _main_dir.joinpath(_spec_basename).is_file()

        # Perform PyInstaller packaging
        pyinstaller.run([
            str(_spec_filepath),
            '-y',
            '--clean',
            '--distpath', str(self._dist_folder_path),
            '--workpath', str(self._build_folder_path),
        ])
        sleep(2)

        if self._args.onefile:
            # Copy data files separately
            for file_tup in datas:
                if self._icons_subfolder_name not in file_tup[0]:  # ignore icons
                    dest_dir = self._dist_folder_path.joinpath(file_tup[1])
                    makedirs(dest_dir, exist_ok=True)
                    copyfile(file_tup[0], dest_dir.joinpath(file_tup[0].split(sep)[-1]))

        else:
            # Copy pyppeteer site-packages folder into dist folder
            pckg = 'pyppeteer'
            src = Path(get_python_lib()).joinpath(pckg)
            d = self._dist_folder_path.joinpath(self._app_name, pckg)
            copytree(src, d, ignore=ignore_patterns('__pycache__'), dirs_exist_ok=True)

        # Remove copied python files and PyInstaller build folder
        for file_path in [
            self._build_folder_path, _pyinstaller_script_path, _spec_filepath
        ]:
            # file_path = self._target_dir.joinpath(file)
            del_func = rmtree if file_path.is_dir() else remove
            try:
                del_func(file_path)
            except FileNotFoundError:
                pass

        # Copy browser files if existing
        if self._copy_browser_session:
            morefiles_src_dir = prev_dist_folder.joinpath(self._app_name)
            target_dir = (
                morefiles_src_dir if morefiles_src_dir.is_dir()
                else self._dist_folder_path
            )
            session_folder = []
            if not self._args.nosession:
                session_folder = [
                    i for i in self._target_dir.iterdir() if i.name.endswith('_session')
                ]
            self._copy_files(['browser_id'] + session_folder, target_dir)

        # Remove folders from dist which are not used. Saves disk space,
        for folder in [('tcl', 'tzdata')]:
            remove_f(self._dist_folder_path.joinpath(self._app_name, *folder))

    def _copy_files(self, file_list, target_dir):
        for file in file_list:
            file_path = self._target_dir.joinpath(file)
            copy_func = copytree if file_path.is_dir() else copyfile
            try:
                copy_func(file_path, target_dir.joinpath(file))
            except (FileExistsError, SameFileError):
                pass

    def _handle_copy_files(self, files_to_copy=None):
        path_str = '.'
        if files_to_copy is None:
            # Assume files are defined from local application folder
            files_to_copy = merge_recursive(self._local_files, _local_files_default)
            path_get = lambda file: main_path(file, self._script_caller)
            # path_str = str(self._target_dir.relative_to(_main_dir))
            path_prefix = path_str + sep
        else:
            path_get = main_path
            path_prefix = ''

        datas = []
        for key, value in files_to_copy.items():
            if key == 'main':
                # in main folder
                datas += [(path_get(file), path_str) for file in value]

            elif value:
                # in sub-folder
                datas += [
                    (path_get(key).joinpath(file), path_prefix + key) for file in value
                ]

            else:
                targ_dir = path_get(key)
                if targ_dir.exists():
                    # empty list; add all containing files
                    datas += [
                        (targ_dir.joinpath(f), path_prefix + key)
                        for f in targ_dir.iterdir()
                    ]

        datas = [
            (str(t[0].relative_to(_main_dir)), t[1]) for t in datas if t[0].is_file()
        ]

        return datas

    @property
    @abstractmethod
    def _local_files(self):
        pass

    @property
    @abstractmethod
    def _app_name(self):
        pass


def pyinstaller_runner(py_installer: Type[PyInstallerBase], main_class):
    if main_class.is_binary:
        scraper = main_class()
        scraper.debug = False
        scraper.mailer.debug = False
        scraper.driver._headless = True
        scraper.run()

    else:
        py_installer(parser.parse_args()).run()
