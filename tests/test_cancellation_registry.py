import unittest
from concurrent.futures import ThreadPoolExecutor
from threading import Event, Thread

from fidelis.studio.cancellation import CancellationRegistry, CancellationRequested


class CancellationTests(unittest.TestCase):
    def setUp(self):
        self.registry = CancellationRegistry()
        self.registry.register("j1", "alice")

    def test_owner_only(self):
        for owner in ("bob", ""):
            with self.assertRaises(PermissionError):
                self.registry.request("j1", owner)
            with self.assertRaises(PermissionError):
                self.registry.is_requested("j1", owner)

    def test_idempotent(self):
        self.assertFalse(self.registry.is_requested("j1", "alice"))
        self.assertFalse(self.registry.request("j1", "alice").already_requested)
        self.assertTrue(self.registry.request("j1", "alice").already_requested)
        self.assertTrue(self.registry.is_requested("j1", "alice"))

    def test_reuse_after_unregister(self):
        self.registry.request("j1", "alice")
        self.registry.unregister("j1", "alice")
        self.registry.register("j1", "bob")
        self.assertFalse(self.registry.is_requested("j1", "bob"))

    def test_concurrent_requests(self):
        with ThreadPoolExecutor(max_workers=16) as pool:
            receipts = list(pool.map(
                lambda _: self.registry.request("j1", "alice"), range(64)
            ))
        self.assertEqual(sum(not r.already_requested for r in receipts), 1)

    def test_checkpoint_only_aborts_after_request(self):
        self.registry.checkpoint("j1", "alice")
        self.registry.request("j1", "alice")
        with self.assertRaises(CancellationRequested) as raised:
            self.registry.checkpoint("j1", "alice")
        self.assertEqual(str(raised.exception), "j1")

    def test_checkpoint_enforces_owner(self):
        self.registry.request("j1", "alice")
        with self.assertRaises(PermissionError):
            self.registry.checkpoint("j1", "bob")
        with self.assertRaises(PermissionError):
            self.registry.checkpoint("missing", "alice")

    def test_checkpoint_clears_on_reuse(self):
        self.registry.request("j1", "alice")
        self.registry.unregister("j1", "alice")
        self.registry.register("j1", "bob")
        self.registry.checkpoint("j1", "bob")

    def test_handle_observes_cancellation(self):
        handle = self.registry.register("j2", "alice")
        handle.checkpoint()
        self.registry.request("j2", "alice")
        with self.assertRaises(CancellationRequested):
            handle.checkpoint()

    def test_stale_handle_cannot_checkpoint_reused_job_same_owner(self):
        handle = self.registry.register("j2", "alice")
        handle.unregister()
        replacement = self.registry.register("j2", "alice")
        self.registry.request("j2", "alice")
        with self.assertRaises(PermissionError):
            handle.checkpoint()
        with self.assertRaises(CancellationRequested):
            replacement.checkpoint()

    def test_stale_handle_cannot_unregister_reused_job(self):
        handle = self.registry.register("j2", "alice")
        handle.unregister()
        replacement = self.registry.register("j2", "alice")
        with self.assertRaises(PermissionError):
            handle.unregister()
        replacement.checkpoint()
        replacement.unregister()
        with self.assertRaises(PermissionError):
            replacement.checkpoint()

    def test_handle_can_request_and_inspect_its_own_registration(self):
        handle = self.registry.register("j2", "alice")
        self.assertFalse(handle.is_requested())
        self.assertFalse(handle.request().already_requested)
        self.assertTrue(handle.request().already_requested)
        self.assertTrue(handle.is_requested())
        with self.assertRaises(CancellationRequested):
            handle.checkpoint()

    def test_stale_handle_cannot_cancel_reused_job(self):
        stale = self.registry.register("j2", "alice")
        stale.unregister()
        current = self.registry.register("j2", "alice")
        with self.assertRaises(PermissionError):
            stale.request()
        with self.assertRaises(PermissionError):
            stale.is_requested()
        self.assertFalse(current.is_requested())
        current.checkpoint()

    def test_stale_handle_cannot_cancel_new_owner(self):
        stale = self.registry.register("j2", "alice")
        stale.unregister()
        current = self.registry.register("j2", "bob")
        with self.assertRaises(PermissionError):
            stale.request()
        self.assertFalse(current.is_requested())

    def test_concurrent_stale_request_does_not_cancel_replacement(self):
        stale = self.registry.register("j2", "alice")
        stale.unregister()
        current = self.registry.register("j2", "alice")
        def attempt(_):
            try:
                stale.request()
            except PermissionError:
                return False
            return True
        with ThreadPoolExecutor(max_workers=16) as pool:
            self.assertFalse(any(pool.map(attempt, range(64))))
        self.assertFalse(current.is_requested())

    def test_wait_times_out_without_cancellation(self):
        handle = self.registry.register("j2", "alice")
        self.assertFalse(handle.wait_requested(0.001))
        self.assertFalse(handle.is_requested())

    def test_wait_wakes_on_cancel(self):
        handle = self.registry.register("j2", "alice")
        started = Event()
        observed = []
        def waiter():
            started.set()
            observed.append(handle.wait_requested(2))
        thread = Thread(target=waiter)
        thread.start()
        self.assertTrue(started.wait(1))
        handle.request()
        thread.join(2)
        self.assertFalse(thread.is_alive())
        self.assertEqual(observed, [True])

    def test_unregister_wakes_waiter_and_invalidates_stale_handle(self):
        handle = self.registry.register("j2", "alice")
        started = Event()
        observed = []
        def waiter():
            started.set()
            try:
                observed.append(handle.wait_requested(2))
            except PermissionError:
                observed.append("stale")
        thread = Thread(target=waiter)
        thread.start()
        self.assertTrue(started.wait(1))
        handle.unregister()
        replacement = self.registry.register("j2", "alice")
        thread.join(2)
        self.assertEqual(observed, ["stale"])
        self.assertFalse(replacement.wait_requested(0))

    def test_wait_rejects_invalid_timeout(self):
        handle = self.registry.register("j2", "alice")
        for timeout in (-1, float("inf"), float("nan"), True, "1"):
            with self.subTest(timeout=timeout), self.assertRaises(ValueError):
                handle.wait_requested(timeout)


    def test_close_invalidates_handles_and_rejects_new_work(self):
        handle = self.registry.register("j2", "alice")
        self.registry.close()
        self.registry.close()
        for operation in (handle.checkpoint, handle.request, handle.is_requested,
                          handle.unregister):
            with self.subTest(operation=operation.__name__), self.assertRaises(PermissionError):
                operation()
        with self.assertRaises(RuntimeError):
            self.registry.register("j3", "alice")

    def test_close_wakes_waiters_without_claiming_cancellation(self):
        handle = self.registry.register("j2", "alice")
        started = Event()
        result = []
        def waiter():
            started.set()
            try:
                result.append(handle.wait_requested(2))
            except PermissionError:
                result.append("closed")
        thread = Thread(target=waiter)
        thread.start()
        self.assertTrue(started.wait(1))
        self.registry.close()
        thread.join(2)
        self.assertFalse(thread.is_alive())
        self.assertEqual(result, ["closed"])

    def test_close_is_safe_after_a_prior_request(self):
        handle = self.registry.register("j2", "alice")
        handle.request()
        self.registry.close()
        with self.assertRaises(PermissionError):
            handle.wait_requested(0)

    def test_close_invalidates_multiple_independent_registrations(self):
        first = self.registry.register("j2", "alice")
        second = self.registry.register("j3", "bob")
        self.registry.close()
        for handle in (first, second):
            with self.assertRaises(PermissionError):
                handle.checkpoint()

    def test_duplicate_registration(self):
        with self.assertRaises(ValueError):
            self.registry.register("j1", "alice")

    def test_invalid_ids(self):
        with self.assertRaises(ValueError):
            self.registry.register("", "alice")
        with self.assertRaises(ValueError):
            self.registry.register("j2", "")


if __name__ == "__main__":
    unittest.main()
