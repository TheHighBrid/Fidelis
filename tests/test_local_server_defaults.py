"""Local network defaults and deployment scaffolding without touching host config."""
from contextlib import redirect_stdout
import importlib.util
import io
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import MagicMock, patch
import yaml

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('fidelis_web_defaults',ROOT/'scripts/web-ui.py')
web=importlib.util.module_from_spec(spec)
spec.loader.exec_module(web)


class LocalDefaultTests(unittest.TestCase):
    def test_default_parser_and_explicit_override(self):
        with patch.dict(os.environ) as env:
            env.pop('HOST',None)
            self.assertEqual(web.build_argument_parser().parse_args([]).bind,'127.0.0.1')
            self.assertEqual(web.build_argument_parser().parse_args(['--bind','0.0.0.0']).bind,'0.0.0.0')
        with patch.dict(os.environ,{'HOST':'localhost'}):
            self.assertEqual(web.build_argument_parser().parse_args([]).bind,'localhost')

    def test_programmatic_launch_passes_loopback_to_socket(self):
        addresses=[]
        class FakeServer:
            allow_reuse_address=False
            def __init__(self,address,handler):addresses.append(address)
            def __enter__(self):return self
            def __exit__(self,*args):return False
            def serve_forever(self):raise KeyboardInterrupt
        with patch.object(web.socketserver,'TCPServer',FakeServer),redirect_stdout(io.StringIO()):
            web.run_server(port=8765)
        self.assertEqual(addresses,[('127.0.0.1',8765)])

    def test_missing_region_dependencies_leave_legacy_get_routes_working(self):
        import sys

        with patch.dict(sys.modules, {'fidelis.studio.http': None}):
            for path in ('/', '/api/models'):
                handler = MagicMock()
                handler.path = path
                handler.dispatch_regions.side_effect = lambda: web.FidelisRequestHandler.dispatch_regions(handler)
                with patch.object(web, 'get_installed_models', return_value=[]):
                    web.FidelisRequestHandler.do_GET(handler)
                handler.send_response.assert_called_once_with(200)
            handler = MagicMock()
            handler.path = '/regions'
            self.assertTrue(web.FidelisRequestHandler.dispatch_regions(handler))
            handler.send_error.assert_called_once_with(503, 'Regional workspace dependencies unavailable')

    def test_compose_publishes_host_loopback_only(self):
        config=yaml.safe_load((ROOT/'docker-compose.yml').read_text())
        ports=config['services']['fidelis']['ports']
        self.assertTrue(ports)
        for binding in ports:
            self.assertEqual(binding.split(':')[0],'127.0.0.1')
        # The container has an explicit network-interface bind for forwarding;
        # host port publication is a separate boundary, not app authentication.
        self.assertIn('"-b", "0.0.0.0"',(ROOT/'Dockerfile').read_text())

    def test_deployment_scaffold_does_not_open_firewall_or_fetch_public_ip(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);log=root/'commands.log'
            for command in ('docker','ufw','curl'):
                script=root/command
                script.write_text('#!/usr/bin/env bash\nprintf "%s %s\\n" "'+command+'" "$*" >> "$FIDELIS_TEST_COMMAND_LOG"\n')
                script.chmod(0o755)
            env={**os.environ,'PATH':str(root)+os.pathsep+os.environ['PATH'],
                 'FIDELIS_TEST_COMMAND_LOG':str(log)}
            result=subprocess.run(['bash',str(ROOT/'deploy/ovh-deploy.sh'),'local'],
                                  env=env,capture_output=True,text=True,check=True)
            calls=log.read_text().splitlines()
            self.assertEqual(calls,['docker compose down','docker compose build','docker compose up -d'])
            self.assertIn('http://127.0.0.1:8080',result.stdout)
            self.assertIn('not an authenticated public deployment',result.stdout)


if __name__=='__main__':unittest.main()
