from __future__ import annotations

import os
import secrets
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
import math
from typing import Optional

import streamlit as st
from twilio.rest import Client

from geolocation import (
    LocationRecord,
    ensure_database,
    hash_tracking_pin,
    phone_number_country,
    reverse_geocode,
    store_location,
    validate_phone_number,
    verify_tracking_pin,
)


@dataclass
class RegistrationResult:
    token: str
    phone: str


DATABASE_PATH = os.environ.get(
    "LOCATION_DB_PATH", os.path.join(os.path.dirname(__file__), "locations.db")
)
BASE_URL = os.environ.get("LOCATION_APP_BASE_URL", "http://localhost:8501")
PIN_SALT = os.environ.get("LOCATION_PIN_SALT", "change-me")
TWILIO_ACCOUNT_SID = os.environ.get("TWILIO_ACCOUNT_SID")
TWILIO_AUTH_TOKEN = os.environ.get("TWILIO_AUTH_TOKEN")
TWILIO_FROM_NUMBER = os.environ.get("TWILIO_FROM_NUMBER")
TWILIO_CHANNEL = os.environ.get("TWILIO_CHANNEL", "whatsapp").lower()
MAX_HISTORY = 20
MIN_DISTANCE_METERS = float(os.environ.get("LOCATION_MIN_DISTANCE_METERS", "20"))
MAX_ACCEPTABLE_ACCURACY = float(os.environ.get("LOCATION_MAX_ACCURACY_METERS", "100"))


def get_db_connection() -> sqlite3.Connection:
    return sqlite3.connect(DATABASE_PATH)


@st.cache_resource
def get_twilio_client() -> Client:
    return Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)


def get_channel_label(channel: str) -> str:
    return "WhatsApp" if channel == "whatsapp" else "SMS"



def register_phone(phone_number: str, tracking_pin: str) -> RegistrationResult:
    token = secrets.token_urlsafe(16)
    with get_db_connection() as connection:
        connection.execute(
            """
            INSERT INTO registrations (token, phone_number, tracking_pin_hash, created_at)
            VALUES (?, ?, ?, ?)
            """,
            (
                token,
                phone_number,
                hash_tracking_pin(tracking_pin, PIN_SALT),
                datetime.now(timezone.utc).isoformat(),
            ),
        )
    return RegistrationResult(token=token, phone=phone_number)


def build_link(mode: str, token: str) -> str:
    return f"{BASE_URL}?mode={mode}&token={token}"


def read_latest_location(token: str) -> Optional[LocationRecord]:
    with get_db_connection() as connection:
        row = connection.execute(
            """
            SELECT latitude, longitude, accuracy, recorded_at
            FROM locations
            WHERE token = ?
            ORDER BY recorded_at DESC
            LIMIT 1
            """,
            (token,),
        ).fetchone()

    if not row:
        return None

    return LocationRecord(
        latitude=row[0],
        longitude=row[1],
        accuracy=row[2],
        recorded_at=row[3],
    )


def read_location_history(token: str, limit: int = MAX_HISTORY) -> list[dict]:
    with get_db_connection() as connection:
        rows = connection.execute(
            """
            SELECT latitude, longitude, accuracy, recorded_at
            FROM locations
            WHERE token = ?
            ORDER BY recorded_at DESC
            LIMIT ?
            """,
            (token, limit),
        ).fetchall()

    return [
        {
            "Latitude": row[0],
            "Longitude": row[1],
            "Accuracy (m)": row[2] if row[2] is not None else "Unknown",
            "Shared at": format_timestamp(row[3]),
        }
        for row in rows
    ]


def get_tracking_pin_hash(token: str) -> Optional[str]:
    with get_db_connection() as connection:
        row = connection.execute(
            "SELECT tracking_pin_hash FROM registrations WHERE token = ?",
            (token,),
        ).fetchone()
    if not row:
        return None
    return row[0]


def haversine_meters(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    radius = 6371000.0
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1)
    delta_lambda = math.radians(lon2 - lon1)
    a = (
        math.sin(delta_phi / 2) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda / 2) ** 2
    )
    return 2 * radius * math.asin(math.sqrt(a))


def format_timestamp(value: str) -> str:
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return value
    local = parsed.astimezone()
    return local.strftime("%Y-%m-%d %H:%M:%S %Z")


def _format_twilio_number(phone_number: str, channel: str) -> str:
    if channel == "whatsapp":
        return phone_number if phone_number.startswith("whatsapp:") else f"whatsapp:{phone_number}"
    return phone_number.replace("whatsapp:", "")


