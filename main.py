import json
import time
import uuid
import urllib.parse
from copy import deepcopy
from typing import Any, Dict, List, Optional

import requests
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service


# =========================================================
# Runtime configuration
# =========================================================

DEEPLINK_URL = "https://www.traveloka.com/en-en/hotel/detail?spec=25-04-2026.26-04-2026.1.1.HOTEL.9000001153383.Radisson%20Resort%20%26%20Spa%20Hua%20Hin.2&cur=EUR&multiRoomAlternativeOption=false"

CHECK_IN = "25-04-2026"
CHECK_OUT = "26-04-2026"
NUM_ROOMS = 1
NUM_ADULTS = 2
HOTEL_ID = "9000001153383"
HOTEL_NAME = "Radisson Resort & Spa Hua Hin"
CURRENCY = "EUR"
LOCALE_ROUTE = "en-en"

CHROMEDRIVER_PATH = ""

HEADLESS = False
CAPTURE_TIMEOUT_SECONDS = 60
TARGET_API_PATH = "/api/v2/hotel/search/rooms"

FORMAT_PRICES = True
SAVE_DEBUG_FILES = False

OUTPUT_CAPTURED_REQUEST = "captured_request.json"
OUTPUT_RESPONSE = "response.json"
OUTPUT_RESULT = "result.json"


# =========================================================
# Deep link construction
# =========================================================

def build_deeplink(
    check_in: str,
    check_out: str,
    num_rooms: int,
    num_adults: int,
    hotel_id: str,
    hotel_name: str,
    currency: str,
    locale_route: str,
) -> str:
    """
    Build a Traveloka hotel detail deep link from search parameters.
    """
    encoded_name = urllib.parse.quote(hotel_name, safe="")
    spec = f"{check_in}.{check_out}.1.{num_rooms}.HOTEL.{hotel_id}.{encoded_name}.{num_adults}"
    return (
        f"https://www.traveloka.com/{locale_route}/hotel/detail"
        f"?spec={spec}&cur={currency}&multiRoomAlternativeOption=false"
    )


def get_deeplink() -> str:
    """
    Return the configured deep link or generate it from the local config.
    """
    if DEEPLINK_URL.strip():
        return DEEPLINK_URL.strip()

    return build_deeplink(
        check_in=CHECK_IN,
        check_out=CHECK_OUT,
        num_rooms=NUM_ROOMS,
        num_adults=NUM_ADULTS,
        hotel_id=HOTEL_ID,
        hotel_name=HOTEL_NAME,
        currency=CURRENCY,
        locale_route=LOCALE_ROUTE,
    )


# =========================================================
# Browser bootstrap
# =========================================================

def create_driver() -> webdriver.Chrome: # type: ignore
    """
    Initialize Chrome WebDriver with performance logging enabled.
    """
    options = Options()

    if HEADLESS:
        options.add_argument("--headless=new")

    options.add_argument("--window-size=1400,1200")
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_argument("--disable-gpu")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--lang=en-US")
    options.set_capability("goog:loggingPrefs", {"performance": "ALL"})

    service = Service(CHROMEDRIVER_PATH) if CHROMEDRIVER_PATH.strip() else Service()
    return webdriver.Chrome(service=service, options=options) # type: ignore


# =========================================================
# DevTools performance log parsing
# =========================================================

