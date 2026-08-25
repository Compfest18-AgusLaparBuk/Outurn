import asyncio

from app.core.config import Settings
from app.domain.models import DocumentType, GeoClassification
from app.services.geocoding import NominatimGeocoder, haversine_km


def test_haversine_distance_is_reproducible():
    from app.domain.models import GeoPoint

    distance = haversine_km(
        GeoPoint(latitude=-6.9175, longitude=107.6191, label="Bandung", query="Bandung"),
        GeoPoint(latitude=-6.8722, longitude=107.5425, label="Cimahi", query="Cimahi"),
    )
    assert 8 < distance < 15


def test_identical_normalized_destinations_do_not_call_external_service():
    settings = Settings(app_env="test", cors_origins=["http://localhost:3000"])
    geocoder = NominatimGeocoder(settings)
    result = asyncio.run(
        geocoder.validate(
            origin=None,
            expected_destination=None,
            document_destinations={
                DocumentType.INVOICE: "Jl. Merdeka No. 10 Bandung",
                DocumentType.PACKING_LIST: "Jalan Merdeka 10 Bandung",
                DocumentType.DELIVERY_ORDER: "Jl Merdeka 10 Bandung",
            },
        )
    )
    assert result.classification == GeoClassification.GEOGRAPHIC_MATCH
    assert result.distance_km == 0