def send_consent_sms(phone_number: str, share_url: str) -> dict:
    if not (TWILIO_ACCOUNT_SID and TWILIO_AUTH_TOKEN and TWILIO_FROM_NUMBER):
        raise ValueError(
            "SMS is not configured. Set TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, and "
            "TWILIO_FROM_NUMBER."
        )
    if TWILIO_CHANNEL not in {"sms", "whatsapp"}:
        raise ValueError("TWILIO_CHANNEL must be set to 'sms' or 'whatsapp'.")
    client = get_twilio_client()
    message = client.messages.create(
        to=_format_twilio_number(phone_number, TWILIO_CHANNEL),
        from_=_format_twilio_number(TWILIO_FROM_NUMBER, TWILIO_CHANNEL),
        body=(
            "Please accept to share your location by opening this link and tapping "
            "Yes: "
            f"{share_url}"
        ),
    )
    return {
        "sid": message.sid,
        "status": message.status,
        "to": message.to,
        "from": message.from_,
        "channel": TWILIO_CHANNEL,
    }


def get_twilio_debug_info(phone_number: str) -> dict:
    if TWILIO_CHANNEL not in {"sms", "whatsapp"}:
        raise ValueError("TWILIO_CHANNEL must be set to 'sms' or 'whatsapp'.")
    return {
        "channel": TWILIO_CHANNEL,
        "from": _format_twilio_number(TWILIO_FROM_NUMBER or "", TWILIO_CHANNEL),
        "to": _format_twilio_number(phone_number, TWILIO_CHANNEL),
    }


def render_live_tracking_controls(
    token: str,
    live_enabled: bool,
    live_interval: int,
) -> tuple[bool, int]:
    enable_live = st.checkbox("Enable live tracking", value=live_enabled)
    interval_seconds = st.number_input(
        "Live tracking interval (seconds)",
        min_value=5,
        max_value=300,
        value=live_interval,
        step=5,
        disabled=not enable_live,
    )
    if enable_live != live_enabled or interval_seconds != live_interval:
        st.experimental_set_query_params(
            mode="share",
            token=token,
            live="1" if enable_live else "0",
            interval=str(interval_seconds),
        )
        st.stop()
    return enable_live, interval_seconds


def render_share_buttons(token: str, live_enabled: bool, interval_seconds: int) -> None:
    live_flag = "true" if live_enabled else "false"
    st.components.v1.html(
        f"""
        <div style="margin-top: 1rem;">
          <button id="shareBtn" style="
              padding: 1rem 1.5rem;
              border-radius: 12px;
              border: none;
              background: #22c55e;
              color: #0f172a;
              font-weight: 800;
              font-size: 1rem;
              width: 100%;
              cursor: pointer;">Yes, share my location</button>
          <button id="rejectBtn" style="
              padding: 1rem 1.5rem;
              border-radius: 12px;
              border: none;
              background: #ef4444;
              color: #f8fafc;
              font-weight: 800;
              font-size: 1rem;
              width: 100%;
              cursor: pointer;
              margin-top: 0.75rem;">No, do not share</button>
          <div id="status" style="margin-top: 0.75rem; font-weight: 600;">
            Waiting for your permission.
          </div>
        </div>
        <script>
          const statusEl = document.getElementById("status");
          const shareBtn = document.getElementById("shareBtn");
          const rejectBtn = document.getElementById("rejectBtn");
          const liveEnabled = {live_flag};
          const liveIntervalMs = {interval_seconds} * 1000;

          function requestLocation() {{
            statusEl.textContent = liveEnabled
              ? "Live tracking is on. Requesting location..."
              : "Requesting location...";
            if (!navigator.geolocation) {{
              statusEl.textContent = "Geolocation is not supported in this browser.";
              return;
            }}

            navigator.geolocation.getCurrentPosition(
              (position) => {{
                const params = new URLSearchParams(window.location.search);
                params.set("mode", "share");
                params.set("token", "{token}");
                params.set("lat", position.coords.latitude.toString());
                params.set("lon", position.coords.longitude.toString());
                params.set("accuracy", position.coords.accuracy.toString());
                params.set("shared", "1");
                params.set("live", liveEnabled ? "1" : "0");
                params.set("interval", "{interval_seconds}");
                window.location.search = params.toString();
              }},
              (error) => {{
                statusEl.textContent = `Location error: ${{error.message}}`;
              }},
              {{ enableHighAccuracy: true, timeout: 15000 }}
            );
          }}

          shareBtn.addEventListener("click", requestLocation);
          rejectBtn.addEventListener("click", () => {{
            statusEl.textContent = "You chose not to share your location.";
          }});
          if (liveEnabled) {{
            setInterval(requestLocation, liveIntervalMs);
          }}
        </script>
        """,
        height=320,
    )


