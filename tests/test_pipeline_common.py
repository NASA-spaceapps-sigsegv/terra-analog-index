import os

import pandas as pd
import pytest

from pipeline import common


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
