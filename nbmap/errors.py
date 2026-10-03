"""Preserve structured failure evidence without persisting response bodies."""
import re


class RemoteFailure(RuntimeError):
    def __init__(self, category, *, code=None, description=None):
        super().__init__(category)
        self.category = category
        self.code = code
        self.description = description


class UserFacingError(RuntimeError):
    """Only contains a sanitized, stage-specific message."""


def redact(text, secrets=()):
    value = str(text or "")
    for secret in sorted({str(s) for s in secrets if s}, key=len, reverse=True):
        value = value.replace(secret, "[已隐藏]")
    value = re.sub(r"(?i)(?:https?://)\S+", "[链接已隐藏]", value)
    value = re.sub(r"(?<!\d)1\d{10}(?!\d)", "[手机号已隐藏]", value)
    value = re.sub(r"(?i)(bearer\s+)\S+", r"\1[已隐藏]", value)
    value = re.sub(r"(?i)((?:access_token|refresh_token|password|token)\s*[:=]\s*)[^\s,;]+", r"\1[已隐藏]", value)
    value = " ".join(value.split())
    value = "".join(c for c in value if c.isprintable())
    return value[:240]


def check_response(response, *, protocol="business"):
    if not isinstance(response, dict):
        raise RemoteFailure("响应不是 JSON 对象")
    # Passport and business APIs use different envelope field names.
    code = response.get("resultCode", response.get("code"))
    description = next((response[k] for k in ("resultDesc", "msg", "message", "desc")
                        if isinstance(response.get(k), str) and response[k]), None)
    if code is None or isinstance(code, bool):
        raise RemoteFailure("响应缺少可识别的状态码", description=description)
    success_codes = {"0", "90000"} if protocol == "passport" else {"0", "1"}
    if str(code) not in success_codes:
        raise RemoteFailure("服务端拒绝请求", code=code, description=description)


def failure_details(exc, secrets=()):
    import json
    import ssl
    import urllib.error
    if isinstance(exc, RemoteFailure):
        return {"category": exc.category, "code": redact(exc.code, secrets) if exc.code is not None else None,
                "description": redact(exc.description, secrets)}
    if isinstance(exc, urllib.error.HTTPError):
        return {"category": "HTTP 请求失败", "code": str(exc.code), "description": "服务器返回 HTTP 错误，未读取响应正文。"}
    if isinstance(exc, urllib.error.URLError):
        reason = exc.reason
        if isinstance(reason, ssl.SSLError):
            description = "TLS 连接失败，请检查网络或代理后重试。"
        elif isinstance(reason, TimeoutError):
            description = "连接超时，请检查网络后重试。"
        else:
            description = "无法连接九号服务，请检查网络或代理后重试。"
        return {"category": "网络错误", "code": None, "description": description}
    if isinstance(exc, TimeoutError):
        return {"category": "网络超时", "code": None, "description": "等待九号响应超时。"}
    if isinstance(exc, (json.JSONDecodeError, UnicodeDecodeError)):
        return {"category": "响应格式异常", "code": None, "description": "服务端没有返回可解析的 JSON，无法判断账号是否正确。"}
    text = str(exc)
    code = re.search(r"(?:code=|HTTP |返回码 )(-?\d+)", text)
    known = {"missing encrypted response": "响应缺少加密数据，可能是接口格式变化。",
             "missing access_token": "服务端未返回登录令牌，无法确认账号认证结果。",
             "invalid JSON": "响应不是可解析的 JSON。",
             "invalid decrypted JSON": "响应解密后不是可解析的 JSON。",
             "missing data field": "响应缺少 data 字段。",
             "missing uid": "响应缺少业务账号标识。"}
    description = next((v for k, v in known.items() if k in text), "未识别的客户端或协议错误；不能据此判断密码是否正确。")
    return {"category": type(exc).__name__, "code": code.group(1) if code else None, "description": description}
