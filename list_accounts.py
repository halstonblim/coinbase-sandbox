import argparse
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from cdp.auth.utils.jwt import JwtOptions, generate_jwt


API_HOST = "api.coinbase.com"
REQUEST_METHOD = "GET"
REQUEST_PATH = "/api/v3/brokerage/accounts"
REQUEST_URL = f"https://{API_HOST}{REQUEST_PATH}"
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


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="List Coinbase Advanced Trade accounts.")
    parser.add_argument("--limit", type=int, help="Accounts per page (default 49, max 250).")
    parser.add_argument("--cursor", help="Pagination cursor returned by a previous response.")
    parser.add_argument(
        "--retail-portfolio-id",
        help="Deprecated portfolio filter. Only relevant for legacy keys.",
    )
    return parser.parse_args()


def build_jwt() -> str:
    return generate_jwt(
        JwtOptions(
            api_key_id=require_env("COINBASE_REST_KEY_ID"),
            api_key_secret=require_env("COINBASE_REST_KEY_SECRET"),
            request_method=REQUEST_METHOD,
            request_host=API_HOST,
            request_path=REQUEST_PATH,
            expires_in=120,
        )
    )


def list_accounts(
    jwt_token: str,
    limit: int | None = None,
    cursor: str | None = None,
    retail_portfolio_id: str | None = None,
) -> str:
    query_params: dict[str, str | int] = {}
    if limit is not None:
        query_params["limit"] = limit
    if cursor:
        query_params["cursor"] = cursor
    if retail_portfolio_id:
        query_params["retail_portfolio_id"] = retail_portfolio_id

    request_url = REQUEST_URL
    if query_params:
        request_url = f"{request_url}?{urllib.parse.urlencode(query_params)}"

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
        args = parse_args()
        body = list_accounts(
            build_jwt(),
            limit=args.limit,
            cursor=args.cursor,
            retail_portfolio_id=args.retail_portfolio_id,
        )
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
