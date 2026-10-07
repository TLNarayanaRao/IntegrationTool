# EMS activity icon proposal

The original set was rejected; it remains design history. Production icons and activity references have not changed.

Six transparent SVG designs use blue queue structures, purple topic fan-out, and data records. Cyan arrows identify receiving/subscribing; green arrows identify sending/publishing. Request Reply uses opposite cyan and amber arrows. Reply uses a single green return arrow. No envelopes or email imagery are used.

review.html and review.png compare all six operations at 24, 40, and 48 px on a dark background and at 48 px on a light background.

Revision 2 in revision-2/ was rejected. It used a horizontal queue symbol with three queued records between brackets. It remains design history.

Both directions in concepts/ were rejected. A used stacked queue trays with depth; B used a queue container holding visible data records. They remain design history.

The user supplied a reference image: a gold rectangular queue with three vertical dark slots, right-pointing triangles at both sides, and a lighter base strip. The SVGs in reference/ followed that silhouette and palette. The user requested further refinement, different colors, and horizontal operation arrows.

reference-refined/ was sent back for more improvement and a color other than blue. It remains design history.

copper/ was superseded by the user's request for violet. It remains design history.

violet/ was superseded by the user's new horizontal cylinder reference. It remains design history.

cylinder/ was superseded by a more detailed user reference: a rounded queue body with vertical slots, a single elliptical end, and an arrow passing through that end. It remains design history.

The user approved filled-cylinder/ and requested that it be applied. Its six SVGs now appear in frontend/public/activity-icons/ and are connected through frontend/src/main.tsx for the palette and canvas. They follow the latest reference with consistent violet fills and dark plum slots. Arrows are integrated through the queue end: Receiver, Subscriber, and Reply point outward; Sender and Publisher point inward; Request Reply uses both directions. A small fan-out marker distinguishes topic operations. See filled-cylinder/review.html and filled-cylinder/review.png. Earlier proposals remain unused design history.
