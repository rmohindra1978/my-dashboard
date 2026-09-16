"""Source registry. Order matters: geography first, then metric sources that depend on the crosswalk."""

from __future__ import annotations

from pipelines.base import Source
from pipelines.sources.cms_enrollment import EnrollmentSource
from pipelines.sources.cms_geo_variation import GeoVariationSource
from pipelines.sources.dac_clinicians import CliniciansSource
from pipelines.sources.sample import SampleFixtureSource

SOURCES: dict[str, type[Source]] = {
    # "census_geo": CensusGeoSource,          # Phase 1 data-engineering session
    # "acs5": AcsSource,
    # "popest": PopEstSource,
    "cms_geo_variation": GeoVariationSource,
    "cms_enrollment": EnrollmentSource,
    "dac_clinicians": CliniciansSource,
    # "hrsa_hpsa": HpsaSource,
    # "cdc_places": PlacesSource,
}

SAMPLE_SOURCES: dict[str, type[Source]] = {"sample": SampleFixtureSource}

__all__ = ["SOURCES", "SAMPLE_SOURCES"]
