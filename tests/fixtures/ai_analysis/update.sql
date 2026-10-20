update target set amount = src.amount + 1 from source src where target.id=src.id;
