import itertools
from unittest.mock import patch

from hypothesis import strategies as st, settings
import pytest
from hypothesis import given
from polars.testing import assert_frame_equal, assert_series_equal
from polars.testing.parametric import dataframes, series
import polars as pl

import pandera.errors
from pandera.engines import polars_engine as pe
from pandera.engines.utils import (
    polars_series_coercible,
    polars_object_coercible,
)

numeric_dtypes = [
    pe.Int8,
    pe.Int16,
    pe.Int32,
    pe.Int64,
    pe.UInt8,
    pe.UInt16,
    pe.UInt32,
    pe.UInt64,
    pe.Float32,
    pe.Float64,
]

temporal_types = [pe.Date, pe.DateTime, pe.Time, pe.Timedelta]

other_types = [
    pe.Categorical,
    pe.Bool,
    pe.String,
]

special_types = [
    pe.Decimal,
    pe.Object,
    pe.Null,
    pe.Category,
]

all_types = numeric_dtypes + temporal_types + other_types


def get_series_strategy(type_: pl.DataType) -> st.SearchStrategy:
    return series(allowed_dtypes=type_, null_probability=0.1, size=100)


def get_dataframe_strategy(type_: pl.DataType) -> st.SearchStrategy:
    return dataframes(
        cols=2, allowed_dtypes=type_, null_probability=0.1, size=100
    )


# Hypothesis slow if test is failing
@pytest.mark.parametrize(
    "dtype, strategy",
    list(
        itertools.product(
            all_types, [get_dataframe_strategy, get_series_strategy]
        )
    ),
)
@given(st.data())
@settings(max_examples=5)
def test_coerce_no_cast(dtype, strategy, data):
    pandera_dtype = dtype()

    df = data.draw(strategy(type_=pandera_dtype.type))

    coerced = pandera_dtype.coerce(data_container=df)

    if isinstance(df, pl.DataFrame):
        assert_frame_equal(df, coerced)
    else:
        assert_series_equal(df, coerced)


@pytest.mark.parametrize(
    "from_dtype, to_dtype, strategy",
    [
        (pe.Int16, pe.Int32, get_series_strategy),
        (pe.UInt16, pe.Int64, get_series_strategy),
        (pe.UInt32, pe.UInt64, get_dataframe_strategy),
        (pe.Float32, pe.Float64, get_dataframe_strategy),
        (pe.String, pe.Categorical, get_dataframe_strategy),
        (pe.Int16, pe.String, get_dataframe_strategy),
    ],
)
@given(st.data())
@settings(max_examples=5)
def test_coerce_cast(from_dtype, to_dtype, strategy, data):
    pl_from_dtype = from_dtype()

    pl_to_dtype = to_dtype()

    s = data.draw(strategy(pl_from_dtype.type))

    coerced = pl_to_dtype.coerce(data_container=s)

    if isinstance(s, pl.Series):
        assert coerced.dtype == pl_to_dtype.type
    else:
        assert coerced[coerced.columns[0]].dtype == pl_to_dtype.type


@pytest.mark.parametrize(
    "to_dtype, container",
    [
        (pe.Int8, pl.Series([1000, 100, 200], dtype=pl.Int64)),
        (pe.Bool, pl.Series(["a", "b", "c"], dtype=pl.Utf8)),
        (pe.Int64, pl.DataFrame({"0": ["1", "b"], "1": ["c", "d"]})),
    ],
)
def test_coerce_cast_failed(to_dtype, container):
    pl_to_dtype = to_dtype()

    error = None

    try:
        pl_to_dtype.coerce(data_container=container)
    except Exception as e:
        error = e

    assert error is not None


