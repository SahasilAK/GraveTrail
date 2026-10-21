def model(dbt, session):
    return dbt.ref("fct_orders")
