"""Run failure callbacks after their worker has exited the exception handler."""
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'Utils'))
from switch_tool import gui


class DeferredRoot:
    def __init__(self):
        self.callbacks = []

    def after(self, delay, callback, *args):
        self.callbacks.append((callback, args))

    def drain(self):
        while self.callbacks:
            callback, args = self.callbacks.pop(0)
            callback(*args)


def variable(value):
    return SimpleNamespace(get=lambda: value)


class ToolboxErrorCallbackTests(unittest.TestCase):
    def test_all_four_worker_failures_show_the_original_error_after_worker_exit(self):
        for operation in ('generic', 'split', 'split_each', 'slim'):
            with self.subTest(operation=operation), tempfile.TemporaryDirectory() as folder:
                root = DeferredRoot()
                states = []
                app = SimpleNamespace(
                    root=root, set_running=states.append, log=lambda *_: None,
                    _log_separator=lambda *_: None,
                    split_path_var=variable(folder), split_parts_var=variable(2),
                    split_title_var=variable('title'), split_price_var=variable('price1'),
                    split_overwrite_var=variable(False), split_each_path_var=variable(folder),
                    split_each_title_var=variable('title'), split_each_overwrite_var=variable(False),
                    slim_path_var=variable(folder), slim_keep_var=variable(4),
                    slim_overwrite_var=variable(False),
                )
                error = f'{operation} original error'

                def fail(*args, **kwargs):
                    raise RuntimeError(error)

                def thread(target, daemon):
                    return SimpleNamespace(start=target)

                with patch.object(gui.threading, 'Thread', side_effect=thread), \
                     patch.object(gui.messagebox, 'showerror') as showerror, \
                     patch.object(gui.split_by_title_mod, 'collect_csv_files_split', side_effect=fail), \
                     patch.object(gui.slim_src_links_mod, 'slim_src_links_target', side_effect=fail):
                    if operation == 'generic':
                        gui.SwitchToolGui.run_operation(app, 'operation', fail, folder)
                    elif operation == 'split':
                        gui.SwitchToolGui._run_split(app)
                    elif operation == 'split_each':
                        gui.SwitchToolGui._run_split_each(app)
                    else:
                        gui.SwitchToolGui._run_src_slim(app)
                    showerror.assert_not_called()
                    self.assertEqual(states, [True])
                    root.drain()
                    showerror.assert_called_once_with('运行失败', error)
                    self.assertEqual(states, [True, False])


if __name__ == '__main__':
    unittest.main()
