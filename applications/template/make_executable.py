#!/usr/bin/env python3

# Used as file to generate standalone executable of program using PyInstaller

from applications.template.main import Config, TemplateScraper
from applications.PyInstaller import PyInstallerBase, pyinstaller_runner


class PyInstaller(PyInstallerBase):

    @property
    def _local_files(self):
        """ Select which non-python files in this folder are required for running
        this program

        Note: if list of sub folder is empty: selects all files within the folder

        Returns
        -------
        dict[list]
            {`sub-folder name`: `list of files in sub-folder needed for program`}
        """

        return {
            # 'main': [],  # from this main folder
            # 'htmls': [],  # from `htmls` sub-folder in this main folder
        }

    @property
    def _app_name(self):
        """ Name given to the packaged application """
        return Config.class_name.replace(' ', '_').lower()


if __name__ == '__main__':
    pyinstaller_runner(PyInstaller, TemplateScraper)

