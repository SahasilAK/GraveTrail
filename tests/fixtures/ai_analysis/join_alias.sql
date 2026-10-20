create table out as select a.id from raw.a a join raw.b b on a.id=b.id where b.active=1;
