# Report Studio (Dashboards › Reports)

Box-based reports and dashboards, on the **Reports** page of the Dashboards app
(next to the spreadsheet dashboards).

## Boards and boxes

- A report is a page of **boxes** on a **4-column grid**. Each box spans 1, 2,
  3 or 4 columns; a row holds boxes until their widths add up to 4.
- Box types: **Title**, **Text**, **Number** (count / sum / average, with
  prefix and suffix), **Chart** (bar, horizontal bar, line, pie, donut; grouped
  by any field, dates by day/week/month/quarter/year), **Table** (chosen
  columns, sort, up to 500 rows), **List**, **Image**, **Hyperlink** and
  **View from an app**.
- On the **Board** tab: *Add box*, drag ⠿ to move, 1–4 to set the width, ✎ to
  edit (filter editor and field pickers), 🗑 to remove. Double-click a box to edit.
- **Add to report**: in the ⋯ menu of any list, graph, pivot or kanban opened
  from a menu, add that view (with its filters, grouping and measures) to an
  existing or new report. Graphs become charts, pivots become grouped tables,
  lists become tables with the list's visible columns.
- Other modules create reports in code (`report.studio.report` with
  `block_ids`); Marketing Intelligence's weekly brief does this.

## Page and exports

- **Page size**: A5, A4, A3, Letter, Legal, Tabloid; portrait or landscape.
- **Scaling**: *Actual size* (content flows over pages), *Fit on one page*
  (shrinks if too tall), *Fill the page* (rows stretched to the page height,
  shrunk if too tall).
- **⋯ › Export**: PDF, Excel, PowerPoint, Word, HTML. Every format keeps the
  grid and the page settings: PDF uses the paper size and margins; Excel sets
  paper, orientation and fit-to-page with native charts; PowerPoint uses
  slides of the paper size with native charts and tables (Fit/Fill: one
  slide); Word sets page size and orientation, boxes in grid tables, charts as
  images; HTML is a printable page of the chosen size.

PowerPoint and Word need `python-pptx` and `python-docx` on the server
(`pip install python-pptx python-docx`); without them those exports explain
what to install. Exact Fit/Fill in PDF needs the patched wkhtmltopdf build that
Odoo recommends (0.12.6 "with patched qt"); an unpatched build still keeps Fit
on one page but prints smaller.

## Safety

Numbers come from queries run with the reader's own access rights. Filters are
literal lists only (no code), fields must exist, sort is one field, links must
start with https://, http://, mailto: or /. A box whose data cannot be read
shows its problem instead of breaking the report. Reports are private to their
owner unless **Shared** with the company.
