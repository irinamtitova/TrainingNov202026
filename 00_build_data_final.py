"""
00_build_data_final.py

PURPOSE
-------
Prepare clinical trial safety data for an analytical training workshop.
The source is the publicly available CDISC pilot study (CDISCPILOT01,
Xanomeline TTS in Alzheimer's disease), distributed by PHUSE:
https://github.com/phuse-org/phuse-scripts/tree/master/data/adam/cdisc

These are public example ADaM (Analysis Data Model) datasets intended for
educational and testing purposes. This program does not establish whether
all records are synthetic or derived from de-identified clinical data.

The workshop is intended to illustrate:
  - treatment-emergent adverse events (TEAEs), including application-site
    events that may show a pattern across treatment arms;
  - serious adverse events (reported examples: two syncope and one seizure);
  - a placebo subject (01-705-1186) reported to fall into the potential
    Hy's Law quadrant of an eDISH plot;
  - low pulse measurements after treatment.

These are expected teaching examples, not findings verified by this script.

USAGE
-----
Open this file as a Python Program in SAS Studio and submit the complete
program. SAS Studio supplies the PROC PYTHON wrapper automatically.
A standalone Python interpreter can also run the file.

Dependencies: pandas and pyreadstat in the Python environment used by SAS.
If pyreadstat is not installed, run the following separately in SAS Studio
(only if user-level installation is permitted):

    import sys
    import subprocess
    subprocess.check_call([sys.executable, "-m", "pip", "install",
                           "--user", "pyreadstat"])

The import block below handles the user-level package search path when
necessary. This program does not install or upgrade packages automatically.
In the SAS training environment, the project directory is normally
/home/student/clinical_training. It contains source/ and data/.

OUTPUT
------
The data/ folder receives six datasets, each in SAS Transport v5 (.xpt)
and CSV (.csv) format:
  ADSL     Subject-Level Analysis Dataset (all rows and columns)
  ADAE     Adverse Events Analysis Dataset (all rows and columns)
  ADVS     Vital Signs Analysis Dataset (selected rows and columns)
  ADLBC    Laboratory Chemistry Analysis Dataset (selected rows and columns)
  ADLBHY   Hy's Law Laboratory Analysis Dataset (selected columns)
  ADEDISH  Derived eDISH dataset (one row per evaluable subject)

The ADEDISH calculation is intended as an independent Python implementation
of programs/02_derive_edish.sas (double programming). This script does not
compare the two outputs or establish their equivalence.

SCOPE AND LIMITATIONS
---------------------
This is a teaching-data preparation script, not a validated regulatory
submission pipeline or a clinical diagnostic algorithm.

No safety population filter is applied in Python. Population selection is
intentionally deferred to SAS Visual Analytics (VA) source filters. ADEDISH
currently does not include SAFFL; it must be enriched with SAFFL from ADSL
before VA can apply a safety population source filter to that dataset.

Other methodological and technical limitations are documented alongside
the relevant processing steps below.
"""

import os              # File and directory operations.
import sys             # Identify the active Python interpreter.
import site            # Locate user-installed Python packages.
import subprocess      # Execute pip from within Python.
import importlib       # Refresh Python's import caches.
import time            # Pause between download attempts.
import urllib.request  # Download files from GitHub.
import urllib.error    # Handle network-related errors.
import http.client     # Handle HTTP connection errors.
import pandas as pd    # Data manipulation and date conversion.


# =====================================================================
# INITIALIZE THE PYTHON ENVIRONMENT
# =====================================================================

# SAS Studio executes Python through PROC PYTHON.
# In a fresh SAS Viya image, pyreadstat may not be installed.
#
# Packages installed with pip --user are stored in the
# personal Python package directory rather than in the
# centrally managed Python environment.

# Identify the personal Python package directory.
user_site = site.getusersitepackages()

# Add this directory to Python's module search path.
site.addsitedir(user_site)

# Refresh the import caches.
importlib.invalidate_caches()

try:
    # Try importing pyreadstat if it is already installed.
    import pyreadstat

