import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

from cdp.auth.utils.jwt import JwtOptions, generate_jwt


API_HOST = "api.coinbase.com"
REQUEST_METHOD = "GET"
ENV_PATH = Path(__file__).with_name(".env")


def load_repo_env() -> None:
    if not ENV_PATH.exists():
        return

    for raw_line in ENV_PATH.read_text().splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue

        key, value = line.split("=", 1)
        key = key.strip()
        if key not in {"COINBASE_REST_KEY_ID", "COINBASE_REST_KEY_SECRET"}:
            continue
        if key in os.environ:
            continue

        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
            value = value[1:-1]
        os.environ[key] = value


def require_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


def require_account_uuid() -> str:
    if len(sys.argv) != 2 or not sys.argv[1].strip():
        raise RuntimeError("Usage: python get_account.py <account_uuid>")
    return sys.argv[1].strip()


def build_jwt(request_path: str) -> str:
    return generate_jwt(
        JwtOptions(
            api_key_id=require_env("COINBASE_REST_KEY_ID"),
            api_key_secret=require_env("COINBASE_REST_KEY_SECRET"),
            request_method=REQUEST_METHOD,
            request_host=API_HOST,
            request_path=request_path,
            expires_in=120,
        )
    )


def fetch_account(account_uuid: str, jwt_token: str) -> str:
    request_path = f"/api/v3/brokerage/accounts/{account_uuid}"
    request_url = f"https://{API_HOST}{request_path}"
    request = urllib.request.Request(
        request_url,
        headers={
            "Authorization": f"Bearer {jwt_token}",
            "Accept": "application/json",
        },
        method=REQUEST_METHOD,
    )
    with urllib.request.urlopen(request) as response:
        return response.read().decode("utf-8")


def main() -> int:
    try:
        load_repo_env()
        account_uuid = require_account_uuid()
        request_path = f"/api/v3/brokerage/accounts/{account_uuid}"
        body = fetch_account(account_uuid, build_jwt(request_path))
        parsed = json.loads(body)
        print(json.dumps(parsed))
        return 0
    except urllib.error.HTTPError as exc:
        error_body = exc.read().decode("utf-8", errors="replace")
        print(error_body, file=sys.stderr)
        return 1
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
