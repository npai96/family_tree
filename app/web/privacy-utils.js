(function registerFamilyTreePrivacyUtils(globalScope) {
  "use strict";

  function validCoordinate(value, minimum, maximum) {
    if (value == null || String(value).trim() === "") return null;
    const number = Number(value);
    return Number.isFinite(number) && number >= minimum && number <= maximum ? number : null;
  }

  function buildExternalMapUrl(place) {
    if (!place) return null;
    const latitude = validCoordinate(place.lat, -90, 90);
    const longitude = validCoordinate(place.lng, -180, 180);
    const query = latitude != null && longitude != null
      ? `${latitude},${longitude}`
      : [place.place_name, place.country].map((value) => String(value || "").trim()).filter(Boolean).join(", ");
    if (!query) return null;
    return `https://www.google.com/maps/search/?api=1&query=${encodeURIComponent(query)}`;
  }

  const api = Object.freeze({ buildExternalMapUrl });
  globalScope.FamilyTreePrivacyUtils = api;
  if (typeof module !== "undefined" && module.exports) module.exports = api;
})(typeof globalThis !== "undefined" ? globalThis : this);
