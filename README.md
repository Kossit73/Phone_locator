# Phone Locator (Consent-Based)

This project is a **consent-first** family location sharing app built with Streamlit.
It creates a private link that your family member opens on their phone to share their
current location. The app does **not** locate a phone number directly—phone numbers
are only used to identify who should receive the link and the country/region.

## Features

- Phone number validation using `phonenumbers` (requires country code).
- Location capture using the browser's Geolocation API (explicit consent required).
- Optional reverse geocoding via `geopy`/Nominatim.
- Live tracking option with accuracy warnings.
- Tracking dashboard with map, history table, and PIN protection.

## Requirements

- Python 3.10+

Install dependencies:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Run the app

```bash
streamlit run streamlit_app.py
```

Open `http://localhost:8501` and follow the prompts to generate a sharing link.

## Configuration

Set `LOCATION_APP_BASE_URL` to the public URL where Streamlit is hosted so the
shared links point back to your deployment:

```bash
export LOCATION_APP_BASE_URL="https://your-app.example.com"
```

Set a strong salt for tracking PIN hashing:

```bash
export LOCATION_PIN_SALT="replace-with-a-random-secret"
```

To enable SMS delivery with Twilio (optional):

```bash
export TWILIO_ACCOUNT_SID="your-account-sid"
export TWILIO_AUTH_TOKEN="your-auth-token"
export TWILIO_FROM_NUMBER="+15551234567"
```

## Notes

- Location sharing requires the family member to tap **Allow** on their phone.
- Country/region is derived from the phone number, while precise location and place type
  come from the shared coordinates via reverse geocoding.
- The database is stored locally in `locations.db`.
- For production, add authentication, HTTPS, and SMS delivery (for example with Twilio).
