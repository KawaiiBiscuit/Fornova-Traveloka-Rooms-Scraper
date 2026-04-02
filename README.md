# Traveloka Rooms Scraper

Automated extraction of hotel room rates from Traveloka using browser-assisted request capture and API replay.

## Overview

This project uses a hybrid extraction flow:

1. Selenium opens a real browser session and loads the hotel detail page.
2. Chrome performance logs are used to intercept the rooms search request.
3. The captured request is reconstructed outside the browser with `requests`.
4. The API response is normalized into a structured list of rates.

This approach avoids manual copying of cookies, headers, and payload data.

---

## Requirements

- Python 3.10+
- A Chromium-based browser installed (Chrome, Edge, Brave, etc.)
- Internet connection
- Valid Traveloka hotel detail page

Install dependencies:

```bash
pip install -r requirements.txt
```

---

## Usage

Run the script from the project directory:

```bash
python main.py
```

---

## Configuration

All runtime configuration is defined inside `main.py`.

### Direct deep link mode

If `DEEPLINK_URL` is set, it will be used directly:

```python
DEEPLINK_URL = "https://www.traveloka.com/en-en/hotel/detail?spec=..."
```

### Generated deep link mode

If `DEEPLINK_URL` is empty, the script will generate a link using:

```python
CHECK_IN = "25-04-2026"
CHECK_OUT = "26-04-2026"
NUM_ROOMS = 1
NUM_ADULTS = 2
HOTEL_ID = "9000001153383"
HOTEL_NAME = "Radisson Resort & Spa Hua Hin"
CURRENCY = "EUR"
LOCALE_ROUTE = "en-en"
```

### Optional ChromeDriver path

If browser startup is slow or automatic driver resolution fails:

```python
CHROMEDRIVER_PATH = r"C:\WebDriver\chromedriver.exe"
```

Leave empty to use Selenium auto-resolution:

```python
CHROMEDRIVER_PATH = ""
```

### Other runtime parameters

```python
HEADLESS = False
CAPTURE_TIMEOUT_SECONDS = 60
TARGET_API_PATH = "/api/v2/hotel/search/rooms"
FORMAT_PRICES = True
SAVE_DEBUG_FILES = True
```

### Price normalization behavior

- Monetary values are normalized using `rateDisplay.numOfDecimalPoint`
- Precision is taken directly from the API response
- `0` means no scaling is applied
- `2` means division by `100`
- `3` means division by `1000`
- If the field is missing or invalid, fallback precision is `0`, so the raw response value is preserved

---

## Output

The script produces a normalized dataset of hotel room rates.

### Primary output

| File | Description |
|------|-------------|
| `result.json` | Final parsed and normalized room rate data |

This file contains structured data extracted from the Traveloka API and is the only required output.

---

### Optional debug output

When `SAVE_DEBUG_FILES = True`, the script also persists intermediate artifacts for debugging and reverse-engineering purposes.

| File | Description |
|------|-------------|
| `captured_request.json` | Intercepted request metadata including headers and payload |
| `response.json` | Raw API response before normalization |

These files are optional and can be disabled by setting:

```python
SAVE_DEBUG_FILES = False
```

They are useful for:

- troubleshooting request failures
- inspecting API schema changes
- validating payload structure
- debugging price normalization logic

---

## Data Structure

Each item in `result.json` represents a single rate entry.

Example:

```json
{
  "room_name": "Superior Ocean View",
  "rate_name": "Superior Room, Ocean View",
  "number_of_guests": "2",
  "cancellation_policy": null,
  "breakfast": "Breakfast Included",
  "price": 52.55,
  "currency": "EUR",
  "total_taxes": 9.31,
  "total_price": 61.86,
  "original_price": 68.53,
  "net_price_per_stay": 52.55,
  "shown_price_per_stay": 61.86,
  "total_price_per_stay": 61.86
}
```

---

## Notes

- A real browser session is used only to capture a valid request context
- All data extraction is performed via API response, not HTML parsing
- Cookies, headers, and payload are captured automatically
- Request payload is refreshed before replay to avoid rejection
- Output is normalized for consistency and further processing

---

## Limitations

- Execution depends on successful interception of the rooms API request
- May fail if Traveloka blocks the session (e.g. anti-bot protection)
- API structure may change without notice
- Price normalization depends on `numOfDecimalPoint` availability and validity