except ModuleNotFoundError as exc:

    # Do not conceal errors caused by missing dependencies
    # inside pyreadstat itself.
    if exc.name != "pyreadstat":
        raise

    print("pyreadstat is not installed.")
    print("Installing pyreadstat into the user environment...")

    # Use the same Python interpreter that PROC PYTHON uses.
    #
    # -m pip: execute pip as a Python module.
    # install: install the requested package.
    # --user: install into the personal package directory.
    #
    # Pin the version that worked in the previous environment.

    subprocess.check_call([
        sys.executable,
        "-m",
        "pip",
        "install",
        "--user",
        "pyreadstat==1.3.8"
    ])

    # Make the newly installed package visible to the
    # currently running Python process.
    site.addsitedir(user_site)
    importlib.invalidate_caches()

    # Import the newly installed package.
    import pyreadstat


# Print diagnostic information to the SAS Studio log.
print("Python executable:", sys.executable)
print("Python version:", sys.version)
print("Pandas version:", pd.__version__)
print("pyreadstat version:", pyreadstat.__version__)
print("pyreadstat location:", pyreadstat.__file__)
print("User package directory:", user_site)

# =====================================================================
# 1. PROJECT DIRECTORIES AND SOURCE LOCATION
# =====================================================================

# Direct download URL for the original ADaM transport files.
# LIMITATION: master is a moving branch. For reproducible results, a fixed
# Git commit and file checksums would be preferable. Neither is used here.
BASE = "https://raw.githubusercontent.com/phuse-org/phuse-scripts/master/data/adam/cdisc/"

# Use the operating-system user's home directory on the SAS Compute
# Server as the base for the project. expanduser("~") resolves the home
# directory (usually /home/student in this training environment).
# os.path.join combines the directory path and the project folder name.
# ROOT is just a Python variable, not a special keyword. It is independent
# of the script location, so this also works inside PROC PYTHON, where
# a script filename is not necessarily available.
# Unlike SAS WORK, this location can persist between sessions, provided
# the home directory is writable and configured as persistent storage.
# These are server-side files, not SAS Content or CAS tables.
ROOT = os.path.join(os.path.expanduser("~"), "clinical_training")

# Keep downloaded source files separate from the prepared workshop datasets.
SRC = os.path.join(ROOT, "source")
OUT = os.path.join(ROOT, "data")

# Create the directories if necessary. exist_ok=True prevents an error
# when the directory already exists.
os.makedirs(SRC, exist_ok=True)
os.makedirs(OUT, exist_ok=True)

# Make the physical server locations visible in the SAS Studio log.
print("Source directory:", SRC)
print("Output directory:", OUT)


# =====================================================================
# 2. HELPER FUNCTIONS: READ, CONVERT DATES, AND EXPORT DATASETS
# =====================================================================


