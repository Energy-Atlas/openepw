import hashlib
import json

from ..epw import read_epw
from ..models import Candidate, SourceRef, VariableLineage
from .base import ProviderResult
from .openmeteo import VARIABLES


class PVGISProvider:
    name = "pvgis"

    def discover(self, request, location, http):
        if request.product not in ("tmy", "published"):
            return []
        return [
            Candidate(
                id=f"pvgis:tmy:{location.key}",
                location_id=location.key,
                source=SourceRef(
                    provider=self.name,
                    dataset="PVGIS TMY",
                    version="5_3",
                    license="European Commission reuse policy (CC BY 4.0)",
                    citation="https://joint-research-centre.ec.europa.eu/photovoltaic-geographical-information-system-pvgis_en",
                ),
                weather_types=["tmy"],
                variables=list(VARIABLES.values()),
                interval_minutes=60,
                warnings=[
                    "Coverage and selected source months verified on retrieval; TMY combines satellite radiation and ERA5 meteorology"
                ],
            )
        ]

    def fetch(self, task, http):
        loc = task.parameters["location"]
        params = {"lat": loc["lat"], "lon": loc["lon"], "outputformat": "json"}
        endpoint = "https://re.jrc.ec.europa.eu/api/v5_3/tmy"
        raw = http.get(endpoint, params=params)
        metadata = json.loads(raw)
        native = http.get(endpoint, params={**params, "outputformat": "epw"})
        data = read_epw(native)
        source = task.source.model_copy(update={"location": data.location, "provisional": False})
        data.metadata = {
            "months_selected": metadata["outputs"]["months_selected"],
            "provider_inputs": metadata.get("inputs", {}),
            "native_epw_sha256": hashlib.sha256(native).hexdigest(),
            "product": "published TMY",
        }
        sha = hashlib.sha256(raw).hexdigest()
        data.lineage = {
            name: VariableLineage(
                variable=name,
                source=source,
                raw_sha256=sha,
                transforms=["native PVGIS EPW; source details in provider_inputs"],
            )
            for name in data.data
            if name != "flags"
        }
        return ProviderResult(data, source, raw, native)
