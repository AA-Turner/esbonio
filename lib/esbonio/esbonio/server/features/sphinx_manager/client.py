from __future__ import annotations

import asyncio
import typing
from typing import Optional

import pygls.uris as Uri
from pygls.client import Client

from .config import SphinxConfig

if typing.TYPE_CHECKING:
    from .manager import SphinxManager


class SphinxClient(Client):
    """JSON-RPC client used to drive a Sphinx application instance hosted in
    a separate subprocess."""

    def __init__(self, manager: SphinxManager, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.manager = manager
        self.logger = manager.logger

        self.sphinx_info = None

    @property
    def src_dir(self) -> Optional[str]:
        """The src directory of the Sphinx application."""
        if self.sphinx_info is None:
            return None

        return self.sphinx_info.src_dir

    @property
    def src_uri(self) -> Optional[str]:
        """The src uri of the Sphinx application."""
        src_dir = self.src_dir
        if src_dir is None:
            return None

        return Uri.from_fs_path(src_dir)

    @property
    def conf_dir(self) -> Optional[str]:
        """The conf directory of the Sphinx application."""
        if self.sphinx_info is None:
            return None

        return self.sphinx_info.conf_dir

    @property
    def conf_uri(self) -> Optional[str]:
        """The conf uri of the Sphinx application."""
        conf_dir = self.conf_dir
        if conf_dir is None:
            return None

        return Uri.from_fs_path(conf_dir)

    @property
    def build_dir(self) -> Optional[str]:
        """The build directory of the Sphinx application."""
        if self.sphinx_info is None:
            return None

        return self.sphinx_info.build_dir

    @property
    def build_uri(self) -> Optional[str]:
        """The build uri of the Sphinx application."""
        build_dir = self.build_dir
        if build_dir is None:
            return None

        return Uri.from_fs_path(build_dir)

    async def start(self, config: SphinxConfig):
        """Start the sphinx agent."""
        command = [*config.python_command, "-m", "sphinx_agent"]
        self.logger.debug("Starting sphinx agent: %s", " ".join(command))

        await self.start_io(
            *command, env={"PYTHONPATH": config.python_path}, cwd=config.cwd
        )

    async def server_exit(self, server: asyncio.subprocess.Process):
        """Called when the sphinx agent process exits."""
        self.logger.debug(f"Process exited with code: {server.returncode}")

        if server.returncode != 0:
            stderr = await server.stderr.read()
            self.logger.debug("Stderr:\n%s", stderr.decode("utf8"))

    async def create_application(self, config: SphinxConfig):
        """Create a sphinx application object."""

        if self.stopped:
            raise RuntimeError("Client is stopped.")

        self.logger.debug("Starting sphinx: %s", " ".join(config.build_command))
        self.sphinx_info = await self.protocol.send_request_async(
            "sphinx/createApp", {"command": config.build_command}
        )
        return self.sphinx_info


def make_sphinx_client(manager: SphinxManager):
    client = SphinxClient(manager=manager)

    @client.feature("window/logMessage")
    def on_msg(ls: SphinxClient, params):
        ls.manager.server.show_message_log(params.message)

    return client