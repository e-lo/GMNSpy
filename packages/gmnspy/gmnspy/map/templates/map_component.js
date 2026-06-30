// gmnspy.map — shared NetworkMap component bootstrap.
//
// Loaded ONCE per host page via NetworkMap.head_assets(). Defines
// window.__gmnspyAttach(uid) which reads window.__GMNSPY_INSTANCES__[uid]
// and attaches a Leaflet map to #gv-map-<uid>. Each per-instance fragment
// pushes its uid into __GMNSPY_QUEUE__ and calls __gmnspyAttach when
// available; this file drains the queue on load, so attach happens
// regardless of fragment-vs-shared-asset ordering on the page.
//
// Safe to load multiple times (re-defines the same function, idempotent).
(function () {
  "use strict";

  if (typeof window.__gmnspyAttach === "function") {
    (window.__GMNSPY_QUEUE__ || []).splice(0).forEach(window.__gmnspyAttach);
    return;
  }

  window.__gmnspyAttach = function (uid) {
    const data = (window.__GMNSPY_INSTANCES__ || {})[uid];
    if (!data) return;
    const mapEl = document.getElementById("gv-map-" + uid);
    if (!mapEl || typeof L === "undefined") return;
    if (mapEl.dataset.gvInit === "1") return;
    mapEl.dataset.gvInit = "1";
    attachOne(mapEl, data);
  };

  (window.__GMNSPY_QUEUE__ || []).splice(0).forEach(window.__gmnspyAttach);

  function attachOne(mapEl, data) {
    const tileProvider = data.tile_provider || "carto-positron";
    const markers = Array.isArray(data.markers) ? data.markers : [];
    const layersData = Array.isArray(data.layers) ? data.layers : [];
    const networkBbox = Array.isArray(data.bbox) ? data.bbox : null;

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
    const SEVERITY_COLOR = { error: "#d1242f", warning: "#9a6700", info: "#0969da" };

    const targetBounds = computeTargetBounds();
    const map = L.map(mapEl, { zoomControl: true, attributionControl: true });
    if (targetBounds) {
      map.fitBounds(targetBounds, { padding: [40, 40], animate: false });
    } else {
      map.setView([47.5, -120.5], 9);
    }
    L.tileLayer(tileConfig.url, { attribution: tileConfig.attribution, maxZoom: tileConfig.maxZoom }).addTo(map);

    // ----- Toggleable layers (links, nodes, ...) ---------------------------
    const layerByName = {};
    layersData.forEach((spec) => {
      const group = L.layerGroup();
      const style = spec.style || {};
      const items = Array.isArray(spec.items) ? spec.items : [];
      items.forEach((item) => {
        let leafletLayer = null;
        if (spec.type === "polyline" && Array.isArray(item.coords) && item.coords.length >= 2) {
          const latlngs = item.coords.map((c) => [c[1], c[0]]);
          leafletLayer = L.polyline(latlngs, {
            color: style.color || "#1f77b4",
            weight: style.weight || 3,
            opacity: style.opacity || 0.9,
          });
        } else if (spec.type === "point" && Array.isArray(item.coord) && item.coord.length >= 2) {
          leafletLayer = L.circleMarker([item.coord[1], item.coord[0]], {
            radius: style.radius || 3,
            color: style.color || "#1f77b4",
            fillColor: style.color || "#1f77b4",
            fillOpacity: style.fillOpacity || 0.85,
            weight: 1,
          });
        }
        if (!leafletLayer) return;
        if (item.props && Object.keys(item.props).length) {
          leafletLayer.bindTooltip(formatProps(item.props), {
            sticky: true,
            direction: "top",
            opacity: 0.95,
          });
        }
        leafletLayer.addTo(group);
      });
      layerByName[spec.id] = { group, spec };
      if (spec.default_on) group.addTo(map);
    });

    // ----- Issue markers ---------------------------------------------------
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
        const btn = document.querySelector(`[data-popup-show-row="${cssEscape(m.issue_id)}"]`);
        if (btn) {
          btn.addEventListener("click", (ev) => {
            ev.preventDefault();
            // No-op when there's no findings table on the host page.
            const row = document.querySelector('tr[data-issue-id="' + cssEscape(m.issue_id) + '"]');
            if (!row) return;
            document.querySelectorAll("tr.is-highlighted").forEach((r) => r.classList.remove("is-highlighted"));
            row.classList.add("is-highlighted");
            row.scrollIntoView({ behavior: "smooth", block: "center" });
          });
        }
      });
      marker.addTo(markerLayer);
    });
    markerLayer.addTo(map);

    // ----- Layer toggle widget --------------------------------------------
    buildLayerToggle();

    // ----- Resize handling -------------------------------------------------
    let allowRefit = true;
    function refresh() {
      map.invalidateSize();
      if (allowRefit && targetBounds) {
        map.fitBounds(targetBounds, { padding: [40, 40], animate: false });
      }
    }
    requestAnimationFrame(refresh);
    if (typeof ResizeObserver !== "undefined") new ResizeObserver(refresh).observe(mapEl);
    window.addEventListener("resize", refresh);
    window.addEventListener("load", () => {
      refresh();
      setTimeout(() => {
        allowRefit = false;
      }, 200);
    });

    // ----- helpers (closure-scoped per instance) ---------------------------

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
      if (networkBbox && networkBbox.length === 4) {
        return L.latLngBounds([
          [networkBbox[1], networkBbox[0]],
          [networkBbox[3], networkBbox[2]],
        ]);
      }
      const all = [];
      layersData.forEach((spec) => {
        const items = Array.isArray(spec.items) ? spec.items : [];
        items.forEach((item) => {
          if (Array.isArray(item.coords)) {
            item.coords.forEach((c) => all.push([c[1], c[0]]));
          } else if (Array.isArray(item.coord)) {
            all.push([item.coord[1], item.coord[0]]);
          }
        });
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
          '<a href="' + esc(m.edit_url) + '" target="_blank" rel="noopener noreferrer">Edit in OSM &rarr;</a>';
      }
      html += '<button type="button" data-popup-show-row="' + esc(m.issue_id || "") + '">Show row</button>';
      html += "</div></div>";
      return html;
    }

    function formatProps(props) {
      const esc = htmlEscape;
      return Object.entries(props)
        .map(([k, v]) => `<b>${esc(k)}:</b> ${esc(String(v))}`)
        .join("<br>");
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
  }
})();
