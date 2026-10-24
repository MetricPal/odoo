# Report Studio

Readable reports from Odoo data, exported to the format people need.

- A report is a list of **blocks**: heading, text, KPI tile (count / sum /
  average of any model) and table (chosen columns, sort, up to 500 rows).
- **Preview** in the form is the same HTML used for every export: **PDF**
  (Odoo's PDF engine), **Excel** (xlsxwriter), **PowerPoint** (python-pptx),
  **Word** (python-docx) and a standalone **HTML** file.
- Numbers come from queries run with the reader's own access rights. Filters
  are literal lists only (no code), fields must exist, sort is one field.
- Reports are private to their owner unless **Shared** with the company.
- Other modules generate reports by creating `report.studio.report` with
  blocks (Marketing Intelligence's weekly brief does this).

PowerPoint and Word need `python-pptx` and `python-docx` on the server; without
them those two buttons explain what to install.
