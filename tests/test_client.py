"""Synthetic protocol integration; urlopen is replaced, no live credentials."""
import base64
import gzip
import io
import json
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.parse import urlsplit

from nbmap.client import Client, safe_error
from nbmap.acquisition import collect_month
from nbmap.archive import RideArchive
from nbmap.storage import read_json
from nbmap.vendor import ninebot_api as api
from nbmap.vendor import ninebot_crypto as crypto


class Response(io.BytesIO):
    def __init__(self, payload):
        super().__init__(gzip.compress(json.dumps(payload).encode()))
        self.headers = {"Content-Encoding": "gzip"}


class ProtocolTests(unittest.TestCase):
    def test_login_gzip_encrypted_pagination_export_and_refresh(self):
        original_build = crypto.build_request
        state = {}
        calls = []

        def build(inner):
            result = original_build(inner)
            state["inner"] = json.loads(inner)
            state["secrets"] = result[1]
            return result

        def fake_http(request, timeout):
            path = urlsplit(request.full_url).path
            calls.append(path)
            if path in (api.PATH_PASSPORT_LOGIN, api.PATH_PASSPORT_REFRESH):
                body = json.loads(request.data)
                if path == api.PATH_PASSPORT_LOGIN:
                    self.assertEqual(body["password"], "synthetic-password")
                return Response({"resultCode": "90000", "resultDesc": "success", "data": {
                    "access_token": "synthetic-access", "refresh_token": "synthetic-refresh",
                    "uuid": "synthetic-uuid", "accessTokenValidity": int(time.time() * 1000) + 3600000}})
            inner = state["inner"]
            if path == api.PATH_BIZ_LOGIN:
                data = {"uid": "synthetic-business"}
            elif path == api.PATH_VEHICLES:
                data = {"vehicles": [{"wnumber": "SYNTHETIC-SN", "vehicle_name": "fixture"}]}
            elif path == api.PATH_TRAVEL_LIST:
                self.assertEqual(inner["wnumber"], "SYNTHETIC-SN")
                self.assertEqual(inner["month"], "202609")
                page = int(inner["page"])
                ids = range(20) if page == 1 else range(20, 25)
                data = {"times": 25, "list": [{"travel_id": str(i)} for i in ids]}
            elif path == api.PATH_TRAVEL_INFO:
                data = {"travel_id": inner["travel_id"], "trail": "116,39,12;116.1,39.1,0"}
            else:
                raise AssertionError("Unexpected network path: " + path)
            secrets = state["secrets"]
            key = crypto.derive_key(*(secrets[k].encode() for k in ("kd1", "kd2", "kd3", "kd4")))
            wrapped = json.dumps({"data": crypto.android_b64(json.dumps({"code": 1, "data": data}).encode())}).encode()
            return Response({"r": base64.b64encode(crypto._aes_cbc_encrypt(key, wrapped)).decode()})

        with tempfile.TemporaryDirectory() as d, patch.object(crypto, "build_request", side_effect=build), \
                patch.object(api.urllib.request, "urlopen", side_effect=fake_http):
            client = Client(Path(d) / "private", interval=0)
            client.login("synthetic-user", "synthetic-password")
            self.assertEqual(client.vehicles()[0]["wnumber"], "SYNTHETIC-SN")
            report = collect_month(client, "SYNTHETIC-SN", "202609", RideArchive.for_vehicle(Path(d) / "data", "SYNTHETIC-SN"))
            self.assertEqual(report["listed_rides"], 25)
            self.assertTrue(report["list_complete"])
            self.assertEqual(report["coordinate_points"], 50)
            self.assertEqual(calls.count(api.PATH_TRAVEL_LIST), 2)
            client.tokens["accessTokenValidity"] = "0"
            client.vehicles()
            self.assertIn(api.PATH_PASSPORT_REFRESH, calls)
            self.assertEqual(calls.count(api.PATH_BIZ_LOGIN), 2)
            token_path = Path(d) / "private/tokens.json"
            self.assertNotIn("password", token_path.read_text())
            self.assertEqual(token_path.stat().st_mode & 0o777, 0o600)
            for path in (Path(d) / "data").rglob("*.json"):
                self.assertNotIn("synthetic-access", path.read_text())

    def test_upstream_error_does_not_echo_credentials(self):
        result = safe_error(RuntimeError("server code=123 message=secret-phone secret-token"))
        self.assertIn("123", result)
        self.assertNotIn("secret", result)


if __name__ == "__main__":
    unittest.main()
