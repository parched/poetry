from __future__ import unicode_literals

import os
import site

from functools import cmp_to_key
from pathlib import Path
from typing import TYPE_CHECKING

from cleo.helpers import argument
from cleo.helpers import option

from ..command import Command


if TYPE_CHECKING:
    from poetry.core.packages.package import Package
    from poetry.core.semver.version import Version
    from poetry.repositories.pool import Pool


BIN = """# -*- coding: utf-8 -*-
import glob
import sys
import os

lib = os.path.normpath(os.path.join(os.path.realpath(__file__), "../..", "lib"))
vendors = os.path.join(lib, "poetry", "_vendor")
current_vendors = os.path.join(
    vendors, "py{}".format(".".join(str(v) for v in sys.version_info[:2]))
)
sys.path.insert(0, lib)
sys.path.insert(0, current_vendors)

if __name__ == "__main__":
    from poetry.console import main
    main()
"""

BAT = '@echo off\r\n{python_executable} "{poetry_bin}" %*\r\n'


class SelfUpdateCommand(Command):

    name = "self update"
    description = "Updates Poetry to the latest version."

    arguments = [argument("version", "The version to update to.", optional=True)]
    options = [option("preview", None, "Install prereleases.")]

    _data_dir = None
    _bin_dir = None
    _pool = None

    @property
    def data_dir(self) -> Path:
        if self._data_dir is not None:
            return self._data_dir

        from poetry.locations import user_data_dir

        if os.getenv("POETRY_HOME"):
            return Path(os.getenv("POETRY_HOME")).expanduser()

        self._data_dir = Path(user_data_dir("pypoetry", roaming=True))

        return self._data_dir

    @property
    def bin_dir(self) -> Path:
        if self._data_dir is not None:
            return self._data_dir

        from poetry.utils._compat import WINDOWS

        if os.getenv("POETRY_HOME"):
            return Path(os.getenv("POETRY_HOME"), "bin").expanduser()

        user_base = site.getuserbase()

        if WINDOWS:
            bin_dir = os.path.join(user_base, "Scripts")
        else:
            bin_dir = os.path.join(user_base, "bin")

        self._bin_dir = Path(bin_dir)

        return self._bin_dir

    @property
    def pool(self) -> "Pool":
        if self._pool is not None:
            return self._pool

        from poetry.repositories.pool import Pool
        from poetry.repositories.pypi_repository import PyPiRepository

        pool = Pool()
        pool.add_repository(PyPiRepository())

        return pool

    def handle(self) -> int:
        from poetry.__version__ import __version__
        from poetry.core.packages.dependency import Dependency
        from poetry.core.semver.version import Version

        version = self.argument("version")
        if not version:
            version = ">=" + __version__

        repo = self.pool.repositories[0]
        packages = repo.find_packages(
            Dependency("poetry", version, allows_prereleases=self.option("preview"))
        )
        if not packages:
            self.line("No release found for the specified version")
            return 1

        packages.sort(
            key=cmp_to_key(
                lambda x, y: 0
                if x.version == y.version
                else int(x.version < y.version or -1)
            )
        )

        release = None
        for package in packages:
            if package.is_prerelease():
                if self.option("preview"):
                    release = package

                    break

                continue

            release = package

            break

        if release is None:
            self.line("No new release found")
            return 1

        if release.version == Version.parse(__version__):
            self.line("You are using the latest version")
            return 0

        self.line("Updating to <info>{}</info>".format(release.version))
        self.line("")

        self.update(release)

        self.line("")
        self.line(
            "<info>Poetry</info> (<comment>{}</comment>) is installed now. Great!".format(
                release.version
            )
        )

    def update(self, release: "Package") -> None:
        from poetry.utils.env import EnvManager

        version = release.version

        env = EnvManager.get_system_env()

        if env.path.is_relative_to(self.data_dir):
            # Poetry was installed using the recommended installer
            self._update(version)

            return 0
        else:
            # Another method was used to install Poetry so we try to install via pip
            env.run_pip("install", f"poetry=={release.version.text}", "-U")

    def _update(self, version: "Version") -> None:
        from poetry.config.config import Config
        from poetry.core.packages.dependency import Dependency
        from poetry.core.packages.project_package import ProjectPackage
        from poetry.installation.installer import Installer
        from poetry.packages.locker import NullLocker
        from poetry.repositories.installed_repository import InstalledRepository
        from poetry.utils.env import EnvManager

        env = EnvManager.get_system_env()
        installed = InstalledRepository.load(env)

        root = ProjectPackage("poetry-updater", "0.0.0")
        root.python_versions = ".".join(str(c) for c in env.version_info[:3])
        root.add_dependency(Dependency("poetry", version.text))

        installer = Installer(
            self.io,
            env,
            root,
            NullLocker(self.data_dir.joinpath("poetry.lock"), {}),
            self.pool,
            Config(),
            installed=installed,
        )
        installer.update(True)
        installer.dry_run(True)
        installer.run()
