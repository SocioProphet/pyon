
__author__ = 'Luke'


# https://github.com/surfly/gevent/blob/b515eb5c803a1217cdff67f9c953a49c77d7bbc1/gevent/_threading.py
_pythread = None

def get_pythread():
    '''
    Loads the 'thread' module, free of monkey patching.
    '''
    global _pythread
    if _pythread:
        return _pythread # Cache the module so we don't have to use imp every time

    import imp
    fp, path, desc = imp.find_module('thread')
    try:
        _pythread = imp.load_module('pythread', fp, path, desc)
    finally:
        if fp:
            fp.close() # Close the file
    return _pythread

_pytime = None
def get_pytime():
    '''
    Loads the 'time' module, free of monkey patching.
    '''
    global _pytime
    if _pytime:
        return _pytime

    import imp
    fp, path, desc = imp.find_module('time')
    try:
        _pytime = imp.load_module('pytime', fp, path, desc)
    finally:
        if fp:
            fp.close()
    return _pythread

# thread imports
start_new_thread = get_pythread().start_new_thread
Lock = get_pythread().allocate_lock
get_ident = get_pythread().get_ident
local = get_pythread()._local
stack_size = get_pythread().stack_size
# time imports
_time = get_pytime().time
_sleep = get_pytime().sleep

try:
    from Queue import Full, Empty
except ImportError:
    from queue import Full, Empty

from collections import deque

import heapq


class RLock(object):
    def __init__(self):
        self.__block = Lock()
        self.__owner = None
        self.__count = 0

    def __repr__(self):
        owner = self.__owner
        return "<%s owner=%r count=%d>" % (self.__class__.__name__, owner, self.__count)

    def acquire(self, blocking=1):
        me = get_ident()
        if self.__owner == me:
            self.__count = self.__count + 1
            return 1
        rc = self.__block.acquire(blocking)
        if rc:
            self.__owner = me
            self.__count = 1
        return rc

    __enter__ = acquire

    def release(self):
        if self.__owner != get_ident():
            raise RuntimeError("cannot release un-acquired lock")
        self.__count = count = self.__count - 1
        if not count:
            self.__owner = None
            self.__block.release()

    def __exit__(self, type, value, traceback):
        self.release()

    def _acquire_restore(self, count_owner):
        count, owner = count_owner
        self.__block.acquire()
        self.__count = count
        self.__owner = owner

    def _release_save(self):
        count = self._count
        self.__count = 0
        owner = self.__owner
        self.__owner = None
        self.__block.release()
        return count, owner

    def _is_owned(self):
        return self.__owner == get_ident()

class Condition(object):
    def __init__(self, lock=None):
        if lock is None:
            lock = RLock()

        self.__lock = lock
        # Export th elock's acquire() and release() methods
        self.acquire = lock.acquire
        self.release = lock.release

        try:
            self._release_save = lock._release_save
        except AttributeError:
            pass

        try:
            self._acquire_restore = lock._acquire_restore
        except AttributeError:
            pass

        try:
            self._is_owned = lock._is_owned
        except AttributeError:
            pass

        self.__waiters = []

    def __enter__(self):
        return self.__lock.__enter__()

    def __exit__(self, type, value, traceback):
        return self.__lock.__exit__(type, value, traceback)

    def __repr__(self):
        return "<Condition(%s, %d)>" % (self.__lock, len(self.__waiters))

    def _release_save(self):
        self.__lock.release()

    def _acquire_restore(self, x):
        self.__lock.acquire()

    def _is_owned(self):
        if self.__lock.acquire(0):
            self.__lock.release()
            return False
        else:
            return True

    def wait(self, timeout=None):
        if not self._is_owned():
            raise RuntimeError("cannot wait on un-acquired lock")
        waiter = Lock()
        waiter.acquire()

        self.__waiters.append(waiter)
        saved_state = self._release_save()
        try: # restore state no matter what (e.g., KeyboardInterrupt)
            if timeout is None:
                waiter.acquire()
            else:
                # Balancing act: We can't afford a pure busy loop, so we have
                # to sleep; but if we sleep the whole timeout time, we'll be
                # unresponsive. The scheme her sleeps very little at first,
                # longer as time goes on, but never longer than 20 times per
                # second (or the timeout time remaining).
                endtime = _time() + timeout
                delay = 0.0005 

                while True:
                    gotit = waiter.acquire(0)
                    if gotit:
                        break
                    remaining = endtime - _time()
                    if remaining <= 0:
                        break

                    # The delay is the least between 2x the delay, the time remaining and/or .05
                    delay = min(delay * 2, remaining, 0.05)

                    _sleep(delay)

                if not gotit:
                    try:
                        self.__waiters.remove(waiter)
                    except ValueError:
                        pass
        finally:
            self._acquire_restore(saved_state)

    def notify(self, n=1):
        if not self._is_owned():
            raise RuntimeError("cannot notify on an un-acquired lock")
        __waiters = self.__waiters
        waiters = __waiters[:n]
        if not waiters:
            return
        for waiter in waiters:
            waiter.release()
            try:
                __waiters.remove(waiter)
            except ValueError:
                pass

    def notify_all(self):
        self.notify(len(self.__waiters))


