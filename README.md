# Phone Locator (Consent-Based)

This project is a **consent-first** family location sharing app. It creates a private
link that your family member opens on their phone to share their current location.
The app does **not** locate a phone number directly—phone numbers are only used to
identify who should receive the link.

## Features

- Phone number validation using `phonenumbers`.
- Location capture using the browser's Geolocation API (explicit consent required).
- Optional reverse geocoding via `geopy`/Nominatim.
- Simple tracking page that shows the last shared location.

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
python app.py
```

Open `http://localhost:5000` and follow the prompts to generate a sharing link.

## Notes

- Location sharing requires the family member to tap **Allow** on their phone.
- The database is stored locally in `locations.db`.
- For production, add authentication, HTTPS, and SMS delivery (for example with Twilio).
