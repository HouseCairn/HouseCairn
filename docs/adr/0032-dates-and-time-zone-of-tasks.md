# 0032. Dates and time zone of tasks

- Status: accepted
- Date: 2026-11-08

## Context

Clocks change twice a year, months have 28 to 31 days and the people of a home live
in one time zone. A task "every Monday" must not slip to Sunday because a night
lasted 23 hours.

## Decision

**A due date is a calendar day, never a moment.** Due dates, completion dates and
the masking delay are `DateField`s; all arithmetic (ADR 0031) is on dates, so a
change of clock cannot move a task, and no test needs to fake a zone to be right.

**"Today" is the day in the time zone of the instance**, the `TIME_ZONE` setting
(UTC by default, ADR 0012), through `django.utils.timezone.localdate`. It decides
what is late, what a completion date defaults to and what "in the future" means.
Instants (`created_at`, `updated_at`, `deleted_at`) stay in UTC.

**Not one zone per home yet.** A home has no time zone field: adding one touches
the `homes` app, and the instance of a household is in practice in one zone. The
decision is reversible: `tasks.services.today()` is the single place that reads the
clock, and a zone per home would replace it by a function of the home, with the
setting as the default.

## Consequences

- A person who completes a task at 23:30 in a zone other than the instance's may see
  it done on the day before or after in their own zone; a per-home zone would fix it.
- Tests pin the day by replacing `services.today`, and prove that two zones read one
  instant as two different days, and that the nights of the change of clock (23 and
  25 hours) are one day each.
