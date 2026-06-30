// gmnspy.reports map-report viewer — runs after page load, builds Leaflet
// map from window.__GMNSPY_DATA__ injected by the Jinja template, and wires
// the marker → table-row "Show row" bridge.
(function () {
  "use strict";

  const data = window.__GMNSPY_DATA__ || {};
  const tileProvider = data.tile_provider || "carto-positron";
  const markers = Array.isArray(data.markers) ? data.markers : [];
  const links = Array.isArray(data.links) ? data.links : [];
  const networkBbox = Array.isArray(data.bbox) ? data.bbox : null;

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
  const tileConfig = TILE_CONFIG[tileProvider] || TILE_CONFIG["carto-positron"];
  L.tileLayer(tileConfig.url, { attribution: tileConfig.attribution, maxZoom: tileConfig.maxZoom }).addTo(map);

  // ----- Network underlay --------------------------------------------------
  // Saturated blue + chunky weight stands out on either the muted CARTO
  // basemap or the colourful OSM one. Wrapped in a layerGroup so the
  // toggle control below can hide/show it without touching the markers.
  const networkLayer = L.layerGroup();
  links.forEach((coords) => {
    if (!coords || coords.length < 2) return;
    // coords: [[lon,lat], ...] — Leaflet wants [lat, lon].
    const latlngs = coords.map((c) => [c[1], c[0]]);
    L.polyline(latlngs, { color: "#1f77b4", weight: 3, opacity: 0.9 }).addTo(networkLayer);
  });
  networkLayer.addTo(map);

  // ----- Issue markers -----------------------------------------------------
  const SEVERITY_COLOR = { error: "#d1242f", warning: "#9a6700", info: "#0969da" };
  const markerLayer = L.layerGroup();
  markers.forEach((m) => {
    if (typeof m.lon !== "number" || typeof m.lat !== "number") return;
    const marker = L.circleMarker([m.lat, m.lon], {
      radius: 7,
      color: SEVERITY_COLOR[m.severity] || "#666",
      fillColor: SEVERITY_COLOR[m.severity] || "#666",
      fillOpacity: 0.75,
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
    marker.addTo(markerLayer);
  });
  markerLayer.addTo(map);

  // ----- Layer toggle (custom — Leaflet's built-in L.Control.Layers
  //       uses a sprite icon we stripped from the inlined CSS to silence
  //       file:// CSP warnings, so we render our own checkboxes).
  if (links.length || markers.length) {
    const ctl = L.control({ position: "topright" });
    ctl.onAdd = function () {
      const div = L.DomUtil.create("div", "gv-layers-control leaflet-bar");
      const parts = [];
      if (links.length) {
        parts.push(
          `<label><input type="checkbox" data-gv-layer="network" checked> Network (${links.length})</label>`
        );
      }
      if (markers.length) {
        parts.push(
          `<label><input type="checkbox" data-gv-layer="markers" checked> Findings (${markers.length})</label>`
        );
      }
      div.innerHTML = parts.join("");
      L.DomEvent.disableClickPropagation(div);
      L.DomEvent.disableScrollPropagation(div);
      div.querySelectorAll("input[data-gv-layer]").forEach((cb) => {
        cb.addEventListener("change", (ev) => {
          const which = ev.target.getAttribute("data-gv-layer");
          const layer = which === "network" ? networkLayer : markerLayer;
          if (ev.target.checked) map.addLayer(layer);
          else map.removeLayer(layer);
        });
      });
      return div;
    };
    ctl.addTo(map);
  }

  // ----- Target bounds — fit to findings when present, else network -------
  // Findings get priority because that's what the reader came to look at;
  // the network is context. Generous padding keeps adjacent network visible.
  const targetBounds = computeTargetBounds();

  function computeTargetBounds() {
    if (markers.length) {
      const latlngs = markers
        .filter((m) => typeof m.lon === "number" && typeof m.lat === "number")
        .map((m) => [m.lat, m.lon]);
      if (latlngs.length) {
        const b = L.latLngBounds(latlngs);
        // Pad single-marker case by ~150m so we don't zoom to street level.
        if (latlngs.length === 1) return b.pad(0.5);
        return b.pad(0.2);
      }
    }
    if (links.length) {
      const all = [];
      links.forEach((coords) => coords.forEach((c) => all.push([c[1], c[0]])));
      if (all.length) return L.latLngBounds(all);
    }
    if (networkBbox && networkBbox.length === 4) {
      return L.latLngBounds([
        [networkBbox[1], networkBbox[0]],
        [networkBbox[3], networkBbox[2]],
      ]);
    }
    return null;
  }

  // First proper fit happens after the container has settled. fitBounds
  // BEFORE invalidateSize would compute a zoom for the pre-layout viewport
  // and leave gaps when the container grows. Doing it inside the
  // ResizeObserver callback below catches every cause (initial CSS settle,
  // dev-tools open/close, window resize, fullscreen) and the fitBounds is
  // always for the *current* viewport.
  let hasFitOnce = false;
  function fitOrPan(animate) {
    if (!targetBounds) {
      if (!hasFitOnce) map.setView([47.5, -120.5], 9);
      hasFitOnce = true;
      return;
    }
    if (!hasFitOnce) {
      map.fitBounds(targetBounds, { padding: [30, 30], animate: !!animate });
      hasFitOnce = true;
    }
  }

  // Initial paint: invalidate + fit on the next frame so layout is done.
  requestAnimationFrame(() => {
    map.invalidateSize();
    fitOrPan(false);
  });
  // Belt-and-braces for slow font-load / image-decode cases that nudge layout.
  setTimeout(() => {
    map.invalidateSize();
    fitOrPan(false);
  }, 250);

  // ResizeObserver covers everything: CSS animations, dev-tools, fullscreen,
  // browser-window resize, container parent resizing for any reason. Cheap —
  // invalidateSize is a no-op when size is unchanged.
  if (typeof ResizeObserver !== "undefined") {
    const ro = new ResizeObserver(() => {
      map.invalidateSize();
    });
    ro.observe(mapEl);
  }
  // Also rebind on window resize for the (rare) browser without ResizeObserver.
  window.addEventListener("resize", () => map.invalidateSize());

  // ----- Sidebar + filter wiring ------------------------------------------

  document.querySelectorAll("[data-unlocated-issue-id]").forEach((el) => {
    el.addEventListener("click", () => {
      const id = el.getAttribute("data-unlocated-issue-id");
      if (id) showRow(id);
    });
  });

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