def get(name):
    """Download an original XPT file if needed and read its data and labels.

    Parameters
    ----------
    name : str
        Dataset name, without its extension (e.g. 'adsl').

    Returns
    -------
    df : pandas.DataFrame
        Observations and variables from the original dataset.
    labels : dict
        Mapping from variable names to their original descriptive labels.
    """
    # Construct the path to the locally cached SAS transport file.
    path = os.path.join(SRC, name + ".xpt")

    # Download only if the file is not already present in the cache.
    # A successful download is retained, so rerunning the program does
    # not require an internet connection for files already available.
    # SAS Compute Server connectivity may be intermittent; retry network
    # failures up to five times instead of stopping on the first error.
    # LIMITATION: no checksum or freshness check is implemented. An
    # outdated cached file can be reused. An unreadable existing file
    # raises an error below; replace or remove it before rerunning.
    if not os.path.exists(path):
        url = BASE + name + ".xpt"
        temporary_path = path + ".part"

        for attempt in range(1, 6):
            try:
                print(f"Downloading {name}, attempt {attempt}/5")

                # Read the response with a 30-second network timeout.
                # The timeout applies to blocking network operations,
                # not necessarily the entire download duration.
                with urllib.request.urlopen(url, timeout=30) as response:
                    content = response.read()

                # Write binary data to a temporary file, not to the final
                # cache location. This avoids caching a partial download.
                with open(temporary_path, "wb") as f:
                    f.write(content)

                # Verify that pyreadstat can read the downloaded XPT file
                # before promoting it to its final filename. Readability
                # is not a checksum or a validation of clinical content.
                pyreadstat.read_xport(temporary_path)
                os.replace(temporary_path, path)

                print(f"Successfully downloaded {name}")
                break

            except (urllib.error.URLError,
                    TimeoutError,
                    http.client.HTTPException) as exc:
                print(f"Download failed: {exc}")

                # Re-raise the final network error, making the failed
                # dataset and underlying exception visible in the log.
                if attempt == 5:
                    raise

                # Allow transient network or routing problems to clear.
                print("Retrying in 3 seconds...")
                time.sleep(3)

            finally:
                # Remove a temporary file if the attempt failed. On a
                # successful attempt os.replace() has already moved it.
                # Non-network errors (e.g. permissions or invalid XPT)
                # propagate rather than being silently ignored.
                if os.path.isfile(temporary_path):
                    os.remove(temporary_path)
    else:
        print(f"Reading cached file: {name}")

    # pyreadstat returns both the table and its metadata. Depending on the
    # original SAS format, dates may be decoded into Python date objects
    # or remain numerical SAS dates.
    df, meta = pyreadstat.read_xport(path)

    # Match each variable name to the corresponding descriptive label.
    # Example: {'USUBJID': 'Unique Subject Identifier', ...}.
    # LIMITATION: other source metadata (formats, lengths, special missing
    # value representations, etc.) is not comprehensively retained.
    labels = dict(zip(meta.column_names, meta.column_labels))
    return df, labels


def convert_sas_date(series):
    """Normalize a declared date column to pandas datetime values.

    SAS stores dates as the number of days since 01JAN1960. In contrast,
    pyreadstat may already have converted the values to Python date or
    datetime objects. Both representations must be handled correctly.

    This assumes that numerical input consists of SAS DATE values, not
    SAS DATETIME values (seconds since 01JAN1960), Excel dates or Unix time.
    Missing dates remain missing. Invalid dates raise an error rather than
    being silently replaced with missing values.
    """
    # Also recognize a numeric column stored with pandas object dtype.
    # infer_dtype ignores missing observations for this classification.
    inferred = pd.api.types.infer_dtype(series, skipna=True)
    if pd.api.types.is_numeric_dtype(series) or inferred in (
        "integer", "floating", "mixed-integer-float"
    ):
        # CRITICAL: specify days and the SAS epoch, instead of allowing
        # pandas to interpret numbers as nanoseconds since 01JAN1970.
        return pd.to_datetime(
            pd.to_numeric(series), unit="D", origin="1960-01-01",
            errors="raise"
        )

    # Already-decoded Python date/datetime objects, or parseable date text.
    # This path also preserves missing dates as NaT (Not a Time).
    # LIMITATION: mixed numeric and date-like values in the same column,
    # ambiguous text dates, and SAS DATETIME values are not supported.
    if inferred in ("mixed", "mixed-integer"):
        raise ValueError(f"Mixed date representations in {series.name!r}")
    return pd.to_datetime(series, errors="raise")


