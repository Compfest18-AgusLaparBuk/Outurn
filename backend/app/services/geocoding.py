from __future__ import annotations

import asyncio
import math
import time
from dataclasses import dataclass

import httpx

from app.core.config import Settings
from app.domain.models import (
    DocumentType,
    GeoClassification,
    GeographicValidation,
    GeoPoint,
)
from app.domain.normalization import normalize_address


@dataclass(frozen=True)
class GeocodeResult:
    query: str
    point: GeoPoint


class NominatimGeocoder:
    """Small, request-scoped geocoder adapter used synchronously during analysis.

    The adapter deliberately does not autocomplete or bulk-geocode. Requests are
    end-user triggered, cached in memory, and serialized to stay below the public
    Nominatim service's one-request-per-second limit.
    """

    def __init__(self, settings: Settings):
        self.base_url = settings.geocoding_base_url.rstrip("/")
        self.user_agent = settings.geocoding_user_agent
        self.timeout = settings.geocoding_timeout_seconds
        self._cache: dict[str, GeocodeResult | None] = {}
        self._rate_lock = asyncio.Lock()
        self._last_request = 0.0

    async def geocode(self, query: str | None) -> GeocodeResult | None:
        normalized = " ".join((query or "").split()).casefold()
        if not normalized or not self.base_url:
            return None
        if normalized in self._cache:
            return self._cache[normalized]

        async with self._rate_lock:
            wait_for = 1.0 - (time.monotonic() - self._last_request)
            if wait_for > 0:
                await asyncio.sleep(wait_for)
            self._last_request = time.monotonic()
            try:
                async with httpx.AsyncClient(timeout=self.timeout) as client:
                    response = await client.get(
                        f"{self.base_url}/search",
                        params={
                            "q": query,
                            "format": "jsonv2",
                            "limit": 1,
                            "addressdetails": 0,
                        },
                        headers={
                            "User-Agent": self.user_agent,
                            "Accept-Language": "id,en;q=0.8",
                        },
                    )
                    response.raise_for_status()
                    payload = response.json()
            except (httpx.HTTPError, ValueError):
                self._cache[normalized] = None
                return None

        if not isinstance(payload, list) or not payload:
            self._cache[normalized] = None
            return None
        candidate = payload[0]
        try:
            point = GeoPoint(
                latitude=float(candidate["lat"]),
                longitude=float(candidate["lon"]),
                label=str(candidate.get("display_name") or query)[:300],
                query=str(query)[:300],
            )
        except (KeyError, TypeError, ValueError):
            self._cache[normalized] = None
            return None
        result = GeocodeResult(query=str(query), point=point)
        self._cache[normalized] = result
        return result

    async def validate(
        self,
        *,
        origin: str | None,
        expected_destination: str | None,
        document_destinations: dict[DocumentType, str | None],
    ) -> GeographicValidation:
        comparable_destinations = [
            normalize_address(value)
            for value in document_destinations.values()
            if value
        ]
        if (
            not expected_destination
            and comparable_destinations
            and len(set(comparable_destinations)) == 1
        ):
            return GeographicValidation(
                classification=GeoClassification.GEOGRAPHIC_MATCH,
                message=(
                    "Document destinations use the same normalized operational area; "
                    "no external geocoding was needed."
                ),
                origin=None,
                expected_destination=None,
                document_destinations={},
                distance_km=0,
                geocoder="Nominatim (on-demand)",
            )

        origin_result = await self.geocode(origin)
        expected_result = await self.geocode(expected_destination)
        document_results: dict[DocumentType, GeocodeResult] = {}
        for document_type, destination in document_destinations.items():
            result = await self.geocode(destination)
            if result is not None:
                document_results[document_type] = result

        all_points = list(document_results.values())
        if expected_result is not None:
            reference = expected_result.point
            distances = [haversine_km(reference, item.point) for item in all_points]
        elif len(all_points) >= 2:
            reference = all_points[0].point
            distances = [haversine_km(reference, item.point) for item in all_points[1:]]
        else:
            reference = None
            distances = []

        if not distances:
            classification = GeoClassification.GEOCODING_UNCERTAIN
            message = "Destination could not be resolved with enough independent evidence."
        else:
            maximum = max(distances)
            if maximum <= 5:
                classification = GeoClassification.GEOGRAPHIC_MATCH
                message = "Resolved destinations point to the same operational area."
            elif maximum <= 25:
                classification = GeoClassification.NEARBY_REVIEW
                message = f"Resolved destinations are nearby but differ by about {maximum:.1f} km."
            else:
                classification = GeoClassification.DESTINATION_MISMATCH
                message = f"Resolved destinations differ materially by about {maximum:.1f} km."

        distance_km = max(distances) if distances else None
        return GeographicValidation(
            classification=classification,
            message=message,
            origin=origin_result.point if origin_result else None,
            expected_destination=expected_result.point if expected_result else None,
            document_destinations={
                document_type: result.point for document_type, result in document_results.items()
            },
            distance_km=round(distance_km, 2) if distance_km is not None else None,
            geocoder="Nominatim",
        )


def haversine_km(left: GeoPoint, right: GeoPoint) -> float:
    radius_km = 6_371.0088
    lat1, lat2 = math.radians(left.latitude), math.radians(right.latitude)
    delta_lat = lat2 - lat1
    delta_lon = math.radians(right.longitude - left.longitude)
    value = (
        math.sin(delta_lat / 2) ** 2
        + math.cos(lat1) * math.cos(lat2) * math.sin(delta_lon / 2) ** 2
    )
    return radius_km * 2 * math.asin(math.sqrt(min(1.0, value)))
