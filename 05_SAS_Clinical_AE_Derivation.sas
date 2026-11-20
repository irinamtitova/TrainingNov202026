/*
Purpose:
Derive adverse event indicators at the subject level.

Input 1: Safety population from ADSL
Input 2: Treatment-emergent adverse events from ADAE

Output: One observation per safety-population subject.
*/


/* Step 1: Aggregate event-level data to subject level. */

proc sql;

    create table work._ae_agg as

    select USUBJID,

           /* Number of treatment-emergent AE records */
           count(*) as N_TEAE,

           /* At least one treatment-emergent AE */
           1 as ANY_TEAE,

           /* At least one serious TEAE */
           max(
               case
                   when upcase(strip(AESER)) = 'Y'
                   then 1 else 0
               end
           ) as ANY_SERIOUS_TEAE,

           /* Application-site adverse events */
           max(
               case
                   when index(
                       upcase(AEDECOD),
                       'APPLICATION SITE'
                   ) > 0
                   then 1 else 0
               end
           ) as ANY_SITE_REACTION,

           /* At least one syncope event */
           max(
               case
                   when upcase(strip(AEDECOD)) = 'SYNCOPE'
                   then 1 else 0
               end
           ) as ANY_SYNCOPE,

           /* At least one dizziness event */
           max(
               case
                   when upcase(strip(AEDECOD)) = 'DIZZINESS'
                   then 1 else 0
               end
           ) as ANY_DIZZINESS

    from &_input2

    group by USUBJID;

quit;


/*
Step 2: Join the aggregated adverse events to the
complete safety population.

A LEFT JOIN is essential because subjects without
adverse events must remain in the denominator.
*/

proc sql;

    create table &_output1 as

    select a.*,

           coalesce(b.N_TEAE, 0)
               as N_TEAE,

           coalesce(b.ANY_TEAE, 0)
               as ANY_TEAE,

           coalesce(b.ANY_SERIOUS_TEAE, 0)
               as ANY_SERIOUS_TEAE,

           coalesce(b.ANY_SITE_REACTION, 0)
               as ANY_SITE_REACTION,

           coalesce(b.ANY_SYNCOPE, 0)
               as ANY_SYNCOPE,

           coalesce(b.ANY_DIZZINESS, 0)
               as ANY_DIZZINESS

    from &_input1 as a

    left join work._ae_agg as b
        on a.USUBJID = b.USUBJID;

quit;


/* Step 3: Inspect the resulting event indicators. */

proc freq data=&_output1;

    tables TRT01A *
          (ANY_TEAE
           ANY_SERIOUS_TEAE
           ANY_SITE_REACTION
           ANY_SYNCOPE
           ANY_DIZZINESS)

          / norow nocol nopercent;

run;