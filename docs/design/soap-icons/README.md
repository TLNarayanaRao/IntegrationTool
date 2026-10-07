# SOAP activity icon proposal

The original XML/hexagon pair was rejected. It remains unused design history.

SOAP Service uses a violet XML service endpoint with an amber incoming request and a green outgoing response. SOAP Request Reply uses an XML document with the SOAP label, a service peer, an amber outgoing request, and a green incoming response. No email/envelope imagery is used.

review.html and review.png compare both designs at 24, 40, and 48 px on dark and light backgrounds.

The user approved service-globe/ and requested that it be applied. Its two SVGs are now in frontend/public/activity-icons/ and connected through frontend/src/main.tsx for the palette and canvas. They use the App Service globe SVG supplied by the user as their base, with an amber request arrow, a green response arrow, and a SOAP label. Service accepts the request and sends the response; Request Reply sends the request and receives the response. See service-globe/review.html and service-globe/review.png. service-globe/SOURCE.md records the reference URL and adaptation.
