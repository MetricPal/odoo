# Gantt View

A `gantt` view type for any model, in Odoo Community.

```xml
<gantt date_start="planned_date_start" date_stop="date_deadline" color="color" progress="progress"
       dependency_field="depend_on_ids" default_group_by="user_ids" default_scale="week">
  <field name="name"/>
</gantt>
```

* **Scales**: day (hours), week, month (days) and year (months); *Today*, previous and next.
* **Grouping**: the first *Group by* of the search bar, else `default_group_by` (many2one, many2many,
  selection); a record with several values (e.g. several assignees) appears in each group.
* **Edit**: drag a bar to move it, drag its right edge to change the end; snaps to the hour (day scale) or the
  day. Clicking a bar opens the record; *New* creates one. `edit="0"` / `create="0"` turn these off.
* **Dependencies**: `dependency_field` (a many2many of predecessors) draws an arrow from each predecessor's end to
  the record's start.
* **Progress**: `progress` (0–100) shades the bar; `color` (an integer) picks the bar colour.
* Records with neither date are counted as "without dates"; a record with one date gets a one-day bar.

The validation of the arch checks that the named fields exist. Writes go through the ORM with the user's rights.
