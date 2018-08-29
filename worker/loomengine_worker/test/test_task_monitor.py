import unittest
from loomengine_worker.task_monitor import TaskMonitor
from loomengine_utils.test.test_connection import MockConnection


class TestTaskMonitor(unittest.TestCase):

    def setUp(self):
        parser = TaskMonitor.get_parser()
        master_url = 'http://just.a.fake.url'
        args = parser.parse_args(['--task_attempt_id', '123',
                                  '--master_url', master_url])

        mock_connection = MockConnection(master_url)
        mock_filemanager = 'placeholder'
        self.task_monitor = TaskMonitor(
            args=args,
            mock_connection=mock_connection,
            mock_filemanager=mock_filemanager)


if __name__ == '__main__':
    unittest.main()
