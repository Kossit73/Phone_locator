from __future__ import annotations

import os
import secrets
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

import streamlit as st

from geolocation import (
    LocationRecord,
    ensure_database,
    reverse_geocode,
    store_location,
    validate_phone_number,
)


@dataclass
class RegistrationResult:
    token: str
    phone: str


DATABASE_PATH = os.environ.get(
    "LOCATION_DB_PATH", os.path.join(os.path.dirname(__file__), "locations.db")
)
BASE_URL = os.environ.get("LOCATION_APP_BASE_URL", "http://localhost:8501")


def get_db_connection() -> sqlite3.Connection:
    return sqlite3.connect(DATABASE_PATH)


def register_phone(phone_number: str) -> RegistrationResult:
    token = secrets.token_urlsafe(16)
    with get_db_connection() as connection:
        connection.execute(
            "INSERT INTO registrations (token, phone_number, created_at) VALUES (?, ?, ?)",
            (token, phone_number, datetime.now(timezone.utc).isoformat()),
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


def render_share_page(token: str, latest_location: Optional[LocationRecord]) -> None:
    st.title("Share your location")
    st.write(
        "Tap the button below to share your current location. Your browser will ask for permission."
    )

    if latest_location:
        st.info(
            "A location was already shared. You can share again to update it for your family."
        )

    st.components.v1.html(
        f"""
        <div style="margin-top: 1rem;">
          <button id="shareBtn" style="
              padding: 0.75rem 1.25rem;
              border-radius: 10px;
              border: none;
              background: #22c55e;
              color: #0f172a;
              font-weight: 700;
              cursor: pointer;">Share my location</button>
          <div id="status" style="margin-top: 0.75rem;">Waiting for your permission.</div>
        </div>
        <script>
          const statusEl = document.getElementById("status");
          const shareBtn = document.getElementById("shareBtn");

          shareBtn.addEventListener("click", () => {{
            statusEl.textContent = "Requesting location...";
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
                window.location.search = params.toString();
              }},
              (error) => {{
                statusEl.textContent = `Location error: ${{error.message}}`;
              }},
              {{ enableHighAccuracy: true, timeout: 15000 }}
            );
          }});
        </script>
        """,
        height=200,
    )

    st.caption("Only share this link with family you trust. You can close it any time.")


def render_tracking_page(token: str) -> None:
    st.title("Latest shared location")

    location = read_latest_location(token)
    if not location:
        st.warning("No location has been shared yet.")
        return

    st.metric("Latitude", f"{location.latitude:.6f}")
    st.metric("Longitude", f"{location.longitude:.6f}")
    st.write(f"Accuracy: {location.accuracy or 'Unknown'} meters")
    st.write(f"Shared at: {location.recorded_at}")

    address = reverse_geocode(location.latitude, location.longitude)
    if address:
        st.write(f"Approximate address: {address}")

    st.markdown(f"[Open on map]({location.map_link()})")
    st.caption("Refresh this page to load the most recent update.")


def render_registration_page() -> None:
    st.title("Family Location Share")
    st.write(
        "Create a private link that your family member opens on their phone to securely share their location."
    )

    with st.form("register"):
        phone_number = st.text_input(
            "Family member phone number",
            placeholder="+1 555 555 1234",
        )
        submitted = st.form_submit_button("Create sharing link")

    if not submitted:
        st.info("Phone numbers are used only to identify who should receive the link.")
        return

    validation = validate_phone_number(phone_number)
    if not validation.is_valid:
        st.error(validation.error)
        return

    registration = register_phone(validation.normalized)
    share_url = build_link("share", registration.token)
    track_url = build_link("track", registration.token)

    st.success("Share link created!")
    st.write(f"Send this link to **{registration.phone}** so they can share their location.")
    st.code(share_url, language="text")
    st.write("Tracking page:")
    st.code(track_url, language="text")


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

        if shared and lat and lon:
            location = store_location(
                database_path=DATABASE_PATH,
                token=token,
                latitude=float(lat),
                longitude=float(lon),
                accuracy=float(accuracy) if accuracy else None,
            )
            st.success("Location shared successfully!")
            st.write(f"Latitude: {location.latitude}, Longitude: {location.longitude}")

        latest_location = read_latest_location(token)
        render_share_page(token, latest_location)
        return

    if mode == "track" and token:
        render_tracking_page(token)
        return

    render_registration_page()


if __name__ == "__main__":
    main()
