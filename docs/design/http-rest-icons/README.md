# HTTP and REST icon proposal

The user approved the three HTTP icons and REST concept A. These five SVG icons are now connected to the activity palette and canvas through frontend/src/main.tsx. Production assets are in frontend/public/activity-icons/.

Five transparent SVGs share a consistent visual style. HTTP uses a globe; REST uses a globe with a cloud overlapping its lower edge. Incoming arrows identify receivers, outward arrows identify outgoing calls, and the return arrow/check identifies HTTP responses.

Open review.html for dark/light previews at activity sizes. review.png is the rendered review board.

The original REST gateway proposals in this directory and rest-review.html/png are retained as design history. REST now uses a cloud covering part of the globe from below: Receiver has a green arrow pointing inward toward the globe, and Invoke has an amber arrow pointing outward from it. The current SVGs are frontend/public/activity-icons/rest-receiver.svg and rest-invoke.svg; the older concept A files remain as design history.

## REST alternatives

Three pairs are in concepts/: A (approved REST service badge), B (resource document with URI path), and C (web endpoint with REST badge). Compare concepts/review.html or concepts/review.png. B and C remain unused alternatives.
