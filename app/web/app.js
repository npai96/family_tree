const missingRuntimeDependencies = [
  ["React", typeof globalThis.React !== "undefined"],
  ["ReactDOM", typeof globalThis.ReactDOM !== "undefined"],
  ["D3", typeof globalThis.d3 !== "undefined"],
  ["graph utilities", typeof globalThis.FamilyTreeGraphUtils !== "undefined"],
  ["error utilities", typeof globalThis.FamilyTreeErrorUtils !== "undefined"],
  ["privacy utilities", typeof globalThis.FamilyTreePrivacyUtils !== "undefined"],
  ["person search utilities", typeof globalThis.FamilyTreePersonSearchUtils !== "undefined"],
].filter(([, available]) => !available).map(([name]) => name);

if (missingRuntimeDependencies.length === 0) {
const { useCallback, useEffect, useMemo, useRef, useState } = React;
const { describeGraphNode, findDirectionalGraphNode } = globalThis.FamilyTreeGraphUtils;
const { formatApiErrorDetail } = globalThis.FamilyTreeErrorUtils;
const { buildExternalMapUrl } = globalThis.FamilyTreePrivacyUtils;
const { buildPersonSearchIndex, searchPersonIndex } = globalThis.FamilyTreePersonSearchUtils;
  const RELATIONSHIP_TYPES = [
    { value: "parent_of", label: "parent_of (A is parent of B)" },
    { value: "child_of", label: "child_of (A is child of B)" },
    { value: "spouse_of", label: "spouse_of (A and B are spouses)" },
    { value: "sibling_of", label: "sibling_of (A and B are siblings)" },
    { value: "aunt_uncle_of", label: "aunt_uncle_of (A is aunt/uncle of B)" },
    { value: "niece_nephew_of", label: "niece_nephew_of (A is niece/nephew of B)" },
    { value: "cousin_of", label: "cousin_of (A and B are cousins)" },
  ];
  const MEDIA_ACCEPT = ".jpg,.jpeg,.png,.webp,.gif,.heic,.heif,.tif,.tiff,.pdf,.txt,.mp3,.wav,.m4a,.mp4,.mov";
  const SELECTION_STABILIZE_MS = 80;
  const MANAGEMENT_DEFER_MS = 240;
  const PANEL_ROW_LIMIT = 80;
  const PERSON_SEARCH_RESULT_LIMIT = 8;
  const LARGE_GRAPH_NODE_THRESHOLD = 180;
  const LARGE_GRAPH_EDGE_THRESHOLD = 320;
  const GRAPH_FIRST_FRAME_BUDGET_MS = 1200;
  const LARGE_GRAPH_MIN_ZOOM = 0.005;

class AppErrorBoundary extends React.Component {
  constructor(props) {
    super(props);
    this.state = { failed: false };
  }

  static getDerivedStateFromError() {
    return { failed: true };
  }

  componentDidCatch(error) {
    console.error("Viraasat UI render failed", error);
  }

  render() {
    if (!this.state.failed) return this.props.children;
    return React.createElement("section", { className: "bootstrap-state", role: "alert" },
      React.createElement("div", { className: "bootstrap-card" }, [
        React.createElement("h1", { key: "title" }, "The interface encountered an error"),
        React.createElement("p", { key: "message" }, "Your family data was not changed. Reload the interface to try again."),
        React.createElement("button", { key: "retry", type: "button", onClick: () => window.location.reload() }, "Reload Viraasat"),
      ])
    );
  }
}

function usesLargeGraphMode(nodes, edges) {
  return nodes.length > LARGE_GRAPH_NODE_THRESHOLD || edges.length > LARGE_GRAPH_EDGE_THRESHOLD;
}

function formatFileSize(bytes) {
  const value = Number(bytes) || 0;
  if (value < 1024) return `${value} B`;
  if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} KiB`;
  return `${(value / (1024 * 1024)).toFixed(1)} MiB`;
}

function edgeKey(fromId, toId) {
  return `${fromId}->${toId}`;
}

function parseYear(dateStr) {
  if (!dateStr || typeof dateStr !== "string") return null;
  const n = Number(dateStr.slice(0, 4));
  return Number.isFinite(n) && n > 0 ? n : null;
}

function computeLevelMap(nodes, edges, rootPersonId) {
  const outgoing = {};
  edges.forEach((e) => {
    if (!outgoing[e.from_person_id]) outgoing[e.from_person_id] = [];
    outgoing[e.from_person_id].push(e.to_person_id);
  });
  const level = {};
  if (rootPersonId) level[rootPersonId] = 0;
  const q = rootPersonId ? [[rootPersonId, 0]] : [];
  for (let queueIndex = 0; queueIndex < q.length; queueIndex += 1) {
    const [id, depth] = q[queueIndex];
    (outgoing[id] || []).forEach((nextId) => {
      if (level[nextId] === undefined) {
        level[nextId] = depth + 1;
        q.push([nextId, depth + 1]);
      }
    });
  }
  nodes.forEach((n) => {
    if (level[n.id] === undefined) level[n.id] = 0;
  });
  return level;
}

function computeLayout(subgraph, rootPersonId) {
  const nodes = subgraph?.persons || [];
  const edges = subgraph?.relationships || [];
  if (!nodes.length) return { width: 1000, height: 600, pos: {}, nodes, edges, layoutMeta: {} };
  const compact = usesLargeGraphMode(nodes, edges);
  const NODE_H = compact ? 66 : 152;
  const NODE_W = compact ? 168 : 312;
  const byId = {};
  nodes.forEach((n) => { byId[n.id] = n; });
  const parentEdges = normalizeParentEdges(edges).filter(([p, c]) => byId[p] && byId[c]);
  const parentChoices = {};
  const parentsByChild = {};
  const childrenByParent = {};
  parentEdges.forEach(([p, c]) => {
    if (!parentsByChild[c]) parentsByChild[c] = [];
    parentsByChild[c].push(p);
  });
  Object.entries(parentsByChild).forEach(([childId, parents]) => {
    const sorted = parents.slice().sort((a, b) => {
      const an = (byId[a].full_name || "").toLowerCase();
      const bn = (byId[b].full_name || "").toLowerCase();
      return an.localeCompare(bn) || a.localeCompare(b);
    });
    parentChoices[childId] = sorted[0];
  });
  Object.entries(parentChoices).forEach(([c, p]) => {
    if (!childrenByParent[p]) childrenByParent[p] = [];
    childrenByParent[p].push(c);
  });

  const leftPad = compact ? 170 : 280;
  const topPad = compact ? 64 : 96;
  const xGap = compact ? 190 : 356;
  const rowGap = compact ? 112 : 244;
  const depth = {};
  const assigned = new Set();
  const roots = nodes
    .filter((n) => !parentChoices[n.id])
    .map((n) => n.id)
    .sort((a, b) => (byId[a].full_name || "").localeCompare(byId[b].full_name || "") || a.localeCompare(b));
  if (rootPersonId && roots.includes(rootPersonId)) {
    roots.splice(roots.indexOf(rootPersonId), 1);
    roots.unshift(rootPersonId);
  }
  let xCursor = 0;
  function place(id, d) {
    if (assigned.has(id)) return xCursor;
    assigned.add(id);
    depth[id] = d;
    const children = (childrenByParent[id] || []).slice().sort((a, b) => {
      const an = (byId[a].full_name || "").toLowerCase();
      const bn = (byId[b].full_name || "").toLowerCase();
      return an.localeCompare(bn) || a.localeCompare(b);
    });
    if (!children.length) {
      const slot = xCursor;
      xCursor += 1;
      return slot;
    }
    const childSlots = children.map((c) => place(c, d + 1));
    return (Math.min(...childSlots) + Math.max(...childSlots)) / 2;
  }
  const rootSlots = {};
  roots.forEach((r) => { rootSlots[r] = place(r, 0); });
  nodes.forEach((n) => {
    if (!assigned.has(n.id)) rootSlots[n.id] = place(n.id, 0);
  });

  const pos = {};
  nodes.forEach((n) => {
    const slot = Object.prototype.hasOwnProperty.call(rootSlots, n.id) ? rootSlots[n.id] : 0;
    const x = leftPad + slot * xGap;
    const y = topPad + (depth[n.id] || 0) * rowGap;
    pos[n.id] = { x, y };
  });

  const kinByNode = {};
  const spouseByNode = {};
  const lateralTypes = new Set(["sibling_of", "cousin_of", "spouse_of", "partner_of"]);
  edges.forEach((edge) => {
    let fromId = edge.from_person_id;
    let toId = edge.to_person_id;
    let relType = edge.relationship_type;
    if (relType === "child_of") {
      fromId = edge.to_person_id;
      toId = edge.from_person_id;
      relType = "parent_of";
    } else if (relType === "niece_nephew_of") {
      fromId = edge.to_person_id;
      toId = edge.from_person_id;
      relType = "aunt_uncle_of";
    }
    if (!lateralTypes.has(relType)) return;
    if (relType === "sibling_of" || relType === "cousin_of") {
      if (!kinByNode[fromId]) kinByNode[fromId] = new Set();
      if (!kinByNode[toId]) kinByNode[toId] = new Set();
      kinByNode[fromId].add(toId);
      kinByNode[toId].add(fromId);
    }
    if (relType === "spouse_of" || relType === "partner_of") {
      if (!spouseByNode[fromId]) spouseByNode[fromId] = new Set();
      if (!spouseByNode[toId]) spouseByNode[toId] = new Set();
      spouseByNode[fromId].add(toId);
      spouseByNode[toId].add(fromId);
    }
  });
  const rowsByDepth = {};
  nodes.forEach((n) => {
    const d = depth[n.id] || 0;
    if (!rowsByDepth[d]) rowsByDepth[d] = [];
    rowsByDepth[d].push(n.id);
  });
  Object.values(rowsByDepth).forEach((rowNodeIds) => {
    if (rowNodeIds.length < 2) return;
    const rowSet = new Set(rowNodeIds);
    const roleByNode = new Map();
    rowNodeIds.forEach((id) => {
      const hasKin = Boolean(kinByNode[id] && Array.from(kinByNode[id]).some((peerId) => rowSet.has(peerId)));
      const hasSpouseOnly = !hasKin && Boolean(spouseByNode[id] && Array.from(spouseByNode[id]).some((peerId) => rowSet.has(peerId)));
      roleByNode.set(id, hasKin ? 0 : (hasSpouseOnly ? 2 : 1));
    });
    const sorted = rowNodeIds.slice().sort((a, b) => {
      const ax = pos[a].x;
      const bx = pos[b].x;
      const aRole = roleByNode.get(a);
      const bRole = roleByNode.get(b);
      if (aRole !== bRole) return aRole - bRole;
      return ax - bx;
    });
    const center = sorted.reduce((sum, id) => sum + pos[id].x, 0) / sorted.length;
    const start = center - ((sorted.length - 1) * xGap) / 2;
    sorted.forEach((id, i) => {
      pos[id].x = start + i * xGap;
    });
  });

  Object.entries(parentsByChild).forEach(([childId, parentIds]) => {
    if (!pos[childId] || !Array.isArray(parentIds) || parentIds.length < 2) return;
    const parentPos = parentIds.map((id) => pos[id]).filter(Boolean);
    if (parentPos.length < 2) return;
    pos[childId].x = parentPos.reduce((sum, p) => sum + p.x, 0) / parentPos.length;
  });

  Object.values(rowsByDepth).forEach((rowNodeIds) => {
    if (rowNodeIds.length < 2) return;
    const sorted = rowNodeIds.slice().sort((a, b) => pos[a].x - pos[b].x);
    const originalCenter = sorted.reduce((sum, id) => sum + pos[id].x, 0) / sorted.length;
    const minGap = compact ? 180 : 334;
    for (let i = 1; i < sorted.length; i += 1) {
      const prev = sorted[i - 1];
      const cur = sorted[i];
      const gap = pos[cur].x - pos[prev].x;
      if (gap < minGap) {
        pos[cur].x = pos[prev].x + minGap;
      }
    }
    const newCenter = sorted.reduce((sum, id) => sum + pos[id].x, 0) / sorted.length;
    const shift = originalCenter - newCenter;
    sorted.forEach((id) => {
      pos[id].x += shift;
    });
  });

  const maxDepth = Math.max(0, ...Object.values(depth));
  const nodeXs = Object.values(pos).map((p) => p.x);
  const minX = Math.min(...nodeXs);
  const maxX = Math.max(...nodeXs);
  const xShift = Math.max(0, 220 - minX);
  if (xShift > 0) {
    Object.keys(pos).forEach((id) => {
      pos[id].x += xShift;
    });
  }
  const shiftedMaxX = Math.max(...Object.values(pos).map((p) => p.x));
  const width = Math.max(1280, shiftedMaxX + NODE_W / 2 + 180);
  const height = Math.max(760, topPad * 2 + (maxDepth + 1) * rowGap + NODE_H);
  return { width, height, pos, nodes, edges, layoutMeta: { level: depth } };
}

function computeGenerationMap(nodes, edges, rootPersonId) {
  const parentPairs = [];
  const lateralPairs = [];
  edges.forEach((e) => {
    let fromId = e.from_person_id;
    let toId = e.to_person_id;
    let relType = e.relationship_type;
    if (relType === "child_of") {
      fromId = e.to_person_id;
      toId = e.from_person_id;
      relType = "parent_of";
    } else if (relType === "niece_nephew_of") {
      fromId = e.to_person_id;
      toId = e.from_person_id;
      relType = "aunt_uncle_of";
    }
    if (relType === "parent_of") {
      parentPairs.push([fromId, toId]); // parent -> child
    } else if (relType === "spouse_of" || relType === "sibling_of" || relType === "cousin_of" || relType === "partner_of") {
      lateralPairs.push([fromId, toId]); // same generation
    }
  });
  const parentsByChild = {};
  const childrenByParent = {};
  parentPairs.forEach(([p, c]) => {
    if (!parentsByChild[c]) parentsByChild[c] = [];
    if (!childrenByParent[p]) childrenByParent[p] = [];
    parentsByChild[c].push(p);
    childrenByParent[p].push(c);
  });
  const lateral = {};
  lateralPairs.forEach(([a, b]) => {
    if (!lateral[a]) lateral[a] = [];
    if (!lateral[b]) lateral[b] = [];
    lateral[a].push(b);
    lateral[b].push(a);
  });

  const gen = {};
  if (rootPersonId) gen[rootPersonId] = 0;
  const q = rootPersonId ? [rootPersonId] : [];
  for (let queueIndex = 0; queueIndex < q.length; queueIndex += 1) {
    const cur = q[queueIndex];
    const g = gen[cur] || 0;
    (parentsByChild[cur] || []).forEach((p) => {
      if (gen[p] === undefined) {
        gen[p] = g - 1;
        q.push(p);
      }
    });
    (childrenByParent[cur] || []).forEach((c) => {
      if (gen[c] === undefined) {
        gen[c] = g + 1;
        q.push(c);
      }
    });
    (lateral[cur] || []).forEach((n) => {
      if (gen[n] === undefined) {
        gen[n] = g;
        q.push(n);
      }
    });
  }
  nodes.forEach((n) => {
    if (gen[n.id] === undefined) gen[n.id] = 0;
  });
  return gen;
}

function normalizeParentEdges(edges) {
  const rows = [];
  (edges || []).forEach((e) => {
    let from = e.from_person_id;
    let to = e.to_person_id;
    let t = e.relationship_type;
    if (t === "child_of") {
      from = e.to_person_id;
      to = e.from_person_id;
      t = "parent_of";
    }
    if (t === "parent_of") rows.push([from, to]);
  });
  return rows;
}

function computeTimeAlignedLayout(subgraph, rootPersonId, contextEvents) {
  const nodes = subgraph?.persons || [];
  const edges = subgraph?.relationships || [];
  if (!nodes.length) return { width: 1100, height: 760, pos: {}, nodes, edges, layoutMeta: {} };
  const compact = usesLargeGraphMode(nodes, edges);
  const NODE_H = compact ? 66 : 152;
  const NODE_W = compact ? 168 : 312;
  const byId = {};
  nodes.forEach((n) => { byId[n.id] = n; });
  const parentEdges = normalizeParentEdges(edges).filter(([p, c]) => byId[p] && byId[c]);
  const parentChoices = {};
  const parentsByChild = {};
  const childrenByParent = {};
  parentEdges.forEach(([p, c]) => {
    if (!parentsByChild[c]) parentsByChild[c] = [];
    parentsByChild[c].push(p);
  });
  Object.entries(parentsByChild).forEach(([childId, parents]) => {
    const sorted = parents.slice().sort((a, b) => a.localeCompare(b));
    parentChoices[childId] = sorted[0];
  });
  Object.entries(parentChoices).forEach(([c, p]) => {
    if (!childrenByParent[p]) childrenByParent[p] = [];
    childrenByParent[p].push(c);
  });

  const nodeYears = {};
  nodes.forEach((n) => {
    nodeYears[n.id] = parseYear(n.birth_date) || parseYear(n.death_date);
  });
  const eventRows = (contextEvents || [])
    .map((evt) => ({ ...evt, year: parseYear(evt.date) }))
    .filter((evt) => evt.year != null)
    .sort((a, b) => a.year - b.year);
  const allYears = Object.values(nodeYears).filter((y) => y != null).concat(eventRows.map((e) => e.year));
  const minYear = allYears.length ? Math.min(...allYears) : 1850;
  const maxYear = allYears.length ? Math.max(...allYears) : minYear + 40;
  const spanYears = Math.max(1, maxYear - minYear);

  const rowGap = compact ? 112 : 244;
  const xGap = compact ? 190 : 356;
  const leftPad = compact ? 170 : 280;
  const topPad = compact ? 54 : 72;
  const pos = {};
  const depth = {};
  const assigned = new Set();
  const roots = nodes
    .filter((n) => !parentChoices[n.id])
    .map((n) => n.id)
    .sort((a, b) => {
      const ay = nodeYears[a] ?? 9999;
      const by = nodeYears[b] ?? 9999;
      return ay - by || (byId[a].full_name || "").localeCompare(byId[b].full_name || "");
    });
  if (rootPersonId && roots.includes(rootPersonId)) {
    roots.splice(roots.indexOf(rootPersonId), 1);
    roots.unshift(rootPersonId);
  }
  let xCursor = 0;
  function place(id, d) {
    if (assigned.has(id)) return xCursor;
    assigned.add(id);
    depth[id] = d;
    const children = (childrenByParent[id] || []).slice().sort((a, b) => {
      const ay = nodeYears[a] ?? 9999;
      const by = nodeYears[b] ?? 9999;
      return ay - by || (byId[a].full_name || "").localeCompare(byId[b].full_name || "");
    });
    if (!children.length) {
      const slot = xCursor;
      xCursor += 1;
      return slot;
    }
    const childSlots = children.map((c) => place(c, d + 1));
    return (Math.min(...childSlots) + Math.max(...childSlots)) / 2;
  }
  const rootSlots = {};
  roots.forEach((r) => { rootSlots[r] = place(r, 0); });
  nodes.forEach((n) => {
    if (!assigned.has(n.id)) {
      rootSlots[n.id] = place(n.id, 0);
    }
  });
  const maxDepth = Math.max(0, ...Object.values(depth));
  const jitterForYear = (id) => {
    const y = nodeYears[id];
    if (y == null) return 0;
    const ratio = (y - minYear) / spanYears;
    return (ratio - 0.5) * 30;
  };
  nodes.forEach((n) => {
    const slot = Object.prototype.hasOwnProperty.call(rootSlots, n.id) ? rootSlots[n.id] : 0;
    const x = leftPad + slot * xGap;
    const baseY = topPad + (depth[n.id] || 0) * rowGap;
    pos[n.id] = { x, y: baseY + jitterForYear(n.id) };
  });

  const lateralByNode = {};
  const kinByNode = {};
  const spouseByNode = {};
  const lateralTypes = new Set(["sibling_of", "cousin_of", "spouse_of", "partner_of"]);
  edges.forEach((edge) => {
    let fromId = edge.from_person_id;
    let toId = edge.to_person_id;
    let relType = edge.relationship_type;
    if (relType === "child_of") {
      fromId = edge.to_person_id;
      toId = edge.from_person_id;
      relType = "parent_of";
    } else if (relType === "niece_nephew_of") {
      fromId = edge.to_person_id;
      toId = edge.from_person_id;
      relType = "aunt_uncle_of";
    }
    if (!lateralTypes.has(relType)) return;
    if (!lateralByNode[fromId]) lateralByNode[fromId] = [];
    if (!lateralByNode[toId]) lateralByNode[toId] = [];
    lateralByNode[fromId].push({ id: toId, type: relType });
    lateralByNode[toId].push({ id: fromId, type: relType });
    if (relType === "sibling_of" || relType === "cousin_of") {
      if (!kinByNode[fromId]) kinByNode[fromId] = new Set();
      if (!kinByNode[toId]) kinByNode[toId] = new Set();
      kinByNode[fromId].add(toId);
      kinByNode[toId].add(fromId);
    }
    if (relType === "spouse_of" || relType === "partner_of") {
      if (!spouseByNode[fromId]) spouseByNode[fromId] = new Set();
      if (!spouseByNode[toId]) spouseByNode[toId] = new Set();
      spouseByNode[fromId].add(toId);
      spouseByNode[toId].add(fromId);
    }
  });

  const rowsByDepth = {};
  nodes.forEach((n) => {
    const d = depth[n.id] || 0;
    if (!rowsByDepth[d]) rowsByDepth[d] = [];
    rowsByDepth[d].push(n.id);
  });
  Object.values(rowsByDepth).forEach((rowNodeIds) => {
    if (rowNodeIds.length < 2) return;
    const rowSet = new Set(rowNodeIds);
    const roleByNode = new Map();
    rowNodeIds.forEach((id) => {
      const hasKin = Boolean(kinByNode[id] && Array.from(kinByNode[id]).some((peerId) => rowSet.has(peerId)));
      const hasSpouseOnly = !hasKin && Boolean(spouseByNode[id] && Array.from(spouseByNode[id]).some((peerId) => rowSet.has(peerId)));
      roleByNode.set(id, hasKin ? 0 : (hasSpouseOnly ? 2 : 1));
    });
    const sorted = rowNodeIds.slice().sort((a, b) => {
      const ax = pos[a].x;
      const bx = pos[b].x;
      const aRole = roleByNode.get(a);
      const bRole = roleByNode.get(b);
      const aHasChildren = (childrenByParent[a] || []).length > 0 ? 1 : 0;
      const bHasChildren = (childrenByParent[b] || []).length > 0 ? 1 : 0;
      if (aRole !== bRole) return aRole - bRole;
      if (aRole === 0 && aHasChildren !== bHasChildren) return aHasChildren - bHasChildren;
      return ax - bx;
    });
    const center = sorted.reduce((sum, id) => sum + pos[id].x, 0) / sorted.length;
    const start = center - ((sorted.length - 1) * xGap) / 2;
    sorted.forEach((id, i) => {
      pos[id].x = start + i * xGap;
    });
  });

  Object.entries(parentsByChild).forEach(([childId, parentIds]) => {
    if (!pos[childId] || !Array.isArray(parentIds) || parentIds.length < 2) return;
    const parentPos = parentIds.map((id) => pos[id]).filter(Boolean);
    if (parentPos.length < 2) return;
    pos[childId].x = parentPos.reduce((sum, p) => sum + p.x, 0) / parentPos.length;
  });

  Object.values(rowsByDepth).forEach((rowNodeIds) => {
    if (rowNodeIds.length < 2) return;
    const sorted = rowNodeIds.slice().sort((a, b) => pos[a].x - pos[b].x);
    const originalCenter = sorted.reduce((sum, id) => sum + pos[id].x, 0) / sorted.length;
    const minGap = compact ? 180 : 334;
    for (let i = 1; i < sorted.length; i += 1) {
      const prev = sorted[i - 1];
      const cur = sorted[i];
      const gap = pos[cur].x - pos[prev].x;
      if (gap < minGap) {
        pos[cur].x = pos[prev].x + minGap;
      }
    }
    const newCenter = sorted.reduce((sum, id) => sum + pos[id].x, 0) / sorted.length;
    const shift = originalCenter - newCenter;
    sorted.forEach((id) => {
      pos[id].x += shift;
    });
  });

  const rowCount = maxDepth + 1;
  const rawHeight = topPad * 2 + (rowCount - 1) * rowGap + NODE_H;
  const nodeXs = Object.values(pos).map((p) => p.x);
  const minX = Math.min(...nodeXs);
  const maxX = Math.max(...nodeXs);
  const xShift = Math.max(0, 220 - minX);
  if (xShift > 0) {
    Object.keys(pos).forEach((id) => {
      pos[id].x += xShift;
    });
  }
  const shiftedMaxX = Math.max(...Object.values(pos).map((p) => p.x));
  const width = Math.max(1280, shiftedMaxX + NODE_W / 2 + 180);
  const eventLaneX = 0;
  const yForYear = (year, yMin, yMax) => {
    const ratio = (year - minYear) / spanYears;
    return yMin + ratio * (yMax - yMin);
  };
  const minNodeTop = Math.min(...Object.values(pos).map((p) => p.y));
  const maxNodeBottom = Math.max(...Object.values(pos).map((p) => p.y + NODE_H));
  const topMargin = 88;
  const bottomMargin = 120;
  const yShift = topMargin - minNodeTop;
  Object.keys(pos).forEach((id) => {
    pos[id].y += yShift;
  });
  const treeHeight = Math.max(rawHeight, maxNodeBottom + yShift + bottomMargin);
  const eventMarks = eventRows.map((evt) => ({
    id: evt.id,
    title: evt.title,
    event_type: evt.event_type,
    year: evt.year,
    y: yForYear(evt.year, topMargin, treeHeight - topMargin),
  }));
  const rowBands = Array.from({ length: rowCount }, (_, l) => {
    return {
      level: l,
      y: topPad + l * rowGap + NODE_H / 2 + yShift,
    };
  });
  return {
    width,
    height: treeHeight,
    pos,
    nodes,
    edges,
    layoutMeta: {
      level: depth,
      mode: "time_aligned",
      minYear,
      maxYear,
      eventLaneX,
      eventMarks,
      rowBands,
    },
  };
}

function computeGraphLayout(subgraph, rootPersonId, layoutMode, contextEvents) {
  if (layoutMode === "time_aligned") {
    return computeTimeAlignedLayout(subgraph, rootPersonId, contextEvents);
  }
  return computeLayout(subgraph, rootPersonId);
}

function normalizeDisplayEdges(edges) {
  const undirectedTypes = new Set(["spouse_of", "sibling_of", "cousin_of", "partner_of"]);
  const displayEdgeMap = new Map();
  edges.forEach((edge) => {
    let fromId = edge.from_person_id;
    let toId = edge.to_person_id;
    let relType = edge.relationship_type;
    if (relType === "child_of") {
      fromId = edge.to_person_id;
      toId = edge.from_person_id;
      relType = "parent_of";
    } else if (relType === "niece_nephew_of") {
      fromId = edge.to_person_id;
      toId = edge.from_person_id;
      relType = "aunt_uncle_of";
    } else if (relType === "grandchild_of") {
      fromId = edge.to_person_id;
      toId = edge.from_person_id;
      relType = "grandparent_of";
    }
    if (undirectedTypes.has(relType) && fromId > toId) {
      fromId = edge.to_person_id;
      toId = edge.from_person_id;
    }
    const dedupeKey = `${fromId}|${toId}|${relType}`;
    if (!displayEdgeMap.has(dedupeKey)) {
      displayEdgeMap.set(dedupeKey, {
        id: dedupeKey,
        from_person_id: fromId,
        to_person_id: toId,
        relationship_type: relType,
      });
    }
  });
  return { undirectedTypes, displayEdges: Array.from(displayEdgeMap.values()) };
}

function GraphView({
  subgraph,
  rootPersonId,
  layoutMode,
  contextEvents,
  mediaPreviewByPersonId,
  zoom,
  selectedNodeId,
  newArrivalId,
  highlightedNodeIds,
  highlightedEdgeKeys,
  onNodeClick,
  onRenderComplete,
  renderStartedAt,
}) {
  const svgRef = useRef(null);
  const transformRef = useRef(null);
  const zoomBehaviorRef = useRef(null);
  const onNodeClickRef = useRef(onNodeClick);
  const onRenderCompleteRef = useRef(onRenderComplete);
  const prevLayoutSignatureRef = useRef("");
  const hasData = Boolean(subgraph && subgraph.persons && subgraph.persons.length);
  onNodeClickRef.current = onNodeClick;
  onRenderCompleteRef.current = onRenderComplete;
  const layout = useMemo(
    () => computeGraphLayout(hasData ? subgraph : { persons: [], relationships: [] }, rootPersonId, layoutMode, contextEvents),
    [contextEvents, hasData, layoutMode, rootPersonId, subgraph]
  );
  const { width, height, pos, nodes, edges, layoutMeta } = layout;
  const CANVAS_PAD_X = 220;
  const CANVAS_PAD_Y = 260;
  const names = useMemo(() => {
    const rows = {};
    nodes.forEach((n) => { rows[n.id] = n.full_name; });
    return rows;
  }, [nodes]);
  const normalizedEdges = useMemo(() => normalizeDisplayEdges(edges), [edges]);
  const { undirectedTypes, displayEdges } = normalizedEdges;
  const connectionCountByNode = useMemo(() => {
    const counts = {};
    displayEdges.forEach((edge) => {
      counts[edge.from_person_id] = (counts[edge.from_person_id] || 0) + 1;
      counts[edge.to_person_id] = (counts[edge.to_person_id] || 0) + 1;
    });
    return counts;
  }, [displayEdges]);
  const largeGraphMode = usesLargeGraphMode(nodes, displayEdges);
  const NODE_W = largeGraphMode ? 168 : 312;
  const NODE_H = largeGraphMode ? 66 : 152;
  const NODE_HALF_W = NODE_W / 2;
  const NODE_HALF_H = NODE_H / 2;

  useEffect(() => {
    if (!hasData || !svgRef.current || typeof d3 === "undefined") return;
    const svg = d3.select(svgRef.current);
    svg.selectAll("*").remove();

    const camera = svg.append("g");
    const stage = camera.append("g").attr("transform", `translate(${CANVAS_PAD_X}, ${CANVAS_PAD_Y})`);
    const root = stage.append("g");

    const localPos = {};
    nodes.forEach((n) => {
      const base = pos[n.id] || { x: 170, y: 100 };
      localPos[n.id] = { x: base.x, y: base.y };
    });
    const layoutSignature = `${layoutMode}|${width}|${height}|${nodes.map((n) => n.id).join(",")}`;
    const shouldAnimateNodes = prevLayoutSignatureRef.current !== layoutSignature;
    prevLayoutSignatureRef.current = layoutSignature;

    function drawGraph() {
      root.selectAll(".edge-layer,.node-layer").remove();
      if (layoutMode === "time_aligned" && layoutMeta && Array.isArray(layoutMeta.rowBands)) {
        const bandLayer = root.append("g").attr("class", "edge-layer");
        layoutMeta.rowBands.forEach((band, i) => {
          const yy = band.y;
          bandLayer
            .append("line")
            .attr("x1", 132)
            .attr("x2", width - 28)
            .attr("y1", yy)
            .attr("y2", yy)
            .attr("stroke", "rgba(160, 65, 0, 0.18)")
            .attr("stroke-width", 1.1)
            .attr("stroke-dasharray", "3 7");
          bandLayer
            .append("text")
            .attr("x", 14)
            .attr("y", yy - 8)
            .attr("font-size", 10)
            .attr("font-family", "Manrope, sans-serif")
            .attr("font-weight", 700)
            .attr("fill", "#9a7c64")
            .text(`Generation ${band.level >= 0 ? `+${band.level}` : band.level}`);
          if (i === 0) {
            bandLayer
              .append("text")
              .attr("x", 14)
              .attr("y", 22)
              .attr("font-size", 11)
              .attr("font-family", "Manrope, sans-serif")
              .attr("letter-spacing", "0.08em")
              .attr("text-transform", "uppercase")
              .attr("fill", "#a38873")
              .text("Hierarchical Family Tree");
          }
        });
      }
      const pairCounts = new Map();
      displayEdges.forEach((edge) => {
        const pairKey = undirectedTypes.has(edge.relationship_type)
          ? [edge.from_person_id, edge.to_person_id].sort().join("|")
          : `${edge.from_person_id}|${edge.to_person_id}`;
        pairCounts.set(pairKey, (pairCounts.get(pairKey) || 0) + 1);
      });
      const pairSeen = new Map();
      const directedIncomingCounts = new Map();
      const directedOutgoingCounts = new Map();
      displayEdges.forEach((edge) => {
        if (undirectedTypes.has(edge.relationship_type)) return;
        directedIncomingCounts.set(edge.to_person_id, (directedIncomingCounts.get(edge.to_person_id) || 0) + 1);
        directedOutgoingCounts.set(edge.from_person_id, (directedOutgoingCounts.get(edge.from_person_id) || 0) + 1);
      });
      const directedIncomingSeen = new Map();
      const directedOutgoingSeen = new Map();
      const lateralLaneSeen = new Map();
      const parentGroups = new Map();
      const parentJunctionByChild = new Map();
      displayEdges.forEach((edge) => {
        if (edge.relationship_type !== "parent_of") return;
        if (!localPos[edge.from_person_id] || !localPos[edge.to_person_id]) return;
        const childId = edge.to_person_id;
        if (!parentGroups.has(childId)) parentGroups.set(childId, []);
        parentGroups.get(childId).push(edge.from_person_id);
      });
      parentGroups.forEach((parents, childId) => {
        parents.sort((a, b) => (localPos[a].x - localPos[b].x) || a.localeCompare(b));
        parentGroups.set(childId, parents);
      });

      const edgeLayer = root.append("g").attr("class", "edge-layer");
      const nodeLayer = root.append("g").attr("class", "node-layer");
      const labelSpecs = [];
      const nodeIds = nodes.map((node) => node.id);

      displayEdges.forEach((edge) => {
        let fromId = edge.from_person_id;
        let toId = edge.to_person_id;
        let from = localPos[fromId];
        let to = localPos[toId];
        if (!from || !to) return;
        const isUndirected = undirectedTypes.has(edge.relationship_type);
        if (isUndirected && from.x > to.x) {
          fromId = edge.to_person_id;
          toId = edge.from_person_id;
          from = localPos[fromId];
          to = localPos[toId];
        }
        const pairKey = isUndirected ? [fromId, toId].sort().join("|") : `${fromId}|${toId}`;
        const seen = pairSeen.get(pairKey) || 0;
        pairSeen.set(pairKey, seen + 1);
        const count = pairCounts.get(
          isUndirected ? [edge.from_person_id, edge.to_person_id].sort().join("|") : `${edge.from_person_id}|${edge.to_person_id}`
        ) || 1;
        const laneOffset = (seen - (count - 1) / 2) * 14;
        const relType = edge.relationship_type;
        const edgeStyle = (() => {
          if (relType === "parent_of") return { color: layoutMode === "time_aligned" ? "rgba(160, 65, 0, 0.44)" : "var(--graph-edge)", width: 2.2, dash: null };
          if (relType === "spouse_of" || relType === "partner_of") return { color: "rgba(76, 86, 175, 0.52)", width: 1.9, dash: null };
          if (relType === "sibling_of") return { color: "rgba(122, 48, 0, 0.44)", width: 1.8, dash: "6 4" };
          if (relType === "cousin_of") return { color: "rgba(122, 48, 0, 0.34)", width: 1.5, dash: "3 5" };
          return { color: "var(--graph-edge)", width: 2, dash: null };
        })();
        let points = [];
        let endX = 0;
        let endY = 0;
        let labelX = 0;
        let labelY = 0;

        if (relType === "parent_of") {
          const parents = parentGroups.get(toId) || [fromId];
          const parentIdx = Math.max(0, parents.indexOf(fromId));
          const parentCount = Math.max(1, parents.length);
          const fanOffset = (parentIdx - (parentCount - 1) / 2) * 34;
          const startX = from.x + fanOffset * 0.2;
          const startY = from.y + NODE_H;
          const junctionX = to.x;
          const junctionY = to.y - 34 - Math.max(0, parentCount - 2) * 8;
          parentJunctionByChild.set(toId, { x: junctionX, y: junctionY });
          const approachX = junctionX + fanOffset;
          const mergeY = Math.max(startY + 24, junctionY - 24);
          points = [
            [startX, startY],
            [startX, mergeY],
            [approachX, mergeY],
            [approachX, junctionY],
            [junctionX, junctionY],
          ];
          endX = junctionX;
          endY = junctionY;
          labelX = (startX + approachX) / 2;
          labelY = mergeY - 10;
        } else if (isUndirected) {
          const startX = from.x;
          const startY = from.y;
          const endXRaw = to.x;
          const endYRaw = to.y;
          const relationLane = relType === "spouse_of" || relType === "partner_of"
            ? 0
            : relType === "sibling_of"
              ? 1
              : relType === "cousin_of"
                ? 2
                : 3;
          const laneKey = `${relType}|${Math.round((startY + endYRaw) / 2 / 22)}`;
          const laneSeen = lateralLaneSeen.get(laneKey) || 0;
          lateralLaneSeen.set(laneKey, laneSeen + 1);
          const bridgeY = Math.min(startY, endYRaw) - 46 - relationLane * 22 - laneSeen * 12 - Math.abs(laneOffset) * 1.4;
          const gap = Math.abs(endXRaw - startX);
          const minGap = 220;
          const detour = gap < minGap ? (minGap - gap) / 2 + 16 : 0;
          const bridgeLeftX = startX - detour;
          const bridgeRightX = endXRaw + detour;
          points = [
            [startX, startY],
            [startX, bridgeY],
            [bridgeLeftX, bridgeY],
            [bridgeRightX, bridgeY],
            [endXRaw, bridgeY],
            [endXRaw, endYRaw],
          ];
          endX = endXRaw;
          endY = endYRaw;
          labelX = (bridgeLeftX + bridgeRightX) / 2;
          labelY = bridgeY - 8;
        } else {
          let sourceSpread = 0;
          let targetSpread = 0;
          const outSeen = directedOutgoingSeen.get(fromId) || 0;
          directedOutgoingSeen.set(fromId, outSeen + 1);
          const outCount = directedOutgoingCounts.get(fromId) || 1;
          sourceSpread = (outSeen - (outCount - 1) / 2) * 10;
          const inSeen = directedIncomingSeen.get(toId) || 0;
          directedIncomingSeen.set(toId, inSeen + 1);
          const inCount = directedIncomingCounts.get(toId) || 1;
          targetSpread = (inSeen - (inCount - 1) / 2) * 10;
          const startX = from.x + laneOffset + sourceSpread;
          const startY = from.y + NODE_H;
          const endXRaw = to.x + laneOffset + targetSpread;
          const endYRaw = to.y;
          const bridgeY = Math.min(startY, endYRaw) - 46 - Math.abs(laneOffset) * 1.8;
          points = [
            [startX, startY],
            [startX, bridgeY],
            [endXRaw, bridgeY],
            [endXRaw, endYRaw],
          ];
          endX = endXRaw;
          endY = endYRaw;
          labelX = (startX + endXRaw) / 2;
          labelY = bridgeY - 9;
        }

        const pathD = `M ${points.map((p) => `${p[0]} ${p[1]}`).join(" L ")}`;

        const edgeColor = edgeStyle.color;
        edgeLayer
          .append("path")
          .attr("class", "graph-edge")
          .attr("data-from-id", edge.from_person_id)
          .attr("data-to-id", edge.to_person_id)
          .attr("data-base-stroke", edgeColor)
          .attr("data-base-width", edgeStyle.width)
          .attr("d", pathD)
          .attr("fill", "none")
          .attr("stroke", edgeColor)
          .attr("stroke-width", edgeStyle.width)
          .attr("stroke-linecap", "round")
          .attr("stroke-linejoin", "round")
          .attr("stroke-dasharray", edgeStyle.dash);

        if (!largeGraphMode && !isUndirected && relType !== "parent_of") {
          const tanX = 0;
          const tanY = 1;
          const headLen = 11;
          const headWidth = 5;
          const baseX = endX - tanX * headLen;
          const baseY = endY - tanY * headLen;
          const leftX = baseX - headWidth;
          const leftY = baseY;
          const rightX = baseX + headWidth;
          const rightY = baseY;
          edgeLayer
            .append("polygon")
            .attr("class", "graph-edge-head")
            .attr("data-from-id", edge.from_person_id)
            .attr("data-to-id", edge.to_person_id)
            .attr("data-base-fill", edgeColor)
            .attr("points", `${endX},${endY} ${leftX},${leftY} ${rightX},${rightY}`)
            .attr("fill", edgeColor)
            .attr("stroke", edgeColor)
            .attr("stroke-width", 0.8);
        }

        labelSpecs.push({
          x: labelX,
          y: labelY,
          text: edge.relationship_type,
          fromId: edge.from_person_id,
          toId: edge.to_person_id,
        });
      });

      parentJunctionByChild.forEach((junction, childId) => {
        const child = localPos[childId];
        if (!child) return;
        const edgeColor = layoutMode === "time_aligned" ? "rgba(160, 65, 0, 0.44)" : "var(--graph-edge)";
        edgeLayer
          .append("line")
          .attr("x1", junction.x)
          .attr("y1", junction.y)
          .attr("x2", child.x)
          .attr("y2", child.y)
          .attr("stroke", edgeColor)
          .attr("stroke-width", 2.2)
          .attr("stroke-linecap", "round");
        const tanX = 0;
        const tanY = 1;
        const headLen = 11;
        const headWidth = 5;
        const endX = child.x;
        const endY = child.y;
        const baseX = endX - tanX * headLen;
        const baseY = endY - tanY * headLen;
        const leftX = baseX - headWidth;
        const leftY = baseY;
        const rightX = baseX + headWidth;
        const rightY = baseY;
        if (!largeGraphMode) {
          edgeLayer
            .append("polygon")
            .attr("points", `${endX},${endY} ${leftX},${leftY} ${rightX},${rightY}`)
            .attr("fill", edgeColor)
            .attr("stroke", edgeColor)
            .attr("stroke-width", 0.8);
        }
      });

      nodes.forEach((node, idx) => {
        const p = localPos[node.id];
        if (!p) return;
        const isRoot = node.id === rootPersonId;
        const fill = "#ffffff";
        const stroke = isRoot ? "#6f7fbe" : "#aebac6";
        const textColor = "#24317d";
        const subtitleColor = "#6a7988";
        const name = names[node.id] || node.id.slice(0, 8);
        const words = name.split(/\s+/).filter(Boolean);
        const line1 = words.slice(0, 2).join(" ");
        const line2 = words.slice(2, 4).join(" ");
        const years = `${node.birth_date || "?"} — ${node.death_date || "present"}`;
        const badge = node.occupation || node.religion || "ancestor";
        const g = nodeLayer
          .append("g")
          .attr("class", "graph-node")
          .attr("data-node-id", node.id)
          .attr("role", "button")
          .attr("tabindex", isRoot ? 0 : -1)
          .attr("aria-pressed", "false")
          .attr("aria-label", describeGraphNode(node, connectionCountByNode[node.id], false))
          .style("cursor", "pointer")
          .datum(node);
        const level = layoutMeta && layoutMeta.level ? (layoutMeta.level[node.id] || 0) : 0;
        const introOffset = layoutMode === "time_aligned" ? Math.max(-8, Math.min(10, level * 3)) : 0;
        g.style("opacity", 0).attr("transform", `translate(0, ${introOffset})`);
        g.append("rect")
          .attr("class", "graph-node-card")
          .attr("data-node-id", node.id)
          .attr("x", p.x - NODE_HALF_W)
          .attr("y", p.y)
          .attr("width", NODE_W)
          .attr("height", NODE_H)
          .attr("rx", 14)
          .attr("fill", fill)
          .attr("stroke", stroke)
          .attr("stroke-width", 1.8)
          .style("filter", largeGraphMode ? "none" : "drop-shadow(0 32px 48px rgba(27, 28, 26, 0.04))");
        if (largeGraphMode) {
          g.append("text")
            .attr("x", p.x)
            .attr("y", p.y + 28)
            .attr("text-anchor", "middle")
            .attr("font-size", 15)
            .attr("font-family", "Newsreader, Georgia, serif")
            .attr("font-weight", 650)
            .attr("fill", textColor)
            .text(name.length > 22 ? `${name.slice(0, 21)}…` : name);
          g.append("text")
            .attr("x", p.x)
            .attr("y", p.y + 49)
            .attr("text-anchor", "middle")
            .attr("font-size", 9.5)
            .attr("font-family", "Manrope, sans-serif")
            .attr("font-weight", 700)
            .attr("fill", "#a04100")
            .text(years);
        } else {
        const portraitX = p.x - NODE_HALF_W + 12;
        const portraitY = p.y + 10;
        const portraitW = 92;
        const portraitH = 126;
        g.append("rect")
          .attr("x", portraitX)
          .attr("y", portraitY)
          .attr("width", portraitW)
          .attr("height", portraitH)
          .attr("rx", 8)
          .attr("fill", "#d5d2cc")
          .attr("stroke", "#c4c6cd")
          .attr("stroke-width", 1);
        const previewUrl = mediaPreviewByPersonId && mediaPreviewByPersonId[node.id];
        if (previewUrl) {
          const clipId = `portrait-${node.id}`;
          g.append("clipPath")
            .attr("id", clipId)
            .append("rect")
            .attr("x", portraitX)
            .attr("y", portraitY)
            .attr("width", portraitW)
            .attr("height", portraitH)
            .attr("rx", 8);
          g.append("image")
            .attr("class", "graph-node-portrait")
            .attr("data-node-id", node.id)
            .attr("x", portraitX)
            .attr("y", portraitY)
            .attr("width", portraitW)
            .attr("height", portraitH)
            .attr("preserveAspectRatio", "xMidYMid slice")
            .attr("clip-path", `url(#${clipId})`)
            .style("filter", isRoot ? "none" : "grayscale(0.95)")
            .attr("href", previewUrl);
        } else {
          g.append("text")
            .attr("x", p.x - NODE_HALF_W + 58)
            .attr("y", p.y + 74)
            .attr("text-anchor", "middle")
            .attr("font-size", 11)
            .attr("font-family", "Manrope, sans-serif")
            .attr("font-weight", 700)
            .attr("fill", "#5c6a79")
            .text("Portrait");
        }
        g.append("text")
          .attr("x", p.x - NODE_HALF_W + 118)
          .attr("y", p.y + 44)
          .attr("text-anchor", "start")
          .attr("font-size", 23)
          .attr("font-family", "Newsreader, Georgia, serif")
          .attr("font-weight", 650)
          .attr("fill", textColor)
          .text(line1);
        if (line2) {
          g.append("text")
            .attr("x", p.x - NODE_HALF_W + 118)
            .attr("y", p.y + 70)
            .attr("text-anchor", "start")
            .attr("font-size", 20)
            .attr("font-family", "Newsreader, Georgia, serif")
            .attr("font-weight", 650)
            .attr("fill", textColor)
            .text(line2);
        }
        g.append("text")
          .attr("x", p.x - NODE_HALF_W + 118)
          .attr("y", p.y + 96)
          .attr("text-anchor", "start")
          .attr("font-size", 11.5)
          .attr("font-family", "Manrope, sans-serif")
          .attr("font-weight", 700)
          .attr("fill", "#a04100")
          .text(years);
        g.append("text")
          .attr("x", p.x - NODE_HALF_W + 118)
          .attr("y", p.y + 117)
          .attr("text-anchor", "start")
          .attr("font-size", 11.5)
          .attr("font-family", "Manrope, sans-serif")
          .attr("fill", subtitleColor)
          .text((node.birth_place || "Birthplace unknown").slice(0, 30));
        const blurb = (node.personality || node.hobbies || node.occupation || "").slice(0, 42);
        if (blurb) {
          g.append("text")
            .attr("x", p.x - NODE_HALF_W + 118)
            .attr("y", p.y + 138)
            .attr("text-anchor", "start")
            .attr("font-size", 10.5)
            .attr("font-family", "Manrope, sans-serif")
            .attr("fill", "#728091")
            .text(blurb);
        }
        const badgeLines = [];
        let remainingBadge = badge.trim();
        while (remainingBadge && badgeLines.length < 2) {
          let cut = Math.min(28, remainingBadge.length);
          if (cut < remainingBadge.length) {
            const wordBreak = remainingBadge.lastIndexOf(" ", cut);
            if (wordBreak > 10) cut = wordBreak;
          }
          badgeLines.push(remainingBadge.slice(0, cut).trim());
          remainingBadge = remainingBadge.slice(cut).trim();
        }
        if (remainingBadge) badgeLines[1] = `${badgeLines[1].slice(0, 27).trimEnd()}…`;
        const badgeW = Math.max(48, Math.min(178, Math.max(...badgeLines.map((line) => line.length)) * 5.2 + 16));
        const badgeH = badgeLines.length === 2 ? 30 : 18;
        g.append("rect")
          .attr("x", p.x + NODE_HALF_W - badgeW - 12)
          .attr("y", p.y + 7)
          .attr("width", badgeW)
          .attr("height", badgeH)
          .attr("rx", 5)
          .attr("fill", "rgba(255, 219, 204, 0.86)");
        const badgeText = g.append("text")
          .attr("x", p.x + NODE_HALF_W - badgeW / 2 - 12)
          .attr("y", p.y + 20)
          .attr("text-anchor", "middle")
          .attr("font-size", 9.5)
          .attr("font-family", "Manrope, sans-serif")
          .attr("font-weight", 700)
          .attr("fill", "#7a3000");
        badgeLines.forEach((line, lineIndex) => badgeText.append("tspan")
          .attr("x", p.x + NODE_HALF_W - badgeW / 2 - 12)
          .attr("dy", lineIndex ? 12 : 0)
          .text(line));
        badgeText.append("title").text(badge);
        }
        g.on("click", function () {
          this.focus();
          onNodeClickRef.current(node.id);
        });
        g.on("keydown", function (event) {
          if (event.key === "Enter" || event.key === " " || event.key === "Spacebar") {
            event.preventDefault();
            onNodeClickRef.current(node.id);
            return;
          }
          const nextNodeId = findDirectionalGraphNode(node.id, event.key, localPos, displayEdges, nodeIds);
          if (!nextNodeId) return;
          event.preventDefault();
          const nextNode = Array.from(svgRef.current.querySelectorAll(".graph-node"))
            .find((element) => element.getAttribute("data-node-id") === nextNodeId);
          if (nextNode) nextNode.focus();
          onNodeClickRef.current(nextNodeId);
        });
        if (shouldAnimateNodes && !largeGraphMode) {
          g.transition()
            .duration(620)
            .delay(Math.min(360, idx * 26))
            .ease(d3.easeCubicInOut)
            .style("opacity", 1)
            .attr("transform", "translate(0,0)");
        } else {
          g.style("opacity", 1).attr("transform", "translate(0,0)");
        }
      });

      const labelLayer = root.append("g").attr("class", "edge-label-layer");
      if (!largeGraphMode) labelSpecs.forEach((label) => {
        const labelWidth = Math.max(52, label.text.length * 7.6);
        labelLayer
          .append("rect")
          .attr("class", "graph-edge-label-bg")
          .attr("data-from-id", label.fromId)
          .attr("data-to-id", label.toId)
          .attr("x", label.x - labelWidth / 2)
          .attr("y", label.y - 14)
          .attr("width", labelWidth)
          .attr("height", 18)
          .attr("rx", 9)
          .attr("fill", "rgba(251, 249, 245, 0.92)");
        labelLayer
          .append("text")
          .attr("class", "graph-edge-label")
          .attr("data-from-id", label.fromId)
          .attr("data-to-id", label.toId)
          .attr("x", label.x)
          .attr("y", label.y)
          .attr("text-anchor", "middle")
          .attr("font-size", 14)
          .attr("font-family", "Manrope, sans-serif")
          .attr("font-weight", 650)
          .attr("fill", "#607488")
          .text(label.text);
      });
    }

    const zoomBehavior = d3.zoom()
      .scaleExtent([largeGraphMode ? LARGE_GRAPH_MIN_ZOOM : 0.35, 2.4])
      .on("zoom", (event) => {
        transformRef.current = event.transform;
        camera.attr("transform", event.transform);
      });
    zoomBehaviorRef.current = zoomBehavior;
    svg.call(zoomBehavior);

    const startingTransform = transformRef.current
      ? d3.zoomIdentity.translate(transformRef.current.x, transformRef.current.y).scale(zoom)
      : d3.zoomIdentity.scale(zoom);
    svg.call(zoomBehavior.transform, startingTransform);

    drawGraph();
    const startedAt = Number.isFinite(renderStartedAt) && renderStartedAt > 0 ? renderStartedAt : performance.now();
    let cancelled = false;
    window.requestAnimationFrame(() => {
      window.requestAnimationFrame(() => {
        if (cancelled) return;
        const detail = {
          duration_ms: Math.round((performance.now() - startedAt) * 10) / 10,
          node_count: nodes.length,
          edge_count: displayEdges.length,
          large_graph_mode: largeGraphMode,
          budget_ms: GRAPH_FIRST_FRAME_BUDGET_MS,
        };
        window.__familyTreeLastGraphRender = detail;
        if (onRenderCompleteRef.current) onRenderCompleteRef.current(detail);
      });
    });
    return () => {
      cancelled = true;
    };
  }, [connectionCountByNode, displayEdges, hasData, largeGraphMode, layoutMeta, layoutMode, mediaPreviewByPersonId, names, nodes, pos, rootPersonId, undirectedTypes, width, height]);

  useEffect(() => {
    if (!hasData || !svgRef.current || typeof d3 === "undefined") return;
    const svg = d3.select(svgRef.current);
    const isHighlightedEdge = (element) => {
      const fromId = element.getAttribute("data-from-id");
      const toId = element.getAttribute("data-to-id");
      return highlightedEdgeKeys.has(edgeKey(fromId, toId)) || highlightedEdgeKeys.has(edgeKey(toId, fromId));
    };
    svg.selectAll(".graph-edge").each(function () {
      const edge = d3.select(this);
      const highlighted = isHighlightedEdge(this);
      edge
        .attr("stroke", highlighted ? "var(--graph-highlight)" : edge.attr("data-base-stroke"))
        .attr("stroke-width", highlighted ? 3.4 : Number(edge.attr("data-base-width")));
    });
    svg.selectAll(".graph-edge-head").each(function () {
      const edgeHead = d3.select(this);
      const highlighted = isHighlightedEdge(this);
      const color = highlighted ? "var(--graph-highlight)" : edgeHead.attr("data-base-fill");
      edgeHead.attr("fill", color).attr("stroke", color);
    });
    svg.selectAll(".graph-edge-label").each(function () {
      d3.select(this).attr("fill", isHighlightedEdge(this) ? "#9a5b1c" : "#607488");
    });
    svg.selectAll(".graph-node-card").each(function () {
      const card = d3.select(this);
      const nodeId = this.getAttribute("data-node-id");
      const selected = nodeId === selectedNodeId;
      const highlighted = highlightedNodeIds.has(nodeId);
      const root = nodeId === rootPersonId;
      card
        .attr("fill", selected ? "#fffaf2" : "#ffffff")
        .attr("stroke", root ? "#6f7fbe" : selected ? "#d59d56" : highlighted ? "#d7b07b" : "#aebac6")
        .attr("stroke-width", selected ? 2.2 : 1.8);
    });
    svg.selectAll(".graph-node").each(function (node) {
      const nodeId = this.getAttribute("data-node-id");
      const selected = nodeId === selectedNodeId;
      d3.select(this)
        .classed("new-arrival", nodeId === newArrivalId)
        .attr("tabindex", selected || (!selectedNodeId && nodeId === rootPersonId) ? 0 : -1)
        .attr("aria-pressed", selected ? "true" : "false")
        .attr("aria-label", describeGraphNode(node, connectionCountByNode[nodeId], selected));
    });
    svg.selectAll(".graph-node-portrait").each(function () {
      const nodeId = this.getAttribute("data-node-id");
      d3.select(this).style("filter", nodeId === selectedNodeId || nodeId === rootPersonId ? "none" : "grayscale(0.95)");
    });
  }, [connectionCountByNode, hasData, highlightedEdgeKeys, highlightedNodeIds, newArrivalId, rootPersonId, selectedNodeId]);

  useEffect(() => {
    if (!hasData || !svgRef.current || !zoomBehaviorRef.current || typeof d3 === "undefined") return;
    const current = transformRef.current || d3.zoomIdentity;
    const nextTransform = d3.zoomIdentity.translate(current.x, current.y).scale(zoom);
    d3.select(svgRef.current).call(zoomBehaviorRef.current.transform, nextTransform);
  }, [hasData, zoom]);

  if (!hasData) {
    return React.createElement("div", { className: "muted", style: { padding: "14px" } }, "Load a subgraph to begin exploration.");
  }

  return React.createElement(React.Fragment, null, [
    React.createElement("p", { className: "sr-only", id: "graph-keyboard-help", key: "help" },
      "Interactive family graph. Tab enters the graph. Use arrow keys to move toward connected relatives, then nearby people. Press Enter or Space to select a person."
    ),
    React.createElement("svg", {
      ref: svgRef,
      className: "d3-graph-canvas",
      key: "svg",
      role: "group",
      "aria-label": "Interactive family relationship graph",
      "aria-describedby": "graph-keyboard-help",
      "data-base-width": Math.ceil(width + CANVAS_PAD_X * 2),
      "data-base-height": Math.ceil(height + CANVAS_PAD_Y * 2),
      "data-large-graph": largeGraphMode ? "true" : "false",
      width: Math.ceil((width + CANVAS_PAD_X * 2) * zoom),
      height: Math.ceil((height + CANVAS_PAD_Y * 2) * zoom),
    }),
  ]);
}

