"""Regression coverage for the legacy HTTP listener's safe default binding."""
import ast
import pathlib
import unittest

SOURCE = pathlib.Path(__file__).resolve().parents[1] / "scripts" / "web-ui.py"


class LoopbackBindingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tree = ast.parse(SOURCE.read_text(encoding="utf-8"))

    def test_run_server_defaults_to_loopback(self):
        functions = [node for node in self.tree.body
                     if isinstance(node, ast.FunctionDef) and node.name == "run_server"]
        self.assertEqual(len(functions), 1)
        defaults = functions[0].args.defaults
        self.assertEqual(ast.literal_eval(defaults[-1]), "127.0.0.1")

    def test_cli_defaults_to_loopback_without_host_environment_override(self):
        main = next(node for node in self.tree.body
                    if isinstance(node, ast.If)
                    and isinstance(node.test, ast.Compare)
                    and isinstance(node.test.left, ast.Name)
                    and node.test.left.id == "__name__")
        bind_calls = [node for node in ast.walk(main)
                      if isinstance(node, ast.Call)
                      and isinstance(node.func, ast.Attribute)
                      and node.func.attr == "add_argument"
                      and any(isinstance(arg, ast.Constant) and arg.value == "--bind"
                              for arg in node.args)]
        self.assertEqual(len(bind_calls), 1)
        default = next(kw.value for kw in bind_calls[0].keywords if kw.arg == "default")
        self.assertEqual(ast.literal_eval(default), "127.0.0.1")

    def test_explicit_bind_option_is_retained(self):
        source = SOURCE.read_text(encoding="utf-8")
        self.assertIn('"-b", "--bind", "--host"', source)
        self.assertIn('run_server(port=args.port, host=args.bind)', source)


if __name__ == "__main__":
    unittest.main()
