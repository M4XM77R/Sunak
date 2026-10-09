"""Keeps Sunak's web research away from the local network (SSRF protection) and slows down password guessing.

`fetch_public` downloads a page from the internet only: every address it would contact (also after a redirect)
has to be a public one, so a search result or a link cannot make Sunak read from localhost, the home network
or a cloud metadata service. `LoginLimiter` is the in-memory counter behind the login and PIN rate limits."""

import http.client
import ipaddress
import os
import socket
import ssl
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

MAX_REDIRECTS = 5


class BlockedAddress(urllib.error.URLError):
    """The address points into a private network (or is not a normal web address)."""


def allow_private():
    """True when SUNAK_ALLOW_PRIVATE_FETCH=1 switches the protection off (for research on an intranet)."""
    return os.environ.get("SUNAK_ALLOW_PRIVATE_FETCH", "").strip().lower() in ("1", "true", "yes", "on")


def is_public_ip(ip):
    """True for an address on the public internet. Private, loopback, link-local (also the 169.254.169.254
    metadata address), unspecified, multicast, reserved and shared (100.64/10) ranges are not; an IPv6 address that
    wraps an IPv4 one (::ffff:a.b.c.d, 6to4, NAT64) is judged by the IPv4 address inside."""
    try:
        a = ipaddress.ip_address(ip.split("%")[0] if isinstance(ip, str) else ip)
    except ValueError:
        return False
    if isinstance(a, ipaddress.IPv6Address):
        inner = a.ipv4_mapped or a.sixtofour
        if inner is None and a in ipaddress.ip_network("64:ff9b::/96"):  # NAT64
            inner = ipaddress.IPv4Address(int(a) & 0xFFFFFFFF)
        if inner is not None:
            return is_public_ip(str(inner))
        if a in ipaddress.ip_network("100::/64") or a in ipaddress.ip_network("2001:db8::/32"):
            return False
    elif a in ipaddress.ip_network("100.64.0.0/10"):
        return False
    return a.is_global and not (a.is_multicast or a.is_reserved)


def _proxied(url):
    """True when the system proxy settings send this address through a proxy."""
    scheme = urllib.parse.urlsplit(url).scheme
    return scheme in urllib.request.getproxies() and not urllib.request.proxy_bypass(urllib.parse.urlsplit(url).hostname or "")


def check_url(url, resolve=None):
    """Raise BlockedAddress unless `url` is an http(s) address whose host (every address it resolves to) is public."""
    resolve = resolve or socket.getaddrinfo
    parts = urllib.parse.urlsplit(url)
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise BlockedAddress("not a web address")
    if allow_private():
        return
    host = parts.hostname
    try:
        infos = resolve(host, parts.port or (443 if parts.scheme == "https" else 80), type=socket.SOCK_STREAM)
    except OSError as e:
        if _proxied(url):  # a proxy looks the name up itself (an IP address never gets here)
            return
        raise BlockedAddress("cannot resolve %s (%s)" % (host, e)) from None
    ips = {i[4][0] for i in infos}
    if not ips or not all(is_public_ip(ip) for ip in ips):
        raise BlockedAddress("%s is not a public address" % host)


def _connect_public(address, timeout=socket._GLOBAL_DEFAULT_TIMEOUT, source_address=None):
    """socket.create_connection that resolves the name itself, refuses unless every answer is a public address,
    and connects to exactly the address it checked. Host header and TLS server name still use the name, so the
    check and the connection cannot see different answers (DNS rebinding)."""
    host, port = address
    infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    ips = [i[4][0] for i in infos]
    if not allow_private() and (not ips or not all(is_public_ip(ip) for ip in ips)):
        raise BlockedAddress("%s is not a public address" % host)
    err = None
    for ip in ips:
        try:
            return socket.create_connection((ip, port), timeout, source_address)
        except OSError as e:
            err = e
    raise err or OSError("no address for %s" % host)


class _PinnedHTTP(http.client.HTTPConnection):
    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self._create_connection = _connect_public  # urllib's own sockets would skip the check


class _PinnedHTTPS(http.client.HTTPSConnection):
    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self._create_connection = _connect_public  # urllib's own sockets would skip the check


class _PinnedHandlers(urllib.request.HTTPHandler, urllib.request.HTTPSHandler):
    def http_open(self, req):
        return self.do_open(_PinnedHTTP, req)

    def https_open(self, req):
        return self.do_open(_PinnedHTTPS, req, context=ssl.create_default_context())


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **kw):
        return None


# no proxy: connections go to the checked address (see _connect_public)
_DIRECT = urllib.request.build_opener(urllib.request.ProxyHandler({}), _PinnedHandlers(), _NoRedirect)
# with a system proxy the proxy looks the name up, so only the check before the request is possible
_PROXIED = urllib.request.build_opener(_NoRedirect)


def fetch_public(url, headers=None, timeout=10, opener=None, resolve=None):
    """Open `url` like urlopen, but only public addresses: the name is checked before the request and before
    every redirect (followed by hand, at most MAX_REDIRECTS), and without a system proxy the connection goes to
    the very address that was checked. Returns the open response (use as a context manager); raises BlockedAddress."""
    resolve = resolve or socket.getaddrinfo
    for _ in range(MAX_REDIRECTS + 1):
        check_url(url, resolve)
        op = opener or (_PROXIED if _proxied(url) else _DIRECT)
        try:
            return op.open(urllib.request.Request(url, headers=headers or {}), timeout=timeout)
        except urllib.error.HTTPError as e:
            if e.code not in (301, 302, 303, 307, 308) or not e.headers.get("Location"):
                raise
            url = urllib.parse.urljoin(url, e.headers["Location"])
            e.close()
        except urllib.error.URLError as e:
            if isinstance(e.reason, BlockedAddress):
                raise e.reason from None
            raise
    raise urllib.error.URLError("too many redirects")


class LoginLimiter:
    """Counts failed password or PIN attempts per key (client address, profile) and locks a key for a growing
    time: after `free` failures the wait is `base` seconds, doubling with every further failure up to `cap`.
    A success forgets the key. In memory only: a restart of Sunak clears it."""

    def __init__(self, free=5, base=30, cap=900, forget=3600, max_keys=5000, clock=time.monotonic):
        self.free, self.base, self.cap, self.forget, self.max_keys, self.clock = free, base, cap, forget, max_keys, clock
        self._lock = threading.Lock()
        self._state = {}  # key -> [failures, locked until, last failure]

    def wait(self, *keys):
        """Seconds (rounded up) until none of the keys is locked any more; 0 when attempts are allowed."""
        now = self.clock()
        with self._lock:
            left = max((self._state[k][1] - now for k in keys if k in self._state), default=0)
        return max(0, int(left) + (1 if left > int(left) else 0))

    def fail(self, *keys):
        """Record a failed attempt for the keys."""
        now = self.clock()
        with self._lock:
            if len(self._state) >= self.max_keys:
                self._state = {k: v for k, v in self._state.items() if now - v[2] < self.forget}
                while len(self._state) >= self.max_keys:  # still full: drop the oldest
                    self._state.pop(min(self._state, key=lambda k: self._state[k][2]))
            for k in keys:
                s = self._state.get(k)
                if s is None or now - s[2] >= self.forget:
                    s = self._state[k] = [0, 0.0, now]
                s[0] += 1
                s[2] = now
                over = s[0] - self.free
                if over >= 0:
                    s[1] = now + min(self.cap, self.base * 2 ** min(over, 20))

    def ok(self, *keys):
        """Forget the keys after a successful login."""
        with self._lock:
            for k in keys:
                self._state.pop(k, None)
