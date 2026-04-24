"""Ingest Seattle zoning polygons from SDCI's ArcGIS FeatureServer.

Typical usage:
    python manage.py ingest_zoning_polygons
    python manage.py ingest_zoning_polygons --limit 5 --dry-run
    python manage.py ingest_zoning_polygons --url <override>

Source: SDCI's Land Use Zoning layer within the
'Zoned_Development_Capacity_Layers_2016' FeatureServer. ~2,600 polygons
covering the city. Returns GeoJSON (WGS84) so we can feed the geometry
straight into GeoDjango via GEOSGeometry.

Upsert key is `object_id` (ArcGIS OBJECTID). If SDCI rebuilds the layer
from scratch, OBJECTIDs may shift; a full sweep still works because each
run replaces the whole set.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from typing import Iterator, Optional

import requests
from django.contrib.gis.geos import GEOSGeometry, MultiPolygon
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction


DEFAULT_URL = (
    "https://services.arcgis.com/ZOyb2t4B0UYuYNYH/arcgis/rest/services/"
    "Zoned_Development_Capacity_Layers_2016/FeatureServer/9"
)


class Command(BaseCommand):
    help = "Ingest Seattle zoning polygons from SDCI's ArcGIS FeatureServer."

    def add_arguments(self, parser):
        parser.add_argument(
            "--url",
            default=DEFAULT_URL,
            help="Override the FeatureServer layer URL.",
        )
        parser.add_argument(
            "--batch-size",
            type=int,
            default=1000,
            help="Features to request per page (capped server-side).",
        )
        parser.add_argument(
            "--limit",
            type=int,
            default=None,
            help="Stop after ingesting this many features (for testing).",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Parse + report counts without writing to the database.",
        )
        parser.add_argument(
            "--purge-missing",
            action="store_true",
            help="Delete rows whose object_id no longer appears in the source.",
        )

    def handle(self, *args, **opts):
        from seattle_app.models import ZoningPolygon, ZoningCode

        code_by_abbrev = {
            z.abbreviation: z for z in ZoningCode.objects.all()
        }
        self.stdout.write(
            f"Loaded {len(code_by_abbrev)} ZoningCode entries for FK lookup."
        )

        counts = {"new": 0, "updated": 0, "unchanged": 0, "skipped_geom": 0}
        seen_object_ids: set[int] = set()

        for feature in self._iter_features(opts["url"], opts["batch_size"], opts["limit"]):
            object_id = self._upsert(
                ZoningPolygon, feature, code_by_abbrev,
                opts["dry_run"], opts["url"], counts,
            )
            if object_id is not None:
                seen_object_ids.add(object_id)

        purged = 0
        if opts["purge_missing"] and not opts["dry_run"] and seen_object_ids:
            purged = (
                ZoningPolygon.objects
                .exclude(object_id__in=seen_object_ids)
                .delete()[0]
            )

        self.stdout.write(self.style.SUCCESS(
            f"Done. new={counts['new']} updated={counts['updated']} "
            f"unchanged={counts['unchanged']} skipped_geom={counts['skipped_geom']} "
            f"purged={purged}"
        ))

    @staticmethod
    def _iter_features(base_url: str, batch_size: int, limit: int | None) -> Iterator[dict]:
        """Yield GeoJSON feature dicts, paginating via resultOffset."""
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
            # ArcGIS sets "exceededTransferLimit": true when more rows exist;
            # we also stop if the server returned fewer than batch_size.
            if len(features) < batch_size and not data.get("exceededTransferLimit"):
                return
            offset += len(features)

    @staticmethod
    @transaction.atomic
    def _upsert(Model, feature, code_by_abbrev, dry_run, source_url, counts) -> int | None:
        props = feature.get("properties") or {}
        geom = feature.get("geometry")
        object_id = props.get("OBJECTID")
        if object_id is None:
            counts["skipped_geom"] += 1
            return None

        multi = _to_multipolygon(geom)
        if multi is None:
            counts["skipped_geom"] += 1
            return object_id

        zonelut = (props.get("ZONELUT") or "").strip()
        zoning_str = (props.get("ZONING") or "").strip()
        defaults = {
            "zone_id": props.get("ZONEID") or 0,
            "zoning": zoning_str,
            "base_zone": _resolve_base_zone(code_by_abbrev, zonelut, zoning_str),
            "contract": (props.get("CONTRACT") or "").strip(),
            "ordinance_number": (props.get("ORDINANCE") or "").strip(),
            "effective_date": _epoch_ms_to_date(props.get("EFFECTIVE")),
            "historic": (props.get("HISTORIC") or "").strip(),
            "pedestrian_overlay": (props.get("PEDESTRIAN") or "").strip(),
            "shoreline_overlay": (props.get("SHORELINE") or "").strip(),
            "other_overlay": (props.get("OVERLAY") or "").strip(),
            "lightrail_overlay": (props.get("LIGHTRAIL") or "").strip(),
            "previous_zone_id": props.get("OLDZONEID"),
            "special_area_id": (props.get("GEO") or "").strip(),
            "boundary": multi,
            "source_url": source_url,
        }

        if dry_run:
            counts["new"] += 1
            return object_id

        _, created = Model.objects.update_or_create(
            object_id=object_id, defaults=defaults,
        )
        counts["new" if created else "updated"] += 1
        return object_id


def _resolve_base_zone(code_by_abbrev, zonelut: str, zoning: str):
    """Resolve a ZoningCode for an SDCI polygon.

    SDCI's ZONELUT column doesn't always match our legend abbreviations
    one-to-one; strategies in order:
      1. Exact match on ZONELUT — handles the 26 base-code rows.
      2. Exact match on ZONING — catches MPC rows where ZONELUT='MPC'
         but ZONING='MPC-YT' (the form on the legend page).
      3. Strip a trailing 'I' or 'P' — SDCI appends these as incentive
         or pedestrian overlay markers (e.g., NC3I, NC2P). The modifier
         is preserved in the raw `zoning` string.
      4. Prefix before first separator — resolves compound codes like
         'MR/RC' down to 'MR'.
    """
    if zonelut and zonelut in code_by_abbrev:
        return code_by_abbrev[zonelut]
    if zoning and zoning in code_by_abbrev:
        return code_by_abbrev[zoning]
    if zonelut and zonelut[-1:] in ("I", "P") and len(zonelut) > 1:
        stripped = zonelut[:-1]
        if stripped in code_by_abbrev:
            return code_by_abbrev[stripped]
    if zonelut:
        prefix = re.split(r"[-/\s]", zonelut, maxsplit=1)[0]
        if prefix and prefix in code_by_abbrev:
            return code_by_abbrev[prefix]
    return None


def _epoch_ms_to_date(value):
    if value in (None, "", 0):
        return None
    try:
        return datetime.fromtimestamp(value / 1000, tz=timezone.utc).date()
    except (TypeError, ValueError, OSError, OverflowError):
        return None


def _to_multipolygon(geom):
    """Convert a GeoJSON geometry dict into a GEOS MultiPolygon (srid=4326).
    Single polygons are wrapped in a single-part MultiPolygon. Returns None
    for non-polygonal or missing geometry."""
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
