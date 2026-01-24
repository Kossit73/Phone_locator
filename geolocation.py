from __future__ import annotations

import hashlib
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional, Tuple

import phonenumbers
from phonenumbers import geocoder
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


def validate_phone_number(phone_number: str) -> PhoneValidation:
    if not phone_number.strip():
        return PhoneValidation(is_valid=False, normalized="", error="Phone number is required.")

    if not phone_number.strip().startswith("+"):
        return PhoneValidation(
            is_valid=False,
            normalized="",
            error="Include the country code (for example, +1...)",
        )

    try:
        parsed = phonenumbers.parse(phone_number, None)
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


def phone_number_country(phone_number: str) -> Optional[str]:
    try:
        parsed = phonenumbers.parse(phone_number, None)
    except phonenumbers.NumberParseException:
        return None

    if not phonenumbers.is_valid_number(parsed):
        return None

    description = geocoder.description_for_number(parsed, "en")
    return description or None


def normalize_place_type(place_type: Optional[str], category: Optional[str]) -> Optional[str]:
    if not place_type and not category:
        return None

    raw = (place_type or category or "").lower()
    mapping = {
        "school": "School",
        "college": "College",
        "university": "University",
        "hospital": "Hospital",
        "clinic": "Clinic",
        "hotel": "Hotel",
        "motel": "Hotel",
        "hostel": "Hotel",
        "residential": "Residential area",
        "apartments": "Residential area",
        "house": "Residential area",
        "neighbourhood": "Residential area",
        "supermarket": "Retail area",
        "mall": "Retail area",
        "shopping_centre": "Retail area",
        "office": "Office",
        "industrial": "Industrial area",
        "park": "Park",
        "stadium": "Stadium",
        "airport": "Airport",
        "station": "Transit station",
    }

    for key, label in mapping.items():
        if key in raw:
            return label

    return place_type or category


def ensure_database(database_path: str) -> None:
    with sqlite3.connect(database_path) as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS registrations (
                token TEXT PRIMARY KEY,
                phone_number TEXT NOT NULL,
                tracking_pin_hash TEXT,
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
        columns = connection.execute("PRAGMA table_info(registrations)").fetchall()
        column_names = {column[1] for column in columns}
        if "tracking_pin_hash" not in column_names:
            connection.execute(
                "ALTER TABLE registrations ADD COLUMN tracking_pin_hash TEXT"
            )


def hash_tracking_pin(pin: str, salt: str) -> str:
    digest = hashlib.sha256(f"{salt}:{pin}".encode("utf-8")).hexdigest()
    return digest


def verify_tracking_pin(pin: str, salt: str, pin_hash: Optional[str]) -> bool:
    if not pin_hash:
        return False
    return hash_tracking_pin(pin, salt) == pin_hash


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


def reverse_geocode(
    latitude: float, longitude: float
) -> Tuple[Optional[str], Optional[str], Optional[str]]:
    geolocator = Nominatim(user_agent="family-location-app")
    try:
        location = geolocator.reverse((latitude, longitude), exactly_one=True, timeout=10)
    except GeocoderServiceError:
        return None, None, None

    if not location:
        return None, None, None

    address = location.address
    raw = location.raw or {}
    place_type = raw.get("type") or raw.get("category")
    place_label = normalize_place_type(raw.get("type"), raw.get("category"))
    return address, place_type, place_label
