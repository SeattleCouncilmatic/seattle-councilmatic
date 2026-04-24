"""Ingest Seattle's Historic and Special Review Districts from SDCI's
ArcGIS FeatureServer.

Typical usage:
    python manage.py ingest_historic_review_districts
    python manage.py ingest_historic_review_districts --dry-run

Source: 'Historic and Special Review Districts' polygon layer on
data-seattlecitygis.opendata.arcgis.com. Eight overlay districts
covering Pioneer Square, International District, Ballard Avenue,
Columbia City, Pike Place Market, Harvard-Belmont, Fort Lawton, and
Sand Point. Each district is a MultiPolygon in WGS84.

The layer is small and stable, so we fetch it in a single query. Upsert
key is `object_id` (SDCI OBJECTID).
"""

from __future__ import annotations

import json
import re

import requests
from django.contrib.gis.geos import GEOSGeometry, MultiPolygon
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction


DEFAULT_URL = (
    "https://services.arcgis.com/ZOyb2t4B0UYuYNYH/arcgis/rest/services/"
    "Zoning_Overlays-Historic-Special_Review_Districts/FeatureServer/23"
)

# SDCI prefixes the chapter field with the literal word "Chapter "
# (e.g., "Chapter 25.16"). Strip it so the stored value joins cleanly
# against MunicipalCodeSection.chapter_number.
_CHAPTER_PREFIX_RE = re.compile(r"^\s*Chapter\s+", re.IGNORECASE)


class Command(BaseCommand):
    help = "Ingest historic and special review districts from SDCI's ArcGIS FeatureServer."

    def add_arguments(self, parser):
        parser.add_argument("--url", default=DEFAULT_URL)
        parser.add_argument("--dry-run", action="store_true")
        parser.add_argument(
            "--purge-missing",
            action="store_true",
            help="Delete rows whose object_id no longer appears in the source.",
        )

    def handle(self, *args, **opts):
        from seattle_app.models import HistoricReviewDistrict

        features = self._fetch_features(opts["url"])
        self.stdout.write(f"Fetched {len(features)} features from SDCI.")

        counts = {"new": 0, "updated": 0, "unchanged": 0, "skipped_geom": 0}
        seen: set[int] = set()

        for feature in features:
            object_id = self._upsert(
                HistoricReviewDistrict, feature,
                opts["dry_run"], opts["url"], counts,
            )
            if object_id is not None:
                seen.add(object_id)

        purged = 0
        if opts["purge_missing"] and not opts["dry_run"] and seen:
            purged = (
                HistoricReviewDistrict.objects
                .exclude(object_id__in=seen)
                .delete()[0]
            )

        self.stdout.write(self.style.SUCCESS(
            f"Done. new={counts['new']} updated={counts['updated']} "
            f"unchanged={counts['unchanged']} "
            f"skipped_geom={counts['skipped_geom']} purged={purged}"
        ))

    @staticmethod
    def _fetch_features(base_url: str) -> list[dict]:
        url = f"{base_url.rstrip('/')}/query"
        params = {"where": "1=1", "outFields": "*", "f": "geojson"}
        resp = requests.get(url, params=params, timeout=60)
        resp.raise_for_status()
        return resp.json().get("features") or []

    @staticmethod
    @transaction.atomic
    def _upsert(Model, feature, dry_run, source_url, counts) -> int | None:
        props = feature.get("properties") or {}
        object_id = props.get("OBJECTID")
        if object_id is None:
            counts["skipped_geom"] += 1
            return None

        multi = _to_multipolygon(feature.get("geometry"))
        if multi is None:
            counts["skipped_geom"] += 1
            return object_id

        chapter_raw = (props.get("CHAPTER") or "").strip()
        smc_chapter = _CHAPTER_PREFIX_RE.sub("", chapter_raw).strip()

        defaults = {
            "overlay_code": (props.get("OVERLAY") or "").strip(),
            "name": (props.get("DESCRIPTION") or "").strip(),
            "purpose": (props.get("PUBLIC_DESCRIPTION") or "").strip(),
            "district_type": (props.get("TYPE") or "").strip().upper(),
            "smc_chapter": smc_chapter,
            "chapter_link": (props.get("CHAPTER_LINK") or "").strip(),
            "boundary": multi,
            "source_url": source_url,
        }

        if dry_run:
            counts["new"] += 1
            return object_id

        existing = Model.objects.filter(object_id=object_id).first()
        if existing is None:
            Model.objects.create(object_id=object_id, **defaults)
            counts["new"] += 1
            return object_id

        changed = False
        for field, value in defaults.items():
            current = getattr(existing, field)
            # Geometries need special handling for equality; re-save always
            # is the pragmatic path for a spatial field.
            if field == "boundary":
                if current.equals_exact(value) is False:
                    setattr(existing, field, value)
                    changed = True
            elif current != value:
                setattr(existing, field, value)
                changed = True
        if changed:
            existing.save()
            counts["updated"] += 1
        else:
            counts["unchanged"] += 1
        return object_id


def _to_multipolygon(geom):
    if not geom:
        return None
    try:
        g = GEOSGeometry(json.dumps(geom), srid=4326)
    except Exception:
        return None
    if g.geom_type == "Polygon":
        return MultiPolygon(g, srid=4326)
    if g.geom_type == "MultiPolygon":
        return g
    return None
