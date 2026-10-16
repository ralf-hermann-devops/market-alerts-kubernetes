import unittest

from services.worker.app.worker import PENDING_MIN_IDLE_MS, read_messages


class FakeRedis:
    def __init__(self, autoclaim_result: tuple, new_messages: list | None = None):
        self.autoclaim_result = autoclaim_result
        self.new_messages = new_messages or []
        self.autoclaim_args = None
        self.readgroup_args = None

    def xautoclaim(self, *args, **kwargs):
        self.autoclaim_args = (args, kwargs)
        return self.autoclaim_result

    def xreadgroup(self, *args, **kwargs):
        self.readgroup_args = (args, kwargs)
        return self.new_messages


class ReadMessagesTests(unittest.TestCase):
    def test_claims_one_bounded_pending_batch_and_then_reads_unread(self):
        pending = [("1-0", {"payload": "old"})]
        client = FakeRedis(("2-0", pending, []))

        messages, cursor, read_pending = read_messages(
            client, "alerts", "workers", "worker-1", "0-0", True
        )

        self.assertEqual(messages, pending)
        self.assertEqual(cursor, "2-0")
        self.assertFalse(read_pending)
        self.assertIsNone(client.readgroup_args)
        self.assertEqual(
            client.autoclaim_args,
            (
                ("alerts", "workers", "worker-1"),
                {
                    "min_idle_time": PENDING_MIN_IDLE_MS,
                    "start_id": "0-0",
                    "count": 10,
                },
            ),
        )

    def test_reads_unread_while_pending_scan_is_in_progress(self):
        unread = [("4-0", {"payload": "first"}), ("5-0", {"payload": "second"})]
        client = FakeRedis(("0-0", [], []), [("alerts", unread)])

        messages, cursor, read_pending = read_messages(
            client, "alerts", "workers", "worker-1", "2-0", False
        )

        self.assertEqual(messages, unread)
        self.assertEqual(cursor, "2-0")
        self.assertTrue(read_pending)
        self.assertEqual(
            client.readgroup_args,
            (
                ("workers", "worker-1", {"alerts": ">"}),
                {"count": 10, "block": 0},
            ),
        )
        self.assertIsNone(client.autoclaim_args)

    def test_waits_for_new_messages_when_pending_scan_is_at_end(self):
        client = FakeRedis(("0-0", [], []))

        messages, cursor, read_pending = read_messages(
            client, "alerts", "workers", "worker-1", "0-0", False
        )

        self.assertEqual(messages, [])
        self.assertEqual(cursor, "0-0")
        self.assertTrue(read_pending)
        self.assertEqual(client.readgroup_args[1]["block"], 5000)

    def test_continues_pending_scan_after_unread_batch(self):
        pending = [("3-0", {"payload": "older"})]
        client = FakeRedis(("4-0", pending, []))

        messages, cursor, read_pending = read_messages(
            client, "alerts", "workers", "worker-1", "2-0", True
        )

        self.assertEqual(messages, pending)
        self.assertEqual(cursor, "4-0")
        self.assertFalse(read_pending)
        self.assertEqual(client.autoclaim_args[1]["start_id"], "2-0")
        self.assertIsNone(client.readgroup_args)


if __name__ == "__main__":
    unittest.main()