def parse_performance_entry(entry: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """
    Decode a raw Chrome performance log entry.
    """
    try:
        return json.loads(entry["message"]).get("message")
    except Exception:
        return None


def collect_performance_messages(driver: webdriver.Chrome) -> List[Dict[str, Any]]: # type: ignore
    """
    Read all currently available performance log messages.
    """
    messages: List[Dict[str, Any]] = []

    for entry in driver.get_log("performance"):
        parsed = parse_performance_entry(entry)
        if parsed:
            messages.append(parsed)

    return messages


def find_rooms_request(messages: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """
    Locate the first POST request targeting the Traveloka rooms endpoint
    with an attached JSON payload.
    """
    for message in messages:
        if message.get("method") != "Network.requestWillBeSent":
            continue

        params = message.get("params", {})
        request = params.get("request", {})

        url = request.get("url", "")
        method = request.get("method", "")
        headers = request.get("headers", {})
        post_data = request.get("postData")

        if TARGET_API_PATH not in url:
            continue

        if method.upper() != "POST":
            continue

        if not post_data:
            continue

        return {
            "url": url,
            "headers": headers,
            "postData": post_data,
        }

    return None


def wait_for_rooms_request(driver: webdriver.Chrome, timeout_seconds: int) -> Dict[str, Any]: # type: ignore
    """
    Poll Chrome performance logs until the rooms request is observed
    or timeout is reached.
    """
    started_at = time.time()

    while time.time() - started_at < timeout_seconds:
        messages = collect_performance_messages(driver)
        captured = find_rooms_request(messages)
        if captured:
            return captured
        time.sleep(0.5)

    raise TimeoutError(
        f"Timed out after {timeout_seconds} seconds while waiting for {TARGET_API_PATH}"
    )


# =========================================================
# Request reconstruction
# =========================================================

def extract_cookies(driver: webdriver.Chrome) -> Dict[str, str]: # type: ignore
    """
    Convert Selenium cookie objects into a flat dictionary for requests.
    """
    cookies: Dict[str, str] = {}

    for cookie in driver.get_cookies():
        name = cookie.get("name")
        value = cookie.get("value")
        if name is not None and value is not None:
            cookies[name] = value

    return cookies


def clean_headers(browser_headers: Dict[str, Any], referer: str) -> Dict[str, str]:
    """
    Remove transport-level and browser-only headers before replay.
    """
    blocked = {
        "host",
        "content-length",
        "cookie",
        "connection",
        "sec-fetch-dest",
        "sec-fetch-mode",
        "sec-fetch-site",
        "priority",
        "te",
        "accept-encoding",
        ":authority",
        ":method",
        ":path",
        ":scheme",
    }

    headers: Dict[str, str] = {}

    for key, value in browser_headers.items():
        if not isinstance(key, str):
            continue
        if key.lower() in blocked:
            continue
        headers[key] = str(value)

    headers["Referer"] = referer
    headers["Origin"] = "https://www.traveloka.com"
    headers["Content-Type"] = "application/json"

    return headers


def parse_payload(post_data: str) -> Dict[str, Any]:
    """
    Deserialize the intercepted JSON request body.
    """
    return json.loads(post_data)


def refresh_payload(payload: Dict[str, Any], deeplink: str, user_agent: str) -> Dict[str, Any]:
    """
    Update volatile payload fields before request replay.
    """
    updated = deepcopy(payload)

    try:
        updated["data"]["tid"] = str(uuid.uuid4())
    except Exception:
        pass

    try:
        updated["data"]["contexts"]["hotelDetailURL"] = deeplink
    except Exception:
        pass

    try:
        updated["data"]["contexts"]["marketingContextCapsule"]["referrer_url"] = deeplink
    except Exception:
        pass

    try:
        updated["data"]["contexts"]["marketingContextCapsule"]["page_full_url"] = deeplink
    except Exception:
        pass

    try:
        updated["data"]["contexts"]["marketingContextCapsule"]["client_user_agent"] = user_agent
    except Exception:
        pass

    try:
        updated["data"]["monitoringSpec"]["referrer"] = deeplink
    except Exception:
        pass

    return updated


def replay_rooms_request(
    url: str,
    headers: Dict[str, str],
    cookies: Dict[str, str],
    payload: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Replay the intercepted rooms request outside the browser context.
    """
    session = requests.Session()

    for name, value in cookies.items():
        session.cookies.set(name, value)

    response = session.post(
        url=url,
        headers=headers,
        json=payload,
        timeout=40,
    )

    print(f"[INFO] Replay status code: {response.status_code}")
    response.raise_for_status()
    return response.json()


# =========================================================
# Money normalization
# =========================================================

def resolve_fraction_digits(rate: Dict[str, Any]) -> int:
    """
    Resolve decimal precision from rateDisplay.numOfDecimalPoint.

    Fallback:
    - return 0 if the field is missing, empty, or invalid
    """
    try:
        value = (rate.get("rateDisplay", {}) or {}).get("numOfDecimalPoint")

        if value in ("", None):
            return 0

        digits = int(str(value).strip())

        if digits < 0:
            return 0

        return digits
    except (ValueError, TypeError):
        return 0


def normalize_money_amount(value: Any, fraction_digits: int) -> Any:
    """
    Scale raw monetary value using the resolved decimal precision.

    Examples:
    - 5255 with 2 -> 52.55
    - 12399 with 0 -> 12399
    - 12399 with 3 -> 12.399
    """
    if value in ("", None):
        return value

    try:
        numeric_value = int(value)
    except (TypeError, ValueError):
        try:
            numeric_value = float(value)
        except (TypeError, ValueError):
            return value

    if fraction_digits <= 0:
        if isinstance(numeric_value, float) and numeric_value.is_integer():
            return int(numeric_value)
        return numeric_value

    return numeric_value / (10 ** fraction_digits)


def apply_price_transforms(item: Dict[str, Any], rate: Dict[str, Any]) -> Dict[str, Any]:
    """
    Apply precision-aware normalization to all monetary fields.
    """
    if not FORMAT_PRICES:
        return item

    fraction_digits = resolve_fraction_digits(rate)

    money_fields = [
        "price",
        "original_price",
        "total_taxes",
        "total_price",
        "net_price_per_stay",
        "shown_price_per_stay",
        "total_price_per_stay",
    ]

    for field in money_fields:
        if field in item:
            item[field] = normalize_money_amount(item[field], fraction_digits)

    return item


# =========================================================
# Response normalization
# =========================================================

def get_breakfast_value(rate: Dict[str, Any]) -> Any:
    """
    Read breakfast-related fields from a single inventory rate node.
    """
    if "displayNumBreakfastIncluded" in rate:
        return rate.get("displayNumBreakfastIncluded")
    if "numBreakfastIncluded" in rate:
        return rate.get("numBreakfastIncluded")
    return ""


def parse_rates(response_data: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Transform Traveloka API response data into normalized rate objects.
    """
    results: List[Dict[str, Any]] = []
    entries = response_data.get("data", {}).get("recommendedEntries", [])

    for entry in entries:
        room_name = entry.get("name", "")
        inventories = entry.get("hotelRoomInventoryList", [])

        for rate in inventories:
            rate_display = rate.get("rateDisplay", {}) or {}
            base_fare = rate_display.get("baseFare", {}) or {}
            taxes = rate_display.get("taxes", {}) or {}
            total_fare = rate_display.get("totalFare", {}) or {}

            item: Dict[str, Any] = {
                "room_name": room_name,
                "rate_name": rate.get("inventoryName", ""),
                "number_of_guests": rate.get("maxOccupancy", ""),
                "cancellation_policy": (
                    rate.get("roomCancellationPolicy", {}) or {}
                ).get("providerCancellationPolicyString", ""),
                "breakfast": get_breakfast_value(rate),
                "price": base_fare.get("amount", ""),
                "currency": total_fare.get("currency", ""),
                "total_taxes": taxes.get("amount", ""),
                "total_price": total_fare.get("amount", ""),
            }

            original_rate_display = rate.get("originalRateDisplay", {}) or {}
            original_total_fare = original_rate_display.get("totalFare", {}) or {}
            original_amount = original_total_fare.get("amount", "")

            if original_amount not in ("", None):
                item["original_price"] = original_amount

            per_room_per_night = (
                rate.get("finalPrice", {}) or {}
            ).get("perRoomPerNightDisplay", {}) or {}

            exclusive_final = per_room_per_night.get("exclusiveFinalPrice", {}) or {}
            inclusive_final = per_room_per_night.get("inclusiveFinalPrice", {}) or {}
            total_price_per_stay = per_room_per_night.get("totalFare", {}) or {}

            if exclusive_final:
                item["net_price_per_stay"] = exclusive_final.get("amount", "")
            if inclusive_final:
                item["shown_price_per_stay"] = inclusive_final.get("amount", "")
            if total_price_per_stay:
                item["total_price_per_stay"] = total_price_per_stay.get("amount", "")

            item = apply_price_transforms(item, rate)
            results.append(item)

    return results


# =========================================================
# Serialization
# =========================================================

def save_json(path: str, data: Any) -> None:
    """
    Persist structured data to disk using UTF-8 encoding.
    """
    with open(path, "w", encoding="utf-8") as file:
        json.dump(data, file, ensure_ascii=False, indent=2)


# =========================================================
# Entry point
# =========================================================

def main() -> None:
    """
    Execute the extraction flow:
    - open Traveloka hotel page
    - intercept the rooms request
    - replay the API call
    - normalize and persist rate data
    """
    deeplink = get_deeplink()

    print("[INFO] Starting Chrome...")
    driver = create_driver()

    try:
        print(f"[INFO] Opening page: {deeplink}")
        driver.get(deeplink)

        print(f"[INFO] Waiting for network request: {TARGET_API_PATH}")
        captured = wait_for_rooms_request(driver, CAPTURE_TIMEOUT_SECONDS)

        print(f"[INFO] Captured request URL: {captured['url']}")

        user_agent = driver.execute_script("return navigator.userAgent;")
        cookies = extract_cookies(driver)
        headers = clean_headers(captured["headers"], deeplink)
        payload = refresh_payload(parse_payload(captured["postData"]), deeplink, user_agent)

        if SAVE_DEBUG_FILES:
            save_json(
                OUTPUT_CAPTURED_REQUEST,
                {
                    "url": captured["url"],
                    "headers": headers,
                    "payload": payload,
                    "cookies_count": len(cookies),
                    "cookie_names": sorted(cookies.keys()),
                },
            )
            print(f"[INFO] Saved captured request to: {OUTPUT_CAPTURED_REQUEST}")

    finally:
        print("[INFO] Closing browser...")
        driver.quit()

    response_data = replay_rooms_request(
        url=captured["url"],
        headers=headers,
        cookies=cookies,
        payload=payload,
    )

    if SAVE_DEBUG_FILES:
        save_json(OUTPUT_RESPONSE, response_data)
        print(f"[INFO] Saved raw response to: {OUTPUT_RESPONSE}")

    rates = parse_rates(response_data)
    save_json(OUTPUT_RESULT, rates)

    print(f"[INFO] Saved parsed rates to: {OUTPUT_RESULT}")
    print(f"[INFO] Total extracted rates: {len(rates)}")


if __name__ == "__main__":
    main()