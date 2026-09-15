# Extending SERVE MD Intelligence

## Add a scoring variable from an existing source

1. Add a `metrics` entry to `config/metrics.yaml`:

   ```yaml
   - id: pct_65_plus_veterans
     label: Veterans share of 65+
     description: Share of the 65+ population with veteran status.
     pillar: demographics
     unit: pct
     format: percent
     higher_is_better: true
     geo_levels: [state, county, zcta, place]
     source: acs5
     derivation: B21001_004E+... / B21001_002E
     scoring_default: 5
   ```

2. Emit rows with that `metric_id` from the source's `transform()` (`pipelines/sources/acs5.py`
   has a table→metric mapping; usually one line).
3. `python -m pipelines.build --source acs5`, `make docs`.

The metric now appears in the market profile panel for its pillar, in the Score Editor with its
default weight, in `/api/meta/metrics`, in ranking filters and CSV exports, and in the data
dictionary. No schema or frontend change is required.

## Add a new public dataset

1. Add a `sources` entry (name, publisher, URL, vintage, geo levels) and its metrics to
   `config/metrics.yaml`.
2. Create `pipelines/sources/<source_id>.py`:

   ```python
   from backend.app.settings import settings
   from pipelines.base import Source, Tidy, download, suppressed_to_null


   class MySource(Source):
       source_id = "my_source"  # must match the `sources` key in metrics.yaml
       geo_levels = ("county",)

       def extract(self) -> dict[str, Path]:
           return {"main": download(URL, settings.raw_dir / self.source_id, "file.csv")}

       def transform(self, raw: dict[str, Path]) -> Tidy:
           df = pd.read_csv(raw["main"], dtype=str)
           df["value"] = suppressed_to_null(df["VALUE"])
           ...
           return Tidy(metric_values=long_df)  # columns: geo_level, geo_id, metric_id, period, value
   ```

3. Register it in `pipelines/sources/__init__.py` (`SOURCES`). Order matters only if the source
   needs geography from `census_geo`.
4. Add a test under `pipelines/tests/` that runs `transform()` on a small checked-in sample file.

`Source.run()` handles caching, registry validation (unknown `metric_id`s fail loudly), upserts,
feature rebuild and provenance.

## Add a pillar

Add it to `pillars` in `config/scoring_default.yaml` and reference it from metrics. The Score
Editor, market profile and rankings table render pillars dynamically.

## Add a geography level

Extend `GeoLevel` in `backend/app/models/geo.py`, load its units/crosswalk/boundaries in
`census_geo`, and list it in the relevant metrics' `geo_levels`.

## Add a financial-model input

Add the field to the relevant Pydantic block in `backend/app/models/financial.py` and a default in
`config/financial_default.yaml`; use it in `engines/financial/engine.py`. The Financial Model page
renders assumption blocks generically, so the new input is editable immediately. Add a test in
`backend/tests/test_financial.py`.

## Add an API consumer or batch job

The engines are pure functions: `score_frame(features, config)`, `rank_markets(con, request,
config)`, `run_model(assumptions)`. Import them directly for notebooks, scheduled exports or
alternative front-ends.
