"use strict";

const test = require("node:test");
const assert = require("node:assert/strict");

const { formatApiErrorDetail } = require("../app/web/error-utils.js");


test("API error formatter preserves human-readable string details", () => {
  assert.equal(formatApiErrorDetail("Person not found", "Fallback"), "Person not found");
});


test("API error formatter turns FastAPI validation arrays into field messages", () => {
  assert.equal(
    formatApiErrorDetail([
      { loc: ["body", "full_name"], msg: "String should have at least 1 character", input: "" },
      { loc: ["query", "depth"], msg: "Input should be less than or equal to 10", input: 99 },
    ]),
    "Full name: String should have at least 1 character; Depth: Input should be less than or equal to 10"
  );
});


test("API error formatter bounds noisy validation responses and has a safe fallback", () => {
  const issues = Array.from({ length: 5 }, (_, index) => ({ loc: ["body", `field_${index}`], msg: "Invalid" }));
  assert.equal(
    formatApiErrorDetail(issues),
    "Field 0: Invalid; Field 1: Invalid; Field 2: Invalid; and 2 more validation issues"
  );
  assert.equal(formatApiErrorDetail({ unexpected: true }, "Could not save"), "Could not save");
});
