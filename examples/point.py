"""Run explicitly to download two historical days and write a local EPW bundle."""

from openepw import Location, WeatherRequest, fetch

if __name__ == "__main__":
    bundle = fetch(
        WeatherRequest(
            locations=Location(lat=42.44, lon=-76.5, standard_offset_minutes=-300),
            start="2024-01-01",
            end="2024-01-02",
            providers=["openmeteo"],
        )
    )
    print(bundle.model_dump_json(indent=2))
