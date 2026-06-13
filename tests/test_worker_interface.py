import unittest

from workers.base import Worker
from workers.mock_worker import MockWorker


class WorkerInterfaceTests(unittest.TestCase):
    def test_mock_worker_conforms_to_worker_protocol(self) -> None:
        self.assertIsInstance(MockWorker(), Worker)

    def test_worker_protocol_declares_only_required_methods(self) -> None:
        protocol_methods = {
            name
            for name, value in Worker.__dict__.items()
            if callable(value) and not name.startswith("_")
        }

        self.assertEqual(
            protocol_methods,
            {"plan", "select_data", "write_code", "draft_answer"},
        )

    def test_mock_worker_has_required_methods(self) -> None:
        worker = MockWorker()

        for method_name in ["plan", "select_data", "write_code", "draft_answer"]:
            with self.subTest(method_name=method_name):
                self.assertTrue(callable(getattr(worker, method_name)))


if __name__ == "__main__":
    unittest.main()