class Semaphore(object):
    def __init__(self, value=1):
        if value < 0:
            raise ValueError("semaphore initial value must be >= 0")
        self.__cond = Condition(Lock())
        self.__value = value

    def acquire(self, blocking=1):
        rc = False
        self.__cond.acquire()

        while self.__value == 0:
            if not blocking:
                break
            self.__cond.wait()
        else:
            self.__value = self.__value - 1
            rc = True
        self.__cond.release()
        return rc

    __enter__ = acquire

    def release(self):
        self.__cond.acquire()
        self.__value = self.__value + 1
        self.__cond.notify()
        self.__cond.release()

    def __exit__(self, type, value, traceback):
        self.release()

class BoundedSemaphore(Semaphore):
    def __init__(self, value=1):
        Semaphore.__init__(self, value)
        self._initial_value = value

    def release(self):
        if self.Semaphore__value >= self._initial_value:
            raise ValueError("Semaphore released too many times")
        return Semaphore.release(self)

class Event(object):

    def __init__(self):
        self.__cond = Condition(Lock())
        self.__flag = False

    def _reset_internal_locks(self):
        self.__cond.__init__()

    def is_set(self):
        return self.__flag

    def set(self):
        self.__cond.acquire()
        try:
            self.__flag = True
            self.__cond.notify_all()
        finally:
            self.__cond.release()

    def clear(self):
        self.__cond.acquire()
        try:
            self.__flag = False
        finally:
            self.__cond.release()

    def wait(self, timeout=None):
        self.__cond.acquire()
        try:
            if not self.__flag:
                self.__cond.wait(timeout)
            return self.__flag
        finally:
            self.__cond.release()

