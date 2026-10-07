"""First in, first out queue for model requests, so several people can use one Sunak at the same time.

Every backend has its own queue (`chat:<provider id>` for chat models, `image` for the image generator).
A request takes a slot before it talks to the backend and gives it back when it is done; while all slots
are taken the requests wait in the order they arrived. A local backend (Ollama on this computer, a LAN
server) has one slot, because one heavy request at a time is what such a machine can do; a backend on the
internet has a few (`SUNAK_MODEL_SLOTS` sets the number for local ones).

The waiting request is told its place ("place 2 in the queue") through `notify(place)`; 0 means it is
its turn. When the browser went away (Stop button, closed tab) the notice fails, and the request leaves the
queue instead of waiting for nothing."""

import contextlib
import os
import threading
import time
from collections import deque

from . import log

logger = log.get("queue")

POLL = 1.0           # seconds between two looks at the queue while waiting
NOTIFY_EVERY = 2.0   # a waiting request is told its place at least this often (this also notices a closed browser)
MAX_WAIT = 900.0     # seconds after which a request gives up waiting
REMOTE_SLOTS = 4     # parallel requests to a backend on the internet


class Cancelled(BrokenPipeError):
    """The request left the queue because its browser went away or it was cancelled."""


class Timeout(Exception):
    """The request waited MAX_WAIT seconds without getting its turn."""


def local_slots():
    """Parallel requests to a local backend: 1, or SUNAK_MODEL_SLOTS."""
    try:
        return max(1, min(32, int(os.environ.get("SUNAK_MODEL_SLOTS", "1"))))
    except ValueError:
        return 1


class Gate:
    """`slots` places, a FIFO line of waiting requests."""

    def __init__(self, slots=1, name="queue"):
        self.name = name
        self.slots = slots
        self.running = 0
        self.waiting = deque()
        self.cv = threading.Condition()

    def acquire(self, notify=None, cancelled=None, timeout=MAX_WAIT):
        me = object()
        with self.cv:
            if self.running < self.slots and not self.waiting:
                self.running += 1
                return
            self.waiting.append(me)
            ahead = len(self.waiting)
        last, told = None, 0.0
        began = time.monotonic()
        deadline = began + timeout
        logger.info("%s: busy, the request waits (place %d)", self.name, ahead)

        def my_turn():
            return self.waiting[0] is me and self.running < self.slots
        try:
            while True:
                with self.cv:
                    if my_turn():
                        self.waiting.popleft()
                        self.running += 1
                        self.cv.notify_all()  # the next one in line may also fit (several slots)
                        place = 0
                    else:
                        place = list(self.waiting).index(me) + 1
                        if time.monotonic() > deadline:
                            raise Timeout
                now = time.monotonic()
                if place == 0:
                    logger.info("%s: its turn after %.1fs", self.name, now - began)
                    if notify and last is not None:
                        try:
                            notify(0)
                        except OSError:
                            self.release()
                            raise Cancelled from None
                    return
                if cancelled and cancelled():
                    raise Cancelled
                if notify and (place != last or now - told >= NOTIFY_EVERY):
                    try:
                        notify(place)
                    except OSError:
                        raise Cancelled from None
                    last, told = place, now
                with self.cv:
                    self.cv.wait_for(my_turn, POLL)
        except BaseException as e:
            if isinstance(e, Timeout):
                logger.warning("%s: gave up after %.0fs in the queue", self.name, time.monotonic() - began)
            elif isinstance(e, Cancelled):
                logger.info("%s: left the queue after %.1fs (cancelled or the browser went away)", self.name, time.monotonic() - began)
            with self.cv:
                if me in self.waiting:
                    self.waiting.remove(me)
                self.cv.notify_all()
            raise

    def release(self):
        with self.cv:
            self.running = max(0, self.running - 1)
            self.cv.notify_all()

    def snapshot(self):
        """(requests running, requests waiting)"""
        with self.cv:
            return self.running, len(self.waiting)


_gates = {}
_lock = threading.Lock()
local = threading.local()   # per request thread: `notify` (set by the HTTP handler) and the slots it holds


def gate(key, slots=1):
    with _lock:
        if key not in _gates:
            _gates[key] = Gate(slots, key)
        return _gates[key]


def snapshot():
    """{key: (running, waiting)} of every queue that has been used."""
    with _lock:
        gates = dict(_gates)
    return {k: g.snapshot() for k, g in gates.items()}


@contextlib.contextmanager
def slot(key, slots=1, notify=None, cancelled=None):
    """Wait for a place in the queue `key`, hold it inside the `with`. A request that already holds a place
    in this queue (the same thread asking again) is not queued behind itself."""
    held = local.__dict__.setdefault("held", {})
    if held.get(key):
        held[key] += 1
        try:
            yield
        finally:
            held[key] -= 1
        return
    g = gate(key, slots)
    g.acquire(notify or getattr(local, "notify", None), cancelled)
    held[key] = 1
    try:
        yield
    finally:
        held.pop(key, None)
        g.release()
