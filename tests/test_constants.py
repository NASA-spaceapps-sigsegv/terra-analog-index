from tai import constants as C


def test_grid_size():
    assert C.N_CELLS_GLOBAL == 64800
    assert C.N_LAT * C.GRID_RES_DEG == 180


def test_dimensions_and_vars_consistent():
    assert set(C.DIMENSION_VARS) == set(C.PHYSICAL_DIMENSIONS)
    assert len(C.CORE_VARS) == 6  # las que tiene todo objetivo
    assert C.PHYSICAL_VARS == C.CORE_VARS + C.OPTIONAL_VARS
    assert set(C.CORE_DIMENSIONS) | set(C.OPTIONAL_DIMENSIONS) == set(C.PHYSICAL_DIMENSIONS)
    assert set(C.DEFAULT_WEIGHTS) == set(C.DIMENSIONS)
    for var in C.PHYSICAL_VARS:
        assert var in C.VALID_RANGES


def test_bio_types():
    assert len(C.BIO_TYPES) == 6
    assert C.VALID_RANGES["bio_types"] == (0, len(C.BIO_TYPES))


def test_default_weights_in_range():
    for w in C.DEFAULT_WEIGHTS.values():
        assert 0.0 <= w <= 1.0
