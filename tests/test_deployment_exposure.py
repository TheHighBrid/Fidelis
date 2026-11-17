"""Conservative Compose local-publication audit regressions."""
import importlib.util
from pathlib import Path
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "check_deployment_exposure.py"
spec = importlib.util.spec_from_file_location("exposure_audit", SCRIPT)
audit = importlib.util.module_from_spec(spec)
spec.loader.exec_module(audit)


class ComposeExposureAuditTests(unittest.TestCase):
    def test_ipv4_loopback(self):
        self.assertEqual(audit.check_compose('services:\n  app:\n    ports:\n      - "127.0.0.1:8080:8080"\n'), [])

    def test_ipv6_loopback(self):
        self.assertEqual(audit.check_compose("services:\n  app:\n    ports:\n      - '[::1]:8080:8080'\n"), [])

    def test_wildcard_and_implicit_bind_rejected(self):
        for mapping in ("8080:8080", "0.0.0.0:8080:8080", "[::]:8080:8080"):
            with self.subTest(mapping=mapping):
                self.assertTrue(audit.check_compose(f"ports:\n  - '{mapping}'\n"))

    def test_unknown_long_syntax_rejected(self):
        self.assertTrue(audit.check_compose("ports:\n  - target: 8080\n    published: 8080\n"))

    def test_host_network_rejected(self):
        config = "services:\n  app:\n    network_mode: host\n    ports:\n      - '127.0.0.1:8080:8080'\n"
        self.assertTrue(any("network mode" in error for error in audit.check_compose(config)))

    def test_dynamic_network_rejected(self):
        config = "services:\n  app:\n    network_mode: ${NETWORK_MODE}\n    ports:\n      - '127.0.0.1:8080:8080'\n"
        self.assertTrue(any("network mode" in error for error in audit.check_compose(config)))

    def test_external_include_rejected(self):
        config = "include:\n  - other.yml\nservices:\n  app:\n    ports:\n      - '127.0.0.1:8080:8080'\n"
        self.assertTrue(any("external Compose" in error for error in audit.check_compose(config)))

    def test_inline_ports_rejected(self):
        config = "services:\n  app:\n    ports: ['0.0.0.0:8080:8080']\n"
        self.assertTrue(any("inline ports" in error for error in audit.check_compose(config)))

    def test_interpolated_port_rejected(self):
        config = "ports:\n  - '${HOST_IP}:8080:8080'\n"
        self.assertTrue(any("interpolated" in error for error in audit.check_compose(config)))\n\n    def test_no_ports_is_unverified(self):
        self.assertTrue(audit.check_compose("services:\n  app:\n    image: fidelis\n"))

    def test_multiple_services_all_checked(self):
        self.assertEqual(len(audit.check_compose(
            'services:\n  a:\n    ports:\n      - "127.0.0.1:8080:8080"\n'
            '  b:\n    ports:\n      - "80:8080"\n'
        )), 1)


if __name__ == "__main__":
    unittest.main()
