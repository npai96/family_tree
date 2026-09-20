"use strict";

const test = require("node:test");
const assert = require("node:assert/strict");

const {
  buildPersonSearchIndex,
  normalizeSearchText,
  searchPersonIndex,
} = require("../app/web/person-search-utils.js");

const PEOPLE = [
  { id: "1", full_name: "Asha Rao", birth_place: "Hyderabad", birth_date: "1945-03-02", occupation: "Teacher" },
  { id: "2", full_name: "Ravi Ashar", birth_place: "Pune", birth_date: "1968-01-01", occupation: "Engineer" },
  { id: "3", full_name: "Nīla Shah", birth_place: "Ahmedabad", birth_date: "1972-09-14", occupation: "Doctor" },
  { id: "4", full_name: "Asha Mehta", birth_place: "Delhi", birth_date: "1980-06-12", occupation: "Artist" },
];

test("search normalization is case, punctuation, and diacritic insensitive", () => {
  assert.equal(normalizeSearchText("  NĪLA—SHAH "), "nila shah");
  const index = buildPersonSearchIndex(PEOPLE);
  assert.deepEqual(searchPersonIndex(index, "nila", 8).map((person) => person.id), ["3"]);
});

test("name matches outrank metadata matches and multiple tokens can span fields", () => {
  const index = buildPersonSearchIndex(PEOPLE);
  assert.deepEqual(searchPersonIndex(index, "asha", 8).map((person) => person.id), ["4", "1", "2"]);
  assert.deepEqual(searchPersonIndex(index, "asha delhi", 8).map((person) => person.id), ["4"]);
  assert.deepEqual(searchPersonIndex(index, "teacher 1945", 8).map((person) => person.id), ["1"]);
});

test("search results stay bounded and empty queries do no work", () => {
  const manyPeople = Array.from({ length: 500 }, (_, index) => ({
    id: String(index),
    full_name: `Person ${String(index).padStart(3, "0")}`,
  }));
  const searchIndex = buildPersonSearchIndex(manyPeople);

  assert.equal(searchPersonIndex(searchIndex, "person", 8).length, 8);
  assert.deepEqual(searchPersonIndex(searchIndex, "", 8), []);
  assert.deepEqual(searchPersonIndex(searchIndex, "person", 0), []);
});
