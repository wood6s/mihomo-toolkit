"""Mihomo controller transport shared by the mode, selector and status commands."""

import json
import os
import sys
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import ProxyHandler, Request, build_opener


DEFAULT_API = "http://127.0.0.1:9090"


class ControllerError(Exception):
    pass


class ControllerNotFound(ControllerError):
    pass


def controller_secret(api):
    configured = os.environ.get("MIHOMO_SECRET_FILE")
    if configured:
        path = Path(configured).expanduser()
    elif api == DEFAULT_API:
        config_home = os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config"
        path = Path(config_home) / "mihomo/secret"
    else:
        return None
    try:
        secret = path.read_text(encoding="ascii").rstrip("\r\n")
    except FileNotFoundError:
        if not configured:
            return None
        raise ControllerError("找不到 MIHOMO_SECRET_FILE 指定的密钥文件。") from None
    except (OSError, UnicodeError):
        raise ControllerError("无法读取 Mihomo 控制接口密钥文件，请检查内容和权限。") from None
    if not secret or not secret.isprintable():
        raise ControllerError("Mihomo 控制接口密钥文件应只包含一行密钥。")
    return secret


class ControllerAPI:
    def __init__(self, api):
        self.api = api.rstrip("/")
        self.secret = controller_secret(self.api)
        self.opener = build_opener(ProxyHandler({}))

    def request(self, method, path, payload=None):
        data = None if payload is None else json.dumps(payload).encode("utf-8")
        request = Request(self.api + path, data=data, method=method,
                          headers={"Content-Type": "application/json"})
        if self.secret:
            request.add_unredirected_header("Authorization", "Bearer " + self.secret)
        try:
            with self.opener.open(request, timeout=5) as response:
                body = response.read()
            result = json.loads(body) if body else {}
            if not isinstance(result, dict):
                raise ControllerError("Mihomo 控制接口返回了无效数据。")
            return result
        except HTTPError as error:
            if error.code == 401:
                raise ControllerError("Mihomo 控制接口认证失败（HTTP 401），请检查管理密钥文件。") from error
            failure = ControllerNotFound if error.code == 404 else ControllerError
            raise failure(f"Mihomo 控制接口 {method} {path} 返回 HTTP {error.code}。") from error
        except (URLError, OSError, TimeoutError) as error:
            raise ControllerError("无法连接 Mihomo 控制接口，请检查服务及 MIHOMO_API。") from error
        except (ValueError, UnicodeError) as error:
            raise ControllerError("Mihomo 控制接口返回的 JSON 无效。") from error

    def get_group(self, group, fallback=None):
        try:
            result = self.request("GET", "/proxies/" + quote(group, safe=""))
        except ControllerNotFound:
            if not fallback or fallback == group:
                raise
            return self.get_group(fallback)
        result["name"] = group
        return result


def main(args):
    try:
        client = ControllerAPI(os.environ.get("MIHOMO_API") or DEFAULT_API)
        if args[:1] == ["get"] and len(args) in (2, 3):
            print(json.dumps(client.get_group(*args[1:])))
        elif args[:1] == ["set"] and len(args) == 3:
            client.request("PUT", "/proxies/" + quote(args[1], safe=""), {"name": args[2]})
        else:
            return 2
    except ControllerError as error:
        print(error, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
