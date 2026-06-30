// gmnspy.reports map-report viewer — runs after page load, builds Leaflet
// map from window.__GMNSPY_DATA__ injected by the Jinja template, and wires
// the marker → table-row "Show row" bridge.
(function () {
  "use strict";

  const data = window.__GMNSPY_DATA__ || {};
  const tileProvider = data.tile_provider || "openstreetmap";
  const markers = Array.isArray(data.markers) ? data.markers : [];
  const links = Array.isArray(data.links) ? data.links : [];
  const bbox = Array.isArray(data.bbox) ? data.bbox : null;

  const mapEl = document.getElementById("gv-map");
  if (!mapEl || typeof L === "undefined") {
    return;
  }

  const map = L.map(mapEl, { zoomControl: true, attributionControl: true });

  const TILE_CONFIG = {
    openstreetmap: {
      url: "https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png",
      attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
      maxZoom: 19,
    },
    "carto-positron": {
      url: "https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png",
      attribution:
        '&copy; <a href="https://www.openstreetmap.org/copyright">OSM</a> &copy; <a href="https://carto.com/attributions">CARTO</a>',
      maxZoom: 19,
    },
  };
  const tileConfig = TILE_CONFIG[tileProvider] || TILE_CONFIG.openstreetmap;
  L.tileLayer(tileConfig.url, { attribution: tileConfig.attribution, maxZoom: tileConfig.maxZoom }).addTo(map);

  // Render the network so it's visible even when no findings are present.
  // Dark slate over the muted carto basemap so the network reads as the
  // primary subject; the basemap is context, not the headline.
  if (links.length) {
    const linkLayer = L.layerGroup();
    links.forEach((coords) => {
      if (!coords || coords.length < 2) return;
      // coords: [[lon,lat], ...] — Leaflet wants [lat, lon].
      const latlngs = coords.map((c) => [c[1], c[0]]);
      L.polyline(latlngs, { color: "#2c3e50", weight: 2.5, opacity: 0.85 }).addTo(linkLayer);
    });
    linkLayer.addTo(map);
  }

  const SEVERITY_COLOR = { error: "#d1242f", warning: "#9a6700", info: "#0969da" };

  const issueGroup = L.layerGroup();
  markers.forEach((m) => {
    if (typeof m.lon !== "number" || typeof m.lat !== "number") return;
    const marker = L.circleMarker([m.lat, m.lon], {
      radius: 7,
      color: SEVERITY_COLOR[m.severity] || "#666",
      fillColor: SEVERITY_COLOR[m.severity] || "#666",
      fillOpacity: 0.7,
      weight: 2,
    });
    marker.bindPopup(buildPopup(m), { maxWidth: 320 });
    marker.on("popupopen", () => {
      const link = document.querySelector(`[data-popup-show-row="${cssEscape(m.issue_id)}"]`);
      if (link) {
        link.addEventListener("click", (ev) => {
          ev.preventDefault();
          showRow(m.issue_id);
        });
      }
    });
    marker.addTo(issueGroup);
  });
  issueGroup.addTo(map);

  // Fit the map: prefer bbox passed in, then marker extent, then links extent.
  let fitted = false;
  if (bbox && bbox.length === 4) {
    map.fitBounds([
      [bbox[1], bbox[0]],
      [bbox[3], bbox[2]],
    ]);
    fitted = true;
  }
  if (!fitted && markers.length) {
    const latlngs = markers.filter((m) => typeof m.lon === "number").map((m) => [m.lat, m.lon]);
    if (latlngs.length) {
      map.fitBounds(latlngs, { padding: [40, 40] });
      fitted = true;
    }
  }
  if (!fitted && links.length) {
    const all = [];
    links.forEach((coords) => coords.forEach((c) => all.push([c[1], c[0]])));
    if (all.length) {
      map.fitBounds(all, { padding: [20, 20] });
      fitted = true;
    }
  }
  if (!fitted) {
    map.setView([47.5, -120.5], 9);
  }

  // Leaflet caches the container size at init time. If the page's CSS layout
  // (flex, grid, responsive image, etc.) settled AFTER L.map() ran, the map
  // computes its bounds for the smaller initial size and loads only a partial
  // strip of tiles. requestAnimationFrame waits for the next paint, by which
  // point the container has its final size.
  requestAnimationFrame(() => map.invalidateSize());
  // And once more after a short delay for slow font-loading / image-decode
  // cases that nudge layout a second time.
  setTimeout(() => map.invalidateSize(), 250);

  // Wire the unlocated-findings sidebar click-handlers.
  document.querySelectorAll("[data-unlocated-issue-id]").forEach((el) => {
    el.addEventListener("click", () => {
      const id = el.getAttribute("data-unlocated-issue-id");
      if (id) showRow(id);
    });
  });

  // Wire the simple filter controls.
  const sevFilter = document.getElementById("gv-filter-severity");
  const tableFilter = document.getElementById("gv-filter-table");
  const searchFilter = document.getElementById("gv-filter-search");
  const applyFilters = () => {
    const sev = sevFilter ? sevFilter.value : "";
    const tbl = tableFilter ? tableFilter.value : "";
    const q = searchFilter ? searchFilter.value.toLowerCase().trim() : "";
    document.querySelectorAll("tr[data-issue-id]").forEach((row) => {
      const rowSev = row.getAttribute("data-severity") || "";
      const rowTbl = row.getAttribute("data-table") || "";
      const text = row.textContent.toLowerCase();
      const matches =
        (!sev || rowSev === sev) && (!tbl || rowTbl === tbl) && (!q || text.indexOf(q) !== -1);
      row.style.display = matches ? "" : "none";
    });
  };
  [sevFilter, tableFilter, searchFilter].forEach((el) => el && el.addEventListener("input", applyFilters));

  // ----- helpers -----------------------------------------------------------

  function buildPopup(m) {
    const sev = (m.severity || "info").toLowerCase();
    const sevLabel = sev.toUpperCase();
    const esc = htmlEscape;
    let html =
      '<div class="gv-marker-popup">' +
      '<div class="gv-popup-header gv-sev severity-' +
      esc(sev) +
      '">' +
      esc(sevLabel) +
      ' <span class="gv-popup-code">' +
      esc(m.code || "") +
      "</span></div>" +
      '<div class="gv-popup-message">' +
      esc(m.message || "") +
      "</div>";
    if (m.fix_hint) {
      html += '<div class="gv-popup-fixhint">' + esc(m.fix_hint) + "</div>";
    }
    html += '<div class="gv-popup-actions">';
    if (m.edit_url) {
      html +=
        '<a href="' +
        esc(m.edit_url) +
        '" target="_blank" rel="noopener noreferrer">Edit in OSM &rarr;</a>';
    }
    html +=
      '<button type="button" data-popup-show-row="' +
      esc(m.issue_id || "") +
      '">Show row</button>';
    html += "</div></div>";
    return html;
  }

  function showRow(issueId) {
    const row = document.querySelector('tr[data-issue-id="' + cssEscape(issueId) + '"]');
    if (!row) return;
    document.querySelectorAll("tr.is-highlighted").forEach((r) => r.classList.remove("is-highlighted"));
    row.classList.add("is-highlighted");
    row.scrollIntoView({ behavior: "smooth", block: "center" });
  }

  function htmlEscape(s) {
    return String(s).replace(/[&<>"']/g, (c) => ({
      "&": "&amp;",
      "<": "&lt;",
      ">": "&gt;",
      '"': "&quot;",
      "'": "&#39;",
    }[c]));
  }
  function cssEscape(s) {
    if (window.CSS && CSS.escape) return CSS.escape(String(s));
    return String(s).replace(/(["\\])/g, "\\$1");
  }
})();