def write(df, labels, name, label, date_cols=()):
    """Export a DataFrame to SAS Transport v5 and CSV.

    Parameters
    ----------
    df : pandas.DataFrame
        Dataset to export. The function does not modify this DataFrame.
    labels : dict
        Mapping of variable names to descriptive variable labels.
    name : str
        Output file name without extension, e.g. 'adsl'. Also used as
        the internal SAS dataset (member) name, in uppercase.
    label : str
        Descriptive dataset label stored in the XPT file.
    date_cols : iterable of str, optional
        Names of columns that represent calendar dates, not timestamps.
        Only columns present in df are processed.

    Output
    ------
    data/<name>.xpt : SAS Transport v5 file with variable labels and date formats.
    data/<name>.csv : CSV file with ISO dates (YYYY-MM-DD); no row index.

    The function also prints the number of observations and variables.
    """
    # SAS Transport v5 allows variable labels of up to 40 characters.
    # Use the variable name itself if the original label is unavailable,
    # and truncate longer labels to meet the v5 restriction.
    # LIMITATION: long labels can lose information; byte limits can also
    # matter for multibyte text. Other v5 limits (e.g. 8-character variable
    # names and 200-byte character values) are not validated here.
    labs = [(labels.get(c) or c)[:40] for c in df.columns]

    # Use DATE9 for the specified date columns in the XPT file.
    # SAS will display a numeric SAS date as e.g. 15MAR2014.
    # Ignore date names that are not present in the current dataset.
    fmt = {c: "DATE9" for c in date_cols if c in df.columns}

    # Prepare separate copies because CSV and XPT need different date
    # representations. Leave the input DataFrame unchanged for later steps.
    xpt = df.copy()
    out = df.copy()
    sas_epoch = pd.Timestamp("1960-01-01")

    for c in fmt:
        # Normalize numerical SAS dates and already-decoded dates using
        # the same conversion function, so both exports represent the
        # same calendar dates.
        dates = convert_sas_date(df[c])

        # XPT: store the number of days since 01JAN1960 as a SAS numeric
        # variable, with the DATE9 display format assigned below.
        # Normalize to calendar days because these are date-only columns.
        # float64 preserves missing values as NaN for the XPT writer.
        xpt[c] = (dates.dt.normalize() - sas_epoch).dt.days.astype("float64")

        # CSV: represent dates as ISO strings for portable importing.
        # Missing dates remain missing and are exported as empty fields.
        out[c] = dates.dt.strftime("%Y-%m-%d")

    # Export the DataFrame as a SAS Transport Version 5 file.
    # table_name: internal SAS dataset name, not the file path.
    # file_label: descriptive label for the dataset itself.
    # column_labels: variable labels in the same order as the columns.
    # variable_format: SAS display formats for the declared date columns.
    # LIMITATION: this is not a lossless copy of all original SAS metadata.
    pyreadstat.write_xport(
        xpt,
        os.path.join(OUT, name + ".xpt"),
        table_name=name.upper(),
        file_label=label,
        column_labels=labs,
        file_format_version=5,
        variable_format=fmt,
    )

    # Export the CSV version without the pandas row index, which is not
    # part of the clinical dataset. CSV cannot retain SAS variable labels
    # or SAS formats. Existing output files are overwritten on reruns.
    out.to_csv(os.path.join(OUT, name + ".csv"), index=False)

    # Print dimensions to make it easier to inspect the preparation log.
    # LIMITATION: the dimensions alone do not validate the contents.
    # No read-back or source-to-output comparison is implemented here.
    print(f"{name:11s} {len(df):6d} rows {len(df.columns):3d} cols")


# =====================================================================
# 3. ADSL AND ADAE: SUBJECT CHARACTERISTICS AND ADVERSE EVENTS
# =====================================================================

# ADSL has one row per subject. It contains demographics, treatment
# assignment, study participation and analysis population flags.
# ADAE contains adverse event analysis records; subjects may have many.
# Retain all source rows and columns in both datasets, with only export
# representation changes (dates, labels, formats).
adsl, l_adsl = get("adsl")
adae, l_adae = get("adae")

# TRTSDT = treatment start date; TRTEDT = treatment end date.
# DISONSDT = disease onset date; VISIT1DT = first visit date;
# RFENDT = end of subject reference period (see source definition).
write(adsl, l_adsl, "adsl", "Subject-Level Analysis Dataset",
      ["TRTSDT", "TRTEDT", "DISONSDT", "VISIT1DT", "RFENDT"])

# ASTDT = adverse event analysis start date; AENDT = analysis end date.
# Important downstream variables include AESER (serious event flag),
# AESEV (severity), AEDECOD (coded event term), and TRTEMFL (TEAE flag).
# Seriousness is a regulatory concept and is not synonymous with severity.
# LIMITATION: expected serious event counts and dose/arm patterns are
# not verified. No TEAE or safety population filter is applied here.
# In VA, count distinct subjects for incidence, not simply event rows.
write(adae, l_adae, "adae", "Adverse Events Analysis Dataset",
      ["TRTSDT", "TRTEDT", "ASTDT", "AENDT"])

