#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""Utility test-functions/classes to test WDOM on browser.

This module depend on selenium webdriver, so please install selenium before
use this module::

    pip install selenium

"""

import sys
import os
import time
import logging
import asyncio
import unittest
import shutil
from multiprocessing import Process, Pipe  # type: ignore
from multiprocessing.connection import Connection
from types import FunctionType, MethodType
from typing import Any, Callable, Iterable, Union, Set, Optional, TYPE_CHECKING

from selenium import webdriver
from selenium.common.exceptions import NoSuchElementException
from selenium.webdriver.common.utils import free_port
from selenium.webdriver.remote.webdriver import WebDriver
from selenium.webdriver.remote.webelement import WebElement
from selenium.webdriver.support.select import Select

from tornado.httpclient import AsyncHTTPClient, HTTPResponse
from tornado.platform.asyncio import to_asyncio_future
from tornado.websocket import websocket_connect, WebSocketClientConnection

from wdom import options, server
from wdom.document import get_document
from wdom.element import Element
from wdom.util import reset

if TYPE_CHECKING:
    from asyncio import AbstractEventLoop  # noqa: F401
    from typing import List  # noqa: F401

driver = webdriver.Chrome
local_webdriver = None
remote_webdriver = None
browser_implict_wait = 0
logger = logging.getLogger(__name__)
root_logger = logging.getLogger('wdom')
server_config = server.server_config


def _get_chromedriver_path() -> str:
    """Get path to chromedriver executable.

    Usually it is on the project root.
    """
    chromedriver_path = shutil.which('chromedriver')
    if chromedriver_path:
        return chromedriver_path
    if 'TRAVIS' in os.environ:
        chromedriver_path = os.path.join(
            os.environ['TRAVIS_BUILD_DIR'], 'chromedriver')
    else:
        chromedriver_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            'chromedriver'
        )
    return chromedriver_path


# see https://www.spirulasystems.com/blog/2016/08/11/https-everywhere-unit-testing-for-chromium/  # noqa: E501
def get_chrome_options() -> webdriver.ChromeOptions:
    """Get default chrome options."""
    chrome_options = webdriver.ChromeOptions()
    chrome_options.add_argument('--headless')
    chrome_options.add_argument('--disable-gpu')  # need for headless
    if 'TRAVIS'in os.environ:
        chrome_options.add_argument('--no-sandbox')
    return chrome_options


class TestCase(unittest.TestCase):
    """Base class for testing wdom modules.

    This class is a sub class of the ``unittest.TestCase``. After all test
    methods, reset wdom's global objects like document, application, and
    elements. If you use ``tearDown`` method, do not forget to call
    ``super().tearDown()``.

    If you want to reuse document/application object in your test class, please
    set them in each setup phase as follow::

        @classmethod
        def setUpClass(cls):
            cls.your_doc = get_document()
            cls.your_app = get_app()

        def setUp(self):
            from wdom.document import set_document
            from wdom.server import set_application
            set_document(self.your_doc)
            set_application(self.your_app)
    """

    def setUp(self) -> None:
        """Reset WDOM states."""
        super().setUp()
        reset()

    def tearDown(self) -> None:
        """Reset WDOM states."""
        reset()
        super().tearDown()

    def assertIsTrue(self, bl: bool) -> None:
        """Check arg is exactly True, not truthy."""
        self.assertIs(bl, True)

    def assertIsFalse(self, bl: bool) -> None:
        """Check arg is exactly False, not falsy."""
        self.assertIs(bl, False)


class HTTPTestCase(TestCase):
    """For http/ws connection test."""

    wait_time = 0.05 if os.getenv('TRAVIS') else 0.01
    timeout = 1.0
    _server_started = False
    _ws_connections = []  # type: List[Connection]

    def start(self) -> None:
        """Start web server.

        Please call this method after prepraring document.
        """
        time.sleep(0.1)
        with self.assertLogs(root_logger, 'INFO'):
            self.server = server.start_server(port=0)
        time.sleep(0.1)
        self.port = server_config['port']
        self.url = 'http://localhost:{}'.format(self.port)
        self.ws_url = 'ws://localhost:{}'.format(self.port)
        self._server_started = True

    def tearDown(self) -> None:
        """Terminate server and close all ws client connections."""
        if self._server_started:
            with self.assertLogs(root_logger, 'INFO'):
                server.stop_server(self.server)
            self._server_started = False
        while self._ws_connections:
            ws = self._ws_connections.pop()
            ws.close()
        super().tearDown()

    async def fetch(self, url: str, encoding: str = 'utf-8') -> HTTPResponse:
        """Fetch url and return ``tornado.httpclient.HTTPResponse`` object.

        Response body is decoded by ``encoding`` and set ``text`` property of
        the response. If failed to decode, ``text`` property will be ``None``.
        """
        response = await to_asyncio_future(
            AsyncHTTPClient().fetch(url, raise_error=False))
        if response.body:
            try:
                response.text = response.body.decode(encoding)
            except UnicodeDecodeError:
                response.text = None
        else:
            response.text = None
        return response

    async def ws_connect(self, url: str, timeout: float = None
                         ) -> WebSocketClientConnection:
        """Make WebSocket connection to the url.

        Retries up to _max (default: 20) times. Client connections made by this
        method are closed after each test method.
        """
        st = time.perf_counter()
        timeout = timeout or self.timeout
        while (time.perf_counter() - st) < timeout:
            try:
                ws = await to_asyncio_future(websocket_connect(url))
            except ConnectionRefusedError:
                await self.wait()
                continue
            else:
                self._ws_connections.append(ws)
                return ws
        raise ConnectionRefusedError(
            'WebSocket connection refused: {}'.format(url))

    async def wait(self, timeout: float = None, times: int = 1) -> None:
        """Coroutine to wait for ``timeout``.

        ``timeout`` is second to wait, and its default value is
        ``self.wait_time``. If ``times`` are specified, wait for
        ``timeout * times``.
        """
        for i in range(times):
            await asyncio.sleep(timeout or self.wait_time)


def start_webdriver() -> None:
    """Start WebDriver and set implicit_wait if it is not started."""
    global local_webdriver
    if local_webdriver is None:
        local_webdriver = driver(
            executable_path=_get_chromedriver_path(),
            chrome_options=get_chrome_options(),
        )
        if browser_implict_wait:
            local_webdriver.implicitly_wait(browser_implict_wait)


def close_webdriver() -> None:
    """Close WebDriver."""
    global local_webdriver
    if local_webdriver is not None:
        local_webdriver.close()
        local_webdriver = None


def get_webdriver() -> WebDriver:
    """Return WebDriver of current process.

    If it is not started yet, start and return it.
    """
    if globals().get('local_webdriver') is None:
        start_webdriver()
    return local_webdriver


conn = None  # type: Connection
wd_conn = None  # type: Connection
browser_manager = None
remote_webdriver = None


def _clear() -> None:
    global conn, wd_conn, browser_manager, remote_webdriver
    conn = None
    wd_conn = None
    browser_manager = None
    remote_webdriver = None


def start_remote_browser() -> None:
    """Start remote browser process."""
    global browser_manager, conn, wd_conn
    conn, wd_conn = Pipe()

    def start_browser() -> None:
        global wd_conn
        bc = BrowserController(wd_conn)
        bc.run()

    browser_manager = Process(target=start_browser)
    browser_manager.start()


def close_remote_browser() -> None:
    """Terminate remote browser process."""
    global conn, browser_manager
    conn.send({'target': 'process', 'method': 'quit'})
    time.sleep(0.3)
    logger.info('\nRemote Browser closed')
    conn.close()
    if browser_manager is not None:
        browser_manager.terminate()
    _clear()


def get_remote_browser() -> WebDriver:
    """Start new WebDriver for remote process."""
    global remote_webdriver
    if remote_webdriver is None:
        remote_webdriver = driver(
            executable_path=_get_chromedriver_path(),
            chrome_options=get_chrome_options(),
        )
        if browser_implict_wait:
            remote_webdriver.implicitly_wait(browser_implict_wait)
        return remote_webdriver
    else:
        return remote_webdriver


class BrowserController:
    """Class to run and wrap webdriver in different proceess."""

    _select_methods = [s for s in dir(Select) if not s.startswith('_')]

    def __init__(self, conn: Connection) -> None:
        """Set up connection and start webdriver.

        ``conn`` is a one end of ``Pipe()``, which is used the inter-process
        communication.
        """
        self.conn = conn
        self.wd = get_remote_browser()
        self.element = None

    def set_element_by_id(self, id: int) -> Union[bool, str]:
        """Find element with ``id`` and set it to element property.

        When successfully find the element, send ``True``. If failed to find
        the element, send message ``Error NoSuchElement: {{ id }}``.
        """
        try:
            self.element = self.wd.find_element_by_css_selector(
                '[rimo_id="{}"]'.format(id))
            return True
        except NoSuchElementException:
            return 'Error NoSuchElement: {}'.format(id)

    def quit(self) -> str:
        """Terminate WebDriver."""
        self.wd.quit()
        return 'closed'

    def close(self) -> str:
        """Close WebDriver."""
        self.wd.close()
        return 'closed'

    def _execute_method(self, method: str, args: Iterable[str]) -> None:
        if isinstance(method, (FunctionType, MethodType)):
            self.conn.send(method(*args))
        else:
            # not callable, just send it back
            self.conn.send(method)

    def run(self) -> None:  # noqa: C901
        """Wait message from the other end of the connection.

        When gat message, execute the method specified by the message. The
        message should be a python's dict, which must have ``target`` and
        ``method`` field.
        """
        while True:
            req = self.conn.recv()
            target = req.get('target', '')
            method_name = req.get('method', '')
            args = req.get('args', [])
            if target == 'process':
                method = getattr(self, method_name)
            elif target == 'browser':
                method = getattr(self.wd, method_name)
            elif target == 'element':
                if self.element is None:
                    # Element must be set
                    self.conn.send('Error: No Element Set')
                    continue
                if (method_name in self._select_methods and
                        self.element.tag_name.lower() == 'select'):
                    s = Select(self.element)
                    method = getattr(s, method_name)
                else:
                    method = getattr(self.element, method_name)
            self._execute_method(method, args)


def wait_for() -> str:
    """Wait the response from the remote process and return it."""
    return asyncio.get_event_loop().run_until_complete(wait_coro())


async def wait_coro() -> str:
    """Wait response from the other process."""
    while True:
        state = conn.poll()
        if state:
            res = conn.recv()
            return res
        else:
            await asyncio.sleep(0)
            continue


def _get_properties(cls: type) -> Set[str]:
    props = set()
    for k, v in vars(cls).items():
        if not isinstance(v, (FunctionType, MethodType)):
            props.add(k)
    return props


class Controller:
    """Base class for remote browser controller."""

    target = None  # type: Optional[str]
    properties = set()  # type: Set[str]

    def __getattr__(self, attr: str) -> Connection:
        """Call methods related to this controller."""
        global conn

        def wrapper(*args: str) -> str:
            conn.send({'target': self.target, 'method': attr, 'args': args})
            res = wait_for()
            if isinstance(res, str):
                if res.startswith('Error NoSuchElement'):
                    raise NoSuchElementException(res)
                elif res.startswith('Error'):
                    raise ValueError(res)
            return res
        if attr in self.properties:
            return wrapper()
        return wrapper


class ProcessController(Controller):
    """Controller of remote browser process."""

    target = 'process'


class RemoteBrowserController(Controller):
    """Controller of remote web driver."""

    target = 'browser'
    properties = _get_properties(WebDriver)


class RemoteElementController(Controller):
    """Controller of remote web driver element."""

    target = 'element'
    properties = _get_properties(WebElement)


class TimeoutError(Exception):
    """The operation is not completed by timeout."""


class RemoteBrowserTestCase:
    """This class is **Experimental**.

    Utility class for testing apps with webdriver in another process. Mainly
    used for development and test of wdom library itself. This class does not
    support all methods provided by selenium.webdriver, but maybe enough.

    After seting up your document, call ``start`` method in setup sequence.
    """

    #: seconds to wait for by ``wait`` method.
    wait_time = 0.01
    #: secondes for deault timeout for ``wait_until`` method
    timeout = 1.0

    def start(self) -> None:
        """Start remote browser process."""
        self._prev_logging = options.config.logging
        options.config.logging = 'warn'
        self.proc = ProcessController()
        self.browser = RemoteBrowserController()
        self.element = RemoteElementController()
        try:
            self.server = server.start_server(port=0)
        except OSError:
            self.wait(0.2)
            self.server = server.start_server(port=0)
        self.address = server_config['address']
        self.url = 'http://{0}:{1}/'.format(self.address, self.port)
        self.browser.get(self.url)
        self.wait_until(lambda: server.is_connected())

    def tearDown(self) -> None:
        """Run tear down process.

        Reset log-level, stop web server, and flush stdout.
        """
        options.config.logging = self._prev_logging
        server.stop_server()
        sys.stdout.flush()
        sys.stderr.flush()
        super().tearDown()  # type: ignore

    @property
    def port(self) -> Optional[str]:
        """Get port of the server."""
        return server_config['port']

    def wait(self, timeout: float = None, times: int = 1) -> None:
        """Wait for ``timeout`` seconds.

        Default timeout is ``RemoteBrowserTestCase.wait_time``.
        """
        loop = asyncio.get_event_loop()
        for i in range(times):
            loop.run_until_complete(asyncio.sleep(timeout or self.wait_time))

    def wait_until(self, func: Callable[[], Any],
                   timeout: float = None) -> None:
        """Wait until ``func`` returns True or exceeds timeout.

        ``func`` is called with no argument. Unit of ``timeout`` is second, and
        its default value is RemoteBrowserTestCase.timeout class variable
        (default: 1.0).
        """
        st = time.perf_counter()
        timeout = timeout or self.timeout
        while (time.perf_counter() - st) < timeout:
            if func():
                return
            self.wait()
        raise TimeoutError('{} did not return True until timeout'.format(func))

    def _set_element(self, node: Element) -> Union[bool, str]:
        try:
            res = self.proc.set_element_by_id(node.rimo_id)
            return res
        except NoSuchElementException:
            return False

    def set_element(self, node: Element, timeout: float = None) -> bool:
        """Set the ``node`` as a target node of the remote browser process."""
        try:
            self.wait_until(lambda: self._set_element(node), timeout)
            return True
        except TimeoutError:
            pass
        raise NoSuchElementException('element not found: {}'.format(node))


class WebDriverTestCase:
    """Base class for testing UI on browser.

    This class starts up an HTTP server on a new subprocess.

    Subclasses should call ``start`` method after seting up your document.
    After ``start`` method called, the web server is running on the other
    process so you cannot make change on the document. If you need to change
    document after server started, please use ``RemoteBrowserTestCase`` class
    instead.
    """

    #: seconds to wait for by ``wait`` method.
    wait_time = 0.01
    #: secondes for deault timeout for ``wait_until`` method
    timeout = 1.0

    @classmethod
    def setUpClass(cls) -> None:  # noqa: D102
        reset()

    @classmethod
    def tearDownClass(cls) -> None:  # noqa: D102
        reset()

    def start(self) -> None:
        """Start server and web driver."""
        self.wd = get_webdriver()

        def start_server(port: int) -> None:
            from wdom import server
            server.start(port=port)

        self.address = 'localhost'
        self.port = free_port()
        self.url = 'http://{0}:{1}/'.format(self.address, self.port)

        self.server = Process(
            target=start_server,
            args=(self.port, )
        )
        self.server.start()
        self.wait(times=10)
        self.wd.get(self.url)

    def tearDown(self) -> None:
        """Terminate server subprocess."""
        self.server.terminate()
        sys.stdout.flush()
        sys.stderr.flush()
        self.wait(times=10)
        super().tearDown()  # type: ignore

    def wait(self, timeout: float = None, times: int = 1) -> None:
        """Wait for ``timeout`` or ``self.wait_time``."""
        loop = asyncio.get_event_loop()
        for i in range(times):
            loop.run_until_complete(asyncio.sleep(timeout or self.wait_time))

    def wait_until(self, func: Callable[[], Any],
                   timeout: float = None) -> None:
        """Wait until ``func`` returns True or exceeds timeout.

        ``func`` is called with no argument. Unit of ``timeout`` is second, and
        its default value is RemoteBrowserTestCase.timeout class variable
        (default: 1.0).
        """
        st = time.perf_counter()
        timeout = timeout or self.timeout
        while (time.perf_counter() - st) < timeout:
            if func():
                return
            self.wait()
        raise TimeoutError('{} did not return True until timeout'.format(func))

    def send_keys(self, element: Element, keys: str) -> None:
        """Send ``keys`` to ``element`` one-by-one.

        Safer than using ``element.send_keys`` method.
        """
        for k in keys:
            element.send_keys(k)


class PyppeteerTestCase(TestCase):
    if os.getenv('TRAVIS', False):
        wait_time = 0.1
    else:
        wait_time = 0.05

    @classmethod
    def setUpClass(cls):
        from pyppeteer.launcher import launch
        from syncer import sync
        cls.browser = launch({'headless': True})
        cls.page = sync(cls.browser.newPage())

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()

    def setUp(self):
        from syncer import sync
        super().setUp()
        self.doc = get_document()
        self.root = self.get_elements()
        self.doc.body.prepend(self.root)
        self.server = server.start_server(port=0)
        self.address = server_config['address']
        self.port = server_config['port']
        self.url = 'http://{}:{}'.format(self.address, self.port)
        sync(self.page.goto(self.url))
        self.element = sync(self.get_element_handle(self.root))

    def tearDown(self):
        server.stop_server(self.server)
        super().tearDown()
        import time
        time.sleep(0.01)

    def get_elements(self):
        raise NotImplementedError

    async def get_element_handle(self, elm):
        result = await self.page.querySelector(
            '[rimo_id="{}"]'.format(elm.rimo_id))
        return result

    async def get_text(self, elm=None):
        elm = elm or self.element
        result = await elm.evaluate('(elm) => elm.textContent')
        return result

    async def get_attribute(self, name, elm=None):
        elm = elm or self.element
        result = await elm.evaluate(
            '(elm) => elm.getAttribute("{}")'.format(name))
        return result

    async def wait(self, timeout=None):
        timeout = timeout or self.wait_time
        _t = timeout / 10
        for _ in range(10):
            await asyncio.sleep(_t)

    async def wait_for_element(self, elm):
        await self.page.waitForSelector(
            '[rimo_id="{}"]'.format(elm.rimo_id),
            {'timeout': 100},
        )
