/* Establish a CAS session and assign the library. */

cas;
caslib _all_ assign;


/* Check the source tables. */

proc contents data=casuser.adsl varnum;
run;

proc contents data=casuser.adae varnum;
run;

proc contents data=casuser.advs varnum;
run;

proc contents data=casuser.adedish varnum;
run;


/* Check clinically relevant variable values. */

proc freq data=casuser.adsl;
    tables saffl trt01a / missing;
run;

proc freq data=casuser.adae;
    tables trtemfl aeser aedecod / missing;
run;

proc freq data=casuser.advs;
    tables paramcd ablfl / missing;
run;

/*Test Python and installed packages.
We need pandas, NumPy, and SciPy*/

proc python;
submit;

import sys
import importlib.util

print("Python version:", sys.version)

packages = [
    "pandas",
    "numpy",
    "scipy",
    "sklearn",
    "pandera",
    "tsfresh",
    "swat"
]

for package in packages:
    installed = importlib.util.find_spec(package) is not None
    print(f"{package:15s} Installed: {installed}")

endsubmit;
run;

/*Test R;
ggplot2 layers graphical elements*/

proc r;
submit;

print(R.version.string)

packages <- c(
    "haven",
    "ggplot2",
    "dplyr",
    "ggrepel",
    "rtables",
    "tern",
    "exact2x2",
    "gtsummary"
)

for (pkg in packages) {
    cat(
        pkg, ":",
        requireNamespace(pkg, quietly = TRUE),
        "\n"
    )
}

endsubmit;
run;