# Local map dependencies

Offline Folium maps embed these local assets; no CDN or network tiles are required.

- Leaflet 1.9.4: `https://unpkg.com/leaflet@1.9.4/dist/leaflet.js` and `leaflet.css`; BSD-2-Clause, see `LEAFLET_LICENSE.txt`.
- Leaflet CSS image URLs have been replaced with embedded PNG data URIs from the same distribution.
- jQuery 3.7.1: `https://code.jquery.com/jquery-3.7.1.min.js`; MIT, see `JQUERY_LICENSE.txt`.

The original source/license notices remain. Online mode optionally uses OpenStreetMap tiles with attribution; offline mode draws only local geometry and markers.
