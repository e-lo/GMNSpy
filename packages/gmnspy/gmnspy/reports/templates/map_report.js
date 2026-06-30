// gmnspy.reports map-report viewer — runs after page load, builds Leaflet
// map from window.__GMNSPY_DATA__ injected by the Jinja template, and wires
// the marker → table-row "Show row" bridge.
(function () {
  "use strict";

  const data = window.__GMNSPY_DATA__ || {};
  const tileProvider = data.tile_provider || "carto-positron";
  const markers = Array.isArray(data.markers) ? data.markers : [];
  const layersData = Array.isArray(data.layers) ? data.layers : [];
  const networkBbox = Array.isArray(data.bbox) ? data.bbox : null;

  const mapEl = document.getElementById("gv-map");
  if (!mapEl || typeof L === "undefined") {
    return;
  }

  const SEVERITY_COLOR = { error: "#d1242f", warning: "#9a6700", info: "#0969da" };

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

  // ----- Compute initial bounds BEFORE map creation -----------------------
  // Leaflet needs a viewport before it can request tiles or render layers.
  // Setting an explicit view at L.map() time avoids the "no view, no render"
  // trap where polylines exist in the layer but nothing draws because the
  // map never has a viewport for the first frame.
  const targetBounds = computeTargetBounds();

  const map = L.map(mapEl, { zoomControl: true, attributionControl: true });
  if (targetBounds) {
    map.fitBounds(targetBounds, { padding: [40, 40], animate: false });
  } else {
    map.setView([47.5, -120.5], 9);
  }

  L.tileLayer(tileConfig.url, { attribution: tileConfig.attribution, maxZoom: tileConfig.maxZoom }).addTo(map);

  // ----- Build overlays from the `layers` array ---------------------------
  // Each layer becomes one L.LayerGroup; the toggle widget adds/removes it
  // from the map. New layer types ("arrow" for movements, "polygon" for
  // zones, …) only need a new switch arm here + matching style fields.
  const layerByName = {};
  layersData.forEach((spec) => {
    const group = L.layerGroup();
    const style = spec.style || {};
    if (spec.type === "polyline" && Array.isArray(spec.polylines)) {
      spec.polylines.forEach((coords) => {
        if (!coords || coords.length < 2) return;
        const latlngs = coords.map((c) => [c[1], c[0]]);
        L.polyline(latlngs, {
          color: style.color || "#1f77b4",
          weight: style.weight || 3,
          opacity: style.opacity || 0.9,
        }).addTo(group);
      });
    } else if (spec.type === "point" && Array.isArray(spec.points)) {
      spec.points.forEach((p) => {
        if (!Array.isArray(p) || p.length < 2) return;
        L.circleMarker([p[1], p[0]], {
          radius: style.radius || 3,
          color: style.color || "#1f77b4",
          fillColor: style.color || "#1f77b4",
          fillOpacity: style.fillOpacity || 0.85,
          weight: 1,
        }).addTo(group);
      });
    }
    layerByName[spec.id] = { group, spec };
    if (spec.default_on) group.addTo(map);
  });

  // ----- Issue markers (always own layer; toggled separately) -------------
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

  // ----- Layer toggle widget (top-right) ----------------------------------
  buildLayerToggle();

  // ----- Resize handling --------------------------------------------------
  // ResizeObserver catches every container size change. We only auto-refit
  // until the page is fully loaded (fonts + images may nudge layout). After
  // that, just invalidateSize — preserve the user's pan/zoom.
  let allowRefit = true;
  function refresh() {
    map.invalidateSize();
    if (allowRefit && targetBounds) {
      map.fitBounds(targetBounds, { padding: [40, 40], animate: false });
    }
  }
  requestAnimationFrame(refresh);
  if (typeof ResizeObserver !== "undefined") {
    new ResizeObserver(refresh).observe(mapEl);
  }
  window.addEventListener("resize", refresh);
  window.addEventListener("load", () => {
    refresh();
    // Lock in the view: subsequent resizes only invalidateSize, no refit.
    setTimeout(() => {
      allowRefit = false;
    }, 200);
  });

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

  function computeTargetBounds() {
    if (markers.length) {
      const latlngs = markers
        .filter((m) => typeof m.lon === "number" && typeof m.lat === "number")
        .map((m) => [m.lat, m.lon]);
      if (latlngs.length) {
        const b = L.latLngBounds(latlngs);
        if (latlngs.length === 1) return b.pad(0.5);
        return b.pad(0.2);
      }
    }
    // Fall back to network bbox so a no-findings report still frames the
    // network nicely.
    if (networkBbox && networkBbox.length === 4) {
      return L.latLngBounds([
        [networkBbox[1], networkBbox[0]],
        [networkBbox[3], networkBbox[2]],
      ]);
    }
    // Last resort: union of layer geometries.
    const all = [];
    layersData.forEach((spec) => {
      if (spec.type === "polyline" && Array.isArray(spec.polylines)) {
        spec.polylines.forEach((coords) => coords.forEach((c) => all.push([c[1], c[0]])));
      } else if (spec.type === "point" && Array.isArray(spec.points)) {
        spec.points.forEach((p) => all.push([p[1], p[0]]));
      }
    });
    return all.length ? L.latLngBounds(all) : null;
  }

  function buildLayerToggle() {
    const entries = [];
    layersData.forEach((spec) => {
      entries.push({
        id: spec.id,
        label: `${spec.label} (${spec.count})`,
        on: !!spec.default_on,
        toggle: (checked) => {
          const layer = layerByName[spec.id].group;
          if (checked) map.addLayer(layer);
          else map.removeLayer(layer);
        },
      });
    });
    if (markers.length) {
      entries.push({
        id: "_markers",
        label: `Findings (${markers.length})`,
        on: true,
        toggle: (checked) => {
          if (checked) map.addLayer(markerLayer);
          else map.removeLayer(markerLayer);
        },
      });
    }
    if (!entries.length) return;

    const ctl = L.control({ position: "topright" });
    ctl.onAdd = function () {
      const div = L.DomUtil.create("div", "gv-layers-control leaflet-bar");
      div.innerHTML = entries
        .map(
          (e) =>
            `<label><input type="checkbox" data-gv-layer="${e.id}"${e.on ? " checked" : ""}> ${e.label}</label>`
        )
        .join("");
      L.DomEvent.disableClickPropagation(div);
      L.DomEvent.disableScrollPropagation(div);
      div.querySelectorAll("input[data-gv-layer]").forEach((cb) => {
        cb.addEventListener("change", (ev) => {
          const id = ev.target.getAttribute("data-gv-layer");
          const entry = entries.find((e) => e.id === id);
          if (entry) entry.toggle(ev.target.checked);
        });
      });
      return div;
    };
    ctl.addTo(map);
  }

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
