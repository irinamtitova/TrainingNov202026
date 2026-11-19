/**************************************************************************
 Program: 01_load_data_to_cas.sas
 Purpose: Import the six clinical XPT files produced by 00_build_data.py,
          load them into CAS, and promote them for SAS Visual Analytics.

 Usage:   Open as a SAS Program in SAS Studio and run the entire file.
          Can be run on a fresh image or rerun after rebuilding the data.

 Input:   /home/student/clinical_training/data/*.xpt
 Output:  ADSL, ADAE, ADVS, ADLBC, ADLBHY, ADEDISH in CASUSER.
          Optional persistent .sashdat files in the target caslib.

 WARNING: Reruns replace the six named in-memory tables in the target
          caslib. Existing reports may be briefly affected. Do not use
          this loader against a shared production caslib without approval.
          Replacement is not atomic; there is no automatic rollback.
**************************************************************************/

/* 1. CONFIGURATION -------------------------------------------------- */

%let root=/home/student/clinical_training/data;
%let target=CASUSER;
%let datasets=adsl adae advs adlbc adlbhy adedish;

/* YES: also save/overwrite the corresponding .sashdat files in CASUSER.
   NO:  only create promoted in-memory tables (sufficient for VA). */
%let save_sashdat=NO;

/* 2. IMPORT HELPER -------------------------------------------------- */

%macro import_xpt(name);
    %local rc;
    %put NOTE: Importing &name from its XPT file.;

    /* XPORT reads the SAS Transport v5 file and retains its available
       SAS variable types, labels and formats. WORK is Compute storage. */
    libname clnxpt xport "&root./&name..xpt";
    %if %sysfunc(libref(clnxpt)) ne 0 %then %do;
        %let failed=1;
        %put ERROR: Cannot assign XPORT libref for &name..;
        %return;
    %end;

    data work.&name;
        set clnxpt.&name;
    run;
    %let rc=&syserr;
    libname clnxpt clear;

    %if &rc > 4 or not %sysfunc(exist(work.&name)) %then %do;
        %let failed=1;
        %put ERROR: XPT import failed for &name..;
        %return;
    %end;
%mend import_xpt;

/* 3. CAS LOADING HELPER --------------------------------------------- */

%macro load_clinical(name);
    %local rc sql_status expected actual table stage;
    %let table=%upcase(&name);
    %let stage=_CLN_STAGE_&table;

    /* Determine the expected row count on the Compute Server. */
    proc sql noprint;
        select count(*) into :expected trimmed from work.&name;
    quit;
    %let sql_status=&sqlrc;
    %if &sql_status ne 0 or %length(%superq(expected))=0 %then %do;
        %let failed=1;
        %put ERROR: Cannot count rows in WORK.&name..;
        %return;
    %end;

    /* First load a temporary session-scope version of the new table.
       REPLACE is valid here for a session-scope staging table.
       This avoids deleting the old promoted table before the new data
       have successfully reached CAS. */
    proc casutil sessref=clnload;
        load data=work.&name
             outcaslib="&target"
             casout="&stage"
             replace;
    quit;
    %let rc=&syserr;
    %if &rc > 4 %then %do;
        %let failed=1;
        %put ERROR: CAS staging load failed for &table..;
        %return;
    %end;

    /* Verify the staging table row count before dropping the old table.
       CLNCAS is the SAS libref connected to the chosen CAS caslib. */
    %let actual=;
    proc sql noprint;
        select count(*) into :actual trimmed from clncas.&stage;
    quit;
    %let sql_status=&sqlrc;
    %if &sql_status ne 0 or %length(%superq(actual))=0 %then %do;
        %let failed=1;
        %put ERROR: Cannot verify the CAS staging table &stage..;
        %return;
    %end;
    %if &actual ne &expected %then %do;
        %let failed=1;
        %put ERROR: Staging row count mismatch for &table: &expected vs &actual..;
        %return;
    %end;

    /* Remove the old in-memory table if it exists. QUIET allows the
       same code to run on a fresh image where the table is absent.
       This does NOT delete a physical .sashdat or the source XPT file. */
    proc casutil sessref=clnload;
        droptable casdata="&table" incaslib="&target" quiet;
    quit;
    %let rc=&syserr;
    %if &rc > 4 %then %do;
        %let failed=1;
        %put ERROR: Could not drop existing CAS table &table..;
        %return;
    %end;

    /* Promote under the final name. Global-scope tables are available
       to other authorized sessions, such as Visual Analytics sessions.
       DROP removes the session-scope staging table after promotion.
       PROMOTE cannot replace a global-scope table in one operation. */
    proc casutil sessref=clnload;
        promote casdata="&stage" incaslib="&target"
                casout="&table" outcaslib="&target" drop;
    quit;
    %let rc=&syserr;
    %if &rc > 4 %then %do;
        %let failed=1;
        %put ERROR: Promotion failed for &table..;
        %return;
    %end;

    /* Compare the final CAS table with the imported SAS dataset. */
    %let actual=;
    proc sql noprint;
        select count(*) into :actual trimmed from clncas.&table;
    quit;
    %let sql_status=&sqlrc;
    %if &sql_status ne 0 or %length(%superq(actual))=0 %then %do;
        %let failed=1;
        %put ERROR: Cannot verify final CAS table &table..;
        %return;
    %end;
    %if &actual ne &expected %then %do;
        %let failed=1;
        %put ERROR: Final row count mismatch for &table: &expected vs &actual..;
        %return;
    %end;
    %put NOTE: VERIFIED &target..&table - &actual rows (matches WORK).;

    /* Optional: persist this promoted table as a SASHDAT file in the
       caslib's backing storage. REPLACE refers to the physical file,
       not to the promoted in-memory table. Requires write permission. */
    %if %upcase(&save_sashdat)=YES %then %do;
        proc casutil sessref=clnload;
            save casdata="&table" incaslib="&target"
                 outcaslib="&target" casout="&name..sashdat" replace;
        quit;
        %let rc=&syserr;
        %if &rc > 4 %then %do;
            %let failed=1;
            %put ERROR: SASHDAT save failed for &table..;
            %return;
        %end;
    %end;
