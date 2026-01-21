from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

import phonenumbers
from geopy.exc import GeocoderServiceError
from geopy.geocoders import Nominatim


@dataclass
class PhoneValidation:
    is_valid: bool
    normalized: str
    error: Optional[str] = None


@dataclass
class LocationRecord:
    latitude: float
    longitude: float
    accuracy: Optional[float]
    recorded_at: str

    def map_link(self) -> str:
        return f"https://www.openstreetmap.org/?mlat={self.latitude}&mlon={self.longitude}#map=15/{self.latitude}/{self.longitude}"

    def as_dict(self) -> dict:
        return {
            "latitude": self.latitude,
            "longitude": self.longitude,
            "accuracy": self.accuracy,
            "recorded_at": self.recorded_at,
        }


def validate_phone_number(phone_number: str, region: str = "US") -> PhoneValidation:
    if not phone_number.strip():
        return PhoneValidation(is_valid=False, normalized="", error="Phone number is required.")

    try:
        parsed = phonenumbers.parse(phone_number, region)
    except phonenumbers.NumberParseException:
        return PhoneValidation(
            is_valid=False,
            normalized="",
            error="Enter a valid phone number with country code.",
        )

    if not phonenumbers.is_valid_number(parsed):
        return PhoneValidation(
            is_valid=False,
            normalized="",
            error="Phone number is not valid for the selected region.",
        )

    normalized = phonenumbers.format_number(parsed, phonenumbers.PhoneNumberFormat.E164)
    return PhoneValidation(is_valid=True, normalized=normalized)


def ensure_database(database_path: str) -> None:
    with sqlite3.connect(database_path) as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS registrations (
                token TEXT PRIMARY KEY,
                phone_number TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS locations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                token TEXT NOT NULL,
                latitude REAL NOT NULL,
                longitude REAL NOT NULL,
                accuracy REAL,
                recorded_at TEXT NOT NULL,
                FOREIGN KEY (token) REFERENCES registrations (token)
            )
            """
        )


def store_location(
    *,
    database_path: str,
    token: str,
    latitude: float,
    longitude: float,
    accuracy: Optional[float],
) -> LocationRecord:
    recorded_at = datetime.now(timezone.utc).isoformat()
    with sqlite3.connect(database_path) as connection:
        connection.execute(
            """
            INSERT INTO locations (token, latitude, longitude, accuracy, recorded_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (token, latitude, longitude, accuracy, recorded_at),
        )

    return LocationRecord(
        latitude=latitude,
        longitude=longitude,
        accuracy=accuracy,
        recorded_at=recorded_at,
    )


def reverse_geocode(latitude: float, longitude: float) -> Optional[str]:
    geolocator = Nominatim(user_agent="family-location-app")
    try:
        location = geolocator.reverse((latitude, longitude), exactly_one=True, timeout=10)
    except GeocoderServiceError:
        return None

    if not location:
        return None

    return location.address
