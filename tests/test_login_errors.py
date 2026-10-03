import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from nbmap.client import Client, safe_error
from nbmap.__main__ import login
from nbmap.vendor import ninebot_api as api


class LoginErrorTests(unittest.TestCase):
    def test_real_business_success_code_one_and_uid(self):
        with patch.object(api, "_send_encrypted", return_value={"code": 1, "desc": "成功", "data": {"uid": "fixture-uid"}}):
            tokens = {"access_token": "fixture-access"}
            self.assertEqual(api.business_login(tokens, "fixture-device"), "fixture-uid")
            self.assertEqual(tokens["business_uid"], "fixture-uid")

    def test_actual_passport_error_envelope_retains_code_and_description(self):
        response = {"resultCode": "90051", "resultDesc": "sign is null"}
        with tempfile.TemporaryDirectory() as d, patch.object(api, "_passport_post", return_value=response):
            client = Client(d)
            with self.assertRaises(RuntimeError) as raised:
                client.login("13812345678", "synthetic-password")
            message = safe_error(raised.exception)
            self.assertIn("90051", message)
            self.assertIn("sign is null", message)
            self.assertIn("账号认证", message)
            self.assertNotIn("数据已保留", message)
            record = json.loads((Path(d) / "last-error.json").read_text())
            self.assertEqual(record["stage"], "passport_login")
            self.assertNotIn("13812345678", json.dumps(record))

    def test_negative_error_code_and_echoed_secrets_are_handled(self):
        response = {"code": -9, "msg": "password error synthetic-password for 13812345678"}
        with tempfile.TemporaryDirectory() as d, patch.object(api, "_passport_post", return_value=response):
            with self.assertRaises(RuntimeError) as raised:
                Client(d).login("13812345678", "synthetic-password")
            message = safe_error(raised.exception)
            self.assertIn("-9", message)
            self.assertIn("password error", message)
            self.assertNotIn("synthetic-password", message)
            self.assertNotIn("13812345678", message)

    def test_resultcode_success_is_accepted(self):
        with patch.object(api, "_passport_post", return_value={"resultCode": "0", "data": {
            "access_token": "fake-access", "refresh_token": "fake-refresh"}}):
            self.assertEqual(api.passport_login("user", "password")["access_token"], "fake-access")

    def test_observed_90000_success_envelope_is_accepted(self):
        for code in (90000, "90000"):
            with self.subTest(code=code), patch.object(api, "_passport_post", return_value={
                "resultCode": code, "resultDesc": "success", "data": {
                    "access_token": "fake-access", "refresh_token": "fake-refresh"}}):
                self.assertEqual(api.passport_login("user", "password")["access_token"], "fake-access")

    def test_success_text_does_not_override_an_error_code(self):
        with patch.object(api, "_passport_post", return_value={"resultCode": "90051", "resultDesc": "success"}):
            with self.assertRaises(RuntimeError):
                api.passport_login("user", "password")

    def test_passport_success_code_does_not_apply_to_business(self):
        from nbmap.errors import check_response
        with self.assertRaises(RuntimeError):
            check_response({"code": 90000, "message": "success"})

    def test_refresh_accepts_passport_success_envelope(self):
        with patch.object(api, "_passport_post", return_value={"resultCode": "90000", "resultDesc": "success", "data": {
            "access_token": "new-access", "refresh_token": "new-refresh"}}):
            self.assertEqual(api.passport_refresh({"access_token": "old", "refresh_token": "old-refresh"})["access_token"], "new-access")

    def test_successful_response_survives_parse_failure_without_password(self):
        response = {"resultCode": "90000", "resultDesc": "success", "data": {
            "unexpected_session": "fixture", "password": "synthetic-password", "echo": "synthetic-password"}}
        with tempfile.TemporaryDirectory() as d, patch.object(api, "_passport_post", return_value=response):
            with self.assertRaises(RuntimeError) as raised:
                Client(d).login("fixture-user", "synthetic-password")
            self.assertIn("无需重复输入密码", safe_error(raised.exception))
            path = Path(d) / "passport-session.json"
            self.assertNotIn("synthetic-password", path.read_text())
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)

    def test_saved_successful_session_can_be_recovered_without_network(self):
        from nbmap.storage import write_json
        with tempfile.TemporaryDirectory() as d:
            write_json(Path(d) / "passport-session.json", {"username": "fixture-user", "area": "86", "response": {
                "resultCode": "90000", "resultDesc": "success", "data": {"access_token": "fixture-access"}}})
            client = Client(d)
            with patch.object(api.urllib.request, "urlopen", side_effect=AssertionError("network forbidden")):
                client.recover_session()
            self.assertEqual(client.tokens["access_token"], "fixture-access")
            self.assertTrue((Path(d) / "tokens.json").exists())

    def test_business_failure_states_that_passport_succeeded(self):
        with tempfile.TemporaryDirectory() as d, patch.object(api, "passport_login", return_value={
                "access_token": "fake-access"}), patch.object(api, "business_login", side_effect=RuntimeError(
                    "business /user/user/login: missing encrypted response")):
            with self.assertRaises(RuntimeError) as raised:
                Client(d).login("user", "password")
            message = safe_error(raised.exception)
            self.assertIn("账号认证已通过", message)
            self.assertIn("车辆服务", message)
            self.assertTrue((Path(d) / "tokens.json").exists())

    def test_login_no_longer_prompts_country_code(self):
        client = Mock()
        with patch("sys.stdin.isatty", return_value=True), patch("builtins.input", return_value="13812345678") as ask, \
                patch("getpass.getpass", return_value="fake-password"), patch("sys.stdout", new_callable=io.StringIO):
            login(client)
        self.assertEqual(ask.call_count, 1)
        self.assertEqual(client.login.call_args.args, ("13812345678", "fake-password", "86"))


if __name__ == "__main__":
    unittest.main()
