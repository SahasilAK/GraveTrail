SELECT o.id, o.amount INTO #stage
FROM [raw].[orders] o;
INSERT INTO [mart].[orders]
SELECT id, amount FROM #stage;
INSERT INTO [mart].[audit] SELECT id FROM [stage];
