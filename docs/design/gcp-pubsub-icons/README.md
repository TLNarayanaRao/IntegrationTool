# GCP Pub/Sub icon proposal

The original pair was sent back for refinement and remains unused design history.

The blue hexagonal topic and connected nodes identify Pub/Sub. Subscriber uses a cyan outgoing topic arrow; Publisher uses a green arrow pointing into the topic. The envelope identifies the message. review.html and review.png show dark/light previews and 24, 40, and 48 px activity sizes.

Revision 2 in revision-2/ was sent back because the user does not want email or envelope imagery. It uses a larger centered topic symbol, an inbox, and an envelope. It remains design history and has not been applied.

Revision 3 in revision-3/ replaced email/envelope/inbox imagery with abstract data records. The user requested that Subscriber use the same green data box as Publisher instead of three boxes.

The user approved revision 4 in revision-4/. Both icons use the identical green data box. Subscriber retains its cyan downward arrow; Publisher retains its green upward arrow. The approved SVGs are now in frontend/public/activity-icons/ and connected through frontend/src/main.tsx for the activity palette and canvas. See revision-4/review.html and revision-4/review.png for dark/light previews at 24, 40, and 48 px. Earlier revisions remain design history.
