# Data activity icon proposal

The original proposal was returned for a change to the Render activities and remains design history.

Seven transparent SVGs cover Parse XML, Render XML, Parse JSON, Render JSON, Parse Data, Render Data, and Read Excel Workbook. XML uses amber tags, JSON uses violet braces, flat data uses a teal table, and Excel uses a green workbook grid. Parse points from the file toward a structured-data tree; Render points from the tree toward the file.

review.html and review.png show all seven designs on dark and light backgrounds and at activity sizes.

The user approved revision-2/ and requested that it be applied. All seven SVGs are now in frontend/public/activity-icons/ and connected through frontend/src/main.tsx for the palette and canvas. Render XML, Render JSON, and Render Data place structured data first on the left and the output file next on the right, with a rightward arrow. Parse and Excel designs are unchanged from the proposal. revision-2/review.html and revision-2/review.png preview the complete set.