class Queue:
    def __init__(self, maxsize=0):
        self.maxsize = maxsize
        self._init(maxsize)
        # mutex must be held whenever the queue is mutating. All methods that
        # acquire mutex must release it before returning. Mutex is shared
        # between the three conditions, so acquiring and releasing the
        # conditions also acquires and releases mutex.
        self.mutex = Lock()
        # Notify not_empty whenever an item is added to the queue; a thread
        # waiting to get is notified then.
        self.not_empty = Condition(self.mutex)
        # Notify not_full whenever an item is removed from the queue; a thread
        # waiting to put is notified then.
        self.not_full = Condition(self.mutex)
        # Notify all_tasks_done whenever the number of unfinished tasks drops
        # to zero; thread waiting to join() is notified to resume.
        self.all_tasks_done = Condition(self.mutex)
        self.unfinished_tasks = 0

    def task_done(self):
        '''Indicate that a formerly enqueued task is complete.

        Used by Queue consumer threads. For each get() used to fetch a task, a
        subsequent call to task_done() tells the queue that the processing on
        the task is complete.

        If a join() is currently blocking, it will resume when all items have
        been processed (meaning that a task_done() call was received for every
        item that had been put() into the queue).

        Raise a ValueError if called more times than there were items placed in
        the queue.
        '''
        self.all_tasks_done.acquire()
        try:
            unfinished = self.unfinished_tasks - 1
            if unfinished <= 0:
                if unfinished < 0:
                    raise ValueError('task_done() called too many times')
                self.all_tasks_done.notify_all()
            self.unfinished_tasks = unfinished
        finally:
            self.all_tasks_done.release()

    def join(self):
        '''Blocks until all items in the Queue have been gotten and processed.

        The count of unfinished tasks goes up whenever an item is added to the
        queue. The count goes down whenever a consumer thread calls task-done()
        to indicate the item was retrieved and all work on it is complete.

        When the count of unfinished takss drops to zero, join() unblocks.
        '''
        self.all_tasks_done.acquire()
        try:
            while self.unfinished_tasks:
                self.all_tasks_done.wait()
        finally:
            self.all_tasks_done.release()

    def qsize(self):
        '''Return the approximate size of the queue (not reliable!)'''
        self.mutex.acquire()
        try:
            return self._qsize()
        finally:
            self.mutex.release()

    def empty(self):
        '''Return True if the queue is empty, False otherwise (not reliable!)'''
        self.mutex.acquire()
        try:
            return not self._qsize()
        finally:
            self.mutex.release()

    def full(self):
        '''Return True if the queue is full, False otherwise (not reliable!)'''
        self.mutex.acquire()
        try:
            if self.maxsize <= 0:
                return False
            if self.maxsize >= self._qsize():
                return True
        finally:
            self.mutex.release()

    def put(self, item, block=True, timeout=None):
        '''Put an item into the queue.

        If optional args `block` is True and `timeout` is None (the default),
        block if necessary until a free slot is available. If `timeout` is a
        positive number, it blocks at most `timeout` seconds and raises the
        Full exception if no free slot was available within that time.
        Otherwise (`block` is False), put an item on the queue if a free slot
        is immediately available, else raise the Full exception (`timeout` is
        ignored in that case).
        '''
        self.not_full.acquire()
        try:
            if self.maxsize > 0:
                if not block:
                    if self._qsize() >= self.maxsize:
                        raise Full
                elif timeout is None:
                    while self._qsize() >= self.maxsize:
                        self.not_full.wait()
                elif timeout < 0:
                    raise ValueError("'timeout' must be a positive number")
                else:
                    endtime = _time() + timeout
                    while self._qsize() >= self.maxsize:
                        remaining = endtime - _time()
                        if remaining <= 0.0:
                            raise Full
                        self.not_full.wait(remaining)
            self._put(item)
            self.unfinished_tasks += 1
            self.not_empty.notify()
        finally:
            self.not_full.release()

    def put_nowait(self, item):
        '''Put an item into the queue without blocking.

        Only enqueue the item if a free slot is immediately available.
        Otherwise raise the Full exception.
        '''
        return self.put(item, False)

    def get(self, block=True, timeout=None):
        '''Remove and return an item from the queue.

        If optional args `block` is True and `timeout` is None (the default),
        block if necessary until an item is available. If `timeout` is a
        positive number, it blocks at most `timeout` seconds and raises the
        Empty exception if no item was available within that time. Otherwise
        (`block` is False), return an item if one is immediately available,
        else raise the Empty exception (`timeout` is ignored in that case).
        '''
        self.not_empty.acquire()
        try:
            if not block:
                if not self._qsize():
                    raise Empty
            elif timeout is None:
                while not self._qsize():
                    self.not_empty.wait()
            elif timeout < 0:
                raise ValueError("'timeout' must be a positive number")
            else:
                endtime = _time() + timeout
                while not self._qsize():
                    remaining = endtime - _time()
                    if remaining <= 0.0:
                        raise Empty
                    self.not_empty.wait(remaining)
            item = self._get()
            self.not_full.notify()
            return item
        finally:
            self.not_empty.release()

    def get_nowait(self):
        '''Remove and return an item from the queue without blocking.

        Only get an item if one is immediately available. Otherwise raise the
        Empty exception.
        '''
        return self.get(False)

    # Override these methods to implement other queue organizations (e.g. stack
    # or priority queue).
    # These will only be called with appropriate locks held

    # Initialize the queue representation
    def _init(self, maxsize):
        self.queue = deque()

    def _qsize(self, len=len):
        return len(self.queue)

    # Put a new item in the queue
    def _put(self, item):
        self.queue.append(item)

    # Get an item from the queue
    def _get(self):
        return self.queue.popleft()


class PriorityQueue(Queue):
    '''Variant of Queue that retrieves open entries in priority order (lowest
    first).

    Entries are typically of the form (priority number, data).
    '''

    def _init(self, maxsize):
        self.queue = []

    def _qsize(self, len=len):
        return len(self.queue)

    def _put(self, item, heappush=heapq.heappush):
        heappush(self.queue, item)

    def _get(self, heappop=heapq.heappop):
        return heappop(self.queue)

class LifoQueue(Queue):
    '''Variant of Queue that retrieves most recently added entries first.'''
    def _init(self, maxsize):
        self.queue = []

    def _qsize(self, len=len):
        return len(self.queue)

    def _put(self, item):
        self.queue.append(item)

    def _get(self):
        return self.queue.pop()



