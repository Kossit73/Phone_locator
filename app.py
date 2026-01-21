from __future__ import annotations

import os
import secrets
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

from flask import Flask, jsonify, redirect, render_template, request, url_for

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


app = Flask(__name__)
app.config["DATABASE_PATH"] = os.environ.get(
    "LOCATION_DB_PATH", os.path.join(os.path.dirname(__file__), "locations.db")
)


def get_db_connection() -> sqlite3.Connection:
    return sqlite3.connect(app.config["DATABASE_PATH"])


def register_phone(phone_number: str) -> RegistrationResult:
    token = secrets.token_urlsafe(16)
    with get_db_connection() as connection:
        connection.execute(
            "INSERT INTO registrations (token, phone_number, created_at) VALUES (?, ?, ?)",
            (token, phone_number, datetime.now(timezone.utc).isoformat()),
        )
    return RegistrationResult(token=token, phone=phone_number)


@app.before_first_request
def setup_database() -> None:
    ensure_database(app.config["DATABASE_PATH"])


@app.route("/", methods=["GET"])
def index() -> str:
    return render_template("index.html")


@app.route("/register", methods=["POST"])
def register() -> str:
    phone_number = request.form.get("phone_number", "")
    validation = validate_phone_number(phone_number)
    if not validation.is_valid:
        return render_template("index.html", error=validation.error)

    registration = register_phone(validation.normalized)
    share_url = url_for("share", token=registration.token, _external=True)
    track_url = url_for("track", token=registration.token, _external=True)

    return render_template(
        "registered.html",
        phone_number=registration.phone,
        share_url=share_url,
        track_url=track_url,
    )


@app.route("/share/<token>", methods=["GET"])
def share(token: str) -> str:
    return render_template("share.html", token=token)


@app.route("/api/location/<token>", methods=["POST"])
def receive_location(token: str):
    data = request.get_json(silent=True) or {}
    latitude = data.get("latitude")
    longitude = data.get("longitude")
    accuracy = data.get("accuracy")

    if latitude is None or longitude is None:
        return jsonify({"error": "Latitude and longitude are required."}), 400

    location = store_location(
        database_path=app.config["DATABASE_PATH"],
        token=token,
        latitude=float(latitude),
        longitude=float(longitude),
        accuracy=float(accuracy) if accuracy is not None else None,
    )

    return jsonify({"status": "ok", "location": location.as_dict()})


@app.route("/track/<token>", methods=["GET"])
def track(token: str) -> str:
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

    location: Optional[LocationRecord] = None
    address = None
    map_link = None

    if row:
        location = LocationRecord(
            latitude=row[0],
            longitude=row[1],
            accuracy=row[2],
            recorded_at=row[3],
        )
        address = reverse_geocode(location.latitude, location.longitude)
        map_link = location.map_link()

    return render_template(
        "track.html",
        token=token,
        location=location,
        address=address,
        map_link=map_link,
    )


@app.route("/health", methods=["GET"])
def health() -> str:
    return "ok"


if __name__ == "__main__":
    ensure_database(app.config["DATABASE_PATH"])
    app.run(host="0.0.0.0", port=5000, debug=True)
