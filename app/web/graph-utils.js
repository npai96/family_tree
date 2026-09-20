(function registerFamilyTreeGraphUtils(globalScope) {
  "use strict";

  const DIRECTION_VECTORS = Object.freeze({
    ArrowLeft: Object.freeze({ x: -1, y: 0 }),
    ArrowRight: Object.freeze({ x: 1, y: 0 }),
    ArrowUp: Object.freeze({ x: 0, y: -1 }),
    ArrowDown: Object.freeze({ x: 0, y: 1 }),
  });

  function directionalCandidates(currentId, direction, positions, candidateIds) {
    const vector = DIRECTION_VECTORS[direction];
    const current = positions && positions[currentId];
    if (!vector || !current) return [];

    return candidateIds
      .filter((candidateId) => candidateId !== currentId && positions[candidateId])
      .map((candidateId) => {
        const candidate = positions[candidateId];
        const dx = candidate.x - current.x;
        const dy = candidate.y - current.y;
        const forwardDistance = dx * vector.x + dy * vector.y;
        const perpendicularDistance = Math.abs(dx * vector.y - dy * vector.x);
        return {
          id: candidateId,
          forwardDistance,
          score: forwardDistance + perpendicularDistance * 2,
        };
      })
      .filter((candidate) => candidate.forwardDistance > 0)
      .sort((left, right) => left.score - right.score || left.id.localeCompare(right.id));
  }

  function findDirectionalGraphNode(currentId, direction, positions, edges, nodeIds) {
    if (!DIRECTION_VECTORS[direction] || !positions || !positions[currentId]) return null;
    const allNodeIds = Array.isArray(nodeIds) ? nodeIds : Object.keys(positions);
    const connectedIds = new Set();
    (edges || []).forEach((edge) => {
      if (edge.from_person_id === currentId) connectedIds.add(edge.to_person_id);
      if (edge.to_person_id === currentId) connectedIds.add(edge.from_person_id);
    });

    const connectedCandidates = directionalCandidates(currentId, direction, positions, Array.from(connectedIds));
    if (connectedCandidates.length) return connectedCandidates[0].id;

    const fallbackCandidates = directionalCandidates(currentId, direction, positions, allNodeIds);
    return fallbackCandidates.length ? fallbackCandidates[0].id : null;
  }

  function describeGraphNode(node, connectionCount, selected) {
    if (!node) return "Unknown family member";
    const name = node.full_name || "Unnamed family member";
    const lifeSpan = `${node.birth_date || "birth date unknown"} to ${node.death_date || "present"}`;
    const place = node.birth_place ? `Born in ${node.birth_place}` : "Birthplace unknown";
    const connections = `${Number(connectionCount) || 0} ${(Number(connectionCount) || 0) === 1 ? "relationship" : "relationships"}`;
    return `${name}. ${lifeSpan}. ${place}. ${connections}.${selected ? " Selected." : ""}`;
  }

  const api = Object.freeze({
    describeGraphNode,
    findDirectionalGraphNode,
  });

  globalScope.FamilyTreeGraphUtils = api;
  if (typeof module !== "undefined" && module.exports) module.exports = api;
})(typeof globalThis !== "undefined" ? globalThis : this);