%mend load_clinical;

/* 4. MAIN PROGRAM --------------------------------------------------- */

%macro load_all_clinical;
    %local i name failed rc;
    %let failed=0;

    /* Check all six files BEFORE modifying any existing CAS table. */
    %do i=1 %to %sysfunc(countw(&datasets));
        %let name=%scan(&datasets,&i);
        %if not %sysfunc(fileexist(&root./&name..xpt)) %then %do;
            %put ERROR: Missing source file &root./&name..xpt.;
            %let failed=1;
        %end;
    %end;
    %if &failed %then %do;
        %put ERROR: Run 00_build_data.py first. No CAS tables were changed.;
        %return;
    %end;

    /* Import all six files successfully into WORK before touching CAS. */
    %do i=1 %to %sysfunc(countw(&datasets));
        %let name=%scan(&datasets,&i);
        %import_xpt(&name);
        %if &failed %then %do;
            %put ERROR: Import stopped. No CAS tables were changed.;
            %return;
        %end;
    %end;

    /* Start (or reuse) a named CAS session and assign a SAS libref.
       The session is left open for subsequent CAS actions in Studio. */
    cas clnload;
    libname clncas cas sessref=clnload caslib="&target";
    %if %sysfunc(libref(clncas)) ne 0 %then %do;
        %put ERROR: Cannot connect to the target caslib &target..;
        %return;
    %end;

    /* Sequentially stage, verify and replace the six tables. */
    %do i=1 %to %sysfunc(countw(&datasets));
        %let name=%scan(&datasets,&i);
        %load_clinical(&name);
        %if &failed %then %do;
            %put ERROR: Loading stopped at &name. Check the log before rerunning.;
            %put ERROR: Earlier tables may already have been replaced.;
            %return;
        %end;
    %end;

    /* List the resulting in-memory tables. */
    proc casutil sessref=clnload;
        list tables incaslib="&target";
    quit;

    /* Inspect the metadata of ADSL and fetch a few observations.
       These are useful checks of variable labels and date formats. */
    proc cas;
        /* PROC CAS selects a session with the CASL SESSION statement,
           unlike PROC CASUTIL, which accepts SESSREF= in its header. */
        session clnload;
        table.columnInfo / table={caslib="&target", name="ADSL"};
        table.fetch / table={caslib="&target", name="ADSL"} to=5;
    run;
    quit;

    %put NOTE: All six clinical tables passed the row-count checks.;
    %put NOTE: Open SAS Visual Analytics and select tables from &target..;
%mend load_all_clinical;

/* 5. EXECUTE -------------------------------------------------------- */

%load_all_clinical;

/* End of program. No safety-population filter is applied here.
   Row counts do not validate clinical logic, metadata or date values.
   ADEDISH does not contain SAFFL in the existing Python output schema.
   Add it separately if a VA source filter on SAFFL is required. */
