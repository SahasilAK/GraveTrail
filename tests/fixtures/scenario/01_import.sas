/* Customer delivery job: an explicitly referenced CSV source. */
proc import datafile="input/customers.csv" out=work.customers_stage dbms=csv replace;
run;
data staging.customers;
    set work.customers_stage;
    keep customer_id customer_name active;
run;
