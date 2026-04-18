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
REQUEST_PATH = "/api/v3/brokerage/products"
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
    parser = argparse.ArgumentParser(description="List Coinbase Advanced Trade products.")
    parser.add_argument("--limit", type=int, help="Number of products to return.")
    parser.add_argument("--cursor", help="Pagination cursor from a previous response.")
    parser.add_argument(
        "--product-type",
        choices=["SPOT", "FUTURE"],
        help="Filter by product type.",
    )
    parser.add_argument(
        "--contract-expiry-type",
        choices=["EXPIRING", "PERPETUAL"],
        help="Filter futures by expiry type.",
    )
    parser.add_argument(
        "--product-id",
        action="append",
        dest="product_ids",
        help="Filter to one or more specific product ids. Repeat the flag to add more.",
    )
    parser.add_argument(
        "--search",
        help="Case-insensitive substring filter applied locally to id/name/description fields.",
    )
    parser.add_argument(
        "--nano-perps",
        action="store_true",
        help="Show only products that look like nano perp or perp-style futures.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print the raw JSON response after local filtering.",
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


def fetch_products(
    jwt_token: str,
    limit: int | None = None,
    cursor: str | None = None,
    product_type: str | None = None,
    contract_expiry_type: str | None = None,
    product_ids: list[str] | None = None,
) -> dict:
    query_params: list[tuple[str, str | int]] = []
    if limit is not None:
        query_params.append(("limit", limit))
    if cursor:
        query_params.append(("cursor", cursor))
    if product_type:
        query_params.append(("product_type", product_type))
    if contract_expiry_type:
        query_params.append(("contract_expiry_type", contract_expiry_type))
    if product_ids:
        for product_id in product_ids:
            query_params.append(("product_ids", product_id))

    request_url = REQUEST_URL
    if query_params:
        request_url = f"{request_url}?{urllib.parse.urlencode(query_params, doseq=True)}"

    request = urllib.request.Request(
        request_url,
        headers={
            "Authorization": f"Bearer {jwt_token}",
            "Accept": "application/json",
        },
        method=REQUEST_METHOD,
    )
    with urllib.request.urlopen(request) as response:
        return json.loads(response.read().decode("utf-8"))


def fetch_all_products(
    jwt_token: str,
    limit: int | None = None,
    product_type: str | None = None,
    contract_expiry_type: str | None = None,
    product_ids: list[str] | None = None,
) -> dict:
    first_response = fetch_products(
        jwt_token,
        limit=limit,
        cursor=None,
        product_type=product_type,
        contract_expiry_type=contract_expiry_type,
        product_ids=product_ids,
    )

    all_products = list(first_response.get("products", []))
    pagination = first_response.get("pagination") or {}
    next_cursor = pagination.get("next_cursor")

    while pagination.get("has_next") and next_cursor:
        page = fetch_products(
            jwt_token,
            limit=limit,
            cursor=next_cursor,
            product_type=product_type,
            contract_expiry_type=contract_expiry_type,
            product_ids=product_ids,
        )
        all_products.extend(page.get("products", []))
        pagination = page.get("pagination") or {}
        next_cursor = pagination.get("next_cursor")

    first_response["products"] = all_products
    first_response["num_products"] = len(all_products)
    first_response["pagination"] = {
        "prev_cursor": "",
        "next_cursor": "",
        "has_next": False,
        "has_prev": False,
    }
    return first_response


def filter_products(products: list[dict], search: str | None, nano_perps: bool) -> list[dict]:
    filtered = products
    if nano_perps:
        filtered = [product for product in filtered if is_nano_perp(product)]
    if search:
        needle = search.lower()
        filtered = [product for product in filtered if matches_search(product, needle)]
    return filtered


def is_nano_perp(product: dict) -> bool:
    details = product.get("future_product_details") or {}
    if product.get("product_type") != "FUTURE":
        return False
    return matches_search(product, "nano") and matches_search(product, "perp")


def matches_search(product: dict, needle: str) -> bool:
    details = product.get("future_product_details") or {}
    haystack = " ".join(
        str(value)
        for value in [
            product.get("product_id"),
            product.get("base_name"),
            product.get("quote_name"),
            product.get("about_description"),
            details.get("display_name"),
            details.get("contract_display_name"),
            details.get("group_description"),
            details.get("group_short_description"),
            details.get("contract_code"),
        ]
        if value
    ).lower()
    return needle in haystack


def print_pretty_products(products: list[dict]) -> None:
    if not products:
        print("No matching products found.")
        return

    for product in products:
        details = product.get("future_product_details") or {}
        perpetual = details.get("perpetual_details") or {}

        print(product.get("product_id", "<unknown>"))
        print(f"  name: {pick_first(details.get('display_name'), details.get('contract_display_name'), product.get('base_name'))}")
        contract_code = details.get("contract_code")
        if contract_code:
            print(f"  contract_code: {contract_code}")
        print(f"  type: {product.get('product_type')} / {details.get('contract_expiry_type', 'N/A')}")
        print(f"  status: {product.get('status')} | trading_disabled={product.get('trading_disabled')}")
        print(f"  price: {product.get('price')} {product.get('quote_display_symbol', product.get('quote_currency_id', ''))}".rstrip())
        print(f"  24h volume: {product.get('volume_24h')}")
        print(f"  venue: {details.get('venue', 'N/A')}")
        print(f"  leverage: {perpetual.get('max_leverage', 'N/A')}")
        print(f"  funding_rate: {pick_first(perpetual.get('funding_rate'), details.get('funding_rate'), 'N/A')}")
        print(f"  open_interest: {pick_first(perpetual.get('open_interest'), details.get('open_interest'), 'N/A')}")
        description = pick_first(
            product.get("about_description"),
            details.get("group_short_description"),
            details.get("group_description"),
        )
        if description:
            print(f"  description: {description}")
        print()


def pick_first(*values: object) -> str:
    for value in values:
        if value not in (None, ""):
            return str(value)
    return ""


def main() -> int:
    try:
        load_repo_env()
        args = parse_args()

        product_type = args.product_type
        contract_expiry_type = args.contract_expiry_type
        if args.nano_perps:
            product_type = "FUTURE"
            contract_expiry_type = None

        jwt_token = build_jwt()
        if args.cursor:
            response = fetch_products(
                jwt_token,
                limit=args.limit,
                cursor=args.cursor,
                product_type=product_type,
                contract_expiry_type=contract_expiry_type,
                product_ids=args.product_ids,
            )
        elif args.search or args.nano_perps:
            response = fetch_all_products(
                jwt_token,
                limit=args.limit,
                product_type=product_type,
                contract_expiry_type=contract_expiry_type,
                product_ids=args.product_ids,
            )
        else:
            response = fetch_products(
                jwt_token,
                limit=args.limit,
                cursor=None,
                product_type=product_type,
                contract_expiry_type=contract_expiry_type,
                product_ids=args.product_ids,
            )

        products = response.get("products", [])
        filtered_products = filter_products(products, search=args.search, nano_perps=args.nano_perps)
        response["products"] = filtered_products
        response["num_products"] = len(filtered_products)

        if args.json:
            print(json.dumps(response))
        else:
            print_pretty_products(filtered_products)
            pagination = response.get("pagination") or {}
            if pagination.get("has_next"):
                print(f"next_cursor: {pagination.get('next_cursor', '')}")

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
