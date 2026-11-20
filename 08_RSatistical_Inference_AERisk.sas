/*
Purpose:
Statistical analysis of treatment-emergent
adverse event risk by treatment group.

Input:
    WORK.SAFETY_ANALYSIS

Output:
    WORK.AE_RISK
*/


proc r;
submit;


# --------------------------------------------------------
# 1. Import the validated SAS dataset into R.
# --------------------------------------------------------

df <- sd2df(
    "safety_analysis",
    "work"
)

names(df) <- toupper(names(df))

df <- as.data.frame(df)

df$TRT01A <- trimws(
    as.character(df$TRT01A)
)


# --------------------------------------------------------
# 2. Define the adverse event endpoints.
# --------------------------------------------------------

endpoints <- c(

    ANY_TEAE =
        "Any treatment-emergent AE",

    ANY_SERIOUS_TEAE =
        "Serious treatment-emergent AE",

    ANY_SITE_REACTION =
        "Application-site reaction",

    ANY_SYNCOPE =
        "Syncope",

    ANY_DIZZINESS =
        "Dizziness"
)


# Identify the treatment groups.

groups <- sort(
    unique(df$TRT01A)
)

groups <- groups[
    !is.na(groups) & nzchar(groups)
]

print(groups)


# Identify placebo without assuming a precise
# capitalization or treatment label.

placebo <- groups[
    grepl("placebo", groups, ignore.case = TRUE)
]

if (length(placebo) != 1) {

    stop(
        "Exactly one placebo treatment group is required."
    )
}


# --------------------------------------------------------
# 3. Define a Wilson confidence interval function.
#
# Used as a building block for the Newcombe
# confidence interval for risk differences.
# --------------------------------------------------------

wilson_ci <- function(x, n, conf = 0.95) {

    if (n <= 0) {
        return(c(NA_real_, NA_real_))
    }

    p <- x / n

    z <- qnorm(
        1 - (1-conf)/2
    )

    denominator <- 1 + z^2/n

    center <- (
        p + z^2/(2*n)
    ) / denominator

    half_width <- (
        z * sqrt(
            p*(1-p)/n + z^2/(4*n^2)
        )
    ) / denominator

    c(
        max(0, center-half_width),
        min(1, center+half_width)
    )
}


# --------------------------------------------------------
# 4. Newcombe score confidence interval for the
#    difference between two independent proportions.
# --------------------------------------------------------

newcombe_ci <- function(x1, n1, x0, n0) {

    p1 <- x1/n1

    p0 <- x0/n0

    ci1 <- wilson_ci(x1, n1)

    ci0 <- wilson_ci(x0, n0)

    difference <- p1-p0

    lower <- difference - sqrt(

        (p1-ci1[1])^2 +

        (ci0[2]-p0)^2
    )

    upper <- difference + sqrt(

        (ci1[2]-p1)^2 +

        (p0-ci0[1])^2
    )

    c(
        max(-1, lower),
        min(1, upper)
    )
}


# --------------------------------------------------------
# 5. Analyze each endpoint.
# --------------------------------------------------------

results <- list()

k <- 1


for (endpoint in names(endpoints)) {


    # Placebo observations.

    control <- df[
        df$TRT01A == placebo,
    ]

    y0 <- control[[endpoint]]

    y0 <- y0[!is.na(y0)]

    n0 <- length(y0)

    x0 <- sum(y0 == 1)

    p0 <- if (n0 > 0) x0/n0 else NA_real_


    # Analyze each treatment group.

    for (group in groups) {

        treatment <- df[
            df$TRT01A == group,
        ]

        y1 <- treatment[[endpoint]]

        y1 <- y1[!is.na(y1)]

        n1 <- length(y1)

        x1 <- sum(y1 == 1)


        if (n1 == 0 || n0 == 0) {
            next
        }


        # Observed incidence proportion.

        p1 <- x1/n1


        # Exact binomial confidence interval
        # (Clopper-Pearson method).

        incidence_ci <- binom.test(
            x1,
            n1,
            conf.level = 0.95
        )$conf.int


        risk_difference <- NA_real_

        rd_lcl <- NA_real_

        rd_ucl <- NA_real_

        relative_risk <- NA_real_

        fisher_p <- NA_real_


        # Compare active treatment groups
        # with placebo.

        if (group != placebo) {

            risk_difference <- p1-p0


            # Confidence interval for
            # independent risk difference.

            rd_ci <- newcombe_ci(
                x1, n1, x0, n0
            )

            rd_lcl <- rd_ci[1]

            rd_ucl <- rd_ci[2]


            # Relative risk.
            # Undefined when placebo incidence is zero.

            if (p0 > 0) {

                relative_risk <- p1/p0
            }


            # Create the 2 x 2 contingency table.
            #
            # Rows:
            # Active treatment, placebo
            #
            # Columns:
            # Event, no event

            tab <- matrix(
                c(
                    x1, n1-x1,
                    x0, n0-x0
                ),
                nrow = 2,
                byrow = TRUE
            )


            # Fisher's exact test.

            if (all(colSums(tab) > 0)) {

                fisher_p <- fisher.test(tab)$p.value

            } else {

                # Both groups have no events or
                # both groups have events in everyone.

                fisher_p <- 1
            }
        }


        # Store the analysis results.

        results[[k]] <- data.frame(

            ENDPOINT = unname(endpoints[endpoint]),

            ENDPOINT_CD = endpoint,

            TRT01A = group,

            REFERENCE = placebo,

            N_SUBJECTS = n1,

            N_EVENTS = x1,

            INCIDENCE = p1,

            INC_LCL = incidence_ci[1],

            INC_UCL = incidence_ci[2],

            RISK_DIFF = risk_difference,

            RD_LCL = rd_lcl,

            RD_UCL = rd_ucl,

            REL_RISK = relative_risk,

            FISHER_P = fisher_p,

            stringsAsFactors = FALSE
        )

        k <- k+1
    }
}


# --------------------------------------------------------
# 6. Combine the individual statistical results.
# --------------------------------------------------------

out <- do.call(
    rbind,
    results
)

rownames(out) <- NULL


# --------------------------------------------------------
# 7. Display results in SAS Studio.
# --------------------------------------------------------

show(out)


# --------------------------------------------------------
# 8. Transfer the R results back to a SAS dataset.
#
# Use the 2026.03-compatible syntax.
# --------------------------------------------------------

df2sd(
    out,
    "ae_risk",
    "work"
)

endsubmit;
run;


/* Apply SAS formatting to the R-generated results. */

data work.ae_risk;

    set work.ae_risk;

    format INCIDENCE
           INC_LCL
           INC_UCL
           RISK_DIFF
           RD_LCL
           RD_UCL percent9.2

           REL_RISK 8.2

           FISHER_P pvalue8.4;

    label

        N_SUBJECTS = "Safety population denominator"

        N_EVENTS = "Number of affected subjects"

        INCIDENCE = "Adverse event incidence"

        RISK_DIFF = "Risk difference versus placebo"

        REL_RISK = "Relative risk versus placebo"

        FISHER_P = "Fisher exact test p-value";

run;


proc print data=work.ae_risk noobs label;
run;