@pytest.mark.parametrize(
    "to_dtype, container",
    [
        (pe.Int8, pl.Series([1000, 100, 200], dtype=pl.Int64)),
        (pe.Bool, pl.Series(["a", "b", "c"], dtype=pl.Utf8)),
        (pe.Int64, pl.DataFrame({"0": ["1", "b"], "1": ["c", "d"]})),
    ],
)
@patch("pandera.engines.polars_engine.polars_coerce_failure_cases")
def test_try_coerce_cast_failed(_, to_dtype, container):
    pl_to_dtype = to_dtype()

    error = None

    try:
        pl_to_dtype.try_coerce(data_container=container)
    except pandera.errors.ParserError as e:
        error = e

    assert error is not None


@pytest.mark.parametrize("dtype", all_types + special_types)
def test_check_not_equivalent(dtype):
    if str(pe.Engine.dtype(dtype)) == "object":
        actual_dtype = pe.Engine.dtype(int)
    else:
        actual_dtype = pe.Engine.dtype(object)
    expected_dtype = pe.Engine.dtype(dtype)
    assert actual_dtype.check(expected_dtype) is False


@pytest.mark.parametrize(
    "to_dtype, container",
    [
        (pe.UInt32, pl.Series([1000, 100, 200], dtype=pl.Int32)),
        (pe.Int64, pl.Series([1000, 100, 200], dtype=pl.UInt32)),
        (pe.Int16, pl.Series(["1", "2", "3"], dtype=pl.Utf8)),
        (pe.Categorical, pl.Series(["False", "False"])),
        (pe.Float32, pl.Series([None, "1"])),
    ],
)
def test_polars_series_coercible(to_dtype, container):
    is_coercible = polars_series_coercible(container, to_dtype.type)
    assert isinstance(is_coercible, pl.Series)
    assert is_coercible.dtype == pl.Boolean

    assert is_coercible.all() is True


@pytest.mark.parametrize(
    "to_dtype, container, result",
    [
        (
            pe.Bool,
            pl.Series(["False", "False"]),
            pl.Series([False, False]),
        ),  # This tests for Pyarrow error
        (
            pe.Int64,
            pl.Series([None, "False", "1"]),
            pl.Series([True, False, True]),
        ),
        (pe.UInt8, pl.Series([266, 255, 1]), pl.Series([False, True, True])),
    ],
)
def test_polars_series_not_coercible(to_dtype, container, result):
    is_coercible = polars_series_coercible(container, to_dtype.type)
    assert isinstance(is_coercible, pl.Series)
    assert is_coercible.dtype == pl.Boolean

    assert is_coercible.all() is False
    assert_series_equal(is_coercible, result)


@pytest.mark.parametrize(
    "to_dtype, container, result",
    [
        (
            pe.UInt32,
            pl.DataFrame(
                data={"0": [1000, 100, 200], "1": [1000, 100, 200]},
                schema={"0": pl.Int32, "1": pl.Int32},
            ),
            pl.DataFrame(
                data={"0": [True, True, True], "1": [True, True, True]},
                schema={"0": pl.Boolean, "1": pl.Boolean},
            ),
        ),
        (
            pl.Int64,
            pl.Series([1000, 100, 200], dtype=pl.Int32),
            pl.Series([True, True, True]),
        ),
        (
            pe.UInt32,
            pl.DataFrame(
                data={"0": ["1000", "a", "200"], "1": ["1000", "100", "c"]},
                schema={"0": pl.Utf8, "1": pl.Utf8},
            ),
            pl.DataFrame(
                data={"0": [True, False, True], "1": [True, True, False]},
                schema={"0": pl.Boolean, "1": pl.Boolean},
            ),
        ),
        (
            pl.Int64,
            pl.Series(["d", "100", "200"], dtype=pl.Utf8),
            pl.Series([False, True, True]),
        ),
    ],
)
def test_polars_object_coercible(to_dtype, container, result):
    is_coercible = polars_object_coercible(container, to_dtype)

    if isinstance(container, pl.DataFrame):
        assert_frame_equal(is_coercible, result)
    else:
        assert_series_equal(is_coercible, result)
