"use strict";

const test = require("node:test");
const assert = require("node:assert/strict");

const { buildExternalMapUrl } = require("../app/web/privacy-utils.js");


test("external map URLs prefer validated coordinates", () => {
  assert.equal(
    buildExternalMapUrl({ lat: 17.385, lng: 78.4867, place_name: "Hyderabad" }),
    "https://www.google.com/maps/search/?api=1&query=17.385%2C78.4867"
  );
});


test("external map URLs fall back to an encoded place and country", () => {
  assert.equal(
    buildExternalMapUrl({ lat: 200, lng: 78, place_name: "New Delhi & NCR", country: "India" }),
    "https://www.google.com/maps/search/?api=1&query=New%20Delhi%20%26%20NCR%2C%20India"
  );
  assert.equal(
    buildExternalMapUrl({ lat: null, lng: null, place_name: "Chennai", country: "India" }),
    "https://www.google.com/maps/search/?api=1&query=Chennai%2C%20India"
  );
});


test("external map URLs reject missing location data", () => {
  assert.equal(buildExternalMapUrl(null), null);
  assert.equal(buildExternalMapUrl({}), null);
  assert.equal(buildExternalMapUrl({ lat: "not-a-number", lng: 10 }), null);
});
