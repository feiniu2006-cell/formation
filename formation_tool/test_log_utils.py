import unittest

from formation_tool.utils import log_utils


class LogUtilsTests(unittest.TestCase):
    def tearDown(self):
        log_utils.reset_log_writer()

    def test_emit_uses_configured_writer(self):
        messages = []
        log_utils.set_log_writer(messages.append)
        log_utils.print_write_complete(3, "target_table")

        self.assertEqual(messages, ["写入完成：3 条 -> target_table"])


if __name__ == "__main__":
    unittest.main()
