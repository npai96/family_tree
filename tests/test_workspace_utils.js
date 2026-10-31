"use strict";

const test = require("node:test");
const assert = require("node:assert/strict");
const { pageFromHash, filterPeople, initials } = require("../app/web/workspace.js");

test("workspace routes accept only known destinations", () => {
  for (const name of ["tree", "people", "places", "circle"]) {
    assert.equal(pageFromHash(`#${name}`), name);
  }
  assert.equal(pageFromHash("#home"), "tree");
  assert.equal(pageFromHash("#access"), "circle");
  for (const value of [undefined, "", "#", "#unknown", "#people/secret", "#__proto__", "#<script>"]) {
    assert.equal(pageFromHash(value), "tree");
  }
});

test("directory searches identity and public profile metadata, not sensitive notes", () => {
  const people = [
    { id: "a", full_name: "Meera Rao", occupation: "Teacher", birth_place: "Mangaluru", medical_notes: "private phrase" },
    { id: "b", full_name: "Tara Rao", occupation: null, birth_place: null },
  ];
  assert.deepEqual(filterPeople(people, "  TEACHER ").map((person) => person.id), ["a"]);
  assert.deepEqual(filterPeople(people, "mangaluru").map((person) => person.id), ["a"]);
  assert.deepEqual(filterPeople(people, "private phrase"), []);
  assert.deepEqual(filterPeople(people, ""), people);
});

test("initials tolerate absent and international names", () => {
  assert.equal(initials(undefined), "?");
  assert.equal(initials("  Meera   Rao "), "MR");
  assert.equal(initials("李 明"), "李明");
});
