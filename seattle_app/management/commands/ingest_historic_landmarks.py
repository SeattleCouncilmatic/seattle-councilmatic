"""Ingest Seattle historic landmarks from SDCI's Landmarks FeatureServer.

Typical usage:
    python manage.py ingest_historic_landmarks
    python manage.py ingest_historic_landmarks --limit 5 --dry-run
    python manage.py ingest_historic_landmarks --resolve-districts

Source: Seattle GIS Landmarks layer — ~516 point features, each a
designated Historic City Landmark with name, address, ordinance number,
photo and designation-document filenames. Since points arrive geocoded,
no separate geocoding pass is needed.

`--resolve-districts` additionally runs a point-in-polygon pass against
reps.District to populate council_district FK after ingest. Skipped by
default so the ingest stays fast and re-runnable.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Iterator

import requests
from django.contrib.gis.geos import GEOSGeometry, Point
from django.core.management.base import BaseCommand
from django.db import transaction


DEFAULT_URL = (
    "https://services.arcgis.com/ZOyb2t4B0UYuYNYH/arcgis/rest/services/"
    "Landmarks/FeatureServer/0"
)
# User-facing page for provenance. SDCI's FeatureServer URL is the machine
# source; the Landmarks page is the canonical human reference.
DEFAULT_SOURCE_URL = (
    "https://www.seattle.gov/neighborhoods/historic-preservation/city-landmarks"
)


class Command(BaseCommand):
    help = "Ingest Seattle historic landmarks from SDCI's ArcGIS FeatureServer."

    def add_arguments(self, parser):
        parser.add_argument("--url", default=DEFAULT_URL)
        parser.add_argument(
            "--source-url",
            default=DEFAULT_SOURCE_URL,
            help="Value stored on each row's source_url field (human-readable provenance).",
        )
        parser.add_argument("--batch-size", type=int, default=1000)
        parser.add_argument("--limit", type=int, default=None)
        parser.add_argument("--dry-run", action="store_true")
        parser.add_argument(
            "--purge-missing",
            action="store_true",
            help="Delete rows whose landmark_number is no longer in the source.",
        )
        parser.add_argument(
            "--resolve-districts",
            action="store_true",
            help="After ingest, run a point-in-polygon pass to set council_district.",
        )

    def handle(self, *args, **opts):
        from seattle_app.models import HistoricLandmark

        counts = {"new": 0, "updated": 0, "skipped_no_landno": 0, "skipped_no_geom": 0}
        seen: set[int] = set()

        for feature in self._iter_features(opts["url"], opts["batch_size"], opts["limit"]):
            landno = self._upsert(
                HistoricLandmark, feature,
                opts["dry_run"], opts["source_url"], counts,
            )
            if landno is not None:
                seen.add(landno)

        purged = 0
        if opts["purge_missing"] and not opts["dry_run"] and seen:
            purged = (
                HistoricLandmark.objects
                .exclude(landmark_number__in=seen)
                .delete()[0]
            )

        self.stdout.write(self.style.SUCCESS(
            f"Done. new={counts['new']} updated={counts['updated']} "
            f"skipped_no_landno={counts['skipped_no_landno']} "
            f"skipped_no_geom={counts['skipped_no_geom']} purged={purged}"
        ))

        if opts["resolve_districts"] and not opts["dry_run"]:
            resolved = self._resolve_districts(HistoricLandmark)
            self.stdout.write(self.style.SUCCESS(
                f"Council district resolution: {resolved} landmarks linked."
            ))

    @staticmethod
    def _iter_features(base_url: str, batch_size: int, limit: int | None) -> Iterator[dict]:
        query_url = f"{base_url.rstrip('/')}/query"
        offset = 0
        total_yielded = 0
        while True:
            params = {
                "where": "1=1",
                "outFields": "*",
                "resultOffset": offset,
                "resultRecordCount": batch_size,
                "f": "geojson",
            }
            resp = requests.get(query_url, params=params, timeout=120)
            resp.raise_for_status()
            data = resp.json()
            features = data.get("features") or []
            if not features:
                return
            for f in features:
                yield f
                total_yielded += 1
                if limit is not None and total_yielded >= limit:
                    return
            if len(features) < batch_size and not data.get("exceededTransferLimit"):
                return
            offset += len(features)

    @staticmethod
    @transaction.atomic
    def _upsert(Model, feature, dry_run, source_url, counts) -> int | None:
        props = feature.get("properties") or {}
        geom = feature.get("geometry")

        landno_raw = props.get("LANDNO")
        if landno_raw is None:
            counts["skipped_no_landno"] += 1
            return None
        try:
            landmark_number = int(landno_raw)
        except (TypeError, ValueError):
            counts["skipped_no_landno"] += 1
            return None

        point = _to_point(geom)
        if point is None:
            counts["skipped_no_geom"] += 1
            return landmark_number

        ordinance_raw = props.get("ORDINANCE")
        ordinance_str = str(int(ordinance_raw)) if ordinance_raw not in (None, "") else ""

        defaults = {
            "name": (props.get("NAME") or "").strip(),
            "address": (props.get("ADDRESS") or "").strip(),
            "original_address": (props.get("ORIG_ADDRE") or "").strip(),
            "designating_ord_number": ordinance_str,
            "designation_date": _epoch_ms_to_date(props.get("EFF_DATE")),
            "photo_filename": (props.get("PHOTO") or "").strip(),
            "document_filename": (props.get("DOCUMENT") or "").strip(),
            "geolocation": point,
            "source_url": source_url,
        }

        if dry_run:
            counts["new"] += 1
            return landmark_number

        _, created = Model.objects.update_or_create(
            landmark_number=landmark_number, defaults=defaults,
        )
        counts["new" if created else "updated"] += 1
        return landmark_number

    @staticmethod
    def _resolve_districts(Model) -> int:
        """Point-in-polygon pass: set council_district FK for every landmark
        whose geolocation falls inside a reps.District boundary."""
        from reps.models import District

        resolved = 0
        with transaction.atomic():
            for district in District.objects.all():
                updated = (
                    Model.objects
                    .filter(geolocation__within=district.geometry)
                    .update(council_district=district)
                )
                resolved += updated
        return resolved


def _epoch_ms_to_date(value):
    if value in (None, "", 0):
        return None
    try:
        return datetime.fromtimestamp(value / 1000, tz=timezone.utc).date()
    except (TypeError, ValueError, OSError, OverflowError):
        return None


def _to_point(geom):
    """Return a GEOS Point (srid=4326) from a GeoJSON point geometry, or None."""
    if not geom or geom.get("type") != "Point":
        return None
    coords = geom.get("coordinates")
    if not coords or len(coords) < 2:
        return None
    try:
        lon, lat = float(coords[0]), float(coords[1])
    except (TypeError, ValueError):
        return None
    return Point(lon, lat, srid=4326)
