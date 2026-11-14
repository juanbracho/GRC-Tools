// Interactive layer for site/index.html: search + "my stack".
// Inlined into the page and allowed by its SHA-256 hash in the CSP.
// Safety rule: data is only ever inserted with textContent (never parsed as HTML).
(() => {
  "use strict";
  const node = document.getElementById("sw-data");
  if (!node) return;
  const D = JSON.parse(node.textContent);
  const $ = (id) => document.getElementById(id);
  const el = (tag, cls, text) => {
    const e = document.createElement(tag);
    if (cls) e.className = cls;
    if (text != null) e.textContent = text;
    return e;
  };

  const incidentBySub = {};
  D.incidents.forEach((i) => { incidentBySub[i.id] = i; });
  const usedBy = {};
  D.vendors.forEach((v) => v.subs.forEach((s) => {
    const u = usedBy[s.id] || (usedBy[s.id] = { name: s.name, vendors: [] });
    if (!u.vendors.includes(v.name)) u.vendors.push(v.name);
    if (s.name.length < u.name.length) u.name = s.name;
  }));
  const vendorName = {};
  D.vendors.forEach((v) => { vendorName[v.id] = v.name; });

  // ---- my stack (remembered in this browser only) ----
  const KEY = "sw-stack-v1";
  let stack = new Set();
  try { stack = new Set(JSON.parse(localStorage.getItem(KEY) || "[]")); } catch (e) { /* private mode */ }
  const save = () => { try { localStorage.setItem(KEY, JSON.stringify([...stack])); } catch (e) { /* ignore */ } };

  const chips = $("sw-stack");
  D.vendors.forEach((v) => {
    const label = el("label", "chip");
    const cb = el("input");
    cb.type = "checkbox";
    cb.checked = stack.has(v.id);
    cb.addEventListener("change", () => {
      if (cb.checked) stack.add(v.id); else stack.delete(v.id);
      save();
      renderStack();
    });
    label.append(cb, document.createTextNode(" " + v.name));
    chips.append(label);
  });

  function line(cls, parts) {
    const d = el("div", cls);
    parts.forEach(([c, t]) => d.append(el("span", c, t)));
    return d;
  }

  function renderStack() {
    const out = $("sw-stack-out");
    out.replaceChildren();
    const mine = D.vendors.filter((v) => stack.has(v.id));
    if (!mine.length) {
      out.append(el("div", "dim", "Tick the apps your company uses to see your own fourth-party exposure."));
      return;
    }
    const counts = {};
    mine.forEach((v) => v.subs.forEach((s) => {
      const c = counts[s.id] || (counts[s.id] = { name: usedBy[s.id].name, vendors: [] });
      if (!c.vendors.includes(v.name)) c.vendors.push(v.name);
    }));
    const ids = Object.keys(counts);
    out.append(line(null, [[null, `${mine.length} app(s) → `], ["mod", `${ids.length} fourth parties`],
                           ["dim", " get your data through them"]]));

    const hits = D.incidents.filter((i) => counts[i.id] || i.confirmed.some((c) => stack.has(c)));
    if (!hits.length) out.append(el("div", "ok", "✓ none of them is on the incident watchlist"));
    hits.forEach((i) => {
      const via = counts[i.id] ? counts[i.id].vendors.join(", ") : "not listed";
      out.append(line("date", [["del", `⚠ ${i.name}`], ["dim", ` ${i.date} · listed by: ${via}`]]));
      i.confirmed.filter((c) => stack.has(c) && !(counts[i.id] || { vendors: [] }).vendors.includes(vendorName[c]))
        .forEach((c) => out.append(el("div", "del", `! ${vendorName[c]} confirmed impact but doesn't list ${i.name}`)));
    });

    const shared = ids.filter((id) => counts[id].vendors.length > 1)
      .sort((a, b) => counts[b].vendors.length - counts[a].vendors.length).slice(0, 8);
    if (shared.length) {
      out.append(el("div", "date", "most shared inside your stack"));
      shared.forEach((id) => out.append(line(null, [[null, counts[id].name + "  "],
        ["bar", "█".repeat(counts[id].vendors.length)], ["dim", ` ${counts[id].vendors.join(", ")}`]])));
    }
  }

  // ---- search ----
  const q = $("sw-q");
  const res = $("sw-results");
  q.addEventListener("input", () => {
    const term = q.value.trim().toLowerCase();
    res.replaceChildren();
    if (term.length < 2) return;
    let found = 0;
    D.vendors.filter((v) => v.name.toLowerCase().includes(term)).forEach((v) => {
      found++;
      res.append(line("date", [[null, `vendor: ${v.name}`], ["dim", ` · ${v.subs.length} subprocessors · `]]));
      D.incidents.filter((i) => i.confirmed.includes(v.id) && !v.subs.some((s) => s.id === i.id)).forEach((i) =>
        res.append(el("div", "del", `! confirmed impact from the ${i.name} incident (${i.date}) but doesn't list ${i.name}`)));
      v.subs.forEach((s) => {
        const inc = incidentBySub[s.id];
        res.append(line(null, [[inc ? "del" : null, (inc ? "⚠ " : "  ") + s.name],
                               ["dim", s.purpose ? ` · ${s.purpose}` : ""]]));
      });
    });
    Object.entries(usedBy)
      .filter(([id, u]) => u.name.toLowerCase().includes(term) || id.includes(term.replace(/\s+/g, "-")))
      .sort((a, b) => b[1].vendors.length - a[1].vendors.length).slice(0, 15)
      .forEach(([id, u]) => {
        found++;
        res.append(line("date", [[null, `fourth party: ${u.name}`], ["dim", ` · behind ${u.vendors.length} vendor(s)`]]));
        res.append(el("div", "dim", `used by: ${u.vendors.join(", ")}`));
        const inc = incidentBySub[id];
        if (inc) res.append(el("div", "del", `⚠ incident ${inc.date}: ${inc.summary}`));
      });
    D.incidents.filter((i) => !usedBy[i.id] && i.name.toLowerCase().includes(term)).forEach((i) => {
      found++;
      res.append(line("date", [[null, `incident: ${i.name}`], ["dim", ` · ${i.date} · not on any watched vendor's list`]]));
      i.confirmed.forEach((c) => res.append(el("div", "del", `! ${vendorName[c]} confirmed impact but doesn't list it`)));
    });
    if (!found) {
      res.append(el("div", "dim", `No match among the ${D.vendors.length} vendors we watch. ` +
        "Vendors are added by hand so every list is checked against the live page."));
    }
  });

  $("sw-interactive").hidden = false;
  renderStack();
})();