def render_channel_debug(phone_number: str) -> None:
    channel_label = get_channel_label(TWILIO_CHANNEL)
    try:
        debug_info = get_twilio_debug_info(phone_number)
    except ValueError as exc:
        st.error(str(exc))
    else:
        st.caption(
            "Message channel: "
            f"**{channel_label}** | From: {debug_info['from']} | "
            f"To: {debug_info['to']}"
        )


def render_share_page(
    token: str,
    latest_location: Optional[LocationRecord],
    live_enabled: bool,
    live_interval: int,
) -> None:
    st.title("Share your location")
    st.markdown("### Please accept to share your location")
    st.write(
        "Tap **Yes** to share once, or enable live tracking for continuous updates."
    )
    st.success("Your location will only be shared after you choose Yes.")
    st.info(
        "Only the phone holder can share their location. Closing this page or revoking "
        "browser permission stops sharing."
    )
    st.caption("Tip: Stay on this page to keep live tracking active.")

    if latest_location:
        st.info(
            "A location was already shared. You can share again to update it for your family."
        )
        st.caption(f"Last consented at: {format_timestamp(latest_location.recorded_at)}")

    enable_live, interval_seconds = render_live_tracking_controls(
        token,
        live_enabled,
        live_interval,
    )
    render_share_buttons(token, enable_live, interval_seconds)

    st.caption("Only share this link with family you trust. You can close it any time.")


def render_tracking_page(token: str) -> None:
    st.title("Latest shared location")
    st.caption(
        "This dashboard only shows locations explicitly shared by the phone holder."
    )

    pin_hash = get_tracking_pin_hash(token)
    pin = st.text_input("Tracking PIN", type="password")
    if pin_hash and not verify_tracking_pin(pin, PIN_SALT, pin_hash):
        st.warning("Enter the tracking PIN to view the location dashboard.")
        return

    auto_refresh = st.checkbox("Auto-refresh dashboard", value=True)
    refresh_seconds = st.slider("Refresh every (seconds)", 5, 120, 15)
    if auto_refresh:
        st.autorefresh(interval=refresh_seconds * 1000, key="track-refresh")

    location = read_latest_location(token)
    if not location:
        st.warning("No location has been shared yet.")
        return

    st.success(f"Last consented at: {format_timestamp(location.recorded_at)}")
    col1, col2, col3 = st.columns(3)
    col1.metric("Latitude", f"{location.latitude:.6f}")
    col2.metric("Longitude", f"{location.longitude:.6f}")
    col3.metric("Accuracy (m)", f"{location.accuracy or 'Unknown'}")
    if location.accuracy and location.accuracy > 100:
        st.warning("Low GPS accuracy detected. Location may be approximate.")

    address, place_type, place_label = reverse_geocode(location.latitude, location.longitude)
    if address:
        st.write(f"Approximate address: {address}")
    if place_label or place_type:
        st.write(f"Place type: {place_label or place_type}")

    st.subheader("Map view")
    st.map(
        [
            {
                "lat": location.latitude,
                "lon": location.longitude,
            }
        ],
        zoom=15,
    )
    st.caption("Legend: blue dot = shared phone location.")
    st.caption("Refresh this page to load the most recent update.")

    history = read_location_history(token)
    if history:
        st.subheader("Location history")
        st.dataframe(history, use_container_width=True)


