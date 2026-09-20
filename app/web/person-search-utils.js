(function registerFamilyTreePersonSearchUtils(globalScope) {
  "use strict";

  const DEFAULT_RESULT_LIMIT = 8;

  function normalizeSearchText(value) {
    return String(value || "")
      .normalize("NFKD")
      .replace(/[\u0300-\u036f]/g, "")
      .toLocaleLowerCase()
      .replace(/[^\p{L}\p{N}]+/gu, " ")
      .trim();
  }

  function buildPersonSearchIndex(persons) {
    return (Array.isArray(persons) ? persons : []).map((person) => {
      const name = normalizeSearchText(person?.full_name);
      const metadata = normalizeSearchText([
        person?.birth_place,
        person?.birth_date,
        person?.occupation,
        person?.religion,
      ].filter(Boolean).join(" "));
      return Object.freeze({
        person,
        name,
        nameTokens: name.split(" ").filter(Boolean),
        metadata,
        searchable: `${name} ${metadata}`.trim(),
      });
    });
  }

  function matchRank(record, query, queryTokens) {
    if (!record || !query || !queryTokens.every((token) => record.searchable.includes(token))) return null;
    if (record.name === query) return 0;
    if (record.name.startsWith(query)) return 1;
    if (record.nameTokens.some((token) => token.startsWith(query))) return 2;
    if (record.name.includes(query)) return 3;
    if (record.metadata.startsWith(query)) return 4;
    return 5;
  }

  function searchPersonIndex(index, queryValue, limit = DEFAULT_RESULT_LIMIT) {
    const query = normalizeSearchText(queryValue);
    const boundedLimit = Math.max(0, Math.floor(Number(limit) || 0));
    if (!query || !boundedLimit) return [];
    const queryTokens = query.split(" ").filter(Boolean);

    return (Array.isArray(index) ? index : [])
      .map((record, sourceIndex) => ({
        person: record.person,
        rank: matchRank(record, query, queryTokens),
        sourceIndex,
      }))
      .filter((match) => match.rank !== null)
      .sort((left, right) => (
        left.rank - right.rank
        || String(left.person?.full_name || "").localeCompare(String(right.person?.full_name || ""))
        || left.sourceIndex - right.sourceIndex
      ))
      .slice(0, boundedLimit)
      .map((match) => match.person);
  }

  const api = Object.freeze({
    buildPersonSearchIndex,
    normalizeSearchText,
    searchPersonIndex,
  });

  globalScope.FamilyTreePersonSearchUtils = api;
  if (typeof module !== "undefined" && module.exports) module.exports = api;
})(typeof globalThis !== "undefined" ? globalThis : this);