# Create a lookup Series indexed by USUBJID, mapping each subject to
# their study site. This will be used to enrich ADLBC below.
# LIMITATION: assumes USUBJID is unique in ADSL; no uniqueness or key
# completeness check is performed. Unmatched subjects map to missing.
site = adsl.set_index("USUBJID")["SITEID"]


# =====================================================================
# 4. ADVS: VITAL SIGNS ANALYSIS DATASET
# =====================================================================

advs, l_advs = get("advs")

# PARAMCD is the short analysis parameter code. Keep only:
# SYSBP = systolic blood pressure; DIABP = diastolic blood pressure;
# PULSE = pulse rate. Other vital sign parameters are discarded.
# .copy() creates an independent DataFrame after filtering.
advs = advs[advs.PARAMCD.isin(["SYSBP", "DIABP", "PULSE"])].copy()

# Retain identifiers, demographics, treatment, measurement dates/time
# points, visit information, values, flags and reference range indicators.
# AVAL = analysis value; BASE = baseline; CHG = change from baseline.
# ANL01FL = analysis record selection flag; ABLFL = baseline flag.
# ANRLO/ANRHI = lower/upper analysis reference range limits.
# BNRIND/ANRIND = baseline/current reference range indicator.
# VSSEQ links back to the source vital signs sequence number.
# LIMITATION: exact column names are expected; a missing column causes
# a KeyError. No schema check is performed before selecting columns.
keep = ["STUDYID", "SITEID", "USUBJID", "AGE", "AGEGR1", "SEX", "RACE", "SAFFL", "TRTSDT", "TRTEDT",
        "TRTA", "TRTAN", "PARAMCD", "PARAM", "PARAMN", "ADT", "ADY", "ATPTN", "ATPT", "AVISIT", "AVISITN",
        "AVAL", "BASE", "CHG", "ANL01FL", "ABLFL", "ANRLO", "ANRHI", "BNRIND", "ANRIND", "VSSEQ"]
advs = advs[keep]

# Export the reduced dataset. Low pulse after treatment is a downstream
# teaching scenario, not a finding validated or classified by this code.
write(advs, l_advs, "advs", "Vital Signs Analysis Dataset (subset)",
      ["TRTSDT", "TRTEDT", "ADT"])


# =====================================================================
# 5. ADLBC: LABORATORY CHEMISTRY ANALYSIS DATASET
# =====================================================================

adlbc, l_lbc = get("adlbc")

# Select laboratory parameters relevant to liver, kidney and metabolic
# safety: ALT (alanine aminotransferase), AST (aspartate aminotransferase),
# ALP (alkaline phosphatase), BILI (bilirubin), CREAT (creatinine),
# and GLUC (glucose). All other laboratory parameters are discarded.
adlbc = adlbc[adlbc.PARAMCD.isin(["ALT", "AST", "ALP", "BILI", "CREAT", "GLUC"])].copy()

# Look up the study site using the subject identifier in ADSL.
# map preserves the rows in ADLBC and adds (or replaces) SITEID.
# This is conceptually a many-to-one lookup/left join in SAS.
# LIMITATION: missing matches or conflicting site information are not
# checked; the ADSL site identifier is treated as authoritative.
adlbc["SITEID"] = adlbc.USUBJID.map(site)
l_lbc["SITEID"] = "Study Site Identifier"

# Keep the variables needed for longitudinal laboratory safety analysis.
# A1LO/A1HI are analysis reference limits used by this source dataset.
# R2A1HI is the source-provided ratio of the analysis value to the
# upper reference limit (AVAL / A1HI), i.e. multiples of ULN.
# LBSEQ links back to the source lab sequence number.
# LIMITATION: the provided ratios, measurement units, and reference
# limits are not independently checked or recalculated.
keep = ["STUDYID", "SITEID", "USUBJID", "TRTA", "TRTAN", "AGE", "AGEGR1", "SEX", "RACE", "SAFFL",
        "TRTSDT", "TRTEDT", "AVISIT", "AVISITN", "ADY", "ADT", "PARAM", "PARAMCD", "PARAMN",
        "AVAL", "BASE", "CHG", "A1LO", "A1HI", "R2A1HI", "ANL01FL", "ANRIND", "BNRIND", "ABLFL", "LBSEQ"]
