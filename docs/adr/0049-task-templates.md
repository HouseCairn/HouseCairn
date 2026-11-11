# 0049. A library of task templates, versioned in the repository

- Status: accepted
- Date: 2026-11-10

## Context

A household that starts with HouseCairn knows it has a boiler and smoke alarms; it rarely
knows how often each should be looked after, and typing twenty tasks by hand is where
people give up. The requirements of the MVP ask that the battery of a smoke alarm be added
from a template in less than a minute on a phone, and that the equipment ticked when a
home is created bring its tasks. The intervals must be trustworthy: each one comes from a
source a person can open, and a rule of one country (the yearly service of a boiler,
required by law in France) must not be shown as a rule for everyone.

## Decision

**A YAML file in the repository, versioned with the code.**
`src/housecairn/tasks/task_templates.yaml` holds the equipment (smoke alarms, boiler,
ventilation...) and about twenty templates. A template gives, in English and in French, a
title, the type of item and the types of room it is found in, an indicative interval
(`every`: a number and a unit of the recurrence of tasks), an optional season, a duration
in minutes, indicative materials, an optional procedure, and the **source** of the
interval, a title and an `https` address. A rule of one country carries its `region` (ISO
3166-1 code) and a `note` that says so and what to do elsewhere. The library holds no
secret and no personal data: generic tasks and public sources only.

A change of the library is a pull request, reviewed like code: no table in the database,
no screen to edit the library, nothing downloaded at run time. A person adds the
templates they want; once added, a task is an ordinary task of the home, that nothing
ties to the library any more, so that a later version of the library never changes the
tasks of a home behind its owners.

**A schema, checked twice.** The JSON Schema of the file is published with the
documentation (`docs/_static/schemas/task-templates.schema.json`). A test validates the
file against it in CI, tries changes the schema must refuse, and checks that every
template has its source and that a regional rule has its note. The code reads the file at
the first use and refuses what it cannot rely on (an unknown equipment, unit or season, a
source that is not `https`, a duplicate identifier, a text without both languages).

**A template makes a task through the service of tasks.** `task_templates.add_templates`
calls `services.create_task` for each template, in one transaction, in the language of
the person who adds it: the title, the interval as a task that repeats *after the last
time* (the date of the last time is what a household knows), the season, the duration,
the procedure, and notes with the materials, the regional note and the source. A first
date and a room are optional; without a date, the task waits for one.

**Two ways in.** On a home that exists, **Tasks › Add from a template** lists the
templates by equipment; ticking one and sending adds it (two taps from the list of tasks).
When a home is created, its form lists the equipment; each ticked adds the tasks of its
templates, in the same transaction as the home. The API gives the library
(`GET /api/v1/task-templates/`, both languages) and adds templates to a home
(`POST /api/v1/homes/<id>/tasks/from-templates/`, the `write` scope), as the screens do
(ADR 0003).

**PyYAML becomes a direct dependency.** It was already installed by drf-spectacular and
Apprise; the library is read with `yaml.safe_load`, which builds only plain data (ADR
0001). JSON would need no dependency, but the file is written and reviewed by people, and
YAML reads better with two languages side by side and comments.

## Consequences

- A household starts with the usual tasks of its equipment in one form, and adds others in
  two taps; every interval shown has a source that opens.
- A new template, or a better source, is a change of one file with its test; the French
  text is in the same file, outside the gettext catalogs, and reviewed in the same pull
  request.
- A rule of one country is marked as such. Templates whose rule differs by country carry
  the French rule as an example, with what to do elsewhere; another country's rules can
  be added as further templates or notes.
- Changing the library never changes the tasks already made from it.
