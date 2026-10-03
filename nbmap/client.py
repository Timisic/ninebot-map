"""Only authentication, owned/shared vehicle list and ride reads are exposed."""
import re
import time
import urllib.error
from datetime import datetime, timezone

from .storage import private_dir, read_json, write_json
from .errors import UserFacingError, failure_details
from .vendor import ninebot_api as api


def safe_error(exc):
    """Never echo upstream bodies, tokens, account numbers or URLs with query strings."""
    if isinstance(exc, UserFacingError):
        return str(exc)
    text = str(exc)
    code = re.search(r"(?:code=|HTTP |返回码 )(-?\d+)", text)
    if "90202" in text or "captcha" in text.lower():
        return "九号要求人机验证。请在官方 App 完成验证后再试；本工具不支持该验证。"
    if isinstance(exc, urllib.error.URLError):
        return "网络连接失败，请检查网络或代理后重试。"
    if not code and ("token" in text.lower() or "登录" in text):
        return "登录状态不可用，请运行 ./run login。"
    return "九号请求未完成" + (f"（返回码 {code.group(1)}）" if code else f"（{type(exc).__name__}）") + "。不能据此判断账号或密码是否正确。"


class Client:
    def __init__(self, config, interval=0.7, progress=None):
        self.config = private_dir(config)
        self.device_id = api.load_config(self.config)["device_id"]
        self.tokens = api.load_tokens(self.config)
        self.interval = interval
        self.last_call = 0.0
        self.progress = progress or (lambda message: None)

    def _save_passport_response(self, response, username, password, area):
        # Keep the successful session locally so schema changes can be repaired
        # without resubmitting a password. Never store password values or fields.
        def clean(value):
            if isinstance(value, dict):
                return {k: clean(v) for k, v in value.items()
                        if not any(term in k.lower() for term in ("password", "passwd", "pwd"))}
            if isinstance(value, list):
                return [clean(v) for v in value]
            if isinstance(value, str):
                return value.replace(password, "[已隐藏]") if password else value
            return value
        write_json(self.config / "passport-session.json", {
            "saved_at": datetime.now(timezone.utc).isoformat(),
            "username": username, "area": area, "response": clean(response)})

    def recover_session(self):
        path = self.config / "passport-session.json"
        if not self.tokens and path.exists():
            saved = read_json(path)
            self.tokens = self._call("passport_parse", api.parse_passport_tokens,
                saved["response"], saved["username"], saved.get("area", "86"))
            api.save_tokens(self.config, self.tokens)

    def _call(self, stage, fn, *args, secrets=(), **kwargs):
        try:
            return fn(*args, **kwargs)
        except UserFacingError:
            raise
        except Exception as exc:
            labels = {"passport_login": "账号认证", "passport_parse": "解析已保存的成功登录响应", "business_login": "连接车辆服务",
                      "refresh": "刷新登录会话", "vehicles": "读取车辆列表",
                      "month": "读取月度行程", "detail": "读取行程详情"}
            sensitive = [*secrets, *(self.tokens.get(k) for k in (
                "access_token", "refresh_token", "username", "phone", "uuid", "business_uid"))]
            info = failure_details(exc, sensitive)
            record = {"timestamp": datetime.now(timezone.utc).isoformat(), "stage": stage,
                      "passport_accepted": bool(self.tokens.get("access_token")) if stage != "passport_login" else False,
                      **info}
            message = f"{labels.get(stage, stage)}失败：{info['category']}"
            if info["code"] is not None:
                message += f"（返回码 {info['code']}）"
            if info["description"]:
                message += f"。服务提示：{info['description']}"
            if stage == "business_login" and record["passport_accepted"]:
                message += "。账号认证已通过，当前失败发生在车辆服务连接阶段；无需先修改密码。"
            elif stage == "passport_login" and "missing access_token" in str(exc):
                message += "。服务端报告认证成功，但登录令牌解析未完成。成功响应已保存在本机，可继续排查，无需重复输入密码。"
            elif stage == "passport_login":
                message += "。本次尚未建立登录会话，也尚未开始获取骑行数据。"
            try:
                write_json(self.config / "last-error.json", record)
                message += "\n脱敏诊断已保存至 .private/last-error.json。"
            except OSError:
                message += "\n诊断文件保存失败，请保留以上提示。"
            raise UserFacingError(message) from None

    def login(self, username, password, area="86"):
        self.progress("[1/2] 正在验证九号账号…")
        self.tokens = self._call("passport_login", api.passport_login, username, password,
                                 area_code=area, secrets=(username, password),
                                 on_success=lambda response: self._save_passport_response(response, username, password, area))
        api.save_tokens(self.config, self.tokens)
        self.progress("[1/2] 账号认证已通过。\n[2/2] 正在连接车辆服务…")
        self._call("business_login", api.business_login, self.tokens, self.device_id, secrets=(username, password))
        api.save_tokens(self.config, self.tokens)

    def session(self):
        self.recover_session()
        if not api.tokens_valid(self.tokens):
            if not self.tokens.get("refresh_token"):
                raise RuntimeError("请先登录")
            self.tokens = self._call("refresh", api.passport_refresh, self.tokens)
            # Re-establish the business session after token rotation.
            self.tokens.pop("business_uid", None)
            api.save_tokens(self.config, self.tokens)
        if not self.tokens.get("business_uid"):
            self._call("business_login", api.business_login, self.tokens, self.device_id)
            api.save_tokens(self.config, self.tokens)

    def _read(self, fn, *args, **kwargs):
        self.session()
        for attempt in range(3):
            time.sleep(max(0, self.interval - (time.monotonic() - self.last_call)))
            self.last_call = time.monotonic()
            try:
                return fn(self.tokens, self.device_id, *args, **kwargs)
            except (urllib.error.URLError, TimeoutError) as exc:
                if isinstance(exc, urllib.error.HTTPError) or attempt == 2:
                    raise
                time.sleep(2 ** attempt)

    def vehicles(self):
        return self._call("vehicles", self._read, api.vehicles)

    def month(self, sn, month, page):
        return self._call("month", self._read, api.travel_list, sn, month, page=str(page))

    def detail(self, sn, ride_id):
        return self._call("detail", self._read, api.travel_detail, sn, ride_id)
