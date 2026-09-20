(function registerFamilyTreeErrorUtils(globalScope) {
  "use strict";

  const LOCATION_PREFIXES = new Set(["body", "query", "path", "header", "cookie"]);

  function readableLocation(location) {
    const parts = Array.isArray(location)
      ? location.filter((part, index) => !(index === 0 && LOCATION_PREFIXES.has(String(part))))
      : [];
    const label = parts
      .map((part) => String(part).replaceAll("_", " "))
      .join(" → ");
    return label ? `${label.charAt(0).toUpperCase()}${label.slice(1)}` : "Request";
  }

  function formatApiErrorDetail(detail, fallback = "Request failed") {
    if (typeof detail === "string" && detail.trim()) return detail.trim();
    if (Array.isArray(detail) && detail.length) {
      const visibleIssues = detail.slice(0, 3).map((issue) => {
        const message = typeof issue?.msg === "string" && issue.msg.trim()
          ? issue.msg.trim()
          : "Invalid value";
        return `${readableLocation(issue?.loc)}: ${message}`;
      });
      if (detail.length > visibleIssues.length) {
        visibleIssues.push(`and ${detail.length - visibleIssues.length} more validation issue${detail.length - visibleIssues.length === 1 ? "" : "s"}`);
      }
      return visibleIssues.join("; ");
    }
    if (detail && typeof detail.message === "string" && detail.message.trim()) {
      return detail.message.trim();
    }
    return fallback;
  }

  const api = Object.freeze({ formatApiErrorDetail });
  globalScope.FamilyTreeErrorUtils = api;
  if (typeof module !== "undefined" && module.exports) module.exports = api;
})(typeof globalThis !== "undefined" ? globalThis : this);