adlbc = adlbc[keep]
write(adlbc, l_lbc, "adlbc", "Lab Chemistry Analysis Dataset (subset)",
      ["TRTSDT", "TRTEDT", "ADT"])


# =====================================================================
# 6. ADLBHY: EXISTING HY'S LAW LABORATORY ANALYSIS DATASET
# =====================================================================

adlbhy, l_hy = get("adlbhy")

# Retain all source observations, but only the columns below.
# PARAMTYP distinguishes types of analysis parameters where populated.
# CRIT1 describes the analysis criterion; CRIT1FL indicates whether it
# has been met. The source may include derived liver safety parameters.
# No new Hy's Law derivation is performed in this section.
# LIMITATION: the source derivations are not independently validated.
keep = ["STUDYID", "USUBJID", "TRTA", "TRTAN", "SAFFL", "AVISIT", "AVISITN", "ADY", "ADT",
        "PARAMTYP", "PARAM", "PARAMCD", "PARAMN", "AVAL", "BASE", "A1LO", "A1HI", "R2A1HI",
        "CRIT1", "CRIT1FL", "ANL01FL", "ABLFL"]
adlbhy = adlbhy[keep]
write(adlbhy, l_hy, "adlbhy", "Hy's Law Lab Analysis Dataset", ["ADT"])


# =====================================================================
# 7. ADEDISH: DERIVE THE SUBJECT-LEVEL LIVER SAFETY SCREENING DATASET
# =====================================================================

# eDISH = Evaluation of Drug-Induced Serious Hepatotoxicity.
# The conventional eDISH scatter plot displays peak ALT and total
# bilirubin, each as a multiple of the upper limit of normal (ULN).
# There is one dot per evaluable subject, generally on logarithmic axes.
# AST is retained here as an additional descriptive laboratory measure,
# but it does not enter the quadrant classification.

# Step 7.1: Select ALT, AST and BILI measurements on analysis day >= 1.
# This is the workshop's operational definition of the post-baseline
# observation window, including scheduled and unscheduled visits.
# LIMITATIONS:
# - ADY >= 1 does not guarantee a measurement was taken after first dose;
#   day 1 may include pre-dose or baseline observations.
# - There is no upper time limit, so post-treatment follow-up may enter
#   the maxima. The appropriate risk window depends on the protocol/SAP.
# - ABLFL and ANL01FL are not used to select eligible analysis records.
# - SAFFL is deliberately NOT filtered: selection is deferred to SAS VA.
lb = adlbc[adlbc.PARAMCD.isin(["ALT", "AST", "BILI"]) & (adlbc.ADY >= 1)]

# Step 7.2: Aggregate the repeated laboratory measurements by subject
# and parameter, then transpose the results into one row per subject.
# R2A1HI expresses each value in multiples of the upper normal limit.
# Example: ALT = 120 U/L, ULN = 40 U/L -> 3 times ULN.
# aggfunc='max' calculates the maximum available ratio for each parameter.
# LIMITATION: ALT, AST and bilirubin maxima are calculated independently
# and may have occurred on different dates. This is appropriate for eDISH
# screening, but does not establish a temporal association. Dates of the
# maxima are not retained. Nonpositive ratios are not screened before
# plotting on logarithmic axes. The source ratios are not validated.
peak = lb.pivot_table(index="USUBJID", columns="PARAMCD", values="R2A1HI", aggfunc="max")

# Rename ALT, AST and BILI to ALTXULN, ASTXULN and BILIXULN.
# XULN means 'times the upper limit of normal'. reset_index() turns
# the subject identifier from a pandas index back into a regular column.
# LIMITATION: if a required parameter is entirely absent, pivot_table
# might not create its column and later steps can fail with a KeyError.
peak.columns = [c + "XULN" for c in peak.columns]
peak = peak.reset_index()

