/* Tiny DOM helpers shared by app.js and chart.js.
   Every piece of text goes in through textContent / text nodes, never innerHTML,
   because strategy names, reasons and symbols will one day come from the server. */
(function () {
  "use strict";

  const SVG_NS = "http://www.w3.org/2000/svg";

  function build(el, attrs, kids) {
    if (attrs) {
      for (const [key, value] of Object.entries(attrs)) {
        if (value === null || value === undefined || value === false) continue;
        if (key.startsWith("on") && typeof value === "function") el.addEventListener(key.slice(2), value);
        else el.setAttribute(key, value === true ? "" : String(value));
      }
    }
    for (const kid of kids.flat(Infinity)) {
      if (kid === null || kid === undefined || kid === false) continue;
      el.append(kid.nodeType ? kid : document.createTextNode(String(kid)));
    }
    return el;
  }

  function h(tag, attrs, ...kids) {
    return build(document.createElement(tag), attrs, kids);
  }

  function s(tag, attrs, ...kids) {
    return build(document.createElementNS(SVG_NS, tag), attrs, kids);
  }

  const ICONS = {
    dot: () => [s("circle", { cx: 8, cy: 8, r: 4.5, fill: "currentColor" })],
    ring: () => [s("circle", { cx: 8, cy: 8, r: 4.5, fill: "none", stroke: "currentColor", "stroke-width": 1.75 })],
    pause: () => [s("rect", { x: 3.5, y: 3, width: 3, height: 10, rx: 0.8, fill: "currentColor" }),
                  s("rect", { x: 9.5, y: 3, width: 3, height: 10, rx: 0.8, fill: "currentColor" })],
    up: () => [s("path", { d: "M8 3 L13.5 12.5 H2.5 Z", fill: "currentColor" })],
    down: () => [s("path", { d: "M8 13 L13.5 3.5 H2.5 Z", fill: "currentColor" })],
    check: () => [s("circle", { cx: 8, cy: 8, r: 7, fill: "currentColor" }),
                  s("path", { d: "M4.6 8.2 L7 10.5 L11.4 5.8", fill: "none", stroke: "#fff", "stroke-width": 1.8, "stroke-linecap": "round", "stroke-linejoin": "round" })],
    alert: () => [s("path", { d: "M8 1.8 L15 14 H1 Z", fill: "currentColor", "stroke-linejoin": "round" }),
                  s("path", { d: "M8 6.2 V9.6 M8 11.5 V11.6", stroke: "#0b0b0b", "stroke-width": 1.7, "stroke-linecap": "round" })],
    cross: () => [s("circle", { cx: 8, cy: 8, r: 7, fill: "currentColor" }),
                  s("path", { d: "M5.4 5.4 L10.6 10.6 M10.6 5.4 L5.4 10.6", stroke: "#fff", "stroke-width": 1.8, "stroke-linecap": "round" })],
    lock: () => [s("rect", { x: 3, y: 7, width: 10, height: 7, rx: 1.6, fill: "currentColor" }),
                 s("path", { d: "M5.2 7 V5.2 a2.8 2.8 0 0 1 5.6 0 V7", fill: "none", stroke: "currentColor", "stroke-width": 1.6, "stroke-linecap": "round" })],
    clock: () => [s("circle", { cx: 8, cy: 8, r: 6.2, fill: "none", stroke: "currentColor", "stroke-width": 1.6 }),
                  s("path", { d: "M8 4.6 V8.2 L10.4 9.6", fill: "none", stroke: "currentColor", "stroke-width": 1.6, "stroke-linecap": "round" })],
  };

  function icon(name) {
    return s("svg", { class: "icon", viewBox: "0 0 16 16", "aria-hidden": "true", focusable: "false" }, ICONS[name]());
  }

  window.DOM = { h, s, icon };
})();
