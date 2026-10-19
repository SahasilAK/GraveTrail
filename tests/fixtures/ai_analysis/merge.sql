merge into target t using source s on t.id=s.id when matched then update set amount=s.amount;