# Step 7.3: Add actual treatment, demographics and study site from ADSL.
# The inner join retains only subjects present in BOTH tables.
# LIMITATIONS:
# - Subjects with no selected measurements are excluded, and duplicate
#   ADSL subject identifiers could create duplicate output rows.
# - SAFFL is not included in this original output schema. To use a VA
#   safety-population source filter for ADEDISH, enrich the dataset with
#   SAFFL from ADSL first, using a validated many-to-one subject lookup.
#   This script intentionally leaves the existing schema unchanged.
peak = adsl[["STUDYID", "USUBJID", "SITEID", "TRT01A", "AGE", "SEX", "RACE"]].merge(
    peak, on="USUBJID", how="inner"
)

# Step 7.4: Retain only subjects with both an ALT maximum and a bilirubin
# maximum. Missing AST alone does not exclude a subject from the plot.
# LIMITATION: one row per EVALUABLE subject, not necessarily every subject
# in ADSL. There is no reconciliation of exclusions or missing data by
# treatment arm. For percentages, explicitly define the denominator and
# do not assume the number of ADEDISH rows is the safety population size.
peak = peak.dropna(subset=["ALTXULN", "BILIXULN"])


def quadrant(r):
    """Assign an eDISH screening quadrant using peak ALT and bilirubin.

    Thresholds used by this workshop: ALT >= 3 x ULN, BILI >= 2 x ULN.
    Exact boundary conventions should match the study analysis plan and
    the independent SAS implementation. The labels describe screening
    quadrants, not confirmed diagnoses of drug-induced liver injury.
    """
    # Two Boolean indicators determine which of four quadrants applies.
    alt, bili = r.ALTXULN >= 3, r.BILIXULN >= 2

    # Both thresholds exceeded or met: potential Hy's Law screening signal.
    # LIMITATION: this does NOT establish a Hy's Law case. A clinical
    # review should consider ALP/cholestasis, the timing of elevations,
    # baseline abnormalities, other medications and alternative causes.
    # ALP is available in ADLBC but is not evaluated by this function.
    if alt and bili:
        return "Potential Hy's Law"

    # Elevated ALT without bilirubin reaching its screening threshold.
    if alt:
        return "Temple's Corollary"

    # Elevated bilirubin without ALT reaching its screening threshold.
    if bili:
        return "Hyperbilirubinemia"

    # Neither screening threshold is reached. This does not mean either
    # laboratory value is normal: ALT may still be above 1 x ULN, for
    # example. The former label 'Normal' was therefore misleading.
    return "Below eDISH thresholds"


# Step 7.5: Apply the classification function separately to every subject.
# axis=1 means that pandas passes one row at a time to quadrant().
peak["EDISHCAT"] = peak.apply(quadrant, axis=1)

# Step 7.6: Define descriptive variable labels for the derived dataset.
l_ed = {"STUDYID": "Study Identifier", "USUBJID": "Unique Subject Identifier", "SITEID": "Study Site Identifier",
        "TRT01A": "Actual Treatment for Period 01", "AGE": "Age", "SEX": "Sex", "RACE": "Race",
        "ALTXULN": "Peak ALT x ULN", "ASTXULN": "Peak AST x ULN", "BILIXULN": "Peak Bilirubin x ULN",
        "EDISHCAT": "eDISH Category"}

# Step 7.7: Export the newly derived, subject-level screening dataset.
write(peak, l_ed, "adedish", "eDISH data, one row per subject")

# Print the observed number of subjects in each quadrant to the log.
# LIMITATION: this is descriptive output, not an automated validation.
# Neither the expected placebo subject nor agreement with the independent
# SAS implementation is verified. Double programming requires comparing
# subject identifiers, peak values, missingness and derived categories,
# then investigating all discrepancies. If the SAS version still uses
# 'Normal', align that label before comparing classifications.
print(peak.EDISHCAT.value_counts().to_string())
