.PHONY: migrate seed-course

migrate:
	.venv/bin/python -m pipeline.db_guard && npx prisma migrate deploy

seed-course:
	@test -n "$(COURSE)" || (echo "COURSE is required, e.g. make seed-course COURSE=multivariable-calculus" && exit 1)
	.venv/bin/python -m pipeline.db_guard && \
	.venv/bin/python -m pipeline.course_orchestrator --course $(COURSE) --include-thin