function LazyDetails({ className = "card", summary, onFirstOpen, children }) {
  const [contentMounted, setContentMounted] = useState(false);
  const renderContent = typeof children === "function" ? children : () => children;
  return React.createElement("details", {
    className,
    "data-lazy-details": summary,
    "data-content-mounted": contentMounted ? "true" : "false",
    onToggle: (event) => {
      if (event.currentTarget.open && !contentMounted) {
        setContentMounted(true);
        if (typeof onFirstOpen === "function") onFirstOpen();
      }
    },
  }, [
    React.createElement("summary", { key: "summary" }, summary),
    contentMounted ? renderContent() : null,
  ]);
}

function GraphControlField({ label, className = "", children }) {
  return React.createElement("label", { className: `graph-control-field ${className}`.trim() }, [
    React.createElement("span", { key: "label" }, label),
    children,
  ]);
}

function PersonPanelSubject({ personId, personName, onFind }) {
  return React.createElement("div", { className: "person-panel-subject" }, [
    React.createElement("input", { key: "value", type: "hidden", name: "person_id", value: personId || "", readOnly: true }),
    React.createElement("span", { key: "label" }, "Selected person"),
    React.createElement("strong", { key: "name" }, personName || "No person selected"),
    React.createElement("button", { key: "find", type: "button", className: "person-panel-find", onClick: onFind }, personId ? "Change with finder" : "Choose with finder"),
  ]);
}

