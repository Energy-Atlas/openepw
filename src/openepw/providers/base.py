from dataclasses import dataclass
from typing import Protocol

from ..dataset import WeatherDataset
from ..models import Candidate, FetchTask, Location, SourceRef, WeatherRequest
from .http import HttpClient


@dataclass
class ProviderResult:
    dataset: WeatherDataset
    source: SourceRef
    raw: bytes
    native_epw: bytes | None = None


class WeatherProvider(Protocol):
    name: str

    def discover(
        self, request: WeatherRequest, location: Location, http: HttpClient
    ) -> list[Candidate]: ...
    def fetch(self, task: FetchTask, http: HttpClient) -> ProviderResult: ...