def render_registration_page() -> None:
    channel_label = get_channel_label(TWILIO_CHANNEL)
    st.title("Family Location Share")
    st.write(
        "Create a private link that your family member opens on their phone to securely "
        "share their location."
    )
    st.caption(
        "Phone numbers only identify the country/region. Exact location requires the recipient to share it."
    )
    if BASE_URL.startswith("http://localhost"):
        st.info(
            "Tip: Set LOCATION_APP_BASE_URL to your public app URL so share links work "
            "on phones outside this machine."
        )
    st.subheader("Share in 3 steps")
    st.write(
        "1. Create the sharing link below.\n"
        f"2. Send it to your family member via {channel_label} and ask them to approve.\n"
        "3. Use the dashboard to view the latest consented update."
    )

    with st.form("register"):
        phone_number = st.text_input(
            "Family member phone number (include country code)",
            placeholder="+1 555 555 1234",
        )
        tracking_pin = st.text_input(
            "Tracking PIN (4-8 digits)",
            type="password",
            placeholder="1234",
        )
        submitted = st.form_submit_button("Create sharing link")

    if not submitted:
        st.info("Phone numbers are used only to identify who should receive the link.")
        return

    validation = validate_phone_number(phone_number)
    if not validation.is_valid:
        st.error(validation.error)
        return
    if not tracking_pin.isdigit() or not (4 <= len(tracking_pin) <= 8):
        st.error("Tracking PIN must be 4-8 digits.")
        return

    registration = register_phone(validation.normalized, tracking_pin)
    country = phone_number_country(registration.phone)
    share_url = build_link("share", registration.token)
    track_url = build_link("track", registration.token)

    st.success("Share link created!")
    st.write(f"Send this link to **{registration.phone}** so they can share their location.")
    if country:
        st.write(f"Detected country/region: **{country}**")
    st.code(share_url, language="text")
    st.write("Tracking page:")
    st.code(track_url, language="text")
    st.subheader("Suggested message to send")
    st.text_area(
        "Copy this message into WhatsApp, SMS, or email.",
        value=(
            "Hi! Please open this link and tap “Share my location” so I can see your "
            "current location. You can stop sharing anytime by closing the page:\n"
            f"{share_url}"
        ),
        height=140,
    )
    st.subheader(f"Send consent via {channel_label}")
    render_channel_debug(registration.phone)
    if st.button(f"Send consent via {channel_label}"):
        try:
            result = send_consent_sms(registration.phone, share_url)
        except ValueError as exc:
            st.error(str(exc))
        else:
            st.success("201 - CREATED - The request was successful.")
            st.json(result)


def main() -> None:
    ensure_database(DATABASE_PATH)
    params = st.experimental_get_query_params()
    mode = params.get("mode", ["register"])[0]
    token = params.get("token", [""])[0]

    if mode == "share" and token:
        lat = params.get("lat", [None])[0]
        lon = params.get("lon", [None])[0]
        accuracy = params.get("accuracy", [None])[0]
        shared = params.get("shared", [None])[0]
        live = params.get("live", ["0"])[0] == "1"
        interval = int(params.get("interval", ["30"])[0])

        if shared and lat and lon:
            latest = read_latest_location(token)
            new_lat = float(lat)
            new_lon = float(lon)
            new_accuracy = float(accuracy) if accuracy else None
            if new_accuracy and new_accuracy > MAX_ACCEPTABLE_ACCURACY:
                st.warning(
                    "Low GPS accuracy detected. Consider moving to an open area "
                    "before sharing."
                )
                render_share_page(token, latest, live, interval)
                return
            if latest:
                distance = haversine_meters(
                    latest.latitude, latest.longitude, new_lat, new_lon
                )
                if distance < MIN_DISTANCE_METERS:
                    st.info(
                        "Location change is within the minimum distance threshold. "
                        "Skipping save to reduce GPS noise."
                    )
                    render_share_page(token, latest, live, interval)
                    return
            location = store_location(
                database_path=DATABASE_PATH,
                token=token,
                latitude=new_lat,
                longitude=new_lon,
                accuracy=new_accuracy,
            )
            st.success("Location shared successfully!")
            st.write(f"Latitude: {location.latitude}, Longitude: {location.longitude}")
            if location.accuracy and location.accuracy > 100:
                st.warning("Low GPS accuracy detected. Consider moving to an open area.")
            address, place_type, place_label = reverse_geocode(
                location.latitude, location.longitude
            )
            if address:
                st.write(f"Approximate address: {address}")
            if place_label or place_type:
                st.write(f"Place type: {place_label or place_type}")
            st.subheader("Map view")
            st.map(
                [
                    {
                        "lat": location.latitude,
                        "lon": location.longitude,
                    }
                ],
                zoom=15,
            )
            st.caption("Legend: blue dot = shared phone location.")

        latest_location = read_latest_location(token)
        render_share_page(token, latest_location, live, interval)
        return

    if mode == "track" and token:
        render_tracking_page(token)
        return

    render_registration_page()


if __name__ == "__main__":
    main()