const PERSON_JOURNEY_STEPS = [
  { name: "Meet them", title: "Who are we remembering?", prompt: "Start with the name they use. You can add or change the rest later." },
  { name: "Their world", title: "What fills their days?", prompt: "A job is one part of a life. What do they enjoy, and what are they like to be around?" },
  { name: "Their story", title: "What would you want someone to know?", prompt: "A small memory is enough to begin. You can return to this story together." },
  { name: "Their place", title: "Where do they fit in the family?", prompt: "Connect them to one relative now, or leave this for later." },
];

function PersonJourney({ people, onClose, onReveal, onCheckDuplicates, onSave, onRetryLink }) {
  const h = React.createElement;
  const [step, setStep] = useState(0);
  const [draft, setDraft] = useState({
    full_name: "", birth_date: "", birth_place: "", occupation: "", hobbies: "",
    personality: "", bio_text: "", relative_id: "", relationship_type: "child_of",
  });
  const [hints, setHints] = useState([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [saved, setSaved] = useState(null);
  const dialogRef = useRef(null);
  const firstFieldRef = useRef(null);
  const stepHeadingRef = useRef(null);
  const completionHeadingRef = useRef(null);
  const onCloseRef = useRef(onClose);
  const busyRef = useRef(busy);
  onCloseRef.current = onClose;
  busyRef.current = busy;
  const update = (field) => (event) => {
    const value = event.target.value;
    setDraft((current) => ({ ...current, [field]: value }));
    if (["full_name", "birth_date", "birth_place"].includes(field)) setHints([]);
    setError("");
  };

  useEffect(() => {
    const priorFocus = document.activeElement;
    const priorOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    firstFieldRef.current?.focus();
    function onKeyDown(event) {
      if (event.key === "Escape" && !busyRef.current) onCloseRef.current();
      if (event.key !== "Tab" || !dialogRef.current) return;
      const focusable = Array.from(dialogRef.current.querySelectorAll("button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled])"));
      if (!focusable.length) return;
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
      else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
    }
    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.body.style.overflow = priorOverflow;
      document.removeEventListener("keydown", onKeyDown);
      priorFocus?.focus?.();
    };
  }, []);
  useEffect(() => {
    if (saved) completionHeadingRef.current?.focus();
    else if (step > 0) stepHeadingRef.current?.focus();
  }, [step, saved]);

  async function next() {
    setError("");
    if (step === 0) {
      if (!draft.full_name.trim()) { setError("Please add their name to continue."); return; }
      setBusy(true);
      try {
        const matches = await onCheckDuplicates(draft);
        setHints(matches);
        if (matches.some((match) => match.reasons.includes("exact_name_match") && match.reasons.includes("birth_date_match"))) {
          setError("This person may already be in the circle. Open their profile instead of adding a duplicate.");
          return;
        }
      } catch (cause) { setError(cause.message); return; }
      finally { setBusy(false); }
    }
    setStep((current) => Math.min(current + 1, PERSON_JOURNEY_STEPS.length - 1));
  }

  async function save() {
    setBusy(true); setError("");
    try { setSaved(await onSave(draft)); }
    catch (cause) { setError(cause.message); }
    finally { setBusy(false); }
  }

  async function retryLink() {
    if (!saved?.person?.id) return;
    setBusy(true); setError("");
    try { setSaved(await onRetryLink(saved.person, draft)); }
    catch (cause) { setError(cause.message); }
    finally { setBusy(false); }
  }

  const field = (key, label, placeholder, extra = {}) => h("label", { className: "journey-field", key }, [
    h("span", { key: "label" }, label),
    h("input", { key: "input", value: draft[key], onChange: update(key), onInput: update(key), placeholder, ...extra }),
  ]);
  const stepContent = [
    h("div", { className: "journey-fields", key: "meet" }, [
      field("full_name", "Their name *", "What name do they go by?", { ref: firstFieldRef, maxLength: 200, autoComplete: "off" }),
      field("birth_date", "When were they born?", "", { type: "date" }),
      field("birth_place", "Where did their story begin?", "City, town, or village"),
      hints.length ? h("div", { className: "journey-hints", key: "hints" }, [
        h("strong", { key: "title" }, "Similar people already in this circle"),
        ...hints.slice(0, 3).map((match) => h("p", { key: match.person_id }, `${match.full_name}${match.birth_date ? ` · ${match.birth_date}` : ""}`)),
      ]) : null,
    ]),
    h("div", { className: "journey-fields", key: "world" }, [
      field("occupation", "What work or calling matters to them?", "A job, craft, or role"),
      field("hobbies", "What do they love doing?", "Music, cooking, cricket, long walks…"),
      field("personality", "How would you describe them to a friend?", "The little things that make them themselves"),
    ]),
    h("label", { className: "journey-field", key: "story" }, [
      h("span", { key: "label" }, "A memory, in your own words"),
      h("textarea", { key: "input", value: draft.bio_text, onChange: update("bio_text"), rows: 7, placeholder: "I remember when…" }),
      h("small", { key: "hint" }, "This story is shared with members of this circle. You can edit it later."),
    ]),
    h("div", { className: "journey-fields", key: "family" }, [
      h("label", { className: "journey-field", key: "relative" }, [
        h("span", { key: "label" }, "Connect them to"),
        h("select", { key: "input", value: draft.relative_id, onChange: update("relative_id") }, [
          h("option", { key: "none", value: "" }, "I'll connect them later"),
          ...people.map((person) => h("option", { key: person.id, value: person.id }, person.full_name)),
        ]),
      ]),
      draft.relative_id ? h("label", { className: "journey-field", key: "relationship" }, [
        h("span", { key: "label" }, `How is ${draft.full_name.trim() || "this person"} related to them?`),
        h("select", { key: "input", value: draft.relationship_type, onChange: update("relationship_type") }, [
          h("option", { key: "child", value: "child_of" }, "Their child"),
          h("option", { key: "parent", value: "parent_of" }, "Their parent"),
          h("option", { key: "spouse", value: "spouse_of" }, "Their spouse"),
          h("option", { key: "sibling", value: "sibling_of" }, "Their sibling"),
        ]),
      ]) : null,
      h("div", { className: "journey-review", key: "review" }, [
        h("strong", { key: "name" }, draft.full_name.trim()),
        h("span", { key: "details" }, [draft.birth_place, draft.occupation, draft.hobbies].filter(Boolean).join(" · ") || "A new story begins here"),
      ]),
    ]),
  ];
  return h("div", { className: "journey-backdrop", onMouseDown: (event) => { if (event.target === event.currentTarget && !busy) onClose(); } },
    h("section", { className: "person-journey", role: "dialog", "aria-modal": "true", "aria-labelledby": "journey-title", ref: dialogRef }, [
      h("div", { className: "journey-head", key: "head" }, [
        h("span", { className: "journey-eyebrow", key: "eyebrow" }, "Viraasat · A new story"),
        h("button", { className: "journey-close", key: "close", type: "button", onClick: onClose, disabled: busy, "aria-label": saved ? "Close" : "Close without saving" }, "×"),
      ]),
      saved ? h("div", { className: "journey-complete", key: "complete" }, [
        h("div", { className: "journey-complete-mark", key: "mark", "aria-hidden": "true" }, "✦"),
        h("h2", { id: "journey-title", key: "title", ref: completionHeadingRef, tabIndex: -1 }, `${saved.person.full_name} is part of the story.`),
        h("p", { key: "description" }, saved.linkError
          ? "Their profile was saved. The family connection needs another try; you can retry it here or link them later."
          : saved.graphError ? "Their profile was saved. Refresh the tree to see their new place." : "Their profile is saved. The tree will bring their new place into view."),
        saved.linkError ? h("p", { className: "journey-error", key: "link-error", role: "alert" }, saved.linkError) : null,
        saved.linkError ? h("button", { className: "journey-primary", key: "retry", type: "button", onClick: retryLink, disabled: busy }, busy ? "Trying again…" : "Retry family connection") : null,
        h("button", { className: "journey-secondary", key: "done", type: "button", onClick: () => onReveal(saved.person.id), disabled: busy }, saved.graphError ? "Close" : saved.linkError ? "View saved profile" : "See their place in the tree"),
      ]) : h("div", { className: "journey-body", key: "body" }, [
        h("ol", { className: "journey-steps", key: "steps", "aria-label": "Add family member progress" },
          PERSON_JOURNEY_STEPS.map((item, index) => h("li", { key: item.name, className: index === step ? "current" : index < step ? "done" : "" }, `${index + 1}. ${item.name}`))),
        h("div", { className: "journey-stage", key: step }, [
          h("h2", { id: "journey-title", key: "title", ref: stepHeadingRef, tabIndex: -1 }, PERSON_JOURNEY_STEPS[step].title),
          h("p", { className: "journey-prompt", key: "prompt" }, PERSON_JOURNEY_STEPS[step].prompt),
          stepContent[step],
        ]),
        error ? h("p", { className: "journey-error", role: "alert", key: "error" }, error) : null,
        h("div", { className: "journey-actions", key: "actions" }, [
          step ? h("button", { className: "journey-secondary", key: "back", type: "button", onClick: () => { setError(""); setStep(step - 1); }, disabled: busy }, "Back") : h("span", { key: "space" }),
          h("button", { className: "journey-primary", key: "forward", type: "button", onClick: step === PERSON_JOURNEY_STEPS.length - 1 ? save : next, disabled: busy }, busy ? "One moment…" : step === PERSON_JOURNEY_STEPS.length - 1 ? "Add to our family" : "Continue"),
        ]),
      ]),
    ])
  );
}

function App() {
  const [users, setUsers] = useState([]);
  const [activeUserId, setActiveUserId] = useState(localStorage.getItem("activeUserId") || "");
  const [authToken, setAuthToken] = useState(localStorage.getItem("authToken") || "");
  const [authState, setAuthState] = useState("checking");
  const [runtimeConfig, setRuntimeConfig] = useState(null);
  const [circles, setCircles] = useState([]);
  const [selectedCircle, setSelectedCircle] = useState("");
  const [members, setMembers] = useState([]);
  const [persons, setPersons] = useState([]);
  const [relationships, setRelationships] = useState([]);
  const [changeRequests, setChangeRequests] = useState([]);
  const [contextEvents, setContextEvents] = useState([]);
  const [timeline, setTimeline] = useState([]);
  const [circleInvitations, setCircleInvitations] = useState([]);
  const [myInvitations, setMyInvitations] = useState([]);
  const [auditLogs, setAuditLogs] = useState([]);
  const [timelineScope, setTimelineScope] = useState("person");
  const [timelineFromDate, setTimelineFromDate] = useState("");
  const [timelineToDate, setTimelineToDate] = useState("");
  const [timelineEventTypes, setTimelineEventTypes] = useState("");
  const [personMedia, setPersonMedia] = useState([]);
  const [mediaPreviewAssetByPersonId, setMediaPreviewAssetByPersonId] = useState({});
  const [mediaAccessTicket, setMediaAccessTicket] = useState(null);
  const [mediaUploadBusy, setMediaUploadBusy] = useState(false);
  const [personPlaces, setPersonPlaces] = useState([]);
  const [selectedPlace, setSelectedPlace] = useState(null);
  const [migrationGeoJson, setMigrationGeoJson] = useState(null);
  const [subgraphMigrationGeoJson, setSubgraphMigrationGeoJson] = useState(null);
  const [subgraphMigrationDates, setSubgraphMigrationDates] = useState([]);
  const [subgraphMigrationIndex, setSubgraphMigrationIndex] = useState(0);
  const [isSubgraphMigrationPlaying, setIsSubgraphMigrationPlaying] = useState(false);
  const [discussionThreadId, setDiscussionThreadId] = useState("");
  const [discussionMessages, setDiscussionMessages] = useState([]);
  const [personRevisions, setPersonRevisions] = useState([]);
  const [personJourneyOpen, setPersonJourneyOpen] = useState(false);
  const [newArrivalId, setNewArrivalId] = useState("");
  const [inviteCopied, setInviteCopied] = useState(false);
  const [subgraph, setSubgraph] = useState(null);
  const [lastRoot, setLastRoot] = useState("");
  const [lastDirection, setLastDirection] = useState("descendants");
  const [lastDepth, setLastDepth] = useState(2);
  const [lastMode, setLastMode] = useState("lineage");
  const [lastLayoutMode, setLastLayoutMode] = useState("hierarchy");
  const [lastLateralTypes, setLastLateralTypes] = useState("spouse_of,sibling_of,cousin_of");
  const [lastLateralDepth, setLastLateralDepth] = useState(1);
  const [status, setStatus] = useState("");
  const [circleDataLoading, setCircleDataLoading] = useState(false);
  const [circleSupplementalLoading, setCircleSupplementalLoading] = useState(false);
  const [personMediaLoading, setPersonMediaLoading] = useState(false);
  const [personPlacesLoading, setPersonPlacesLoading] = useState(false);
  const [personRevisionsLoading, setPersonRevisionsLoading] = useState(false);
  const [discussionLoading, setDiscussionLoading] = useState(false);
  const [leftOpen, setLeftOpen] = useState(true);
  const [rightOpen, setRightOpen] = useState(true);
  const [timeTimelineOpen, setTimeTimelineOpen] = useState(true);
  const [selectedPersonId, setSelectedPersonId] = useState("");
  const [highlightedNodeIds, setHighlightedNodeIds] = useState([]);
  const [highlightedEdgeKeys, setHighlightedEdgeKeys] = useState([]);
  const [zoom, setZoom] = useState(1);
  const [graphRenderStats, setGraphRenderStats] = useState(null);
  const [editingRelationshipId, setEditingRelationshipId] = useState("");
  const [peopleListExpanded, setPeopleListExpanded] = useState(false);
  const [relationshipListExpanded, setRelationshipListExpanded] = useState(false);
  const [mediaPanelActivated, setMediaPanelActivated] = useState(false);
  const [discussionPanelActivated, setDiscussionPanelActivated] = useState(false);
  const [placesPanelActivated, setPlacesPanelActivated] = useState(false);
  const [revisionsPanelActivated, setRevisionsPanelActivated] = useState(false);
  const [personSearchQuery, setPersonSearchQuery] = useState("");
  const [personSearchFocused, setPersonSearchFocused] = useState(false);
  const [personSearchActiveIndex, setPersonSearchActiveIndex] = useState(0);
  const [graphRootPersonId, setGraphRootPersonId] = useState("");
  const [editRelationshipDraft, setEditRelationshipDraft] = useState({
    from_person_id: "",
    to_person_id: "",
    relationship_type: "parent_of",
  });
  const graphViewportRef = useRef(null);
  const personSearchInputRef = useRef(null);
  const graphRenderStartedAtRef = useRef(0);
  const migrationTimerRef = useRef(null);
  const prevTimeTimelineOpenRef = useRef(true);
  const pendingTimelineViewportAnchorRef = useRef(null);
  const discussionThreadIdRef = useRef("");
  const discussionSelectionKeyRef = useRef("");
  const activeDiscussionThreadKeyRef = useRef("");
  const selectedCircleRef = useRef(selectedCircle);
  const selectedPersonIdRef = useRef(selectedPersonId);
  const circlesRequestRef = useRef(0);
  const circleDataRequestRef = useRef(0);
  const mediaPreviewsRequestRef = useRef(0);
  const managementDataRequestRef = useRef(0);
  const myInvitesRequestRef = useRef(0);
  const personMediaRequestRef = useRef(0);
  const personPlacesRequestRef = useRef(0);
  const personRevisionsRequestRef = useRef(0);
  const discussionLoadRequestRef = useRef(0);
  const graphRequestRef = useRef(0);
  const graphAbortControllerRef = useRef(null);
  selectedCircleRef.current = selectedCircle;
  selectedPersonIdRef.current = selectedPersonId;

  const headers = useMemo(() => {
    if (authToken) return { "Content-Type": "application/json", Authorization: `Bearer ${authToken}` };
    return { "Content-Type": "application/json" };
  }, [authToken]);

  const activeMediaTicket = mediaAccessTicket && mediaAccessTicket.circle_id === selectedCircle
    ? mediaAccessTicket.ticket
    : "";
  const mediaPreviewByPersonId = useMemo(() => {
    if (!activeMediaTicket || !selectedCircle) return {};
    const previews = {};
    Object.entries(mediaPreviewAssetByPersonId).forEach(([personId, assetId]) => {
      previews[personId] = `/circles/${selectedCircle}/media/${assetId}/download?ticket=${encodeURIComponent(activeMediaTicket)}&v=${encodeURIComponent(assetId)}`;
    });
    return previews;
  }, [activeMediaTicket, mediaPreviewAssetByPersonId, selectedCircle]);
  const mediaAccessNeeded = mediaPanelActivated || Object.keys(mediaPreviewAssetByPersonId).length > 0;

  const personOptions = useMemo(() => persons.map((p) => ({ value: p.id, label: p.full_name })), [persons]);
  const personNameById = useMemo(
    () => Object.fromEntries(persons.map((person) => [person.id, person.full_name])),
    [persons]
  );
  const effectiveGraphRootPersonId = graphRootPersonId || personOptions[0]?.value || "";
  const effectiveGraphRootPersonName = personNameById[effectiveGraphRootPersonId] || "No root selected";
  const personSearchIndex = useMemo(() => buildPersonSearchIndex(persons), [persons]);
  const personSearchResults = useMemo(
    () => searchPersonIndex(personSearchIndex, personSearchQuery, PERSON_SEARCH_RESULT_LIMIT),
    [personSearchIndex, personSearchQuery]
  );
  const visiblePeopleRows = peopleListExpanded ? persons : persons.slice(0, PANEL_ROW_LIMIT);
  const visibleRelationshipRows = relationshipListExpanded ? relationships : relationships.slice(0, PANEL_ROW_LIMIT);
  const userOptions = useMemo(
    () => users.map((u) => ({ value: u.id, label: `${u.display_name} (${u.id.slice(0, 8)})` })),
    [users]
  );
  const activeUserName = useMemo(() => users.find((u) => u.id === activeUserId)?.display_name || "", [users, activeUserId]);
  const managedAuthAvailable = runtimeConfig?.auth_mode === "supabase";
  const reviewAuthAvailable = runtimeConfig?.review_auth_enabled === true;
  const isAuthenticated = authState === "signed_in" && Boolean(authToken);
  const personPanelLoading = personMediaLoading || personPlacesLoading || personRevisionsLoading || discussionLoading;
  const workspaceStatus = status || (
    !runtimeConfig || authState === "checking"
      ? "Checking security mode"
      : (authState === "unavailable"
          ? "Authentication locked"
          : (!isAuthenticated
              ? "Sign in to continue"
              : (circleDataLoading
                  ? "Loading selected circle"
                  : (circleSupplementalLoading
                      ? "Loading collaboration details"
                      : (personPanelLoading ? "Loading open person panel" : (selectedCircle ? "Ready" : "Create or select a circle"))))))
  );
  const authModeClass = !runtimeConfig ? "checking" : (managedAuthAvailable ? "verified" : (reviewAuthAvailable ? "review" : "disabled"));
  const authModeLabel = !runtimeConfig
    ? "Checking security mode"
    : managedAuthAvailable ? "Private archive · signed-in accounts" : (reviewAuthAvailable
        ? `Review auth · no identity proof · ${runtimeConfig.environment}`
        : `Authentication locked · ${runtimeConfig.environment}`);
  const activeMembership = useMemo(
    () => members.find((m) => m.user_id === activeUserId) || null,
    [members, activeUserId]
  );
  const activeCircleRole = activeMembership ? activeMembership.role : null;
  const canManageMembers = activeCircleRole === "owner";
  const canEditRecords = activeCircleRole === "owner" || activeCircleRole === "editor";
  const profileFieldAccessProps = canEditRecords ? {} : { readOnly: true, "aria-readonly": "true" };
  const selectedPerson = useMemo(
    () => persons.find((p) => p.id === selectedPersonId) || (subgraph?.persons || []).find((p) => p.id === selectedPersonId) || null,
    [persons, subgraph, selectedPersonId]
  );
  const highlightedNodeSet = useMemo(() => new Set(highlightedNodeIds), [highlightedNodeIds]);
  const highlightedEdgeSet = useMemo(() => new Set(highlightedEdgeKeys), [highlightedEdgeKeys]);
  const isLargeSubgraph = Boolean(
    subgraph && usesLargeGraphMode(subgraph.persons || [], subgraph.relationships || [])
  );
  const externalMapUrl = selectedPlace ? buildExternalMapUrl(selectedPlace) : null;
  const handleGraphRenderComplete = useCallback((detail) => {
    graphRenderStartedAtRef.current = 0;
    setGraphRenderStats(detail);
    if (detail.large_graph_mode) window.requestAnimationFrame(fitGraph);
  }, []);
  const subgraphMigrationView = useMemo(() => {
    const features = (subgraphMigrationGeoJson && subgraphMigrationGeoJson.features) || [];
    const points = features.filter((f) => f.geometry && f.geometry.type === "Point");
    const lines = features.filter((f) => f.geometry && f.geometry.type === "LineString");
    if (!points.length && !lines.length) {
      return { points: [], lines: [], width: 560, height: 240 };
    }
    const allCoords = [];
    points.forEach((f) => {
      if (Array.isArray(f.geometry.coordinates)) allCoords.push(f.geometry.coordinates);
    });
    lines.forEach((f) => {
      if (Array.isArray(f.geometry.coordinates)) {
        f.geometry.coordinates.forEach((c) => allCoords.push(c));
      }
    });
    const lngs = allCoords.map((c) => Number(c[0]));
    const lats = allCoords.map((c) => Number(c[1]));
    const minLng = Math.min(...lngs);
    const maxLng = Math.max(...lngs);
    const minLat = Math.min(...lats);
    const maxLat = Math.max(...lats);
    const width = 560;
    const height = 240;
    const pad = 20;
    const spanLng = Math.max(0.0001, maxLng - minLng);
    const spanLat = Math.max(0.0001, maxLat - minLat);
    function project(coord) {
      const x = pad + ((Number(coord[0]) - minLng) / spanLng) * (width - pad * 2);
      const y = pad + (1 - ((Number(coord[1]) - minLat) / spanLat)) * (height - pad * 2);
      return [x, y];
    }
    const projectedPoints = points.map((f, i) => {
      const [x, y] = project(f.geometry.coordinates);
      return {
        key: `p-${i}`,
        x,
        y,
        label: (f.properties && (f.properties.place_name || f.properties.full_name)) || "Place",
        fromDate: (f.properties && f.properties.from_date) || "",
        personName: (f.properties && f.properties.full_name) || "",
      };
    });
    const projectedLines = lines.map((f, i) => {
      const coords = (f.geometry.coordinates || []).map(project);
      return {
        key: `l-${i}`,
        d: coords.length ? `M ${coords.map((c) => `${c[0]} ${c[1]}`).join(" L ")}` : "",
        label: (f.properties && f.properties.full_name) || "Route",
      };
    }).filter((l) => l.d);
    return { points: projectedPoints, lines: projectedLines, width, height };
  }, [subgraphMigrationGeoJson]);
  const lineageJourneyItems = useMemo(() => {
    const rows = (subgraph?.persons || []).map((p) => ({
      id: p.id,
      name: p.full_name || p.id.slice(0, 8),
      birthDate: p.birth_date || "",
      deathDate: p.death_date || "",
      birthPlace: p.birth_place || "",
      badge: p.occupation || p.religion || "Ancestor",
      worldEvents: (contextEvents || [])
        .filter((evt) => {
          const year = (p.birth_date || p.death_date || "").slice(0, 4);
          return year && (evt.date || "").startsWith(year);
        })
        .slice(0, 2)
        .map((evt) => evt.title),
      sortDate: p.birth_date || p.death_date || "9999-12-31",
    }));
    rows.sort((a, b) => a.sortDate.localeCompare(b.sortDate) || a.name.localeCompare(b.name));
    return rows.slice(0, 12);
  }, [subgraph, contextEvents]);
  const historicalTimelineItems = useMemo(() => {
    return (contextEvents || [])
      .map((evt) => ({
        id: evt.id,
        yearLabel: evt.date ? evt.date.slice(0, 4) : "Era",
        title: evt.title || "Untitled event",
        description: evt.description || "No event description provided.",
      }))
      .sort((a, b) => a.yearLabel.localeCompare(b.yearLabel))
      .slice(0, 40);
  }, [contextEvents]);

  function setActiveUser(id) {
    setActiveUserId(id);
    localStorage.setItem("activeUserId", id || "");
  }

  async function revokeTokenRemotely(token) {
    if (!token) return true;
    try {
      const response = await fetch("/auth/logout", {
        method: "POST",
        headers: { Authorization: `Bearer ${token}` },
      });
      return response.ok || response.status === 401;
    } catch (_) {
      return false;
    }
  }

  async function signOutCurrentUser() {
    const revocationConfirmed = await revokeTokenRemotely(authToken);
    setToken("");
    setPersonJourneyOpen(false);
    setInviteCopied(false);
    if (managedAuthAvailable) {
      setActiveUser("");
      setUsers([]);
    }
    setStatus(revocationConfirmed
      ? "Signed out"
      : "Signed out locally. Server revocation could not be confirmed.");
  }

  async function changeActiveUser(id) {
    if (id === activeUserId) return;
    const revocationConfirmed = await revokeTokenRemotely(authToken);
    setToken("");
    setActiveUserId(id);
    localStorage.setItem("activeUserId", id || "");
    setStatus(revocationConfirmed
      ? "User changed. Sign in for the selected user."
      : "User changed and local access was cleared. Server revocation could not be confirmed.");
  }

  function setToken(token) {
    const nextToken = token || "";
    setAuthToken(nextToken);
    setAuthState(nextToken ? "signed_in" : "signed_out");
    if (nextToken) localStorage.setItem("authToken", nextToken);
    else localStorage.removeItem("authToken");
  }

  function selectCircle(circleId) {
    const nextCircleId = circleId || "";
    if (selectedCircleRef.current !== nextCircleId) {
      setPersonJourneyOpen(false);
      setNewArrivalId("");
      selectedPersonIdRef.current = "";
      setSelectedPersonId("");
      clearSelectedPersonPanelData("");
      setPersonSearchQuery("");
      setGraphRootPersonId("");
    }
    selectedCircleRef.current = nextCircleId;
    setSelectedCircle(nextCircleId);
  }

  function selectPerson(personId) {
    const nextPersonId = personId || "";
    if (selectedPersonIdRef.current !== nextPersonId) {
      const selectionKey = selectedCircleRef.current && nextPersonId
        ? `${selectedCircleRef.current}:${nextPersonId}`
        : "";
      clearSelectedPersonPanelData(selectionKey);
    }
    selectedPersonIdRef.current = nextPersonId;
    setSelectedPersonId(nextPersonId);
  }

  function clearSelectedPersonPanelData(selectionKey = "") {
    personMediaRequestRef.current += 1;
    personPlacesRequestRef.current += 1;
    personRevisionsRequestRef.current += 1;
    discussionLoadRequestRef.current += 1;
    discussionSelectionKeyRef.current = selectionKey;
    setActiveDiscussionThread("");
    setDiscussionMessages([]);
    setPersonMedia([]);
    setPersonPlaces([]);
    setSelectedPlace(null);
    setMigrationGeoJson(null);
    setPersonRevisions([]);
    setPersonMediaLoading(false);
    setPersonPlacesLoading(false);
    setPersonRevisionsLoading(false);
    setDiscussionLoading(false);
  }

  function requestIsCurrent(requestRef, requestId, signal) {
    return !signal?.aborted && requestRef.current === requestId;
  }

  function cancelGraphRequest() {
    graphRequestRef.current += 1;
    if (graphAbortControllerRef.current) graphAbortControllerRef.current.abort();
    graphAbortControllerRef.current = null;
    graphRenderStartedAtRef.current = 0;
  }

  async function fetchSubgraph({ circleId, root, direction, depth, mode, lateralTypes, lateralDepth }) {
    cancelGraphRequest();
    const requestId = graphRequestRef.current;
    const controller = new AbortController();
    graphAbortControllerRef.current = controller;
    graphRenderStartedAtRef.current = performance.now();
    setGraphRenderStats(null);
    const query = new URLSearchParams({
      root_person_id: root,
      direction,
      depth: String(depth),
      mode,
      lateral_types: lateralTypes,
      lateral_depth: String(lateralDepth),
    });
    try {
      const data = await requestJson(`/circles/${encodeURIComponent(circleId)}/graph/subgraph?${query}`, {
        headers,
        signal: controller.signal,
      });
      if (
        !requestIsCurrent(graphRequestRef, requestId, controller.signal) ||
        selectedCircleRef.current !== circleId
      ) return null;
      return data;
    } catch (error) {
      if (requestIsCurrent(graphRequestRef, requestId)) {
        graphRenderStartedAtRef.current = 0;
        setGraphRenderStats(null);
      }
      if (error?.name === "AbortError") return null;
      throw error;
    } finally {
      if (graphAbortControllerRef.current === controller) graphAbortControllerRef.current = null;
    }
  }

  function reportRequestError(error) {
    if (error?.name === "AbortError") return;
    setStatus(error?.message || "Request failed");
  }

  function clearCircleData() {
    clearSelectedPersonPanelData("");
    setMembers([]);
    setPersons([]);
    setRelationships([]);
    setChangeRequests([]);
    setContextEvents([]);
    setCircleInvitations([]);
    setAuditLogs([]);
    setTimeline([]);
    setMediaPreviewAssetByPersonId({});
    setPeopleListExpanded(false);
    setRelationshipListExpanded(false);
    setMediaPanelActivated(false);
    setDiscussionPanelActivated(false);
    setPlacesPanelActivated(false);
    setRevisionsPanelActivated(false);
    setPersonSearchQuery("");
    setPersonSearchFocused(false);
    setPersonSearchActiveIndex(0);
    setGraphRootPersonId("");
  }

  function setActiveDiscussionThread(threadId, selectionKey = "") {
    const nextThreadId = threadId || "";
    discussionThreadIdRef.current = nextThreadId;
    activeDiscussionThreadKeyRef.current = nextThreadId ? selectionKey : "";
    setDiscussionThreadId(nextThreadId);
  }

  function appendDiscussionMessage(message) {
    if (!message || !message.id) return;
    setDiscussionMessages((previous) => (
      previous.some((item) => item.id === message.id)
        ? previous
        : previous.concat([message])
    ));
  }

  function responseErrorMessage(response, body, fallback) {
    const message = formatApiErrorDetail(body?.detail, fallback);
    const requestId = response.headers.get("X-Request-Id");
    return response.status >= 500 && requestId
      ? `${message} (reference ${requestId})`
      : message;
  }

  async function requestJson(url, options = {}) {
    const res = await fetch(url, options);
    if (!res.ok) {
      const body = await res.json().catch(() => ({ detail: "Request failed" }));
      if (res.status === 401) {
        setToken("");
        throw new Error("Your session expired. Sign in again.");
      }
      throw new Error(responseErrorMessage(res, body, "Request failed"));
    }
    return res.json();
  }

  async function requestCircleAccessTicket(circleId, scope, signal) {
    return requestJson(`/circles/${circleId}/access-tickets`, {
      method: "POST",
      headers,
      body: JSON.stringify({ scope }),
      signal,
    });
  }

  function findPathFromRoot(targetId) {
    if (!subgraph || !lastRoot || !targetId) return { nodes: [], edges: [] };
    const prev = {};
    const q = [lastRoot];
    const visited = new Set([lastRoot]);
    while (q.length) {
      const cur = q.shift();
      if (cur === targetId) break;
      (subgraph.relationships || []).forEach((edge) => {
        if (edge.from_person_id === cur && !visited.has(edge.to_person_id)) {
          visited.add(edge.to_person_id);
          prev[edge.to_person_id] = cur;
          q.push(edge.to_person_id);
        }
      });
    }
    if (!visited.has(targetId)) return { nodes: [targetId], edges: [] };
    const nodes = [];
    const edges = [];
    let cur = targetId;
    while (cur !== undefined) {
      nodes.push(cur);
      const parent = prev[cur];
      if (parent !== undefined) {
        edges.push(edgeKey(parent, cur));
      }
      cur = parent;
    }
    return { nodes: nodes.reverse(), edges: edges.reverse() };
  }

  function applyPersonFocus(personId) {
    selectPerson(personId);
    const path = findPathFromRoot(personId);
    setHighlightedNodeIds(path.nodes.length ? path.nodes : [personId]);
    setHighlightedEdgeKeys(path.edges);
  }

  function openPersonProfile(personId) {
    applyPersonFocus(personId);
    setRightOpen(true);
  }

  function choosePersonSearchResult(person) {
    if (!person?.id) return;
    openPersonProfile(person.id);
    setGraphRootPersonId(person.id);
    setPersonSearchQuery("");
    setPersonSearchFocused(false);
    setPersonSearchActiveIndex(0);
    setStatus(`Opened profile for ${person.full_name || "family member"}`);
  }

  function focusPersonFinder() {
    setPersonSearchFocused(true);
    personSearchInputRef.current?.focus();
    personSearchInputRef.current?.scrollIntoView({ block: "center", behavior: "smooth" });
  }

  function handlePersonSearchKeyDown(event) {
    if (event.key === "Escape") {
      event.preventDefault();
      setPersonSearchQuery("");
      setPersonSearchFocused(false);
      return;
    }
    if (!personSearchResults.length) return;
    if (event.key === "ArrowDown" || event.key === "ArrowUp") {
      event.preventDefault();
      const direction = event.key === "ArrowDown" ? 1 : -1;
      setPersonSearchActiveIndex((current) => (
        (current + direction + personSearchResults.length) % personSearchResults.length
      ));
      return;
    }
    if (event.key === "Enter") {
      event.preventDefault();
      choosePersonSearchResult(personSearchResults[Math.min(personSearchActiveIndex, personSearchResults.length - 1)]);
    }
  }

  function fitGraph() {
    const el = graphViewportRef.current;
    if (!el) return;
    const svg = el.querySelector(".d3-graph-canvas");
    const graphWidth = Number(svg?.getAttribute("data-base-width")) || 1000;
    const graphHeight = Number(svg?.getAttribute("data-base-height")) || 600;
    const minZoom = svg?.getAttribute("data-large-graph") === "true" ? LARGE_GRAPH_MIN_ZOOM : 0.35;
    const pad = 60;
    const nextZoom = Math.max(minZoom, Math.min(1.8, Math.min((el.clientWidth - pad) / graphWidth, (el.clientHeight - pad) / graphHeight)));
    setZoom(nextZoom);
    el.scrollTop = 0;
    el.scrollLeft = 0;
  }

  function setTimeTimelineOpenAnchored(nextOpen) {
    const viewport = graphViewportRef.current;
    if (viewport && lastLayoutMode === "time_aligned") {
      pendingTimelineViewportAnchorRef.current = {
        centerX: viewport.scrollLeft + viewport.clientWidth / 2,
        centerY: viewport.scrollTop + viewport.clientHeight / 2,
      };
    }
    setTimeTimelineOpen(nextOpen);
  }

  async function loadUsers() {
    if (!reviewAuthAvailable) {
      setUsers([]);
      return;
    }
    const data = await requestJson("/users");
    setUsers(data);
    const rememberedUserStillExists = data.some((user) => user.id === activeUserId);
    if (!rememberedUserStillExists) {
      setActiveUser(data.length ? data[0].id : "");
    }
  }

  async function bootstrapAuthentication() {
    const config = await requestJson("/runtime-config");
    setRuntimeConfig(config);
    if (config.auth_mode === "supabase") {
      const handoff = await requestJson("/auth/managed/session");
      const token = handoff.access_token || authToken;
      if (new URLSearchParams(window.location.search).has("signin")) {
        setStatus("Sign-in did not complete. Please try again.");
        window.history.replaceState(null, "", "/");
      }
      if (token) {
        try {
          const user = await requestJson("/auth/me", { headers: { Authorization: `Bearer ${token}` } });
          setUsers([user]);
          setActiveUser(user.id);
          setToken(token);
          return;
        } catch (_) {
          setStatus("Your session could not be restored. Please sign in again.");
        }
      }
      setToken("");
      setUsers([]);
      setActiveUser("");
      setAuthState("signed_out");
      return;
    }
    if (!config.review_auth_enabled) {
      setAuthToken("");
      localStorage.removeItem("authToken");
      setUsers([]);
      setActiveUserId("");
      localStorage.removeItem("activeUserId");
      setAuthState("unavailable");
      setStatus(config.warning);
      return;
    }

    const data = await requestJson("/users");
    setUsers(data);

    if (!authToken) {
      const fallbackUserId = data.some((user) => user.id === activeUserId)
        ? activeUserId
        : (data[0]?.id || "");
      setActiveUserId(fallbackUserId);
      localStorage.setItem("activeUserId", fallbackUserId);
      setAuthState("signed_out");
      return;
    }

    try {
      const response = await fetch("/auth/me", {
        headers: { Authorization: `Bearer ${authToken}` },
      });
      if (!response.ok) {
        setToken("");
        const fallbackUserId = data.some((user) => user.id === activeUserId)
          ? activeUserId
          : (data[0]?.id || "");
        setActiveUserId(fallbackUserId);
        localStorage.setItem("activeUserId", fallbackUserId);
        setStatus("Your saved session expired. Sign in again.");
        return;
      }
      const authenticatedUser = await response.json();
      setActiveUserId(authenticatedUser.id);
      localStorage.setItem("activeUserId", authenticatedUser.id);
      setAuthState("signed_in");
      setStatus("Session restored");
    } catch (_) {
      setToken("");
      setStatus("Could not restore your session. Sign in again.");
    }
  }

  async function loginAsActiveUser() {
    if (managedAuthAvailable) {
      window.location.assign("/auth/managed/start");
      return;
    }
    if (!reviewAuthAvailable) {
      setStatus(runtimeConfig?.warning || "Authentication is unavailable");
      return;
    }
    if (!activeUserId) {
      setStatus("Select a user first");
      return;
    }
    const data = await requestJson("/auth/login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ user_id: activeUserId }),
    });
    if (data.user && data.user.id && data.user.id !== activeUserId) {
      setActiveUserId(data.user.id);
      localStorage.setItem("activeUserId", data.user.id);
    }
    setToken(data.access_token);
    setStatus("Signed in");
  }

  async function loadCircles(signal) {
    const requestId = ++circlesRequestRef.current;
    if (!isAuthenticated) {
      setCircles([]);
      selectCircle("");
      return;
    }
    const data = await requestJson("/circles", { headers, signal });
    if (!requestIsCurrent(circlesRequestRef, requestId, signal)) return;
    setCircles(data);
    if (!data.length) return selectCircle("");
    const activeCircleId = selectedCircleRef.current;
    const exists = data.some((c) => c.id === activeCircleId);
    if (!activeCircleId || !exists) selectCircle(data[0].id);
  }

  async function loadCircleData(circleId, signal, onCoreReady) {
    const requestId = ++circleDataRequestRef.current;
    if (!isAuthenticated || !circleId) {
      clearCircleData();
      return;
    }
    const [m, p, r] = await Promise.all([
      requestJson(`/circles/${circleId}/members`, { headers, signal }),
      requestJson(`/circles/${circleId}/persons`, { headers, signal }),
      requestJson(`/circles/${circleId}/relationships`, { headers, signal }),
    ]);
    if (!requestIsCurrent(circleDataRequestRef, requestId, signal) || selectedCircleRef.current !== circleId) return;
    setMembers(m); setPersons(p); setRelationships(r);
    if (typeof onCoreReady === "function") onCoreReady();

    const previewRequestId = ++mediaPreviewsRequestRef.current;
    const supplementalResults = await Promise.allSettled([
      requestJson(`/circles/${circleId}/change-requests`, { headers, signal }),
      requestJson(`/circles/${circleId}/context-events`, { headers, signal }),
      requestJson(`/circles/${circleId}/media-previews`, { headers, signal }),
    ]);
    if (!requestIsCurrent(circleDataRequestRef, requestId, signal) || selectedCircleRef.current !== circleId) return;
    const [changeRequestsResult, contextEventsResult, mediaPreviewsResult] = supplementalResults;
    if (changeRequestsResult.status === "fulfilled") setChangeRequests(changeRequestsResult.value);
    if (contextEventsResult.status === "fulfilled") setContextEvents(contextEventsResult.value);
    if (mediaPreviewsResult.status === "fulfilled") {
      applyMediaPreviews(circleId, mediaPreviewsResult.value, previewRequestId, signal);
    }
    const failedSupplement = supplementalResults.find((result) => result.status === "rejected");
    if (failedSupplement && failedSupplement.reason?.name !== "AbortError") {
      throw new Error(`Core family data loaded; a collaboration panel could not refresh: ${failedSupplement.reason?.message || "request failed"}`);
    }
  }

  function applyMediaPreviews(circleId, rows, requestId, signal) {
    if (!requestIsCurrent(mediaPreviewsRequestRef, requestId, signal) || selectedCircleRef.current !== circleId) return;
    const previews = {};
    (rows || []).forEach((preview) => {
      previews[preview.person_id] = preview.asset_id;
    });
    setMediaPreviewAssetByPersonId(previews);
  }

  async function loadMediaPreviews(circleId, signal) {
    const requestId = ++mediaPreviewsRequestRef.current;
    if (!circleId) return applyMediaPreviews(circleId, [], requestId, signal);
    const rows = await requestJson(`/circles/${circleId}/media-previews`, { headers, signal });
    applyMediaPreviews(circleId, rows, requestId, signal);
  }

  async function loadManagementData(circleId, signal) {
    const requestId = ++managementDataRequestRef.current;
    if (!isAuthenticated || !circleId) {
      setCircleInvitations([]);
      setAuditLogs([]);
      return;
    }
    const [invitesResult, auditResult] = await Promise.allSettled([
      requestJson(`/circles/${circleId}/invitations`, { headers, signal }),
      requestJson(`/circles/${circleId}/audit-logs?limit=60`, { headers, signal }),
    ]);
    if (!requestIsCurrent(managementDataRequestRef, requestId, signal) || selectedCircleRef.current !== circleId) return;
    setCircleInvitations(invitesResult.status === "fulfilled" ? invitesResult.value : []);
    setAuditLogs(auditResult.status === "fulfilled" ? auditResult.value : []);
  }

  async function loadMyInvites(signal) {
    const requestId = ++myInvitesRequestRef.current;
    if (!isAuthenticated) {
      setMyInvitations([]);
      return;
    }
    const rows = await requestJson("/invitations?status=pending", { headers, signal });
    if (!requestIsCurrent(myInvitesRequestRef, requestId, signal)) return;
    setMyInvitations(rows);
  }

  useEffect(() => { bootstrapAuthentication().catch((e) => {
    setAuthToken("");
    localStorage.removeItem("authToken");
    setAuthState("unavailable");
    setStatus(`Could not determine the deployment security mode: ${e.message}`);
  }); }, []);
  useEffect(() => {
    const controller = new AbortController();
    selectCircle("");
    setSubgraph(null);
    setTimeline([]);
    selectPerson("");
    setHighlightedNodeIds([]);
    setHighlightedEdgeKeys([]);
    loadCircles(controller.signal).catch(reportRequestError);
    return () => controller.abort();
  }, [activeUserId, authToken, authState]);
  useEffect(() => {
    const controller = new AbortController();
    let loadTimer = null;
    let managementTimer = null;
    cancelGraphRequest();
    clearCircleData();
    setSubgraph(null);
    setLastRoot("");
    setGraphRenderStats(null);
    setHighlightedNodeIds([]);
    setHighlightedEdgeKeys([]);
    const shouldLoad = isAuthenticated && Boolean(selectedCircle);
    setCircleDataLoading(shouldLoad);
    setCircleSupplementalLoading(shouldLoad);
    if (shouldLoad) {
      loadTimer = window.setTimeout(() => {
        loadCircleData(selectedCircle, controller.signal, () => {
          if (controller.signal.aborted) return;
          setCircleDataLoading(false);
          managementTimer = window.setTimeout(() => {
            loadManagementData(selectedCircle, controller.signal).catch(reportRequestError);
          }, MANAGEMENT_DEFER_MS);
        })
          .catch(reportRequestError)
          .finally(() => {
            if (!controller.signal.aborted) {
              setCircleDataLoading(false);
              setCircleSupplementalLoading(false);
            }
          });
      }, SELECTION_STABILIZE_MS);
    }
    return () => {
      if (loadTimer) window.clearTimeout(loadTimer);
      if (managementTimer) window.clearTimeout(managementTimer);
      controller.abort();
      cancelGraphRequest();
    };
  }, [activeUserId, authToken, authState, selectedCircle]);
  useEffect(() => {
    const controller = new AbortController();
    setMyInvitations([]);
    loadMyInvites(controller.signal).catch(reportRequestError);
    return () => controller.abort();
  }, [activeUserId, authToken, authState]);
  useEffect(() => {
    let stopped = false;
    let refreshTimer = null;
    let accessController = null;
    if (!selectedCircle || !isAuthenticated || !mediaAccessNeeded) {
      setMediaAccessTicket(null);
      return undefined;
    }

    setMediaAccessTicket((current) => (
      current && current.circle_id === selectedCircle ? current : null
    ));

    async function refreshMediaAccess() {
      accessController = new AbortController();
      try {
        const access = await requestCircleAccessTicket(selectedCircle, "media", accessController.signal);
        if (stopped) return;
        setMediaAccessTicket({ ...access, circle_id: selectedCircle });
        const refreshInMs = Math.max(10000, Date.parse(access.expires_at) - Date.now() - 60000);
        refreshTimer = window.setTimeout(refreshMediaAccess, refreshInMs);
      } catch (error) {
        if (stopped || error?.name === "AbortError") return;
        setStatus(`Media access is reconnecting: ${error.message}`);
        refreshTimer = window.setTimeout(refreshMediaAccess, 5000);
      }
    }

    refreshTimer = window.setTimeout(refreshMediaAccess, 120);
    return () => {
      stopped = true;
      if (refreshTimer) window.clearTimeout(refreshTimer);
      if (accessController) accessController.abort();
    };
  }, [selectedCircle, authToken, authState, mediaAccessNeeded]);
  async function createUser(e) {
    e.preventDefault();
    if (!reviewAuthAvailable) {
      setStatus(runtimeConfig?.warning || "Authentication is unavailable");
      return;
    }
    const user = await requestJson("/users", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ display_name: e.target.display_name.value.trim() }),
    });
    setStatus("User created");
    e.target.reset();
    await loadUsers();
    await changeActiveUser(user.id);
    const auth = await requestJson("/auth/login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ user_id: user.id }),
    });
    setToken(auth.access_token);
    setStatus("User created and signed in");
  }

  async function openSampleCircle() {
    setStatus("Opening your private sample family…");
    const circle = await requestJson("/demo/sample-circle", { method: "POST", headers });
    await loadCircles();
    selectCircle(circle.id);
    setStatus("Your fictional sample is ready. Find Meera Rao, then render the graph. Edits are saved to your account.");
  }

  async function createCircle(e) {
    e.preventDefault();
    const circle = await requestJson("/circles", { method: "POST", headers, body: JSON.stringify({ name: e.target.name.value.trim() }) });
    setStatus("Circle created");
    e.target.reset();
    await loadCircles();
    selectCircle(circle.id);
  }

  async function addMember(e) {
    e.preventDefault();
    if (!canManageMembers) throw new Error("Only owners can manage members");
    await requestJson(`/circles/${selectedCircle}/members`, {
      method: "POST",
      headers,
      body: JSON.stringify({ user_id: e.target.user_id.value, role: e.target.role.value }),
    });
    setStatus("Member upserted");
    await loadCircleData(selectedCircle);
    await loadManagementData(selectedCircle);
  }

  async function createInvitation(e) {
    e.preventDefault();
    if (!canManageMembers) throw new Error("Only owners can send invitations");
    await requestJson(`/circles/${selectedCircle}/invitations`, {
      method: "POST",
      headers,
      body: JSON.stringify({
        invited_user_id: e.target.invited_user_id.value || null,
        role: e.target.role.value,
      }),
    });
    setStatus("Invitation sent");
    await loadManagementData(selectedCircle);
    await loadMyInvites();
  }

  async function respondInvitation(invitationId, action) {
    await requestJson(`/invitations/${invitationId}/respond`, {
      method: "POST",
      headers,
      body: JSON.stringify({ action }),
    });
    setStatus(`Invitation ${action}ed`);
    await loadMyInvites();
    await loadCircles();
  }

  async function transferOwnership(e) {
    e.preventDefault();
    if (!canManageMembers) throw new Error("Only owners can transfer ownership");
    const newOwnerUserId = e.target.new_owner_user_id.value;
    await requestJson(`/circles/${selectedCircle}/ownership/transfer`, {
      method: "POST",
      headers,
      body: JSON.stringify({ new_owner_user_id: newOwnerUserId }),
    });
    setMembers((prev) => prev.map((m) => {
      if (m.user_id === activeUserId) return { ...m, role: "viewer" };
      if (m.user_id === newOwnerUserId) return { ...m, role: "owner" };
      return m;
    }));
    setStatus("Ownership transferred");
    await loadCircleData(selectedCircle);
    await loadManagementData(selectedCircle);
  }

  async function checkJourneyDuplicates(draft) {
    const query = new URLSearchParams({ full_name: draft.full_name.trim() });
    if (draft.birth_date) query.set("birth_date", draft.birth_date);
    if (draft.birth_place.trim()) query.set("birth_place", draft.birth_place.trim());
    return requestJson(`/circles/${selectedCircle}/persons/duplicate-hints?${query}`, { headers });
  }

  async function finishPersonJourney(person, draft) {
    let linkError = "";
    if (draft.relative_id) {
      try {
        await requestJson(`/circles/${selectedCircle}/relationships`, {
          method: "POST", headers,
          body: JSON.stringify({ from_person_id: person.id, to_person_id: draft.relative_id, relationship_type: draft.relationship_type }),
        });
      } catch (cause) { linkError = cause.message; }
    }
    const linked = draft.relative_id && !linkError;
    const root = linked && draft.relationship_type !== "parent_of" ? draft.relative_id : person.id;
    const mode = linked && ["spouse_of", "sibling_of"].includes(draft.relationship_type) ? "family_expanded" : "lineage";
    setLastRoot(root);
    setGraphRootPersonId(root);
    setLastDirection("descendants");
    setLastDepth(2);
    setLastMode(mode);
    setLastLayoutMode("hierarchy");
    setLastLateralTypes("spouse_of,sibling_of,cousin_of");
    setLastLateralDepth(1);
    selectPerson(person.id);
    setHighlightedNodeIds([person.id]);
    setHighlightedEdgeKeys([]);
    setRightOpen(true);
    const results = await Promise.allSettled([
      loadCircleData(selectedCircle),
      fetchSubgraph({ circleId: selectedCircle, root, direction: "descendants", depth: 2, mode, lateralTypes: "spouse_of,sibling_of,cousin_of", lateralDepth: 1 }),
    ]);
    const graphResult = results[1];
    if (graphResult.status === "fulfilled" && graphResult.value) setSubgraph(graphResult.value);
    const refreshError = results.find((result) => result.status === "rejected");
    setStatus(linkError ? `Profile saved; family link needs attention: ${linkError}` :
      refreshError ? `Profile saved; refresh needed: ${refreshError.reason.message}` : `${person.full_name} added to the family`);
    return { person, linkError, graphError: refreshError?.reason?.message || "" };
  }

  async function savePersonJourney(draft) {
    const profile = Object.fromEntries(
      ["full_name", "birth_date", "birth_place", "occupation", "hobbies", "personality", "bio_text"]
        .map((field) => [field, draft[field].trim() || null])
    );
    profile.full_name = draft.full_name.trim();
    const person = await requestJson(`/circles/${selectedCircle}/persons`, {
      method: "POST", headers, body: JSON.stringify(profile),
    });
    return finishPersonJourney(person, draft);
  }

  async function copyInvitationCode() {
    try {
      await navigator.clipboard.writeText(activeUserId);
      setInviteCopied(true);
      window.setTimeout(() => setInviteCopied(false), 2600);
    } catch (_) { setStatus("Copy failed. Select the invitation code and copy it manually."); }
  }

  function revealNewPerson(personId) {
    setPersonJourneyOpen(false);
    setNewArrivalId(personId);
    window.requestAnimationFrame(() => {
      const node = Array.from(document.querySelectorAll(".graph-node"))
        .find((element) => element.getAttribute("data-node-id") === personId);
      node?.scrollIntoView({ behavior: window.matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth", block: "center", inline: "center" });
    });
    window.setTimeout(() => setNewArrivalId((current) => current === personId ? "" : current), 3800);
  }

  async function addRelationship(e) {
    e.preventDefault();
    await requestJson(`/circles/${selectedCircle}/relationships`, {
      method: "POST",
      headers,
      body: JSON.stringify({
        from_person_id: e.target.from_person_id.value,
        to_person_id: e.target.to_person_id.value,
        relationship_type: e.target.relationship_type.value.trim(),
      }),
    });
    setStatus("Relationship created");
    e.target.reset();
    await loadCircleData(selectedCircle);
    await reloadSubgraph(selectedCircle);
  }

  async function reloadSubgraph(circleIdOverride) {
    const circleId = circleIdOverride || selectedCircle;
    if (!circleId || !lastRoot) return;
    const data = await fetchSubgraph({
      circleId,
      root: lastRoot,
      direction: lastDirection,
      depth: lastDepth,
      mode: lastMode,
      lateralTypes: lastLateralTypes,
      lateralDepth: Number(lastLateralDepth || 0),
    });
    if (!data) return;
    setSubgraph(data);
    if (selectedPersonId && !data.persons.some((p) => p.id === selectedPersonId)) {
      selectPerson(lastRoot);
      setHighlightedNodeIds([lastRoot]);
      setHighlightedEdgeKeys([]);
    }
  }

  function buildSubgraphQuery() {
    return `root_person_id=${encodeURIComponent(lastRoot)}&direction=${encodeURIComponent(lastDirection)}&depth=${Number(lastDepth)}&mode=${encodeURIComponent(lastMode)}&lateral_types=${encodeURIComponent(lastLateralTypes)}&lateral_depth=${Number(lastLateralDepth || 0)}`;
  }

  async function deleteRelationship(relationshipId, circleId) {
    const targetCircleId = circleId || selectedCircle;
    if (!targetCircleId) {
      throw new Error("No active circle selected");
    }
    await requestJson(`/circles/${targetCircleId}/relationships/${relationshipId}`, {
      method: "DELETE",
      headers,
    });
    setStatus("Relationship deleted");
    await loadCircleData(targetCircleId);
    await reloadSubgraph(targetCircleId);
  }

  function startEditRelationship(r) {
    setEditingRelationshipId(r.id);
    setEditRelationshipDraft({
      from_person_id: r.from_person_id,
      to_person_id: r.to_person_id,
      relationship_type: r.relationship_type,
    });
  }

  async function saveRelationshipEdit(circleId) {
    if (!editingRelationshipId) return;
    const targetCircleId = circleId || selectedCircle;
    if (!targetCircleId) {
      throw new Error("No active circle selected");
    }
    await requestJson(`/circles/${targetCircleId}/relationships/${editingRelationshipId}`, {
      method: "PATCH",
      headers,
      body: JSON.stringify(editRelationshipDraft),
    });
    setStatus("Relationship updated");
    setEditingRelationshipId("");
    await loadCircleData(targetCircleId);
    await reloadSubgraph(targetCircleId);
  }

  async function loadSubgraph(e) {
    e.preventDefault();
    const root = e.target.root_person_id.value;
    const direction = e.target.direction.value;
    const depth = Number(e.target.depth.value || 2);
    const mode = e.target.mode.value || "lineage";
    const layoutMode = e.target.layout_mode.value || "hierarchy";
    const lateralTypes = e.target.lateral_types.value.trim() || "spouse_of,sibling_of,cousin_of";
    const lateralDepth = Number(e.target.lateral_depth.value || 1);
    setStatus("Loading graph…");
    const circleId = selectedCircle;
    const data = await fetchSubgraph({ circleId, root, direction, depth, mode, lateralTypes, lateralDepth });
    if (!data) return;
    setSubgraph(data);
    setLastRoot(root);
    setGraphRootPersonId(root);
    setLastDirection(direction);
    setLastDepth(depth);
    setLastMode(mode);
    setLastLayoutMode(layoutMode);
    setLastLateralTypes(lateralTypes);
    setLastLateralDepth(lateralDepth);
    selectPerson(root);
    setHighlightedNodeIds([root]);
    setHighlightedEdgeKeys([]);
    setZoom(1);
    setStatus(`Loaded ${data.persons.length} nodes and ${data.relationships.length} edges`);
    setTimeout(fitGraph, 0);
  }

  async function createChangeRequest(e) {
    e.preventDefault();
    await requestJson(`/circles/${selectedCircle}/change-requests`, {
      method: "POST",
      headers,
      body: JSON.stringify({
        entity_type: "person",
        entity_id: e.target.entity_id.value,
        proposed_patch_json: { religion: e.target.religion.value.trim() || null },
      }),
    });
    setStatus("Change request created");
    e.target.reset();
    await loadCircleData(selectedCircle);
  }

  async function reviewRequest(id, action) {
    await requestJson(`/circles/${selectedCircle}/change-requests/${id}/${action}`, {
      method: "POST",
      headers,
      body: JSON.stringify({ review_comment: `${action} from sidebar` }),
    });
    setStatus(`Change request ${action}`);
    await loadCircleData(selectedCircle);
  }

  async function createContextEvent(e) {
    e.preventDefault();
    await requestJson(`/circles/${selectedCircle}/context-events`, {
      method: "POST",
      headers,
      body: JSON.stringify({
        date: e.target.date.value,
        title: e.target.title.value.trim(),
        event_type: e.target.event_type.value,
        location_name: e.target.location_name.value.trim() || null,
        description: e.target.description.value.trim() || null,
      }),
    });
    setStatus("Context event created");
    e.target.reset();
    await loadCircleData(selectedCircle);
  }

  async function updatePersonProfile(e) {
    e.preventDefault();
    if (!selectedPersonId || !canEditRecords) return;
    const payload = {
      full_name: e.target.full_name.value.trim(),
      religion: e.target.religion.value.trim() || null,
      sex: e.target.sex.value.trim() || null,
      birth_date: e.target.birth_date.value || null,
      death_date: e.target.death_date.value || null,
      birth_place: e.target.birth_place.value.trim() || null,
      occupation: e.target.occupation.value.trim() || null,
      hobbies: e.target.hobbies.value.trim() || null,
      personality: e.target.personality.value.trim() || null,
      medical_notes: e.target.medical_notes.value.trim() || null,
      bio_text: e.target.bio_text.value.trim() || null,
      revision_reason: e.target.revision_reason.value.trim() || null,
    };
    await requestJson(`/circles/${selectedCircle}/persons/${selectedPersonId}`, {
      method: "PATCH",
      headers,
      body: JSON.stringify(payload),
    });
    setStatus("Person profile updated");
    await loadCircleData(selectedCircle);
    if (revisionsPanelActivated) await loadPersonRevisions(selectedPersonId);
    if (subgraph) {
      setSubgraph((prev) => {
        if (!prev) return prev;
        return {
          ...prev,
          persons: (prev.persons || []).map((p) => (p.id === selectedPersonId ? { ...p, ...payload } : p)),
        };
      });
    }
  }

  async function linkEventToPerson(e) {
    e.preventDefault();
    await requestJson(`/circles/${selectedCircle}/persons/${e.target.person_id.value}/context-links`, {
      method: "POST",
      headers,
      body: JSON.stringify({
        context_event_id: e.target.context_event_id.value,
        relevance_note: e.target.relevance_note.value.trim() || null,
      }),
    });
    setStatus("Linked event to person");
  }

  async function loadTimeline(e) {
    e.preventDefault();
    let data = [];
    if (timelineScope === "person") {
      data = await requestJson(`/circles/${selectedCircle}/persons/${e.target.person_id.value}/timeline`, { headers });
    } else {
      if (!lastRoot) {
        setStatus("Render a graph first to load subgraph timeline");
        return;
      }
      const query = buildSubgraphQuery();
      const filters = `&from_date=${encodeURIComponent(timelineFromDate || "")}&to_date=${encodeURIComponent(timelineToDate || "")}&event_types=${encodeURIComponent(timelineEventTypes || "")}`;
      data = await requestJson(`/circles/${selectedCircle}/graph/subgraph/timeline?${query}${filters}`, { headers });
    }
    setTimeline(data);
    setStatus(`Loaded timeline with ${data.length} items`);
  }

  async function loadPersonMedia(personId, circleId = selectedCircle, signal) {
    const requestId = ++personMediaRequestRef.current;
    if (!personId || !circleId) return setPersonMedia([]);
    const data = await requestJson(`/circles/${circleId}/persons/${personId}/media`, { headers, signal });
    if (
      !requestIsCurrent(personMediaRequestRef, requestId, signal)
      || selectedCircleRef.current !== circleId
      || selectedPersonIdRef.current !== personId
    ) return;
    setPersonMedia(data);
  }

  async function loadPersonRevisions(personId, circleId = selectedCircle, signal) {
    const requestId = ++personRevisionsRequestRef.current;
    if (!personId || !circleId) return setPersonRevisions([]);
    const data = await requestJson(`/circles/${circleId}/persons/${personId}/revisions`, { headers, signal });
    if (
      !requestIsCurrent(personRevisionsRequestRef, requestId, signal)
      || selectedCircleRef.current !== circleId
      || selectedPersonIdRef.current !== personId
    ) return;
    setPersonRevisions(data);
  }

  async function loadExistingPersonThread(circleId, personId, selectionKey, signal) {
    const requestId = ++discussionLoadRequestRef.current;
    if (!personId || !circleId) return null;
    const query = `entity_type=person&entity_id=${encodeURIComponent(personId)}`;
    const thread = await requestJson(`/circles/${circleId}/threads?${query}`, { headers, signal });
    if (
      !requestIsCurrent(discussionLoadRequestRef, requestId, signal)
      || discussionSelectionKeyRef.current !== selectionKey
      || !thread
    ) return thread;
    setActiveDiscussionThread(thread.id, selectionKey);
    const messages = await requestJson(`/circles/${circleId}/threads/${thread.id}/messages`, { headers, signal });
    if (
      requestIsCurrent(discussionLoadRequestRef, requestId, signal)
      && discussionSelectionKeyRef.current === selectionKey
    ) setDiscussionMessages(messages);
    return thread;
  }

  async function createOrGetPersonThread(circleId, personId, selectionKey) {
    const requestId = ++discussionLoadRequestRef.current;
    const thread = await requestJson(`/circles/${circleId}/threads`, {
      method: "POST",
      headers,
      body: JSON.stringify({ entity_type: "person", entity_id: personId }),
    });
    if (requestIsCurrent(discussionLoadRequestRef, requestId) && discussionSelectionKeyRef.current === selectionKey) {
      setActiveDiscussionThread(thread.id, selectionKey);
      const messages = await requestJson(`/circles/${circleId}/threads/${thread.id}/messages`, { headers });
      if (
        requestIsCurrent(discussionLoadRequestRef, requestId)
        && discussionSelectionKeyRef.current === selectionKey
      ) setDiscussionMessages(messages);
    }
    return thread;
  }

  async function sendDiscussionMessage(e) {
    e.preventDefault();
    const circleId = selectedCircle;
    const personId = selectedPersonId;
    if (!circleId || !personId) {
      setStatus("Select a person to start discussion");
      return;
    }
    const content = e.target.content.value.trim();
    if (!content) return;
    const selectionKey = `${circleId}:${personId}`;
    let threadId = activeDiscussionThreadKeyRef.current === selectionKey
      ? discussionThreadIdRef.current
      : "";
    if (!threadId) {
      const thread = await createOrGetPersonThread(circleId, personId, selectionKey);
      threadId = thread.id;
    }
    const message = await requestJson(`/circles/${circleId}/threads/${threadId}/messages`, {
      method: "POST",
      headers,
      body: JSON.stringify({ content }),
    });
    if (discussionSelectionKeyRef.current === selectionKey) appendDiscussionMessage(message);
    e.target.reset();
    setStatus("Discussion note added");
  }

  async function uploadMedia(e) {
    e.preventDefault();
    const formElement = e.currentTarget;
    const circleId = selectedCircle;
    const targetPersonId = e.target.person_id.value;
    const chosen = e.target.file.files && e.target.file.files[0];
    if (!circleId || !targetPersonId || !chosen) return;
    if (chosen.size === 0) throw new Error("Choose a non-empty media file");
    const form = new FormData();
    form.append("file", chosen);
    setMediaUploadBusy(true);
    setStatus(`Uploading ${chosen.name}…`);
    try {
      const res = await fetch(`/circles/${circleId}/persons/${targetPersonId}/media`, {
        method: "POST",
        headers: authToken
          ? { Authorization: `Bearer ${authToken}` }
          : (activeUserId ? { "X-User-Id": activeUserId } : {}),
        body: form,
      });
      if (!res.ok) {
        const body = await res.json().catch(() => ({ detail: "Upload failed" }));
        if (res.status === 401) setToken("");
        throw new Error(responseErrorMessage(res, body, "Upload failed"));
      }
      setStatus(`${chosen.name} uploaded`);
      formElement.reset();
      await Promise.all([
        loadPersonMedia(targetPersonId, circleId),
        loadMediaPreviews(circleId),
      ]);
    } finally {
      setMediaUploadBusy(false);
    }
  }

  async function loadPersonPlaces(personId, circleId = selectedCircle, signal) {
    const requestId = ++personPlacesRequestRef.current;
    if (!personId || !circleId) {
      setPersonPlaces([]);
      setSelectedPlace(null);
      return;
    }
    const data = await requestJson(`/circles/${circleId}/persons/${personId}/places`, { headers, signal });
    if (
      !requestIsCurrent(personPlacesRequestRef, requestId, signal)
      || selectedCircleRef.current !== circleId
      || selectedPersonIdRef.current !== personId
    ) return;
    setPersonPlaces(data);
    setSelectedPlace(null);
  }

  async function addPersonPlace(e) {
    e.preventDefault();
    const targetPersonId = e.target.person_id.value;
    if (!targetPersonId) {
      setStatus("Select a person before adding a place");
      return;
    }
    await requestJson(`/circles/${selectedCircle}/persons/${targetPersonId}/places`, {
      method: "POST",
      headers,
      body: JSON.stringify({
        place_name: e.target.place_name.value.trim(),
        country: e.target.country.value.trim() || null,
        lat: e.target.lat.value ? Number(e.target.lat.value) : null,
        lng: e.target.lng.value ? Number(e.target.lng.value) : null,
        from_date: e.target.from_date.value || null,
        to_date: e.target.to_date.value || null,
        notes: e.target.notes.value.trim() || null,
      }),
    });
    setStatus("Place added");
    e.target.reset();
    await loadPersonPlaces(targetPersonId);
  }

  async function loadMigrationGeojson(personId) {
    if (!personId) {
      setStatus("Select a person before loading migration GeoJSON");
      return;
    }
    const data = await requestJson(`/circles/${selectedCircle}/persons/${personId}/migration-geojson`, { headers });
    setMigrationGeoJson(data);
    setStatus(`Loaded migration GeoJSON with ${data.features.length} features`);
  }

  async function loadSubgraphMigrationGeojson(upToDate = "") {
    if (!lastRoot) {
      setStatus("Render a graph first to load subgraph migration");
      return;
    }
    const query = buildSubgraphQuery();
    const upto = upToDate ? `&up_to_date=${encodeURIComponent(upToDate)}` : "";
    const data = await requestJson(`/circles/${selectedCircle}/graph/subgraph/migration-geojson?${query}${upto}`, { headers });
    setSubgraphMigrationGeoJson(data);
    if (!upToDate) {
      const pointDates = Array.from(new Set(
        (data.features || [])
          .filter((f) => f.geometry && f.geometry.type === "Point" && f.properties && f.properties.from_date)
          .map((f) => f.properties.from_date)
      )).sort();
      setSubgraphMigrationDates(pointDates);
      setSubgraphMigrationIndex(pointDates.length ? pointDates.length - 1 : 0);
    }
    setStatus(`Loaded subgraph migration GeoJSON with ${data.features.length} features`);
  }

  function setSubgraphMigrationCursor(nextIndex) {
    if (!subgraphMigrationDates.length) return;
    const clamped = Math.max(0, Math.min(subgraphMigrationDates.length - 1, nextIndex));
    setSubgraphMigrationIndex(clamped);
    const date = subgraphMigrationDates[clamped];
    loadSubgraphMigrationGeojson(date).catch((x) => setStatus(x.message));
  }

  async function onTimelineItemClick(item) {
    if (item.kind === "life" && item.ref_id) {
      applyPersonFocus(item.ref_id);
      setStatus("Focused timeline life event in graph");
      return;
    }
    if (item.kind === "context" && item.ref_id) {
      const linkedPersons = await requestJson(`/circles/${selectedCircle}/context-events/${item.ref_id}/persons`, { headers });
      const ids = linkedPersons.map((p) => p.id);
      setHighlightedNodeIds(ids);
      setHighlightedEdgeKeys([]);
      if (ids.length) selectPerson(ids[0]);
      setStatus(`Highlighted ${ids.length} linked person nodes`);
    }
  }

  useEffect(() => {
    const controller = new AbortController();
    let loadTimer = null;
    if (!selectedCircle || !selectedPersonId || !isAuthenticated || !mediaPanelActivated) {
      setPersonMediaLoading(false);
      return () => controller.abort();
    }
    setPersonMediaLoading(true);
    loadTimer = window.setTimeout(() => {
      loadPersonMedia(selectedPersonId, selectedCircle, controller.signal)
        .catch(reportRequestError)
        .finally(() => {
          if (
            !controller.signal.aborted
            && selectedCircleRef.current === selectedCircle
            && selectedPersonIdRef.current === selectedPersonId
          ) setPersonMediaLoading(false);
        });
    }, SELECTION_STABILIZE_MS);
    return () => {
      if (loadTimer) window.clearTimeout(loadTimer);
      controller.abort();
    };
  }, [selectedPersonId, selectedCircle, activeUserId, authToken, authState, mediaPanelActivated]);

  useEffect(() => {
    const controller = new AbortController();
    let loadTimer = null;
    if (!selectedCircle || !selectedPersonId || !isAuthenticated || !placesPanelActivated) {
      setPersonPlacesLoading(false);
      return () => controller.abort();
    }
    setPersonPlacesLoading(true);
    loadTimer = window.setTimeout(() => {
      loadPersonPlaces(selectedPersonId, selectedCircle, controller.signal)
        .catch(reportRequestError)
        .finally(() => {
          if (
            !controller.signal.aborted
            && selectedCircleRef.current === selectedCircle
            && selectedPersonIdRef.current === selectedPersonId
          ) setPersonPlacesLoading(false);
        });
    }, SELECTION_STABILIZE_MS);
    return () => {
      if (loadTimer) window.clearTimeout(loadTimer);
      controller.abort();
    };
  }, [selectedPersonId, selectedCircle, activeUserId, authToken, authState, placesPanelActivated]);

  useEffect(() => {
    const controller = new AbortController();
    let loadTimer = null;
    if (!selectedCircle || !selectedPersonId || !isAuthenticated || !revisionsPanelActivated) {
      setPersonRevisionsLoading(false);
      return () => controller.abort();
    }
    setPersonRevisionsLoading(true);
    loadTimer = window.setTimeout(() => {
      loadPersonRevisions(selectedPersonId, selectedCircle, controller.signal)
        .catch(reportRequestError)
        .finally(() => {
          if (
            !controller.signal.aborted
            && selectedCircleRef.current === selectedCircle
            && selectedPersonIdRef.current === selectedPersonId
          ) setPersonRevisionsLoading(false);
        });
    }, SELECTION_STABILIZE_MS);
    return () => {
      if (loadTimer) window.clearTimeout(loadTimer);
      controller.abort();
    };
  }, [selectedPersonId, selectedCircle, activeUserId, authToken, authState, revisionsPanelActivated]);

  useEffect(() => {
    const controller = new AbortController();
    let loadTimer = null;
    const selectionKey = selectedCircle && selectedPersonId ? `${selectedCircle}:${selectedPersonId}` : "";
    if (!selectedCircle || !selectedPersonId || !isAuthenticated || !discussionPanelActivated) {
      setDiscussionLoading(false);
      return () => controller.abort();
    }
    discussionSelectionKeyRef.current = selectionKey;
    setDiscussionLoading(true);
    loadTimer = window.setTimeout(() => {
      loadExistingPersonThread(selectedCircle, selectedPersonId, selectionKey, controller.signal)
        .catch(reportRequestError)
        .finally(() => {
          if (
            !controller.signal.aborted
            && discussionSelectionKeyRef.current === selectionKey
            && selectedCircleRef.current === selectedCircle
            && selectedPersonIdRef.current === selectedPersonId
          ) setDiscussionLoading(false);
        });
    }, SELECTION_STABILIZE_MS);
    return () => {
      if (loadTimer) window.clearTimeout(loadTimer);
      controller.abort();
    };
  }, [selectedPersonId, selectedCircle, activeUserId, authToken, authState, discussionPanelActivated]);
  useEffect(() => {
    if (!selectedCircle || !isAuthenticated || !discussionPanelActivated) return undefined;
    let stopped = false;
    let ws = null;
    let retryTimer = null;
    let ticketController = null;
    let retryDelayMs = 1000;
    const proto = window.location.protocol === "https:" ? "wss" : "ws";

    async function connectRealtime() {
      if (ticketController) ticketController.abort();
      ticketController = new AbortController();
      try {
        const access = await requestCircleAccessTicket(selectedCircle, "websocket", ticketController.signal);
        if (stopped) return;
        ws = new WebSocket(
          `${proto}://${window.location.host}/ws/circles/${selectedCircle}`,
          ["family-tree.v1", `family-tree-ticket.${access.ticket}`]
        );
        ws.onopen = () => {
          retryDelayMs = 1000;
          setStatus((current) => current.startsWith("Realtime connection") ? "" : current);
        };
        ws.onmessage = (evt) => {
          try {
            const data = JSON.parse(evt.data);
            if (data.type === "thread.message.created" && data.thread_id === discussionThreadIdRef.current) {
              appendDiscussionMessage(data.message);
            }
          } catch (_) {
            // ignore malformed websocket payloads
          }
        };
        ws.onclose = () => {
          ws = null;
          if (stopped) return;
          setStatus("Realtime connection interrupted; reconnecting…");
          retryTimer = window.setTimeout(connectRealtime, retryDelayMs);
          retryDelayMs = Math.min(retryDelayMs * 2, 30000);
        };
      } catch (error) {
        if (stopped || error?.name === "AbortError") return;
        setStatus(`Realtime connection is retrying: ${error.message}`);
        retryTimer = window.setTimeout(connectRealtime, retryDelayMs);
        retryDelayMs = Math.min(retryDelayMs * 2, 30000);
      }
    }

    retryTimer = window.setTimeout(connectRealtime, 120);
    return () => {
      stopped = true;
      if (retryTimer) window.clearTimeout(retryTimer);
      if (ticketController) ticketController.abort();
      if (ws) ws.close();
    };
  }, [selectedCircle, authToken, authState, discussionPanelActivated]);
  useEffect(() => {
    if (!isSubgraphMigrationPlaying || subgraphMigrationDates.length <= 1) return undefined;
    migrationTimerRef.current = window.setInterval(() => {
      setSubgraphMigrationIndex((prev) => {
        const next = prev >= subgraphMigrationDates.length - 1 ? 0 : prev + 1;
        const date = subgraphMigrationDates[next];
        loadSubgraphMigrationGeojson(date).catch((x) => setStatus(x.message));
        return next;
      });
    }, 1100);
    return () => {
      if (migrationTimerRef.current) window.clearInterval(migrationTimerRef.current);
    };
  }, [isSubgraphMigrationPlaying, subgraphMigrationDates, lastRoot, selectedCircle, lastDirection, lastDepth, lastMode, lastLateralTypes, lastLateralDepth]);

  useEffect(() => {
    const viewport = graphViewportRef.current;
    if (!viewport || lastLayoutMode !== "time_aligned") {
      prevTimeTimelineOpenRef.current = timeTimelineOpen;
      return;
    }
    const wasOpen = prevTimeTimelineOpenRef.current;
    if (wasOpen === timeTimelineOpen) return;
    const anchor = pendingTimelineViewportAnchorRef.current;
    const applyAnchor = () => {
      if (!anchor) return;
      viewport.scrollLeft = Math.max(0, anchor.centerX - viewport.clientWidth / 2);
      viewport.scrollTop = Math.max(0, anchor.centerY - viewport.clientHeight / 2);
    };
    window.requestAnimationFrame(() => {
      applyAnchor();
      window.requestAnimationFrame(applyAnchor);
    });
    pendingTimelineViewportAnchorRef.current = null;
    prevTimeTimelineOpenRef.current = timeTimelineOpen;
  }, [timeTimelineOpen, lastLayoutMode]);

  useEffect(() => {
    setPersonSearchActiveIndex(0);
  }, [personSearchQuery, selectedCircle]);

  const gridCols = `${leftOpen ? "320px" : "44px"} 1fr ${rightOpen ? "340px" : "44px"}`;

  return React.createElement(React.Fragment, null, [
    React.createElement("div", { className: "topbar", key: "top" }, [
      React.createElement("div", { key: "t" }, [
        React.createElement("div", { className: "title", key: "ttl" }, "Viraasat"),
        React.createElement("div", { className: "subtitle", key: "sub" }, "Digital Heirloom for South Asian Lineage"),
      ]),
      React.createElement("div", { key: "actions", style: { display: "flex", gap: "8px", alignItems: "center" } }, [
        React.createElement("div", {
          className: `auth-mode-chip ${authModeClass}`,
          key: "auth-mode",
          title: runtimeConfig?.warning || "Loading deployment security configuration",
          role: "status",
        }, authModeLabel),
        React.createElement("button", { className: "btn", key: "zoom-in", onClick: () => setZoom((z) => Math.min(2.2, z + 0.15)) }, "Zoom +"),
        React.createElement("button", { className: "btn", key: "zoom-out", onClick: () => setZoom((z) => Math.max(graphRenderStats?.large_graph_mode ? LARGE_GRAPH_MIN_ZOOM : 0.35, z - 0.15)) }, "Zoom -"),
        React.createElement("button", { className: "btn", key: "fit", onClick: fitGraph }, "Fit"),
        React.createElement("button", { className: "btn", key: "reset", onClick: () => setZoom(1) }, "1:1"),
        React.createElement("button", { className: "btn", key: "l", onClick: () => setLeftOpen((v) => !v) }, leftOpen ? "Hide Left" : "Show Left"),
        React.createElement("button", { className: "btn", key: "r", onClick: () => setRightOpen((v) => !v) }, rightOpen ? "Hide Right" : "Show Right"),
      ]),
    ]),
    React.createElement("div", { className: "shell", style: { gridTemplateColumns: gridCols }, key: "shell" }, [
      React.createElement("aside", { className: `sidebar ${leftOpen ? "" : "collapsed"}`, key: "left" }, [
        React.createElement("div", { className: "sidebar-head", key: "h" }, [
          React.createElement("span", { key: "txt" }, "Archive Stewardship"),
          React.createElement("button", { className: "btn", key: "b", onClick: () => setLeftOpen((v) => !v) }, leftOpen ? "◀" : "▶"),
        ]),
        leftOpen ? React.createElement("div", { className: "sidebar-body", key: "body" }, [
          React.createElement("details", { className: "card", open: true, key: "u" }, [
            React.createElement("summary", { key: "s" }, "Users & Circles"),
            !managedAuthAvailable && React.createElement("form", { key: "f1", onSubmit: (e) => createUser(e).catch((x) => setStatus(x.message)) }, [
              React.createElement("input", { key: "i1", name: "display_name", required: true, placeholder: "New user name", disabled: !reviewAuthAvailable }),
              React.createElement("button", { key: "b1", type: "submit", disabled: !reviewAuthAvailable || authState === "checking" }, "Create User"),
            ]),
            !managedAuthAvailable && React.createElement("label", { key: "l1" }, "Active User"),
            !managedAuthAvailable && React.createElement("select", { key: "s1", value: activeUserId, onChange: (e) => changeActiveUser(e.target.value).catch((x) => setStatus(x.message)), disabled: !reviewAuthAvailable || authState === "checking" },
              [React.createElement("option", { key: "x", value: "" }, "Select user")]
                .concat(userOptions.map((u) => React.createElement("option", { key: u.value, value: u.value }, u.label)))
            ),
            React.createElement("div", { className: "auth-row", key: "auth-row" }, [
              React.createElement("button", {
                key: "signin",
                type: "button",
                className: "auth-btn auth-btn-in",
                onClick: () => loginAsActiveUser().catch((x) => setStatus(x.message)),
                disabled: authState === "checking" || isAuthenticated || (!managedAuthAvailable && (!reviewAuthAvailable || !activeUserId)),
              }, managedAuthAvailable ? "Continue with Google" : "Sign In"),
              React.createElement("button", {
                key: "signout",
                type: "button",
                className: "auth-btn auth-btn-out",
                disabled: authState === "checking" || !authToken,
                onClick: () => signOutCurrentUser().catch((x) => setStatus(x.message)),
              }, "Sign Out"),
            ]),
            managedAuthAvailable && isAuthenticated ? React.createElement("button", {
              key: "sample", type: "button", className: "sample-family-button", onClick: () => openSampleCircle().catch((x) => setStatus(x.message)),
            }, "Explore a sample family") : null,
            React.createElement("form", { key: "f2", onSubmit: (e) => createCircle(e).catch((x) => setStatus(x.message)) }, [
              React.createElement("input", { key: "i2", name: "name", required: true, placeholder: "New circle name" }),
              React.createElement("button", { key: "b2", type: "submit", disabled: !isAuthenticated }, "Create Circle"),
            ]),
            React.createElement("label", { key: "l2" }, "Active Circle"),
            React.createElement("select", { key: "s2", value: selectedCircle, onChange: (e) => selectCircle(e.target.value) },
              [React.createElement("option", { key: "z", value: "" }, "Select circle")]
                .concat(circles.map((c) => React.createElement("option", { key: c.id, value: c.id }, c.name)))
            ),
            circleDataLoading
              ? React.createElement("div", { className: "muted", key: "circle-loading", role: "status" }, "Loading selected circle…")
              : (circleSupplementalLoading
                  ? React.createElement("div", { className: "muted", key: "circle-loading", role: "status" }, "Core family loaded · refreshing collaboration details…")
                  : null),
            React.createElement("div", { className: "muted", key: "ctx" }, activeUserName ? `${isAuthenticated ? "Active" : "Selected for sign-in"}: ${activeUserName}` : "No active user"),
            React.createElement("div", { className: "muted", key: "ctx-role" }, selectedCircle ? `Role: ${activeCircleRole || "none"}` : "Role: n/a"),
            React.createElement("div", { className: "muted", key: "ctx2" }, authState === "checking" ? "Auth: checking security mode" : (authState === "unavailable" ? "Auth: locked" : (isAuthenticated ? "Auth: signed in" : "Auth: signed out"))),
            managedAuthAvailable && isAuthenticated ? React.createElement("div", { key: "account-code" }, [
              React.createElement("label", { key: "label", htmlFor: "account-code" }, "Your invitation code"),
              React.createElement("div", { className: "invitation-code-row", key: "row" }, [
                React.createElement("input", { key: "code", id: "account-code", readOnly: true, value: activeUserId, onFocus: (e) => e.target.select() }),
                React.createElement("button", { key: "copy", type: "button", onClick: copyInvitationCode, "aria-label": "Copy your invitation code" }, inviteCopied ? "Copied" : "Copy"),
              ]),
              React.createElement("p", { className: "muted", key: "help" }, "Copy and send this code to a circle owner. They send you an invitation; you accept it under Invitations & Ownership. Your changes are saved to your account."),
              React.createElement("span", { className: "sr-only", role: "status", key: "copied" }, inviteCopied ? "Invitation code copied" : ""),
            ]) : null,
          ]),
          selectedCircle && canEditRecords ? React.createElement("div", { className: "journey-entry", key: "journey-entry" }, [
            React.createElement("span", { className: "journey-entry-kicker", key: "kicker" }, "Family archive"),
            React.createElement("strong", { key: "title" }, "Someone to remember?"),
            React.createElement("p", { key: "copy" }, "Begin with a name, then add the details that make them themselves."),
            React.createElement("button", { key: "open", type: "button", onClick: () => setPersonJourneyOpen(true) }, "Add a family member"),
          ]) : null,
          React.createElement(LazyDetails, { className: "card", key: "m", summary: "Membership" }, () => [
            React.createElement("form", { key: "f", onSubmit: (e) => addMember(e).catch((x) => setStatus(x.message)) }, [
              managedAuthAvailable ? React.createElement("input", { key: "s1", name: "user_id", required: true, placeholder: "Member invitation code", "aria-label": "Member invitation code" }) : React.createElement("select", { key: "s1", name: "user_id" },
                userOptions.map((u) => React.createElement("option", { key: u.value, value: u.value }, u.label))
              ),
              React.createElement("select", { key: "s2", name: "role" }, [
                React.createElement("option", { key: "e", value: "editor" }, "editor"),
                React.createElement("option", { key: "v", value: "viewer" }, "viewer"),
              ]),
              React.createElement("button", { key: "b", type: "submit", disabled: !selectedCircle || !canManageMembers }, "Add / Update"),
            ]),
            React.createElement("div", { className: "muted", key: "perm" }, canManageMembers ? "Owner permission: manage members" : "Only owners can manage members"),
            React.createElement("div", { className: "list", key: "l" },
              members.map((m) => {
                const user = users.find((u) => u.id === m.user_id);
                return React.createElement("div", { className: "item", key: `${m.circle_id}-${m.user_id}` }, [
                  React.createElement("span", { key: "n" }, user ? user.display_name : m.user_id.slice(0, 8)),
                  React.createElement("span", { className: "pill", key: "p" }, m.role),
                ]);
              })
            ),
          ]),
          React.createElement(LazyDetails, { className: "card", key: "inv", summary: "Invitations & Ownership" }, () => [
            React.createElement("form", { key: "f", onSubmit: (e) => createInvitation(e).catch((x) => setStatus(x.message)) }, [
              managedAuthAvailable ? React.createElement("input", { key: "u", name: "invited_user_id", required: true, placeholder: "Recipient invitation code", "aria-label": "Recipient invitation code" }) : React.createElement("select", { key: "u", name: "invited_user_id" },
                users.map((u) => React.createElement("option", { key: u.id, value: u.id }, `${u.display_name} (${u.id.slice(0, 8)})`))
              ),
              React.createElement("select", { key: "r", name: "role" }, [
                React.createElement("option", { key: "e", value: "editor" }, "editor"),
                React.createElement("option", { key: "v", value: "viewer" }, "viewer"),
              ]),
              React.createElement("button", { key: "b", type: "submit", disabled: !selectedCircle || !canManageMembers }, "Send Invite"),
            ]),
            React.createElement("form", { key: "xfer", onSubmit: (e) => transferOwnership(e).catch((x) => setStatus(x.message)) }, [
              React.createElement("select", { key: "n", name: "new_owner_user_id" },
                members.filter((m) => m.user_id !== activeUserId).map((m) => {
                  const u = users.find((row) => row.id === m.user_id);
                  const label = u ? `${u.display_name} (${u.id.slice(0, 8)})` : m.user_id.slice(0, 8);
                  return React.createElement("option", { key: m.user_id, value: m.user_id }, label);
                })
              ),
              React.createElement("button", { key: "b", type: "submit", disabled: !selectedCircle || !canManageMembers || members.length < 2 }, "Transfer Ownership"),
            ]),
            React.createElement("div", { className: "muted", key: "myh" }, "My Pending Invitations"),
            React.createElement("div", { className: "list", key: "my" },
              myInvitations.map((inv) => React.createElement("div", { className: "item", key: inv.id }, [
                React.createElement("div", { key: "d" }, `Circle ${inv.circle_id.slice(0, 8)} • ${inv.role}`),
                React.createElement("div", { key: "a", style: { display: "flex", gap: "6px", marginTop: "4px" } }, [
                  React.createElement("button", { key: "ac", type: "button", className: "btn", onClick: () => respondInvitation(inv.id, "accept").catch((x) => setStatus(x.message)) }, "Accept"),
                  React.createElement("button", { key: "dc", type: "button", className: "ghost", onClick: () => respondInvitation(inv.id, "decline").catch((x) => setStatus(x.message)) }, "Decline"),
                ]),
              ]))
            ),
            React.createElement("div", { className: "muted", key: "ch" }, "Circle Invitations"),
            React.createElement("div", { className: "list", key: "cl" },
              circleInvitations.map((inv) => React.createElement("div", { className: "item", key: inv.id }, `${inv.invited_user_id.slice(0, 8)} • ${inv.role} • ${inv.status}`))
            ),
          ]),
          React.createElement(LazyDetails, { className: "card", key: "p", summary: "People & Relationships" }, () => [
            React.createElement("button", { key: "add", type: "button", className: "people-journey-button", onClick: () => setPersonJourneyOpen(true), disabled: !selectedCircle || !canEditRecords }, "Add a family member"),
            React.createElement("form", { key: "f2", onSubmit: (e) => addRelationship(e).catch((x) => setStatus(x.message)) }, [
              React.createElement("select", { key: "a", name: "from_person_id" }, personOptions.map((p) => React.createElement("option", { key: p.value, value: p.value }, p.label))),
              React.createElement("select", { key: "b", name: "to_person_id" }, personOptions.map((p) => React.createElement("option", { key: p.value, value: p.value }, p.label))),
              React.createElement(
                "select",
                { key: "c", name: "relationship_type", required: true, defaultValue: "parent_of" },
                RELATIONSHIP_TYPES.map((t) => React.createElement("option", { key: t.value, value: t.value }, t.label))
              ),
              React.createElement("button", { key: "d", type: "submit", disabled: personOptions.length < 2 || !canEditRecords }, "Link"),
            ]),
            React.createElement("div", { className: "muted", key: "rel-help" }, "Direction rule: Person A (first dropdown) -> Person B (second dropdown)."),
            React.createElement("div", { className: "muted", key: "perm2" }, canEditRecords ? "Editor permission: records editable" : "Viewer mode: records are read-only"),
            React.createElement("div", { className: "list", key: "l" },
              visiblePeopleRows.map((p) => React.createElement("div", { className: "item", key: p.id },
                React.createElement("button", {
                  className: "person-list-select",
                  type: "button",
                  onClick: () => openPersonProfile(p.id),
                  "aria-label": `Open profile for ${p.full_name}`,
                }, [
                  React.createElement("span", { key: "name" }, p.full_name),
                  React.createElement("span", { className: "muted", key: "detail" }, p.religion || "Religion not recorded"),
                ])
              ))
            ),
            persons.length > PANEL_ROW_LIMIT
              ? React.createElement("button", {
                  className: "ghost list-expander",
                  key: "people-more",
                  type: "button",
                  "aria-expanded": peopleListExpanded ? "true" : "false",
                  onClick: () => setPeopleListExpanded((expanded) => !expanded),
                }, peopleListExpanded ? `Show first ${PANEL_ROW_LIMIT} people` : `Show all ${persons.length} people`)
              : null,
            React.createElement("div", { className: "muted", style: { margin: "6px 2px" }, key: "rh" }, "Relationships"),
            React.createElement("div", { className: "list", key: "rl" },
              visibleRelationshipRows.map((r) => {
                const fromName = personNameById[r.from_person_id] || r.from_person_id.slice(0, 8);
                const toName = personNameById[r.to_person_id] || r.to_person_id.slice(0, 8);
                const isEditing = editingRelationshipId === r.id;
                return React.createElement("div", { className: "item", key: r.id }, [
                  isEditing
                    ? React.createElement("div", { key: "edit", style: { display: "grid", gap: "6px", width: "100%" } }, [
                        React.createElement("select", {
                          key: "ef",
                          value: editRelationshipDraft.from_person_id,
                          onChange: (e) => setEditRelationshipDraft((prev) => ({ ...prev, from_person_id: e.target.value })),
                        }, personOptions.map((p) => React.createElement("option", { key: p.value, value: p.value }, p.label))),
                        React.createElement("select", {
                          key: "et",
                          value: editRelationshipDraft.to_person_id,
                          onChange: (e) => setEditRelationshipDraft((prev) => ({ ...prev, to_person_id: e.target.value })),
                        }, personOptions.map((p) => React.createElement("option", { key: p.value, value: p.value }, p.label))),
                        React.createElement("select", {
                          key: "er",
                          value: editRelationshipDraft.relationship_type,
                          onChange: (e) => setEditRelationshipDraft((prev) => ({ ...prev, relationship_type: e.target.value })),
                        }, RELATIONSHIP_TYPES.map((t) => React.createElement("option", { key: t.value, value: t.value }, t.label))),
                        React.createElement("div", { key: "ea", style: { display: "flex", gap: "6px" } }, [
                          React.createElement("button", {
                            key: "save",
                            type: "button",
                            onClick: () => saveRelationshipEdit(r.circle_id).catch((x) => setStatus(x.message)),
                            disabled: !canEditRecords,
                          }, "Save"),
                          React.createElement("button", {
                            key: "cancel",
                            type: "button",
                            className: "ghost",
                            onClick: () => setEditingRelationshipId(""),
                          }, "Cancel"),
                        ]),
                      ])
                    : React.createElement("div", { key: "txt", style: { display: "grid", gap: "2px" } }, [
                        React.createElement("span", { key: "a" }, `${fromName} -> ${toName}`),
                        React.createElement("span", { key: "b", className: "muted" }, r.relationship_type),
                      ]),
                  isEditing
                    ? null
                    : React.createElement("div", { key: "actions", style: { display: "flex", gap: "6px" } }, [
                        React.createElement(
                          "button",
                          {
                            key: "edit",
                            type: "button",
                            className: "ghost",
                            onClick: () => startEditRelationship(r),
                            disabled: !canEditRecords,
                          },
                          "Edit"
                        ),
                        React.createElement(
                          "button",
                          {
                            key: "del",
                            type: "button",
                            className: "ghost",
                            onClick: () => {
                              if (window.confirm("Delete this relationship?")) {
                                deleteRelationship(r.id, r.circle_id).catch((x) => setStatus(x.message));
                              }
                            },
                            disabled: !canEditRecords,
                          },
                          "Delete"
                        ),
                      ]),
                ]);
              })
            ),
            relationships.length > PANEL_ROW_LIMIT
              ? React.createElement("button", {
                  className: "ghost list-expander",
                  key: "relationships-more",
                  type: "button",
                  "aria-expanded": relationshipListExpanded ? "true" : "false",
                  onClick: () => setRelationshipListExpanded((expanded) => !expanded),
                }, relationshipListExpanded ? `Show first ${PANEL_ROW_LIMIT} relationships` : `Show all ${relationships.length} relationships`)
              : null,
          ]),
        ]) : null
      ]),

      React.createElement("main", { className: "graph-wrap", key: "center" }, [
        React.createElement("div", { className: "graph-scroll", key: "scroll", ref: graphViewportRef }, [
          React.createElement("div", { style: { padding: "12px 12px 0 12px" }, key: "controls" }, [
            React.createElement("div", { className: "status-badge", key: "st", "aria-live": "polite" }, workspaceStatus),
            !isAuthenticated
              ? React.createElement("section", { className: "auth-gate", key: "auth-gate", role: "region", "aria-label": "Sign in to continue" }, [
                  React.createElement("div", { className: "auth-gate-eyebrow", key: "e" }, "Private family archive"),
                  React.createElement("h1", { key: "h" }, authState === "checking"
                    ? "Checking this deployment"
                    : (authState === "unavailable"
                        ? "Authentication is locked for this deployment"
                        : "Continue your family archive")),
                  React.createElement("p", { key: "p" }, authState === "checking"
                    ? "Loading the server security mode before requesting any private family data."
                    : (authState === "unavailable"
                        ? (runtimeConfig?.warning || "Access remains closed until authentication is configured.")
                        : (managedAuthAvailable ? "Sign in with Google to create a private family circle. Add people, connect relatives, and return to your saved work on any device." : "Choose an existing user or create your first archive steward to begin."))),
                  managedAuthAvailable && authState !== "checking" && authState !== "unavailable"
                    ? React.createElement("p", { className: "auth-gate-access", key: "access" },
                        "Live access is currently limited to approved Google test accounts. If your account has not been added, contact the project owner to request access.")
                    : null,
                  authState === "checking"
                    ? React.createElement("div", { className: "muted", key: "checking", role: "status" }, "Checking security mode…")
                    : (authState === "unavailable"
                        ? React.createElement("div", { className: "muted", key: "locked", role: "status" }, "No user directory or family data has been loaded.")
                        : React.createElement("div", { className: "auth-gate-actions", key: "a" }, [
                        React.createElement("button", {
                          key: "continue",
                          type: "button",
                          onClick: () => loginAsActiveUser().catch((x) => setStatus(x.message)),
                          disabled: !managedAuthAvailable && !activeUserId,
                        }, managedAuthAvailable ? "Continue with Google" : (activeUserName ? `Continue as ${activeUserName}` : "Select a user to continue")),
                        !managedAuthAvailable && React.createElement("button", {
                          key: "choose",
                          type: "button",
                          className: "ghost",
                          onClick: () => setLeftOpen(true),
                        }, "Choose another user"),
                      ])),
                ])
              : React.createElement("form", { onSubmit: (e) => loadSubgraph(e).catch((x) => setStatus(x.message)), key: "f" }, [
              React.createElement("div", { className: "person-finder", key: "person-finder" }, [
                React.createElement("label", { htmlFor: "person-finder-input", key: "label" }, "Find a person"),
                React.createElement("input", {
                  id: "person-finder-input",
                  key: "input",
                  ref: personSearchInputRef,
                  type: "search",
                  value: personSearchQuery,
                  placeholder: persons.length ? "Name, birthplace, year, or occupation" : "No people in this circle yet",
                  disabled: circleDataLoading || persons.length === 0,
                  autoComplete: "off",
                  role: "combobox",
                  "aria-autocomplete": "list",
                  "aria-controls": "person-finder-results",
                  "aria-expanded": personSearchFocused && Boolean(personSearchQuery.trim()),
                  "aria-activedescendant": personSearchFocused && personSearchResults.length
                    ? `person-finder-option-${Math.min(personSearchActiveIndex, personSearchResults.length - 1)}`
                    : undefined,
                  onFocus: () => setPersonSearchFocused(true),
                  onBlur: () => setPersonSearchFocused(false),
                  onChange: (e) => setPersonSearchQuery(e.target.value),
                  onKeyDown: handlePersonSearchKeyDown,
                }),
                personSearchFocused && personSearchQuery.trim()
                  ? (personSearchResults.length
                      ? React.createElement("div", {
                          className: "person-finder-results",
                          id: "person-finder-results",
                          key: "results",
                          role: "listbox",
                          "aria-label": "Matching people",
                        }, personSearchResults.map((person, index) => React.createElement("button", {
                          className: `person-finder-option ${index === personSearchActiveIndex ? "active" : ""}`.trim(),
                          id: `person-finder-option-${index}`,
                          key: person.id,
                          type: "button",
                          role: "option",
                          "aria-selected": index === personSearchActiveIndex,
                          onMouseDown: (e) => e.preventDefault(),
                          onMouseEnter: () => setPersonSearchActiveIndex(index),
                          onClick: () => choosePersonSearchResult(person),
                        }, [
                          React.createElement("strong", { key: "name" }, person.full_name || "Unnamed family member"),
                          React.createElement("span", { key: "details" }, [person.birth_date, person.birth_place, person.occupation].filter(Boolean).join(" · ") || "No additional details"),
                        ])))
                      : React.createElement("div", { className: "person-finder-empty", key: "empty", role: "status" }, "No matching people"))
                  : null,
              ]),
              React.createElement("div", { className: "graph-controls-grid", key: "g" }, [
                React.createElement("div", { className: "graph-root-choice", key: "p" }, [
                  React.createElement("input", {
                    key: "value",
                    type: "hidden",
                    name: "root_person_id",
                    value: effectiveGraphRootPersonId,
                    readOnly: true,
                  }),
                  React.createElement("span", { className: "graph-root-label", key: "label" }, "Graph root"),
                  React.createElement("strong", { key: "name" }, effectiveGraphRootPersonName),
                  React.createElement("button", {
                    className: "graph-root-change",
                    key: "change",
                    type: "button",
                    disabled: persons.length === 0,
                    onClick: focusPersonFinder,
                  }, "Find another"),
                ]),
                React.createElement(GraphControlField, { key: "d", label: "Direction" },
                  React.createElement("select", { key: "control", name: "direction", "aria-label": "Traversal direction" }, [
                    React.createElement("option", { key: "desc", value: "descendants" }, "descendants"),
                    React.createElement("option", { key: "anc", value: "ancestors" }, "ancestors"),
                  ])),
                React.createElement(GraphControlField, { key: "depth", label: "Depth" },
                  React.createElement("input", { key: "control", type: "number", name: "depth", min: 1, max: 10, defaultValue: 2, "aria-label": "Traversal depth" })),
                React.createElement(GraphControlField, { key: "m", label: "Family scope" },
                  React.createElement("select", { key: "control", name: "mode", defaultValue: "lineage", "aria-label": "Graph mode" }, [
                    React.createElement("option", { key: "l", value: "lineage" }, "lineage"),
                    React.createElement("option", { key: "f", value: "family_expanded" }, "family expanded"),
                  ])),
                React.createElement(GraphControlField, { key: "layout_mode", label: "Layout" },
                  React.createElement("select", { key: "control", name: "layout_mode", value: lastLayoutMode, onChange: (e) => setLastLayoutMode(e.target.value), "aria-label": "Graph layout" }, [
                    React.createElement("option", { key: "h", value: "hierarchy" }, "hierarchy"),
                    React.createElement("option", { key: "t", value: "time_aligned" }, "time aligned"),
                  ])),
                React.createElement(GraphControlField, { key: "ld", label: "Side hops" },
                  React.createElement("input", { key: "control", type: "number", name: "lateral_depth", min: 0, max: 4, defaultValue: 1, "aria-label": "Lateral relationship depth" })),
                React.createElement(GraphControlField, { key: "lt", label: "Side relationships", className: "graph-control-wide" },
                  React.createElement("input", { key: "control", name: "lateral_types", defaultValue: "spouse_of,sibling_of,cousin_of", placeholder: "spouse, sibling, cousin", "aria-label": "Lateral relationship types" })),
                React.createElement("button", { className: "graph-render-button", key: "b", type: "submit", disabled: !effectiveGraphRootPersonId }, "Render Graph"),
              ]),
              graphRenderStats
                ? React.createElement("div", {
                    className: `graph-performance ${graphRenderStats.duration_ms <= graphRenderStats.budget_ms ? "" : "over-budget"}`.trim(),
                    key: "performance",
                    role: "status",
                    "aria-live": "polite",
                    "data-testid": "graph-performance",
                  }, [
                    React.createElement("strong", { key: "mode" }, graphRenderStats.large_graph_mode ? "Performance overview" : "Detailed cards"),
                    React.createElement("span", { key: "size" }, `${graphRenderStats.node_count} people · ${graphRenderStats.edge_count} relationships`),
                    React.createElement("span", { key: "frame" }, `First frame ${Math.round(graphRenderStats.duration_ms)} ms · ${graphRenderStats.duration_ms <= graphRenderStats.budget_ms ? "within" : "over"} 1.2 s target`),
                  ])
                : null,
            ])
          ]),
          isAuthenticated ? (lastLayoutMode === "time_aligned"
            ? React.createElement("section", { className: `time-aligned-shell ${timeTimelineOpen ? "" : "timeline-collapsed"}`.trim(), key: "time-shell" }, [
                timeTimelineOpen
                  ? React.createElement("aside", { className: "historical-panel", key: "timeline" }, [
                      React.createElement("div", { className: "historical-panel-head", key: "h" }, [
                        React.createElement("div", { className: "historical-panel-title", key: "t" }, "Historical Tapestry"),
                        React.createElement("button", { className: "btn", key: "c", type: "button", onClick: () => setTimeTimelineOpenAnchored(false) }, "Hide"),
                      ]),
                      React.createElement("div", { className: "historical-list", key: "lst" },
                        historicalTimelineItems.length
                          ? historicalTimelineItems.map((evt, idx) =>
                              React.createElement("div", { className: "historical-item", key: evt.id }, [
                                React.createElement("span", { className: "historical-dot", key: "d" }),
                                React.createElement("div", { className: "historical-year", key: "y" }, evt.yearLabel),
                                React.createElement("div", { className: "historical-event", key: "t" }, evt.title),
                                React.createElement("div", { className: "historical-desc", key: "x" }, evt.description),
                                (evt.description && evt.description.length > 90) || idx % 4 === 1
                                  ? React.createElement("div", { className: "historical-media", key: "m" }, [
                                      React.createElement("span", { className: "historical-media-tag", key: "tag" }, "Archival Visual"),
                                    ])
                                  : null,
                              ])
                            )
                          : [React.createElement("div", { className: "muted", key: "none" }, "Add context events to populate timeline.")])
                    ])
                  : null,
                React.createElement("div", { className: "time-graph-stage", key: "g" }, [
                  !timeTimelineOpen
                    ? React.createElement(
                        "button",
                        {
                          className: "timeline-reveal-btn",
                          key: "show-timeline",
                          type: "button",
                          onClick: () => setTimeTimelineOpenAnchored(true),
                          title: "Show timeline",
                          "aria-label": "Show timeline",
                        },
                        "▸"
                      )
                    : null,
                  React.createElement(GraphView, {
                    key: "graph",
                    subgraph,
                    rootPersonId: lastRoot,
                    layoutMode: lastLayoutMode,
                    contextEvents,
                    mediaPreviewByPersonId,
                    zoom,
                    selectedNodeId: selectedPersonId,
                    newArrivalId,
                    highlightedNodeIds: highlightedNodeSet,
                    highlightedEdgeKeys: highlightedEdgeSet,
                    onNodeClick: applyPersonFocus,
                    onRenderComplete: handleGraphRenderComplete,
                    renderStartedAt: graphRenderStartedAtRef.current,
                  }),
                ]),
              ])
            : React.createElement(React.Fragment, { key: "journey-default" }, [
                !isLargeSubgraph ? React.createElement("section", { className: "lineage-journey", key: "lineage-journey" }, [
                  React.createElement("div", { className: "lineage-journey-head", key: "h" }, [
                    React.createElement("div", { className: "lineage-journey-title", key: "t" }, "Lineage Journey"),
                    React.createElement("div", { className: "muted", key: "m" }, lineageJourneyItems.length ? `${lineageJourneyItems.length} profiles` : "Render a graph to build timeline"),
                  ]),
                  React.createElement("div", { className: "lineage-journey-subtitle", key: "sub" }, "Tracing roots from earliest known ancestors through defining world events."),
                  React.createElement("div", { className: "lineage-journey-rail", key: "trk" },
                    lineageJourneyItems.length
                      ? lineageJourneyItems.map((item, idx) =>
                          React.createElement("div", { className: `journey-row ${idx % 2 ? "flip" : ""}`, key: item.id }, [
                            React.createElement("div", { className: "journey-person", key: "p" },
                              React.createElement("button", {
                                type: "button",
                                className: "journey-person-card",
                                onMouseDown: (e) => e.preventDefault(),
                                onClick: () => applyPersonFocus(item.id),
                              }, [
                                React.createElement("div", { className: "journey-person-head", key: "ph" }, [
                                  React.createElement("div", { className: "lineage-name", key: "n" }, item.name),
                                  React.createElement("span", { className: "journey-chip", key: "c" }, item.badge),
                                ]),
                                React.createElement("div", { className: "lineage-years", key: "y" }, `${item.birthDate || "?"} — ${item.deathDate || "present"}`),
                                React.createElement("div", { className: "muted", key: "bp" }, item.birthPlace || "Birthplace unknown"),
                              ])
                            ),
                            React.createElement("div", { className: "journey-center", key: "d" }, React.createElement("span", { className: "journey-dot" })),
                            React.createElement("div", { className: "journey-context", key: "ctx" }, [
                              React.createElement("div", { className: "journey-context-label", key: "lbl" }, `World Events • ${(item.birthDate || item.deathDate || "").slice(0, 4) || "Era"}`),
                              ...(item.worldEvents.length
                                ? item.worldEvents.map((evt, i) => React.createElement("div", { key: `e-${i}` }, `• ${evt}`))
                                : [React.createElement("div", { className: "muted", key: "none" }, "No mapped world events for this year.")]),
                            ]),
                          ])
                        )
                      : [React.createElement("div", { className: "muted", key: "empty" }, "Timeline entries appear here after graph render.")]
                  )
                ]) : null,
                React.createElement(GraphView, {
                  key: "graph",
                  subgraph,
                  rootPersonId: lastRoot,
                  layoutMode: lastLayoutMode,
                  contextEvents,
                  mediaPreviewByPersonId,
                  zoom,
                  selectedNodeId: selectedPersonId,
                  newArrivalId,
                  highlightedNodeIds: highlightedNodeSet,
                  highlightedEdgeKeys: highlightedEdgeSet,
                  onNodeClick: applyPersonFocus,
                  onRenderComplete: handleGraphRenderComplete,
                  renderStartedAt: graphRenderStartedAtRef.current,
                }),
              ])) : null,
        ])
      ]),

      React.createElement("aside", { className: `sidebar ${rightOpen ? "" : "collapsed"}`, key: "right" }, [
        React.createElement("div", { className: "sidebar-head", key: "h" }, [
          React.createElement("span", { key: "txt" }, "Context & Collaboration"),
          React.createElement("button", { className: "btn", key: "b", onClick: () => setRightOpen((v) => !v) }, rightOpen ? "▶" : "◀"),
        ]),
        rightOpen ? React.createElement("div", { className: "sidebar-body", key: "body" }, [
          React.createElement("details", { className: "card", open: true, key: "profile" }, [
            React.createElement("summary", { key: "s" }, "Selected Person"),
            selectedPerson
              ? React.createElement("div", { key: "p" }, [
                  React.createElement("div", { style: { fontWeight: 700, marginBottom: "6px" }, key: "n" }, selectedPerson.full_name),
                  React.createElement("div", { className: "muted", key: "r" }, `Birth: ${selectedPerson.birth_date || "Unknown"} ${selectedPerson.birth_place ? "• " + selectedPerson.birth_place : ""}`),
                  !canEditRecords
                    ? React.createElement("div", { className: "profile-readonly-note", key: "readonly", role: "status" }, "Viewer mode · profile details are read-only")
                    : null,
                  React.createElement("form", { key: `edit-${selectedPerson.id}`, onSubmit: (e) => updatePersonProfile(e).catch((x) => setStatus(x.message)) }, [
                    React.createElement("input", { key: "f1", name: "full_name", "aria-label": "Full name", required: true, defaultValue: selectedPerson.full_name || "", ...profileFieldAccessProps }),
                    React.createElement("input", { key: "f2", name: "religion", "aria-label": "Religion", placeholder: "Religion", defaultValue: selectedPerson.religion || "", ...profileFieldAccessProps }),
                    React.createElement("input", { key: "f3", name: "sex", "aria-label": "Sex", placeholder: "Sex", defaultValue: selectedPerson.sex || "", ...profileFieldAccessProps }),
                    React.createElement("input", { key: "f4", type: "date", name: "birth_date", "aria-label": "Birth date", defaultValue: selectedPerson.birth_date || "", ...profileFieldAccessProps }),
                    React.createElement("input", { key: "f5", type: "date", name: "death_date", "aria-label": "Death date", defaultValue: selectedPerson.death_date || "", ...profileFieldAccessProps }),
                    React.createElement("input", { key: "f6", name: "birth_place", "aria-label": "Birth place", placeholder: "Birth place", defaultValue: selectedPerson.birth_place || "", ...profileFieldAccessProps }),
                    React.createElement("input", { key: "f7", name: "occupation", "aria-label": "Occupation", placeholder: "Occupation", defaultValue: selectedPerson.occupation || "", ...profileFieldAccessProps }),
                    React.createElement("input", { key: "f8", name: "hobbies", "aria-label": "Hobbies", placeholder: "Hobbies", defaultValue: selectedPerson.hobbies || "", ...profileFieldAccessProps }),
                    React.createElement("input", { key: "f9", name: "personality", "aria-label": "Personality", placeholder: "Personality", defaultValue: selectedPerson.personality || "", ...profileFieldAccessProps }),
                    canEditRecords
                      ? React.createElement("textarea", { key: "f10", name: "medical_notes", "aria-label": "Medical notes", placeholder: "Medical notes (owners and editors only)", defaultValue: selectedPerson.medical_notes || "" })
                      : React.createElement("div", { className: "muted sensitive-field-notice", key: "f10" }, "Medical notes are visible only to owners and editors."),
                    React.createElement("textarea", { key: "f11", name: "bio_text", "aria-label": "Biography and oral history notes", placeholder: "Biography / oral history notes", defaultValue: selectedPerson.bio_text || "", ...profileFieldAccessProps }),
                    canEditRecords
                      ? React.createElement("input", { key: "f12", name: "revision_reason", "aria-label": "Revision reason", placeholder: "Revision reason (optional)" })
                      : null,
                    canEditRecords
                      ? React.createElement("button", { key: "f13", type: "submit" }, "Save Profile")
                      : null,
                  ]),
                ])
              : React.createElement("div", { className: "muted", key: "x" }, "Click a node to inspect profile details."),
          ]),
          React.createElement(LazyDetails, {
            className: "card",
            key: `revisions-${selectedCircle}`,
            summary: "Revision History",
            onFirstOpen: () => setRevisionsPanelActivated(true),
          }, () => [
            React.createElement("div", { className: "list", key: "l" },
              personRevisionsLoading
                ? React.createElement("div", { className: "muted", role: "status" }, "Loading revision history…")
                : (!selectedPersonId
                    ? React.createElement("div", { className: "muted" }, "Select a person to view revision history")
                    : (personRevisions.length
                        ? personRevisions.map((rev) => {
                let religion = "N/A";
                let occupation = "N/A";
                let birthPlace = "N/A";
                try {
                  const snap = JSON.parse(rev.snapshot_json);
                  religion = snap.religion || "N/A";
                  occupation = snap.occupation || "N/A";
                  birthPlace = snap.birth_place || "N/A";
                } catch (_) {
                  religion = "N/A";
                  occupation = "N/A";
                  birthPlace = "N/A";
                }
                return React.createElement("div", { className: "item", key: rev.id }, [
                  React.createElement("div", { key: "r" }, `Rev ${rev.revision_no} • ${rev.reason || "manual"}`),
                  React.createElement("div", { className: "muted", key: "t" }, rev.created_at.slice(0, 19).replace("T", " ")),
                  React.createElement("div", { className: "muted", key: "f1" }, `Religion: ${religion}`),
                  React.createElement("div", { className: "muted", key: "f2" }, `Occupation: ${occupation}`),
                  React.createElement("div", { className: "muted", key: "f3" }, `Birth place: ${birthPlace}`),
                ]);
              })
                        : React.createElement("div", { className: "muted" }, "No revision history for this person")))
            ),
          ]),
          React.createElement(LazyDetails, {
            className: "card",
            key: `discussion-${selectedCircle}`,
            summary: "Discussion",
            onFirstOpen: () => setDiscussionPanelActivated(true),
          }, () => [
            React.createElement("div", { className: "muted", key: "hint", role: discussionLoading ? "status" : undefined }, discussionLoading
              ? "Loading discussion…"
              : (selectedPerson
                  ? (discussionThreadId ? `Thread for ${selectedPerson.full_name}` : `No discussion yet for ${selectedPerson.full_name}`)
                  : "Select a person to open discussion")),
            React.createElement("form", { key: "f", onSubmit: (e) => sendDiscussionMessage(e).catch((x) => setStatus(x.message)) }, [
              React.createElement("input", { key: "i", name: "content", required: true, placeholder: "Add family memory or note..." }),
              React.createElement("button", { key: "b", type: "submit", disabled: !selectedPersonId || !isAuthenticated }, discussionThreadId ? "Send" : "Start discussion"),
            ]),
            React.createElement("div", { className: "list", key: "l" },
              discussionMessages.map((m) => {
                const sender = users.find((u) => u.id === m.sender_user_id);
                return React.createElement("div", { className: "item", key: m.id }, [
                  React.createElement("div", { key: "c" }, m.content),
                  React.createElement("div", { className: "muted", key: "m" }, `${sender ? sender.display_name : m.sender_user_id.slice(0, 8)} • ${m.created_at.slice(0, 19).replace("T", " ")}`),
                ]);
              })
            ),
          ]),
          React.createElement(LazyDetails, {
            className: "card",
            key: `media-${selectedCircle}`,
            summary: "Media",
            onFirstOpen: () => setMediaPanelActivated(true),
          }, () => [
            React.createElement("form", { key: "f", onSubmit: (e) => uploadMedia(e).catch((x) => setStatus(x.message)) }, [
              React.createElement(PersonPanelSubject, { key: "p", personId: selectedPersonId, personName: selectedPerson?.full_name, onFind: focusPersonFinder }),
              React.createElement("input", { key: "i", type: "file", name: "file", accept: managedAuthAvailable ? ".jpg,.jpeg,.png" : MEDIA_ACCEPT, disabled: mediaUploadBusy }),
              React.createElement("div", { className: "muted", key: "policy" }, managedAuthAvailable
                ? "JPEG or PNG images only. Limit: 5 MiB for this hosted demo."
                : "JPEG, PNG, WebP, GIF, HEIC, TIFF, PDF, text, MP3, WAV, M4A, MP4, or MOV. Server limit: 25 MiB by default."),
              React.createElement("button", { key: "b", type: "submit", disabled: !selectedPersonId || !canEditRecords || mediaUploadBusy }, mediaUploadBusy ? "Uploading…" : "Upload"),
            ]),
            React.createElement("div", { className: "list", key: "l" },
              personMediaLoading
                ? React.createElement("div", { className: "muted", role: "status" }, "Loading media…")
                : (!selectedPersonId
                    ? React.createElement("div", { className: "muted" }, "Select a person to view media")
                    : (personMedia.length
                        ? personMedia.map((m) =>
                React.createElement("div", { className: "item", key: m.id }, [
                  React.createElement("div", { key: "n" }, m.original_filename),
                  React.createElement("div", { className: "muted", key: "x" }, `${formatFileSize(m.bytes)}${m.mime_type ? ` • ${m.mime_type}` : ""}`),
                  React.createElement(
                    "a",
                    {
                      key: "d",
                      href: activeMediaTicket
                        ? `/circles/${selectedCircle}/media/${m.id}/download?ticket=${encodeURIComponent(activeMediaTicket)}`
                        : undefined,
                      target: "_blank",
                      rel: "noreferrer",
                      "aria-disabled": activeMediaTicket ? undefined : "true",
                      onClick: (event) => {
                        if (!activeMediaTicket) event.preventDefault();
                      },
                    },
                    activeMediaTicket ? "Open" : "Preparing secure link…"
                  ),
                ])
              )
                        : React.createElement("div", { className: "muted" }, "No media for this person")))
            ),
          ]),
          React.createElement(LazyDetails, {
            className: "card",
            key: `places-${selectedCircle}`,
            summary: "Places & Migration",
            onFirstOpen: () => setPlacesPanelActivated(true),
          }, () => [
            React.createElement("form", { className: "migration-panel", key: "f", onSubmit: (e) => addPersonPlace(e).catch((x) => setStatus(x.message)) }, [
              React.createElement(PersonPanelSubject, { key: "p", personId: selectedPersonId, personName: selectedPerson?.full_name, onFind: focusPersonFinder }),
              React.createElement("input", { key: "name", name: "place_name", required: true, placeholder: "Place name" }),
              React.createElement("input", { key: "country", name: "country", placeholder: "Country" }),
              React.createElement("input", { key: "lat", name: "lat", type: "number", step: "any", placeholder: "Latitude" }),
              React.createElement("input", { key: "lng", name: "lng", type: "number", step: "any", placeholder: "Longitude" }),
              React.createElement("input", { key: "from", name: "from_date", type: "date" }),
              React.createElement("input", { key: "to", name: "to_date", type: "date" }),
              React.createElement("input", { key: "notes", name: "notes", placeholder: "Notes" }),
              React.createElement("button", { key: "b", type: "submit", disabled: !selectedPersonId || !canEditRecords }, "Add Place"),
              React.createElement("button", { key: "b2", className: "ghost", type: "button", disabled: !selectedPersonId, onClick: () => loadMigrationGeojson(selectedPersonId).catch((x) => setStatus(x.message)) }, "Load Migration GeoJSON"),
            ]),
            React.createElement("div", { className: "muted", key: "sgm-head" }, "Subgraph Migration"),
            React.createElement("div", { className: "migration-panel", key: "sgm-controls" }, [
              React.createElement("button", { key: "load", type: "button", className: "ghost", disabled: !lastRoot, onClick: () => loadSubgraphMigrationGeojson("").catch((x) => setStatus(x.message)) }, "Load Subgraph Migration"),
              React.createElement("div", { className: "muted", key: "hint" }, subgraphMigrationDates.length ? `As of ${subgraphMigrationDates[subgraphMigrationIndex]}` : "Load migration to enable playback"),
              React.createElement("input", {
                key: "slider",
                type: "range",
                min: 0,
                max: Math.max(0, subgraphMigrationDates.length - 1),
                value: Math.min(subgraphMigrationIndex, Math.max(0, subgraphMigrationDates.length - 1)),
                disabled: subgraphMigrationDates.length === 0,
                onChange: (e) => setSubgraphMigrationCursor(Number(e.target.value)),
              }),
              React.createElement("button", {
                key: "play",
                type: "button",
                className: "btn",
                disabled: subgraphMigrationDates.length <= 1,
                onClick: () => setIsSubgraphMigrationPlaying((v) => !v),
              }, isSubgraphMigrationPlaying ? "Pause Playback" : "Play Playback"),
            ]),
            subgraphMigrationGeoJson
              ? React.createElement(
                  "a",
                  {
                    key: "sgm-geo",
                    href: `data:application/json;charset=utf-8,${encodeURIComponent(JSON.stringify(subgraphMigrationGeoJson, null, 2))}`,
                    download: `subgraph_migration_${lastRoot || "root"}.geojson`,
                  },
                  "Download Subgraph Migration GeoJSON"
                )
              : null,
            subgraphMigrationGeoJson
              ? React.createElement("div", { className: "migration-panel", key: "sgm-viz" }, [
                  React.createElement("div", { className: "muted", key: "sgm-viz-title", style: { marginBottom: "6px" } }, "Playback View (projected migration paths)"),
                  React.createElement("svg", { key: "sgm-svg", width: "100%", viewBox: `0 0 ${subgraphMigrationView.width} ${subgraphMigrationView.height}` }, [
                    React.createElement("rect", {
                      key: "bg",
                      x: 0,
                      y: 0,
                      width: subgraphMigrationView.width,
                      height: subgraphMigrationView.height,
                      fill: "#f7fafc",
                      stroke: "#d2dde8",
                    }),
                    ...subgraphMigrationView.lines.map((line) =>
                      React.createElement("path", {
                        key: line.key,
                        d: line.d,
                        fill: "none",
                        stroke: "#91a8ba",
                        strokeWidth: 2.5,
                        strokeLinecap: "round",
                      })
                    ),
                    ...subgraphMigrationView.points.map((pt) =>
                      React.createElement("g", { key: pt.key }, [
                        React.createElement("circle", {
                          key: "c",
                          cx: pt.x,
                          cy: pt.y,
                          r: 4.8,
                          fill: "#1e6c6d",
                          stroke: "#ffffff",
                          strokeWidth: 1.4,
                        }),
                        React.createElement("text", {
                          key: "t",
                          x: pt.x + 7,
                          y: pt.y - 7,
                          fontSize: 10,
                          fill: "#345",
                        }, `${pt.label}${pt.fromDate ? ` (${pt.fromDate})` : ""}`),
                      ])
                    ),
                  ]),
                ])
              : null,
            migrationGeoJson
              ? React.createElement(
                  "a",
                  {
                    key: "geo",
                    href: `data:application/json;charset=utf-8,${encodeURIComponent(JSON.stringify(migrationGeoJson, null, 2))}`,
                    download: `migration_${selectedPersonId || "person"}.geojson`,
                  },
                  "Download Selected Person GeoJSON"
                )
              : null,
            React.createElement("div", { className: "list", key: "l" },
              personPlacesLoading
                ? React.createElement("div", { className: "muted", role: "status" }, "Loading places…")
                : (!selectedPersonId
                    ? React.createElement("div", { className: "muted" }, "Select a person to view places")
                    : (personPlaces.length
                        ? personPlaces.map((pl) =>
                React.createElement("div", { className: "item", key: pl.id }, [
                  React.createElement("div", { key: "t" }, `${pl.place_name}${pl.country ? `, ${pl.country}` : ""}`),
                  React.createElement("div", { className: "muted", key: "d" }, `${pl.from_date || "?"} -> ${pl.to_date || "?"}`),
                  React.createElement("button", { key: "v", type: "button", className: "btn", onClick: () => setSelectedPlace(pl) }, "Map options"),
                ])
              )
                        : React.createElement("div", { className: "muted" }, "No places for this person")))
            ),
            selectedPlace
              ? React.createElement("div", { className: "external-map-consent", key: "map-options" }, [
                  React.createElement("div", { className: "external-map-consent-head", key: "head" }, [
                    React.createElement("strong", { key: "title" }, `${selectedPlace.place_name}${selectedPlace.country ? `, ${selectedPlace.country}` : ""}`),
                    React.createElement("button", { key: "close", type: "button", className: "ghost", onClick: () => setSelectedPlace(null), "aria-label": "Close map options" }, "Close"),
                  ]),
                  React.createElement("p", { className: "muted", key: "privacy" },
                    "Viraasat does not load an external map automatically. Opening the map shares this location and your network metadata with Google in a new tab."
                  ),
                  selectedPlace.lat != null && selectedPlace.lng != null
                    ? React.createElement("div", { className: "muted", key: "coordinates" }, `Coordinates: ${selectedPlace.lat}, ${selectedPlace.lng}`)
                    : null,
                  externalMapUrl
                    ? React.createElement("a", {
                        className: "btn external-map-link",
                        href: externalMapUrl,
                        key: "open",
                        target: "_blank",
                        rel: "noopener noreferrer",
                        onClick: () => setStatus("Opening an external map in a new tab"),
                      }, "Open Google Maps")
                    : React.createElement("div", { className: "muted", key: "unavailable" }, "This place does not have enough location information to open a map."),
                ])
              : null,
          ]),
          React.createElement(LazyDetails, { className: "card", key: "cr", summary: "Change Requests" }, () => [
            React.createElement("form", { key: "f", onSubmit: (e) => createChangeRequest(e).catch((x) => setStatus(x.message)) }, [
              React.createElement("select", { key: "p", name: "entity_id" }, personOptions.map((p) => React.createElement("option", { key: p.value, value: p.value }, p.label))),
              React.createElement("input", { key: "r", name: "religion", placeholder: "Proposed religion value" }),
              React.createElement("button", { key: "b", type: "submit", disabled: personOptions.length === 0 }, "Propose"),
            ]),
            React.createElement("div", { className: "list", key: "l" },
              changeRequests.map((cr) => React.createElement("div", { className: "item", key: cr.id }, [
                React.createElement("div", { key: "s" }, `Status: ${cr.status}`),
                React.createElement("div", { className: "muted", key: "p" }, cr.proposed_patch_json),
                cr.status === "pending" ? React.createElement("div", { key: "a", style: { marginTop: "6px" } }, [
                  React.createElement("button", { key: "ap", type: "button", onClick: () => reviewRequest(cr.id, "approve").catch((x) => setStatus(x.message)), disabled: !canEditRecords }, "Approve"),
                  React.createElement("button", { key: "rj", type: "button", className: "ghost", onClick: () => reviewRequest(cr.id, "reject").catch((x) => setStatus(x.message)), disabled: !canEditRecords }, "Reject"),
                ]) : null
              ]))
            ),
          ]),
          React.createElement(LazyDetails, { className: "card", key: "ctx", summary: "Context Events" }, () => [
            React.createElement("form", { key: "f", onSubmit: (e) => createContextEvent(e).catch((x) => setStatus(x.message)) }, [
              React.createElement("input", { key: "d", type: "date", name: "date", required: true }),
              React.createElement("input", { key: "t", name: "title", required: true, placeholder: "Event title" }),
              React.createElement("select", { key: "e", name: "event_type" }, [
                React.createElement("option", { key: "w", value: "world" }, "world"),
                React.createElement("option", { key: "p", value: "political" }, "political"),
                React.createElement("option", { key: "s", value: "social" }, "social"),
                React.createElement("option", { key: "t", value: "technology" }, "technology"),
                React.createElement("option", { key: "f", value: "family" }, "family"),
              ]),
              React.createElement("input", { key: "l", name: "location_name", placeholder: "Location" }),
              React.createElement("input", { key: "x", name: "description", placeholder: "Description" }),
              React.createElement("button", { key: "b", type: "submit", disabled: !selectedCircle || !canEditRecords }, "Add Event"),
            ]),
            React.createElement("form", { key: "lnk", onSubmit: (e) => linkEventToPerson(e).catch((x) => setStatus(x.message)) }, [
              React.createElement("select", { key: "p1", name: "person_id" }, personOptions.map((p) => React.createElement("option", { key: p.value, value: p.value }, p.label))),
              React.createElement("select", { key: "e1", name: "context_event_id" }, contextEvents.map((e) => React.createElement("option", { key: e.id, value: e.id }, `${e.date} ${e.title}`))),
              React.createElement("input", { key: "rn", name: "relevance_note", placeholder: "Relevance note" }),
              React.createElement("button", { key: "b2", type: "submit", disabled: personOptions.length === 0 || contextEvents.length === 0 || !canEditRecords }, "Link Event"),
            ]),
            React.createElement("div", { className: "list", key: "lst" },
              contextEvents.map((e) => React.createElement("div", { className: "item", key: e.id }, `${e.date} • ${e.title}`))
            ),
          ]),
          React.createElement(LazyDetails, { className: "card", key: "tl", summary: "Timeline" }, () => [
            React.createElement("form", { key: "f", onSubmit: (e) => loadTimeline(e).catch((x) => setStatus(x.message)) }, [
              React.createElement("select", { key: "p", name: "person_id" }, personOptions.map((p) => React.createElement("option", { key: p.value, value: p.value }, p.label))),
              React.createElement("select", { key: "scope", value: timelineScope, onChange: (e) => setTimelineScope(e.target.value) }, [
                React.createElement("option", { key: "person", value: "person" }, "person"),
                React.createElement("option", { key: "subgraph", value: "subgraph" }, "subgraph"),
              ]),
              React.createElement("input", { key: "from", type: "date", value: timelineFromDate, onChange: (e) => setTimelineFromDate(e.target.value), placeholder: "From date" }),
              React.createElement("input", { key: "to", type: "date", value: timelineToDate, onChange: (e) => setTimelineToDate(e.target.value), placeholder: "To date" }),
              React.createElement("input", { key: "et", value: timelineEventTypes, onChange: (e) => setTimelineEventTypes(e.target.value), placeholder: "event types: world,political..." }),
              React.createElement("button", { key: "b", type: "submit", disabled: personOptions.length === 0 }, "Load Timeline"),
            ]),
            React.createElement("div", { className: "list", key: "l" },
              timeline.map((t, i) => React.createElement(
                "div",
                {
                  className: "item",
                  key: `${t.date}-${i}`,
                  onClick: () => onTimelineItemClick(t).catch((x) => setStatus(x.message)),
                  style: { cursor: "pointer" }
                },
                [
                  React.createElement("span", { className: "timeline-dot", style: { background: t.kind === "life" ? "#1e6c6d" : "#d18b3d" }, key: "dot" }),
                  `${t.date} • ${t.title}`
                ]
              ))
            ),
          ]),
          React.createElement(LazyDetails, { className: "card", key: "audit", summary: "Audit Logs" }, () => [
            React.createElement("div", { className: "list", key: "l" },
              auditLogs.map((a) => React.createElement("div", { className: "item", key: a.id }, [
                React.createElement("div", { key: "x" }, `${a.action} • ${a.entity_type}`),
                React.createElement("div", { className: "muted", key: "t" }, `${(a.actor_user_id || "").slice(0, 8)} • ${a.created_at.slice(0, 19).replace("T", " ")}`),
              ]))
            ),
          ]),
        ]) : null
      ]),
    ]),
      personJourneyOpen && isAuthenticated && selectedCircle && canEditRecords
        ? React.createElement(PersonJourney, { key: "person-journey", people: persons, onClose: () => setPersonJourneyOpen(false), onReveal: revealNewPerson, onCheckDuplicates: checkJourneyDuplicates, onSave: savePersonJourney, onRetryLink: finishPersonJourney })
        : null,
  ]);
}

ReactDOM.createRoot(document.getElementById("root")).render(
  React.createElement(AppErrorBoundary, null, React.createElement(App))
);
globalThis.FamilyTreeBootstrap.complete();
} else {
  globalThis.FamilyTreeBootstrap.fail(
    `Required browser libraries were unavailable: ${missingRuntimeDependencies.join(", ")}. Check the network connection, then retry.`
  );
}
