"""Inspect a future plan; use --execute to read climate data and generate output."""

import argparse

from openepw import FutureRequest, execute, plan_future

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("baseline")
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    request = FutureRequest(
        baseline=args.baseline,
        target_year=2050,
        reference_period=(1985, 2014),
        climate_scenario="ssp245",
    )
    plan = plan_future(request)
    print((execute(plan) if args.execute else plan).model_dump_json(indent=2))
