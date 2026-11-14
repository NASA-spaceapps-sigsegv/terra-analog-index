import json
import math
import os
import time

import pandas as pd
import pytest

from pipeline import common
from tai.models import Manifest


def _touch(path, mtime):
    path.write_text("x")
    os.utime(path, (mtime, mtime))
    return path


def test_parser_accepts_force_and_bbox():
    args = common.make_parser("99_test").parse_args(["--force", "--bbox", "-30", "-20", "-75", "-65"])
    assert args.force is True
    assert args.bbox == [-30.0, -20.0, -75.0, -65.0]
    assert common.make_parser("99_test").parse_args([]).bbox is None


def test_bbox_mask():
    lat = pd.Series([-25.0, 10.0])
    lon = pd.Series([-70.0, 10.0])
    assert common.bbox_mask(lat, lon, None).tolist() == [True, True]
    assert common.bbox_mask(lat, lon, [-30, -20, -75, -65]).tolist() == [True, False]
    with pytest.raises(ValueError):
        common.bbox_mask(lat, lon, [-20, -30, -75, -65])


def test_up_to_date(tmp_path):
    inp = _touch(tmp_path / "in.txt", 1000)
    script = _touch(tmp_path / "step.py", 1000)
    out = _touch(tmp_path / "out.parquet", 2000)
    assert common.is_up_to_date([out], [inp, script])

    _touch(script, 3000)  # editing the script invalidates the output
    assert not common.is_up_to_date([out], [inp, script])


def test_missing_output_is_not_up_to_date(tmp_path):
    inp = _touch(tmp_path / "in.txt", 1000)
    assert not common.is_up_to_date([tmp_path / "nope.parquet"], [inp])


def test_directory_input_uses_newest_file(tmp_path):
    raw = tmp_path / "raw"
    raw.mkdir()
    _touch(raw / "a.nc", 1000)
    out = _touch(tmp_path / "out.parquet", 2000)
    assert common.is_up_to_date([out], [raw])
    _touch(raw / "b.nc", 3000)
    assert not common.is_up_to_date([out], [raw])


def test_require_inputs(tmp_path):
    common.require_inputs([_touch(tmp_path / "a", 1)])
    with pytest.raises(common.MissingInputError, match="b.txt"):
        common.require_inputs([tmp_path / "b.txt"])


# --- Atomic writes and manifest ----------------------------------------------


def test_atomic_write_json_rejects_nan(tmp_path):
    path = tmp_path / "x.json"
    with pytest.raises(ValueError):
        common.atomic_write_json({"a": math.nan}, path)
    assert not path.exists()
    assert list(tmp_path.iterdir()) == []  # no temp file left behind


def test_atomic_write_parquet_roundtrip(tmp_path):
    path = tmp_path / "sub" / "t.parquet"
    df = pd.DataFrame({"cell_id": [1, 2]})
    common.atomic_write_parquet(df, path)
    pd.testing.assert_frame_equal(pd.read_parquet(path), df)


def test_column_stats():
    df = pd.DataFrame({"a": [1.0, None, 3.0], "s": ["x", None, "y"]})
    stats = common.column_stats(df, ["a", "s"])
    assert stats["a"] == {"non_null": 2, "null": 1, "min": 1.0, "max": 3.0}
    assert stats["s"] == {"non_null": 2, "null": 1, "min": None, "max": None}


def test_write_step_manifest_upserts(tmp_path, monkeypatch):
    monkeypatch.setattr(common, "ROOT", tmp_path)
    out = tmp_path / "data" / "processed" / "grid.parquet"
    common.atomic_write_parquet(pd.DataFrame({"cell_id": [1]}), out)
    manifest = tmp_path / "manifest.json"

    entry = common.step_entry("01_grid", time.monotonic(), [], [(out, 1)], notes=["first"])
    common.write_step_manifest(entry, grid={"res_deg": 1.0, "n_cells": 1, "land_frac_min": 0.5}, path=manifest)
    entry = common.step_entry("01_grid", time.monotonic(), [], [(out, 1)], notes=["second"])
    common.write_step_manifest(entry, path=manifest)

    data = json.loads(manifest.read_text(encoding="utf-8"))
    Manifest.model_validate(data)
    assert len(data["steps"]) == 1
    assert data["steps"][0]["notes"] == ["second"]
    assert data["steps"][0]["outputs"][0]["path"] == "data/processed/grid.parquet"
    assert data["grid"]["n_cells"] == 1
