from __future__ import annotations

import hashlib

from drift_agent.types import DriftCategory, DriftItem, DriftTaxonomy


def classify_drift(category: DriftCategory, parameter_location: str | None = None) -> DriftTaxonomy:
    """Classify by the changed contract aspect; parameter origin is kept separately."""
    mapping = {
        DriftCategory.MISSING_ENDPOINT: DriftTaxonomy.MISSING_ENDPOINT,
        DriftCategory.GHOST_ENDPOINT: DriftTaxonomy.UNDOCUMENTED_ENDPOINT,
        DriftCategory.ADDITIVE_DRIFT: DriftTaxonomy.SCHEMA,
        DriftCategory.DESTRUCTIVE_DRIFT: DriftTaxonomy.SCHEMA,
        DriftCategory.TYPE_DRIFT: DriftTaxonomy.SCHEMA,
        DriftCategory.REQUIRED_DRIFT: DriftTaxonomy.REQUIRED_NULLABLE,
        DriftCategory.NULLABILITY_DRIFT: DriftTaxonomy.REQUIRED_NULLABLE,
        DriftCategory.STATUS_CODE_DRIFT: DriftTaxonomy.RESPONSE_CODE,
        DriftCategory.DESCRIPTION_DRIFT: DriftTaxonomy.DESCRIPTION,
        DriftCategory.EXAMPLE_DRIFT: DriftTaxonomy.EXAMPLE,
        DriftCategory.ANALYSIS_LIMITATION: DriftTaxonomy.ANALYSIS_LIMITATION,
    }
    if category == DriftCategory.PARAMETER_DRIFT:
        return {
            "path": DriftTaxonomy.PATH_PARAMETER,
            "query": DriftTaxonomy.QUERY_PARAMETER,
            "header": DriftTaxonomy.HEADER_PARAMETER,
            "cookie": DriftTaxonomy.COOKIE_PARAMETER,
        }.get(parameter_location, DriftTaxonomy.SCHEMA)
    return mapping[category]


def drift_sort_key(item: DriftItem) -> tuple[str, ...]:
    return (item.priority, item.endpoint, item.location, item.category.value, item.id)


def make_drift_id(endpoint: str, location: str, category: DriftCategory) -> str:
    raw = f"{endpoint}|{location}|{category.value}"
    return hashlib.sha256(raw.encode()).hexdigest()[:12]

