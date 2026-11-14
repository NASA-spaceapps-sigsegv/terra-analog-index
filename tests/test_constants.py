from tai import constants as C


def test_grid_size():
    assert C.N_CELLS_GLOBAL == 64800
    assert C.N_LAT * C.GRID_RES_DEG == 180


def test_dimensions_and_vars_consistent():
    assert set(C.DIMENSION_VARS) == set(C.PHYSICAL_DIMENSIONS)
    assert len(C.PHYSICAL_VARS) == 6
    assert set(C.DEFAULT_WEIGHTS) == set(C.DIMENSIONS)
    for var in C.PHYSICAL_VARS:
        assert var in C.VALID_RANGES


def test_bio_types():
    assert len(C.BIO_TYPES) == 6
    assert C.VALID_RANGES["bio_types"] == (0, len(C.BIO_TYPES))


def test_default_weights_in_range():
    for w in C.DEFAULT_WEIGHTS.values():
        assert 0.0 <= w <= 1.0
