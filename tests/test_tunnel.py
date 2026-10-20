"""Tests for explicitly managed public MCP tunnel process handling."""

from __future__ import annotations

import io
import subprocess
import unittest
from unittest import mock

from neezy_backend.tunnel import CloudflareQuickTunnel, TunnelError


class FakeProcess:
    def __init__(self, output: str) -> None:
        self.stdout = io.StringIO(output)
        self.returncode = None
        self.terminated = False

    def poll(self):
        return self.returncode

    def terminate(self):
        self.terminated = True
        self.returncode = 0

    def wait(self, timeout=None):
        if self.returncode is None:
            raise subprocess.TimeoutExpired("cloudflared", timeout)
        return self.returncode

    def kill(self):
        self.returncode = -9


class TunnelTests(unittest.TestCase):
    def test_start_parses_https_url_and_uses_safe_argv(self) -> None:
        process = FakeProcess(
            "INFO tunnel ready at https://sample-name.trycloudflare.com\n"
        )
        tunnel = CloudflareQuickTunnel()
        with (
            mock.patch(
                "neezy_backend.tunnel.shutil.which", return_value="/bin/cloudflared"
            ),
            mock.patch(
                "neezy_backend.tunnel.subprocess.Popen", return_value=process
            ) as popen,
        ):
            tunnel.start("cloudflared", 8766)
            self.assertEqual(
                tunnel.wait_for_url(1.0), "https://sample-name.trycloudflare.com"
            )
            args, kwargs = popen.call_args
            self.assertEqual(args[0][0], "/bin/cloudflared")
            self.assertIn("http://127.0.0.1:8766", args[0])
            self.assertIn("127.0.0.1:8766", args[0])
            self.assertFalse(kwargs["shell"])
            self.assertTrue(tunnel.running)
            tunnel.stop()
        self.assertTrue(process.terminated)
        self.assertFalse(tunnel.running)

    def test_missing_executable_fails_without_starting_process(self) -> None:
        tunnel = CloudflareQuickTunnel()
        with (
            mock.patch("neezy_backend.tunnel.shutil.which", return_value=None),
            mock.patch("neezy_backend.tunnel.subprocess.Popen") as popen,
        ):
            with self.assertRaisesRegex(TunnelError, "not found"):
                tunnel.start("cloudflared", 8766)
        popen.assert_not_called()

    def test_rejects_invalid_local_port(self) -> None:
        with self.assertRaises(ValueError):
            CloudflareQuickTunnel().start("cloudflared", 0)


if __name__ == "__main__":
    unittest.main()
