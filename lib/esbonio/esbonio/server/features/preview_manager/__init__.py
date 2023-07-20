import asyncio
import logging
from http.server import HTTPServer
from http.server import SimpleHTTPRequestHandler
from typing import Any
from typing import Optional

import pygls.uris as Uri

from esbonio.server import EsbonioLanguageServer
from esbonio.server import Uri
from esbonio.server.feature import LanguageFeature
from esbonio.server.features.sphinx_manager import SphinxManager

from .webview import WebviewServer
from .webview import make_ws_server


class RequestHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, logger: logging.Logger, directory: str, **kwargs) -> None:
        self.logger = logger
        super().__init__(*args, directory=directory, **kwargs)

    def translate_path(self, path: str) -> str:
        result = super().translate_path(path)
        # self.logger.debug("Translate: '%s' -> '%s'", path, result)
        return result

    def log_message(self, format: str, *args: Any) -> None:
        self.logger.debug(format, *args)


class RequestHandlerFactory:
    """Class for dynamically producing request handlers.

    ``HTTPServer`` works by taking a "request handler" class and creating an instance of
    it for every request it receives. By making this class callable, we can dynamically
    produce a request handler based on the current situation.
    """

    def __init__(self, logger: logging.Logger, build_dir: str):
        self.logger = logger
        self.build_dir = build_dir

    def __call__(self, *args, **kwargs):
        return RequestHandler(
            *args, logger=self.logger, directory=self.build_dir, **kwargs
        )


class PreviewManager(LanguageFeature):
    """Language feature for managing previews."""

    def __init__(self, server: EsbonioLanguageServer, sphinx: SphinxManager):
        super().__init__(server)
        self.sphinx = sphinx
        self.sphinx.add_listener("build", self.on_build)

        logger = server.logger.getChild("PreviewServer")
        self._request_handler_factory = RequestHandlerFactory(logger, "")
        self._http_server: Optional[HTTPServer] = None
        self._http_future: Optional[asyncio.Future] = None

        self._ws_server: Optional[WebviewServer] = None
        self._ws_task: Optional[asyncio.Task] = None

    @property
    def preview_active(self) -> bool:
        """Return true if the preview is active.

        i.e. there is a HTTP server hosting the build result."""
        return self._http_server is not None

    @property
    def preview_controllable(self) -> bool:
        """Return true if the preview is controllable.

        i.e. there is a web socket server available to control the webview.
        """
        return self._ws_server is not None

    def get_http_server(self) -> HTTPServer:
        """Return the http server instance hosting the previews.

        This will also handle the creation of the server the first time it is called.
        """
        if self._http_server is not None:
            return self._http_server

        self._http_server = HTTPServer(("localhost", 0), self._request_handler_factory)

        loop = asyncio.get_running_loop()
        self._http_future = loop.run_in_executor(
            self.server.thread_pool_executor,
            self._http_server.serve_forever,
        )

        return self._http_server

    async def get_webview_server(self) -> WebviewServer:
        """Return the websocket server used to communicate with the webview."""

        if self._ws_server is not None:
            return self._ws_server

        logger = self.server.logger.getChild("WebviewServer")
        self._ws_server = make_ws_server(self.server, logger)
        self._ws_task = asyncio.create_task(self._ws_server.start_ws("localhost", 0))

        # HACK: we need to yield control to the event loop to give the ws_server time to
        #       spin up and allocate a port number.
        await asyncio.sleep(1)

        return self._ws_server

    async def on_build(self, src_uri: Uri, result):
        """Called whenever a sphinx build completes."""
        self.logger.debug("Build finished: '%s'", src_uri)

        client = await self.sphinx.get_client(src_uri)
        if client is None:
            return

        # Only refresh the view if the project we are previewing was built.
        if client.build_dir != self._request_handler_factory.build_dir:
            return

        webview = await self.get_webview_server()
        webview.reload()

    async def scroll_view(self, line: int):
        """Scroll the webview to the given line number."""

        webview = await self.get_webview_server()
        webview.scroll(line)

    async def preview_file(self, params):
        src_uri = Uri.parse(params["uri"])
        self.logger.debug("Preview file called %s", src_uri)

        client = await self.sphinx.get_client(src_uri)
        if client is None:
            return None

        if client.src_uri is None or client.build_dir is None or client.builder is None:
            return None

        # TODO: Have the sphinx client provide a mapping from src -> html
        rst_path = src_uri.path.replace(client.src_uri.path, "")
        if client.builder == "html":
            html_path = rst_path.replace(".rst", ".html")
        elif client.builder == "dirhtml":
            html_path = rst_path.replace("index.rst", "").replace(".rst", "/")
        else:
            self.logger.error(
                "Previews for the '%s' builder are not currently supported",
                client.builder,
            )
            return None

        self.logger.debug("'%s' -> '%s' -> '%s'", src_uri.path, rst_path, html_path)

        server = self.get_http_server()
        self._request_handler_factory.build_dir = client.build_dir
        self.logger.debug("Preview running on port: %s", server.server_port)

        webview = await self.get_webview_server()
        self.logger.debug("Websockets running on port: %s", webview.port)

        uri = Uri.create(
            scheme="http", 
            authority=f"localhost:{server.server_port}",
            path=html_path,
            query=f"ws={webview.port}",
        )
        return {"uri": uri.as_string(encode=False)}


def esbonio_setup(server: EsbonioLanguageServer, sphinx: SphinxManager):
    manager = PreviewManager(server, sphinx)
    server.add_feature(manager)

    @server.feature("view/scroll")
    async def on_scroll(ls: EsbonioLanguageServer, params):
        await manager.scroll_view(params.line)

    @server.command("esbonio.server.previewFile")
    async def preview_file(ls: EsbonioLanguageServer, *args):
        return await manager.preview_file(args[0][0])
