"""
Purpose:
Transform longitudinal vital sign measurements into
subject-level analytical features.

Input:
    WORK.VS_INPUT

Output:
    WORK.VS_FEATURES

Libraries:
    pandas
    numpy
    scipy (optional, for robust trend estimation)
"""

import pandas as pd
import numpy as np


# --------------------------------------------------------
# 1. Check whether SciPy is available.
# --------------------------------------------------------

try:
    from scipy.stats import theilslopes
    SCIPY_AVAILABLE = True

except ImportError:
    SCIPY_AVAILABLE = False

print("SciPy available:", SCIPY_AVAILABLE)


# --------------------------------------------------------
# 2. Import the SAS table from the input port.
# --------------------------------------------------------

df = SAS.sd2df(_input1)

# Standardize column names.
df.columns = df.columns.str.upper()

print("Input dimensions:", df.shape)


# --------------------------------------------------------
# 3. Check that the required variables exist.
# --------------------------------------------------------

required_columns = {
    "USUBJID",
    "PARAMCD",
    "AVAL",
    "BASE",
    "CHG",
    "ABLFL",
    "ADY"
}

missing_columns = required_columns - set(df.columns)

if missing_columns:
    raise ValueError(
        f"Missing required columns: {missing_columns}"
    )


# --------------------------------------------------------
# 4. Clean character and numeric variables.
# --------------------------------------------------------

for col in ["USUBJID", "PARAMCD", "ABLFL"]:

    df[col] = (
        df[col]
        .astype("string")
        .str.strip()
    )

df["PARAMCD"] = df["PARAMCD"].str.upper()

df["ABLFL"] = df["ABLFL"].str.upper()


for col in ["AVAL", "BASE", "CHG", "ADY"]:

    df[col] = pd.to_numeric(
        df[col],
        errors="coerce"
    )

    df[col] = df[col].replace(
        [np.inf, -np.inf],
        np.nan
    )


# Retain only relevant vital sign parameters.

parameters = ["SYSBP", "DIABP", "PULSE"]

df = df[
    df["PARAMCD"].isin(parameters)
    & df["USUBJID"].notna()
    & df["USUBJID"].ne("")
].copy()


# --------------------------------------------------------
# 5. Define a function to extract features for one subject
#    and one vital sign parameter.
# --------------------------------------------------------

def extract_features(group):

    group = group.copy()

    # For this teaching example, use measurements after
    # analysis day 1 and exclude baseline-flagged records.
    #
    # Day 1 is excluded deliberately because it may
    # contain both pre-dose and post-dose measurements.

    post = group.loc[
        group["ADY"].gt(1)
        & group["ABLFL"].fillna("").ne("Y")
        & group["AVAL"].notna()
    ].copy()

    post = post.sort_values("ADY")


    # Identify the baseline associated with the
    # post-baseline records.

    baseline_values = (
        post["BASE"]
        .dropna()
        .unique()
    )

    n_baselines = len(baseline_values)

    # Do not combine change measurements if different
    # baseline values suggest different analysis contexts.

    baseline = (
        float(baseline_values[0])
        if n_baselines == 1
        else np.nan
    )


    # Calculate features only from valid measurements.

    n = len(post)

    features = {

        "BASE": baseline,

        "N": n,

        "N_BASE": n_baselines,

        "MIN": np.nan,
        "MAX": np.nan,

        "MEAN_CHG": np.nan,

        "MAX_DROP": np.nan,
        "MAX_RISE": np.nan,

        "SD": np.nan,

        "DAY_MIN": np.nan,

        "SLOPE": np.nan
    }


    # If no post-baseline measurements exist,
    # retain the subject but leave features missing.

    if n == 0:
        return features


    features["MIN"] = post["AVAL"].min()

    features["MAX"] = post["AVAL"].max()

    features["SD"] = post["AVAL"].std(ddof=1)


    # Analysis day of the first minimum measurement.

    min_value = features["MIN"]

    features["DAY_MIN"] = (
        post.loc[
            post["AVAL"].eq(min_value),
            "ADY"
        ].min()
    )


    # Use the existing ADaM change-from-baseline variable.
    # Only use it when a consistent baseline is available.

    if n_baselines == 1:

        change = post.loc[
            post["BASE"].eq(baseline),
            "CHG"
        ].dropna()

        if not change.empty:

            features["MEAN_CHG"] = change.mean()

            # A reduction is represented as a
            # positive magnitude.

            features["MAX_DROP"] = max(
                0.0,
                -change.min()
            )

            # An increase is also represented as
            # a positive magnitude.

            features["MAX_RISE"] = max(
                0.0,
                change.max()
            )


    # Robust longitudinal trend using SciPy.
    #
    # Several measurements can occur on the same day.
    # We first calculate a daily median.

    daily = (
        post.groupby("ADY")["AVAL"]
        .median()
        .sort_index()
    )

    # Calculate a slope only when at least three
    # distinct analysis days are available.

    if SCIPY_AVAILABLE and len(daily) >= 3:

        result = theilslopes(
            y=daily.to_numpy(dtype=float),
            x=daily.index.to_numpy(dtype=float)
        )

        features["SLOPE"] = float(result.slope)

    return features


# --------------------------------------------------------
# 6. Apply the function to every subject and parameter.
# --------------------------------------------------------

records = []

for (subject, parameter), group in df.groupby(
    ["USUBJID", "PARAMCD"],
    sort=True
):

    row = {
        "USUBJID": str(subject),
        "PARAMCD": str(parameter)
    }

    row.update(extract_features(group))

    records.append(row)


# Convert the results into a pandas DataFrame.

long_features = pd.DataFrame(records)

if long_features.empty:
    raise ValueError(
        "No eligible vital sign records found."
    )

print("Long feature table:", long_features.shape)

print(long_features.head())


# --------------------------------------------------------
# 7. Pivot the data to one observation per subject.
# --------------------------------------------------------

feature_names = [
    "BASE",
    "N",
    "N_BASE",
    "MIN",
    "MAX",
    "MEAN_CHG",
    "MAX_DROP",
    "MAX_RISE",
    "SD",
    "DAY_MIN",
    "SLOPE"
]

wide_features = long_features.pivot(
    index="USUBJID",
    columns="PARAMCD",
    values=feature_names
)


# Ensure a consistent output schema even if one
# of the vital sign parameters is absent.

expected_columns = pd.MultiIndex.from_product(
    [feature_names, parameters]
)

wide_features = wide_features.reindex(
    columns=expected_columns
)


# Flatten the hierarchical pandas column structure.
#
# Example:
# ("MAX_DROP", "SYSBP") becomes SYSBP_MAX_DROP.

wide_features.columns = [
    f"{parameter}_{feature}"
    for feature, parameter in wide_features.columns
]

wide_features = wide_features.reset_index()


# Use ordinary Python string objects for SAS transfer.

wide_features["USUBJID"] = (
    wide_features["USUBJID"].astype(str)
)


# --------------------------------------------------------
# 8. Validate the output.
# --------------------------------------------------------

if wide_features["USUBJID"].duplicated().any():

    raise ValueError(
        "Duplicate subjects in output table."
    )

print("Output dimensions:", wide_features.shape)

print(wide_features.head())

print(wide_features.dtypes)


# --------------------------------------------------------
# 9. Transfer the Python DataFrame back to SAS.
# --------------------------------------------------------

SAS.df2sd(
    wide_features,
    _output1
)

print("Vital sign feature engineering completed.")